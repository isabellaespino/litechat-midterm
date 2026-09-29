# Plan: Loop 4: Anthropic and Google in chat, and a Global System Prompt

- **Date:** 2026-09-29 (Unix 1790676012)
- **Sources:**
  - proxy docs, https://proxy.litechat.ai/docs (Anthropic Messages, Google Gemini
    generateContent, OpenAI Chat Completions; re-read 2026-09-29)
  - first study §4 and §6.5 (plain-HTTP adapters, one per provider)
  - wiki `chat.md` (the send flow, the `llm` package)
- **Branch:** `loop4-all-providers`, off `main`. Don't merge during execute. Wait for the
  rendezvous command.
- **Scope:**
  - An Anthropic adapter and a Google adapter, each handling that provider's request
    format, system prompt, 1,024-token output cap and usage fields.
  - All three models in the New chat picker, and no more "Coming soon" on `/models/`.
  - A per-user **Global System Prompt** on My Profile, sent as the system prompt in every
    chat for all three providers. It's optional: with none set, requests carry no system
    prompt.
- **Must stay identical across providers:**
  - Charge the actual cost from the reported usage, rounded up to the micro-dollar.
  - Charge nothing on failure.
  - 402 at ≤ $0, before any proxy call.
  - The 120 s timeout, and the error mapping (503 for 429, 503, timeouts, connection
    errors and missing keys; 502 for other failures).
  - Both response modes (form and JSON), and the nav balance update.
- **Not in this loop:**
  - Per-message model switching (a chat keeps its model).
  - Per-chat system prompts. Snapshotting the system prompt onto messages.
  - Streaming. Prompt caching.
- **Keys:** `ANTHROPIC_API_KEY` and `GOOGLE_API_KEY` are already loaded in settings and
  listed in `.env.example`. Both are set in the local `.env` (checked with `grep -c`,
  values not printed).

## Provider contracts (from the proxy docs)

| | OpenAI (existing) | Anthropic | Google |
|---|---|---|---|
| Endpoint | `POST /openai/v1/chat/completions` | `POST /anthropic/v1/messages` | `POST /google/v1beta/models/{api_model_id}:generateContent` |
| Auth | `Authorization: Bearer <OPENAI_API_KEY>` | `x-api-key: <ANTHROPIC_API_KEY>` + `anthropic-version: 2023-06-01` | `x-goog-api-key: <GOOGLE_API_KEY>` |
| Messages | `messages: [{role: user\|assistant, content}]` | `messages: [{role: user\|assistant, content}]`. **No two consecutive messages with the same role.** | `contents: [{role: user\|model, parts: [{text}]}]`. Our `assistant` becomes `model`. |
| System prompt (only when set) | first message `{"role": "system", "content": s}` | top-level `"system": s` (a string) | top-level `"systemInstruction": {"parts": [{"text": s}]}`. The shape isn't shown in the proxy docs: this is the standard Gemini shape, and the real check in Step 7 confirms it. |
| Output cap | `max_tokens: 1024` | `max_tokens: 1024` (required) | `generationConfig.maxOutputTokens: 1024` |
| Reasoning off | `reasoning_effort: "none"` | `thinking: {"type": "disabled"}` | `generationConfig.thinkingConfig.thinkingBudget: 0` |
| Reply text | `choices[0].message.content` | join the `text` of every `content[]` block with `type == "text"`; ignore other block types | join `candidates[0].content.parts[].text` |
| Input tokens | `usage.prompt_tokens` | `usage.input_tokens` + `cache_creation_input_tokens` + `cache_read_input_tokens` (the cache fields default to 0; we never enable caching, so this only guards against undercharging) | `usageMetadata.promptTokenCount` |
| Output tokens | `usage.completion_tokens` | `usage.output_tokens` | `usageMetadata.candidatesTokenCount` (0 if absent) + `thoughtsTokenCount` (0 if absent; billed as output) |
| Stop → our `stop_reason` | `stop`→`stop`, `length`→`length` | `end_turn`→`stop`, `max_tokens`→`length`, else raw | `STOP`→`stop`, `MAX_TOKENS`→`length`, `SAFETY`→`safety`, else lowercased raw |

