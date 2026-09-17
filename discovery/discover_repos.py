"""
discovery/discover_repos.py — Phase 1a: inventory a customer's GitHub repositories.

For every enabled customer in repos_config.json:
  1. list all repos in the customer's GitHub org
  2. keep those whose name starts with `search_prefix` (case-insensitive — real-world naming
     is inconsistent: `Acme_CRM_Integration`, `Acme-PTE`, `AcmeSC-PTE`)
  3. merge into `repos[]` (new → added, missing → `active: false`, existing → refreshed)
  4. NEW vs. the POC: read each repo's app.json and store the AL app metadata
     (id, name, publisher, version) plus the current head SHA. This is what
     discover_bc_extensions.py compares against — it never has to touch GitHub itself.

Usage:
    python discovery/discover_repos.py                       # all enabled customers
    python discovery/discover_repos.py --customer "Acme AB"  # one customer
    python discovery/discover_repos.py --skip-app-metadata   # faster, names only

Auth: GITHUB_TOKEN (see .env.example).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import config  # noqa: E402
from common.github_client import GitHubClient, GitHubError, al_file_paths, find_app_json_path  # noqa: E402


def merge_repos(existing: list[dict], matched: list[dict], now: str) -> list[dict]:
    by_name = {r["name"]: r for r in existing}
    seen = set()
    for repo in matched:
        name = repo["name"]
        seen.add(name)
        entry = by_name.get(name, {"custom_label": None, "app": None, "head_sha": None})
        entry.update(
            {
                "name": name,
                "url": repo["html_url"],
                "default_branch": repo.get("default_branch", "main"),
                "description": repo.get("description"),
                "archived": bool(repo.get("archived")),
                "pushed_at": repo.get("pushed_at"),
                "active": not repo.get("archived", False),
                "last_discovered": now,
            }
        )
        by_name[name] = entry
    for name, entry in by_name.items():
        if name not in seen:
            entry["active"] = False
    return sorted(by_name.values(), key=lambda r: r["name"].lower())


def enrich_app_metadata(gh: GitHubClient, org: str, repo: dict) -> None:
    """Read app.json from the default branch and record id/name/publisher/version + head SHA."""
    branch = repo.get("default_branch", "main")
    try:
        repo["head_sha"] = gh.get_branch_head_sha(org, repo["name"], branch)
        tree = gh.get_tree(org, repo["name"], branch)
        app_path = find_app_json_path(tree)
        if not app_path:
            repo["app"] = None
            repo["al_file_count"] = len(al_file_paths(tree))
            print(f"    - {repo['name']}: no app.json found (not an AL project?)")
            return
        app_json = json.loads(gh.get_file(org, repo["name"], app_path, ref=branch))
        repo["app"] = {
            "id": app_json.get("id"),
            "name": app_json.get("name"),
            "publisher": app_json.get("publisher"),
            "version": app_json.get("version"),
            "path": app_path,
            "dependencies": [d.get("name") for d in app_json.get("dependencies", [])],
        }
        repo["al_file_count"] = len(al_file_paths(tree, app_path))
        print(f"    - {repo['name']}: {repo['app']['name']} v{repo['app']['version']} ({repo['al_file_count']} .al files)")
    except (GitHubError, json.JSONDecodeError, KeyError) as exc:
        repo["app"] = repo.get("app")  # keep last known metadata
        repo["metadata_error"] = str(exc)[:200]
        print(f"    - {repo['name']}: [WARN] could not read app.json — {exc}")


def discover(customer: dict, gh: GitHubClient, now: str, with_app_metadata: bool) -> bool:
    print(f"[QUERY] {customer['name']}: org={customer['org']} prefix={customer['search_prefix']!r}")
    org_repos = gh.list_org_repos(customer["org"])
    if org_repos is None:
        print(f"  [WARN] org '{customer['org']}' not found or not accessible")
        customer["unreachable"] = True
        return False
    customer.pop("unreachable", None)

    prefix = customer["search_prefix"].lower()
    matched = [r for r in org_repos if r["name"].lower().startswith(prefix)]
    customer["repos"] = merge_repos(customer.get("repos", []), matched, now)

    active = [r for r in customer["repos"] if r["active"]]
    print(f"  [OK] {len(active)} active repo(s), {len(customer['repos']) - len(active)} inactive")
    if with_app_metadata:
        for repo in active:
            enrich_app_metadata(gh, customer["org"], repo)
    else:
        for repo in customer["repos"]:
            print(f"    - {repo['name']} ({'active' if repo['active'] else 'INACTIVE'})")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--customer", help="Only refresh this customer")
    parser.add_argument("--config", type=Path, default=config.REPOS_CONFIG_FILE, help="Path to repos_config.json")
    parser.add_argument("--skip-app-metadata", action="store_true", help="Do not read app.json / head SHA per repo")
    args = parser.parse_args()

    repos_config = config.load_repos_config(args.config)
    gh = GitHubClient(config.github_token())
    now = config.utc_now_iso()

    updated = False
    for customer in repos_config.get("customers", []):
        if args.customer and customer["name"] != args.customer:
            continue
        if not customer.get("enabled", True):
            print(f"[SKIP] {customer['name']}: disabled")
            continue
        updated |= discover(customer, gh, now, with_app_metadata=not args.skip_app_metadata)

    if not updated:
        sys.exit(f"No matching enabled customer found for {args.customer!r} in {args.config}")

    repos_config["generated_at"] = now
    config.write_json_atomic(args.config, repos_config)
    print(f"[DONE] Wrote {args.config}")


if __name__ == "__main__":
    main()
