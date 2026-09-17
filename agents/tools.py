"""
agents/tools.py — Deterministic FunctionTools used by the two Foundry agents.

    analyze_repo(org, repo, branch?, ref?)              → used by bc-code-analyst
    get_repo_changes(org, repo, base_sha, head_sha?)    → used by bc-change-tracker

Both follow the lab's `check_thresholds` pattern: everything that can be computed in code IS
computed in code (GitHub calls, AL parsing, archetype classification, version diffs), and the
agent only reasons over the structured JSON result. This keeps the agents grounded — they cannot
describe an object that the tool did not find.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from azure.ai.projects.models import FunctionTool  # noqa: E402

from common import config  # noqa: E402
from common.al_analysis import analyze_file, analyze_repo_files  # noqa: E402
from common.github_client import GitHubClient, GitHubError, al_file_paths, find_app_json_path  # noqa: E402

_gh: GitHubClient | None = None


def github() -> GitHubClient:
    global _gh
    if _gh is None:
        _gh = GitHubClient(config.github_token())
    return _gh


def _default_branch(org: str, repo: str, branch: str | None) -> str:
    if branch:
        return branch
    return github().get_repo(org, repo).get("default_branch", "main")


# =============================================================================================
# Tool 1: analyze_repo
# =============================================================================================
def analyze_repo(org: str, repo: str, branch: str | None = None, ref: str | None = None, max_chars: int | None = None) -> str:
    """
    Fetch an AL repository and return the structured analysis as a JSON string.
    `ref` (commit SHA/tag) wins over `branch`; when neither is given the default branch is used.
    """
    gh = github()
    try:
        branch = _default_branch(org, repo, branch)
        head_sha = ref or gh.get_branch_head_sha(org, repo, branch)
        tree = gh.get_tree(org, repo, head_sha)
        app_path = find_app_json_path(tree)
        if not app_path:
            return json.dumps({"error": f"No app.json found anywhere in {org}/{repo}@{branch} — not an AL project"})
        app_json = json.loads(gh.get_file(org, repo, app_path, ref=head_sha))
        al_paths = al_file_paths(tree, app_path)
        al_files = {path: gh.get_file(org, repo, path, ref=head_sha) for path in al_paths}
    except (GitHubError, json.JSONDecodeError) as exc:
        return json.dumps({"error": f"Could not analyze {org}/{repo}: {exc}"})

    analysis = analyze_repo_files(app_json, al_files, max_chars or config.MAX_AL_CHARS)
    analysis["repository"] = {
        "org": org,
        "repo": repo,
        "branch": branch,
        "head_sha": head_sha,
        "url": f"https://github.com/{org}/{repo}",
        "app_json_path": app_path,
        "analyzed_at": config.utc_now_iso(),
    }
    return json.dumps(analysis, ensure_ascii=False)


ANALYZE_REPO_TOOL = FunctionTool(
    name="analyze_repo",
    description=(
        "Fetch a Business Central AL repository from GitHub and return a structured analysis: "
        "app.json manifest (name, version, publisher, dependencies), every AL object with type/id/name, "
        "codeunits classified as logic / subscribers / install_upgrade, all event subscribers, table fields, "
        "page actions and API properties, plus the AL source text within a size budget. "
        "Always call this before documenting a repository."
    ),
    parameters={
        "type": "object",
        "properties": {
            "org": {"type": "string", "description": "GitHub organisation or user that owns the repository"},
            "repo": {"type": "string", "description": "Repository name"},
            "branch": {"type": "string", "description": "Branch to analyze (defaults to the repository's default branch)"},
            "ref": {"type": "string", "description": "Optional commit SHA to analyze instead of the branch head"},
        },
        "required": ["org", "repo"],
        "additionalProperties": False,
    },
    strict=False,
)


# =============================================================================================
# Tool 2: get_repo_changes
# =============================================================================================
_DOC_IRRELEVANT_PREFIXES = (".github/", ".vscode/", ".alpackages/", ".altestrunner/", "Translations/", "translations/")
_DOC_IRRELEVANT_SUFFIXES = (".md", ".xlf", ".json.lock", ".ruleset.json", "launch.json", "settings.json", ".gitignore", ".png", ".jpg")


def _is_doc_relevant(path: str) -> bool:
    lower = path.lower()
    if lower.endswith("app.json"):
        return True
    if lower.startswith(_DOC_IRRELEVANT_PREFIXES) or lower.endswith(_DOC_IRRELEVANT_SUFFIXES):
        return False
    return lower.endswith(".al")


def _read_app_version(gh: GitHubClient, org: str, repo: str, ref: str, tree: list[dict] | None = None) -> str | None:
    try:
        tree = tree or gh.get_tree(org, repo, ref)
        path = find_app_json_path(tree)
        if not path:
            return None
        return json.loads(gh.get_file(org, repo, path, ref=ref)).get("version")
    except (GitHubError, json.JSONDecodeError):
        return None


def get_repo_changes(org: str, repo: str, base_sha: str, head_sha: str | None = None, branch: str | None = None) -> str:
    """
    Everything that changed between two commits, as a JSON string:
    commits, merged pull requests, changed files (with truncated patches for AL/app.json),
    a quick classification of each changed AL object at head, and app version before/after.
    """
    gh = github()
    try:
        branch = _default_branch(org, repo, branch)
        head_sha = head_sha or gh.get_branch_head_sha(org, repo, branch)
        if head_sha == base_sha:
            return json.dumps({"org": org, "repo": repo, "base_sha": base_sha, "head_sha": head_sha, "no_changes": True})

        cmp = gh.compare(org, repo, base_sha, head_sha)
        base_commit = gh.get_commit(org, repo, base_sha)
        base_date = base_commit["commit"]["committer"]["date"]
        head_commit = gh.get_commit(org, repo, head_sha)
        head_date = head_commit["commit"]["committer"]["date"]

        commits = [
            {
                "sha": c["sha"][:10],
                "date": c["commit"]["committer"]["date"],
                "author": (c["commit"].get("author") or {}).get("name"),
                "message": c["commit"]["message"].strip()[:500],
            }
            for c in cmp.get("commits", [])
        ]

        pulls = [
            {
                "number": pr["number"],
                "title": pr["title"],
                "body": (pr.get("body") or "").strip()[:1500],
                "merged_at": pr["merged_at"],
                "author": (pr.get("user") or {}).get("login"),
                "labels": [lb["name"] for lb in pr.get("labels", [])],
                "url": pr["html_url"],
            }
            for pr in gh.list_merged_pulls(org, repo, branch, base_date)
        ]

        head_tree = gh.get_tree(org, repo, head_sha)
        files, total_patch, classified = [], 0, 0
        for f in cmp.get("files", []):
            path = f["filename"]
            relevant = _is_doc_relevant(path)
            entry = {
                "path": path,
                "status": f.get("status"),
                "additions": f.get("additions"),
                "deletions": f.get("deletions"),
                "doc_relevant": relevant,
            }
            if relevant and f.get("patch") and total_patch < config.MAX_TOTAL_PATCH_CHARS:
                patch = f["patch"]
                if len(patch) > config.MAX_PATCH_CHARS:
                    patch = patch[: config.MAX_PATCH_CHARS] + f"\n... [patch truncated, {len(f['patch'])} chars total]"
                entry["patch"] = patch
                total_patch += len(patch)
            if relevant and path.lower().endswith(".al") and f.get("status") in ("added", "modified", "renamed") and classified < 40:
                try:
                    info = analyze_file(path, gh.get_file(org, repo, path, ref=head_sha))
                    entry["object"] = {k: info.get(k) for k in ("type", "id", "name", "extends", "archetype", "commented_out")}
                    if info.get("event_subscribers"):
                        entry["object"]["event_subscribers"] = info["event_subscribers"]
                    classified += 1
                except GitHubError:
                    pass
            files.append(entry)

        result = {
            "org": org,
            "repo": repo,
            "branch": branch,
            "base_sha": base_sha,
            "head_sha": head_sha,
            "base_date": base_date,
            "head_date": head_date,
            "app_version_before": _read_app_version(gh, org, repo, base_sha),
            "app_version_after": _read_app_version(gh, org, repo, head_sha, head_tree),
            "total_commits": cmp.get("total_commits", len(commits)),
            "commits": commits[:100],
            "pull_requests": pulls,
            "files": files,
            "summary": {
                "files_changed": len(files),
                "al_files_changed": sum(1 for f in files if f["path"].lower().endswith(".al")),
                "doc_relevant_files": sum(1 for f in files if f["doc_relevant"]),
                "added": [f["path"] for f in files if f["status"] == "added" and f["doc_relevant"]],
                "removed": [f["path"] for f in files if f["status"] == "removed" and f["doc_relevant"]],
            },
        }
        return json.dumps(result, ensure_ascii=False)
    except GitHubError as exc:
        return json.dumps({"error": f"Could not compare {org}/{repo} {base_sha[:7]}..{head_sha or branch}: {exc}"})


GET_REPO_CHANGES_TOOL = FunctionTool(
    name="get_repo_changes",
    description=(
        "Return what changed in a GitHub AL repository between two commits: commits, merged pull requests "
        "(title, body, labels), changed files with patches for .al and app.json, the type/name/archetype of each "
        "changed AL object, and the app version before/after. Always call this before writing a change log."
    ),
    parameters={
        "type": "object",
        "properties": {
            "org": {"type": "string", "description": "GitHub organisation or user"},
            "repo": {"type": "string", "description": "Repository name"},
            "base_sha": {"type": "string", "description": "Commit SHA the current documentation was generated from"},
            "head_sha": {"type": "string", "description": "Commit SHA to compare to (defaults to the head of the default branch)"},
            "branch": {"type": "string", "description": "Base branch for pull request lookup (defaults to the default branch)"},
        },
        "required": ["org", "repo", "base_sha"],
        "additionalProperties": False,
    },
    strict=False,
)


# =============================================================================================
# Registry used by the function-call loop
# =============================================================================================
TOOL_REGISTRY = {
    "analyze_repo": analyze_repo,
    "get_repo_changes": get_repo_changes,
}


def execute_tool(name: str, arguments: str | dict) -> str:
    """Run a registered tool with the JSON arguments the model produced. Never raises."""
    fn = TOOL_REGISTRY.get(name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool '{name}'"})
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else dict(arguments)
        return fn(**args)
    except TypeError as exc:
        return json.dumps({"error": f"Bad arguments for {name}: {exc}"})
    except Exception as exc:  # tool failures are reported to the model, not raised
        return json.dumps({"error": f"{name} failed: {exc}"})


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run a tool locally and print its JSON output (no agent involved).")
    parser.add_argument("tool", choices=sorted(TOOL_REGISTRY))
    parser.add_argument("--org", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--branch")
    parser.add_argument("--base-sha")
    parser.add_argument("--head-sha")
    a = parser.parse_args()
    if a.tool == "analyze_repo":
        out = analyze_repo(a.org, a.repo, a.branch)
    else:
        if not a.base_sha:
            parser.error("--base-sha is required for get_repo_changes")
        out = get_repo_changes(a.org, a.repo, a.base_sha, a.head_sha, a.branch)
    data = json.loads(out)
    data.pop("source", None)  # keep terminal output readable
    print(json.dumps(data, indent=2, ensure_ascii=False))
