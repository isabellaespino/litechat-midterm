# Chat4All

Chat4All replicates the core functionality of [Litechat](https://litechat.ai): metered,
pay-as-you-go access to LLMs from several providers, for people who won't pay for a
subscription.

Pay-as-you-go AI chat for people who don't want a subscription. Each user has a
prepaid US dollar balance that admins top up in Django admin.
Users pick a model from OpenAI, Anthropic or Google, and each reply is charged by
the tokens it uses. Built with Django, SQLite and server-rendered templates.

> **Status: loop 8.** Chat works end to end with all three models: GPT-5.6 Luna
> (OpenAI), Claude Haiku (Anthropic) and Gemini Flash (Google). It uses a chatbot-style
> layout, and each reply is charged from its token usage at that model's price. Usage
> and costs are shown on **My Profile**, which also holds an optional **Global System
> Prompt**. Replies render Markdown safely, chats can be deleted, and the sidebar shows
> each chat's date. The app has a navy-and-gold design and a landing page with a price
> snapshot. New chats are named automatically, and My Profile holds Memories, which
> each chat can switch on or off.

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

- **The landing page** (`/`) explains how Chat4All works and shows a **price snapshot**:
  for each active model, its price and an **estimate** of how many messages $2.00 buys.
  The estimate assumes a message of about 500 input tokens and a 300-token reply in a
  new chat, and uses the same rounding as real charges. Longer chats cost more per reply.
- **Sign up** from the nav bar or the landing page's **Get started**. Every new account
  starts with **$2.00** of credit.
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
  - A new chat starts with the first line of your message as its title. A moment
    after the first reply, it gets a short **automatic title** from the same model.
    That's free: it costs you nothing and never appears in your usage. Renaming always
    wins, and without JavaScript the first line stays as the title.
  - **Rename** a chat from the link next to its title.
  - **Delete** a chat with the **×** on its sidebar row (or **Delete** next to its
    title), then confirm. The chat and its messages are gone for good. What its replies
    cost stays on My Profile under "Deleted chats", and nothing is refunded.
  - The sidebar shows each chat's **last activity** under its title ("14:05",
    "Yesterday", "Mon", "Sep 3", …) in your own time zone. Without JavaScript it shows
    the date in UTC.
  - Model replies render **Markdown**: bold, lists, code blocks and tables. For safety,
    raw HTML is shown as text, images are never loaded (they appear as links), and only
    `http`, `https` and `mailto` links are allowed. Your own messages are shown exactly
    as typed.
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
  - your **Memories**: up to 10 short notes about you (200 characters each), e.g. "I'm
    a student" or "keep answers short". They're sent with the Global System Prompt to
    every model in every chat, so they also count toward input tokens. My Profile shows
    an estimate of what your prompt and memories add to each message. Delete a memory
    any time; it's removed at once.
  - Once you have a memory, an **Include memories** switch appears next to the message
    box. It's on for new chats and saved per chat. Change it any time; it applies from
    the next message you send. When it's off, your memories aren't sent but your Global
    System Prompt still is. It's a normal form control, so it works without JavaScript.
    Automatic titles never include memories or the prompt.

  Each reply is charged its actual cost. When your balance reaches $0.00 or less,
  sending is blocked until an admin tops you up. The last reply can take the balance
  slightly below zero. The old `/credit/` address redirects to `/profile/`.
- **Admin** (staff only) is at `/admin/`:
  - *Credit transactions → Add* tops up a user. Enter the amount in dollars. The
    ledger is append-only: use an *adjustment* (which may be negative) to correct a
    mistake.
  - *LLM models* edits the catalog. Prices are entered in dollars per 1M tokens.
  - *Wallets* and each user's page show current balances (read-only). Each user's page
    also shows their Global System Prompt and Memories (read-only).
  - *Title generations (app cost)* lists every automatic title call with its tokens,
    status and cost, and a total for the rows shown. The app pays for these, so they
    never appear in a user's ledger.

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
