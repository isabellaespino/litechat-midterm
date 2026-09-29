# Litechat

Pay-as-you-go AI chat for people who don't want a subscription. Each user has a
prepaid US dollar balance ("Available credit") that admins top up in Django admin.
Users pick a model from OpenAI, Anthropic or Google, and each reply is charged by
the tokens it uses. Built with Django, SQLite and server-rendered templates.

> **Status: loop 1.** Accounts, the model catalog and the credit ledger are in place.
> Chatting (and charging for replies) arrives in loop 2.

## Requirements

- Python 3.12 or newer
- No database server: SQLite is built into Python

## Setup from a fresh clone

```sh
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create your .env from the template, then edit it (see below)
cp .env.example .env

# 4. Create the database tables
python manage.py migrate

# 5. Load the model catalog (safe to re-run)
python manage.py seed

# 6. Create an admin account
python manage.py createsuperuser

# 7. Run the server
python manage.py runserver 0.0.0.0:8000
```

Then open http://localhost:8000.

### Filling in `.env`

| Variable | Required | Value |
|---|---|---|
| `DJANGO_SECRET_KEY` | yes | A long random string. Generate one with `python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"` |
| `DJANGO_DEBUG` | no | `true` for local development. Leave empty (off) in production. |
| `DJANGO_ALLOWED_HOSTS` | no | Comma-separated host names. Defaults to `localhost,127.0.0.1,0.0.0.0`. |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY` | from loop 2 | Your keys for the LLM proxy at https://proxy.litechat.ai. Not used yet. |

`.env` holds secrets and is ignored by git. Never commit it.

## Using the app

- **Sign up** from the nav bar. Every new account starts with **$2.00** of credit.
- **Models** lists the available models, grouped by provider, with their prices per
  1M tokens.
- **Available credit** (in the nav bar when logged in) shows your balance and history.
- **Admin** (staff only) is at `/admin/`:
  - *Credit transactions → Add* tops up a user. Enter the amount in dollars. The
    ledger is append-only: use an *adjustment* (which may be negative) to correct a
    mistake.
  - *LLM models* edits the catalog. Prices are entered in dollars per 1M tokens.
  - *Wallets* and each user's page show current balances (read-only).

## Running the tests

```sh
python manage.py test
```

Tests use a throwaway test database. They never touch `db.sqlite3`.

## Notes

- Money is stored as whole **micro-dollars** (1 USD = 1,000,000), because a single
  reply costs a fraction of a cent. Balances are displayed rounded down to the cent.
- Balances change only through ledger entries (`billing/services.py`), so a user's
  balance always equals the sum of their transactions.
- Design decisions live in `doc/study/`, and step-by-step plans in `doc/plan/`.
