# Development

## Setup

Follow `README.md`. In short:

1. Create and activate a virtualenv (`python3 -m venv .venv`).
2. `pip install -r requirements.txt`.
3. `cp .env.example .env`, then set `DJANGO_SECRET_KEY`.
4. `python manage.py migrate`.
5. `python manage.py seed`.
6. `python manage.py createsuperuser`.
7. `python manage.py runserver 0.0.0.0:8000`.

These steps were verified on a fresh clone at the loop 1 rendezvous.

## Rules that constrain the code (from `CLAUDE.md`)

- **Secrets** live only in `.env`, which is git-ignored. Never print its contents.
  Add every new variable to `.env.example` with no value.
- **LLM calls** happen from the backend only, never from browser code.
- **Dependencies:** declare every one in `requirements.txt`, and justify it in a study
  before adding it.
- **Database:** never reset or reseed `db.sqlite3`. `migrate` and `seed` are additive
  and safe. Verify behavior with `python manage.py test`, which uses a throwaway test
  database.
- **Navigation:** every page must be linked from the nav or another page.
- **Server:** always bind to `0.0.0.0:8000`.

## Tests

`python manage.py test` runs 37 tests (at loop 1):

| File | Covers |
|---|---|
| `config/tests.py` | the home page; the money helpers (rounding, negatives, conversion) |
| `accounts/tests.py` | sign-up, log-in and log-out status codes and behavior, including the 400s |
| `catalog/tests.py` | `/models/` grouping and inactive hiding; dollar↔µ$ in the admin form; the seed command's idempotence |
| `billing/tests.py` | sign-up credit for every creation path; the ledger invariant; admin top-ups and adjustments; append-only 403s; read-only wallets; the `/credit/` page |

The LLM proxy isn't called anywhere yet. From loop 2, tests will mock it and must never
make live calls.

## Workflow and commits

Work goes through study → plan → execute plan (on a branch) → rendezvous (merge) →
sync docs. Each change is one conventional commit (`feat:`, `fix:`, `chore:`,
`build:`).