- **Normalized `stop_reason`:** `Message.was_cut_off` already checks `"length"`, and
  stored OpenAI rows already use `stop`/`length`. So there's no migration for existing
  data.
- **Missing usage:** if input or output usage is missing, estimate with
  `ceil(chars/4)`, set `usage_estimated=True` and log a warning, as the OpenAI adapter
  does. A reply is never free.
- **Google `SAFETY` with no text parts:** this is a valid reply, not an error. Store
  empty text and `stop_reason="safety"`, and charge the reported usage (first study
  §6.3). The bubble shows "The model declined to answer this (safety filter)." A missing
  `candidates` array, or a missing `content` without `SAFETY`, is malformed → 502.

---

## Step 0: Branch

- [ ] `git switch -c loop4-all-providers` from an up-to-date `main`.

## Step 1: `chore: extract shared proxy request handling`

There's no behavior change. Its purpose is to make the error handling identical for
every provider by construction.

- [ ] `llm/http.py`, `post_json(provider, api_model_id, url, headers, body) -> dict`.
      Move the loop 2 logic out of `llm/openai.py` unchanged:
  - `requests.post(url, json=body, headers=headers, timeout=settings.LLM_TIMEOUT_SECONDS)`
  - `Timeout` or `ConnectionError` → `LLMError(503)`
  - a 429 or 503 response → 503
  - any other non-2xx → 502
  - an invalid JSON body → 502
  - logs the status and model, never the headers, the key or the body
- [ ] `llm/http.py`, `require_key(value, name)`: an empty value → log "`<name>` is not
      set" and raise `LLMError(503)` before any request. Also move `estimate_tokens`
      and the user-facing `UNAVAILABLE` / `FAILED` messages here.
- [ ] `llm/openai.py` now only builds the URL, headers and body, and parses the reply.
      Its signature becomes `complete(api_model_id, messages, system=None)`. When
      `system` is set, prepend `{"role": "system", "content": system}`.
- [ ] `llm/__init__.py`:
  - `complete(llm_model, messages, system=None)` dispatches through a
    `PROVIDERS = {"openai": openai.complete}` dict.
  - An unknown provider still raises `LLMError(503, "This model isn't available yet.")`.
  - `send_message` keeps calling it without `system` for now.
- [ ] Tests:
  - [ ] Change the mock target from `llm.openai.requests.post` to
        `llm.http.requests.post` in `llm/tests.py` and `chat/tests.py`.
  - [ ] Move the error-mapping tests into a `ProxyErrorMappingTests` that loops over a
        `PROVIDER_CASES` table (OpenAI only for now; Steps 2 and 3 add rows).
  - [ ] Add OpenAI system-prompt tests: `system="Be brief."` → the first message is
        `{"role": "system", "content": "Be brief."}`. `system=None` → there's no
        system message.
  - [ ] Every existing test passes unchanged in meaning (100 tests plus the new ones).
- [ ] Commit.

## Step 2: `feat: add Anthropic proxy adapter`

- [ ] `llm/anthropic.py`, `complete(api_model_id, messages, system=None)`:
  - `require_key(settings.ANTHROPIC_API_KEY, "ANTHROPIC_API_KEY")`.
  - URL `{LLM_PROXY_BASE_URL}/anthropic/v1/messages`, headers `x-api-key`,
    `anthropic-version: 2023-06-01`, `Content-Type: application/json`.
  - The body is `{"model", "messages", "max_tokens": MAX_OUTPUT_TOKENS, "thinking":
    {"type": "disabled"}}`, plus `"system": system` **only if** `system` is set.
  - **Same-role guard:** merge consecutive messages with the same role (joined with a
    blank line) before sending. Our history always alternates, because failures save
    nothing, so this is defence in depth.
  - Parse:
    - text = the join of the `type == "text"` blocks. If there's no `content` list →
      502.
    - Usage as in the contract table.
    - Stop mapped to `stop`, `length` or the raw value.
