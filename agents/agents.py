"""
agents/agents.py — Phase 2: the two Foundry agents of the BC Deployment Analyzer.

    bc-code-analyst    FunctionTool analyze_repo      → Swedish "Anpassningar" documentation
    bc-change-tracker  FunctionTool get_repo_changes  → impact verdict (JSON) + Swedish changelog

Both are PromptAgentDefinition agents created with `create_version()` so they show up in the
Foundry portal under Build → Agents, are versioned, and can be reused by name from the
orchestrator (`ensure()` creates a version only when the agent does not exist yet, or when
`--recreate` is passed after editing the instruction files).

Usage (smoke test against one repository):
    python agents/agents.py --org <org> --repo <repo>                 # full documentation
    python agents/agents.py --org <org> --repo <repo> --since <sha>   # + change log since a commit
    python agents/agents.py --recreate                                # push new instructions
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from azure.ai.projects import AIProjectClient  # noqa: E402
from azure.ai.projects.models import PromptAgentDefinition  # noqa: E402
from azure.identity import DefaultAzureCredential  # noqa: E402
from openai.types.responses.response_input_param import FunctionCallOutput  # noqa: E402

from agents.tools import ANALYZE_REPO_TOOL, GET_REPO_CHANGES_TOOL, execute_tool  # noqa: E402
from common import config  # noqa: E402

INSTRUCTIONS_DIR = Path(__file__).resolve().parent / "instructions"
MAX_TOOL_ROUNDS = 8


class RunResult:
    """Text output + usage so the orchestrator can record cost per repo."""

    def __init__(self, text: str, input_tokens: int = 0, output_tokens: int = 0, tool_calls: int = 0, response_id: str | None = None):
        self.text = text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.tool_calls = tool_calls
        self.response_id = response_id

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class FoundryAgent:
    """Shared plumbing: create/reuse an agent version, run a conversation with a function-call loop."""

    name: str = ""
    instructions_file: str = ""
    tools: list = []
    description: str = ""

    def __init__(self, client: AIProjectClient | None = None):
        self._owns_client = client is None
        self.client = client or AIProjectClient(endpoint=config.PROJECT_CONNECTION_STRING, credential=DefaultAzureCredential())
        self.openai = self.client.get_openai_client()
        self.version: str | None = None

    # --- lifecycle ------------------------------------------------------------------------------
    def instructions(self) -> str:
        return (INSTRUCTIONS_DIR / self.instructions_file).read_text(encoding="utf-8")

    def exists(self) -> bool:
        try:
            self.client.agents.get(agent_name=self.name)
            return True
        except Exception:
            return False

    def create(self):
        """Create a new agent version (always). Returns AgentVersionDetails."""
        agent = self.client.agents.create_version(
            agent_name=self.name,
            definition=PromptAgentDefinition(
                model=config.MODEL_DEPLOYMENT_NAME,
                instructions=self.instructions(),
                tools=self.tools or None,
            ),
            description=self.description,
            metadata={"solution": "bc-deployment-analyzer"},
        )
        self.version = agent.version
        return agent

    def ensure(self, recreate: bool = False):
        """Reuse the deployed agent by name; create a version only if missing (or recreate=True)."""
        if recreate or not self.exists():
            agent = self.create()
            print(f"  ✅ Deployed {self.name} (version {agent.version})")
        else:
            print(f"  ↺ Reusing existing agent {self.name}")
        return self

    def cleanup(self, delete_agent: bool = False):
        if delete_agent:
            try:
                self.client.agents.delete(agent_name=self.name)
            except Exception as exc:
                print(f"  [WARN] could not delete {self.name}: {exc}")
        elif self.version:
            try:
                self.client.agents.delete_version(agent_name=self.name, agent_version=self.version)
            except Exception as exc:
                print(f"  [WARN] could not delete {self.name} v{self.version}: {exc}")
        if self._owns_client:
            self.client.close()

    # --- execution --------------------------------------------------------------------------------
    def run(self, input_text: str, verbose: bool = True) -> RunResult:
        agent_ref = {"agent_reference": {"name": self.name, "type": "agent_reference"}}
        conversation = self.openai.conversations.create()
        input_tokens = output_tokens = tool_calls = 0
        try:
            response = self.openai.responses.create(input=input_text, conversation=conversation.id, extra_body=agent_ref)
            input_tokens, output_tokens = _accumulate_usage(response, input_tokens, output_tokens)

            for _ in range(MAX_TOOL_ROUNDS):
                function_calls = [item for item in response.output if item.type == "function_call"]
                if not function_calls:
                    break
                outputs = []
                for call in function_calls:
                    tool_calls += 1
                    if verbose:
                        print(f"    🛠  {self.name} → {call.name}({_short_args(call.arguments)})")
                    outputs.append(FunctionCallOutput(type="function_call_output", call_id=call.call_id, output=execute_tool(call.name, call.arguments)))
                response = self.openai.responses.create(input=outputs, conversation=conversation.id, extra_body=agent_ref)
                input_tokens, output_tokens = _accumulate_usage(response, input_tokens, output_tokens)

            return RunResult(response.output_text, input_tokens, output_tokens, tool_calls, response.id)
        finally:
            try:
                self.openai.conversations.delete(conversation_id=conversation.id)
            except Exception:
                pass


def _accumulate_usage(response, input_tokens: int, output_tokens: int) -> tuple[int, int]:
    usage = getattr(response, "usage", None)
    if usage:
        input_tokens += getattr(usage, "input_tokens", 0) or 0
        output_tokens += getattr(usage, "output_tokens", 0) or 0
    return input_tokens, output_tokens


def _short_args(arguments: str) -> str:
    try:
        args = json.loads(arguments)
        return ", ".join(f"{k}={str(v)[:12]}" for k, v in args.items())
    except Exception:
        return arguments[:60]


# =============================================================================================
# Agent 1: Code Analyst
# =============================================================================================
class CodeAnalystAgent(FoundryAgent):
    name = config.CODE_ANALYST_AGENT_NAME
    instructions_file = "code_analyst.md"
    tools = [ANALYZE_REPO_TOOL]
    description = "Documents a Business Central PTE repository (Swedish 'Anpassningar' section) grounded in analyze_repo."

    def document(self, org: str, repo: str, branch: str | None = None, custom_label: str | None = None) -> RunResult:
        label = f"\nUse this display name for the ### heading: {custom_label}" if custom_label else ""
        prompt = (
            "MODE: full\n"
            f"Document the Business Central extension in GitHub repository org={org} repo={repo}"
            + (f" branch={branch}" if branch else "")
            + ".\nCall analyze_repo first, then return the complete Section 3 entry in Swedish starting at the ### heading."
            + label
        )
        return self.run(prompt)

    def update(self, org: str, repo: str, branch: str | None, current_doc: str, change_summary: str, custom_label: str | None = None) -> RunResult:
        label = f"\nKeep this display name for the ### heading: {custom_label}" if custom_label else ""
        prompt = (
            "MODE: update\n"
            f"Repository org={org} repo={repo}" + (f" branch={branch}" if branch else "") + ".\n"
            "Call analyze_repo to get the current state of the code, then return the complete updated Section 3 "
            "entry (### heading and all #### sections). Keep unchanged text as is." + label + "\n\n"
            "=== CHANGE SUMMARY (from bc-change-tracker) ===\n" + change_summary.strip() + "\n\n"
            "=== CURRENT DOCUMENTATION ===\n" + current_doc.strip()
        )
        return self.run(prompt)

    def document_from_analysis(self, analysis_json: str, custom_label: str | None = None) -> RunResult:
        """Evaluation / workflow mode: analysis is supplied inline, no tool call expected."""
        label = f"\nUse this display name for the ### heading: {custom_label}" if custom_label else ""
        prompt = (
            "MODE: full\n"
            "The analysis JSON is provided below — do NOT call analyze_repo. Return the complete Section 3 entry in Swedish "
            "starting at the ### heading." + label + "\n\n=== ANALYSIS ===\n" + analysis_json
        )
        return self.run(prompt)


# =============================================================================================
# Agent 2: Change Tracker
# =============================================================================================
_JSON_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


class ChangeVerdict:
    def __init__(self, raw_text: str):
        self.raw_text = raw_text
        self.data: dict = {}
        self.changelog_md: str = raw_text.strip()
        m = _JSON_BLOCK_RE.search(raw_text)
        if m:
            try:
                self.data = json.loads(m.group(1))
            except json.JSONDecodeError:
                self.data = {}
            self.changelog_md = raw_text[m.end():].strip()
        if not self.data:  # fall back to a conservative verdict so the pipeline still progresses
            self.data = {"impact": "minor", "requires_full_regeneration": True, "affected_features": [], "summary_sv": ""}

    @property
    def impact(self) -> str:
        return str(self.data.get("impact", "minor")).lower()

    @property
    def requires_full_regeneration(self) -> bool:
        return bool(self.data.get("requires_full_regeneration", self.impact == "major"))

    @property
    def version_after(self) -> str | None:
        return self.data.get("version_after")


class ChangeTrackerAgent(FoundryAgent):
    name = config.CHANGE_TRACKER_AGENT_NAME
    instructions_file = "change_tracker.md"
    tools = [GET_REPO_CHANGES_TOOL]
    description = "Explains what changed in an AL repository since the last documentation run (impact verdict + Swedish changelog)."

    def track(self, org: str, repo: str, base_sha: str, head_sha: str | None = None, branch: str | None = None) -> tuple[ChangeVerdict, RunResult]:
        prompt = (
            f"Analyse the changes in GitHub repository org={org} repo={repo}"
            + (f" branch={branch}" if branch else "")
            + f" between base_sha={base_sha} and head_sha={head_sha or 'HEAD of the default branch'}.\n"
            "Call get_repo_changes first. Then return Part 1 (JSON verdict) and Part 2 (Swedish changelog)."
        )
        result = self.run(prompt)
        return ChangeVerdict(result.text), result

    def track_from_changes(self, changes_json: str) -> tuple[ChangeVerdict, RunResult]:
        prompt = (
            "The change data JSON is provided below — do NOT call get_repo_changes. Return Part 1 (JSON verdict) "
            "and Part 2 (Swedish changelog).\n\n=== CHANGES ===\n" + changes_json
        )
        result = self.run(prompt)
        return ChangeVerdict(result.text), result


# =============================================================================================
# Main — smoke test
# =============================================================================================
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--org", help="GitHub org (defaults to the first enabled customer in repos_config.json)")
    parser.add_argument("--repo", help="Repository (defaults to the first active repo of that customer)")
    parser.add_argument("--branch")
    parser.add_argument("--since", metavar="SHA", help="Also run the change tracker from this base commit")
    parser.add_argument("--recreate", action="store_true", help="Create new agent versions from the instruction files")
    parser.add_argument("--no-run", action="store_true", help="Only (re)deploy the agents")
    args = parser.parse_args()

    if not config.PROJECT_CONNECTION_STRING:
        sys.exit("❌ PROJECT_CONNECTION_STRING not set. Run setup/deploy.sh first!")

    org, repo, branch = args.org, args.repo, args.branch
    if not (org and repo) and not args.no_run:
        try:
            cfg = config.load_repos_config()
            customer = next(c for c in cfg["customers"] if c.get("enabled", True))
            first = next(r for r in customer["repos"] if r.get("active", True))
            org, repo, branch = customer["org"], first["name"], first.get("default_branch")
        except (FileNotFoundError, StopIteration):
            sys.exit("Pass --org and --repo (or run discovery/discover_repos.py first)")

    print("=== Deploying agents ===")
    analyst = CodeAnalystAgent().ensure(recreate=args.recreate)
    tracker = ChangeTrackerAgent(client=analyst.client).ensure(recreate=args.recreate)
    if args.no_run:
        return

    print(f"\n=== bc-code-analyst: documenting {org}/{repo} ===")
    result = analyst.document(org, repo, branch)
    print(result.text)
    print(f"\n  tokens in/out: {result.input_tokens}/{result.output_tokens}, tool calls: {result.tool_calls}")

    if args.since:
        print(f"\n=== bc-change-tracker: changes since {args.since[:7]} ===")
        verdict, res = tracker.track(org, repo, args.since, branch=branch)
        print(json.dumps(verdict.data, indent=2, ensure_ascii=False))
        print(verdict.changelog_md)
        print(f"\n  tokens in/out: {res.input_tokens}/{res.output_tokens}, tool calls: {res.tool_calls}")

    # Agents stay deployed on purpose — the orchestrator reuses them by name.
    analyst.client.close()


if __name__ == "__main__":
    main()
