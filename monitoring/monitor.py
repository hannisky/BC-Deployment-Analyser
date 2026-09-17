"""
monitoring/monitor.py — Phase 3: enable GenAI tracing and verify traces reach Application Insights.

What gets traced:
  * every agent run (model call, tokens, latency) — automatically via AIProjectInstrumentor
  * every FunctionTool call (analyze_repo / get_repo_changes) with inputs/outputs
  * our own business spans: bc.pipeline.run → bc.pipeline.customer → bc.pipeline.repo →
    bc.agent.* carrying KPIs (mode, impact, tokens, duration) as `bc.*` attributes

Usage:
    python monitoring/monitor.py                       # traced run on the bundled sample analysis (no GitHub needed)
    python monitoring/monitor.py --org X --repo Y      # traced run against a real repository (needs GITHUB_TOKEN)

IMPORTANT: tracing env vars must be set BEFORE the Foundry SDK is imported — common.tracing does that.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import config  # noqa: E402
from common import tracing  # noqa: E402


def run_traced_sample(analyst) -> None:
    dataset = config.load_json(config.EVALUATION_DIR / "evaluation_dataset.json")
    case = next(c for c in dataset["cases"] if c["agent"] == "code_analyst")
    print(f"\n=== Traced run: bc-code-analyst on sample case {case['id']} ({case['title']}) ===")
    with tracing.pipeline_span("bc.pipeline.repo", customer="Monitoring-demo", repo=case["id"], mode="sample") as span:
        started = time.time()
        with tracing.pipeline_span("bc.agent.code_analyst", repo=case["id"], mode="full"):
            result = analyst.document_from_analysis(json.dumps(case["input"]["analysis"], ensure_ascii=False))
        tracing.record_kpis(span, tokens_in=result.input_tokens, tokens_out=result.output_tokens, duration_s=round(time.time() - started, 1))
    print(result.text[:600] + ("..." if len(result.text) > 600 else ""))
    print(f"\n  tokens in/out: {result.input_tokens}/{result.output_tokens}")


def run_traced_live(analyst, org: str, repo: str, branch: str | None) -> None:
    print(f"\n=== Traced run: bc-code-analyst on {org}/{repo} (live GitHub) ===")
    with tracing.pipeline_span("bc.pipeline.repo", customer="Monitoring-demo", repo=repo, org=org, mode="full") as span:
        started = time.time()
        with tracing.pipeline_span("bc.agent.code_analyst", repo=repo, mode="full"):
            result = analyst.document(org, repo, branch)
        tracing.record_kpis(span, tokens_in=result.input_tokens, tokens_out=result.output_tokens, duration_s=round(time.time() - started, 1), tool_calls=result.tool_calls)
    print(result.text[:600] + ("..." if len(result.text) > 600 else ""))
    print(f"\n  tokens in/out: {result.input_tokens}/{result.output_tokens}, tool calls: {result.tool_calls}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--org")
    parser.add_argument("--repo")
    parser.add_argument("--branch")
    parser.add_argument("--live-metrics", action="store_true", help="Also stream Live Metrics to App Insights")
    args = parser.parse_args()

    if not config.PROJECT_CONNECTION_STRING:
        sys.exit("❌ PROJECT_CONNECTION_STRING not set. Run setup/deploy.sh first!")
    if not config.APPINSIGHTS_CONNECTION_STRING:
        sys.exit("❌ APPLICATIONINSIGHTS_CONNECTION_STRING not set — re-run setup/deploy.sh or connect App Insights in the portal")

    print("=== Setting up tracing ===")
    if not tracing.setup_tracing(live_metrics=args.live_metrics):
        sys.exit(1)

    from agents.agents import CodeAnalystAgent  # after tracing setup

    analyst = CodeAnalystAgent().ensure()
    with tracing.pipeline_span("bc.pipeline.run", customers="Monitoring-demo"):
        if args.org and args.repo:
            run_traced_live(analyst, args.org, args.repo, args.branch)
        else:
            run_traced_sample(analyst)
    analyst.client.close()

    print("\n=== Flushing telemetry ===")
    tracing.flush()
    print("⏳ Traces typically appear within 1–3 minutes.")
    print("   Foundry portal  → your project → Agents → bc-code-analyst → Traces / Monitor")
    print("   Azure portal    → Application Insights → Investigate → Transaction search / Agents (preview)")
    print("   Log Analytics   → run the queries in monitoring/queries.kql (filter on customDimensions['bc.*'])")
    print("\n🎉 Monitoring is active.")


if __name__ == "__main__":
    main()