- [ ] Register `"anthropic": anthropic.complete` in `PROVIDERS`.
- [ ] Tests (`llm/tests.py`, mocking `llm.http.requests.post`):
  - [ ] Request shape: the URL, `x-api-key` from settings, `anthropic-version`, a body
        with `max_tokens == 1024` and `thinking.type == "disabled"`, `timeout=120`, and
        **no `Authorization` header**.
  - [ ] `system` is present as a string when given, and **absent** when `None`.
  - [ ] Parsing:
    - two text blocks are joined, and a `thinking` block is ignored
    - `input_tokens`/`output_tokens` are mapped
    - cache fields are added to input when present
    - `end_turn` → `stop`, `max_tokens` → `length`
  - [ ] Missing usage → estimated. No `content` → 502.
  - [ ] Consecutive same-role messages are merged. Alternating history is passed through
        unchanged.
  - [ ] Add an Anthropic row to `PROVIDER_CASES`: identical 502/503 mapping, timeout,
        connection error, a malformed body, and a missing key → 503 with no request.
  - [ ] Dispatch: `complete(<anthropic LLMModel>, …)` calls the Anthropic adapter.
- [ ] Commit.

## Step 3: `feat: add Google Gemini proxy adapter`

- [ ] `llm/google.py`, `complete(api_model_id, messages, system=None)`:
  - `require_key(settings.GOOGLE_API_KEY, "GOOGLE_API_KEY")`.
  - URL `{LLM_PROXY_BASE_URL}/google/v1beta/models/{api_model_id}:generateContent`. The
    model id is URL-quoted with `urllib.parse.quote(api_model_id, safe="")`. Headers
    `x-goog-api-key` and `Content-Type`.
  - The body is:
    - `{"contents": [{"role": "user" | "model", "parts": [{"text": …}]}…]}`
    - `"generationConfig": {"maxOutputTokens": 1024, "thinkingConfig":
      {"thinkingBudget": 0}}`
    - plus `"systemInstruction": {"parts": [{"text": system}]}` **only if** `system`
      is set
  - Parse as in the contract table. `SAFETY` with no parts → a reply with empty text
    and `stop_reason="safety"`, charged its usage.
- [ ] Register `"google": google.complete` in `PROVIDERS`.
- [ ] Tests:
  - [ ] Request shape: the URL contains `/models/gemini-3.8-flash:generateContent`,
        `x-goog-api-key` from settings, and there's no `Authorization` header.
        `maxOutputTokens == 1024`, `thinkingBudget == 0`, `timeout=120`.
  - [ ] Roles: our `assistant` history is sent as `model`, in order, and text goes into
        `parts`.
  - [ ] `systemInstruction` is present with the right shape when given, and **absent**
        when `None`.
  - [ ] Parsing:
    - multiple parts are joined
    - `promptTokenCount` → input
    - `candidatesTokenCount + thoughtsTokenCount` → output
    - an absent `candidatesTokenCount` → 0
    - `STOP` → `stop`, `MAX_TOKENS` → `length`
    - `SAFETY` with no parts → empty text, `safety`, usage kept
  - [ ] Missing `usageMetadata` → estimated. No `candidates` → 502.
  - [ ] Add a Google row to `PROVIDER_CASES`: identical error mapping and missing key.
- [ ] Commit.

## Step 4: `feat: enable Anthropic and Google models in chat`

- [ ] `CHAT_PROVIDERS = ["openai", "anthropic", "google"]`.
- [ ] The New chat picker lists all three active seeded models, grouped by provider
      (Anthropic, Google, OpenAI), with name and tier only.
- [ ] `/models/`: every seeded model shows **Start a chat**, and nothing shows "Coming
      soon". The template's conditional stays for any future provider without an
      adapter. The test asserts no "Coming soon" with the seeded catalog.
- [ ] `_message.html`: for `stop_reason == "safety"`, show "The model declined to answer
      this (safety filter)." in place of the empty text. `Message.was_blocked` is a
      property. My Profile shows "(blocked)" on that reply row.
