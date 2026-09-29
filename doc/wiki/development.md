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

`python manage.py test` runs 100 tests (at loop 3):

| File | Tests | Covers |
|---|---|---|
| `config/tests.py` | 5 | the home page; the money helpers (rounding, negatives, conversion) |
| `accounts/tests.py` | 10 | sign-up, log-in and log-out status codes and behavior, including the 400s |
| `catalog/tests.py` | 7 | `/models/` grouping and inactive hiding; dollar↔µ$ in the admin form; the seed command's idempotence |
| `billing/tests.py` | 22 | sign-up credit for every creation path; the ledger invariant; `str()` in dollars; admin top-ups, adjustments and dollar display; append-only 403s; read-only wallets; **My Profile** (usage by chat and reply, totals, pagination, bounded queries, the `/credit/` 301, the nav "My Profile · $X.XX") |
| `llm/tests.py` | 10 | the OpenAI request shape (URL, Bearer key, `max_tokens` 1024, `reasoning_effort`, timeout 120); response parsing; estimated usage; error-status mapping; missing key; provider dispatch; the no-network guard |
| `chat/tests.py` | 46 | cost rounding; titles; `send_message`; every chat status in **form mode and JSON mode** (200/302/400/401/402/404/502/503); JSON `balance` after the charge; history resent; the `/chats/` redirect; sidebar order, ownership and `aria-current`; bubble order; **no costs on chat pages**; picker vs model chip; the out-of-credit composer being disabled; renaming (400/404/405, no reorder); escaping; script included once with the right hooks; no proxy URL or key names in templates; admin dollar display |

### The LLM proxy is never called from tests

- `TEST_RUNNER = "config.test_runner.NoNetworkTestRunner"` patches
  `requests.sessions.Session.request` to raise `RuntimeError("Real HTTP request
  attempted in tests…")` for the whole run. Any accidental real call fails the test.
  `llm/tests.py::NoNetworkGuardTests` checks the guard itself.
- Tests mock at one of two levels:
  - `mock.patch("llm.openai.requests.post")` returns an OpenAI-shaped response. Used
    for the client tests and for the view tests, so the whole stack runs.
  - `mock.patch("llm.complete")` returns an `LLMReply`. Used for the service tests.
- Use `@override_settings(OPENAI_API_KEY="test-key")` in view tests, so they don't
  depend on your `.env`.

### Real proxy checks

Real calls happen only in a manual verification step, outside the test suite. It uses a
script run against a **throwaway test database** (`create_test_db` / `destroy_test_db`)
that follows nav links. Loop 2's check sent two real messages; loop 3's did the same
through the JSON path and checked each response's `balance` against the wallet. It never
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

## Workflow and commits

Work goes through study → plan → execute plan (on a branch) → rendezvous (merge) →
sync docs. Each change is one conventional commit (`feat:`, `fix:`, `chore:`,
`build:`).
