"""
orchestration/create_workflow_agent.py — Register the two agents as a Foundry *Workflow* agent.

The production path is run_pipeline.py (Python orchestration), because Foundry workflows cannot
execute local FunctionTools. This script exists so the collaboration is also visible and testable
in the Foundry portal (Build → Agents → Workflows → Preview / Traces): paste a change-data JSON or
an analysis JSON into the playground and the two agents run in sequence without tool calls.

Usage:
    python orchestration/create_workflow_agent.py            # create/update the workflow agent
    python orchestration/create_workflow_agent.py --invoke   # also run it once (background poll)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import config  # noqa: E402

WORKFLOW_AGENT_NAME = os.getenv("WORKFLOW_AGENT_NAME") or "bc-documentation-workflow"


def workflow_yaml(name: str) -> str:
    return (
        "kind: Workflow\n"
        f"name: {name}\n"
        "description: BC Deployment Analyzer - change tracking then documentation of a PTE repository\n"
        "trigger:\n"
        "  kind: OnConversationStart\n"
        "  id: trigger_start\n"
        "  actions:\n"
        "    - kind: InvokeAzureAgent\n"
        "      id: step_track_changes\n"
        "      agent:\n"
        f"        name: {config.CHANGE_TRACKER_AGENT_NAME}\n"
        "      conversationId: =System.ConversationId\n"
        "      input:\n"
        '        messages: ""\n'
        "      output:\n"
        "        autoSend: true\n"
        "    - kind: InvokeAzureAgent\n"
        "      id: step_document\n"
        "      agent:\n"
        f"        name: {config.CODE_ANALYST_AGENT_NAME}\n"
        "      conversationId: =System.ConversationId\n"
        "      input:\n"
        '        messages: ""\n'
        "      output:\n"
        "        autoSend: true\n"
        "    - kind: EndConversation\n"
        "      id: step_end\n"
    )


def create_workflow_agent(name: str) -> str:
    from azure.ai.projects import AIProjectClient
    from azure.ai.projects.models import WorkflowAgentDefinition
    from azure.identity import DefaultAzureCredential

    client = AIProjectClient(endpoint=config.PROJECT_CONNECTION_STRING, credential=DefaultAzureCredential(), allow_preview=True)
    result = client.agents.create_version(
        agent_name=name,
        definition=WorkflowAgentDefinition(workflow=workflow_yaml(name)),
        description="BC Deployment Analyzer workflow: bc-change-tracker → bc-code-analyst",
    )
    print(f"  Workflow agent {result.name} version {result.version} — visible in Foundry portal → Build → Agents (kind: workflow)")
    client.close()
    return result.name


def invoke_workflow(name: str) -> str:
    """Run the workflow once with a bundled analysis so no GitHub access is needed."""
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    sample = config.load_json(config.EVALUATION_DIR / "evaluation_dataset.json")
    case = next(c for c in sample["cases"] if c["agent"] == "code_analyst")
    query = (
        "The analysis JSON is provided below — do NOT call any tools. First summarise the change impact as if this were "
        "a first-time documentation run, then return the complete Section 3 entry in Swedish.\n\n"
        + json.dumps(case["input"]["analysis"], ensure_ascii=False)
    )

    client = AIProjectClient(endpoint=config.PROJECT_CONNECTION_STRING, credential=DefaultAzureCredential(), allow_preview=True)
    openai_client = client.get_openai_client()
    conversation = openai_client.conversations.create()
    resp = openai_client.responses.create(
        conversation=conversation.id,
        extra_body={"agent_reference": {"name": name, "type": "agent_reference"}},
        input=query,
        background=True,
    )
    print(f"  Submitted run {resp.id} (status {resp.status})")
    text = ""
    for attempt in range(15):
        time.sleep(8)
        r = openai_client.responses.retrieve(resp.id)
        print(f"  [{attempt + 1}] status={r.status}")
        if r.status in ("completed", "failed", "cancelled"):
            text = r.output_text or ""
            break
    print(text or "  (no text output via API — open the run under Traces in the portal)")
    openai_client.conversations.delete(conversation_id=conversation.id)
    client.close()
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", default=WORKFLOW_AGENT_NAME)
    parser.add_argument("--invoke", action="store_true")
    args = parser.parse_args()
    if not config.PROJECT_CONNECTION_STRING:
        sys.exit("❌ PROJECT_CONNECTION_STRING not set. Run setup/deploy.sh first!")

    print("=== Ensuring the two agents exist ===")
    from agents.agents import ChangeTrackerAgent, CodeAnalystAgent

    analyst = CodeAnalystAgent().ensure()
    ChangeTrackerAgent(client=analyst.client).ensure()
    analyst.client.close()

    print("=== Creating workflow agent ===")
    name = create_workflow_agent(args.name)
    if args.invoke:
        print("=== Invoking workflow ===")
        invoke_workflow(name)


if __name__ == "__main__":
    main()
