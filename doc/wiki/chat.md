# Chat and the LLM proxy

The chat pages look and behave like a chatbot:
- a sidebar of your chats with **+ New chat**
- message bubbles in one scrolling thread (yours on the right, the model's on the left)
- a message box pinned at the bottom, where **Enter sends**
- no page reload, with a "thinking" indicator while the reply loads

Replies are **whole**, not streamed (redesign study §5 and §10 #6). Every turn resends
the full stored history. Each reply is charged its actual cost, but **no costs or token
counts appear on the chat pages**; they're on [My Profile](billing.md#my-profile). Only
providers listed in `CHAT_PROVIDERS` (currently `openai`) can be chatted with.

Design sources: `doc/study/1790662970-chatbot-ui-redesign.md` and the loop 3 plan.

## Models (`chat/models.py`)

**`Conversation`**

- `owner` (FK to User)
- `title` (default "New chat", set from the first message, renamable)
- `llm_model` (FK to `catalog.LLMModel`, **PROTECT**, so a model with chats can't be
  deleted; deactivate it instead)
- `created_at`, `updated_at`

`Meta.ordering = ["-updated_at", "-id"]`. Aggregated querysets ignore this, so every
list query also calls `.order_by("-updated_at", "-id")` explicitly.

**`Message`**

- `conversation`
- `role` (`user` / `assistant`)
- `content`
- `created_at`

Assistant replies also store:
- `input_tokens`, `output_tokens`
- `cost_micros`
- `stop_reason` (`stop`, or `length` when cut off at 1,024 tokens)
- `usage_estimated`
- a **price snapshot** (`input_price_micros_per_mtok`, `output_price_micros_per_mtok`),
  so later catalog edits don't rewrite history

`was_cut_off` is true when `stop_reason == "length"`. Messages are ordered
`created_at, id`.

## The send flow

`chat.services.send_message(user, llm_model, text, conversation=None)`:

1. Build `messages` from `history_for(conversation)` (every stored message, in order,
   as `{"role", "content"}`) plus the new user message.
2. Call `llm.complete(llm_model, messages)` **outside any transaction**. It can take up
   to 120 seconds, and holding a SQLite write lock that long would block everyone. If it
   raises `LLMError`, the error propagates and **nothing is saved or charged**.
3. Compute the cost with `billing.services.reply_cost_micros()`. See
   [billing](billing.md#charging-a-reply).
4. In one `transaction.atomic()` block:
   - create the conversation if it's new, titled with `title_from(text)` (the first
     line, whitespace collapsed, at most 50 characters with `…`)
   - save the user message and the assistant message
   - post a `charge` ledger entry of `-cost`, linked to the assistant message
   - bump `updated_at`
5. Return the conversation, with `conversation.new_messages = [user_message,
   assistant]` attached. The JSON response renders exactly these two, even if another
   tab sends at the same moment.

`send_message` doesn't check the balance. The views do that before calling it, so the
charge always applies, even if it takes the balance slightly negative.

## Pages and templates

Every page is reachable from the nav (**Chats**), the home page's "Start a chat", or
`/models/` "Start a chat". Inside the chat pages, the sidebar has **+ New chat** and
every chat.

| URL | Behavior |
|---|---|
| `/chats/` (`chat_list`) | **302** to the most recently updated chat, or to `/chats/new/` if you have none. The sidebar replaces the old list page. |
| `/chats/new/` (`chat_new`) | An empty thread ("Start a conversation…") with the **model picker in the message box**. The first send creates the chat. |
| `/chats/<id>/` (`chat_detail`) | The thread, with a fixed **model label** (a chip) in the message box instead of a picker (redesign §10 #2). Only the owner can open it; anyone else gets 404. |
| `/chats/<id>/rename/` (`chat_rename`) | POST only (GET → 405). See [Renaming](#renaming). |

Templates (`templates/chat/`), all rendered on the server:

| Template | What it is |
|---|---|
| `layout.html` | Extends `base.html` with `body.app-page` / `main.chat-app`: a full-height grid of `aside.sidebar` + `section.chat-main`. It includes `_script.html` once. |
| `_sidebar.html` | + New chat, and the user's chats newest first (titles only). The current chat has `aria-current="page"`. The wrapper has `data-sidebar-list`, which the script replaces. |
| `_main.html` | The unit the script swaps in after a new chat's first reply. It holds the mobile "Chats" `<details>` (with a second copy of the sidebar), the header (title and rename), the thread and the composer. |
| `_message.html` | One bubble: `.bubble.user` or `.bubble.assistant` (with a model-name label). Content is autoescaped, with `linebreaksbr`. A cut-off reply adds "Reply was cut short." |
| `_composer.html` | The out-of-credit notice, then `form.composer`, which has a `role="alert"` error area, the picker or model chip, the textarea, Send, and the "Enter to send · Shift+Enter for a new line" hint (shown only when the script is active). |
| `_out_of_credit.html` | "You're out of credit. Contact an administrator to top up", linking to My Profile. When it shows, the textarea and Send are rendered `disabled`. |
| `_script.html` | The inline enhancement script. See [The script](#the-script-progressive-enhancement). |

Layout details (CSS inline in `base.html`):
- **The thread opens at the newest message with no JS.** `.thread` is
  `flex-direction: column-reverse` around a normally ordered `.thread-inner`.
- **The composer stays put.** `.composer-wrap` is `position: sticky; bottom: 0` in the
  flex column, and only the thread scrolls.
- **`main.chat-app` needs `width: 100%; margin: 0`.** The base `main { margin: 0 auto }`
  would otherwise shrink it to its content inside the flex-column body. This was a loop
  3 bug.
- **Under 720px**, the sidebar is hidden and a `<details class="mobile-chats">` toggle
  shows the same list. There's no horizontal scroll at 375px.
- A chat whose model is inactive or no longer chat-enabled shows "This model is no
  longer available. Start a new chat." instead of the composer.

**No costs on chat pages:**
- The picker labels show name and tier only (`chat.forms.model_label`), with no prices.
- The only money on these pages is the nav's "My Profile · $X.XX" (redesign §10 #1).
- Tests check that the page body below the nav contains no `$`, "tokens" or "per 1M".

## Two response modes: form posts and fetch (JSON)

`chat_new` and `chat_detail` run **the same checks in the same order** for both modes.
Only the response differs. A request is treated as JSON only when its `Accept` header
**starts with** `application/json` (`wants_json`), which is what the script sends. Don't
use `request.accepts("application/json")`: a browser form post sends `*/*`, which
`accepts()` treats as matching JSON.

| Situation (in check order) | Form post | JSON (`fetch`) | Proxy called? |
|---|---|---|---|
| Logged out | 302 to log-in | **401** `{"error", "login_url"}` | no |
| Another user's chat, or unknown id | 404 | 404 `{"error": "Chat not found."}` | no |
| Invalid form (empty, over 8,000 characters, missing or unsupported model) | 400, page with errors | 400 `{"error", "field_errors"}` | no |
| Existing chat's model inactive or unsupported | 400 | 400 `{"error"}` | no |
| Balance ≤ $0 | **402**, page with notice | **402** `{"error", "out_of_credit": true, "balance"}` | no |
| Proxy 429 or 503, timeout, connection error, missing key | 503 | 503 `{"error"}` | yes (except for a missing key) |
| Proxy 400/401/403/other 5xx, malformed response | 502 | 502 `{"error"}` | yes |
| Success, new chat | 302 → `/chats/<id>/#latest` | **200** `{"chat_url", "main_html", "sidebar_html", "balance"}` | yes |
| Success, existing chat | 302 → `/chats/<id>/#latest` | **200** `{"messages_html", "sidebar_html", "balance"}` | yes |

- `chat_login_required` replaces `login_required` on these views. `fetch()` silently
  follows redirects, so a redirect to log-in would reach the script as a 200 HTML page.
- `balance` is the wallet **after** the charge, formatted exactly like the nav
  (`format_dollars`, rounded down), e.g. `"$1.99"` or `"-$0.01"`.
- The HTML fragments come from the same partial templates as the full pages, so there's
  one renderer and autoescaping applies everywhere.
- On any failure in form mode, the page re-renders with the **draft still in the
  textarea**, and on New chat the chosen model too.

## The script (progressive enhancement)

`templates/chat/_script.html` is an inline `<script data-chat-script>` (redesign §10 #5):
plain JavaScript, no framework, no dependencies. It's inline, not a static file, because
a README setup leaves `DEBUG` off and `runserver` then doesn't serve `/static/`. Without
the script, every form still works with a normal POST and page reload.

- **On load:** adds `html.js`, which reveals the Enter hint, and scrolls to the newest
  bubble.
- **Enter to send:** a `keydown` on the composer textarea. Enter with no modifier calls
  `form.requestSubmit()`. Shift+Enter inserts a new line. It ignores Enter while an input
  method editor is composing (`isComposing`, or `keyCode 229`), for example while typing
  Chinese or Japanese.
- **Submit** (delegated on `document`, so it survives the `main_html` swap):
  1. Builds `FormData(form)` before disabling (it includes the CSRF token and the model).
  2. Appends a pending user bubble (**`textContent`**, never HTML) and a `.thinking`
     bubble (static markup: three dots plus a visually hidden "Thinking…").
  3. Disables the composer, sets `aria-busy` on the thread, and posts with
     `Accept: application/json`.
- **On 200:**
  - Removes the pending bubbles.
  - New chat: replaces `.chat-main` with `main_html`, calls `history.pushState` to
    `chat_url`, and updates `document.title`.
  - Existing chat: appends `messages_html`.
  - Replaces every `[data-sidebar-list]`.
  - Writes `balance` into every `[data-nav-balance]`, so the nav's "My Profile · $X.XX"
    stays current after each reply (redesign §10 #1).
- **On error:**
  - Removes the pending bubbles, **restores the draft**, and puts the error in the
    `role="alert"` area.
  - 402 keeps the composer disabled, links to My Profile, and updates the nav balance.
  - 401 links to log-in.
  - Non-JSON or network failures show "Something went wrong. Please try again."
- **`popstate`** (back/forward after `pushState`) reloads the page.
- Model output reaches the page only as HTML rendered and escaped by the server. The
  script never builds HTML from it.

## Renaming

`POST /chats/<id>/rename/`, handled by `RenameForm` (title: stripped, 1–100
characters). It's a plain form in the chat header, `<details class="rename">`, and works
without the script:
- success → 302 back to the chat
- invalid → **400**, re-rendering the chat with the rename form open and the error
- someone else's chat → 404
- GET → 405
- logged out → 302 to log-in

It saves with `QuerySet.update()`, so `updated_at` is unchanged and **renaming doesn't
reorder the sidebar**.

## The `llm` package (proxy client)

`llm/` is a plain Python package, not a Django app. It's the only code that talks to the
proxy, and it runs only on the backend.

- `LLMReply(text, input_tokens, output_tokens, stop_reason, usage_estimated=False)`.
- `LLMError(status, message)`:
  - `status` is what our view returns (502 or 503).
  - `message` is safe to show users. It never contains the API key or the proxy's
    response body.
- `complete(llm_model, messages)` dispatches on `llm_model.provider`. Only `openai` is
  implemented. Any other provider raises `LLMError(503, "This model isn't available
  yet.")`.

**`llm/openai.py`** sends `POST {LLM_PROXY_BASE_URL}/openai/v1/chat/completions`, with
`Authorization: Bearer <OPENAI_API_KEY>` and a body of
`{"model", "messages", "max_tokens": 1024, "reasoning_effort": "none"}`, and a
`timeout` of `LLM_TIMEOUT_SECONDS` (120). It reads:
- `choices[0].message.content`
- `choices[0].finish_reason`
- `usage.prompt_tokens` / `usage.completion_tokens`

If usage is missing, it estimates `ceil(chars / 4)` for the input and output, sets
`usage_estimated=True`, and logs a warning.

Error mapping:

| What happened | `LLMError.status` |
|---|---|
| `OPENAI_API_KEY` empty | 503 (no request sent) |
| `requests.Timeout` / `ConnectionError` | 503 |
| HTTP 429 or 503 | 503 |
| Any other non-2xx | 502 |
| Invalid JSON, no choices, or content that isn't a string | 502 |

Logs record the proxy status code and model id, never the headers, the key or the
response body.

**Proxy facts** (from https://proxy.litechat.ai/docs, and what we've observed):
- Each provider serves one model.
- All three providers are DeepSeek Flash underneath.
- The proxy is stateless, which is why we resend the full history.
- **Its reliability varies a lot.** In loop 3's checks, calls took anywhere from 1.5 s
  to a dropped connection after 85 s. Most real-proxy runs hit at least one 503. The
  app's handling (503, draft restored, nothing charged) was exercised for real each
  time.

## Admin

- **Conversations** (read-only): list columns are title, owner, model, message count,
  total cost ($) and updated. You can filter by model and search by title or owner. The
  detail page has a read-only message inline with role, content, tokens, cost ($) and
  stop reason. There's no add, change or delete.
- **Ledger:** `charge` rows have a "Chat" column that links to the conversation.
