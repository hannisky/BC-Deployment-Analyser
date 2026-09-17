"""
evaluation/evaluate.py — Phase 4: measure documentation quality with LLM-as-judge + deterministic checks.

For every case in evaluation_dataset.json the target agent is run with the case input supplied
inline (no GitHub access needed — the same code path the Foundry workflow uses), and the output
is scored with:

    Built-in evaluators (azure-ai-evaluation, 1–5):
      coherence        is the documentation logically structured?
      fluency          is the Swedish well-formed and readable?
      groundedness     does every statement follow from the analysis / change data (the context)?
      task_adherence   did the agent do what the instructions + query asked?

    Deterministic evaluators (this file, 1–5):
      format_adherence heading structure, forbidden phrases, JSON verdict present, Swedish, ...
      coverage         share of `must_mention` facts present in the output

Results are written to evaluation/results/ (JSON + Markdown) and the script exits non-zero when
any metric mean is below the threshold — that is the CI quality gate.

Usage:
    python evaluation/evaluate.py                          # all cases, both agents
    python evaluation/evaluate.py --agent code_analyst     # one agent
    python evaluation/evaluate.py --case CA-01 --verbose   # one case, print the response
    python evaluation/evaluate.py --offline                # score the reference answers (pipeline self-test, no Azure)
    python evaluation/evaluate.py --export-portal          # write eval_portal.jsonl for the portal UI
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import config  # noqa: E402

DATASET_FILE = config.EVALUATION_DIR / "evaluation_dataset.json"
PORTAL_FILE = config.EVALUATION_DIR / "eval_portal.jsonl"
RESULTS_DIR = config.EVALUATION_DIR / "results"

_SWEDISH_MARKERS = re.compile(
    r"\b(och|för|när|som|med|inte|till|tills|från|används|skapas|sätts|fältet|sidan|tabellen|på|är|av|att|"
    r"en|ett|nytt|ny|vid|visas|endast|samt|har|kan|ska|blir|där|även|eller|utan|över|under)\b",
    re.IGNORECASE,
)
_ENGLISH_MARKERS = re.compile(r"\b(the|this feature|is used|when the|creates|allows|which|with the|from the)\b")
_JSON_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


# =============================================================================================
# Deterministic evaluators (same call signature style as the SDK evaluators)
# =============================================================================================
class FormatAdherenceEvaluator:
    """Checks the structural contract the pipeline relies on. Score = 1 + 4 * passed/total."""

    def __call__(self, *, case: dict, response: str) -> dict:
        exp = case["expected"]
        checks: dict[str, bool] = {}
        text = response.strip()

        if case["agent"] == "code_analyst":
            checks["starts_with_h3"] = text.startswith(exp.get("starts_with", "### "))
            checks["single_h3"] = len(re.findall(r"(?m)^### ", text)) == 1
            checks["has_h4"] = bool(re.search(r"(?m)^#### ", text))
            for heading in exp.get("required_headings", []):
                checks[f"heading:{heading}"] = bool(re.search(r"(?mi)^#### .*" + re.escape(heading), text))
            if "Övriga anpassningar" in text:
                h4s = re.findall(r"(?m)^#### (.*)$", text)
                checks["ovriga_last"] = bool(h4s) and h4s[-1].strip().startswith("Övriga anpassningar")
        else:
            m = _JSON_BLOCK_RE.search(text)
            checks["json_block"] = bool(m)
            data = {}
            if m:
                try:
                    data = json.loads(m.group(1))
                except json.JSONDecodeError:
                    checks["json_parses"] = False
            if data:
                checks["json_parses"] = True
                checks["impact_expected"] = str(data.get("impact", "")).lower() == exp["impact"]
                checks["full_regen_expected"] = bool(data.get("requires_full_regeneration")) == exp["requires_full_regeneration"]
                if exp.get("version_after"):
                    checks["version_after"] = data.get("version_after") == exp["version_after"]
            tail = text[m.end():] if m else text
            checks["changelog_h4"] = tail.strip().startswith(exp.get("changelog_heading_prefix", "#### "))

        for phrase in exp.get("forbidden", []):
            checks[f"forbidden:{phrase[:20]}"] = phrase not in text
        if exp.get("language") == "sv":
            # Judge the prose only — the change tracker's JSON verdict has English keys by design
            prose = text
            m_json = _JSON_BLOCK_RE.search(text)
            if m_json:
                prose = text[m_json.end():]
            sv, en = len(_SWEDISH_MARKERS.findall(prose)), len(_ENGLISH_MARKERS.findall(prose))
            checks["swedish"] = sv >= 2 and sv > en

        passed = sum(checks.values())
        score = 1 + 4 * passed / max(len(checks), 1)
        return {"format_adherence": round(score, 2), "format_adherence_failed": [k for k, v in checks.items() if not v]}


class CoverageEvaluator:
    """Share of `must_mention` facts present in the response (case-insensitive)."""

    def __call__(self, *, case: dict, response: str) -> dict:
        terms = case["expected"].get("must_mention", [])
        low = response.lower()
        missing = [t for t in terms if t.lower() not in low]
        ratio = 1 - len(missing) / len(terms) if terms else 1.0
        return {"coverage": round(1 + 4 * ratio, 2), "coverage_missing": missing}


# =============================================================================================
# Targets — how each case is sent to the agent
# =============================================================================================
def build_query(case: dict) -> str:
    """The user message the agent receives (also used as the evaluators' `query`)."""
    inp = case["input"]
    if case["agent"] == "code_analyst":
        if inp.get("mode") == "update":
            return (
                "MODE: update\nThe analysis JSON is provided below — do NOT call analyze_repo. Return the complete updated "
                "Section 3 entry (### heading and all #### sections). Keep unchanged text as is.\n\n"
                "=== CHANGE SUMMARY (from bc-change-tracker) ===\n" + inp["change_summary"] + "\n\n"
                "=== CURRENT DOCUMENTATION ===\n" + inp["current_doc"] + "\n\n"
                "=== ANALYSIS ===\n" + json.dumps(inp["analysis"], ensure_ascii=False)
            )
        return (
            "MODE: full\nThe analysis JSON is provided below — do NOT call analyze_repo. Return the complete Section 3 "
            "entry in Swedish starting at the ### heading.\n\n=== ANALYSIS ===\n" + json.dumps(inp["analysis"], ensure_ascii=False)
        )
    return (
        "The change data JSON is provided below — do NOT call get_repo_changes. Return Part 1 (JSON verdict) and "
        "Part 2 (Swedish changelog).\n\n=== CHANGES ===\n" + json.dumps(inp["changes"], ensure_ascii=False)
    )


def build_context(case: dict) -> str:
    inp = case["input"]
    if case["agent"] == "code_analyst":
        ctx = json.dumps(inp["analysis"], ensure_ascii=False)
        if inp.get("mode") == "update":
            ctx = "CURRENT DOCUMENTATION:\n" + inp["current_doc"] + "\n\nCHANGE SUMMARY:\n" + inp["change_summary"] + "\n\nANALYSIS:\n" + ctx
        return ctx
    return json.dumps(inp["changes"], ensure_ascii=False)


def run_target(case: dict, agents: dict, offline: bool) -> tuple[str, dict]:
    if offline:
        return case["expected"]["reference_response_sv"], {"tokens_in": 0, "tokens_out": 0, "duration_s": 0.0}
    agent = agents[case["agent"]]
    started = time.time()
    result = agent.run(build_query(case), verbose=False)
    return result.text, {"tokens_in": result.input_tokens, "tokens_out": result.output_tokens, "duration_s": round(time.time() - started, 1)}


# =============================================================================================
# Judge model
# =============================================================================================
def judge_model_config() -> tuple[dict, object | None]:
    import os

    cfg = {
        "azure_endpoint": config.foundry_account_endpoint(),
        "azure_deployment": os.getenv("EVAL_MODEL_DEPLOYMENT_NAME", config.MODEL_DEPLOYMENT_NAME),
        "api_version": os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
    }
    api_key = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
    if api_key:
        cfg["api_key"] = api_key
        return cfg, None
    from azure.identity import DefaultAzureCredential

    return cfg, DefaultAzureCredential()


def build_llm_evaluators() -> dict:
    from azure.ai.evaluation import CoherenceEvaluator, FluencyEvaluator, GroundednessEvaluator, TaskAdherenceEvaluator

    model_config, credential = judge_model_config()
    kwargs = {"credential": credential} if credential else {}
    return {
        "coherence": CoherenceEvaluator(model_config, **kwargs),
        "fluency": FluencyEvaluator(model_config, **kwargs),
        "groundedness": GroundednessEvaluator(model_config, **kwargs),
        "task_adherence": TaskAdherenceEvaluator(model_config, **kwargs),
    }


def score_case(case: dict, query: str, response: str, llm_evals: dict | None) -> dict:
    scores: dict = {}
    scores.update(FormatAdherenceEvaluator()(case=case, response=response))
    scores.update(CoverageEvaluator()(case=case, response=response))
    if not llm_evals:
        return scores
    context = build_context(case)
    calls = {
        "coherence": lambda e: e(query=query, response=response),
        "fluency": lambda e: e(response=response),
        "groundedness": lambda e: e(query=query, context=context, response=response),
        "task_adherence": lambda e: e(query=query, response=response),
    }
    for name, evaluator in llm_evals.items():
        try:
            out = calls[name](evaluator)
            scores[name] = out.get(name, out.get(f"{name}_score"))
            reason = out.get(f"{name}_reason")
            if reason:
                scores[f"{name}_reason"] = str(reason)[:400]
        except Exception as exc:
            scores[name] = None
            scores[f"{name}_error"] = str(exc)[:200]
    return scores


# =============================================================================================
# Reporting
# =============================================================================================
METRICS = ["coherence", "fluency", "groundedness", "task_adherence", "format_adherence", "coverage"]


def aggregate(rows: list[dict]) -> dict:
    agg = {}
    for metric in METRICS:
        values = [r["scores"].get(metric) for r in rows if isinstance(r["scores"].get(metric), (int, float))]
        agg[metric] = round(statistics.mean(values), 2) if values else None
    return agg


def render_markdown(rows: list[dict], agg: dict, threshold: float, passed: bool, offline: bool) -> str:
    lines = [
        f"# Evaluation run {config.utc_now_iso()}",
        "",
        f"Mode: {'offline (reference answers)' if offline else 'live agents'} · Cases: {len(rows)} · Threshold: {threshold} · "
        f"Gate: {'✅ PASSED' if passed else '❌ FAILED'}",
        "",
        "| Metric | Mean |",
        "|---|---:|",
    ]
    for metric in METRICS:
        v = agg.get(metric)
        flag = "" if v is None else (" ⚠️" if v < threshold else "")
        lines.append(f"| {metric} | {v if v is not None else '–'}{flag} |")
    lines += ["", "## Per case", "", "| Case | Agent | " + " | ".join(METRICS) + " | Failed checks | Missing facts |", "|---|---|" + "---:|" * len(METRICS) + "---|---|"]
    for r in rows:
        s = r["scores"]
        vals = " | ".join(str(s.get(m)) if s.get(m) is not None else "–" for m in METRICS)
        lines.append(f"| {r['id']} | {r['agent']} | {vals} | {', '.join(s.get('format_adherence_failed', [])) or '–'} | {', '.join(s.get('coverage_missing', [])) or '–'} |")
    lines.append("")
    return "\n".join(lines)


def export_portal_dataset(cases: list[dict]) -> None:
    """One JSONL row per code_analyst case for Foundry portal evaluations (query/context/ground_truth)."""
    with open(PORTAL_FILE, "w", encoding="utf-8") as f:
        for case in cases:
            if case["agent"] != "code_analyst":
                continue
            row = {"query": build_query(case), "context": build_context(case), "ground_truth": case["expected"]["reference_response_sv"]}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"[DONE] Wrote {PORTAL_FILE}")


