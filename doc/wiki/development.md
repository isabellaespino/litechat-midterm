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

`python manage.py test` runs 70 tests (at loop 2):

| File | Tests | Covers |
|---|---|---|
| `config/tests.py` | 5 | the home page; the money helpers (rounding, negatives, conversion) |
| `accounts/tests.py` | 10 | sign-up, log-in and log-out status codes and behavior, including the 400s |
| `catalog/tests.py` | 7 | `/models/` grouping and inactive hiding; dollar↔µ$ in the admin form; the seed command's idempotence |
| `billing/tests.py` | 17 | sign-up credit for every creation path; the ledger invariant; `str()` in dollars; admin top-ups, adjustments and dollar display; append-only 403s; read-only wallets; the `/credit/` page |
| `llm/tests.py` | 10 | the OpenAI request shape (URL, Bearer key, `max_tokens` 1024, `reasoning_effort`, timeout 120); response parsing; estimated usage; error-status mapping; missing key; provider dispatch; the no-network guard |
| `chat/tests.py` | 21 | cost rounding; titles; `send_message` (charges, failure saves nothing, history order, negative balance); every chat view status (302/400/402/404/502/503); history resent; list ordering and ownership; cut-off and escaping; the Coming soon badge; admin dollar display |

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
that follows nav links. Loop 2's check sent two real messages to GPT-5.6 Luna and
confirmed the costs, the resent history and the ledger. It never writes to
`db.sqlite3`.

## Workflow and commits

Work goes through study → plan → execute plan (on a branch) → rendezvous (merge) →
sync docs. Each change is one conventional commit (`feat:`, `fix:`, `chore:`,
`build:`).
