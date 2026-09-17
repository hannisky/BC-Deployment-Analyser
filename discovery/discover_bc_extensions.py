"""
discovery/discover_bc_extensions.py — Phase 1b: inventory a Business Central environment and
validate published versions against source control.

Runs in isolation from the other phases: it READS repos_config.json (for the app metadata
collected by discover_repos.py) but never writes to it. For every BC environment it produces
its own pair of files under output/{customer}/:

    {customer}_bc_{environment}.json   — raw extension list + comparison result (machine-readable)
    {customer}_bc_{environment}.md     — Swedish Markdown report (indexed by Copilot / GitHub)

The report replaces the old "KRÄVER MANUELL KOMPLETTERING" placeholders with a deterministic
version validation:

    ✅ Matchar             app.json version == published version (major.minor.build)
    ⚠️ Git är nyare        source has a version that is not published yet
    ⚠️ BC är nyare         the environment runs a build that is not in the default branch
    ❓ Inget repo          own-published app with no matching repo (unpublished? renamed?)
    ❔ Ej publicerad       repo with app.json but nothing installed in this environment

Usage:
    python discovery/discover_bc_extensions.py                       # all customers/environments
    python discovery/discover_bc_extensions.py --customer "Acme AB"

Auth: BC_CLIENT_ID / BC_CLIENT_SECRET (+ tenant/environment/company per customer in
repos_config.json `bc_environments[]`, or defaults from env/bc_config.json).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import msal
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import config  # noqa: E402
from common.al_analysis import compare_versions  # noqa: E402

BC_SCOPE = "https://api.businesscentral.dynamics.com/.default"
BC_API = "https://api.businesscentral.dynamics.com/v2.0"

STATUS_LABEL = {
    "match": "✅ Matchar",
    "git_ahead": "⚠️ Git är nyare – ej publicerad ändring",
    "bc_ahead": "⚠️ BC är nyare – källkod saknar publicerad version",
    "unknown": "❔ Version saknas",
    "no_repo": "❓ Inget repo hittades",
    "not_published": "❔ Ej publicerad i miljön",
}


# --- Business Central API ---------------------------------------------------------------------
def get_access_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    app = msal.ConfidentialClientApplication(
        client_id=client_id,
        client_credential=client_secret,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
    )
    result = app.acquire_token_for_client(scopes=[BC_SCOPE])
    if "access_token" not in result:
        raise RuntimeError(f"BC auth failed for tenant {tenant_id}: {result.get('error')}: {result.get('error_description')}")
    return result["access_token"]


def resolve_company_id(tenant_id: str, environment: str, company_name: str, headers: dict) -> str:
    resp = requests.get(f"{BC_API}/{tenant_id}/{environment}/api/microsoft/automation/v2.0/companies", headers=headers, timeout=20)
    resp.raise_for_status()
    companies = resp.json().get("value", [])
    if not company_name and companies:
        return companies[0]["id"]  # apps are environment-wide; any company works
    for company in companies:
        if company.get("name", "").strip().lower() == company_name.strip().lower():
            return company["id"]
    raise RuntimeError(f"Company '{company_name}' not found in environment '{environment}'")


def fetch_non_microsoft_extensions(tenant_id: str, environment: str, company_id: str, headers: dict) -> list[dict]:
    resp = requests.get(
        f"{BC_API}/{tenant_id}/{environment}/api/microsoft/automation/v2.0/companies({company_id})/extensions",
        headers=headers,
        params={"$filter": "publisher ne 'Microsoft'"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("value", [])


# --- Comparison -----------------------------------------------------------------------------------
def _norm(name: str | None) -> str:
    return re.sub(r"[\s\-_]+", "", (name or "").lower())


def build_extension_records(raw: list[dict], own_publisher: str, now: str) -> list[dict]:
    records = []
    for e in raw:
        publisher = (e.get("publisher") or "").strip()
        records.append(
            {
                "id": e.get("id"),
                "packageId": e.get("packageId"),
                "displayName": e.get("displayName"),
                "publisher": publisher,
                "version": f"{e.get('versionMajor')}.{e.get('versionMinor')}.{e.get('versionBuild')}",
                "isInstalled": e.get("isInstalled"),
                "publishedAs": e.get("publishedAs"),
                "is_own_publisher": bool(own_publisher) and publisher.lower() == own_publisher.strip().lower(),
                "last_queried": now,
            }
        )
    return sorted(records, key=lambda r: ((not r["is_own_publisher"]), (r["displayName"] or "").lower()))


def compare_with_repos(extensions: list[dict], repos: list[dict]) -> dict:
    """Match own-published extensions to repos by app id first, then by normalised name."""
    active_repos = [r for r in repos if r.get("active", True) and r.get("app")]
    by_id = {r["app"]["id"]: r for r in active_repos if r["app"].get("id")}
    by_name = {_norm(r["app"]["name"]): r for r in active_repos if r["app"].get("name")}
    by_repo_name = {_norm(r["name"]): r for r in active_repos}

    matched_repo_names = set()
    own_rows, third_party = [], []
    for ext in extensions:
        if not ext["is_own_publisher"]:
            third_party.append(ext)
            continue
        repo = by_id.get(ext["id"]) or by_name.get(_norm(ext["displayName"])) or by_repo_name.get(_norm(ext["displayName"]))
        if repo is None:
            own_rows.append({**ext, "repo": None, "git_version": None, "status": "no_repo"})
            continue
        matched_repo_names.add(repo["name"])
        status = compare_versions(repo["app"].get("version"), ext["version"])
        own_rows.append(
            {
                **ext,
                "repo": repo["name"],
                "repo_url": repo.get("url"),
                "git_version": repo["app"].get("version"),
                "head_sha": repo.get("head_sha"),
                "matched_by": "app_id" if by_id.get(ext["id"]) is repo else "name",
                "status": status,
            }
        )

    unpublished = [
        {"repo": r["name"], "repo_url": r.get("url"), "app_name": r["app"].get("name"), "git_version": r["app"].get("version"), "status": "not_published"}
        for r in active_repos
        if r["name"] not in matched_repo_names
    ]
    counts = {
        "third_party": len(third_party),
        "own_published": len(own_rows),
        "match": sum(1 for r in own_rows if r["status"] == "match"),
        "mismatch": sum(1 for r in own_rows if r["status"] in ("git_ahead", "bc_ahead")),
        "no_repo": sum(1 for r in own_rows if r["status"] == "no_repo"),
        "not_published": len(unpublished),
    }
    return {"third_party": third_party, "own": own_rows, "not_published": unpublished, "counts": counts}


# --- Markdown ---------------------------------------------------------------------------------------
def _md_escape(text) -> str:
    return str(text if text is not None else "–").replace("|", "\\|")


def render_markdown(customer: dict, env: dict, comparison: dict, known: dict, repos_generated_at: str | None) -> str:
    c = comparison["counts"]
    title = f"# Installerade tillägg – {customer['name']} ({env['environment']})"
    lines = [
        title,
        "",
        f"> Automatiskt genererad av `discover_bc_extensions.py` {config.today_iso()}. "
        f"Tenant `{env['tenant_id']}`, miljö **{env['environment']}**"
        + (f", företag *{env['company_name']}*" if env.get("company_name") else "")
        + ". Källa: Business Central Automation API (`publisher ne 'Microsoft'`). "
        f"Versionsvalidering mot GitHub-inventeringen från `discover_repos.py`"
        + (f" ({repos_generated_at})." if repos_generated_at else " (ingen inventering hittades)."),
        "",
        "## Sammanfattning",
        "",
        "| Kategori | Antal |",
        "|---|---:|",
        f"| Tredjepartstillägg (ISV) | {c['third_party']} |",
        f"| Egna appar publicerade i miljön | {c['own_published']} |",
        f"| ✅ Version matchar Git | {c['match']} |",
        f"| ⚠️ Versionsavvikelse | {c['mismatch']} |",
        f"| ❓ Publicerad app utan repo | {c['no_repo']} |",
        f"| ❔ Repo utan publicerad app | {c['not_published']} |",
        "",
        "## 1 Installerade tillägg (tredje part)",
        "",
        "Kommersiella ISV-appar installerade i miljön. Beskrivningar hämtas från `known_extensions.json` när de finns.",
        "",
        "| Tillägg | Utgivare | Version | Status | Beskrivning |",
        "|---|---|---|---|---|",
    ]
    for ext in comparison["third_party"]:
        info = known.get((ext["displayName"] or "").lower(), {})
        desc = info.get("description", "–")
        if info.get("url"):
            desc += f" Mer information: {info['url']}"
        installed = "Installerad" if ext.get("isInstalled") else "Publicerad, ej installerad"
        lines.append(f"| {_md_escape(ext['displayName'])} | {_md_escape(ext['publisher'])} | {ext['version']} | {installed} | {_md_escape(desc)} |")
    if not comparison["third_party"]:
        lines.append("| – | – | – | – | Inga tredjepartstillägg hittades |")

    lines += [
        "",
        "## 2 Egna anpassningar – versionsvalidering",
        "",
        "Appar publicerade under egen utgivare jämförda med `app.json` i respektive repos standardbranch "
        "(jämförelse på major.minor.build). Detaljerad funktionsdokumentation per app finns i respektive app-dokument.",
        "",
        "| App | GitHub-repo | Version i BC | Version i Git | Status |",
        "|---|---|---|---|---|",
    ]
    for row in comparison["own"]:
        repo_cell = f"[{row['repo']}]({row['repo_url']})" if row.get("repo") else "–"
        lines.append(
            f"| {_md_escape(row['displayName'])} | {repo_cell} | {row['version']} | {_md_escape(row.get('git_version'))} | {STATUS_LABEL[row['status']]} |"
        )
    if not comparison["own"]:
        lines.append("| – | – | – | – | Inga egna appar hittades i miljön |")

    lines += [
        "",
        "## 3 Repos utan publicerad app i miljön",
        "",
        "AL-projekt i GitHub som inte motsvarar någon installerad app i just denna miljö (kan vara under utveckling, "
        "publicerad i en annan miljö eller avvecklad).",
        "",
        "| GitHub-repo | App (app.json) | Version i Git | Status |",
        "|---|---|---|---|",
    ]
    for row in comparison["not_published"]:
        lines.append(f"| [{row['repo']}]({row['repo_url']}) | {_md_escape(row['app_name'])} | {_md_escape(row['git_version'])} | {STATUS_LABEL['not_published']} |")
    if not comparison["not_published"]:
        lines.append("| – | – | – | Alla repos med app.json är publicerade i miljön |")
    lines.append("")
    return "\n".join(lines)


# --- Main -----------------------------------------------------------------------------------------------
def environments_for(customer: dict, creds: dict) -> list[dict]:
    envs = customer.get("bc_environments") or []
    if envs:
        return envs
    if creds.get("tenant_id"):
        return [{"tenant_id": creds["tenant_id"], "environment": creds["environment"], "company_name": creds["company_name"]}]
    return []


def process_environment(customer: dict, env: dict, creds: dict, known: dict, repos_generated_at: str | None, output_dir: Path) -> dict:
    now = config.utc_now_iso()
    token = get_access_token(env["tenant_id"], creds["client_id"], creds["client_secret"])
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    company_id = resolve_company_id(env["tenant_id"], env["environment"], env.get("company_name", ""), headers)
    raw = fetch_non_microsoft_extensions(env["tenant_id"], env["environment"], company_id, headers)

    extensions = build_extension_records(raw, creds.get("own_publisher", ""), now)
    comparison = compare_with_repos(extensions, customer.get("repos", []))

    slug = config.slugify(customer["name"])
    env_slug = config.slugify(env["environment"])
    base = output_dir / slug / f"{slug}_bc_{env_slug}"
    config.write_json_atomic(
        base.with_suffix(".json"),
        {
            "customer": customer["name"],
            "tenant_id": env["tenant_id"],
            "environment": env["environment"],
            "company_name": env.get("company_name"),
            "queried_at": now,
            "repos_generated_at": repos_generated_at,
            "counts": comparison["counts"],
            "extensions": extensions,
            "own_apps": comparison["own"],
            "repos_not_published": comparison["not_published"],
        },
    )
    config.write_text_atomic(base.with_suffix(".md"), render_markdown(customer, env, comparison, known, repos_generated_at))

    c = comparison["counts"]
    print(f"  [OK] {env['environment']}: {c['third_party']} third-party, {c['own_published']} own — "
          f"{c['match']} match, {c['mismatch']} mismatch, {c['no_repo']} without repo, {c['not_published']} repos unpublished")
    for row in comparison["own"]:
        print(f"    - {row['displayName']}: BC {row['version']} / Git {row.get('git_version') or '–'} → {STATUS_LABEL[row['status']]}")
    print(f"  [DONE] Wrote {base.with_suffix('.md')}")
    return comparison["counts"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--customer", help="Only query this customer")
    parser.add_argument("--config", type=Path, default=config.REPOS_CONFIG_FILE, help="Path to repos_config.json (read-only)")
    parser.add_argument("--output", type=Path, default=config.OUTPUT_DIR, help="Output directory")
    args = parser.parse_args()

    repos_config = config.load_repos_config(args.config)
    creds = config.bc_credentials()
    known_raw = config.load_json(config.KNOWN_EXTENSIONS_FILE, default={}) or {}
    known = {k.lower(): v for k, v in known_raw.items() if not k.startswith("_")}

    processed = 0
    for customer in repos_config.get("customers", []):
        if args.customer and customer["name"] != args.customer:
            continue
        if not customer.get("enabled", True):
            print(f"[SKIP] {customer['name']}: disabled")
            continue
        envs = environments_for(customer, creds)
        if not envs:
            print(f"[SKIP] {customer['name']}: no bc_environments[] configured and no BC_TENANT_ID default")
            continue
        print(f"[QUERY] {customer['name']}: {len(envs)} BC environment(s)")
        for env in envs:
            try:
                process_environment(customer, env, creds, known, repos_config.get("generated_at"), args.output)
                processed += 1
            except Exception as exc:  # keep going with the next environment/customer
                print(f"  [ERROR] {env.get('environment')}: {exc}")

    if not processed:
        sys.exit("No BC environment was processed — check --customer, enabled flags and bc_environments[]")


if __name__ == "__main__":
    main()