# =============================================================================================
# Main
# =============================================================================================
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--agent", choices=["code_analyst", "change_tracker", "all"], default="all")
    parser.add_argument("--case", help="Run a single case id, e.g. CA-01")
    parser.add_argument("--offline", action="store_true", help="Score the reference answers instead of calling agents (no Azure)")
    parser.add_argument("--no-llm-judge", action="store_true", help="Deterministic evaluators only")
    parser.add_argument("--threshold", type=float, default=3.5, help="Minimum mean score per metric for the gate")
    parser.add_argument("--export-portal", action="store_true", help="Write eval_portal.jsonl and exit")
    parser.add_argument("--verbose", action="store_true", help="Print each agent response")
    args = parser.parse_args()

    dataset = config.load_json(DATASET_FILE)
    cases = [c for c in dataset["cases"] if (args.agent == "all" or c["agent"] == args.agent) and (not args.case or c["id"] == args.case)]
    if args.export_portal:
        export_portal_dataset(dataset["cases"])
        return
    if not cases:
        sys.exit("No cases match the filter")

    use_llm = not args.no_llm_judge and not (args.offline and not config.PROJECT_CONNECTION_STRING)
    agents: dict = {}
    if not args.offline:
        if not config.PROJECT_CONNECTION_STRING:
            sys.exit("❌ PROJECT_CONNECTION_STRING not set. Run setup/deploy.sh first (or use --offline).")
        from agents.agents import ChangeTrackerAgent, CodeAnalystAgent

        print("=== Agents ===")
        analyst = CodeAnalystAgent().ensure()
        agents = {"code_analyst": analyst, "change_tracker": ChangeTrackerAgent(client=analyst.client).ensure()}

    llm_evals = None
    if use_llm:
        try:
            llm_evals = build_llm_evaluators()
            print("=== Judge: coherence, fluency, groundedness, task_adherence ===")
        except Exception as exc:
            print(f"[WARN] LLM judge unavailable ({exc}) — deterministic evaluators only")

    rows = []
    for case in cases:
        print(f"\n[{case['id']}] {case['title']}")
        query = build_query(case)
        try:
            response, usage = run_target(case, agents, args.offline)
        except Exception as exc:
            print(f"  ❌ target failed: {exc}")
            rows.append({"id": case["id"], "agent": case["agent"], "title": case["title"], "scores": {"format_adherence": 1.0, "coverage": 1.0, "error": str(exc)}, "usage": {}})
            continue
        if args.verbose:
            print("-" * 60 + "\n" + response + "\n" + "-" * 60)
        scores = score_case(case, query, response, llm_evals)
        rows.append({"id": case["id"], "agent": case["agent"], "title": case["title"], "scores": scores, "usage": usage, "response": response})
        print("  " + ", ".join(f"{m}={scores.get(m)}" for m in METRICS if scores.get(m) is not None))
        if scores.get("format_adherence_failed"):
            print(f"  failed checks: {scores['format_adherence_failed']}")
        if scores.get("coverage_missing"):
            print(f"  missing facts: {scores['coverage_missing']}")

    agg = aggregate(rows)
    gate_metrics = [m for m in METRICS if agg.get(m) is not None]
    passed = all(agg[m] >= args.threshold for m in gate_metrics) and not any("error" in r["scores"] for r in rows)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    config.write_json_atomic(RESULTS_DIR / f"eval_{stamp}.json", {"run_at": config.utc_now_iso(), "offline": args.offline, "threshold": args.threshold, "passed": passed, "metrics": agg, "rows": rows})
    md = render_markdown(rows, agg, args.threshold, passed, args.offline)
    config.write_text_atomic(RESULTS_DIR / f"eval_{stamp}.md", md)
    config.write_text_atomic(RESULTS_DIR / "latest.md", md)

    print("\n" + "=" * 70)
    print("EVALUATION SUMMARY")
    print("=" * 70)
    for metric in METRICS:
        if agg.get(metric) is not None:
            print(f"  {metric:18} {agg[metric]:>5}  {'⚠️ below threshold' if agg[metric] < args.threshold else ''}")
    print(f"\n  Quality gate (>= {args.threshold}): {'✅ PASSED' if passed else '❌ FAILED'}")
    print(f"  Results: {RESULTS_DIR / f'eval_{stamp}.md'}")
    print("=" * 70)

    if agents:
        agents["code_analyst"].client.close()
    if not passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
