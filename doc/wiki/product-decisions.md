# Product decisions

This page explains why the product works the way it does, which alternatives were
rejected, and where the code departs from each loop's plan. The detailed analysis is in
the study (`doc/study/1790657879-litechat-clone-feasibility.md`, §6 and §10).

## Who it's for

People who want occasional access to LLMs from several providers but **won't pay for a
subscription**. Every decision below serves that user: pay only for what you use, see
exactly what you spent, and never be billed for more than you put in.

## What I identified as core

The brief describes Litechat as **metered, à la carte access to LLMs from several
providers, for regular users who won't pay for a subscription**. So I identified the core
as **letting a regular person use AI models from several providers and pay only for what
they use, with no subscription.**

The features that serve that core:

| Core feature | Where it lives |
|---|---|
| **Accounts:** sign-up, log-in, log-out | `accounts/`, Django's built-in auth ([accounts](accounts.md)) |
| **Prepaid credit charged per reply at each model's price, with $2.00 free to start** | the wallet and append-only ledger, `reply_cost_micros`, the sign-up credit, the 402 block ([billing](billing.md)) |
| **A model picker across OpenAI, Anthropic and Google** | the model catalog and the three provider adapters behind one shared request function ([catalog](catalog.md), [chat → the `llm` package](chat.md#the-llm-package-proxy-clients)) |
| **Saved chats that can be revisited, renamed and deleted** | `Conversation`/`Message`, the sidebar, rename, delete ([chat](chat.md)) |
| **A profile showing the balance and usage** | My Profile, and the nav's "My Profile · $X.XX" ([billing → My Profile](billing.md#my-profile)) |

Everything else makes that core easier to use, but isn't the core itself:
- the chatbot layout (sidebar, bubbles, Enter to send, no reload)
- Markdown rendering
- the Global System Prompt
- **Memories:** up to 10 short notes about the user, sent with the Global System Prompt
  in every chat (loop 7; [billing → Memories](billing.md#memories)), with a **per-chat
  "Include memories" switch** (loop 8;
  [chat → the switch](chat.md#the-include-memories-switch))
- **Automatic chat titles:** after the first reply, a short title from the chat's own
  model. It's **free to users**, and the cost is recorded for admins only (loop 7;
  [chat → Automatic titles](chat.md#automatic-titles))
- the landing page with its price snapshot

## Out of scope

| Feature | Why it's out of scope |
|---|---|
| **Web search** | The proxy's docs state that **hosted search is unavailable** ("Hosted search and code execution are unavailable", on the OpenAI Responses page). Adding it would need a separate search service and API key, a way to pass results to three different providers, and a price for searches on top of token charges. That's a new paid dependency outside the brief's core. |
| **File uploads** | The proxy's file APIs keep files **private to the proxy account** (ours, shared by every user), **expire them after one hour**, and cap them at 64 MiB per file and 100 files / 256 MiB per account and provider. Supporting uploads would mean our own per-user storage and clean-up, size limits, and handling for the file tokens each provider bills (large documents can cost far more than a chat message), all to work around a one-hour, shared-quota store. The core, pay-per-use chat across providers, doesn't need it. |
| **Thinking effort** (deferred, not rejected) | The proxy supports a reasoning setting on all three interfaces: OpenAI `reasoning_effort`, Anthropic `thinking`, and Google `thinkingConfig.thinkingBudget`. Chat4All currently turns it **off** on every request. **Thinking tokens are billed as output**, so enabling it can multiply a reply's cost with tokens the user never sees in the answer. Google already reports them as `thoughtsTokenCount`, which we charge as output. Offering it needs a product decision on **how to show and bill that cost**: for example showing thinking tokens separately on My Profile, a per-chat setting with a cost warning, or a thinking-token cap. **Memories were prioritized instead** for loop 7. |
| **Organization billing accounts** | The brief is about **regular individual users**. Shared balances would need organizations, membership and roles, per-member usage and limits, and rules for who can top up or see what. That's a different product (team billing) with its own ledger design. It was recorded as out of scope in the first study (§9, and decisions log §10 #6), and everything here keeps one wallet per user. |

## The credit system

### 1. Prepaid credit, charged per token

**Decision.** Each user has a prepaid US dollar balance, shown as "Available credit"
(e.g. `$1.99`). Each reply is charged by its **actual token usage**, as reported by the
proxy:
`input_tokens × input_price + output_tokens × output_price`, rounded up to the next
micro-dollar. Sending is blocked when the balance is **$0.00 or less**. A reply that
costs more than the remaining balance is still charged in full, so the balance can go
slightly negative.

**Why.**
- **Prepaid** means the operator never extends credit. There are no invoices, no
  collections and no surprise bills. Users can't spend money they haven't put in, apart
  from a bounded overshoot on one final reply.
- **Per token** matches how LLM costs actually arise: the proxy reports input and output
  tokens separately, and long chats cost more because the whole history is resent every
  turn. Charging per token passes that through honestly, and a short question costs
  almost nothing.
- **Charging the actual cost** (instead of refusing or cutting off a reply the balance
  can't fully cover) means users never get an unexpectedly truncated answer. The
  overshoot is bounded by the 1,024-output-token cap. At the most expensive seeded price
  ($5.00 per 1M output tokens), that's about half a cent of output per reply.
- **Micro-dollars** (whole integers, 1 USD = 1,000,000) are needed because one reply
  costs a fraction of a cent. For example, 1,000 input plus 300 output tokens on GPT-5.6
  Luna costs $0.0011. Loop 2's real check charged $0.00011 and $0.000114 for two short
  replies. Integers stay exact under concurrent `F()` updates. Balances are displayed
  rounded *down* to the cent, so we never overstate what's available.
- **No charge on failure:** if the proxy errors or times out, the user pays nothing and
  nothing is saved. Their draft stays in the form, so they can resend.

### 2. $2.00 sign-up credit

**Decision.** Every new user automatically receives $2.00, recorded as a `signup`
ledger entry. It's granted by a signal, so it applies however the account is created.

**Why.**
- It lets a new user try every model straight away, without waiting for an admin top-up.
  At the seeded prices, $2.00 covers hundreds of typical short replies.
- It's a ledger entry, not a starting balance written directly, so it shows in the
  user's history and keeps the invariant `balance == sum(ledger)`.
- It's small enough that the cost of abuse (making throwaway accounts for free credit)
  is limited. If abuse becomes a problem, the amount is one setting
  (`SIGNUP_CREDIT_MICROS`).

### 3. Per-model prices

**Decision.** Every model in the catalog has its own input and output price per 1M
tokens, editable in Django admin. The seeded models are all value tier: Claude Haiku
$1.00 / $5.00, GPT-5.6 Luna $0.50 / $2.00, Gemini Flash $0.30 / $2.50.

**Why.**
- Real providers price their models differently, and users choose partly on cost.
  Showing the price next to each model makes the choice informed.
- Input and output are priced separately because they're reported separately and
  usually cost different amounts. A single blended price would overcharge short-answer
  chats and undercharge long answers.
- Prices live in the database, not in code, so operators can change them, or add
  models, without a deploy. Each charged reply stores a snapshot of the prices it used,
  so later price edits don't rewrite history.

### 4. An append-only ledger

**Decision.** Every change to a balance is a `CreditTransaction` row: `signup`,
`topup`, `charge` (linked to the reply it paid for) or `adjustment`. The wallet balance is updated in the same database
transaction, and never edited directly. In admin, ledger rows can be added but not
changed or deleted. Mistakes are corrected with an `adjustment`, which may be negative.

**Why.**
- **Auditability:** every cent can be traced to a reason, a time and either the admin
  who made it (top-ups) or the exact reply it paid for (charges). Users see the same
  history on `/credit/`.
- **Correctness:** if admins edited balances directly, an edit made from a stale form
  could silently overwrite a charge that landed in the meantime. Ledger inserts plus
  atomic `F()` increments can't lose updates.
- **Verifiability:** `balance == sum(ledger)` can always be checked, and it's covered by
  tests.

### 5. Waiting up to 120 seconds for the proxy

**Decision.** `LLM_TIMEOUT_SECONDS = 120` (study §10 #12). It was 60 in the loop 2 plan.

**Why.** The proxy's response time varies widely. In loop 2's real check, one call hit
the 60-second timeout, and a retry took close to 60 seconds. For the user, a slow reply
is better than a failed one. A timeout still charges nothing, so the only cost of the
longer wait is the user's time. The call runs outside any database transaction, so a
slow reply doesn't block other users.

### 6. A chatbot-style UI, with costs on My Profile

**Decision** (loop 3, redesign study §10):
- The chat pages use a sidebar, bubbles, a pinned composer, Enter to send, and sending
  without a reload.
- They show no costs or token counts. **My Profile** shows the credit and what each chat
  and reply cost.
- The nav shows **"My Profile · $X.XX"**, and it updates after every reply.
- A chat's model is shown as a **fixed label**.
- Chats can be **renamed**.
- `/chats/` opens the latest chat.
- The script is **inline**, and replies stay **whole**.

**Why.**
- Users expect a chat app to look like one, and a running meter next to every message
  makes a pay-as-you-go product feel expensive.
- Keeping the balance in the nav means users still always know where they stand, which
  matters because sending is blocked at $0. So the nav must update live, from each
  reply's JSON `balance`.
- The fixed model label keeps each chat's history in one model's format. Per-message
  switching stays deferred until more than one model can chat.
- An inline script avoids static-file serving issues when `DEBUG` is off.
- Whole replies keep the status codes and billing exact.

### 7. Three providers behind one set of rules

**Decision** (loop 4):
- GPT-5.6 Luna, Claude Haiku and Gemini Flash can all be picked in chat.
- Each has its own small adapter (`llm/openai.py`, `anthropic.py`, `google.py`) that
  translates our neutral history and reads its provider's usage fields.
- All three send through **one shared request function** (`llm/http.py`), so the
  timeout, the 502/503 mapping and the missing-key 503 are the same by construction.
- Charging uses each model's own price from the catalog.

**Why.**
- The product promise is "pick any provider, pay only for what you use". That only holds
  if a Claude reply is metered as exactly as a GPT reply.
- Putting the failure handling in one place (with one table-driven test run for every
  provider) means a fix or change applies to all providers at once. A new provider only
  has to get its request format and usage fields right.
- Separate small adapters (about 60 lines each) keep each provider's quirks readable:
  Anthropic's same-role rule, Google's `model` role and its safety blocks.

### 8. An optional Global System Prompt

**Decision** (loop 4):
- One instruction per user, set on My Profile and up to 4,000 characters.
- It's sent as the system prompt in every chat, with every model, **read at send time**.
- When empty, requests carry no system field at all.
- It isn't stored on messages.

**Why.**
- It matches Litechat, and it's the simplest way to give users control over tone or
  language across every model.
- One global setting avoids a per-chat settings UI.
- Reading it at send time means a change applies straight away everywhere.
- Sending nothing when it's empty keeps requests exactly as before for users who never
  set one, with no extra tokens.
- It's billed honestly: the provider counts it as input tokens. The page says so, and the
  4,000-character cap bounds the cost.

### 9. Markdown replies, sanitized twice

**Decision** (loop 5, study §2 and §5 #1):
- Model replies render Markdown (bold, lists, code, tables) on the server, through
  **markdown-it-py with raw HTML off and images off**, then **nh3 with a strict
  allowlist**.
- No `<img>`, no `style`, no `on*`, and only `http`/`https`/`mailto` links.
- Stored replies stay raw Markdown. User messages aren't rendered.

**Why.**
- Models answer in Markdown. Showing `**` and `|---|` literally made replies hard to
  read.
- But model output is untrusted and can be steered by prompt injection, so the
  requirement was that it can **never** inject HTML or scripts.
- The libraries were **tested against an XSS corpus**, not chosen by reputation:
  - Python-Markdown passed `<script>`, `<iframe>` and `javascript:` links straight
    through.
  - markdown-it-py and mistune blocked scripts but still emitted `<img>`.
  - Any parser followed by nh3 was clean.
- Two layers mean one config slip (e.g. turning `html` on) or one parser bug can't open a
  hole.
- Images and `style` are excluded because both make the browser **fetch a URL chosen by
  the model** without a click, which would be a silent way to exfiltrate a conversation.

### 10. Deleting a chat keeps its charges

**Decision** (loop 5, study §3 and §5 #2–3):
- Users can delete a chat, after a confirmation page. The chat and its messages are
  hard-deleted.
- **Its charges stay in the ledger unchanged, with no refund**, and My Profile shows
  them as "Deleted chats".
- If a chat is deleted while a reply is in flight, that reply is still charged, and the
  request returns 404.

**Why.**
- The tokens were used and paid to the provider. Refunding on delete would turn delete
  into a free-usage loophole (chat, delete, get refunded, repeat).
- Keeping the rows without editing them preserves the append-only ledger and
  `balance == sum(ledger)`. The `SET_NULL` link already did the right thing.
- Hard delete matches what users expect from "delete". Their text is really gone.
- The "Deleted chats" line keeps My Profile honest: the per-chat totals still add up to
  what was spent.
- A confirmation page works without JavaScript and avoids blocking browser dialogs.

### 11. Sidebar dates in the user's own time zone

**Decision** (loop 5, study §4 and §5 #4):
- Each sidebar row shows its **last activity**: `14:05`, `Yesterday`, `Mon`, `Sep 3`
  or `Sep 3, 2025`.
- The server renders a `<time>` element in UTC, and the existing script localizes it
  with `Intl`.

**Why.**
- Last activity is what the sidebar is sorted by, so the dates read in order.
- The app runs in UTC, and server-side "today" would be wrong near midnight for most
  users.
- Localizing in the browser needs no time-zone setting and no dependency, and it
  degrades to a correct UTC date without JavaScript.

### 12. A Chat4All identity, with navy and gold, and a hero landing page

**Decision** (loop 6, planned directly from a decided list, with no study):
- The app is renamed **Chat4All** wherever users see it, and the README credits Litechat
  as the product it replicates.
- A **navy color scheme with a gold accent** across the whole app.
- A **hero-themed landing page**, with an original inline-SVG shield, How it works, and a
  catalog-driven price snapshot. It's the only page with the hero theme.
- Log-in and sign-up are **centered cards**.

See [Visual design](design.md).

**Why.**
- A product needs its own name, and "Litechat" is the product being replicated.
- The landing page explains the core in one screen: no subscription, $2.00 free, three
  providers, and pay per reply. The price snapshot answers "how far does my money go?"
  with estimates computed by the same formula as real charges, and the assumption is
  stated on the page.
- Readability was a hard requirement, so contrast is enforced by tests (22 pairs, all
  ≥ 4.5:1) and audited in the browser, not judged by eye.

### 13. Automatic chat titles, free to users

**Decision** (loop 7, study §2 and decisions §4 #1–4):
- After a new chat's first reply, a **separate request** asks **the chat's own model**
  for a 3–6-word title, with a 20-token cap and a 20 s timeout.
- **The app pays.** The user's wallet and ledger are never touched, and nothing appears
  on My Profile, in the credit history or in the nav. Each attempt's tokens and cost are
  recorded in an **admin-only** log.
- **Every new chat gets an attempt, regardless of balance.**
- If the call fails or returns nothing usable, the first-line title stays, with no retry
  and no charge. A rename always wins.

**Why.**
- **A separate request** keeps the first reply exactly as fast as before. This proxy has
  taken up to 85 s, and a slow or failed title must never delay or endanger a reply that
  already succeeded.
- **The chat's own model** means no provider sees content the user didn't send to it.
  Picking the cheapest model would send a Claude chat to Google to save a fraction of a
  hundredth of a cent.
- **Free and invisible:** titles are something the app does, not something the user
  asked for. Keeping them out of the ledger keeps "Spent" a pure record of the user's
  own replies, with every reconciliation intact. The admin log keeps the real cost
  visible to the operator: about 10% of a first reply, once per chat, and 161–517 µ$ in
  the real check.

### 14. Memories, capped because they're billed on every message

**Decision** (loop 7, study §3 and decisions §4 #5–6):
- Users keep **up to 10 notes of at most 200 characters** on My Profile.
- They're sent after the Global System Prompt, to every model in every chat, and never
  with title calls.
- Deleting one is immediate, with no confirmation.
- My Profile shows an **estimate** of what the prompt and memories add to every message.
- Only the user adds memories.

**Why.**
- Memories let a user say once "I'm a student" or "keep answers short" instead of in
  every chat.
- Every character rides along as input tokens on **every** message, so the caps bound
  the cost: at the limit, about 512 tokens, or roughly $0.0005 per Claude Haiku message.
  The estimate on My Profile makes that visible rather than hidden.
- 200 characters fits a real sentence.
- A memory is one line that's easy to re-add, so a confirmation page for deleting would
  be friction without protection.
- AI-generated memories are out of scope. They'd need consent and review rules for what
  a model writes about a user.

### 15. A per-chat "Include memories" switch

**Decision** (loop 8, made directly by the user, with no study):
- An **"Include memories" switch next to the message box**, saved **per chat** and **on
  for new chats**.
- It can be changed at any time, and applies from the next message.
- **Off** sends the Global System Prompt without memories.
- It's a **normal form control** that works without JavaScript, and it **only appears
  once the user has a memory**.
- Titles still never include memories.
- Charging is unchanged.

**Why.**
- Memories are global, but not every chat should be shaped by them. "I'm a student" helps
  a homework chat and not a recipe chat. A per-chat switch gives that control without
  per-chat memory lists.
- Keeping the prompt when memories are off separates the two: the prompt is a standing
  instruction, and memories are personal context.
- Making it part of the message form means no extra endpoint and no JavaScript
  dependency. What the switch shows is always exactly what the next send uses.
- Hiding it until a memory exists avoids a control that would do nothing.

**Finding (loop 8's real check): switching memories off partway through a chat doesn't
fully remove their effect.** The request stops carrying them straight away. The mocked
tests prove that per provider, and in the real check fresh chats with the switch off used
about 18 fewer input tokens, the size of the memory block. **But the model tends to imitate its own earlier
replies in the history.** With the memory "Always answer in exactly one sentence." on
for the first message and off for the second:
- GPT-5.6 Luna and Gemini Flash **still answered in one sentence**, copying the style of
  their earlier one-sentence reply.
- Claude Haiku answered in three sentences.

In **fresh chats started with the switch off**, all three answered in 4–10 sentences, and
the Global System Prompt was still followed. So "off" means **not sent**, not
**forgotten**: earlier replies shaped by a memory stay in the history and can keep
steering the model. The way to get a clean slate is a new chat with the switch off.

## Rejected alternatives

| Alternative | Why we rejected it |
|---|---|
| **Monthly subscriptions** | This is exactly what the target user won't pay. A subscription charges light users for capacity they don't use and needs recurring billing, plan tiers and cancellation flows. It would also still need usage caps to protect the operator from heavy users, which brings metering back anyway. |
| **Flat per-message pricing** | Simple to explain, but the cost of a message varies by orders of magnitude: a one-line question in a new chat is tiny, while a long answer deep into a chat (with the whole history resent) is expensive. A flat price either overcharges short messages (bad for our price-sensitive users) or loses money on long ones, and it gives users no reason to prefer cheaper models or shorter chats. |
| **No credits (free, or billed afterwards)** | Free, unmetered access exposes the operator to unbounded proxy costs, with nothing to stop one user from using up the budget. Billing after use (invoicing for usage) means extending credit to anonymous sign-ups, handling unpaid bills, and integrating a payment processor before launch. Prepaid credit avoids both: usage is limited by what's been paid (or granted), and top-ups can start as a manual admin action. |
| Admins editing the balance directly | No audit trail, and it can lose updates when an admin's save races with a charge (see §4). |
| Floats or cents for money | Floats drift. Cents can't represent one reply's cost. |
| Capping each reply to what the balance can afford | Users near $0 would get surprise truncated answers. We chose to charge the actual cost and allow a bounded, slightly negative balance instead. |
| Saving the user's message when the proxy fails | It would leave an unanswered message in the history, which would then be resent on every later turn. We save nothing and keep the draft in the form instead. |
| Streaming replies | Once a streamed response starts it has already sent 200, so a proxy failure partway through can't become a 502/503. Usage arrives only at the end, so a broken stream leaves tokens used with nothing to charge. Whole replies plus a thinking indicator keep charging exact and every status code correct (redesign study §5). |
| A frontend framework (React/Vue) or htmx for the chat UI | A framework is forbidden by `CLAUDE.md` and would pull rendering, and the temptation to call LLMs, into the browser. htmx is a new dependency that saves only a few dozen lines. A small inline script plus server-rendered fragments gives the same result with no dependency. |
| Official provider SDKs (`openai`, `anthropic`, `google-genai`) | Three new dependencies, each needing its base URL overridden, and each possibly sending headers or paths the proxy doesn't support. The request bodies are small, so plain `requests` through one shared function is less code and gives exactly the same error handling for all three (first study §6.5). |
| Per-chat system prompts | A settings UI on every chat, plus rules for how it interacts with the global prompt. Users asked for one Litechat-style global instruction. Can be added later on top of `UserSettings`. |
| Storing the system prompt on each message | It would make the prompt part of the resent history, adding repeated tokens and cost. It would also mean a changed prompt doesn't apply to old chats. It's read at send time instead. |
| Treating a Google safety block as an error (502) | The provider did the work and reported usage, so refusing to charge would give it away, and showing "the model failed" would be misleading. It's stored as a charged reply that shows "The model declined to answer this (safety filter)." |
| Rendering Markdown in the browser (`marked` + `DOMPurify`) | It makes the browser a second renderer, adds JS libraries from a CDN, can't be checked by Django's tests, and shows raw Markdown without JS. Server rendering reuses the one partial for pages and JSON fragments. |
| Storing rendered HTML instead of rendering on display | It needs a migration, freezes old replies under an old sanitizer policy, and risks HTML reaching a model in the history. Rendering takes about 1 ms per reply. |
| Python-Markdown or markdown-it-py **without** a sanitizer | Python-Markdown passes raw HTML by design. markdown-it-py alone is safe only as long as one config flag stays set. For "must never inject", the second layer is worth one small wheel. |
| bleach as the sanitizer | Deprecated by its maintainers (security fixes only). nh3 is the recommended successor. |
| Refunding a deleted chat's charges | The tokens were used and paid for, and it would make delete a way to get free usage. |
| Soft-deleting chats | It keeps text the user asked to delete, and adds an "is deleted" filter to every query. |
| A JavaScript `confirm()` dialog for deleting | It has no no-JS fallback, blocks the page, and can't be styled. |
| Sidebar dates in UTC only, or a per-user time-zone setting | UTC is wrong near midnight for most users. A setting adds UI nobody asked for, when the browser already knows the time zone. |
| Provider logos, or real superhero imagery on the landing page | These are trademarks and copyrighted characters. Providers are named in text, and the emblem is an original shield drawn in inline SVG. |
| Hard-coding the price snapshot, or computing it with a separate formula | It would drift from the catalog and from real charges. The snapshot reads active models from the catalog and uses `reply_cost_micros`, so an admin price edit changes it immediately. |
| Gold as a text color on light backgrounds | About 1.9:1 on white, which is unreadable. Gold is text only on navy, and a test enforces this. |
| Generating the title inside the first send | It adds a full proxy round trip (up to 85 s here) to every new chat's first reply, and a title failure could endanger a reply that succeeded. |
| A background thread or task queue for titles | No task queue exists. Celery would be a new dependency and service, and threads in the WSGI dev server aren't durable. A second request from the script does the same job. |
| Titling with the cheapest model | It sends the user's first message to a provider they didn't choose, to save a fraction of a hundredth of a cent. |
| Charging users for titles, or folding the cost into the first reply | Titles weren't requested by the user (decision #1). Folding the cost in would make a reply's cost stop matching its reported tokens. The app pays, and admins see the cost. |
| Retrying failed titles automatically | It hides costs and adds load against an unreliable proxy for a nicety. One attempt, then the first-line title stays, and the user can rename. |
| Saving the Include memories switch as soon as it's flipped | It needs a separate endpoint, plus a second no-JS button next to the message box, and it can disagree with what the next send uses if a save fails. Saving it with the message it applies to keeps the form control simple and always truthful. |
| Clearing or rewriting earlier replies when memories are switched off | The history is what the user saw, and it's resent for context. Editing it would change the conversation behind the user's back. A new chat with the switch off is the clean slate. |
| Unlimited memories, or editing memories in place | Every memory is billed on every message, so there's a cap. Delete and re-add is simpler than an edit flow for one-line notes. |
| Showing costs on the chat pages | Chat pages should feel like a chatbot, not a meter. Costs moved to My Profile, and the nav keeps the balance visible (redesign §10 #1). |

## Departures from the plan

### Loop 1

The loop 1 plan (`doc/plan/1790659225-loop1-foundation.md`) was followed step by step,
in seven commits. The code differs from it in these places:

1. **Invalid forms in Django admin return 200. The app's own forms return 400.**
   - The app's forms (sign-up, log-in, new chat and send) re-render invalid
     submissions with **400**, following the study's status-code decision.
     `SignUpView.form_invalid` and `LoginView.form_invalid` pass `status=400`.
   - Django admin re-renders an invalid add or change form with **200**. That's how
     Django's `ModelAdmin` is built. Examples are a negative top-up, or a price with more
     than 6 decimal places. We didn't override it: admin is a staff-only internal tool,
     overriding would mean customizing admin internals for no user benefit, and the error
     messages still show. Tests assert this (`AdminTopUpTests.test_negative_top_up_is_rejected`
     expects 200 and no ledger row).
   - **Rule:** views we write return 400 for invalid forms. Django admin keeps its own
     behavior.
2. **Existing ledger entries can be viewed in admin (200) but not changed or deleted
   (403).** The plan expected 403 on the change URL. Django admin gives a read-only page
   to anyone with view permission, which is useful for auditing. Posting a change and
   opening or posting the delete page return 403, and tests check this.
3. **The money helpers live in `config/money.py`, and the template filters in
   `catalog/templatetags/money.py`,** not in `billing` as planned. The catalog (step 4)
   needed dollar conversion and formatting before the billing app existed (step 5), and
   both apps use the same helpers.
4. **Users who existed before billing** get a $0.00 wallet when first seen
   (`get_wallet`), not the sign-up credit. Only newly created users get the $2.00. At
   loop 1 the dev database had no users, so this affected no one.
5. **Verifying the full click-through without touching the dev database.** The plan's
   smoke test (sign up, top up, and so on) was run by following nav links on a throwaway
   test database, so no test accounts were written to `db.sqlite3`. The live server on
   `0.0.0.0:8000` was checked with GET requests only.

### Loop 2

The loop 2 plan (`doc/plan/1790661385-loop2-openai-chat.md`) was followed in six
commits, plus one follow-up fix. The code differs from it in these places:

1. **Timeout raised from 60 to 120 seconds** (`fix: raise LLM proxy timeout to 120
   seconds`). The plan set 60. See decision 5 above.
2. **The chat list is ordered explicitly.** The plan relied on
   `Conversation.Meta.ordering`, but Django **ignores `Meta.ordering` on querysets that
   aggregate** (the list counts and sums messages). A test caught that chats came back
   in arbitrary order. The view now calls `.order_by("-updated_at", "-id")`. Keep this
   in mind for any future annotated query.
3. **The out-of-credit notice shows when the page loads.** The plan only described the
   notice on a blocked send (402). The chat pages now also show it at $0 or less when
   first loaded (200), so users learn before typing a message. The 402 on send is
   unchanged.
4. **The inactive-model check comes before the balance check.** Sending to a chat whose
   model was deactivated returns 400 even if the user is also out of credit, because
   topping up wouldn't help. The plan didn't specify the order.
5. **`LLMError` takes its status in the constructor** (`LLMError(status, message)`),
   rather than being set afterwards. There's no behavior change.
6. **Real-proxy verification ran on a throwaway database.** As in loop 1, the plan's
   end-to-end check signed up, started a chat, sent two real messages and checked the
   ledger, all on a temporary test database following nav links. `db.sqlite3` only
   received the two new migrations.

### Loop 3

The loop 3 plan (`doc/plan/1790663510-loop3-chat-redesign.md`) was followed in six
commits, plus one fix found in the browser check. Before execution, the user changed the
plan: the nav balance must update live from each JSON reply (it was an accepted risk in
the first draft), and the `uitest` account was authorized. The code differs from the plan
in these places:

1. **Layout width fix** (`fix: make the chat layout fill the window width`). On desktop,
   the chat app shrank to its content (686–782px of 1280). The body is a flex column, and
   the base `main { margin: 0 auto }` made `<main>` fit its content. The fix sets
   `width: 100%; margin: 0` on `main.chat-app`. **Every automated assertion passed
   anyway.** The bug was found by looking at a screenshot, and the browser check now
   asserts the width.
2. **`send_message` records the exchange it created**
   (`conversation.new_messages = [user_message, assistant]`). The JSON response renders
   exactly those two bubbles, even if another tab sends at the same moment. It only
   adds information: the signature and behavior are unchanged.
3. **Chats whose model is unavailable** keep loop 2's behavior: a "Start a new chat" link
   replaces the composer. The plan didn't mention it.
4. **The browser check used headless Chrome over the DevTools protocol**, driven by a
   Node script in the scratchpad, because the Chrome extension tools weren't available.
   Nothing was added to the repo. It ran on the dev server with the authorized `uitest`
   account, so the dev database now has `uitest`, a few test chats and about $0.001 of
   real charges.
5. **The real-proxy checks needed retries.** The proxy dropped or stalled connections
   (1.5 s to 85 s). Each time, the app returned 503, restored the draft and charged
   nothing, so these failures also tested the error path for real. The final browser run
   passed 30/30.

### Loop 4

The loop 4 plan (`doc/plan/1790676012-loop4-all-providers.md`) was followed in its six
commits, with no follow-up fix. The code differs from it in these places:

1. **`LLMReply` and `LLMError` moved to `llm/base.py`.** `llm/__init__.py` now imports
   the adapters to build `PROVIDERS`, and the adapters import these types. Leaving them
   in `__init__` would have created a circular import. They're still importable as
   `from llm import LLMError, LLMReply`.
2. **The admin inline needed `verbose_name`.** For a one-to-one inline, Django headings
   use `verbose_name`, not `verbose_name_plural`. A test caught this ("Global System
   Prompt" was missing), and both are now set.
3. **The "unsupported model" tests now use a made-up provider (`mistral`)** with no
   adapter, because all three real providers are enabled. This also exercises the
   `CHAT_PROVIDERS` filter directly.
4. **The Google `systemInstruction` shape (the plan's main risk) was confirmed by real
   calls.** All three models replied in French with "Always reply in French." set, and
   in English once it was cleared. All 12 real calls succeeded on the first try
   (1.3–1.8 s), and every charge matched the formula at that model's price.
5. **The browser check (23/23) used a new driver script, `browser_loop4.mjs`**, which
   reuses loop 3's DevTools harness. Like the others, it lives in the scratchpad, not the
   repo. It ran on the dev database with `uitest`, which gained a few Claude, Gemini and
   GPT chats, about $0.002 of real charges, and an `accounts_usersettings` row. That row
   is currently empty, because the check cleared the prompt at the end.

### Loop 5

The loop 5 plan (`doc/plan/1790681656-loop5-markdown-delete-dates.md`) was followed in
its five commits, plus one follow-up fix. The code differs from it in these places:

1. **"Deleted chats" alignment fix** (`fix: right-align the Deleted chats total on My
   Profile`). The float rule for totals was scoped to `.usage-chat`, so the new card's
   total sat inline. **No assertion caught it; a screenshot did.** The one-shot browser
   check after the fix asserts the alignment.
2. **Flash messages moved inside the chat column.** The plan didn't mention it, but
   "Chat deleted." (shown after the redirect to the next chat) would have rendered as a
   stray grid cell in `main.chat-app`. `base.html` now wraps messages in a
   `{% block messages %}`. `layout.html` empties it, and `_main.html` shows them under
   the chat header.
3. **The view-level XSS audit was tightened.** The plan said to audit "the thread". The
   first version counted our own bubble `div`s and flagged correctly escaped text. It
   now parses exactly each rendered reply (`bubble-text md`), plus the whole thread with
   only our `div`/`span` wrappers allowed.
4. **`send_message` was split** into `_save_exchange()` (the writes) and
   `_conversation_exists()` (the check), and it now **raises `ConversationDeleted` only
   after the charge's transaction commits**. Raising inside `transaction.atomic()` would
   have rolled back the very charge the fix exists to keep. Keeping the check separate
   also lets the backstop test force the "check passes, write fails" path.
5. **Verification results:**
   - The Node date check passed 11/11 in each of three time zones.
   - Real Markdown replies from all three models rendered a table, a list, bold text and
     a code block, and passed the parsed audit, with stored raw Markdown and correct
     charges.
   - The browser check passed 17/17, including the Los Angeles → Tokyo time zone switch
     (04:47 → 20:47).
   - `uitest` deleted one old "Browser pass chat", whose three charges now form its
     "Deleted chats" line.

### Loop 6

The loop 6 plan (`doc/plan/1790683617-loop6-chat4all-visual-refresh.md`) was followed in
its five commits, with no follow-up fix. The code differs from it in these places:

1. **The focus ring has a navy halo.** The plan specified a gold outline. A gold ring
   alone is about 1.9:1 on white, which fails WCAG's 3:1 for focus indicators. So
   `:focus-visible` adds `box-shadow: 0 0 0 5px var(--navy-900)`, which makes the ring
   visible on both light and navy backgrounds.
2. **The contrast test covers 22 pairs, not only the plan's table.** It adds the
   combinations the new CSS introduced: error text on `--error-soft`, muted text on
   `--navy-100`, navy on `--gold-hover`, white on `--error`, and muted-on-navy on
   `--navy-700`. The lowest is 5.7:1 (error on error-soft), still above AA.
3. **Log-in and sign-up forms use `novalidate`**, so validation errors come from the
   server and appear inside the card (with the existing 400) instead of as browser
   pop-ups.
4. **Two unused style rules from loop 2 were removed** (`.msg-user`, `.usage`).
5. **Verification:** the browser check passed 39/39. It audited contrast on about 600
   text elements across 8 pages at 1280px and 375px, found no horizontal scroll, and
   confirmed the focus ring and where the CTA leads. Screenshots of every page were
   reviewed. There were no proxy calls and no dev-database changes beyond `uitest`
   logging in.

### Loop 7

The loop 7 plan (`doc/plan/1790687240-loop7-auto-titles-memories.md`) was followed in its
five commits, plus one follow-up fix. Decision #1 had already overridden the study's
recommendation (app-paid titles, admin-only cost, no ledger kind) before planning. The
code differs from the plan in these places:

1. **Three migrations, not two.** `chat.0002_title_generation` (the admin cost log) and
   `chat.0003_title_source` landed in separate commits, as did `accounts.0002_memory`.
   `title_source` defaults to `user`, so all 12 existing dev-database chats became
   `user` and will never be retitled.
2. **A test moved to the later step.** Step 3's title test originally set a memory, but
   `Memory` only exists from Step 4. "The title call never carries memories" is covered
   by `MemoriesInChatTests.test_title_call_never_carries_memories`.
3. **Two test corrections, not app changes.** A helper found the new chat by title
   prefix, which failed on messages with repeated spaces because titles collapse them;
   it now takes the newest chat. And one hand-counted character total in the estimate
   test was off by one, so its expected values and comment were corrected (50 + 1 + 2 +
   150 = 203 characters → 51 tokens).
4. **A loop 3 layout bug fixed** (`fix: keep My Profile chat totals on their own line on
   phones`). The floated per-chat total landed in the middle of the wrapped details line
   at 375px. Loop 7's screenshots caught it; no assertion had.
5. **The admin list was checked without logging in as the owner.** The dev database's
   only staff account is the owner's, so the admin cost list was rendered in-process with
   `RequestFactory` as that user, read-only with no session, rather than creating another
   admin.
6. **Verification:** 9/9 real proxy calls (titles for all three models, each app cost
   matching the formula, the user's balance and ledger unchanged; memories followed by
   all three), and the browser check passed 16/16, plus 4/4 for the layout fix.

### Loop 8

The loop 8 plan (`doc/plan/1790689108-loop8-include-memories-switch.md`, with no study)
was followed in its three commits, plus one follow-up fix. The code differs from it in
these places:

1. **The switch's off state has a visible border.** The plan styled the off track with
   `--line`, but that's about 1.3:1 against the page, below WCAG's 3:1 for controls. Off
   is now a white track with a `--muted` border and knob (6.5:1), and on is `--navy-700`
   with a white knob. No new tokens, so `ContrastTests` is unchanged.
2. **The phone composer was fixed** (`fix: keep the message box and Send on their own line
   on phones`).
   - The screenshots showed the model chip plus the switch squeezing the message box to a
     sliver ("Me / ssa").
   - A first attempt (a 200px minimum) pushed Send onto its own line in chats without the
     switch.
   - The final rule gives the message box and Send their own line on phones. It was
     measured at 375px with and without the switch, and at 1280px.
3. **An extra real-proxy check.** The plan's check (on, then off in the same chat) gave an
   ambiguous result: two models stayed at one sentence with the switch off. A second run
   started **fresh chats with the switch off**, which answered in 4–10 sentences with
   about 18 fewer input tokens, while still following the prompt. That separates "not
   sent" (proven) from "no longer influential" (not guaranteed; see the finding under
   decision 15).
4. **Verification:** 216 tests, 9/9 real calls, and a browser check (20/20) including
   **no-JavaScript** toggling and the keyboard. It also confirmed that loop 7's automatic
   title still worked alongside the switch ("How Rainbows Form"). `uitest` was left with
   no memories.

