# Lenz for Hermes Agent

An opt-in, model-directed fact-checking plugin for Hermes Agent 0.23.2 or newer. It provides Lenz claim extraction, quick assessment, capped draft review, a capped one-claim deep-check workflow, job status, account usage, and policy tools. It uses the documented HTTPS API at `https://lenz.io/api/v1` with `X-Lenz-API-Version: 2026-10-11`.

## Privacy, costs, and operational limits

Only a tool invocation sends the selected text, claims, or URL to Lenz. The plugin does not register hooks and never automatically transmits every prompt, response, or conversation. Requests may contain sensitive text; decide what to submit before invoking a tool. Network calls go to `lenz.io` and may be billed against your Lenz account. Only HTTPS is used, redirects are refused, no API key or response body is logged, and errors do not echo provider response bodies. Credentials are read through Hermes's profile-scoped `agent.secret_scope.get_secret`, never read from files by this plugin. There are no shell commands, telemetry, background tasks, self-updates, or plugin dependencies. Reviews request private visibility and explicitly disable account-default webhooks. Consult Lenz's own retention terms and billing details.

Extraction costs no credits subject to Lenz's fair-use limits. Quick checks cost up to one credit per assessed claim, deep checks cost up to five credits at low depth or ten at standard depth, and citation checks up to one credit per citation. Costs and API behavior may change; see [Lenz API](https://lenz.io/api/v1/docs/). A temporary network error after submission may mean a job was created and charged. Every work-submission call generates an opaque UUIDv4 idempotency key (or accepts the UUIDv4 supplied as `idempotency_key`) and returns it even on timeout. Lenz retains these keys for 24 hours. To retry the same operation safely within that window, use the returned key with the identical input and mode so the request body is unchanged; a different body may be rejected, and a new key can create another charge. A 409 can mean a request is still being created: retry with the same key. After the 24-hour deduplication window, check account activity before retrying. The plugin does not automatically retry paid requests.

Modes cap **each request**, not a session, day, account, or aggregate spend. A user or agent can submit repeated requests. Use Lenz's account-level spending and credit controls for an overall budget. Maximum review credits are conservative estimates using the published rates:

| Mode | Assessments | Deep checks | Depth | Citation checks | Max review credits |
| --- | ---: | ---: | --- | ---: | ---: |
| heavy | 20 | 5 | standard | 4 | 74 |
| normal (default) | 10 | 2 | standard | 2 | 32 |
| moderate | 5 | 1 | low | 0 | 10 |
| light | 2 | 0 | low | 0 | 2 |
| critical-only | 3 | 1 | standard | 0 | 13 |

Critical-only requires `critical: true`; that flag reflects the caller's judgment and is not automatic classification. Direct assessment rejects more claims than the selected cap. In light mode the deep-check tool is unavailable. The single-claim `lenz_verify` tool calls `/review` with server-side limits of one assessment and one conditional deep check: maximum 11 credits at standard depth or 6 at low depth. A deep check only occurs when Lenz finds an assessable claim and its escalation conditions match. This avoids uncapped fanout from an ambiguous `/verify` input. The caps are deliberately explicit and are not Lenz account spending limits.

Completed quick assessment is not a deep verified citation; an outcome of **No Public Record** does not mean the claim is false. Async `queued`, `processing`, `needs_input`, `failed`, and `cancelled` jobs are not verdicts. `lenz_status` exposes their original status and result. This version does not resolve Lenz's `needs_input` state or automatically poll, cancel, or retry. Review the returned evidence before making decisions. HTTP, network, invalid-config and credential errors fail without returning a fabricated verdict. No claims of exhaustive review or proof are made.

## Install and configure

Copy this directory into the target profile's `~/.hermes/plugins/lenz/`. Set `LENZ_API_KEY` through Hermes's supported credentials interface for that profile; never add a key to this plugin or README. Enable with `hermes plugins enable lenz`, then restart the gateway or start a new Hermes session. Configure `plugins.entries.lenz.settings.mode` in `~/.hermes/config.yaml` or the plugin settings UI:

```yaml
plugins:
  enabled:
    - lenz
  entries:
    lenz:
      settings:
        mode: normal  # heavy | normal | moderate | light | critical-only
```

Preserve any existing plugin settings and enabled entries when applying the example. Invalid modes fail closed with an error. Call `lenz_policy` to inspect the live policy. Tools are model-directed: `lenz_extract`, `lenz_assess`, `lenz_verify`, `lenz_review`, `lenz_status`, and `lenz_usage`. `lenz_verify` and `lenz_review` return asynchronous review IDs; use `lenz_status` with `kind: review` and the ID. `lenz_status` can also inspect verification IDs created elsewhere using `kind: verification`. `lenz:verification` is the bundled Hermes skill.

## Validation

```sh
python3 -m unittest discover -s tests -v
hermes plugins validate . --install-deps
```

Unit tests mock network requests and do not require credentials or incur charges. A live Lenz integration test requires a user-provided key and may incur credits. No public catalog submission has been made; catalog publication additionally requires a public repository and a reviewed exact 40-character commit pin.
