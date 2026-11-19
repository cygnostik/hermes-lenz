# Lenz for Hermes Agent

Use Lenz to screen a claim, investigate a doubtful fact, or check a draft before publication. Start with a local preview: you see the maximum credit cost before any claim leaves Hermes.

## Install and connect

From the reviewed branch checkout, in the target Hermes profile:

```sh
hermes plugins install "file://$PWD" --ref "$(git rev-parse HEAD)" --no-enable
hermes plugins enable lenz
```

The local Git source warning is expected. Review the source before enabling it. Use `hermes -p NAME plugins …` for a named profile. No SDK, MCP server, plugin dependency or additional Desktop pane is needed.

1. Get your own key from [Lenz API credentials](https://lenz.io/api-credentials). Enter it **only in the masked installer prompt in your own terminal**, or skip the prompt and save it in the target profile’s Lenz plugin settings under **Lenz API key**. Hermes stores `LENZ_API_KEY` in that profile’s credential environment, not in plugin settings YAML. Don’t put it in chat, commands or this checkout.
2. Start a fresh Hermes session. Ask **“Preview a quick check of ‘Earth has one natural moon.’ Don’t send it.”** You should get a maximum of **1 credit**, with nothing submitted. This works without a key.
3. Ask **“Show my Lenz balance and reset.”** This calls `/me/usage` without sending claim text or spending credits. A rejected key needs replacing in the same masked field; restart the session after changing it. Revoke compromised keys on the Lenz credentials page.

## Pick a check

| Request | Tool | What the maximum buys |
|---|---|---|
| Which statements could I check? | `lenz_extract` | 0 credits, subject to daily fair use. A list, not a verdict. |
| Is this worth investigating? | `lenz_assess` | 1 credit per list item. A quick verdict, confidence and searched pages, not verified citations. |
| Check this one claim against sources | `lenz_verify` | One assessment plus at most one deep check via `/review`: 6 at low depth or 11 at standard. |
| Check a draft and its citations | `lenz_review` | Assessment + conditional deep checks + citations, bounded by mode below. Unchecked material may remain. |

For any submission, preview first, review the exact text or URL and maximum, then tell Hermes whether to send it. A preview expires after 15 minutes. A new or changed check needs new consent. `lenz_policy` explains the current mode without a network call. Choose **Check depth and draft limits** in the plugin settings:

| Mode | Assessments | Deep checks | Depth | Citations | Max per draft |
|---|---:|---:|---|---:|---:|
| light | 2 | 0 | none | 0 | 2 |
| moderate | 5 | 1 | low | 0 | 10 |
| normal (default) | 10 | 2 | standard | 2 | 32 |
| heavy | 20 | 5 | standard | 4 | 74 |
| critical-only | 3 | 1 | standard | 0 | 13 |

Critical-only requires explicit `critical: true`. A queued review is a receipt, not a verdict. `lenz_status` takes `kind: review` and the returned ID (also supports existing verification task IDs with `kind: verification`). Check the same ID later. If input is needed, resolve it in Lenz. Failed rows, rewritten text and “No Public Record” are not proof of falsity. Read the evidence, not just the label.

## What the 500-credit monthly budget means

The plugin reserves at most **500 Lenz credits per profile per provider period**. This is a ceiling on submissions, not credits supplied by Hermes or a prediction of your bill. It does not depend on a plan name. The shared account balance includes any extra credits, and spending on the website, MCP, other keys or profiles can reduce it. Hermes model usage is separate. The plugin never purchases credits or enables overages.

Before any content submission it reads the live balance, reset and applicable unit prices from the same credential. It requires the supported prices, a known balance, and a future reset with a timezone. Spendable room is the lesser of live remaining and the local unreserved room. The first paid reservation starts with at most the then-available balance; later lower balances can tighten that ceiling. A top-up or refund does not expand it mid-period. No credit carries forward locally. The next period opens only after the last boundary passes **and** Lenz reports a later reset. A clock change, account switch or unexpected reset can cause a safe refusal. Use a dedicated profile per account.

The full maximum counts, including partial results, HTTP failures after dispatch, and timeouts. It is not billed usage. Parallel calls reserve atomically before sending. Paid IDs cannot be sent twice, even across restarts or resets. The ledger counts the period of admission, not when an async job settles. Shared balance can change between reading it and submission; Lenz has the final say. On uncertainty, inspect Lenz activity or poll a known ID. Do not start a new job just to recover a receipt.

State is in `lenz-budget/monthly.sqlite3` under the active Hermes home, outside the plugin install. It stores amounts, reset times, opaque IDs and expiring preview tags, **not** claims, results or keys. Disabling, reinstalling or rotating a key does not replenish it. Preserve this state with the profile; another home, deletion, rollback or manual edits are outside the enforcement boundary. The plugin enforces matching preview, amount and budget; the agent must still get the user’s agreement. It does not authenticate a human click.

## Privacy and compatibility

Only the selected input goes to [Lenz](https://lenz.io/privacy). A public URL asks Lenz to fetch it. Reviews request private deep checks and an empty webhook URL to suppress default webhooks. Extraction and list assessment do not expose those switches. Private visibility does not mean zero retention. Hermes itself can retain tool inputs and results in chat history. No automatic prompt interception, background polling, telemetry, redirects or automatic resubmission.

Native HTTPS targets `https://lenz.io/api/v1` with the [2026-10-11 contract](https://lenz.io/docs/api-versions). [Plans](https://lenz.io/plans) and [terms](https://lenz.io/terms) describe provider allowances; `lenz_usage` reports the connected account. Existing tool names and mode settings are retained. **Migration:** old calls without `approved_credits` now preview only. To send, use that preview's ID and maximum; do not replay old requests. Settings are profile-owned. Disable with `hermes plugins disable lenz`.

Offline tests: `python3 -m unittest discover -s tests -v`. Validate the clean plugin checkout with `hermes plugins validate . --install-deps`. This private engineering branch is not a catalog listing.
