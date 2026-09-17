"""
orchestration/run_pipeline.py — Phase 5: the production pipeline that keeps customer documentation
in sync with GitHub.

Per enabled customer, per active AL repository:

    head SHA changed since last run?
        no  → skip (documentation is current)
        yes → bc-change-tracker  (what changed? impact verdict + Swedish changelog)
                 impact none   → record SHA, nothing to rewrite
                 impact minor  → bc-code-analyst in UPDATE mode (current doc + change summary)
                 impact major  → bc-code-analyst in FULL mode (regenerate the section)
    first run / --force → bc-code-analyst in FULL mode

Output per customer (output/{Customer}/):
    {Customer}_{repo}.md        one document per PTE app (Anpassningar + Ändringshistorik)
    README.md                   customer index: apps, versions in Git vs BC, links
    .doc_state.json             per-repo state: last documented SHA, version, cost
    {Customer}_bc_{env}.md      from discovery/discover_bc_extensions.py (read for the index)

Usage:
    python orchestration/run_pipeline.py                       # all customers
    python orchestration/run_pipeline.py --customer "Acme AB"  # one customer
    python orchestration/run_pipeline.py --repo Acme-PTE       # one repository
    python orchestration/run_pipeline.py --discover            # run GitHub + BC discovery first
    python orchestration/run_pipeline.py --force               # regenerate everything
    python orchestration/run_pipeline.py --dry-run             # decide modes, call no agents
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import config  # noqa: E402
from common import tracing  # noqa: E402

SECTION_START, SECTION_END = "<!-- bc-analyzer:section:start -->", "<!-- bc-analyzer:section:end -->"
HISTORY_START, HISTORY_END = "<!-- bc-analyzer:history:start -->", "<!-- bc-analyzer:history:end -->"
MAX_HISTORY_ENTRIES = 30


# =============================================================================================
# State
# =============================================================================================
def load_state(out_dir: Path, customer_name: str) -> dict:
    state = config.load_json(out_dir / config.DOC_STATE_FILENAME, default=None)
    if not state:
        state = {"customer": customer_name, "updated_at": None, "repos": {}}
    state.setdefault("repos", {})
    return state


def save_state(out_dir: Path, state: dict) -> None:
    state["updated_at"] = config.utc_now_iso()
    config.write_json_atomic(out_dir / config.DOC_STATE_FILENAME, state)


# =============================================================================================
# Document assembly (deterministic — the agent only produces the ### section)
# =============================================================================================
def _between(text: str, start: str, end: str) -> str | None:
    if start in text and end in text:
        return text.split(start, 1)[1].split(end, 1)[0].strip()
    return None


def read_existing_doc(path: Path) -> tuple[str | None, str | None, str | None]:
    """Returns (full_text, current_section, history_block) or (None, None, None)."""
    if not path.exists():
        return None, None, None
    text = path.read_text(encoding="utf-8")
    return text, _between(text, SECTION_START, SECTION_END), _between(text, HISTORY_START, HISTORY_END)


def clean_section(text: str) -> str:
    """Strip accidental code fences / preamble so the section starts at the ### heading."""
    text = text.strip()
    text = re.sub(r"^```(?:markdown|md)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    idx = text.find("### ")
    return text[idx:].strip() if idx > 0 else text


def prepend_history(existing: str | None, entry: str | None) -> str:
    entries = []
    if entry and entry.strip():
        entries.append(entry.strip())
    if existing:
        entries.append(existing.strip())
    text = "\n\n".join(e for e in entries if e)
    # Cap the number of #### entries so the file does not grow without bound
    parts = re.split(r"(?m)^(?=#### )", text)
    kept = [p for p in parts if p.strip()][:MAX_HISTORY_ENTRIES]
    return "\n".join(kept).strip()


def render_repo_doc(customer: dict, repo: dict, app: dict, head_sha: str, section: str, history: str, agent_label: str) -> str:
    app_name = repo.get("custom_label") or app.get("name") or repo["name"]
    lines = [
        f"# {app_name} – {customer['name']}",
        "",
        f"> **Automatiskt genererad dokumentation.** Källa: [{customer['org']}/{repo['name']}]({repo['url']}) "
        f"(branch `{repo.get('default_branch', 'main')}`, commit `{head_sha[:7]}`) · App-version i Git: **{app.get('version') or '–'}** · "
        f"Utgivare: {app.get('publisher') or '–'} · Senast uppdaterad: {config.today_iso()} · Genererad av `{agent_label}` i Microsoft Foundry. "
        f"Versionsvalidering mot Business Central finns i kundens miljörapport.",
        "",
        "## Anpassningar",
        "",
        SECTION_START,
        section.strip(),
        SECTION_END,
        "",
        "## Ändringshistorik",
        "",
        HISTORY_START,
        history.strip() if history.strip() else f"#### {config.today_iso()} – första dokumentation\n- Dokumentationen genererades för första gången från commit `{head_sha[:7]}`.",
        HISTORY_END,
        "",
    ]
    return "\n".join(lines)


def render_customer_index(customer: dict, state: dict, out_dir: Path, bc_reports: list[dict]) -> str:
    slug = config.slugify(customer["name"])
    bc_versions: dict[str, dict] = {}  # app id/name → {env: (version, status)}
    for report in bc_reports:
        env = report["environment"]
        for row in report.get("own_apps", []):
            key = row.get("id") or row.get("displayName")
            bc_versions.setdefault(key, {})[env] = (row["version"], row["status"])

    envs = [r["environment"] for r in bc_reports]
    header = ["App", "GitHub-repo", "Version (Git)"] + [f"Version (BC {e})" for e in envs] + ["Dokumentation", "Senast dokumenterad"]
    lines = [
        f"# Implementationsdokumentation {customer['name']}",
        "",
        f"> Automatiskt underhållen av BC Deployment Analyzer. Senast körd: {config.today_iso()}. "
        "Varje app har ett eget dokument med funktionsbeskrivning (Anpassningar) och ändringshistorik. "
        "Installerade tredjepartstillägg och versionsvalidering per Business Central-miljö finns i miljörapporterna nedan.",
        "",
        "## Egna anpassningar (PTE)",
        "",
        "| " + " | ".join(header) + " |",
        "|" + "---|" * len(header),
    ]
    status_icon = {"match": "✅", "git_ahead": "⚠️", "bc_ahead": "⚠️", "unknown": "❔", "no_repo": "❓"}
    for repo in sorted(customer.get("repos", []), key=lambda r: r["name"].lower()):
        if not repo.get("active", True):
            continue
        st = state["repos"].get(repo["name"], {})
        app = repo.get("app") or {}
        name = repo.get("custom_label") or app.get("name") or repo["name"]
        row = [name, f"[{repo['name']}]({repo['url']})", app.get("version") or "–"]
        for env in envs:
            hit = bc_versions.get(app.get("id"), {}).get(env) or bc_versions.get(app.get("name"), {}).get(env)
            row.append(f"{status_icon.get(hit[1], '')} {hit[0]}" if hit else "❔ ej publicerad")
        doc_file = st.get("doc_file")
        row.append(f"[{doc_file}](./{doc_file})" if doc_file else ("–" if app else "inget AL-projekt"))
        row.append((st.get("documented_at") or "–")[:10])
        lines.append("| " + " | ".join(row) + " |")

    inactive = [r for r in customer.get("repos", []) if not r.get("active", True)]
    if inactive:
        lines += ["", "Inaktiva/arkiverade repos: " + ", ".join(f"`{r['name']}`" for r in inactive)]

    lines += ["", "## Business Central-miljöer", ""]
    if bc_reports:
        for report in bc_reports:
            c = report.get("counts", {})
            fname = f"{slug}_bc_{config.slugify(report['environment'])}.md"
            lines.append(
                f"- [{report['environment']}](./{fname}) – {c.get('third_party', 0)} tredjepartstillägg, "
                f"{c.get('own_published', 0)} egna appar ({c.get('match', 0)} ✅, {c.get('mismatch', 0)} ⚠️, {c.get('no_repo', 0)} ❓) · "
                f"inventerad {str(report.get('queried_at', ''))[:10]}"
            )
    else:
        lines.append("- Ingen miljörapport hittades – kör `discovery/discover_bc_extensions.py`.")

    recent = [
        (st.get("documented_at", ""), repo, st)
        for repo, st in state["repos"].items()
        if st.get("last_summary_sv")
    ]
    if recent:
        lines += ["", "## Senaste ändringar", ""]
        for documented_at, repo, st in sorted(recent, reverse=True)[:10]:
            lines.append(f"- **{documented_at[:10]} – {repo}** (v{st.get('app_version') or '–'}): {st['last_summary_sv']}")
    lines.append("")
    return "\n".join(lines)


def load_bc_reports(out_dir: Path, slug: str) -> list[dict]:
    reports = []
    for path in sorted(out_dir.glob(f"{slug}_bc_*.json")):
        data = config.load_json(path)
        if data:
            reports.append(data)
    return reports


# =============================================================================================
# Pipeline
# =============================================================================================
class Stats:
    def __init__(self):
        self.repos = self.documented = self.updated = self.skipped = self.failed = self.no_app = 0
        self.tokens_in = self.tokens_out = 0
        self.failures: list[str] = []

    def summary(self) -> str:
        return (
            f"repos={self.repos} documented={self.documented} updated={self.updated} skipped={self.skipped} "
            f"no_app={self.no_app} failed={self.failed} tokens_in={self.tokens_in} tokens_out={self.tokens_out}"
        )


def read_app_manifest(gh, org: str, repo_name: str, sha: str, known_path: str | None) -> dict:
    from common.github_client import find_app_json_path

    try:
        path = known_path or find_app_json_path(gh.get_tree(org, repo_name, sha))
        if not path:
            return {}
        return json.loads(gh.get_file(org, repo_name, path, ref=sha))
    except Exception:
        return {}


def process_repo(customer: dict, repo: dict, state: dict, out_dir: Path, analyst, tracker, gh, stats: Stats, force: bool, dry_run: bool) -> None:
    org, name, branch = customer["org"], repo["name"], repo.get("default_branch", "main")
    slug = config.slugify(customer["name"])
    doc_path = out_dir / f"{slug}_{config.slugify(name)}.md"
    repo_state = state["repos"].get(name, {})

    with tracing.pipeline_span("bc.pipeline.repo", customer=customer["name"], repo=name, org=org) as span:
        stats.repos += 1
        head_sha = gh.get_branch_head_sha(org, name, branch)
        app_meta = repo.get("app") or {}
        app = read_app_manifest(gh, org, name, head_sha, app_meta.get("path")) or app_meta
        if not app:
            print(f"  [SKIP] {name}: no app.json (not an AL project)")
            stats.no_app += 1
            tracing.record_kpis(span, mode="no_app")
            return

        existing_text, existing_section, existing_history = read_existing_doc(doc_path)
        last_sha = repo_state.get("last_sha")

        if force or not last_sha or existing_section is None:
            mode = "full"
        elif last_sha == head_sha:
            mode = "skip"
        else:
            mode = "update"
        tracing.record_kpis(span, mode=mode, head_sha=head_sha[:7], app_version=app.get("version"))
        print(f"  [{mode.upper():6}] {name} @ {head_sha[:7]} (v{app.get('version') or '?'})" + (f" — last documented {last_sha[:7]}" if last_sha else ""))

        if mode == "skip":
            stats.skipped += 1
            repo_state["last_checked"] = config.utc_now_iso()
            state["repos"][name] = repo_state
            return
        if dry_run:
            return

        started = time.time()
        history_entry = None
        summary_sv = None
        tokens_in = tokens_out = 0

        if mode == "update":
            with tracing.pipeline_span("bc.agent.change_tracker", repo=name):
                verdict, tr = tracker.track(org, name, last_sha, head_sha, branch)
            tokens_in += tr.input_tokens
            tokens_out += tr.output_tokens
            summary_sv = verdict.data.get("summary_sv")
            print(f"    → impact={verdict.impact} full_regen={verdict.requires_full_regeneration} features={verdict.data.get('affected_features')}")
            tracing.record_kpis(span, impact=verdict.impact, pull_requests=len(verdict.data.get("pull_requests") or []))
            if verdict.impact == "none":
                repo_state.update({"last_sha": head_sha, "last_checked": config.utc_now_iso(), "last_impact": "none", "app_version": app.get("version")})
                state["repos"][name] = repo_state
                stats.skipped += 1
                stats.tokens_in += tokens_in
                stats.tokens_out += tokens_out
                # Keep the header (commit/version) current even though the section is unchanged
                config.write_text_atomic(doc_path, render_repo_doc(customer, repo, app, head_sha, existing_section, existing_history or "", analyst.name))
                return
            history_entry = verdict.changelog_md
            if verdict.requires_full_regeneration:
                with tracing.pipeline_span("bc.agent.code_analyst", repo=name, mode="full"):
                    res = analyst.document(org, name, branch, repo.get("custom_label"))
            else:
                change_summary = json.dumps(verdict.data, ensure_ascii=False, indent=2) + "\n\n" + verdict.changelog_md
                with tracing.pipeline_span("bc.agent.code_analyst", repo=name, mode="update"):
                    res = analyst.update(org, name, branch, existing_section, change_summary, repo.get("custom_label"))
            stats.updated += 1
            repo_state["last_impact"] = verdict.impact
        else:
            with tracing.pipeline_span("bc.agent.code_analyst", repo=name, mode="full"):
                res = analyst.document(org, name, branch, repo.get("custom_label"))
            if last_sha and last_sha != head_sha:
                history_entry = f"#### {config.today_iso()} – dokumentationen regenererades\n- Fullständig regenerering från commit `{head_sha[:7]}` (tidigare `{last_sha[:7]}`)."
            stats.documented += 1
            repo_state["last_impact"] = "full"

        tokens_in += res.input_tokens
        tokens_out += res.output_tokens
        section = clean_section(res.text)
        if not section.startswith("### "):
            raise RuntimeError(f"analyst output does not start with a ### heading: {section[:80]!r}")

        history = prepend_history(existing_history, history_entry)
        config.write_text_atomic(doc_path, render_repo_doc(customer, repo, app, head_sha, section, history, analyst.name))

        repo_state.update(
            {
                "last_sha": head_sha,
                "app_name": app.get("name"),
                "app_version": app.get("version"),
                "doc_file": doc_path.name,
                "documented_at": config.utc_now_iso(),
                "last_checked": config.utc_now_iso(),
                "last_summary_sv": summary_sv or repo_state.get("last_summary_sv"),
                "tokens_last_run": {"input": tokens_in, "output": tokens_out},
                "duration_s": round(time.time() - started, 1),
            }
        )
        state["repos"][name] = repo_state
        stats.tokens_in += tokens_in
        stats.tokens_out += tokens_out
        tracing.record_kpis(span, tokens_in=tokens_in, tokens_out=tokens_out, duration_s=repo_state["duration_s"], section_chars=len(section))
        print(f"    ✅ wrote {doc_path.name} ({len(section)} chars, {tokens_in}/{tokens_out} tokens, {repo_state['duration_s']}s)")


def process_customer(customer: dict, analyst, tracker, gh, stats: Stats, only_repo: str | None, force: bool, dry_run: bool) -> None:
    out_dir = config.customer_output_dir(customer["name"])
    out_dir.mkdir(parents=True, exist_ok=True)
    state = load_state(out_dir, customer["name"])
    slug = config.slugify(customer["name"])

    with tracing.pipeline_span("bc.pipeline.customer", customer=customer["name"]) as span:
        print(f"\n[CUSTOMER] {customer['name']} → {out_dir}")
        repos = [r for r in customer.get("repos", []) if r.get("active", True)]
        if only_repo:
            repos = [r for r in repos if r["name"] == only_repo]
        for repo in repos:
            try:
                process_repo(customer, repo, state, out_dir, analyst, tracker, gh, stats, force, dry_run)
            except Exception as exc:
                stats.failed += 1
                stats.failures.append(f"{customer['name']}/{repo['name']}: {exc}")
                print(f"  [ERROR] {repo['name']}: {exc}")
            if not dry_run:
                save_state(out_dir, state)

        if not dry_run:
            bc_reports = load_bc_reports(out_dir, slug)
            config.write_text_atomic(out_dir / "README.md", render_customer_index(customer, state, out_dir, bc_reports))
            print(f"  📄 index → {out_dir / 'README.md'}")
        tracing.record_kpis(span, repos=len(repos), failed=stats.failed)


def run_discovery(repos_config_path: Path, customer_filter: str | None) -> None:
    """Run both discovery scripts in-process so the pipeline can be a single scheduled job."""
    import subprocess

    py = sys.executable
    base = [py, str(config.DISCOVERY_DIR / "discover_repos.py"), "--config", str(repos_config_path)]
    if customer_filter:
        base += ["--customer", customer_filter]
    subprocess.run(base, check=True)
    try:
        cmd = [py, str(config.DISCOVERY_DIR / "discover_bc_extensions.py"), "--config", str(repos_config_path)]
        if customer_filter:
            cmd += ["--customer", customer_filter]
        subprocess.run(cmd, check=True)
    except (subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"[WARN] BC discovery failed ({exc}) — continuing with GitHub data only")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--customer", help="Only process this customer")
    parser.add_argument("--repo", help="Only process this repository")
    parser.add_argument("--config", type=Path, default=config.REPOS_CONFIG_FILE)
    parser.add_argument("--discover", action="store_true", help="Run GitHub + BC discovery before documenting")
    parser.add_argument("--force", action="store_true", help="Regenerate all documentation (ignore stored SHAs)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen; call no agents")
    parser.add_argument("--recreate-agents", action="store_true", help="Deploy new agent versions from agents/instructions/*.md")
    parser.add_argument("--no-trace", action="store_true", help="Disable Application Insights tracing even if configured")
    args = parser.parse_args()

    if not config.PROJECT_CONNECTION_STRING and not args.dry_run:
        sys.exit("❌ PROJECT_CONNECTION_STRING not set. Run setup/deploy.sh first!")

    if args.discover:
        run_discovery(args.config, args.customer)

    # Tracing must be configured before the Foundry SDK client is created
    if not args.no_trace and not args.dry_run:
        tracing.setup_tracing()

    from agents.agents import ChangeTrackerAgent, CodeAnalystAgent  # noqa: E402 — after tracing setup
    from common.github_client import GitHubClient  # noqa: E402

    repos_config = config.load_repos_config(args.config)
    gh = GitHubClient(config.github_token())
    stats = Stats()

    analyst = tracker = None
    if not args.dry_run:
        print("=== Agents ===")
        analyst = CodeAnalystAgent().ensure(recreate=args.recreate_agents)
        tracker = ChangeTrackerAgent(client=analyst.client).ensure(recreate=args.recreate_agents)
    else:
        class _Noop:  # dry-run placeholder so process_repo can be reused
            name = config.CODE_ANALYST_AGENT_NAME
        analyst = tracker = _Noop()

    started = time.time()
    with tracing.pipeline_span("bc.pipeline.run", customers=args.customer or "all", force=args.force, dry_run=args.dry_run) as span:
        for customer in repos_config.get("customers", []):
            if args.customer and customer["name"] != args.customer:
                continue
            if not customer.get("enabled", True):
                print(f"[SKIP] {customer['name']}: disabled")
                continue
            process_customer(customer, analyst, tracker, gh, stats, args.repo, args.force, args.dry_run)
        tracing.record_kpis(
            span, repos=stats.repos, documented=stats.documented, updated=stats.updated, skipped=stats.skipped,
            failed=stats.failed, tokens_in=stats.tokens_in, tokens_out=stats.tokens_out, duration_s=round(time.time() - started, 1),
        )

    print("\n" + "=" * 70)
    print("BC DEPLOYMENT ANALYZER — RUN SUMMARY")
    print("=" * 70)
    print("  " + stats.summary())
    for failure in stats.failures:
        print(f"  ❌ {failure}")
    print("=" * 70)

    if not args.dry_run:
        analyst.client.close()
    tracing.flush()
    if stats.failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
