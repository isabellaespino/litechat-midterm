# Chat and the LLM proxy

The chat pages look and behave like a chatbot:
- a sidebar of your chats with **+ New chat**, each showing its last-activity date and a
  **×** to delete it
- message bubbles in one scrolling thread (yours on the right, the model's on the left)
- a message box pinned at the bottom, where **Enter sends**
- no page reload, with a "thinking" indicator while the reply loads

Replies are **whole**, not streamed (redesign study §5 and §10 #6). Every turn resends
the full stored history. Each reply is charged its actual cost, but **no costs or token
counts appear on the chat pages**; they're on [My Profile](billing.md#my-profile).

**All three seeded models can chat** (`CHAT_PROVIDERS = ["openai", "anthropic",
"google"]`): GPT-5.6 Luna, Claude Haiku and Gemini Flash. Each goes through its own
adapter (see [the `llm` package](#the-llm-package-proxy-clients)). Charging, the 402
block, the 120 s timeout and error handling are identical for all three, and tested for
each.

Model replies render as **sanitized Markdown** (see [Markdown in
replies](#markdown-in-replies)).

Design sources: `doc/study/1790662970-chatbot-ui-redesign.md`,
`doc/study/1790678621-loop5-markdown-delete-dates.md`, and the loop 3–5 plans.

## Models (`chat/models.py`)

**`Conversation`**

- `owner` (FK to User)
- `title` (default "New chat"). It starts as the first line of the first message, is
  replaced by an [automatic title](#automatic-titles) after the first reply, and is
  renamable.
- `title_source`, which records where the title came from:
  - `provisional`: the first line, waiting for an automatic title
  - `generating`: a title request has claimed it
  - `auto`: the automatic title was saved
  - `user`: set by a rename, **and the default for chats created before loop 7**, so
    those are never retitled
  - `failed`: the title call failed or returned nothing usable; no retry
- `llm_model` (FK to `catalog.LLMModel`, **PROTECT**, so a model with chats can't be
  deleted; deactivate it instead)
- `include_memories` (loop 8, default `True`): whether this chat sends the user's
  [Memories](billing.md#memories). See [The Include memories switch](#the-include-memories-switch).
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
- `stop_reason`, normalized across providers: `stop`, `length` (cut off at 1,024
  tokens), `safety` (blocked by Google's filter), or the provider's raw value
- `usage_estimated`
- a **price snapshot** (`input_price_micros_per_mtok`, `output_price_micros_per_mtok`),
  so later catalog edits don't rewrite history

`was_cut_off` is true when `stop_reason == "length"`, and `was_blocked` when it's
`"safety"`. Messages are ordered `created_at, id`.

## The send flow

`chat.services.send_message(user, llm_model, text, conversation=None)`:

1. Build `messages` from `history_for(conversation)` (every stored message, in order,
   as `{"role", "content"}`) plus the new user message.
2. Build the system text at send time with `accounts.services.system_text_for(user,
   include_memories=…)`: the Global System Prompt, then (if the chat's switch is on) the
   user's [Memories](billing.md#memories). It's `None` when nothing is left. The switch
   value for this send comes in as `send_message(…, include_memories=…)` and is saved on
   the chat in the same transaction as the messages and the charge. Call `llm.complete(llm_model, messages, system=…)` **outside any
   transaction**. It can take up
   to 120 seconds, and holding a SQLite write lock that long would block everyone. If it
   raises `LLMError`, the error propagates and **nothing is saved or charged**.
3. Compute the cost with `billing.services.reply_cost_micros()`. See
   [billing](billing.md#charging-a-reply).
4. In one `transaction.atomic()` block, `_save_exchange()`:
   - creates the conversation if it's new, titled with `title_from(text)` (the first
     line, whitespace collapsed, at most 50 characters with `…`)
   - saves the user message and the assistant message
   - posts a `charge` ledger entry of `-cost`, linked to the assistant message
   - bumps `updated_at`
5. Return the conversation, with `conversation.new_messages = [user_message,
   assistant]` attached. The JSON response renders exactly these two, even if another
   tab sends at the same moment.

**If the chat is deleted while its reply is in flight** (e.g. from another tab), the
provider has already been paid for the tokens:
- Inside the transaction, `_conversation_exists()` re-checks the chat first. If it's
  gone, only the **charge** is posted (with `message=None` and the note "Reply in deleted
  chat “title”"), and nothing else is saved.
- **Backstop:** if the chat vanishes between that check and the writes, the writes fail
  with `DatabaseError` and roll back. The charge is then posted in a fresh transaction.
- Either way `ConversationDeleted` is raised **after** the charge has committed. If it
  were raised inside the atomic block, the charge would be rolled back too.
- `chat_detail` turns it into **404**, with `{"error": "This chat was deleted."}` in
  JSON mode.
- Before loop 5 this case was a 500 with the charge lost. That was reproduced during the
  study, and both paths are now tested.

`send_message` doesn't check the balance. The views do that before calling it, so the
charge always applies, even if it takes the balance slightly negative.

## Pages and templates

Every page is reachable from the nav (**Chats**), the home page's "Start a chat", or
`/models/` "Start a chat". Inside the chat pages, the sidebar has **+ New chat** and
every chat.

| URL | Behavior |
|---|---|
| `/chats/` (`chat_list`) | **302** to the most recently updated chat, or to `/chats/new/` if you have none. The sidebar replaces the old list page. |
| `/chats/new/` (`chat_new`) | An empty thread ("Start a conversation…") with the **model picker in the message box**: all three models, grouped by provider (Anthropic, Google, OpenAI), with name and tier only. The first send creates the chat. |
| `/chats/<id>/` (`chat_detail`) | The thread, with a fixed **model label** (a chip) in the message box instead of a picker (redesign §10 #2). Only the owner can open it; anyone else gets 404. |
| `/chats/<id>/rename/` (`chat_rename`) | POST only (GET → 405). See [Renaming](#renaming). |
| `/chats/<id>/delete/` (`chat_delete`) | GET: the confirmation page. POST: delete. See [Deleting a chat](#deleting-a-chat). |
| `/chats/<id>/title/` (`chat_title`) | POST, JSON only, called by the script. See [Automatic titles](#automatic-titles). |

Templates (`templates/chat/`), all rendered on the server:

| Template | What it is |
|---|---|
| `layout.html` | Extends `base.html` with `body.app-page` / `main.chat-app`: a full-height grid of `aside.sidebar` + `section.chat-main`. It empties base's `messages` block, so flash messages render inside the chat column instead of as a grid cell. It includes `_script.html` once. |
| `_sidebar.html` | + New chat, and the user's chats newest first. Each `li.chat-row` has an `a.chat-link` (containing `span.chat-title` and `time.chat-date`; the current chat has `aria-current="page"`) and an `a.chat-delete` (×, with `aria-label="Delete “title”"`). The wrapper has `data-sidebar-list`, which the script replaces. |
| `_main.html` | The unit the script swaps in after a new chat's first reply. It holds the mobile "Chats" `<details>` (with a second copy of the sidebar), the header (title, Rename, Delete), any flash messages, the thread and the composer. |
| `_message.html` | One bubble: `.bubble.user` or `.bubble.assistant` (with a model-name label). **Assistant** content goes through the `markdown` filter into `div.bubble-text.md`. **User** content stays autoescaped with `linebreaksbr`, exactly as typed. A cut-off reply adds "Reply was cut short." A safety-blocked empty reply shows "The model declined to answer this (safety filter)." |
| `confirm_delete.html` | The delete confirmation page (extends `base.html`). |
| `_composer.html` | The out-of-credit notice, then `form.composer`, which has a `role="alert"` error area, the picker or model chip, the **Include memories switch** (only when the user has a memory), the textarea, Send, and the "Enter to send · Shift+Enter for a new line" hint (shown only when the script is active). |
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
- **The sidebar ×** appears on hover or keyboard focus from 721px up, and is always
  visible at phone widths.
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
| Proxy 429 or 503, timeout, connection error, missing key (for that provider) | 503 | 503 `{"error"}` | yes (except for a missing key) |
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

- **On load:** adds `html.js`, which reveals the Enter hint, localizes the sidebar dates
  (`localizeTimes()`), and scrolls to the newest bubble.
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
    `chat_url`, and updates `document.title` (to "<chat title> · Chat4All").
  - Existing chat: appends `messages_html`.
  - Replaces every `[data-sidebar-list]`, then re-localizes the dates. Dates are also
    re-localized right after a `main_html` swap, because it holds the mobile sidebar
    copy.
  - Writes `balance` into every `[data-nav-balance]`, so the nav's "My Profile · $X.XX"
    stays current after each reply (redesign §10 #1).
- **On error:**
  - Removes the pending bubbles, **restores the draft**, and puts the error in the
    `role="alert"` area.
  - 402 keeps the composer disabled, links to My Profile, and updates the nav balance.
  - 401 links to log-in.
  - Non-JSON or network failures show "Something went wrong. Please try again."
- **Automatic title:** `requestTitle(chat_url)` runs after a new chat's first reply (the
  `main_html` branch), and **on load** when the header has
  `data-title-source="provisional"`. It sends a background POST with `X-CSRFToken`. On
  `changed: true`, while still on that chat, it updates the header, the rename box,
  `document.title` and the sidebars. **Every other status is ignored silently, and it
  never touches the nav balance.**
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
reorder the sidebar** or change its date.

## The Include memories switch

Loop 8 (plan `doc/plan/1790689108-loop8-include-memories-switch.md`, with no study
because the decisions were made directly). Users choose **per chat** whether their
memories are sent.

- **Where:** in the composer row, **next to the message box**: after the model picker or
  chip, before the textarea.
- **When it's shown:** **only when the user has at least one memory**
  (`chat_context` adds `user_memory_count`).
- **Default:** **on for new chats.** Chats created before loop 8 were migrated to on, so
  they behave as in loop 7.
- **A normal form control** that works without JavaScript:
  - `<input type="checkbox" name="include_memories" value="1" id="id_include_memories"
    role="switch">` inside a `<label class="memory-switch">`, all **inside
    `form.composer`**.
  - The script already builds `new FormData(form)` before disabling the composer, so the
    fetch path sends it too. **The script needed no changes**, and a test pins that
    ordering.
- **Telling "off" from "not shown":** browsers don't submit an unchecked checkbox. A hidden
  `memories_switch=1` marker is rendered **only when the switch is shown**, and
  `MessageForm.include_memories_for(conversation)` resolves it:
  - marker present → the checkbox's value
  - marker absent → the chat's saved value (or `True` for a new chat), so a send from a
    page without the switch never changes the setting
- **Applies from the next message, and is saved with it:** the value applies to the
  message sent with it and every later one.
  - It's saved on the chat **when that send succeeds**, in the same transaction.
  - A failed send (400, 402, 502 or 503) saves nothing. The re-rendered composer shows
    the **posted** switch state (`switch_checked`) along with the draft, so a resend
    carries it.
  - **Flipping the switch without sending isn't saved:** a reload shows the saved
    setting, which is always exactly what the next send will use.
- **Off:** the Global System Prompt is still sent, without the memory block. Off with no
  prompt sends **no system field at all**, for every provider.
- **Titles:** automatic titles send `system=None` whatever the switch says, so they never
  carry memories or the prompt.
- **Charging** is unchanged: every reply is charged from its reported usage (fewer input
  tokens when memories are off).
- **Styling:** see [Visual design](design.md#include-memories-switch).

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

## Automatic titles

Loop 7, study `doc/study/1790686669-loop7-auto-titles-memories.md` §2 and decisions §4.
After a new chat's first reply, the chat is renamed with a short title written by **the
chat's own model**.

- **Timing:** the first send is **unchanged**. It saves the provisional first-line title
  (`title_from`) with `title_source="provisional"` and returns as fast as before. The
  title comes from a **separate request** that the script fires right after. So the
  first reply never waits for it, and a slow or failed title can't hurt the reply.
- **Without JavaScript**, the first-line title stays. If the chat is later opened with
  JavaScript, it gets one attempt then.
- **The call** (`chat/titles.py`, `generate_title`):
  1. **Claim:** `filter(title_source="provisional").update(title_source="generating")`.
     If no row changed, it returns "conflict" with **no proxy call**, so only one request
     ever titles a chat.
  2. `llm.complete(model, [one user message], system=None, max_output_tokens=20,
     timeout=20)`, **outside any transaction**. The message is a fixed instruction
     ("Write a short title (3 to 6 words)… Use the conversation's language.") plus the
     first message and first reply, each truncated to 1,000 characters. **No Global
     System Prompt and no memories** are sent.
  3. `clean_title()` keeps the first line, strips quotes, Markdown marks and a
     "Title:" prefix, collapses spaces, drops a trailing `.:;`, and caps at 60
     characters with `…`. It returns `""` for nothing usable ("", ".", "Title",
     "untitled", …).
  4. In one transaction:
     - if the chat was deleted → `chat_deleted`
     - otherwise it saves with `filter(title_source="generating").update(title=…,
       title_source="auto")`
     - an unusable answer → `failed`, keeping the first-line title
     - 0 rows updated means a **rename won** → `superseded`

     `update()` means the title never bumps `updated_at`, so the sidebar doesn't
     reorder.
- **Free and invisible to users** (decision #1):
  - The app pays. **Nothing touches the user's wallet or ledger.** The response has no
    `balance`, and the title's cost appears nowhere users look: not My Profile, the
    credit history, the chat page or the nav.
  - "Spent" stays replies-only, and every reconciliation still holds.
  - It's attempted **regardless of balance**, even at $0 or below.
- **Admin-only cost log:** `chat.TitleGeneration`, one row per attempt. It records the
  chat (`SET_NULL`), user, model, status (`ok`, `unusable`, `superseded`,
  `chat_deleted`, `failed`), the title, tokens, a price snapshot, `cost_micros` (from
  `reply_cost_micros`, the same formula as charges) and `error_status`. A claim conflict
  makes no call and writes no row.
- **Admin:** "Title generations (app cost)" is read-only, with the total cost of the
  rows shown in the heading, and filters by status and model.
- **Endpoint** `POST /chats/<id>/title/` (`chat_login_required`, `require_POST`, **not**
  balance-gated):

  | Result | Status |
  |---|---|
  | title saved | 200 `{"changed": true, "title", "sidebar_html"}` |
  | unusable answer | 200 `{"changed": false, "title": <first-line title>}` |
  | not provisional (renamed, already titled, generating, or failed before) | 409 |
  | proxy failure | 502 / 503 (the `LLMError` status) |
  | chat deleted during the call, another user's chat, or unknown | 404 |
  | logged out (JSON) | 401 |
  | GET | 405 |

  A POST without a CSRF token (e.g. from `curl`) gets Django's 403 before the view.
- **Measured in loop 7's real check:** titles took 1.4–5.2 s after the first reply.
  They cost the app 161–517 µ$ each for about 500 input tokens (the replies were long),
  within the study's worst case.

## Deleting a chat

Loop 5, study §3 and §5.
- **Where:** the **×** on a sidebar row, or **Delete** in the chat header. Both link to
  `/chats/<id>/delete/` (`chat_delete`, using `chat_login_required` and
  `require_http_methods(["GET", "POST"])`).
- **GET** → 200, `confirm_delete.html`: "Delete “title”?", then "This deletes the chat and
  its messages. It can't be undone. Charges for its replies stay in your usage history on
  My Profile. Deleting a chat doesn't refund them." It has a red **Delete chat** button
  (a POST form) and **Cancel**. A GET changes nothing.
- **POST** → `conversation.delete()` (its messages cascade). Then the flash message
  "Chat deleted." and **302** to `/chats/`, which opens the next most recent chat or New
  chat.
- Other methods → 405. Another user's chat, or an unknown id → 404. Logged out → 302 to
  log-in.
- **Charges are kept, not refunded:**
  - Each charge row's `message` link becomes NULL (`on_delete=SET_NULL`). Its amount,
    date and note ("Reply in “title”") are untouched.
  - **No ledger row is added or edited**, so the balance doesn't change and
    `balance == sum(ledger)` still holds.
  - My Profile shows them as one **"Deleted chats"** line (see
    [billing](billing.md#my-profile)).
- It's a hard delete: the chat's text is really gone. There's no soft delete and no undo
  (study §5 #5).

## Sidebar dates

Each sidebar row shows the chat's **last activity** (`updated_at`, the same field the
sidebar is sorted by) under its title.
- **Server (the no-JS fallback):** `<time class="chat-date" datetime="<ISO 8601>"
  data-relative title="Sep 29, 2026 14:05 UTC">Sep 29, 2026</time>`, in UTC.
- **Script:** `localizeTimes()` rewrites each `time[data-relative]` in the **browser's
  time zone**, using `relativeLabel(date, now)` and comparing *local* calendar days:

  | Age | Label |
  |---|---|
  | same day (or future, from clock skew) | `14:05` (24-hour) |
  | previous day | `Yesterday` |
  | 2–6 days | `Mon` |
  | same year | `Sep 3` |
  | older | `Sep 3, 2025` |

  The tooltip becomes the full local date and time. It uses built-in
  `Intl.DateTimeFormat("en-US", …)`, with no dependency. Day differences use
  `Math.round`, so DST changes don't shift them.
- `relativeLabel` sits between `// relativeLabel:start` and `// relativeLabel:end`
  markers, so it can be extracted and tested under Node in different time zones (see
  [development](development.md#date-formatting-under-node)).
- A send bumps `updated_at`, so the chat moves to the top with a new date. Renaming
  doesn't.

## Markdown in replies

Assistant replies are rendered as Markdown **on the server, every time a bubble is
rendered**, through the `markdown` template filter (`chat/templatetags/chat_markdown.py`,
which calls `chat.markdown.render_markdown`).
- It's the same `_message.html` partial for full pages and the JSON `messages_html` /
  `main_html` fragments, so the script didn't change.
- `Message.content` stays the model's **raw** Markdown, which is what's resent in the
  history. Rendered HTML never goes back to a model.
- User messages are **not** rendered.

Two independent layers (loop 5 study §2):

1. **markdown-it-py:** `MarkdownIt("commonmark", {"html": False}).enable(["table",
   "strikethrough"]).disable("image")`.
   - Raw HTML is escaped.
   - `javascript:`, `vbscript:`, `file:` and `data:` links are rejected.
   - An image becomes a plain link (`!` + `<a>`), so nothing loads without a click.
2. **nh3** (the Rust *ammonia* sanitizer), applied to the parser's output:
   - `ALLOWED_TAGS`: `p br strong em s del code pre blockquote ul ol li h1–h6 hr a table
     thead tbody tr th td`
   - `ALLOWED_ATTRIBUTES`: `a[href, title]`, `code[class]`
   - `_attribute_filter`: `code[class]` must match `^language-[A-Za-z0-9_+-]+$`, or it's
     dropped
   - `url_schemes`: `http`, `https`, `mailto`
   - `link_rel`: `noopener noreferrer nofollow`

- **Never allowed:**
  - `<img>`, because a model-chosen image URL is a silent data-exfiltration channel under
    prompt injection.
  - Any `style` attribute, because CSS `url(…)` is the same channel. Aligned tables
    therefore lose their alignment.
  - Any `on*` handler.
- `render_markdown` is the **only** place model output is passed to `mark_safe`, and
  only after `nh3.clean`.
- **Not supported** (out of scope): syntax highlighting, autolinking bare URLs, math, and
  images.
- **Styling:** the `.md` rules in `base.html` cover paragraphs, lists, inline code,
  `pre` blocks with horizontal scroll, tables that scroll horizontally on phones,
  headings scaled to bubble size, blockquotes and `hr`.
- **Tests:** `chat/tests.py` has `XSS_CORPUS` (14 payloads) and `unsafe_html()`, which
  **parses** the HTML and flags any tag outside the allowlist, any `on*`, `style`, `src`
  or `srcset` attribute, any non-`http(s)`/`mailto` `href`, and any bad `code` class.
  - `MarkdownRenderingTests` runs the corpus through the renderer.
  - `MarkdownInChatTests` runs it through the full page, the JSON `messages_html` and
    `main_html`, and a parse of the whole thread (allowing only our own `div`/`span`
    wrappers).
  - **Why parse:** substring checks give false positives on correctly escaped text, such
    as `&lt;img onerror…` or a plain-text `javascript:`.

## The `llm` package (proxy clients)

`llm/` is a plain Python package, not a Django app. It's the only code that talks to the
proxy, and it runs only on the backend.

| Module | What it does |
|---|---|
| `llm/base.py` | `LLMReply(text, input_tokens, output_tokens, stop_reason, usage_estimated=False)`, and `LLMError(status, message)`. `status` is what our view returns (502 or 503). `message` is safe to show users: it never contains a key or the proxy's response body. Both are re-exported from `llm`. |
| `llm/http.py` | Shared by every adapter, so failures behave identically for all providers. `post_json()` handles the request, the timeout and the error mapping below, and returns the decoded JSON. `require_key()` raises 503 before any request when a key is empty. It also has `malformed()`, `estimated_usage()` (`ceil(chars / 4)`, logged as a warning), and the two user-facing messages. |
| `llm/openai.py`, `llm/anthropic.py`, `llm/google.py` | One adapter per provider: `complete(api_model_id, messages, system=None) -> LLMReply`. Each builds its provider's URL, headers and body, then parses the reply. |
| `llm/__init__.py` | `complete(llm_model, messages, system=None)` dispatches through `PROVIDERS = {"openai": …, "anthropic": …, "google": …}`. An unknown provider raises `LLMError(503, "This model isn't available yet.")`. |

`messages` is always our neutral history, a list of `{"role": "user" | "assistant",
"content"}` dicts. Each adapter translates it to its provider's format. `system` is the
user's [Global System Prompt](billing.md#global-system-prompt), or `None`.

**Per-call limits:** `llm.complete(…, max_output_tokens=None, timeout=None)` passes both
down to every adapter. `max_output_tokens` sets each provider's cap field, and `timeout`
goes to `http.post_json`. The defaults are the reply settings (1,024 tokens, 120 s).
Automatic titles pass `TITLE_MAX_OUTPUT_TOKENS = 20` and `TITLE_TIMEOUT_SECONDS = 20`.

### Provider contracts

| | OpenAI | Anthropic | Google |
|---|---|---|---|
| Endpoint | `POST /openai/v1/chat/completions` | `POST /anthropic/v1/messages` | `POST /google/v1beta/models/{api_model_id}:generateContent` (the id is URL-quoted) |
| Auth | `Authorization: Bearer <OPENAI_API_KEY>` | `x-api-key: <ANTHROPIC_API_KEY>` + `anthropic-version: 2023-06-01` | `x-goog-api-key: <GOOGLE_API_KEY>` |
| History | `messages` as is | `messages`. **Consecutive same-role messages are merged** (joined with a blank line), because Anthropic rejects them. Our history always alternates, so this is only a safety net. | `contents: [{role: "user" \| "model", parts: [{text}]}]`. Our `assistant` becomes `model`. |
| System prompt (only when set) | first message `{"role": "system", "content": s}` | top-level `"system": s` | `"systemInstruction": {"parts": [{"text": s}]}`. The proxy docs don't show this shape; a real call confirmed it in loop 4. |
| Output cap | `max_tokens: 1024` | `max_tokens: 1024` | `generationConfig.maxOutputTokens: 1024` |
| Reasoning off | `reasoning_effort: "none"` | `thinking: {"type": "disabled"}` | `generationConfig.thinkingConfig.thinkingBudget: 0` |
| Reply text | `choices[0].message.content` | the joined `text` of every `content[]` block with `type == "text"` (thinking and tool blocks are ignored) | the joined `candidates[0].content.parts[].text` |
| Input tokens | `usage.prompt_tokens` | `usage.input_tokens` + any `cache_creation_input_tokens` / `cache_read_input_tokens` (we never enable caching; this guards against undercharging) | `usageMetadata.promptTokenCount` |
| Output tokens | `usage.completion_tokens` | `usage.output_tokens` | `candidatesTokenCount` (0 if absent) + `thoughtsTokenCount` (0 if absent; billed as output) |
| Stop → our `stop_reason` | `stop`, `length` | `end_turn`→`stop`, `max_tokens`→`length`, else raw | `STOP`→`stop`, `MAX_TOKENS`→`length`, `SAFETY`→`safety`, else lowercase |

- **Normalized stop reasons:** `Message.was_cut_off` is `stop_reason == "length"`, and
  `Message.was_blocked` is `stop_reason == "safety"`.
- **Missing usage** on any provider: tokens are estimated, `usage_estimated=True`, and
  the reply is still charged.
- **Google safety blocks:** `SAFETY` with no content is a **valid reply, not an error**.
  It's stored with empty text and `stop_reason="safety"`, charged its reported usage,
  and shown as "The model declined to answer this (safety filter)." My Profile marks it
  "(blocked)". A missing `candidates`, or missing content without `SAFETY`, is malformed
  → 502.

### Error mapping (identical for every provider, in `llm/http.py`)

| What happened | `LLMError.status` |
|---|---|
| The provider's key is empty | 503, with no request sent. It affects only that provider's model. |
| `requests.Timeout` (after `LLM_TIMEOUT_SECONDS` = 120) or `ConnectionError` | 503 |
| HTTP 429 or 503 | 503 |
| Any other non-2xx | 502 |
| Invalid JSON, or a body missing the reply fields | 502 |

Logs record the provider, the proxy status code and the model id. They never record
headers, keys or bodies.

### Proxy facts

From https://proxy.litechat.ai/docs, plus what we've observed:
- Each provider serves one model.
- All three are DeepSeek Flash underneath, so replies look alike.
- The proxy is stateless, which is why we resend the full history.
- **Its reliability varies a lot.** Loop 3 saw calls from 1.5 s to a connection dropped
  after 85 s. In loop 4's run, all 12 real calls answered in 1.3–1.8 s. The app's
  failure handling (503, draft restored, nothing charged) has been exercised for real.

## Admin

- **Conversations** (read-only): list columns are title, owner, model, message count,
  total cost ($) and updated. You can filter by model and search by title or owner. The
  detail page has a read-only message inline with role, content, tokens, cost ($) and
  stop reason. There's no add, change or delete.
- **Ledger:** `charge` rows have a "Chat" column that links to the conversation.
- **Title generations (app cost):** described in [Automatic titles](#automatic-titles).
