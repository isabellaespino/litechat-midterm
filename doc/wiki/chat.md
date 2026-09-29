# Chat and the LLM proxy

Users start a chat with a model, send messages, and see **whole replies**: no streaming
and no JavaScript. Every turn resends the full stored history to the model. Each reply
is charged its actual cost. Only providers listed in `CHAT_PROVIDERS` (currently
`openai`) can be chatted with.

## Models (`chat/models.py`)

**`Conversation`**

- `owner` (FK to User)
- `title` (default "New chat", set from the first message)
- `llm_model` (FK to `catalog.LLMModel`, **PROTECT**, so a model with chats can't be
  deleted; deactivate it instead)
- `created_at`, `updated_at`

`Meta.ordering = ["-updated_at", "-id"]`. Aggregated querysets ignore this, so see the
note under [Pages](#pages).

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
2. Call `llm.complete(llm_model, messages)` **outside any transaction**. The request can
   take up to 120 seconds, and holding a SQLite write lock that long would block
   everyone. If it raises `LLMError`, the error propagates and **nothing is saved or
   charged**.
3. Compute the cost with `billing.services.reply_cost_micros()`. See
   [billing](billing.md#charging-a-reply).
4. In one `transaction.atomic()` block:
   - create the conversation if it's new, titled with `title_from(text)` (the first
     line, whitespace collapsed, at most 50 characters with `…`)
   - save the user message and the assistant message
   - post a `charge` ledger entry of `-cost`, linked to the assistant message, with the
     note "Reply in “title”"
   - bump `updated_at`

`send_message` doesn't check the balance. The views do that before calling it
(below), so the charge always applies, even if it takes the balance slightly negative.

## Pages

Every page is reachable from the nav (Chats, New chat), the home page's "Start a chat",
or `/models/` "Start a chat".

- **`/chats/`**: the user's chats with title, model, message count, total cost and last
  update, newest first. It has a New chat button, and an empty state linking to New
  chat. The query counts and sums messages, which makes Django **ignore
  `Meta.ordering`**, so the view calls `.order_by("-updated_at", "-id")` explicitly.
- **`/chats/new/`**: `NewChatForm` has two fields:
  - a model picker, grouped by provider in `<optgroup>`s. Each option shows the name,
    tier and "$in / $out per 1M tokens". It only offers active models whose provider is
    in `CHAT_PROVIDERS`.
  - the first message.

  A successful POST creates the chat and redirects to it.
- **`/chats/<id>/`**: the title, model and total cost of the chat, then each message.
  Each reply shows "N in / M out tokens · $cost", plus "(cut off at 1,024 tokens)" or
  "(estimated usage)" where they apply. The send form is at the bottom. The last message
  has `id="latest"`, and successful sends redirect to `#latest`.
- Replies are rendered with autoescaping plus `linebreaksbr`. Model output is untrusted,
  and a test checks that `<script>` is escaped.
- If the balance is $0 or less, an "out of credit" notice with a link to `/credit/`
  shows as soon as the page loads (status 200), before the user tries to send.
- If the chat's model is inactive or no longer chat-enabled, the send form is replaced
  by a "Start a new chat" link.

## Status codes (chat views)

Checked in this order when a message is posted:

| Situation | Status | Proxy called? |
|---|---|---|
| Anonymous | 302 to log-in | no |
| Another user's chat, or an unknown id | 404 | no |
| Invalid form: empty, over 8,000 characters, or a missing or unsupported model | 400 | no |
| The existing chat's model is inactive or unsupported | 400 ("This model is no longer available. Start a new chat.") | no |
| Balance ≤ $0 | **402**, with the out-of-credit notice | no |
| Proxy 429 or 503, timeout, connection error, missing API key | 503 | yes (except for a missing key) |
| Proxy 400/401/403/other 5xx, or a malformed response | 502 | yes |
| Success | 302 to `/chats/<id>/#latest` | yes |

On any 4xx or 5xx, the page re-renders with the user's **draft still in the textarea**
(and the chosen model, on New chat), so they can resend.

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
`usage_estimated=True`, and logs a warning. The reply is still charged, because a free
reply is worse than an approximate one.

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

**Proxy facts** (from https://proxy.litechat.ai/docs):
- Each provider serves one model.
- All three providers are DeepSeek Flash underneath.
- The proxy is stateless, which is why we resend the full history.

## Admin

- **Conversations** (read-only): list columns are title, owner, model, message count,
  total cost ($) and updated. You can filter by model and search by title or owner. The
  detail page has a read-only message inline with role, content, tokens, cost ($) and
  stop reason. There's no add, change or delete.
- **Ledger:** `charge` rows have a "Chat" column that links to the conversation.
