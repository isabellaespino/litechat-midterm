# Study: Chatbot-style chat UI and a My Profile page

- **Date:** 2026-09-29 (Unix 1790662970)
- **Type:** study (feasibility and tradeoffs; no code)
- **Builds on:** `doc/study/1790657879-litechat-clone-feasibility.md`. Loop 2 is on
  `main`; see `doc/wiki/chat.md`.
- **Status:** draft for review. Decisions needed in §10.

## 1. Request

Redesign the chat pages so they feel like a normal AI chatbot (ChatGPT, Litechat),
instead of one message per page like email:

1. A **sidebar** listing my chats, with a **New chat** button.
2. **Bubbles** in one scrolling thread: mine on the right, the model's on the left.
3. The **message box fixed at the bottom**, with **Enter to send**.
4. The **model picker near the message box**.
5. **Sending without a full page reload**, with a **"thinking" indicator** while the
   reply loads.
6. **No costs or token counts on the chat pages.**
7. A **My Profile** page, reachable from the nav, showing the available credit and the
   usage history (what each chat and each reply cost). It **replaces `/credit/`**.

Constraints:
- `CLAUDE.md`: no frontend framework; server-rendered templates; LLM requests only from
  the backend; correct status codes.
- Metering, the 402 block and every existing status code must keep working.

**Verdict: feasible without a framework or any new dependency.** Items 1–4, 6 and 7 are
server-rendered HTML and CSS. Items 3 (Enter to send) and 5 (no reload, thinking
indicator) can't be done without JavaScript. A small, dependency-free script that
*progressively enhances* the existing forms delivers them and keeps every page working
without JS. Replies should **stay whole** for now (§5).

## 2. Where we are (loop 2)

- The chat pages use a plain POST, then a redirect back to the page, then a full page
  load (PRG). Sending reloads the page and jumps to `#latest`.
- Chats are listed on a separate `/chats/` page with cost columns. Each reply shows "N in
  / M out tokens · $cost", and each chat shows its total cost.
- `/credit/` shows the balance and the raw ledger. The nav shows "Available credit:
  $X.XX".
- `chat.services.send_message()` does the proxy call and the charge. The views do the
  checks: 404 → 400 → inactive model 400 → **402** → 502/503 → success.

The service, the ledger and the checks don't need to change. The redesign is about how
the pages look and how a send reaches the view.

## 3. Does this need JavaScript?

`CLAUDE.md` forbids a **frontend framework**. It doesn't forbid JavaScript. The
relevant rules are: no framework, pages rendered on the server, and LLM calls only from
the backend. A browser script that posts to **our** Django view doesn't call the LLM.
The view still does, on the server, with the key in `.env`.

What each feature needs:

