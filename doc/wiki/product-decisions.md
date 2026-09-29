# Product decisions

This page explains why the product works the way it does, which alternatives were
rejected, and where the code departs from each loop's plan. The detailed analysis is in
the study (`doc/study/1790657879-litechat-clone-feasibility.md`, §6 and §10).

## Who it's for

People who want occasional access to LLMs from several providers but **won't pay for a
subscription**. Every decision below serves that user: pay only for what you use, see
exactly what you spent, and never be billed for more than you put in.

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

