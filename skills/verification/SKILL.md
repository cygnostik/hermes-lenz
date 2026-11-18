---
name: verification
description: Verify factual claims or draft content using the Lenz fact-checking tools.
---

# Lenz verification

Use Lenz when fact-checking is requested or verification would materially help an evidence-based answer. Each request sends its supplied text or URL to Lenz; do not send private information, secrets or unrelated conversation history. No tool verifies responses automatically. Call `lenz_policy` to see the current policy, per-request limits, and estimated maximum credit costs. These are limits on each request, not daily or cumulative budgets.

Use `lenz_extract` to enumerate claims without assessment charges. Use `lenz_assess` for quick assessments (one credit per checked claim), `lenz_verify` for a capped asynchronous review of one claim (at most one assessment and one conditional deep check), or `lenz_review` for an asynchronous draft review with mode-specific assessment, escalation and citation caps. Only set `critical` when the user or context establishes that the material is high stakes; in critical-only mode it is required. Do not treat an assessment's searched pages as verified citations. The API's No Public Record verdict is not a finding of falsity. If a check fails, is pending, needs input, or is partially complete, say so explicitly and do not represent it as verified. Poll with `lenz_status` rather than resubmitting jobs. Carefully cite and distinguish the actual source evidence from Lenz's assessment.

Every submission returns `idempotency_key`, including uncertain failures. If retrying the same submission within 24 hours, pass the same UUIDv4 as `idempotency_key` with exactly the same input and mode; a new key can cause a duplicate charge. Do not automatically retry paid requests.