| Feature | Without JS | With a small script |
|---|---|---|
| Sidebar, bubbles, one scrolling thread | ✅ CSS grid/flex | same |
| Opening a chat scrolled to the newest message | ✅ `#latest` anchor, or the `flex-direction: column-reverse` scroll trick | `scrollTop` after each send |
| Message box fixed at the bottom | ✅ CSS (the thread scrolls, the composer doesn't) | same |
| Model picker by the message box | ✅ a `<select>` in the composer form | same |
| **Enter to send**, Shift+Enter for a new line | ❌ Enter in a `<textarea>` always adds a new line. A single-line `<input>` would submit on Enter but can't hold multi-line messages. | ✅ a `keydown` handler (ignoring Enter while an input method editor is composing text, e.g. for Chinese or Japanese) |
| **No full page reload** | ❌ a form POST always navigates | ✅ `fetch()` and insert the reply |
| **"Thinking" indicator** | ❌ the browser shows nothing but its own spinner while the request runs | ✅ show the user's bubble immediately plus an animated "thinking" bubble |
| Disable Send while a reply is pending | ❌ | ✅ also reduces accidental double charges |

**Options:**

| Option | Verdict |
|---|---|
| **A. No JS** | Delivers only the layout. Enter to send, no reload and the thinking indicator (three of the headline asks) are impossible. Rejected as the whole answer, but it is the **fallback** every page must still support. |
| **B. Small vanilla script, progressive enhancement (recommended)** | About 150 lines of plain JavaScript, no framework, no build step, no new dependency. It intercepts the composer's submit, sends the same form with `fetch`, and inserts HTML **rendered by the server**. With JS off, the same forms still work the PRG way. |
| C. htmx (or a similar "HTML over the wire" library) | Tidy: attributes instead of hand-written `fetch`. But it adds a dependency, which `CLAUDE.md` says to justify first, and it saves only a few dozen lines here. Its model (server-rendered fragments swapped into the page) is the same as B's, so switching later is cheap. Not worth it yet. |
| D. React/Vue/Svelte single-page app | Forbidden by `CLAUDE.md`. It would also move rendering, and the temptation to call LLMs, into the browser. Rejected. |

### How option B works

The script must not render messages itself. Instead:

- **The server stays the only renderer.** One partial template renders a message
  bubble. The full page uses it, and the fetch response returns the new bubbles rendered
  by the same partial. There's one source of truth and Django's autoescaping applies
  everywhere, which matters because model output is untrusted.
- **The browser shows only what it already knows:** the user's own text, inserted with
  `textContent` (never `innerHTML`), plus the thinking bubble. The server's HTML then
  replaces them.
- **One view, two response formats.** The chat views read the request's `Accept`
  header. A normal form post gets the PRG behavior it gets today. A post that asks for
  JSON (`Accept: application/json`) runs **exactly the same checks and service call**
  but gets JSON back. Keeping one view avoids a second code path where metering could
  drift.

## 4. Status codes and metering under fetch

Every check stays in the view, in today's order, before `send_message()` is called.
Only the response body changes when the request asks for JSON:

| Situation | Form post (unchanged) | Fetch/JSON post |
|---|---|---|
| Success, existing chat | 302 → `#latest` | **200** `{"messages_html": "<the two new bubbles>"}` |
| Success, new chat | 302 → the new chat | **200** `{"messages_html", "chat_url", "sidebar_item_html"}`. The script updates the address bar with `history.pushState` and adds the chat to the sidebar. |
| Invalid form (empty, too long, bad model) | 400, re-rendered page | 400 `{"error", "field_errors"}` |
| Inactive or unsupported model | 400 | 400 `{"error"}` |
| Balance ≤ $0 | **402**, notice on the page | **402** `{"error", "out_of_credit": true}`. The script shows the notice and disables the composer. |
| Proxy failure | 502 / 503 | 502 / 503 `{"error"}`. The script removes the pending bubbles, **restores the draft**, and shows the error. |
| Another user's chat | 404 | 404 |
| Not logged in | 302 to log-in | **401** `{"error": "Please log in again."}` (see the pitfall below) |

Success is 200, as `CLAUDE.md` requires. The form path keeps its correct 302.

**Pitfalls the plan must handle:**
- **An expired session under fetch.** `login_required` redirects to the log-in page, and
  `fetch` silently follows that redirect. The script would then receive the log-in
  page's HTML with a 200 and could treat it as a reply. JSON requests from logged-out
  users must get a **401** instead of a redirect.
- **CSRF.** The script sends the form's `csrfmiddlewaretoken`, either by posting the
  form data or with an `X-CSRFToken` header. There's no exemption.
- **Metering is unchanged.** The 402 pre-check, charging the actual cost, charging
  nothing on failure, and the atomic ledger write all live in `chat.views` and
  `chat.services`, which both paths share. Tests must cover the 402, 400, 502/503 and
  404 cases **in both modes**, and assert that the proxy isn't called when blocked.
- **Closing the tab mid-reply.** The server finishes, saves and charges, exactly as
  today. The tokens were consumed, and the reply appears when the chat is reopened.
- **Double sends.** Disabling the composer while a reply is pending prevents accidental
  double submits in one tab. Two tabs can still race; the study accepted that (§6.3,
  bounded overdraft).
- **Long waits.** The proxy can take up to 120 s. `fetch` has no default timeout, so
  the thinking bubble simply stays up. The server's timeout decides, and the script gets
  a 503 and restores the draft.

## 5. Stream the reply, or keep it whole?

| | Whole replies (today, recommended) | Streaming (SSE or a streamed `fetch`) |
|---|---|---|
| User experience | A thinking bubble, then the full reply | Text appears as it's generated |
| **Status codes** | The final status is known before we respond, so 402/502/503 work as specified | Headers (**200**) go out before the proxy finishes. A failure mid-stream **can't become a 502 or 503**, so the status-code rule is broken for those cases and errors need an in-stream signal. |
| **Billing** | Usage arrives with the reply, and one atomic write saves the messages and the charge | Usage arrives only at the end of the stream, and for OpenAI only if `stream_options.include_usage` is set. If the stream breaks, tokens were consumed but usage may never arrive: we'd have to estimate or give the reply away, and decide what to do with a partial reply. |
| Server | One blocking request per send (fine on `runserver`) | A long-lived streaming response per send, with a worker held for the whole stream. Awkward under sync Django/WSGI. |
| Providers | One request/response parser each | Three different stream formats to handle before adding Anthropic and Google (`[DONE]`, `message_stop`, no end marker at all) |
| Code | Unchanged service | A streaming view, an incremental parser, and client code to read the stream |

**Recommendation: keep replies whole.** The thinking indicator removes the "dead page"
feeling, which is most of the gain, at none of the billing or status-code risk. Replies
are capped at 1,024 tokens, so the wait for the rest of a reply once it has started is
bounded. Most of the observed delay is probably the proxy's time before it sends
anything, which streaming wouldn't shorten. Revisit streaming in its own study once all
three adapters exist.

## 6. Layout (server-rendered)

```
┌───────────────────────────────────────────────────────────────┐
│ top nav: Litechat · Home · Models · Chats · My Profile · …    │
├──────────────┬────────────────────────────────────────────────┤
│ [+ New chat] │  Chat title                 GPT-5.6 Luna       │
│              │                                                │
│ Today        │   ┌──────────────────────┐                     │
│ ▸ Plan a trip│   │ model reply (left)   │                     │
│   Hello…     │   └──────────────────────┘                     │
│              │                  ┌───────────────────────┐     │
│ Earlier      │                  │ my message (right)    │     │
│   Recipe…    │                  └───────────────────────┘     │
│              │   ┌──────┐                                     │
│              │   │ ● ● ●│  thinking…                          │
│              │   └──────┘                                     │
│              ├────────────────────────────────────────────────┤
│              │ [model ▾] [ Message…              ] [Send]     │
│              │ Enter to send · Shift+Enter for a new line     │
└──────────────┴────────────────────────────────────────────────┘
```

- **Page shell:** a full-height (`100dvh`) grid under the existing top nav: the sidebar,
  plus a main column (header, a scrolling thread, and a composer that stays put). The
  top nav stays because `CLAUDE.md` requires every page to be reachable from navigation.
- **Sidebar:**
  - The user's chats, newest first, as titles only. An optional nicety: group them as
    Today / Previous 7 days / Earlier.
  - The current chat is highlighted, and a **New chat** button sits at the top.
  - It uses the same query as today's `/chats/` minus the cost columns, and keeps the
    explicit `order_by` lesson from loop 2.
- **Bubbles:**
  - Mine are right-aligned with the accent color. The model's are left-aligned and
    neutral.
  - Content is escaped, with `linebreaksbr`. Markdown rendering stays out of scope; it
    needs a sanitizer dependency (first study, §6.10).
  - A reply cut off at the output cap shows a neutral "Reply was cut short." with no
    token count.
- **Composer:** a textarea with the Send button. **Model picker:**
  - **New chat:** a `<select>` of chat-enabled models, grouped by provider, next to the
    textarea.
  - **Existing chat:** the model is fixed per chat (first study, §6.6), so the picker
    shows as a read-only chip with the model name. Switching per message stays deferred
    (§10 Q2). Today only one model can chat anyway.
- **Out of credit:** a notice right above the composer: "You're out of credit. Contact
  an administrator to top up", linking to My Profile. The composer is disabled. The
  server still enforces 402 whatever the browser shows.
- **Mobile (phone width):** the sidebar collapses behind a "Chats" toggle. A
  `<details>`/`<summary>` works with no JS. The composer stays pinned, and bubbles use
  most of the width.
- **Accessibility:**
  - The thread is an `aria-live="polite"` region, so new replies are announced.
  - The thinking bubble has visible text ("Thinking…") and sets `aria-busy`.
  - Focus returns to the textarea after a send, and the Enter/Shift+Enter hint is shown
    as text.
  - The dots animation respects `prefers-reduced-motion`.
- **URLs:** keep `/chats/new/` and `/chats/<id>/`. `/chats/` can redirect to the most
  recent chat, or to New chat if there are none, because the sidebar replaces the list
  page. It could also stay as a plain list for no-JS narrow screens; the plan decides.

## 7. Removing costs from the chat pages

Remove:
- the per-reply "N in / M out tokens · $cost" line
- the chat's total cost in the header
- the cost and message-count columns of the chat list
- the model prices in the chat's model picker (keep name and tier; prices stay on
  `/models/`)

