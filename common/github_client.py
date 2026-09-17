"""
common/github_client.py — Thin, dependency-light wrapper around the GitHub REST API.

Only read-only endpoints are used (a fine-grained PAT with Contents/Metadata/Pull requests
read scopes is enough). All functions are deterministic — no LLM involved — so the agents
reason over verified data instead of guessing what a repository contains.
"""

from __future__ import annotations

import base64
from typing import Any

import requests

GITHUB_API = "https://api.github.com"
DEFAULT_TIMEOUT = 20


class GitHubError(RuntimeError):
    pass


class GitHubClient:
    def __init__(self, token: str, api_base: str = GITHUB_API):
        self.api_base = api_base.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "bc-deployment-analyzer",
            }
        )

    # --- low level -------------------------------------------------------------------------
    def _get(self, path: str, params: dict | None = None, allow_404: bool = False) -> Any:
        resp = self.session.get(f"{self.api_base}{path}", params=params, timeout=DEFAULT_TIMEOUT)
        if resp.status_code == 404 and allow_404:
            return None
        if resp.status_code >= 400:
            raise GitHubError(f"GitHub {resp.status_code} on {path}: {resp.text[:300]}")
        return resp.json()

    def _paginate(self, path: str, params: dict | None = None, allow_404: bool = False) -> list | None:
        params = dict(params or {})
        params.setdefault("per_page", 100)
        page = 1
        items: list = []
        while True:
            params["page"] = page
            batch = self._get(path, params=params, allow_404=allow_404)
            if batch is None:
                return None
            if not batch:
                break
            items.extend(batch)
            if len(batch) < params["per_page"]:
                break
            page += 1
        return items

    # --- repositories ------------------------------------------------------------------------
    def list_org_repos(self, org: str) -> list[dict] | None:
        """All repos in an org (or user account). Returns None if the org is not reachable."""
        repos = self._paginate(f"/orgs/{org}/repos", params={"type": "all"}, allow_404=True)
        if repos is None:
            # Fall back to a user account with the same name
            repos = self._paginate(f"/users/{org}/repos", params={"type": "owner"}, allow_404=True)
        return repos

    def get_repo(self, org: str, repo: str) -> dict:
        return self._get(f"/repos/{org}/{repo}")

    def get_branch_head_sha(self, org: str, repo: str, branch: str) -> str:
        data = self._get(f"/repos/{org}/{repo}/branches/{branch}")
        return data["commit"]["sha"]

    def get_tree(self, org: str, repo: str, ref: str) -> list[dict]:
        """Recursive tree listing for a branch name or commit SHA."""
        data = self._get(f"/repos/{org}/{repo}/git/trees/{ref}", params={"recursive": "1"})
        if data.get("truncated"):
            print(f"    [WARN] {repo}: git tree listing truncated by GitHub (very large repo)")
        return data.get("tree", [])

    def get_file(self, org: str, repo: str, path: str, ref: str | None = None) -> str:
        params = {"ref": ref} if ref else None
        data = self._get(f"/repos/{org}/{repo}/contents/{path}", params=params)
        if isinstance(data, dict) and data.get("encoding") == "base64":
            return base64.b64decode(data["content"]).decode("utf-8-sig", errors="replace")
        # Files > 1 MB come back without inline content — fetch the blob
        if isinstance(data, dict) and data.get("sha"):
            blob = self._get(f"/repos/{org}/{repo}/git/blobs/{data['sha']}")
            return base64.b64decode(blob["content"]).decode("utf-8-sig", errors="replace")
        raise GitHubError(f"Unexpected contents response for {org}/{repo}/{path}")

    # --- history -----------------------------------------------------------------------------
    def compare(self, org: str, repo: str, base: str, head: str) -> dict:
        """Commits and changed files between two refs (GitHub caps files at 300)."""
        return self._get(f"/repos/{org}/{repo}/compare/{base}...{head}")

    def get_commit(self, org: str, repo: str, sha: str) -> dict:
        return self._get(f"/repos/{org}/{repo}/commits/{sha}")

    def list_merged_pulls(self, org: str, repo: str, base_branch: str, merged_after_iso: str) -> list[dict]:
        """Closed PRs into base_branch that were merged after the given ISO timestamp."""
        pulls = self._paginate(
            f"/repos/{org}/{repo}/pulls",
            params={"state": "closed", "base": base_branch, "sort": "updated", "direction": "desc"},
        ) or []
        merged = []
        for pr in pulls:
            merged_at = pr.get("merged_at")
            if not merged_at:
                continue
            if merged_at > merged_after_iso:
                merged.append(pr)
            elif pr.get("updated_at", "") < merged_after_iso:
                break  # sorted by updated desc — nothing older can be newer
        return merged


# --- tree helpers (pure functions) ---------------------------------------------------------------
def find_app_json_path(tree: list[dict]) -> str | None:
    """app.json is often nested (e.g. `{Name}-al-project/app.json`) — never assume repo root."""
    candidates = sorted(
        (e["path"] for e in tree if e.get("type") == "blob" and e["path"].split("/")[-1] == "app.json"),
        key=lambda p: (p.count("/"), p),
    )
    # Ignore test-app manifests when a main app exists
    non_test = [p for p in candidates if "test" not in p.lower()]
    return (non_test or candidates or [None])[0]


def al_file_paths(tree: list[dict], app_json_path: str | None = None) -> list[str]:
    """All .al blobs. When app.json is nested, only files under that folder belong to the app."""
    paths = [e["path"] for e in tree if e.get("type") == "blob" and e["path"].lower().endswith(".al")]
    if app_json_path and "/" in app_json_path:
        root = app_json_path.rsplit("/", 1)[0] + "/"
        scoped = [p for p in paths if p.startswith(root)]
        if scoped:
            paths = scoped
    # Exclude test projects living next to the main app
    return sorted(p for p in paths if "/test/" not in p.lower() and not p.lower().startswith("test/"))
