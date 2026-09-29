# Plan: Loop 2: end-to-end chat with the OpenAI model

- **Date:** 2026-09-29 (Unix 1790661385)
- **Source study:** `doc/study/1790657879-litechat-clone-feasibility.md` (§4 proxy, §6.3
  charging, §6.4 whole replies, §6.5 plain HTTP, §6.8 status codes)
- **Builds on:** loop 1 (`doc/plan/1790659225-loop1-foundation.md`, wiki in `doc/wiki/`)
- **Branch:** `loop2-openai-chat`, off `main`. Don't merge during execute. Wait for the
  rendezvous command.
- **Scope:**
  - Start a chat by picking a model. Only OpenAI models can be picked this loop.
  - Send messages and see whole replies. The history is stored and the full history is
    resent on every request.
  - Charge each reply its actual cost from the reported usage, with no charge on a proxy
    error.
  - Block sending with 402 when the balance is $0 or less, and cap replies at 1,024
    output tokens.
  - Add `requests` to the requirements, and add a chats list linked from the nav.
  - Show ledger amounts in the admin as dollars.
- **Not in this loop:**
  - Anthropic and Google adapters. Those models stay in the catalog but can't be picked
    yet.
  - Renaming chats (loop 3).
  - Streaming, markdown rendering, a history cap, per-message model switching.

## Fixed values