Keep:
- the out-of-credit notice, which is about the balance, not a cost
- the cut-short note, reworded without the token count

The data isn't touched: every `Message` still stores tokens, cost and a price snapshot,
and every `charge` still links to its reply. It's only shown on My Profile (and in
admin).

## 8. My Profile page

`/profile/` (name `profile`), login required. It replaces `/credit/`.

- **Account:** username and member since.
- **Available credit:** shown large, rounded down to the cent (`$1.99`), plus "Contact
  an administrator to add credit."
- **Usage by chat:** one row per chat, newest activity first. Each row shows the title
  (linking to the chat), model, number of replies, tokens in/out, **total cost**
  (`dollars_precise`) and last used. Each row expands (`<details>`, no JS) into its
  **replies**: date/time, tokens in/out and cost per reply, plus "(estimated)" or "(cut
  short)" where they apply.
- **Credit added:** sign-up credit, top-ups and adjustments (the non-`charge` ledger
  rows), with date, note and amount.
- **Totals:** total added, total spent, and the balance, which equals the ledger sum.
  That makes the invariant visible to the user.

**Queries (no N+1):**
1. Conversations with `Count` and `Sum` annotations, **explicitly ordered**.
2. One query for the assistant messages of the conversations on the current page,
   grouped in Python.
