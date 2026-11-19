# Lenz for Hermes

Hand Hermes a draft and ask it to flag the numbers, dates, and quotes that need checking. Use Lenz to check a few claims, investigate a disputed one, or review the draft and its citations. You see the most a check can cost before you decide what to send.

![Lenz for Hermes with an installed tool preview showing one credit maximum and nothing sent](docs/media/readme-hero.png)

## Try it without a key

In a fresh Hermes session with Lenz enabled, ask:

> Preview a quick check of “Earth has one natural moon.” Don’t send it.

Expect a **one-credit maximum** and **nothing sent**. The estimate is local. It is not a fact-check result, and it does not use Lenz credits.

## Install and connect

Lenz is a native Hermes Agent plugin, not an MCP server. It requires Hermes **0.23.2 or newer** and has no extra plugin dependencies. It was tested on macOS with an isolated Hermes profile.

Install from the public repository, or see [Releases](https://github.com/cygnostik/hermes-lenz/releases) for an exact commit to pin:

```sh
hermes plugins install https://github.com/cygnostik/hermes-lenz --no-enable
hermes plugins enable lenz
```

Read the custom-source trust prompt. To pin a revision, add `--ref` followed by the full 40-character commit SHA, not a version tag. For a named profile, use `hermes -p NAME` for both commands. Start a new session in that profile after enabling the plugin.

1. Create your own key at [Lenz API credentials](https://lenz.io/api-credentials).
2. In Hermes Desktop, open **Settings → Plugins → Lenz**, enter it in **Lenz API key**, and click **Save settings**. Alternatively, use the installer’s masked prompt in your own interactive terminal. If the terminal warns that input may be echoed, skip the prompt. Never paste the key into chat or enter it as a command argument.
3. Ask **“Show my Lenz balance and reset.”** This reads your account usage without submitting a claim or spending Lenz credits. If you replace a rejected key, start a fresh session and check again.

![Hermes Desktop’s Lenz settings: an empty masked key field and a check-depth selector](docs/media/desktop-settings.png)

## What you can check

| Ask Hermes | Maximum | What you get |
| --- | ---: | --- |
| “Which statements in this paragraph can I fact-check?” | 0 credits | A list of claims. Daily limits apply. |
| “Check the dates and dollar amounts in this draft.” | 1 per claim | A first verdict and confidence rating. A page found in search isn't a verified citation. |
| “Does the original study back up this claim?” | 6 at low depth or 11 at standard | An initial assessment and, when needed, one deeper check. |
| “Review this draft and flag citations that don’t support the claims.” | 32 in Normal mode | Claim checks, deeper checks where warranted, and citation checks. |

Check the text or URL Hermes plans to send to Lenz and the maximum cost, then say in chat whether to go ahead. If you change the request or wait more than 15 minutes, ask for a new preview. The plugin checks that the request and amount match the preview.

If a review is still running, ask Hermes to check its status instead of submitting it again. Read the sources and look for claims the review skipped or couldn't check. If Lenz finds no public record, that doesn't prove the claim is false.

### Draft limits

Choose **Check depth and draft limits** in Lenz’s plugin settings. The maximum is a reservation, not necessarily what Lenz bills. Critical-only is for explicitly high-stakes requests.

| Mode | Quick checks | Deep checks | Citations | Max credits |
| --- | ---: | --- | ---: | ---: |
| Light | 2 | None | 0 | 2 |
| Moderate | 5 | 1 low | 0 | 10 |
| Normal (default) | 10 | 2 standard | 2 | 32 |
| Heavy | 20 | 5 standard | 4 | 74 |
| Critical-only | 3 | 1 standard | 0 | 13 |

## The 500-credit monthly cap

Lenz for Hermes caps **reservations in this profile** at 500 credits per Lenz reset period. It does not grant credits or change your plan. Before sending content, the plugin checks the connected account’s balance, reset date, and prices. A lower balance can tighten the cap for the rest of that period. The cap does not cover spending on the Lenz website, through MCP, or in other profiles.

With 500 credits available, you could budget for **300 quick claim checks, five Normal draft reviews, and four Moderate draft reviews** at their maximum costs. With 100 credits, set aside 32 for one Normal review and up to 68 for quick checks. Ask Hermes for your Lenz balance or see [Lenz plans](https://lenz.io/plans). Hermes model usage is separate.

The full quoted maximum remains reserved on an ambiguous submission, even if no bill has arrived. Check Lenz activity before starting another request. The ledger survives restarts and reinstallations in the same profile. It opens a new period only after the old reset passes and Lenz reports a later reset.

## Data, updates, and removal

- A local preview does not contact Lenz. If you proceed, the plugin sends the selected material to `https://lenz.io/api/v1`. A public URL asks Lenz to fetch it. Balance and status checks make read requests. See [Lenz privacy](https://lenz.io/privacy).
- The local ledger holds amounts, reset times, request IDs, and expiring preview tags, not claim text, results, or credentials. Hermes can retain conversations and tool results. Reviews request private deep checks and no webhook delivery; private does not mean zero retention. The plugin does not run checks in the background or retry submissions automatically.
- To update, review the new revision and use Hermes’s plugin manager. Calls from older versions that omit the approved maximum now preview only. To disable, run `hermes plugins disable lenz`. To uninstall, run `hermes plugins remove lenz` in the same profile. The ledger is outside the installed plugin, under `lenz-budget/`, so removing the plugin does not reset it. Manage or revoke your key separately.

[License](LICENSE) · [Report an issue](https://github.com/cygnostik/hermes-lenz/issues)