- [ ] Tests (`chat/tests.py`, with a helper that builds a **provider-shaped** mocked
      response for each model):
  - [ ] For **each** of GPT-5.6 Luna, Claude Haiku and Gemini Flash, in both form and
        JSON mode:
    - start a chat → 302 or 200
    - the charge equals `reply_cost_micros` with **that model's prices**, e.g. Claude
      at 1,000 in + 300 out = 1,000 + 1,500 = 2,500 µ$, and Gemini at 1,000 in + 300 out
      = 300 + 750 = 1,050 µ$
    - the ledger links the reply
    - the JSON `balance` is the balance after the charge
  - [ ] For each provider, the second send resends the history in that provider's
        format (Google roles `user`/`model`).
  - [ ] For each provider, a balance ≤ 0 gives 402 and the proxy **is not called**. A
        proxy 500 gives 502, a 429 gives 503 and a timeout gives 503, each with nothing
        saved or charged and the draft preserved.
  - [ ] A missing `ANTHROPIC_API_KEY` or `GOOGLE_API_KEY` (`override_settings`) gives
        503 for that provider only. The other providers still work.
  - [ ] A Google SAFETY reply is charged, and it shows the declined note, no cost on the
        chat page, and "(blocked)" on My Profile.
  - [ ] The picker contains all three models. `/models/` has no "Coming soon".
- [ ] Commit.

## Step 5: `feat: add a Global System Prompt on My Profile`

- [ ] Model `accounts.UserSettings`:
  - `user` (a one-to-one field that is the primary key)
  - `system_prompt` (a `TextField`, blank allowed, stripped by the form, at most
    **4,000 characters**)
  - `updated_at`

  The `accounts` app gets `models.py` and its first migration. Read it through a
  `get_settings(user)` helper (`get_or_create`), so existing users need no data
  migration.
- [ ] `SystemPromptForm` (`system_prompt`, not required, `max_length=4000`,
      `strip=True`).
- [ ] `POST /profile/system-prompt/` (`system_prompt`, in `accounts/views.py`,
      `login_required` and `require_POST`):
  - valid → save and 302 to `/profile/#system-prompt`, with a message: "System prompt
    saved." or "System prompt cleared."
  - invalid (over 4,000 characters) → **400**, re-rendering My Profile with the error
    and the draft
  - GET → 405
  - logged out → 302 to log-in
- [ ] My Profile (`billing/profile.html`) gets a **Global System Prompt** section
      (`id="system-prompt"`) near the top. It has a textarea prefilled with the current
      prompt, Save, and help text: "Sent as the system prompt in every chat, with every
      model. Leave empty for none. It counts toward each reply's input tokens." The
      profile view adds `system_prompt_form` to its context. The rendering is extracted
      into a `render_profile(request, **extra, status=200)` helper so the 400 path can
      reuse it.
- [ ] Wire it in: `send_message` reads `get_settings(user).system_prompt` at send time,
      and passes `system=prompt or None` to `llm.complete`. A blank or whitespace-only
      prompt → `None`, so there's no system field at all. The prompt isn't stored on
      messages; it isn't part of the chat history and isn't shown in the thread.
- [ ] Admin: a read-only "System prompt" inline on the user admin (for support).
- [ ] Tests:
  - [ ] The profile page shows the section and textarea. Saving → 302, and the prompt is
        stored stripped. Saving an empty value clears it. Over 4,000 characters → 400 and
        nothing is stored. GET → 405. Anonymous → 302 to log-in.
  - [ ] **For each provider**, with a prompt set, the request carries it in that
        provider's format:
    - OpenAI: a `system` message first
    - Anthropic: top-level `system`
    - Google: `systemInstruction.parts[0].text`
  - [ ] **For each provider**, with no prompt (or only whitespace), the request has
        **no** system message or field.
  - [ ] Isolation: Bob's prompt is never sent in Alice's chats.
  - [ ] Charging is unchanged: the charge still comes from the reported usage, which
        includes the system prompt's input tokens.
  - [ ] Other existing behavior is unchanged: 402 still blocks before the proxy is
        called, whatever the prompt.
