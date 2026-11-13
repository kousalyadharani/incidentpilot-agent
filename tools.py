"""Synthetic incident data and server-side allowlisted agent tools."""

from __future__ import annotations

from collections import Counter

ALLOWED_ACTIONS = {
    "rollback-last-deploy": "Simulate rollback of the last deployment",
    "restart-auth-api": "Simulate restart of the auth API",
    "scale-api-gateway": "Simulate adding one API gateway replica",
}

SCENARIOS = {
    "auth-5xx": {
        "title": "Auth API 5xx after deployment",
        "description": "Authentication errors rose shortly after a deployment. Checkout and login reports are increasing.",
        "focus_service": "auth-api",
        "runbook_query": "5xx after deployment",
        "suggested_action": "rollback-last-deploy",
        "proposal_reason": "The auth API is degraded and matching 5xx errors appear in the selected synthetic logs. Verify the release and rollback criteria first.",
        "services": {
            "api-gateway": {"status": "healthy", "summary": "p95 latency 180 ms; error rate 0.3%"},
            "auth-api": {"status": "degraded", "summary": "5xx rate 12.4%; p95 latency 2.8 s"},
            "orders-api": {"status": "healthy", "summary": "p95 latency 240 ms; error rate 0.2%"},
            "database": {"status": "healthy", "summary": "connections 42/200; query p95 28 ms"},
            "queue": {"status": "healthy", "summary": "depth 18; oldest message 0.4 s"},
        },
        "logs": [
            "09:14:02Z INFO api-gateway request_id=req-a1 route=/login status=200 duration_ms=102",
            "09:14:07Z ERROR auth-api request_id=req-a2 route=/token/refresh status=502 error=upstream_timeout",
            "09:14:10Z ERROR auth-api request_id=req-a3 route=/login status=503 error=connection_pool_exhausted",
            "09:15:01Z INFO deploy service=auth-api version=2.8.1 actor=release-bot",
            "09:15:14Z ERROR auth-api request_id=req-a4 route=/token/refresh status=502 error=upstream_timeout",
            "09:16:45Z ERROR auth-api request_id=req-a5 route=/login status=503 error=connection_pool_exhausted",
            "09:17:03Z INFO database query_p95_ms=29 active_connections=43",
        ],
    },
    "gateway-latency": {
        "title": "Elevated API gateway latency",
        "description": "Several clients report slow responses. The gateway p95 has increased, while downstream health is unclear.",
        "focus_service": "api-gateway",
        "runbook_query": "high latency",
        "suggested_action": "scale-api-gateway",
        "proposal_reason": "The synthetic gateway latency is elevated. Confirm load and capacity limits before considering a scale-out.",
        "services": {
            "api-gateway": {"status": "degraded", "summary": "p95 latency 2.1 s; CPU 91%; error rate 1.8%"},
            "auth-api": {"status": "healthy", "summary": "p95 latency 210 ms; error rate 0.2%"},
            "orders-api": {"status": "healthy", "summary": "p95 latency 260 ms; error rate 0.4%"},
            "database": {"status": "healthy", "summary": "connections 58/200; query p95 31 ms"},
            "queue": {"status": "healthy", "summary": "depth 24; oldest message 0.7 s"},
        },
        "logs": [
            "10:02:01Z WARN api-gateway route=/catalog duration_ms=2030 status=200",
            "10:02:14Z WARN api-gateway route=/orders duration_ms=2190 status=200",
            "10:03:08Z INFO auth-api p95_ms=210 error_rate=0.2",
            "10:03:22Z WARN api-gateway cpu_percent=91 active_requests=884",
            "10:04:11Z INFO database query_p95_ms=31 active_connections=58",
        ],
    },
    "database-pool": {
        "title": "Database connection pool pressure",
        "description": "A backend service reports intermittent database connection errors; determine whether the database itself is unhealthy.",
        "focus_service": "database",
        "runbook_query": "database connection errors",
        "suggested_action": "restart-auth-api",
        "proposal_reason": "The sample shows a pool pressure signal. Check client pool configuration and connection ownership before any restart.",
        "services": {
            "api-gateway": {"status": "healthy", "summary": "p95 latency 190 ms; error rate 0.4%"},
            "auth-api": {"status": "degraded", "summary": "pool wait 1.6 s; connection errors 8.1%"},
            "orders-api": {"status": "healthy", "summary": "pool wait 20 ms; connection errors 0.1%"},
            "database": {"status": "healthy", "summary": "connections 76/200; query p95 35 ms"},
            "queue": {"status": "healthy", "summary": "depth 21; oldest message 0.6 s"},
        },
        "logs": [
            "11:20:04Z ERROR auth-api pool=primary error=acquire_timeout wait_ms=1500",
            "11:20:11Z INFO database connections=76 max_connections=200",
            "11:20:45Z ERROR auth-api pool=primary error=connection_refused retries=2",
            "11:21:02Z INFO orders-api pool=primary acquire_wait_ms=20",
            "11:21:30Z ERROR auth-api pool=primary error=acquire_timeout wait_ms=1500",
        ],
    },
}

def run_tool(name: str, arguments: dict, scenario_id: str) -> dict:
    scenario = SCENARIOS.get(scenario_id)
    if scenario is None:
        raise ValueError("Unknown synthetic incident scenario.")
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be an object.")

    if name == "inspect_service_health":
        service = arguments.get("service")
        if service not in scenario["services"]:
            raise ValueError("Unknown service for this synthetic environment.")
        return {"service": service, **scenario["services"][service]}

    if name == "analyze_logs":
        service = arguments.get("service")
        if service not in scenario["services"]:
            raise ValueError("Unknown service for this synthetic environment.")
        matches = [line for line in scenario["logs"] if f" {service} " in line]
        errors = [line for line in matches if " ERROR " in line]
        return {
            "service": service,
            "line_count": len(matches),
            "error_count": len(errors),
            "error_signatures": dict(Counter(line.split("error=")[-1] for line in errors)),
            "sample_lines": matches[:5],
        }

    if name == "propose_remediation":
        action = arguments.get("action")
        if action not in ALLOWED_ACTIONS:
            raise ValueError("Action is not in the remediation allowlist.")
        reason = arguments.get("reason", "")
        return {"action": action, "label": ALLOWED_ACTIONS[action], "reason": str(reason)[:400], "status": "requires human approval"}

    raise ValueError("Tool is not available.")
