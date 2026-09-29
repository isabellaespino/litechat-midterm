# Study: A metered, pay-as-you-go multi-provider LLM chat app (Litechat clone)

- **Date:** 2026-09-29 (Unix 1790657879)
- **Type:** study (feasibility and tradeoffs; no code)
- **Status:** decisions recorded (§10). Ready for a plan.

## 1. Request

Build a web app that copies the core of [Litechat](https://litechat.ai): people who
won't pay for a subscription get pay-per-use access to LLMs from several providers.

Required features:

1. Users sign up and log in.
2. Each user has a prepaid credit balance in US dollars. Admins top it up through
   Django admin.
3. Users chat with a model they choose from a catalog covering OpenAI, Anthropic and
   Google.
4. The token usage of each reply is charged against the balance. Chatting is blocked
   when the balance is $0 or less.
5. Users can revisit and rename past chats.

Constraints: Django, SQLite, Django's built-in auth and admin, server-rendered templates.
LLMs are reached only through the proxy at `https://proxy.litechat.ai/docs`. Keys live in
`.env` as `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` and `GOOGLE_API_KEY`.

**Verdict: feasible, and small.** Each feature maps onto something Django already
provides or onto a few simple models. The hard parts are correct billing (normalizing
usage across providers, sub-cent amounts, concurrency), not infrastructure.

## 2. What Litechat actually does (reference scope)

The public site advertises model switching (OpenAI GPT-4o/GPT-5, Anthropic Claude Sonnet),
file and image uploads, a web-search toggle, and saved chats that can be renamed and
managed. The landing page doesn't describe its pricing or credits.

We copy only the **metered chat core** for individual users. §9 lists what is out of
scope, including organization billing accounts.

## 3. Stack justification (required by CLAUDE.md for the first study)

### 3.1 Why Django, SQLite, built-in auth and admin, and server-rendered templates

| Choice | Why it fits | What we give up |
|---|---|---|
| **Django** | Auth, sessions, CSRF, ORM, migrations, forms, admin and a test runner all ship in one package. Almost every feature here is a built-in, so most of our code is domain logic (billing, adapters) rather than plumbing. | Async and streaming are more awkward than in FastAPI or Node. That's acceptable because we don't stream (§6.4). |
| **SQLite** | No server to install, one file, and Python ships the driver. A fresh clone runs with no setup. Plenty for a class-scale, single-host app. | Writes are serialized, `select_for_update` does nothing, and it won't handle many concurrent writers. Fine at this scale, and §6.3 covers how billing works around it. |
| **Built-in auth** | `UserCreationForm`, `LoginView` and `LogoutView` give us sign-up and login in a few lines, with password hashing, validators and session handling already hardened. | No email verification or social login. Not required. |
| **Django admin** | The spec says admins top up balances and edit the model catalog "through Django admin". Admin gives us both UIs for free, with permissions, audit-friendly forms, filtering and search. | The admin UI is generic. We customize it lightly (inlines, read-only fields, `list_filter` by provider, `save_model`). |
| **Server-rendered templates, no JS framework** | Each page is a form plus a list. POST/redirect/GET covers the whole interaction model. There's no build step or node_modules. Because the browser never talks to the proxy, keeping every LLM request on the backend (a CLAUDE.md rule) happens naturally, and API keys never reach the client. | The page reloads on every send, and replies appear only when complete (no typing effect). |

### 3.2 Alternatives considered

| Alternative | Why not |
|---|---|
| Flask or FastAPI + SQLAlchemy | We would have to assemble auth, CSRF, migrations and an admin UI from extensions. The admin UI alone is a core requirement (top-ups and the model catalog) that Django provides for free. |
| Django REST Framework + a React/Vue SPA | Two codebases and a JS toolchain, plus an API layer the app doesn't need. It also raises the risk of LLM calls or keys leaking into browser code. |
| PostgreSQL | Better concurrency and a real `select_for_update`, but it adds a service to install and configure, which breaks "set up from README and requirements.txt alone". Django's ORM makes switching later a settings change. |
| Next.js / Rails / Laravel | Comparable productivity, but they leave the Python ecosystem the project specifies and bring no advantage for this scope. |

## 4. The proxy: what we're integrating with

The proxy docs describe four interfaces. We would use three of them:

| Provider | Endpoint (base `https://proxy.litechat.ai`) | Auth header | Model | Usage fields |
|---|---|---|---|---|
| OpenAI | `POST /openai/v1/chat/completions` | `Authorization: Bearer <key>` | `gpt-5.6-luna` | `usage.prompt_tokens`, `usage.completion_tokens`, `usage.total_tokens` |
| Anthropic | `POST /anthropic/v1/messages` (+ `anthropic-version: 2023-06-01`) | `x-api-key: <key>` | `claude-haiku-4-5-20251001` | `usage.input_tokens`, `usage.output_tokens` |
| Google | `POST /google/v1beta/models/gemini-3.8-flash:generateContent` | `x-goog-api-key: <key>` | `gemini-3.8-flash` | `usageMetadata.promptTokenCount`, `candidatesTokenCount`, `totalTokenCount` |

The fourth, OpenAI Responses (`/openai/v1/responses`), isn't needed. It requires
`store: false` and doesn't support `previous_response_id`, so it has no advantage over Chat
Completions for us.

Facts from the docs that shape the design:

- **Each provider has exactly one model.** We seed only these three models (§5). The
  catalog is a DB table, so admins can add more models later without code changes, as
  long as the proxy serves them.
- **All three interfaces are backed by DeepSeek Flash.** The docs say the
  interfaces "do not reproduce the named providers' model behavior." Replies will look
  alike across providers. What we're really building is three request/response
  *adapters* plus metering. Model quality doesn't matter here.
- **The proxy is stateless.** We send the full conversation history on every turn, so we
  must store every message ourselves (which we need for "revisit past chats" anyway).
- **Request and response shapes differ by provider.**
  - Roles: OpenAI and Anthropic use `user`/`assistant`. Google uses `user`/`model`.
  - System prompt: OpenAI takes it as a message. Anthropic takes a top-level `system`
    field. Google takes a `systemInstruction` field.
  - Output limit: OpenAI takes `max_tokens` (optional). Anthropic requires
    `max_tokens`. Google takes `generationConfig.maxOutputTokens`.
  - Reasoning control: OpenAI takes `reasoning_effort: "none"`. Anthropic takes
    `thinking: {"type": "disabled"}`. Google takes
    `thinkingConfig.thinkingBudget: 0`. Disabling reasoning keeps replies cheap and
    predictable.
  - Stop and truncation signals: OpenAI returns `finish_reason` (`length`). Anthropic
    returns `stop_reason` (`max_tokens`). Google returns `finishReason` (`MAX_TOKENS`
    or `SAFETY`).
- **Errors:** 400 means the request needs fixing. 401 or 403 means bad auth. 429 means
  rate-limited. 502 or 504 means an upstream failure. 503 means contact the admin.

**Env var naming.** The Chat Completions page refers to a `BUILD_OPENAI_KEY` backend
variable. The env var name is only our own config, so we follow the spec
(`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`) and list all three in
`.env.example`.

## 5. Proposed domain model (conceptual)

All money amounts are **integers of micro-dollars** (1 USD = 1,000,000 µ$). See §6.1.

- **User**: Django's built-in `auth.User`, unchanged.
- **Wallet** (one-to-one with User): `balance_micros` (a signed integer, because it can go
  slightly negative, §6.3). It's created automatically for every new user, and is
  immediately credited with **$2.00 of sign-up credit**, recorded as a ledger entry.
- **CreditTransaction** (append-only ledger): user, signed `amount_micros`, `kind`
  (`signup` / `topup` / `charge` / `adjustment`), optional FK to the message it paid for,
  `created_by` (the admin who made a top-up), note, timestamp.
- **LLMModel** (catalog, editable in Django admin):
  - `provider`: `openai` / `anthropic` / `google`. The picker and the admin list are
    grouped by provider.
  - `api_model_id`: the id sent to the proxy, e.g. `gpt-5.6-luna`.
  - `display_name` and a short `description`.
  - `tier`: `value` / `standard` / `premium`.
  - Its own price: `input_price_micros_per_mtok` and `output_price_micros_per_mtok`
    (micro-dollars per 1M tokens). The price is split into input and output because the
    proxy reports those counts separately.
  - `is_active`, so admins can hide a model without deleting chats that used it.
- **Conversation**: owner, title, `llm_model` FK (protected on delete), created/updated
  timestamps.
- **Message**: conversation, role (`user`/`assistant`), content, and for assistant
  messages: `input_tokens`, `output_tokens`, `cost_micros`, `stop_reason`. It also
  snapshots the prices applied, so later catalog price edits don't rewrite history.

Storing the cost on each message and in the ledger makes every charge auditable.
Admins can check that `balance_micros == sum(ledger)`.

**Seed data:** exactly the three proxy models, one per provider. These are starting
values (every model is DeepSeek Flash underneath), and admins can change them.

| Provider | Model id | Display name | Tier | Input / output price per 1M tokens |
|---|---|---|---|---|
| Anthropic | `claude-haiku-4-5-20251001` | Claude Haiku | value | $1.00 / $5.00 |
| OpenAI | `gpt-5.6-luna` | GPT-5.6 Luna | value | $0.50 / $2.00 |
| Google | `gemini-3.8-flash` | Gemini Flash | value | $0.30 / $2.50 |

In micro-dollars, $1.00 per 1M tokens is 1,000,000 µ$ per 1M tokens, i.e. exactly 1 µ$
per token, so every seeded price is a whole number.

## 6. Key tradeoffs

### 6.1 Money representation: prepaid USD in micro-dollars (decided)

A single reply costs a fraction of a cent. For example, 1,000 input tokens plus 300 output
tokens at $1/$4 per 1M tokens costs $0.0022. Cents are too coarse for that, and floats
drift. So:

- **Storage:** every amount (balance, ledger entries, message costs, prices) is a
  whole-number count of micro-dollars in an `IntegerField`/`BigIntegerField`. This works
  well with SQLite and `F()` arithmetic.
- **Cost of a reply:** `ceil((in_tokens × input_price + out_tokens × output_price) /
  1,000,000)` µ$, computed with integers only. Rounding up means no reply is ever free
  from rounding.
- **Display:** users see **"Available credit"** in dollars and cents, e.g. `$1.99`.
  The formatter rounds **down** to the cent (never overstating what's available), and
  shows negatives as `-$0.01`. A template filter does this in one place. Per-reply costs
  are too small for cents, so the usage history shows them with more decimal places
  (e.g. `$0.0022`).
- **Admin top-ups** are entered in dollars (e.g. `5.00`) and converted to micro-dollars
  on save, so admins never type µ$ values.

### 6.2 Top-ups through Django admin

- **Rejected: admins edit the balance directly.** There's no audit trail, and it races
  with charges (an admin form holding a stale balance overwrites a charge that landed
  in between).
- **Chosen: admins add a `CreditTransaction(kind=topup)`**, via its own admin page or
  an inline on the user. Its `save_model` applies `balance = F('balance') + amount` in
  the same transaction. In admin, the balance is read-only. An optional admin action,
  "Add $N to selected users", covers bulk top-ups.

### 6.3 Charging and blocking (decided)

The cost of a reply is only known *after* the proxy returns usage. The decision:

- **Block when the balance is $0 or less.** Sending is refused before any proxy call.
- **Always charge the actual cost** of every reply, even if that takes the balance
  slightly negative. The next top-up covers the deficit first.
- **The overdraft is bounded** by a fixed per-request output cap of **1,024 output
  tokens** (`max_tokens`, stored as a setting). The worst case is one reply's cost at the
  final positive balance. At the seeded prices, 1,024 output tokens costs at most about
  half a cent (Claude Haiku: 1,024 × $5/1M ≈ $0.0051), plus the input. We don't shrink replies based on the
  balance, so users never get a surprise truncation.

Alternatives considered: sizing the output cap to what the balance can afford (rejected:
truncates replies unexpectedly), and holding the maximum cost up front then settling
(rejected: extra state and cleanup of stuck holds, too much for this scope).

**Concurrency.** Two tabs sending at once could both pass the pre-check. Mitigations:

- Deduct with `UPDATE ... SET balance = balance - cost` (Django `F()`) inside
  `transaction.atomic()`, never read-modify-write in Python.
- Write the Message, the ledger row and the balance update in one atomic block after
  the proxy call. Don't hold a transaction open during the slow HTTP call: that would
  lock SQLite for seconds.
- `select_for_update` does nothing on SQLite. A rare double-send makes the overdraft at
  most two replies' cost, which fits the "slightly negative" policy.

**Failures.** If the proxy returns an error (4xx/5xx or a timeout), the user isn't
charged and no assistant message is saved. We keep the user's message so they can
retry. Truncated replies (`length` / `max_tokens` / `MAX_TOKENS`) *are* charged,
because tokens were consumed. A Google `SAFETY` stop is charged for whatever usage is
reported.

**Missing usage.** If a response lacks usage fields, estimate the tokens (about 4 chars
per token) and log a warning rather than give the reply away for free.

### 6.4 Streaming vs. whole replies

- **Streaming (SSE):** better UX, but needs browser JS to read the stream, a
  streaming Django response, and usage gathered from terminal events. Each provider
  signals the end of a stream differently (`[DONE]`, `message_stop`, no sentinel at
  all). It also makes billing on disconnect ambiguous.
- **Chosen: whole replies.** A form POST, then the backend calls the proxy and waits,
  then saves, then redirects to the chat page (PRG). This keeps templates pure, billing
  exact and tests simple. The cost is a wait of a few seconds with no feedback. One line
  of inline JS to disable the Send button is acceptable, since it's not a framework.
  Streaming can be a later study.

### 6.5 Provider integration: SDKs vs. plain HTTP

- **Rejected: three official SDKs** (`openai`, `anthropic`, `google-genai`). They're typed
  and familiar, but they add three dependencies. We'd need to override the base URLs,
  and the SDKs may send headers or paths the proxy doesn't support.
- **Chosen: one HTTP client.** `requests`, with three small adapter functions selected by
  `LLMModel.provider`. Each has the signature `(model, history, max_tokens) -> (text,
  input_tokens, output_tokens, stop_reason)`. The request bodies are small and
  documented above. That's one dependency, full control over URLs and headers, and it's
  easy to mock in tests. Views never see which provider is in use.

Set a timeout on every call (e.g. 60 s). Map proxy 429, 502, 503 and 504 to a
friendly error message and a 502 or 503 response from our own view (§6.8).

### 6.6 Model choice per chat vs. per message

- **Chosen: per chat.** Pick the model when starting a chat from a picker grouped by
  provider (`<optgroup>`). Each option shows the display name, the tier and the price, and
  the description is visible alongside. The model is stored on `Conversation`.
- **Deferred: per message.** More flexible, like Litechat's "switch models", but every
  adapter must accept history created by others. That's fine, because we store neutral
  `user`/`assistant` roles and translate on send. It's a cheap later extension.

### 6.7 History growth and cost

Every turn resends the entire history, so input tokens (and cost) grow with chat
length. Show the cost on each reply and the running total on each chat, and add a
generous history cap (e.g. the last 40 messages) as a setting. Mention this in the UI
copy so users understand why long chats cost more.

### 6.8 HTTP status codes (CLAUDE.md rule; decided)

| Situation | Status |
|---|---|
| GET pages | 200 |
| Successful form POSTs (redirect after POST) | 302 |
| Invalid form submissions (sign-up, login, rename, send, new chat), re-rendered with errors | **400** |
| Sending with a balance of $0 or less, re-rendered with an "Add credit" notice | **402 Payment Required** |
| Another user's chat, or an unknown chat | 404 |
| An inactive model chosen for a new chat | 400 |
| Proxy failure, with a friendly page | 502, or 503 for rate limits and outages |
| Anonymous access to chat pages | 302 to login |

Django's `LoginView` and generic views re-render invalid forms with 200 by default, so
the plan must override `form_invalid` (or render with `status=400`) everywhere, and test
it.

### 6.9 Titles and renaming

- **Chosen: auto-title from the first ~50 characters of the first user message.** It's
  free and instant.
- **Rejected: auto-title via an LLM call.** It would spend the user's money without asking.
- **Rename:** a small form on the chat page that POSTs a new title (owner only,
  length-validated, 400 if invalid).

### 6.10 Rendering replies

LLM output is untrusted. Rely on Django's autoescaping plus `linebreaksbr`. Rendering
markdown would need a new dependency and HTML sanitizing (`markdown` + `bleach`/`nh3`).
Defer it.

## 7. Dependencies (justification required before adding)

| Package | Why |
|---|---|
| `Django` (pinned 5.x LTS) | The framework (§3). |
| `requests` | HTTP calls to the proxy (§6.5). `urllib` from the standard library would work, but it's verbose and makes timeouts and JSON handling error-prone. |
| `python-dotenv` | Loads `.env` into the environment for `settings.py`. Small, with no transitive dependencies. The alternative is `django-environ`, which is heavier than we need. |

Nothing else. In particular: no provider SDKs, no DRF, no Celery, no JS toolchain, and no
money library (integers of micro-dollars are enough).

## 8. Operational rules and how the design meets them

- **Keys:** read from the environment in `settings.py` and used only in the backend
  adapter module. They're never passed to templates or logged. `.env.example` lists
  `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` and
  `GOOGLE_API_KEY` with no values.
- **`.gitignore`:** `db.sqlite3`, `.venv/`, `.env`, `__pycache__/`, `*.pyc`.
- **Seed data:** an idempotent `seed` management command (`get_or_create` on
  `api_model_id`). It loads the three proxy models only. New users get their $2.00 from
  the automatic sign-up credit, so the seed command doesn't need a demo user. The command
  is preferred over a fixture because it's idempotent: re-running it skips models that
  already exist, so it never duplicates rows or overwrites prices an admin has edited. It must never delete or reset existing rows.
- **Navigation:** a base template with a nav bar containing Chats (list), New chat,
  Available credit (linking to the usage history), Admin (staff only), and Log in/Sign
  up/Log out. Every chat in the list links to its page, and there's a rename form on the
  chat page.
- **Testing:** use Django's `TestCase` (throwaway test DB). Mock the proxy with
  `unittest.mock` and fake responses in each of the three shapes. Key tests:
  - usage normalization for each provider
  - micro-dollar cost math and rounding up
  - display formatting (`$1.99`, rounding down, negatives)
  - blocking at ≤ $0 with 402, and charging into a slight negative
  - no charge on a proxy error
  - 400 on invalid forms, and 404 on another user's chat
  - admin top-up updating the balance and the ledger

  There are no live proxy calls in the test suite. At most, one manual smoke check.
- **Run:** `python manage.py runserver 0.0.0.0:8000`.

## 9. Out of scope (candidates for later studies)

- Organization or team billing accounts (shared balances, member management).
- Self-service payments (Stripe), refunds, invoices and currencies other than USD.
- Streaming replies, and per-message model switching.
- File and image uploads (the proxy supports them, but they're private per account and
  expire after an hour), and web search (not offered by the proxy).
- Markdown rendering, per-user rate limiting, and email verification.

## 10. Decisions log

| # | Question | Decision |
|---|---|---|
| 1 | Overdraft policy | Charge the actual cost of every reply, even if the balance goes slightly negative. Block sending when the balance is $0 or less. The overdraft is bounded by a fixed output cap (§6.3). |
| 2 | Credit unit | A prepaid USD balance, shown as "Available credit" in dollars and cents (e.g. `$1.99`). Every amount is stored as whole micro-dollars (§6.1). |
| 3 | Model catalog | A DB table editable in Django admin, grouped by provider, each with a display name, a short description, a tier (value/standard/premium) and its own price (§5). |
| 4 | Seed models | Only the three models the proxy serves (§5). |
| 5 | Invalid form status | 400 (§6.8). |
| 6 | Organization billing | Out of scope (§9). |
| 7 | Proxy env var names | Follow the spec (`OPENAI_API_KEY`, etc.), not the docs' `BUILD_OPENAI_KEY` (§4). |
| 8 | Seeded tiers | All three seeded models are **value** tier (§5). |
| 9 | Seeded prices (input / output per 1M tokens) | Claude Haiku $1.00 / $5.00; GPT-5.6 Luna $0.50 / $2.00; Gemini Flash $0.30 / $2.50 (§5). |
| 10 | Output cap | Replies are capped at **1,024 output tokens** (§6.3). |
| 11 | Sign-up credit | Every new user automatically receives **$2.00**, recorded as a `signup` ledger entry (§5). |

No open questions remain for loop 1.

## 11. Recommendation

Proceed. Suggested plan structure, one conventional commit each:

1. `chore:` project scaffold, `.gitignore`, `.env.example`, `requirements.txt`, README
   setup steps.
2. `feat:` sign-up/login/logout (with 400 on invalid forms) and the base template with
   navigation.
3. `feat:` Wallet + CreditTransaction ledger in micro-dollars, the "Available credit"
   display, and admin top-up in dollars.
4. `feat:` LLMModel catalog (provider, tier, description, prices) with admin, and the
   seed command.
5. `feat:` proxy adapters (OpenAI, Anthropic, Google) with usage normalization, and
   tests using mocked responses.
6. `feat:` conversations and messages: create (grouped model picker), send, list, view,
   rename.
7. `feat:` metering: the ≤ $0 block (402), atomic actual-cost charge, and a usage history
   page.
8. `chore:` wiki sync (`doc/wiki/`).
