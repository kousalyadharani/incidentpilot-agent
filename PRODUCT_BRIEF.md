# IncidentPilot — product brief

## Product statement

IncidentPilot helps an on-call engineer turn a noisy, small incident into a reviewable next step. An agent can inspect a fixed sandbox, but the operator can see every tool call and must approve any simulated remediation.

## User problem hypothesis

During an incident, responders may need to correlate service health, log signals, and runbook guidance while avoiding premature changes. A chat-only assistant can hide how it reached a conclusion or overstate what the evidence proves. A bounded agent with a visible trace and an approval gate may make that workflow easier to review.

This is a product hypothesis. The prototype has not been tested with on-call engineers.

## Primary user

Software engineer or incident commander triaging a service alert in a small or medium engineering team.

## Core workflow

1. Pick a fictional incident or add a short operator note.
2. The agent reads synthetic health, logs, and runbook snippets through allowlisted tools.
3. It states an assessment, supporting evidence, uncertainty, and a safe next step.
4. It may create a pending remediation proposal.
5. A human approves or rejects; approval records a simulation only.

## Product requirements

- Every observation must come from scenario data or a returned tool result.
- The agent must distinguish evidence from inference and disclose uncertainty.
- Tool access must be explicit, narrowly scoped, and server-validated.
- The model must not execute arbitrary commands or modify external systems.
- Remediation proposals require a separate human action.
- Offline mode must demonstrate the workflow without credentials or a model call.
- The application must disclose that live mode sends incident text to the configured model provider.
- The prototype must not request secrets or real customer information.

## Success measures to validate

These are evaluation targets, not achieved results:

- In scripted scenarios, reviewers can trace each claim to a visible tool result.
- The agent abstains from proposing changes when the relevant service evidence is healthy or incomplete.
- Reviewers correctly understand that approving a proposal only records a simulation.
- Operators can identify the next safe step from the result without reading raw logs first.
- Tool-call count and request size remain within explicit limits.

## Evaluation plan

Prepare 10–15 fictional incidents with expected evidence and a rubric. Include straightforward cases, misleading symptoms, incomplete data, and conflicting signals. Measure evidence attribution, unsafe proposal rate, abstention quality, and reviewer comprehension. Have a human reviewer label every failure; do not optimize only for producing an answer. Before any production use, evaluate against real incident data under an approved privacy and security process.

## Risks and controls

| Risk | Prototype control |
|---|---|
| Unsupported root-cause claims | Prompt requests uncertainty; UI shows evidence and limits |
| Unsafe action suggestion | Allowlisted actions; all proposals require a human decision |
| Excessive model autonomy | No shell, arbitrary network, or production integration tools |
| Secret exposure | UI warning; API key stays on server; live mode is explicit |
| Confusing demo with real operations | Synthetic labels and simulation-only approval result |
| Stale or weak runbook advice | Bundled example only; no claim of organization-specific guidance |

## Scope exclusions

- Connecting to production observability, cloud accounts, routers, or deployment systems.
- Automatic remediation or on-call paging.
- Persistent user accounts, conversation storage, or telemetry.
- Claiming a root cause or service-level improvement without evaluation.

## Next steps

1. Validate the interaction with 5–8 engineers using scenario walkthroughs.
2. Add an evaluation corpus and report failure categories before expanding tools.
3. Review privacy, security, accessibility, and human approval design.
4. Consider read-only integrations only after the bounded sandbox is validated.
