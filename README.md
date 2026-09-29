# Litechat

Pay-as-you-go AI chat for people who don't want a subscription. Each user has a
prepaid US dollar balance that admins top up in Django admin.
Users pick a model from OpenAI, Anthropic or Google, and each reply is charged by
the tokens it uses. Built with Django, SQLite and server-rendered templates.

> **Status: loop 4.** Chat works end to end with all three models: GPT-5.6 Luna
> (OpenAI), Claude Haiku (Anthropic) and Gemini Flash (Google). It uses a chatbot-style
> layout, and each reply is charged from its token usage at that model's price. Usage
> and costs are shown on **My Profile**, which also holds an optional **Global System
> Prompt**.

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
| `OPENAI_API_KEY` | yes, for GPT-5.6 Luna | Your OpenAI key for the LLM proxy at https://proxy.litechat.ai. |
| `ANTHROPIC_API_KEY` | yes, for Claude Haiku | Your Anthropic key for the same proxy. |
| `GOOGLE_API_KEY` | yes, for Gemini Flash | Your Google key for the same proxy. |

Each key is only needed for its own model. If one is missing, sending to that model
shows "unavailable" (503) and charges nothing, and the other models keep working.

`.env` holds secrets and is ignored by git. Never commit it.

## Using the app

- **Sign up** from the nav bar. Every new account starts with **$2.00** of credit.
- **Models** lists the available models, grouped by provider, with their prices per
  1M tokens.
- **Chats** opens your most recent chat (or a new one). The sidebar lists your chats,
  newest first, with a **+ New chat** button.
  - In a new chat, pick a model next to the message box: Claude Haiku, Gemini Flash or
    GPT-5.6 Luna. An existing chat keeps its model, shown as a label.
  - Press **Enter to send**, and **Shift+Enter** for a new line. Your message appears
    right away with a "thinking" indicator, and the whole reply replaces it without
    reloading the page. Replies can take a few seconds (the proxy is allowed up to 120
    seconds).
  - **Rename** a chat from the link next to its title.
  - Replies are capped at 1,024 output tokens. Your whole conversation is resent with
    each message, so long chats cost more per reply.
  - The chat pages don't show costs. If the model fails to answer, your draft is put
    back in the box and nothing is charged.
  - The chat pages also work with JavaScript turned off: sending then reloads the page.
- **My Profile · $X.XX** (in the nav bar when logged in) shows your available credit,
  which updates after every reply. The profile page shows:
  - your available credit, and totals (credit added, spent, balance)
  - what each chat cost, expandable to the cost and tokens of each reply
  - the credit you've been given (sign-up credit, top-ups)
  - your **Global System Prompt**: one optional instruction (up to 4,000 characters)
    that's sent as the system prompt in every chat, with every model. For example,
    "Always reply in French." Leave it empty for none. It's resent with every message,
    so it counts toward each reply's input tokens.

  Each reply is charged its actual cost. When your balance reaches $0.00 or less,
  sending is blocked until an admin tops you up. The last reply can take the balance
  slightly below zero. The old `/credit/` address redirects to `/profile/`.
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

Tests use a throwaway test database. They never touch `db.sqlite3`. They also never
call the LLM proxy: the proxy is mocked, and the test runner
(`config/test_runner.py`) makes any real HTTP request fail.

## Notes

- Money is stored as whole **micro-dollars** (1 USD = 1,000,000), because a single
  reply costs a fraction of a cent. Balances are displayed rounded down to the cent.
- Balances change only through ledger entries (`billing/services.py`), so a user's
  balance always equals the sum of their transactions.
- LLM requests are made only from the backend (`llm/`). The API key never reaches the
  browser.
- Design decisions live in `doc/study/`, step-by-step plans in `doc/plan/`, and the
  living manual in `doc/wiki/`.
