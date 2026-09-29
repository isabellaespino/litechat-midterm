# Study: Loop 7: automatic chat titles and Memories

- **Date:** 2026-09-29 (Unix 1790686669)
- **Type:** study (feasibility and tradeoffs; no code)
- **Builds on:** loop 6 on `main` (wiki: `chat.md` send flow and renaming, `billing.md`
  ledger, My Profile and Global System Prompt, `product-decisions.md` core and out of
  scope)
- **Status:** decisions recorded (§4). Planned as loop 7.

## 1. Request

1. **Automatic chat titles.** Name each chat after its first reply, instead of using the
   first line of the first message. Decide:
   - who pays for the extra model call, and how it appears in the ledger
   - which model generates the title
   - what happens if the title call fails
   - how it affects the time the first reply takes
2. **Memories.** Users add short notes about themselves on My Profile (e.g. "I'm a
   student", "keep answers short"), and can delete each one. The notes are sent with the
   Global System Prompt in every chat. Decide limits on how many and how long, because
   they're resent and billed as input on every message. **AI-generated memories are out
   of scope.**

**Verdict: both are feasible without new dependencies.**
- Titles are the harder one: a second model call touches billing, the ledger's "Deleted
  chats" reconciliation, the adapters' output cap, and the script.
- Memories are a small model plus a profile section, reusing the system-prompt path from
  loop 4.
- Both need migrations.

---

## 2. Automatic chat titles

### 2.1 What exists today

- `chat.services.title_from(text)` sets the title when the chat is created: the first
  line of the first message, at most 50 characters. `Conversation.title` holds up to 100.
- Renaming (loop 3) saves with `QuerySet.update()`, so it doesn't bump `updated_at` or
  reorder the sidebar.
- All three adapters send `MAX_OUTPUT_TOKENS` (1,024) as the output cap, with no
  per-call override.
- **The ledger:** a reply's charge is `kind="charge"` linked to its `Message`. My
  Profile's **"Deleted chats" line counts every `charge` row with `message IS NULL`**, so
  a title charge recorded as a `charge` with no message would be **miscounted as a
  deleted chat**. The title charge needs its own representation (§2.4).

### 2.2 When the title is generated, and the effect on first-reply time

The proxy's latency varies a lot: we've measured 1.3 s up to an 85 s dropped connection.
A second call is therefore not free in time.

| Option | First-reply wait | Verdict |
|---|---|---|
| A. **Same request, after the reply:** call the model again before responding | **+1 full proxy round trip** (typically 1–2 s, occasionally tens of seconds). A slow or failing title call delays or endangers a reply that already succeeded. | Rejected. |
| B. **A background thread or task queue** after responding | Unchanged | There's no task queue (Celery etc. would be a new dependency and service). Threads in a WSGI dev server aren't durable and complicate DB connections and tests. Rejected. |
| **C. A second, separate request, triggered by the script (recommended)** | **Unchanged.** The reply shows exactly as fast as today. | The first send saves a **provisional** title (today's `title_from`), and the reply renders immediately. Then the script, which already handles the new-chat response, fires `POST /chats/<id>/title/` in the background. When it answers, the header, the sidebar entry and `document.title` update in place. If the user navigates away, the server still finishes the request and saves the title. |
| D. Lazily, on the next page load | Unchanged | A GET that calls a paid API and writes to the DB is wrong for a GET, and it would make a later page load slow. Rejected. |

**Without JavaScript**, option C doesn't run, so the chat keeps its provisional
first-line title. The user can rename it. That's an acceptable degradation: no-JS users
already get full page reloads. An alternative would be to run the title call inside the
form-mode POST for no-JS users only, at the cost of option A's latency for them.

### 2.3 Which model generates the title

| Option | Cost of one title | Privacy | Verdict |
|---|---|---|---|
| **The chat's own model (recommended)** | Its own price (below) | **Nothing new is shared:** the conversation only goes to the provider the user already chose | Same key, same adapter, predictable. If that provider is down, the title fails the same way the chat would. |
| The cheapest active model | Slightly cheaper (Gemini or GPT) | **It sends the user's first message to a provider they didn't pick** (a Claude chat's content would go to Google) | Rejected. A hidden data-sharing change to save a fraction of a hundredth of a cent. |
| A fixed "title model" setting | Depends | Same issue as above for every other provider | Rejected, for the same reason. |

**The title request:**
- **Content:** a short fixed instruction ("Write a 3–6 word title for this conversation.
  Reply with the title only, no quotes or punctuation at the end."), plus the **first
  user message and the first reply, each truncated to 1,000 characters**.
- **The Global System Prompt and memories are not sent.** They aren't needed to name the
  chat, and leaving them out keeps the call small. The title still comes out in the
  conversation's own language, because the content drives it.
- **Output cap:** `max_tokens` 20. This needs an optional `max_output_tokens` argument
  on `llm.complete` and the three adapters, defaulting to `MAX_OUTPUT_TOKENS`.
- **Timeout:** a shorter one for titles (e.g. **20 s**, not 120 s). The title isn't
  essential, and the request holds a server worker.

**Cost at seeded prices** (a typical 150 input / 8 output tokens; the worst case is 540 in
/ 20 out, from the 1,000-character truncation):

| Model | Typical title | Worst case | For comparison: one 500/300-token message |
|---|---|---|---|
| Claude Haiku | 190 µ$ ($0.00019) | 640 µ$ | 2,000 µ$ |
| GPT-5.6 Luna | 91 µ$ | 310 µ$ | 850 µ$ |
| Gemini Flash | 65 µ$ | 212 µ$ | 900 µ$ |

A title costs about **10% of a typical first reply**, and at most about a third. That's
once per chat.

### 2.4 Who pays, and how it appears in the ledger

| Option | Verdict |
|---|---|
| **The user pays the actual cost, as its own visible ledger row (recommended)** | This matches the product's core ("pay only for what you use", "see exactly what you spent"). The provider really bills these tokens, and the operator has no other revenue to absorb costs from. It's shown honestly rather than hidden. |
| The operator absorbs it (free to the user) | Friendlier for a feature the user didn't ask for, but it creates an untracked cost outside the ledger: `balance == sum(ledger)` would hold while real spend quietly exceeds income. If chosen, record it in an operator-cost log, not the user's ledger. |
| Fold it into the first reply's charge | It hides the cost inside the reply's tokens and cost, which then no longer match what the provider reported. Rejected. |

**Ledger representation (recommended):**
- A **new kind, `title`** ("Chat title"), next to `signup`, `topup`, `charge` and
  `adjustment`.
- A **new nullable FK `CreditTransaction.conversation`** (`on_delete=SET_NULL`), set for
  title rows.
- The note: `Chat title for “<provisional title>”`.
- It's posted through `post_transaction`, so it's atomic, uses `F()`, and keeps
  `balance == sum(ledger)`.
- Because it isn't `kind="charge"`, **it doesn't pollute "Deleted chats".**

**My Profile then needs:**
- **Per-chat totals** that include the chat's title charge (the sum of reply costs plus
  its `title` row), with a "Title" line in the chat's expanded reply table.
- **"Spent on replies"** becomes "Spent", including title rows. Alternatively it stays
  split as "replies" plus "titles"; the plan picks one.
- **"Deleted chats"** also counts `title` rows whose `conversation` became NULL, so the
  equation still holds: (per-chat totals + deleted total = spent).
- The admin ledger shows the kind, with the "Chat" column linking the conversation.

**Credit guard:** the title call is **skipped when the balance is $0 or less.** The chat
keeps its provisional title and the user is charged nothing. A feature the user didn't
explicitly request should never push them further negative.

### 2.5 Failure handling

| What happens | Result |
|---|---|
| The proxy fails (`LLMError`: timeout, 429, 5xx, missing key) | **No charge.** The provisional title stays. The state becomes `failed`, and there's no automatic retry. The script silently ignores it. |
| The proxy answers but the text is unusable (empty, only punctuation, or just "Title") | **Charged**, because the tokens were used, consistent with "charge actual usage". The provisional title stays. |
| The output is usable | It's **cleaned**: first line only, surrounding quotes and Markdown (`#`, `*`, backticks) stripped, whitespace collapsed, a trailing period removed, and capped at 60 characters with `…`. Then it's saved. Titles are always rendered escaped (never as Markdown). |
| The user **renamed the chat** while the title call was in flight | **The rename wins.** The save is a conditional update (`filter(pk=…, title_source="provisional")`). The call is still charged (the tokens were used) and the response is 409. |
| The chat was **deleted** while the call was in flight | The title row is still recorded (with `conversation` NULL, noted as a deleted chat), and the response is 404. This mirrors loop 5's in-flight reply rule. |
| **Duplicate or concurrent title requests** (two tabs, a double fire) | The first request claims the chat by moving `title_source` from `provisional` to `generating` in one conditional update, and only that request calls the model. Others get **409** without calling the proxy. |

**New field:** `Conversation.title_source`, with the choices:
- `provisional`: from `title_from`, eligible for an automatic title
- `generating`
- `auto`
- `user`: set on rename, and never auto-titled again
- `failed` / `skipped`

**Migration default:** existing chats get `user`, so there's **no retroactive titling or
charging** of existing chats.

**Endpoint** `POST /chats/<id>/title/` (JSON only, called by the script):

| Situation | Status |
|---|---|
| A title was generated | 200 `{title, sidebar_html, balance}` |
| The title isn't provisional (renamed, already titled, or another request is generating it) | 409 |
| Balance ≤ $0 (skipped) | 402 |
| Proxy failure | 502 / 503 |
| Another user's chat, or unknown | 404 |
| Logged out | 401 |
| GET | 405 |

The script updates the nav balance from `balance`, as it does after replies.

---

## 3. Memories

### 3.1 Behavior

- **My Profile → "Memories"**, next to the Global System Prompt. It has:
  - the list of the user's notes (oldest first), each with a **Delete** button (a POST
    form)
  - an **"Add a memory"** single-line input with an **Add** button
  - help text: "Short notes about you that every model sees, e.g. 'I'm a student' or
    'keep answers short'. Sent with every message, so they count toward input tokens."
- There's **no editing.** Delete and re-add instead. That keeps the UI and the rules
  small.
- **Deleting doesn't need a confirmation page.** A memory is one short line the user
  typed and can re-add in seconds, unlike a chat and its history. It's deleted at once,
  with "Memory deleted." shown.
- **Only the user adds memories.** AI-generated or AI-suggested memories are out of
  scope, as requested.

### 3.2 How they're sent

A single system text is built at send time (extending `system_prompt_for` into
`system_text_for(user)`):

```
<Global System Prompt, if set>

About the user (notes they asked you to remember):
- I'm a student
- keep answers short
```

- With neither set → `None`, so there's still **no system field at all** (loop 4's
  rule).
- With only memories → just the memory block. With only a prompt → just the prompt,
  unchanged from today.
- It goes to every provider through the existing `system=` path: OpenAI's `system`
  message, Anthropic's `system`, Google's `systemInstruction`. **No adapter changes.**
- It's read **at send time**, so adding or deleting a memory affects the next message
  in every chat.
- Memories aren't stored on messages, and aren't sent with the **title** call (§2.3).
- The notes are the user's own words, sent only in their own chats. The worst a user
  can do is steer their own replies. There's no cross-user risk, and a test covers
  that.

### 3.3 Limits (they're billed on every message)

Every memory's characters ride along as input tokens on **every** message in **every**
chat. Here's the cost of the extra input, at about 4 characters per token:

| Cap | Tokens | Claude Haiku ($1/M in) | GPT-5.6 Luna ($0.50/M) | Gemini Flash ($0.30/M) |
|---|---|---|---|---|
| **10 memories × 200 characters (recommended)** | about 512 | 512 µ$ ($0.0005) per message | 256 µ$ | 154 µ$ |
| 5 × 200 | about 262 | 262 µ$ | 131 µ$ | 79 µ$ |
| 20 × 100 | about 512 | 512 µ$ | 256 µ$ | 154 µ$ |
| + the existing Global System Prompt cap (4,000 chars) | +1,000 | total ≈ 1,512 µ$ per message | 756 µ$ | 454 µ$ |

**Recommendation: at most 10 memories, each at most 200 characters.**
- 200 characters fits a real sentence ("I'm a second-year nursing student; explain
  medical terms simply"). The example notes are about 15 characters.
- At the cap, memories add about $0.0005 per Claude message, roughly a quarter of a
  typical message. That's a real but bounded cost.
- The cap is enforced on the server:
  - over 200 characters → 400
  - an 11th memory → 400, with "You can keep up to 10 memories. Delete one to add
    another."
  - empty or whitespace-only → 400
  - a case-insensitive duplicate of an existing note → 400
- **Make the cost visible:** My Profile shows "Your system prompt and memories add about
  N tokens to every message (≈ $X with Claude Haiku, $Y with GPT-5.6 Luna, $Z with Gemini
  Flash). Estimate." It's computed with the same `ceil(chars/4)` heuristic already used
  for missing usage, and the same `reply_cost_micros`, and labeled as an estimate.
- **The landing page's snapshot doesn't change.** It describes a new user with no
  prompt and no memories. It could add "plus any system prompt or memories you set", as
  a one-line copy tweak.

### 3.4 Data model and endpoints

- `accounts.Memory`: `user` FK (CASCADE), `text` (`CharField(max_length=200)`),
  `created_at`, ordered `created_at, id`. It's a new migration in `accounts`.
- `POST /profile/memories/` adds a memory:
  - valid → 302 to `/profile/#memories`, with "Memory added."
  - invalid → **400**, re-rendering My Profile with the error and the draft (through
    `render_profile`)
- `POST /profile/memories/<id>/delete/` → 302 with "Memory deleted." Another user's
  memory → **404**.
- Both are `login_required` (logged out → 302 to log-in) and `require_POST` (GET → 405).
- Admin: a read-only "Memories" inline on the user admin, like the Global System Prompt.

---

## 4. Decisions

Decided on 2026-09-29, before planning loop 7. **#1 departs from the study's
recommendation (§2.4).**

| # | Question | Decision |
|---|---|---|
| 1 | Who pays for the title call | **The app absorbs it. Titles are free and invisible to the user.** Each title call's token usage and cost are **recorded for admins only**, visible in Django admin and **never** on My Profile, in the credit history, or anywhere else users see. **Nothing goes in the user's ledger**, so `balance == sum(ledger)` and the "Deleted chats" reconciliation are unaffected, and no new ledger kind is needed. **Every new chat gets a title attempt regardless of balance**, so there's no $0 skip. |
| 2 | Which model | **The chat's own model** (§2.3). |
| 3 | When | **A separate request right after the first reply** (§2.2 option C). The first reply's latency is unchanged. |
| 4 | Title failures | As in §2.5, **except the user is never charged** in any case. The cost of an answered-but-unusable title, a title that lost a race with a rename, or one whose chat was deleted mid-call, is recorded for admins only. |
| 5 | Memory limits | **At most 10 memories of 200 characters each** (§3.3). |
| 6 | Deleting a memory | **Immediately, with no confirmation** (§3.1). |
| 7 | My Profile totals | **One "Spent" total, for replies only**, and the totals must still add up: (per-chat totals + deleted chats = spent; added − spent = balance). Titles never appear there. |

## 5. Suggested plan shape (loop 7), one conventional commit each

1. `feat: allow a smaller output cap per model call`. The optional `max_output_tokens`
   on `llm.complete` and the adapters, plus a per-call timeout, with provider-table
   tests.
2. `feat: add the title ledger kind and conversation link`. The migrations, My Profile
   totals and the "Deleted chats" reconciliation, and admin.
3. `feat: name chats automatically after the first reply`. `title_source`, the title
   service and cleanup, the `POST /chats/<id>/title/` endpoint, the script trigger, and
   tests (mocked proxy, every status, races with rename and delete, the $0 skip).
4. `feat: add Memories on My Profile`. The model, forms, endpoints, the profile section
   with the cost estimate, `system_text_for`, admin, and tests (limits, each provider's
   system field, isolation, not sent with titles).
5. `chore: update README`.

Then verify:
- **Real proxy, each model:** the first reply, then the title arrives, its charge
  matches the formula, and the ledger kind is `title`. Memories change replies (e.g.
  "Always answer in one sentence"). The prompt plus memories are accepted by all three
  providers.
- **Browser check:** the title appears in the sidebar and header without a reload. Add
  and delete memories. Screenshots.
