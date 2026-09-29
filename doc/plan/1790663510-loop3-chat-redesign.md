# Plan: Loop 3: chatbot-style chat UI, renaming, and My Profile

- **Date:** 2026-09-29 (Unix 1790663510)
- **Source study:** `doc/study/1790662970-chatbot-ui-redesign.md` (decisions in §10)
- **Builds on:** loop 2 (`doc/wiki/chat.md`, `doc/wiki/billing.md`)
- **Branch:** `loop3-chat-redesign`, off `main`. Don't merge during execute. Wait for the
  rendezvous command.
- **Scope:**
  - A sidebar with the user's chats and New chat, and bubbles in one scrolling thread.
  - A composer fixed at the bottom, with Enter to send.
  - A model picker in the composer on new chats, and a fixed model label on existing
    chats.
  - Sending without a reload, with a thinking indicator.
  - Renaming chats.
  - No costs or token counts on the chat pages. A **My Profile** page with the credit
    and usage history replaces `/credit/`, and the nav shows **"My Profile · $X.XX"**.
  - `/chats/` redirects to the latest chat.
- **Not in this loop:**
  - Streaming (decision #6).
  - Switching models per message, and markdown rendering.
  - Sidebar date grouping.
  - The Anthropic and Google adapters.
  - Automated browser tests, which would need a new dependency (study §9).
- **Unchanged:**
  - `chat.services.send_message()`, `billing.services`, and the ledger and its admin.
  - The proxy client, and the order of the view checks (404 → 400 → inactive model 400
    → 402 → 502/503 → success).
  - No new dependencies and no model changes, so **no migrations** are expected.

## Response contract (both modes, same view, same checks)

A request **wants JSON** only if its `Accept` header starts with `application/json`,
which is what the script sends. Don't use `request.accepts("application/json")`: a
normal browser form post sends `Accept: …, */*`, which `accepts()` treats as JSON too.

| Situation | Form post | JSON (`fetch`) |
|---|---|---|
| Send success, existing chat | 302 → `/chats/<id>/#latest` | **200** `{"messages_html", "sidebar_html"}` |
| Send success, new chat | 302 → `/chats/<id>/#latest` | **200** `{"chat_url", "main_html", "sidebar_html"}` |
| Invalid message form | 400 page | 400 `{"error", "field_errors"}` |
| Inactive or unsupported model | 400 page | 400 `{"error"}` |
| Balance ≤ $0 | **402** page | **402** `{"error", "out_of_credit": true}` |
| Proxy failure | 502 / 503 page | 502 / 503 `{"error"}` |
| Another user's chat, or an unknown chat | 404 | 404 `{"error"}` |
| Logged out | 302 to log-in | **401** `{"error", "login_url"}` |

- The HTML fragments are rendered by the **same partial templates** the full pages use.
- The script never builds HTML from model output. The user's own text in the pending
  bubble is inserted with `textContent`.
- Rename (`POST /chats/<id>/rename/`) is a **form-only** endpoint: 302 on success, 400
  when invalid, 404 when it's not the user's chat, 302 to log-in when logged out.

---

## Step 0: Branch

- [ ] `git switch -c loop3-chat-redesign` from an up-to-date `main`.

## Step 1: `feat: add My Profile page with usage history`

- [ ] `billing/views.py`, `profile(request)` (`login_required`), at `/profile/`
      (name `profile`). It renders `billing/profile.html` with:
  - [ ] **Account:** username, and member since (`date_joined`).
  - [ ] **Available credit:** shown large, with `dollars` (rounded down), plus "Contact
        an administrator to add credit."
  - [ ] **Totals:** total added (the sum of non-`charge` rows), total spent (the sum of
        `charge` rows, shown as a positive number), and the balance. Balance = added −
        spent, so the ledger invariant is visible to the user.
  - [ ] **Usage by chat:** the user's conversations annotated with the reply count
        (assistant messages), the `Sum` of input and output tokens, the `Sum` of
        `cost_micros`, and last used. Order explicitly with `.order_by("-updated_at",
        "-id")`, because `Meta.ordering` is ignored on aggregates. Paginate with
        `Paginator(…, 20)` and `get_page(request.GET.get("page"))`. Show newer/older
        links when there are several pages.
  - [ ] **Replies per chat:** one query for the assistant messages of the conversations
        on the current page (`conversation__in=page`), grouped in Python, so there's no
        N+1. Each chat is a `<details>` whose summary row has the title (a link to the
        chat), model, replies, tokens in/out, total cost (`dollars_precise`) and last
        used. Its body is a table of replies: date/time, tokens in/out, cost, and
        "(estimated)" or "(cut short)" where they apply.
  - [ ] **Credit added:** the non-`charge` ledger rows (sign-up credit, top-ups,
        adjustments), with date, type, note and amount.
  - [ ] Empty states: "No chats yet", with a link to New chat.
- [ ] `/credit/`: replace the view with `RedirectView(pattern_name="profile",
      permanent=True)`, which returns **301**. Delete `templates/billing/credit.html` and
      the old `credit` view.
- [ ] Nav (`base.html`): replace "Available credit: $X.XX" with **"My Profile ·
      {{ available_credit_micros|dollars }}"**, linking to `/profile/`.
- [ ] Update `chat/_out_of_credit.html`: the link "View your credit" now points to
      `profile`.
- [ ] Tests (`billing/tests.py`; replace the old `CreditPageTests`):
  - [ ] Anonymous → 302 to log-in. A logged-in user → 200, showing "$2.00" and "Sign-up
        credit".
  - [ ] With two chats, charged through `send_message` with a mocked `llm.complete`:
    - both chats appear, newest first, with the right reply counts, tokens and total
      cost
    - each reply row shows its cost
    - another user's chats and ledger rows don't appear
  - [ ] Totals: added − spent == balance == the ledger sum. A top-up appears under
        Credit added, and charges don't.
  - [ ] Pagination: with 21 chats, page 1 has 20 and page 2 has 1. `?page=abc` → 200.
  - [ ] The profile query count is bounded (`assertNumQueries`) whatever the number of
        chats on the page.
  - [ ] `GET /credit/` → **301** to `/profile/`.
  - [ ] The nav shows "My Profile · $2.00" and links to `/profile/`. A balance of 1 µ$
        shows "$0.00", and -1 µ$ shows "-$0.01".
- [ ] Commit.

## Step 2: `feat: redesign chat pages as a sidebar and bubble thread`

Everything in this step works **without JavaScript**.

- [ ] Templates (`templates/chat/`):
  - [ ] `layout.html` (extends `base.html`): a full-height grid under the top nav, with
        `aside.sidebar` and `section.chat-main`. `chat_new` and `chat_detail` both
        extend it.
  - [ ] `_sidebar.html`: a **+ New chat** button and the user's chats, newest first
        (titles only). The current chat is marked with `aria-current="page"`. It's the
        wrapper for the list, marked `data-sidebar-list`.
  - [ ] `_main.html`: the chat header, the thread and the composer (the unit the script
        swaps after a new chat's first reply).
  - [ ] `_message.html`: one bubble. `.bubble.user` is right-aligned with the accent
        color. `.bubble.assistant` is left-aligned and neutral, with a small model-name
        label. It renders `content|linebreaksbr` (autoescaped). A cut-off reply adds
        "Reply was cut short." with no token count.
  - [ ] `_composer.html`:
    - **New chat:** the model `<select>` (grouped by provider, **showing names and tiers
      only, no prices**), the textarea and Send.
    - **Existing chat:** a read-only **model label chip**, the textarea and Send.
    - A hint, "Enter to send · Shift+Enter for a new line", visible only when
      `html.js` is set (added by the script in Step 5).
    - An error region (`role="alert"`) and the out-of-credit notice sit above it.
    - When out of credit, the textarea and button are rendered `disabled`. The server
      still returns 402 if posted.
  - [ ] Delete `conversation_list.html`, `conversation_new.html` and
        `conversation_detail.html` (replaced by the above).
- [ ] Thread:
  - [ ] A `.thread` scroll container with `display:flex; flex-direction:column-reverse;
        overflow-y:auto`, wrapping an inner `.thread-inner` whose messages are in
        normal order. The page then opens **scrolled to the newest message with no
        JS**.
  - [ ] It's an `aria-live="polite"` region. The last bubble keeps `id="latest"`.
  - [ ] The empty state for New chat: "Start a conversation" with the picker below.
- [ ] Composer: `position: sticky; bottom: 0` inside `.chat-main` (a flex column
      where the thread is `flex: 1`). It stays visible while the thread scrolls.
- [ ] Mobile (under 720px): the desktop `aside` is hidden. A `<details
      class="mobile-chats">` with the summary "Chats" at the top of `.chat-main`
      includes the same `_sidebar.html`. There's no horizontal scroll at 360px width.
- [ ] Views (`chat/views.py`):
  - [ ] `chat_list` (`/chats/`) → **302** to the user's most recently updated chat, or
        to `chat_new` if they have none.
  - [ ] Add `sidebar_conversations(user)` (explicit `order_by`, no annotations) to the
        context of `chat_new` and `chat_detail`.
  - [ ] Remove `total_cost` and all token and cost context. The 400/402/404/502/503
        behavior is unchanged.
- [ ] Remove costs from the chat pages: there's no "tokens", "per 1M", reply cost or
      chat total anywhere in `.chat-main` or the sidebar. The nav's "My Profile ·
      $X.XX" is the only money on these pages (decision #1).
- [ ] Nav: **Chats** (→ `/chats/`, which redirects) stays. Drop the separate **New
      chat** nav link, since the sidebar has it. Home "Start a chat" and `/models/`
      "Start a chat" still link to `chat_new`.
- [ ] CSS goes in `base.html` (inline, as today), using the existing variables.
- [ ] Tests (`chat/tests.py`; update the loop 2 view tests for the new markup):
  - [ ] `/chats/` → 302 to the newest chat. With no chats → 302 to `/chats/new/`.
        Anonymous → 302 to log-in.
  - [ ] The chat page has the sidebar with the user's chats only, newest first, the
        current chat marked `aria-current`, and a New chat link.
  - [ ] Bubbles: the user message has `bubble user` and the reply has `bubble
        assistant`, in order.
  - [ ] **No costs on the chat pages:** the chat page and New chat contain none of
        "tokens", "per 1M" or the reply's cost string (e.g. "$0.0011"). The nav contains
        "My Profile · ".
  - [ ] The New chat composer has the grouped `<select>`. The existing-chat composer
        has no `<select>` and shows the model label.
  - [ ] Out of credit: the composer is `disabled` and the notice links to `/profile/`.
        A POST still → 402, and the proxy isn't called.
  - [ ] Every existing status-code test (400, 402, 404, 502, 503, 302 success) still
        passes via form posts.
  - [ ] A cut-off reply shows "Reply was cut short." and not "1,024 tokens".
  - [ ] XSS: a `<script>` reply is still escaped.
- [ ] Commit.

## Step 3: `feat: rename chats from the chat header`

- [ ] `RenameForm`: `title`, required, stripped, 1–100 characters.
- [ ] `POST /chats/<id>/rename/` (`chat_rename`, `login_required`, POST only, so GET →
      **405**):
  - not the owner → 404
  - invalid → **400**, re-rendering the chat page with the error and the rename form
    open
  - valid → save the title (without bumping `updated_at`, so renaming doesn't reorder
    the sidebar), then 302 to `chat_detail`
- [ ] Header UI: the title, with a `<details class="rename"><summary>Rename</summary>`
      containing the form (the input is prefilled). It works without JS.
- [ ] Tests:
  - [ ] Renaming → 302. The title appears in the header and the sidebar, and the
        profile page shows the new title.
  - [ ] An empty or whitespace title → 400. A 101-character title → 400. Another user's
        chat → 404. GET → 405. Anonymous → 302 to log-in.
  - [ ] Renaming leaves `updated_at` unchanged, so the sidebar order holds.
- [ ] Commit.

## Step 4: `feat: return JSON from chat views for fetch requests`

- [ ] `chat/views.py` helpers:
  - [ ] `wants_json(request)`: `request.headers.get("Accept", "").startswith("application/json")`.
  - [ ] `chat_login_required`: like `login_required`, but returns **401**
        `{"error": "Please log in again.", "login_url": …}` when `wants_json`. It's
        used on `chat_new` and `chat_detail`.
  - [ ] `respond_error(request, context, template, status, message, **extra)`: renders
        the page (form mode) or a `JsonResponse` (JSON mode) with the **same status**.
- [ ] In `chat_new` and `chat_detail`, route every existing exit through the helpers.
      The 404 for another user's chat returns JSON `{"error": "Chat not found."}` with
      404 in JSON mode.
- [ ] Success in JSON mode:
  - existing chat → **200** `{"messages_html": <the two new messages rendered with
    _message.html>, "sidebar_html": <_sidebar.html>}`
  - new chat → **200** `{"chat_url", "main_html": <_main.html for the new chat>,
    "sidebar_html"}`
- [ ] 400 JSON includes `field_errors` (`form.errors.get_json_data()`). 402 JSON
      includes `out_of_credit: true`.
- [ ] Tests (a JSON-mode twin for each status, using `HTTP_ACCEPT="application/json"`
      and the mocked `llm.openai.requests.post`):
  - [ ] Existing chat success → 200 JSON containing the reply text in `bubble
        assistant`, and the sidebar HTML. Exactly one charge, of the same cost as the
        form path. The proxy received the full history.
  - [ ] New chat success → 200 with `chat_url` for the created conversation, and
        `main_html` containing both bubbles and a model label (no `<select>`).
  - [ ] 400 (empty, too long, unsupported model), 402 (balance 0 and -1; proxy **not**
        called), 404 (another user's chat; proxy not called), 502 and 503 (nothing saved
        or charged). All return the JSON `error` with the same status as form mode.
  - [ ] Logged out + JSON → **401** JSON (not 302). Logged out + form → 302 (unchanged).
  - [ ] A browser-style `Accept: text/html,…,*/*` post still gets the 302 form behavior.
  - [ ] An XSS check on `messages_html`: `<script>` is escaped.
  - [ ] No cost or token strings in any JSON HTML fragment.
- [ ] Commit.

## Step 5: `feat: send chat messages without reloading`

- [ ] `templates/chat/_script.html`, included once at the end of `layout.html`. It's an
      inline `<script>` (decision #5), plain ES2017 or later, with no dependencies. It
      uses event delegation on `document`, so the handlers survive `main_html` swaps.
  - [ ] On load: `document.documentElement.classList.add("js")`.
  - [ ] **Enter to send:** on `keydown` in the composer textarea, if `key === "Enter"`
        and there's no Shift/Alt/Ctrl/Meta and it's not `isComposing` (with a
        `keyCode !== 229` fallback), then `preventDefault()` and
        `form.requestSubmit()`. Shift+Enter inserts a new line as usual.
  - [ ] **Submit:** intercept `submit` on `form.composer`. If the trimmed text is empty,
        do nothing. Otherwise:
    1. Build `FormData(form)` (it includes `csrfmiddlewaretoken` and the model).
    2. Append a pending `.bubble.user` (text via `textContent`) and a `.bubble.assistant.thinking`
       with three animated dots and visually hidden "Thinking…". Set
       `aria-busy="true"` on the thread.
    3. Clear and disable the textarea and button, then scroll to the bottom.
    4. `fetch(form.action, {method: "POST", body, headers: {Accept: "application/json"}, credentials: "same-origin"})`.
  - [ ] **On 200:** remove the pending bubbles.
    - If there's `main_html` (new chat): replace `.chat-main`'s contents with it, then
      `history.pushState({}, "", chat_url)`.
    - Otherwise, insert `messages_html` at the end of `.thread-inner`.
    - Replace every `[data-sidebar-list]` with `sidebar_html`.
    - Re-enable the composer, focus the textarea and scroll to the bottom.
  - [ ] **On an error status:** remove the pending bubbles, **restore the draft** into
        the textarea, and put the `error` into the `role="alert"` region.
    - **402:** keep the composer disabled and show the out-of-credit notice, linking to
      `/profile/`.
    - **401:** show "Please log in again", linking to `login_url`.
    - **A non-JSON or network failure:** show "Something went wrong. Please try again."
    - Otherwise, re-enable the composer.
  - [ ] **The nav balance:** the script doesn't update "My Profile · $X.XX" after a
        send. The next full page load does. (The plan accepts this; see "Open risks".)
  - [ ] `popstate` → `location.reload()` (keeps back/forward correct after
        `pushState`).
  - [ ] Honor `prefers-reduced-motion`: the dots don't animate.
- [ ] CSS: `.thinking` dots and the `.js .hint` visibility.
- [ ] Tests (server side only):
  - [ ] The chat pages include the script exactly once, and the composer form has class
        `composer` and the right `action` (`chat_new` or `chat_detail`).
  - [ ] The script contains no proxy URL or key name. `grep -r
        "proxy.litechat.ai\|OPENAI_API_KEY" templates/` is empty.
- [ ] Commit.

## Step 6: `chore: update README for the chat redesign and My Profile`

- [ ] "Using the app":
  - [ ] The chat layout: sidebar, Enter / Shift+Enter, the thinking indicator.
  - [ ] Rename from the chat header.
  - [ ] **My Profile** (nav, with the balance) shows the credit, and what each chat and
        reply cost. Costs no longer appear in chats.
  - [ ] `/credit/` now redirects to `/profile/`.
- [ ] Note that the chat pages work without JavaScript (full page reloads). The script
      only enhances them.
- [ ] Update the status note to loop 3.
- [ ] Commit.

## Step 7: Verify the whole loop (no commit)

- [ ] `python manage.py check`, and `makemigrations --check --dry-run` shows **no
      changes** (this loop changes no models).
- [ ] `python manage.py test` all pass, with no real HTTP (the guard is active).
- [ ] `python manage.py migrate` on the dev DB: expect "No migrations to apply". Never
      reset.
- [ ] Live server on `0.0.0.0:8000`: GET `/`, `/models/` → 200. `/chats/`,
      `/profile/` → 302 to log-in when anonymous. `/credit/` → 301.
- [ ] **One real end-to-end JSON send** (only if `OPENAI_API_KEY` is set, checked
      without printing it). Run it on a throwaway test DB via the test client with
      `HTTP_ACCEPT="application/json"`:
  - New chat → 200 with `main_html`.
  - A follow-up → 200 with `messages_html`.
  - `/profile/` shows both replies' costs and the totals, and the nav shows "My Profile
    · $1.99".
- [ ] **Browser pass (the JS behavior the test client can't check).** Drive Chrome with
      the browser tooling if it's available, otherwise hand this checklist to the user.
      It uses a dedicated `uitest` account signed up on the **dev DB**. That adds rows
      but resets nothing. **Ask the user before creating it.**
  - [ ] Enter sends. Shift+Enter adds a new line.
  - [ ] The user bubble appears at once, with the thinking bubble. The reply replaces it
        with no reload.
  - [ ] The first message in New chat updates the URL to `/chats/<id>/`, and the chat
        appears at the top of the sidebar.
  - [ ] Rename works, and the sidebar and header update.
  - [ ] My Profile shows the chat and reply costs. The chat pages show none.
  - [ ] With JavaScript disabled, sending still works via a page reload.
  - [ ] At phone width (about 375px): no horizontal scroll, the Chats toggle works, and
        the composer stays visible.
- [ ] `git status` is clean. `git log main..loop3-chat-redesign --oneline` shows six
      commits. Stop and wait for **rendezvous**.

## Open risks (accepted for this loop)

- **The nav balance goes stale after a fetch send** until the next page load. The
  alternative is returning `balance_html` in the JSON and updating the nav. It's cheap,
  and can be added if the stale value bothers you in the browser pass.
- **Two tabs can still both send** at a balance just above $0. The overdraft is bounded
  (first study, §6.3). The script only prevents double sends within one tab.
- **The JS behavior has no automated tests** (study §9). It's covered by the browser
  pass above, and the server contract it relies on is fully tested.

## Done when

- The chat pages look and work like a chatbot:
  - a sidebar with New chat
  - bubbles (mine on the right) in one thread that opens at the newest message
  - a pinned composer where Enter sends
  - a model picker on New chat, and a fixed label in existing chats
  - no reload, with a thinking indicator
  - renaming from the header
- There's no cost or token count on any chat page. My Profile (nav: "My Profile ·
  $X.XX") shows the credit, the totals, and every chat's and reply's cost.
  `/credit/` → 301.
- Metering is unchanged: the 402 block, charging the actual cost, charging nothing on
  failure. Every status code holds in both form and JSON modes, and JSON requests from
  logged-out users get 401.
- Everything works with JavaScript disabled. No new dependencies and no migrations.