- [ ] Commit.

## Step 6: `chore: update README for all providers and the system prompt`

- [ ] The key table: all three keys are now required to chat with their model. A missing
      key makes only that provider's model return 503 ("unavailable").
- [ ] Using the app: all three models can chat, and My Profile has a Global System
      Prompt (what it does, that it's optional, and that it counts toward input tokens).
- [ ] Update the status note to loop 4.
- [ ] Commit.

## Step 7: Verify the whole loop (no commit)

- [ ] `check` passes. `makemigrations --check` shows **only** the new `accounts`
      migration, committed in Step 5, so no further changes.
- [ ] `python manage.py test` all pass, with no real HTTP (the guard is active).
- [ ] `migrate` on the dev DB (adds `accounts_usersettings`, additive only). Never reset.
- [ ] Live server on `0.0.0.0:8000`: `/models/` → 200 with no "Coming soon". The chat
      pages and `/profile/` → 302 to log-in when anonymous.
- [ ] **Real end-to-end check, all three models** (keys checked without printing). Run on
      a throwaway test DB, in JSON mode, retrying once per call because the proxy is
      flaky:
  - [ ] For each model: a new chat, then a follow-up → 200 each. Check the reply text is
        non-empty, the charge equals the formula with that model's prices, and `balance`
        matches the wallet.
  - [ ] Set the Global System Prompt to "Always reply in French.", then send one message
        to each model. The proxy must accept each request: in particular, a 400 from
        Google means the `systemInstruction` shape is wrong, and that gets fixed before
        rendezvous. Report whether the replies followed the prompt. Everything is
        DeepSeek Flash underneath, so following it is likely but not guaranteed. What
        must hold is that the request is accepted and charged.
  - [ ] Clear the prompt, and confirm one more request per provider succeeds.
- [ ] **Browser check** (headless Chrome over DevTools, as in loop 3; `uitest` on the dev
      DB, already authorized):
  - [ ] The New chat picker shows the three models in three provider groups.
  - [ ] Start a chat with Claude Haiku and with Gemini Flash using Enter. The replies
        arrive without a reload, and the nav balance updates.
  - [ ] My Profile: save a system prompt → "System prompt saved." and it's prefilled on
        reload. Clearing it → "System prompt cleared."
  - [ ] Screenshots: the picker, a Gemini chat, and My Profile's system prompt section.
        Look at them.
- [ ] `git status` is clean. `git log main..loop4-all-providers --oneline` shows six
      commits. Stop and wait for **rendezvous**.

## Risks

- **The Google `systemInstruction` shape** is inferred from the standard Gemini API,
  because the proxy page names the field without showing it. It's mitigated by the real
  check in Step 7.
- **The proxy is unreliable** (loop 3 saw calls from 1.5 s to an 85 s dropped
  connection). Real checks retry once, and a failure is judged by whether the app
  handled it (503, draft kept, no charge).
- **Anthropic's same-role rule:** our saved history always alternates, and the merge
  guard covers any exception.
- **Cost of the system prompt:** it's resent on every turn and billed as input tokens.
  The 4,000-character cap bounds it, and the help text tells users.

## Done when

- GPT-5.6 Luna, Claude Haiku and Gemini Flash can all be picked in New chat and chat end
  to end, and `/models/` shows no "Coming soon".
- Each adapter uses its provider's request format, system-prompt field, 1,024-token cap
  and usage fields. Charges use each model's prices from the reported usage.
- 402, the 120 s timeout, the 502/503 mapping, charging nothing on failure, the JSON
  `balance` and the nav update behave identically for all three, and are tested for each.
- My Profile has an optional Global System Prompt, sent as the system prompt to every
  provider when set and omitted entirely when empty.
- Tests mock the proxy for every provider. Real calls happen only in the verify step, on
  a throwaway database.
