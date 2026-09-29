# Development

## Setup

Follow `README.md`. In short:

1. Create and activate a virtualenv (`python3 -m venv .venv`).
2. `pip install -r requirements.txt`.
3. `cp .env.example .env`, then set `DJANGO_SECRET_KEY`, and `OPENAI_API_KEY` to chat.
4. `python manage.py migrate`.
5. `python manage.py seed`.
6. `python manage.py createsuperuser`.
7. `python manage.py runserver 0.0.0.0:8000`.

These steps were verified on a fresh clone at the loop 1 and loop 2 rendezvous.

## Rules that constrain the code (from `CLAUDE.md`)

- **Secrets** live only in `.env`, which is git-ignored. Never print its contents. To
  check that a key is set, test for a non-empty value without echoing it, e.g.
  `grep -cE '^OPENAI_API_KEY=.+' .env`. Add every new variable to `.env.example` with
  no value.
- **LLM calls** happen from the backend only (`llm/`), never from browser code.
- **Dependencies:** declare every one in `requirements.txt`, and justify it in a study
  before adding it.
- **Database:** never reset or reseed `db.sqlite3`. `migrate` and `seed` are additive
  and safe. Verify behavior with `python manage.py test`, which uses a throwaway test
  database.
- **Navigation:** every page must be linked from the nav or another page.
- **Server:** always bind to `0.0.0.0:8000`.

## Tests

`python manage.py test` runs 175 tests (at loop 6):

