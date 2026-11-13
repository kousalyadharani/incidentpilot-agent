# Synthetic incident runbooks

## Elevated 5xx after a release
Source: RB-DEPLOY-5XX

Compare error rate and latency before and after the release. Check dependency health and inspect the release diff. Verify that the service version and affected routes line up with the observed failures. Use the team's established rollback criteria, confirm the expected blast radius, and record the approver and incident impact. A timing correlation alone does not prove the release caused the issue. Do not roll back automatically.

## Elevated request latency
Source: RB-LATENCY

Compare latency by route and service. Separate application processing time from downstream waits. Check saturation signals such as CPU, memory, active requests, and connection pools alongside traffic volume. Compare healthy and degraded dependencies. Consider a capacity change only after confirming the bottleneck, checking limits, and agreeing on a rollback plan. Do not infer that adding replicas will fix a downstream bottleneck.

## Database connection pool pressure
Source: RB-DB-POOL

Separate database server capacity from client-side pool exhaustion. Compare total database connections with the configured maximum, then compare acquisition wait and connection errors across clients. Check for recent pool-size changes, leaked connections, retry amplification, and connection churn. Avoid restarting a shared database while it is healthy; first identify which client is exhausting or misusing its pool.

## Authentication API errors
Source: RB-AUTH

Compare authentication route failures by status code and error signature. Check the auth service health, gateway observations, identity provider dependency, database connection acquisition, and release timeline. A healthy database snapshot does not rule out a client-side connection-pool issue. Keep account identifiers, tokens, cookies, and credentials out of incident notes and diagnostic prompts.

## Incident evidence and approval
Source: RB-EVIDENCE

Label each statement as an observed signal, a likely explanation, or an unverified hypothesis. Prefer a safe next observation when evidence conflicts or is incomplete. A human approver should verify the target, expected impact, change window, and rollback criteria before a production action. A proposal is not an execution record. Document the decision and outcome separately.