3. The non-charge ledger rows.

Paginate the chats with Django's `Paginator`, 20 per page.

**Nav:** "Available credit: $X.XX" is replaced by **My Profile**, whether or not it
carries a small balance (§10 Q1). `/credit/` returns a **301** to `/profile/`, so old
links and bookmarks keep working and the status code is correct. The wiki and README
references move to `/profile/`. The admin is unchanged.

## 9. Delivering the script, and testing it

- **Static files and `DEBUG`:** a fresh clone following the README leaves `DJANGO_DEBUG`
  empty, so `DEBUG` is off. With `DEBUG` off, `runserver` **doesn't serve `/static/`**,
  so a separate `chat.js` would silently not load. Options:
  - **(a) Recommended:** an inline `<script>` in the chat template, like the inline CSS
    in `base.html`. It always loads, and needs no dependency or README change.
  - (b) `static/chat/chat.js`, plus telling the README to set `DJANGO_DEBUG=true` for
    local use.
  - (c) Add `whitenoise`, a new dependency.

  Option (a) is fine at around 150 lines. Move to (b) or (c) if the script grows.
- **Testing:**
  - **Django tests (required):** the JSON contract of both views, covering 200, 400,
    401, 402, 404, 502 and 503. Check the proxy isn't called when blocked, that the JSON
    path charges identically to the form path, that no cost or token text appears on
    the chat pages, the My Profile totals and per-reply rows, the 301 from `/credit/`,
    and the nav links. The no-network test runner still blocks real HTTP.
  - **Browser behavior:** Enter vs Shift+Enter, the thinking bubble, restoring the
    draft, `pushState`. This can't be checked by Django's test client. Automated browser
    tests would need Selenium or Playwright plus a browser driver, a heavy dependency for
    about 150 lines. **Recommend a scripted manual browser check** in the plan's verify
    step (and optionally the Chrome browser tooling), not a new test dependency.
- **No new Python dependencies** in any recommended option.

## 10. Open questions (decisions for the plan)

1. **Nav:** replace "Available credit: $X.XX" with a plain **My Profile** link, or
   **"My Profile · $1.99"**? Recommendation: **plain My Profile**. It matches "no costs
   on chat pages", and the balance is one click away.
2. **Model picker in an existing chat:** a read-only chip (recommended; the model stays
   fixed per chat), or allow switching models per message now? Only one model can chat
   today, so switching adds nothing until the adapters land.
3. **Rename chats:** fold loop 3's rename into this redesign? It fits naturally as a
   pencil icon or small form in the chat header, and works without JS. Recommendation:
   **yes, include it**.
4. **`/chats/` list page:** redirect it to the latest chat (the sidebar replaces it), or
   keep it as a simple list? Recommendation: **redirect**, and keep a "Chats" nav link
   that goes to the chat view.
5. **Script delivery:** inline (recommended) or a static file plus `DJANGO_DEBUG=true`
   in the README (§9)?
6. **Streaming:** confirm **whole replies** for now (§5).

## 11. Recommendation and suggested plan shape

Proceed with option B (a vanilla progressive-enhancement script), whole replies, and a
My Profile page. There are no new dependencies. Suggested commits, one each:

1. `feat: add My Profile page with usage history`. `/profile/`, with `/credit/` → 301,
   and the nav link.
2. `feat: redesign chat pages as a sidebar and bubble thread`. Server-rendered layout,
   the fixed composer, the picker by the composer, costs removed. It works fully without
   JS.
3. `feat: return JSON from chat views for fetch requests`. Content negotiation, 401 for
   JSON requests when logged out, and tests for every status in both modes.
4. `feat: send chat messages without reloading`. The inline script: Enter to send, the
   thinking bubble, errors restoring the draft, `pushState` and the sidebar update for
   new chats.
5. (If Q3 = yes) `feat: rename chats from the chat header`.
6. `chore: update README` for the profile, and the chat usage notes.

Then verify: the Django tests, plus a manual browser pass over Enter/Shift+Enter, the
thinking bubble, the 402 state, a proxy error restoring the draft, a new chat appearing
in the sidebar, and a pass with JS disabled.