| File | Tests | Covers |
|---|---|---|
| `config/tests.py` | 18 | the money helpers (rounding, negatives, conversion); `BrandTests` (no rendered page says "Litechat", the Chat4All titles, nav and admin header, the script's title); `ContrastTests` (the WCAG ratio of 22 palette pairs ≥ 4.5, parsed from `base.html`, and gold text only on navy); `EstimateTests`; `LandingPageTests` (hero, CTA for logged-out and logged-in users, steps, snapshot values, the snapshot following catalog edits, the theme only on `/`) |
| `accounts/tests.py` | 19 | sign-up, log-in and log-out status codes and behavior, including the 400s; `AuthCardTests` (headings, a label per input, one full-width button, cross-links, no social login, errors in the card); the Global System Prompt form (save, strip, clear, 400 over 4,000 characters, 405, anonymous, admin inline) |
| `catalog/tests.py` | 7 | `/models/` grouping and inactive hiding; dollar↔µ$ in the admin form; the seed command's idempotence |
| `billing/tests.py` | 22 | sign-up credit for every creation path; the ledger invariant; `str()` in dollars; admin top-ups, adjustments and dollar display; append-only 403s; read-only wallets; **My Profile** (usage by chat and reply, totals, pagination, bounded queries, the `/credit/` 301, the nav "My Profile · $X.XX") |
| `llm/tests.py` | 31 | `ProxyErrorMappingTests` runs the **same** checks for every row of `PROVIDER_CASES` (OpenAI, Anthropic, Google): 502/503 mapping, timeouts and connection errors, malformed bodies, a 120 s timeout, and a missing key → 503 with no request. It also covers per-adapter request shape, the system prompt present or absent, parsing, usage and stop mapping, and estimates; Anthropic block joining, cache tokens and same-role merging; Google roles, `systemInstruction`, thinking tokens and safety blocks; dispatch; and the no-network guard. |
| `chat/tests.py` | 78 | everything from loop 3 (form and JSON modes, the sidebar, bubbles, no costs, renaming, the script hooks). **Loop 5:** `MarkdownRenderingTests` and `MarkdownInChatTests` (a 14-payload XSS corpus, parsed, through the renderer, the page and both JSON fragments; features; stored raw; user text not rendered); `DeleteChatTests` (confirmation page, access rules, charges kept and balance unchanged, redirect after delete, the "Deleted chats" line reconciling, the in-flight race in both modes, and the backstop path); `SidebarDateTests` (`<time>` markup, bump on send but not on rename, JSON fragments, script hooks). From loop 4: `AllProvidersChatTests`: for **each** model, its own price in both modes, history resent in its format, 402 before the proxy, 502/503 with nothing charged, a missing key affecting only that provider, a Google safety block, and the three-model picker. Also `GlobalSystemPromptTests`: the prompt in each provider's format, left out when blank, never another user's, read at send time, and charging and 402 unchanged. |

### The LLM proxy is never called from tests

- `TEST_RUNNER = "config.test_runner.NoNetworkTestRunner"` patches
  `requests.sessions.Session.request` to raise `RuntimeError("Real HTTP request
  attempted in tests…")` for the whole run. Any accidental real call fails the test.
  `llm/tests.py::NoNetworkGuardTests` checks the guard itself.
- Tests mock at one of two levels:
  - `mock.patch("llm.http.requests.post")`, the single place every adapter sends from,
    returns a **provider-shaped** response (`chat.tests.provider_reply(provider, …)`, or
    the `openai_body`/`anthropic_body`/`google_body` helpers in `llm/tests.py`). Used for
    the client tests and for the view tests, so the whole stack runs.
  - `mock.patch("llm.complete")` returns an `LLMReply`. Used for the service tests.
- Use `@override_settings(OPENAI_API_KEY=…, ANTHROPIC_API_KEY=…, GOOGLE_API_KEY=…)` in
  view tests, so they don't depend on your `.env`.
- **When adding a provider:** add a row to `llm.tests.PROVIDER_CASES` (the shared error
  tests then cover it), a branch in `chat.tests.provider_reply`, and an entry in
  `PROVIDER_MODELS`.

### Real proxy checks

Real calls happen only in a manual verification step, outside the test suite. It uses a
script run against a **throwaway test database** (`create_test_db` / `destroy_test_db`)
that follows nav links. Loop 2's check sent two real messages; loop 3's did the same
through the JSON path and checked each response's `balance` against the wallet. Loop 4's
check made 12 calls: a new chat and a follow-up per model, one per model with the system
prompt "Always reply in French." (all three replied in French, which confirmed Google's
`systemInstruction` shape), and one per model after clearing it. Every charge matched the
formula. It never
writes to `db.sqlite3`. The proxy is unreliable (see [chat](chat.md)), so expect to
retry once.

### Browser checks (the chat script)

Django's test client can't run JavaScript, so the script's behavior is checked in a real
browser at the verify step.
- Loop 3 drove **headless Chrome** through the DevTools protocol, from a Node script
  kept in the scratchpad, with no repo dependency. It ran against the dev server using
  the **`uitest`** account in the dev database, which the user authorized. Its password
  isn't recorded here: reset it with `python manage.py changepassword uitest` if you
  need it.
- 30 checks, including:
  - Enter vs Shift+Enter
  - the thinking bubble
  - no reload
  - `pushState` and the sidebar update
  - the nav balance being rewritten by the script
  - the draft restored after a real proxy error
  - renaming
  - phone width (375px)
  - sending with JavaScript disabled
- **Look at the screenshots, too.** Loop 3's layout-width bug passed every assertion
  and was only visible in a screenshot.
- **Gotcha:** `runserver --noreload` keeps Django's **cached template loader**, which
  never picks up template edits. Restart the server after changing templates, or run
  without `--noreload`.
- **Loop 5's check (17/17)** covered:
  - a real Markdown reply (table, list, bold, code), with no `img`, `script`, `iframe` or
    `[style]` inside `.md`
  - sidebar dates localized, with the browser's time zone switched from Los Angeles to
    Tokyo (`Emulation.setTimezoneOverride`)
  - the delete flow (× → confirmation → "Chat deleted.", the nav balance unchanged, the
    My Profile "Deleted chats" line)
  - phone width (the × visible and dates shown)

  The screenshots caught one more thing no assertion did: the "Deleted chats" total
  wasn't right-aligned.

- **Loop 6's check (39/39)** had **no proxy calls**:
  - an **in-page contrast audit**: every visible element with its own text (about 600
    across 8 pages, at 1280px and 375px) against its nearest opaque ancestor background,
    none under AA
  - no horizontal scroll at 375px
  - the gold focus ring with its navy halo on keyboard focus
  - where the landing CTA leads when logged out and logged in
  - screenshots of every page, reviewed

  See [Visual design → checking visuals](design.md#checking-visuals).

### Date formatting under Node

The sidebar's `relativeLabel()` is plain JavaScript, so the verify step extracts it (the
text between its `// relativeLabel:start/end` markers) and runs it under Node with
`TZ=America/Los_Angeles`, `TZ=Asia/Tokyo` and `TZ=UTC`. The cases:
- today, just after midnight, just before midnight yesterday
- yesterday, 3 and 6 days ago (weekday), 7 days ago
- earlier this year, last year, and a future time from clock skew
- **the same UTC timestamp near midnight landing on different local days**: 23:30 UTC on
  Sep 28 is "Yesterday" in Los Angeles and UTC, but "08:30" (today) in Tokyo

Loop 5: 11/11 in each zone. Like the browser scripts, it lives in the scratchpad.

## Workflow and commits

Work goes through study → plan → execute plan (on a branch) → rendezvous (merge) →
sync docs. Each change is one conventional commit (`feat:`, `fix:`, `chore:`,
`build:`).
