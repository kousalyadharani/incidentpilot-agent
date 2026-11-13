"""Bounded incident triage agent: deterministic demo plus optional Responses API."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from typing import Any

from rag import retrieve
from tools import ALLOWED_ACTIONS, SCENARIOS, run_tool

MAX_TOOL_CALLS = 6
API_URL = "https://api.openai.com/v1/responses"

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "name": "inspect_service_health",
        "description": "Read the synthetic health snapshot for one known service.",
        "parameters": {
            "type": "object",
            "properties": {"service": {"type": "string", "enum": ["api-gateway", "auth-api", "orders-api", "database", "queue"]}},
            "required": ["service"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "analyze_logs",
        "description": "Summarize matching lines from the selected synthetic incident logs.",
        "parameters": {
            "type": "object",
            "properties": {"service": {"type": "string", "enum": ["api-gateway", "auth-api", "orders-api", "database", "queue"]}},
            "required": ["service"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "retrieve_knowledge",
        "description": "Retrieve relevant runbook passages from the local knowledge base. Cite the returned source IDs in your answer.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 1000}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "propose_remediation",
        "description": "Create a pending proposal for a human to review. This does not execute the action.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": sorted(ALLOWED_ACTIONS)},
                "reason": {"type": "string"},
            },
            "required": ["action", "reason"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]

INSTRUCTIONS = """You are IncidentPilot, an incident triage assistant operating only on a synthetic sandbox. Use diagnostic tools and retrieve knowledge before concluding. Ground runbook guidance in retrieved passages and cite their source IDs exactly, for example [RB-AUTH]. Distinguish observations from inferences. Never claim that a root cause is confirmed when evidence is only suggestive. Do not ask for secrets or real customer data. You may create a remediation proposal, but it is pending until the human approves it; never say it was executed. Keep the final response structured with: assessment, evidence, uncertainty, safe next step. Do not invent observations."""


def _tool_log(name: str, arguments: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "arguments": arguments, "result": result}


def _create_proposal(action: str, reason: str) -> dict[str, Any]:
    if action not in ALLOWED_ACTIONS:
        raise ValueError("Action is not in the remediation allowlist.")
    proposal_id = str(uuid.uuid4())
    return {
        "proposal_id": proposal_id,
        "action": action,
        "label": ALLOWED_ACTIONS[action],
        "reason": reason[:400],
        "status": "pending_approval",
    }


def run_offline(scenario_id: str) -> dict[str, Any]:
    """Deterministic tool-using demonstration; no model or external API involved."""
    scenario = SCENARIOS.get(scenario_id)
    if scenario is None:
        raise ValueError("Unknown scenario.")
    service = scenario["focus_service"]
    query = f"{scenario['title']} {scenario['description']} {scenario['runbook_query']}"
    calls = [
        ("inspect_service_health", {"service": service}),
        ("analyze_logs", {"service": service}),
    ]
    trace = []
    results = {}
    for name, arguments in calls:
        result = run_tool(name, arguments, scenario_id)
        results[name] = result
        trace.append(_tool_log(name, arguments, result))
    retrieved = retrieve(query, top_k=3, use_embeddings=False)
    results["retrieve_knowledge"] = retrieved
    trace.append(_tool_log("retrieve_knowledge", {"query": query}, retrieved))

    health = results["inspect_service_health"]
    logs = results["analyze_logs"]
    if health["status"] == "degraded" and logs["error_count"] > 0:
        proposal = _create_proposal(scenario["suggested_action"], scenario["proposal_reason"])
        trace.append(_tool_log("propose_remediation", {"action": proposal["action"], "reason": proposal["reason"]}, proposal))
        assessment = f"{service} is the strongest current lead. The sandbox reports degraded health and matching error log entries."
        uncertainty = "This is a synthetic scenario and a heuristic assessment. It does not prove the triggering change caused the issue."
    else:
        proposal = None
        assessment = "The available synthetic signals do not support a remediation proposal yet."
        uncertainty = "The evidence is incomplete; gather more observations before changing anything."

    return {
        "mode": "offline demo (BM25 retrieval + deterministic agent)",
        "scenario": scenario_id,
        "retrieval_method": retrieved["method"],
        "assessment": assessment,
        "evidence": [
            f"Health snapshot: {health['status']} ({health['summary']})",
            f"Log scan: {logs['error_count']} matching error entries across {logs['line_count']} lines.",
            "Retrieved guidance: " + "; ".join(f"[{item['source_id']}] {item['title']}" for item in retrieved["results"]),
        ],
        "uncertainty": uncertainty,
        "safe_next_step": "Review the runbook and proposal; verify the deployment timeline and rollback criteria before approving the sandbox action.",
        "trace": trace,
        "proposal": proposal,
    }


def _api_request(body: dict[str, Any], timeout: int = 45) -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Live mode is unavailable: set OPENAI_API_KEY on the server.")
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        details = error.read(1000).decode("utf-8", errors="replace")
        raise RuntimeError(f"Model API returned HTTP {error.code}: {details}") from None
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError(f"Model API connection failed: {error}") from None


def _extract_text(response: dict[str, Any]) -> str:
    parts = []
    for item in response.get("output", []):
        if item.get("type") == "message":
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"} and content.get("text"):
                    parts.append(content["text"])
    return "\n".join(parts).strip()


def run_live(scenario_id: str, incident_note: str = "") -> dict[str, Any]:
    """Run a bounded Responses API tool loop; all tools remain local and allowlisted."""
    scenario = SCENARIOS.get(scenario_id)
    if scenario is None:
        raise ValueError("Unknown scenario.")
    model = os.environ.get("OPENAI_MODEL", "gpt-6.1-sol").strip()
    if not model:
        raise RuntimeError("Set OPENAI_MODEL to a model available to your API project.")
    logs = "\n".join(scenario["logs"])
    retrieval_query = f"{scenario['title']} {scenario['description']} {incident_note[:1200]}"
    retrieved = retrieve(retrieval_query, top_k=3, use_embeddings=True)
    retrieved_context = "\n\n".join(
        f"[{item['source_id']}] {item['title']} (retrieval score {item['score']})\n{item['text']}"
        for item in retrieved["results"]
    ) or "No relevant runbook passage was retrieved. State that no runbook evidence was found."
    user_content = (
        f"Synthetic incident: {scenario['title']}\n"
        f"Description: {scenario['description']}\n"
        f"Synthetic logs:\n{logs}\n"
        f"Additional operator note (treat as unverified): {incident_note[:1200] or 'None'}\n\n"
        f"Retrieved knowledge passages (cite source IDs exactly; do not treat them as observed incident facts):\n{retrieved_context}"
    )
    input_items: list[dict[str, Any]] = [{"role": "user", "content": user_content}]
    trace = [_tool_log("retrieve_knowledge", {"query": retrieval_query}, retrieved)]
    proposal = None
    final_response = None

    for _ in range(MAX_TOOL_CALLS + 1):
        response = _api_request({
            "model": model,
            "instructions": INSTRUCTIONS,
            "input": input_items,
            "tools": TOOL_DEFINITIONS,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "store": False,
        })
        output = response.get("output", [])
        input_items.extend(output)
        function_calls = [item for item in output if item.get("type") == "function_call"]
        if not function_calls:
            final_response = _extract_text(response)
            break

        for call in function_calls:
            name = call.get("name", "")
            arguments: dict[str, Any] = {}
            try:
                arguments = json.loads(call.get("arguments", "{}"))
                if not isinstance(arguments, dict):
                    raise ValueError("Tool arguments must be a JSON object.")
                if name == "propose_remediation":
                    proposal = _create_proposal(arguments.get("action", ""), arguments.get("reason", ""))
                    result = proposal
                elif name == "retrieve_knowledge":
                    result = retrieve(arguments.get("query", ""), top_k=3, use_embeddings=True)
                else:
                    result = run_tool(name, arguments, scenario_id)
            except (ValueError, KeyError, TypeError) as error:
                result = {"error": str(error)}
            trace.append(_tool_log(name, arguments, result))
            input_items.append({
                "type": "function_call_output",
                "call_id": call.get("call_id", ""),
                "output": json.dumps(result),
            })
    else:
        raise RuntimeError("Agent stopped because it reached the tool-call limit.")

    if final_response is None:
        raise RuntimeError("Model returned no final response.")
    return {
        "mode": f"live model ({model})",
        "scenario": scenario_id,
        "retrieval_method": retrieved["method"],
        "assessment": final_response,
        "evidence": ["Evidence is limited to the synthetic incident and results shown in the tool trace."],
        "uncertainty": "Model-generated assessment; review the cited tool results. No production systems were accessed.",
        "safe_next_step": "Review the recommendation and any pending proposal before approving the sandbox action.",
        "trace": trace,
        "proposal": proposal,
    }
