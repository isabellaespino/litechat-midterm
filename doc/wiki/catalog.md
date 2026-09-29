# Model catalog

The models users can choose from. It's a database table editable in Django admin, so
models and prices can change without a code change.

## `LLMModel` (`catalog/models.py`)

| Field | Notes |
|---|---|
| `provider` | `openai` / `anthropic` / `google`, displayed as OpenAI / Anthropic / Google |
| `api_model_id` | Unique. The id sent to the LLM proxy as `model`. |
| `display_name`, `description` | Shown on `/models/` |
| `tier` | `value` / `standard` / `premium` |
| `input_price_micros_per_mtok`, `output_price_micros_per_mtok` | µ$ per 1M tokens. $1.00/1M = 1 µ$ per token. |
| `is_active` | Inactive models are hidden from `/models/` and the chat picker, but kept for history. Existing chats on an inactive model can be read but not sent to. |
| `sort_order` | Order within a provider |
| `created_at`, `updated_at` | |

Ordering: `provider`, `sort_order`, `display_name`. `str()` is "Provider · Display name".

Models are referenced by `chat.Conversation.llm_model` with `PROTECT`, so a model that
has chats can't be deleted. Deactivate it instead. Price edits affect only future
replies, because each reply stores the prices it was charged at.

## Which models can chat

A model can be picked in chat only if it's active **and** its provider is in
`settings.CHAT_PROVIDERS` (currently `["openai"]`). The rule lives in
`chat.forms.chat_models()`. Enabling Anthropic or Google needs an adapter in `llm/` plus
adding the provider to that setting.

The chat picker (on New chat, in the message box) shows **name and tier only**, e.g.
"GPT-5.6 Luna · Value". Prices appear on `/models/` and My Profile, never on the chat
pages.

## Admin

Prices are entered as **dollars per 1M tokens** (`LLMModelForm`). They're converted to
µ$ on save and shown in dollars when editing. The list shows prices in dollars, and can
be filtered by provider, tier and active, and searched by name or model id.

## `/models/` page

Public. It lists active models **grouped by provider** (`{% regroup %}`). Each model shows
its display name, tier badge, description, and "$in input / $out output per 1M tokens".
Chat-enabled models have a **Start a chat** link to `/chats/new/`. The others show a
**Coming soon** badge.

## Seed data: `python manage.py seed`

`catalog/management/commands/seed.py` adds the three models the proxy serves. They all
behave the same, because every one is DeepSeek Flash underneath (see the study, §4):

| Provider | `api_model_id` | Display name | Tier | Input / output per 1M |
|---|---|---|---|---|
| Anthropic | `claude-haiku-4-5-20251001` | Claude Haiku | value | $1.00 / $5.00 |
| OpenAI | `gpt-5.6-luna` | GPT-5.6 Luna | value | $0.50 / $2.00 |
| Google | `gemini-3.8-flash` | Gemini Flash | value | $0.30 / $2.50 |

It uses `get_or_create` on `api_model_id` and prints `created:` or `exists:` for each
model. Re-running it never duplicates, updates or deletes rows, so prices an admin has
edited survive. The command creates no users: new users get their $2.00 from the
sign-up credit.