| Setting (`config/settings.py`) | Value |
|---|---|
| `LLM_PROXY_BASE_URL` | `https://proxy.litechat.ai` (a setting, not a secret, so it isn't in `.env`) |
| `LLM_TIMEOUT_SECONDS` | `60` |
| `MAX_OUTPUT_TOKENS` | `1024` (already defined in loop 1; now sent as `max_tokens`) |
| `CHAT_MESSAGE_MAX_CHARS` | `8000` (form validation, limits the input cost of a single message) |
| `CHAT_PROVIDERS` | `["openai"]`: the providers whose models can be picked in chat |

**Proxy contract** (from `https://proxy.litechat.ai/docs/openai/chat-completions`):

- **Request:** `POST {LLM_PROXY_BASE_URL}/openai/v1/chat/completions`, with headers
  `Authorization: Bearer <OPENAI_API_KEY>` and `Content-Type: application/json`.
- **Request body:**
  `{"model": "<api_model_id>", "messages": [{"role": "user"|"assistant", "content": "..."}...], "max_tokens": 1024, "reasoning_effort": "none"}`
- **Response:** `choices[0].message.content`, `choices[0].finish_reason`
  (`stop`/`length`), and `usage.prompt_tokens` / `usage.completion_tokens`.
- **Proxy errors:** 400, 401/403, 429, 502/504, 503.

**Cost of a reply** (in µ$, integers only, rounded up):
`ceil((prompt_tokens × input_price_micros_per_mtok + completion_tokens × output_price_micros_per_mtok) / 1_000_000)`.
Example: GPT-5.6 Luna, 1,000 in + 300 out → `ceil((500_000_000 + 600_000_000) / 1e6)` =
1,100 µ$ = $0.0011.

**Status codes:**

| Situation | Status |
|---|---|
| GET pages | 200 |
| Successful send or new chat | 302 to the chat page |
| Invalid message form (empty, too long, missing or unsupported model) | 400 |
| Balance ≤ $0 | **402** (the proxy isn't called) |
| Proxy 429 or 503, timeout, connection error, missing API key | 503 |
| Proxy 400/401/403/5xx, or a malformed response | 502 |
| Another user's chat, or an unknown chat | 404 |
| Anonymous visitor | 302 to log-in |

**Rule on failure:** if the proxy call fails, **nothing is saved and nothing is
charged**. The page re-renders with a friendly error and the user's draft still in the
textarea, so they can resend. This refines the study's §6.3 ("keep the user's message"):
saving nothing avoids unanswered messages in the history that would then be resent.

## Layout additions

```
llm/                 # plain Python package (not a Django app): proxy clients
  __init__.py        #   LLMReply dataclass, LLMError, complete(model, messages) -> dispatch by provider
  openai.py          #   Chat Completions adapter (requests)
  tests.py
chat/                # Django app: Conversation, Message, views, admin
templates/chat/      # conversation_list.html, conversation_new.html, conversation_detail.html
config/test_runner.py  # test runner that blocks real HTTP
```

---

## Step 0: Branch

- [ ] `git switch -c loop2-openai-chat` from an up-to-date `main`.

## Step 1: `fix: show ledger amounts in dollars in admin`

- [ ] Change `CreditTransaction.__str__` to "<Kind> <±$amount> for <user>" using
      `format_dollars_precise`, e.g. "Top-up $5.00 for alice" and "Charge -$0.0011 for
      alice". This is what admin shows in page titles, breadcrumbs, the "was added"
      message and Recent actions. It currently shows "5000000 µ$".
- [ ] Confirm the columns and read-only fields already use dollars:
  - [ ] Ledger list `amount` column
  - [ ] Ledger read-only `amount` field
  - [ ] Wallet `available_credit`
  - [ ] User inline
- [ ] Make sure no admin page shows `amount_micros` or `balance_micros` raw. The
      read-only change page's fields list must not include them.
- [ ] Tests:
  - [ ] `str(txn)` for the top-up and charge examples above.
  - [ ] After an admin top-up of $5.00, the success message and the change page title
        contain "$5.00" and not "5000000".
- [ ] Commit.

## Step 2: `build: add requests for LLM proxy calls`

- [ ] Add `requests>=2.32,<3` to `requirements.txt` (the reason is in the study, §7)
      and install it in `.venv`.
- [ ] Commit.

## Step 3: `feat: add OpenAI proxy client`

- [ ] Add these settings: `LLM_PROXY_BASE_URL`, `LLM_TIMEOUT_SECONDS` and
      `CHAT_PROVIDERS`.
- [ ] `llm/__init__.py`:
  - [ ] `LLMReply` dataclass with fields `text`, `input_tokens`, `output_tokens`,
        `stop_reason` and `usage_estimated: bool`.
  - [ ] `LLMError(Exception)` with `status` (the HTTP status our view returns: 502 or
        503) and a user-safe `message`. It must never include the API key or the raw
        response body.
  - [ ] `complete(llm_model, messages)` dispatches on `llm_model.provider`. Anything
        other than `openai` raises `LLMError(503, "This model isn't available yet.")`.
- [ ] `llm/openai.py`, `complete(api_model_id, messages)`:
  - [ ] If `OPENAI_API_KEY` is empty, raise `LLMError(503)` without making a request.
  - [ ] `requests.post(url, json=body, headers=..., timeout=LLM_TIMEOUT_SECONDS)`, with
        the body exactly as in the proxy contract above.
  - [ ] Map failures to `LLMError`:
    - `Timeout` or `ConnectionError` → 503.
    - A 429 or 503 response → 503.
    - Any other non-2xx response → 502.
    - Invalid JSON or a missing `choices[0].message.content` → 502.

    Log the proxy's status code and the model, never the headers or the key.
  - [ ] Parse `text`, `finish_reason`, `prompt_tokens` and `completion_tokens`. If
        usage is missing, estimate tokens (`ceil(chars / 4)` for the input and for the
        output), set `usage_estimated=True`, and log a warning.
- [ ] `config/test_runner.py`: a `NoNetworkTestRunner` (subclass of `DiscoverRunner`)
      patches `requests.sessions.Session.request` to raise `RuntimeError("Real HTTP
      request attempted in tests")` for the whole run. Set
      `TEST_RUNNER = "config.test_runner.NoNetworkTestRunner"`. Tests mock
      `llm.openai.requests.post`, so no request ever reaches the network.
- [ ] Tests (`llm/tests.py`), all with the mocked `llm.openai.requests.post`:
  - [ ] Request shape: the URL, `Authorization: Bearer <key from settings>`, a body with
        `model`, the full `messages` list in order, `max_tokens == 1024` and
        `reasoning_effort == "none"`, and `timeout=60`.
  - [ ] A success response is parsed into an `LLMReply`. `finish_reason: "length"` is
        passed through.
  - [ ] Missing usage: tokens are estimated and `usage_estimated` is true.
  - [ ] Status 400, 401, 500, 502 and 504 → `LLMError.status == 502`. Status 429 and
        503 → 503.
  - [ ] `Timeout` and `ConnectionError` → 503. A malformed body → 502.
  - [ ] An empty key → 503, and `requests.post` isn't called.
  - [ ] A non-OpenAI provider passed to `complete()` → 503.
  - [ ] Guard test: calling the real `requests.get("https://example.com")` inside a
        test raises `RuntimeError`.
- [ ] Commit.

## Step 4: `feat: add conversations and messages`

- [ ] `chat` app, added to `INSTALLED_APPS`.
- [ ] `Conversation` fields:
  - `owner` (FK to User, CASCADE)
  - `title` (100 characters, default "New chat")
  - `llm_model` (FK to `catalog.LLMModel`, PROTECT)
  - `created_at`, `updated_at`
  - `Meta.ordering = ["-updated_at"]`
- [ ] `Message` fields:
  - `conversation` (FK, CASCADE, `related_name="messages"`)
  - `role` (`user` / `assistant`)
  - `content`
  - `created_at`
  - Assistant-only (nullable or default 0): `input_tokens`, `output_tokens`,
    `cost_micros`, `stop_reason`, `usage_estimated`
  - Price snapshot: `input_price_micros_per_mtok`, `output_price_micros_per_mtok`
  - `Meta.ordering = ["created_at", "id"]`
- [ ] Add `CreditTransaction.message`: a `OneToOneField("chat.Message", null=True,
      blank=True, on_delete=SET_NULL)`, and a `message=None` parameter on
      `post_transaction`. The migration depends on `chat`.
- [ ] `billing/services.py`: `reply_cost_micros(input_tokens, output_tokens,
      input_price, output_price)`, integer ceil as defined above.
- [ ] `chat/services.py`:
  - [ ] `title_from(text)`: the first line, whitespace collapsed, at most 50 characters,
        with `…` added if it was cut. It falls back to "New chat".
  - [ ] `history_for(conversation)`: all stored messages in order, as
        `[{"role", "content"}]`.
  - [ ] `send_message(user, llm_model, text, conversation=None)`:
    1. Build the messages: the stored history plus the new user message.
    2. Call `llm.complete()` **outside** any transaction. On `LLMError`, re-raise with
       nothing saved.
    3. In one `transaction.atomic()` block:
       - create the conversation if it's new, titled with `title_from(text)`
       - save the user message and the assistant message (with tokens, stop reason,
         price snapshot and `cost_micros`)
       - `post_transaction(user, -cost, "charge", note=f"Reply in “{title}”",
         message=assistant_msg)`
       - bump `conversation.updated_at`
    4. Return the conversation.

    The caller checks the balance first (Step 5). The charge is applied even if the
    balance goes negative.
- [ ] Admin (read-only, for support):
  - [ ] `Conversation`: list shows owner, title, model, message count, total cost ($)
        and updated date. A read-only `Message` inline shows role, content, tokens and
        cost ($).
  - [ ] No add, change or delete.
  - [ ] The ledger admin shows the linked message's conversation for `charge` rows.
- [ ] Tests:
  - [ ] `reply_cost_micros`: the $0.0011 example; 1 input token at $0.30/1M → 1 µ$
        (rounds up); 0 tokens → 0.
  - [ ] `title_from`: a long message is cut with `…`; blank input gives "New chat".
  - [ ] `send_message` with a mocked `llm.complete`:
    - creates both messages
    - charges the exact cost
    - the ledger row links to the assistant message
    - the balance equals the ledger sum
  - [ ] `send_message` when `llm.complete` raises: no conversation, no messages and no
        transaction are created, and the balance is unchanged.
  - [ ] The history passed to `llm.complete` on the third turn has 5 messages
        (user/assistant/user/assistant/user), in order.
- [ ] Commit.

## Step 5: `feat: add chat pages with metering`

- [ ] Forms:
  - [ ] `MessageForm`: `content`, required, stripped, at most `CHAT_MESSAGE_MAX_CHARS`.
  - [ ] `NewChatForm`: `MessageForm` plus `llm_model`, a `ModelChoiceField` over active
        models whose provider is in `CHAT_PROVIDERS`. The choices are grouped by
        provider in `<optgroup>`s, and each label shows the name, tier and "$in / $out
        per 1M".
- [ ] Views (all `login_required`):
  - [ ] `GET /chats/` (`chat_list`): the user's conversations with title, model, message
        count, total cost ($) and last updated. It has a **New chat** button and an
        empty state that links to New chat.
  - [ ] `GET /chats/new/` (`chat_new`): the model picker and the first message.
  - [ ] `POST /chats/new/`:
    - invalid form → 400
    - balance ≤ 0 → 402
    - `LLMError` → 502 or 503, with the draft and the chosen model preserved
    - otherwise `send_message` → 302 to the chat
  - [ ] `GET /chats/<id>/` (`chat_detail`): 404 unless the chat is the user's own. It
        shows:
    - the title and model name, with the total cost of the chat
    - the messages, with `linebreaksbr`. Each reply shows "N in / M out tokens ·
      $0.0011". A cut-off reply adds "(cut off at 1,024 tokens)". An estimated reply
      adds "(estimated usage)".
    - the send form
  - [ ] `POST /chats/<id>/` (the send action, same URL):
    - not the owner → 404
    - invalid form → 400
    - balance ≤ 0 → 402
    - the chat's model is inactive or unsupported → 400 ("This model is no longer
      available. Start a new chat.")
    - `LLMError` → 502 or 503 with the draft preserved
    - success → 302 to `chat_detail` with the `#latest` anchor
  - [ ] The 402 response re-renders the same page with a notice: "You're out of credit
        (Available credit: $0.00 or less). Contact an administrator to top up." It
        links to `/credit/`.
  - [ ] The balance check reads `get_wallet(user).balance_micros` immediately before the
        proxy call.
- [ ] Templates: `chat/conversation_list.html`, `conversation_new.html`,
      `conversation_detail.html`. The send area says "Replies can take a few seconds."
      There's no JavaScript.
- [ ] Navigation:
  - [ ] base nav (logged in): **Chats** (→ `/chats/`) and **New chat** (→
        `/chats/new/`)
  - [ ] home page (logged in): a **Start a chat** button
  - [ ] each chat in the list links to its page, and the chat page links back to Chats
  - [ ] `/models/`: models whose provider isn't in `CHAT_PROVIDERS` get a "Coming soon"
        badge, and chat-ready models link to New chat
- [ ] Tests (`chat/tests.py`, mocking `llm.openai.requests.post` with an OpenAI-shaped
      JSON response):
  - [ ] Anonymous GET of `/chats/`, `/chats/new/` and `/chats/<id>/` → 302 to log-in.
  - [ ] `GET /chats/new/` → 200, and it lists GPT-5.6 Luna but not Claude Haiku or
        Gemini Flash.
  - [ ] New chat POST (valid):
    - → 302 to the chat
    - creates 1 conversation and 2 messages
    - the wallet drops by exactly the computed cost
    - there's one `charge` row linked to the reply
    - the proxy was called once with `max_tokens=1024`
  - [ ] Second send → 302. The proxy received the 3 messages in order (history
        resent). The ledger has two charges.
  - [ ] Proxy returns 500 → 502. Proxy returns 429 → 503. Timeout → 503. In each case
        nothing new is saved, the balance is unchanged, and the response contains the
        draft text.
  - [ ] Balance exactly 0 → 402 and the proxy is **not** called. Balance -1 µ$ → 402.
  - [ ] Balance 1 µ$ → the send succeeds and the balance goes negative by the cost
        minus 1. The next send → 402.
  - [ ] Empty message → 400. A message over 8,000 characters → 400. An Anthropic model
        id posted to New chat → 400. A deactivated model in an existing chat → 400. The
        proxy isn't called in any of these.
  - [ ] Another user's chat: GET → 404, POST → 404, and the proxy isn't called.
  - [ ] `/chats/` shows only the user's own chats, most recently updated first. The nav
        contains Chats and New chat links.
  - [ ] A reply with `finish_reason: "length"` is charged and shows the cut-off note.
  - [ ] An XSS check: a reply containing `<script>` is rendered escaped.
- [ ] Commit.

## Step 6: `chore: document chat setup in README`

- [ ] README:
  - [ ] `OPENAI_API_KEY` is required from loop 2. Anthropic and Google keys are unused
        until a later loop.
  - [ ] Using the app: Chats → New chat → pick a model → send. Each reply shows its token
        usage and cost. Sending is blocked at $0.00, so ask an admin to top up.
  - [ ] Tests never call the proxy (the test runner blocks real HTTP).
  - [ ] Update the "Status" note to loop 2.
- [ ] Commit.

## Step 7: Verify the whole loop (no commit)

- [ ] `python manage.py check` and `makemigrations --check --dry-run` are both clean.
- [ ] `python manage.py test` all pass, with zero real HTTP requests (the guard would
      fail the run).
- [ ] `python manage.py migrate` on the dev DB (additive only, never reset or reseeded).
- [ ] Live server on `0.0.0.0:8000`: GET `/`, `/models/`, `/chats/` (302 when
      anonymous) and the log-in page → expected codes.
- [ ] **One real end-to-end check**, only if `OPENAI_API_KEY` is set (check with
      `grep -c` without printing the value). Run it on a throwaway test database, as in
      loop 1's walk-through, following nav links: sign up → New chat → pick GPT-5.6 Luna
      → send "Say hello in one sentence." → reply shown → send a follow-up → Available
      credit dropped by the sum of both charges → `/credit/` lists them. This is the
      only real proxy call, and it runs outside the test suite. If the key isn't set,
      report the check as skipped.
- [ ] `git status` is clean. `git log main..loop2-openai-chat --oneline` shows six
      commits. Stop and wait for **rendezvous**.

## Done when

- A logged-in user can go Chats → New chat, pick GPT-5.6 Luna, send messages, and see
  whole replies. Every page is reached through links.
- Each reply is charged its actual cost from the reported usage (rounded up to the
  micro-dollar), linked in the ledger, and shown under the reply. Proxy errors charge
  and save nothing.
- A balance of $0 or less gets 402 without calling the proxy. Replies are capped at
  1,024 output tokens.
- The full history is stored and resent on every turn.
- Admin shows every ledger amount in dollars.
- Tests mock the proxy, and the test runner makes real HTTP impossible.
