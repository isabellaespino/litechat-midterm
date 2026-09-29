# Plan: Loop 1: foundation (accounts, model catalog, credit ledger)

- **Date:** 2026-09-29 (Unix 1790659225)
- **Source study:** `doc/study/1790657879-litechat-clone-feasibility.md`
- **Branch:** `loop1-foundation`, off `main`. Don't merge during execute. Wait for the
  rendezvous command.
- **Scope:** Django project setup, sign-up/log-in/log-out, the model catalog, the credit
  ledger with sign-up credit and admin top-ups, the seed command, navigation, README,
  `requirements.txt`, `.gitignore` and `.env.example`.
- **Not in this loop:** no LLM or proxy calls, no chats or messages, no charging. The
  proxy keys go in `.env.example` but aren't used yet.

## Fixed values (from study §10)

| Setting | Value |
|---|---|
| Money unit | whole micro-dollars (`1 USD = 1_000_000`) |
| Sign-up credit | `SIGNUP_CREDIT_MICROS = 2_000_000` ($2.00) |
| Output cap (defined now, used in loop 2) | `MAX_OUTPUT_TOKENS = 1024` |
| Invalid form status | 400 |

| Provider | `api_model_id` | Display name | Tier | Input µ$/1M tok | Output µ$/1M tok |
|---|---|---|---|---|---|
| anthropic | `claude-haiku-4-5-20251001` | Claude Haiku | value | 1_000_000 | 5_000_000 |
| openai | `gpt-5.6-luna` | GPT-5.6 Luna | value | 500_000 | 2_000_000 |
| google | `gemini-3.8-flash` | Gemini Flash | value | 300_000 | 2_500_000 |

## Layout

```
config/          # Django project (settings, root urls, wsgi/asgi)
accounts/        # sign-up view and form; uses built-in auth views for log-in/log-out
catalog/         # LLMModel, admin, public model list, `seed` command
billing/         # Wallet, CreditTransaction, sign-up credit, admin top-ups, credit page, money filters
templates/       # base.html (nav), home, registration/*, catalog/*, billing/*
```

---

## Step 0: Branch

- [ ] `git switch -c loop1-foundation` from an up-to-date `main`.

## Step 1: `chore: scaffold Django project`

- [ ] Create `requirements.txt` pinning `Django>=5.2,<5.3` (LTS) and `python-dotenv`.
      `requests` isn't added until loop 2, when the proxy is first called.
- [ ] Create a local `.venv` (not committed) and install the requirements.
- [ ] `django-admin startproject config .`
- [ ] `.gitignore`: `.venv/`, `.env`, `db.sqlite3`, `db.sqlite3-journal`, `__pycache__/`,
      `*.pyc`, `.DS_Store`, `staticfiles/`.
- [ ] `.env.example`, with names only and no values: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`,
      `DJANGO_ALLOWED_HOSTS`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`.
- [ ] `config/settings.py`:
  - [ ] `load_dotenv(BASE_DIR / ".env")`.
  - [ ] Read `SECRET_KEY`, `DEBUG` and `ALLOWED_HOSTS` from the environment. Fail with a
        clear error if `DJANGO_SECRET_KEY` is missing.
  - [ ] Read the three proxy keys into settings (not used yet). Never log them.
  - [ ] `TEMPLATES["DIRS"] = [BASE_DIR / "templates"]`.
  - [ ] `LOGIN_URL = "login"`, `LOGIN_REDIRECT_URL = "home"`,
        `LOGOUT_REDIRECT_URL = "home"`.
  - [ ] `SIGNUP_CREDIT_MICROS = 2_000_000` and `MAX_OUTPUT_TOKENS = 1024`.
- [ ] Create a local `.env` from `.env.example` for development. Don't print its contents.
- [ ] Verify: `python manage.py check` passes, and `git status` doesn't show `.env`,
      `.venv` or `db.sqlite3`.
- [ ] Commit.

## Step 2: `feat: add base layout, home page and navigation`

- [ ] `templates/base.html`: page title block, messages block and a nav bar.
  - Always visible: **Home**, **Models**.
  - Logged out: **Log in**, **Sign up**.
  - Logged in: **Available credit: $X.XX** (links to the credit page),
    `Hi, <username>`, and **Log out**, as a POST form button with a CSRF token, because
    Django 5 logout requires POST.
  - Staff only: **Admin** (`/admin/`).
- [ ] A `home` view at `/` that renders with 200. It gives a short explanation of the
      product, with calls to action to Sign up or Browse models.
- [ ] Minimal inline CSS in `base.html`. No framework and no JS.
- [ ] Links to pages that don't exist yet (Models, Credit, Sign up) are added in the
      steps that create those pages, so the nav never links to a 404.
- [ ] Test: `GET /` returns 200 for both anonymous and logged-in users.
- [ ] Commit.

## Step 3: `feat: add sign-up, log-in and log-out`

- [ ] `accounts` app. `SignUpForm` extends `UserCreationForm` (username, password1,
      password2).
- [ ] `SignUpView` at `/accounts/signup/`: GET returns 200. A valid POST creates the
      user, logs them in and redirects (302) to `home`. An invalid POST re-renders
      with **400**.
- [ ] Log-in at `/accounts/login/`: subclass `LoginView` so `form_invalid` renders
      with **400**.
- [ ] Log-out at `/accounts/logout/`: the built-in `LogoutView` (POST, then 302).
- [ ] Templates: `registration/login.html` and `registration/signup.html`, each
      linking to the other.
- [ ] Redirect logged-in users away from the sign-up and log-in pages (302 to
      `home`).
- [ ] Nav: add Log in, Sign up and Log out.
- [ ] Tests:
  - [ ] Sign-up GET returns 200. A valid POST returns 302, creates the user and logs
        them in. An invalid POST (mismatched passwords, duplicate username) returns 400.
  - [ ] Log-in GET returns 200. Valid credentials return 302. Bad credentials return
        400.
  - [ ] Log-out via POST returns 302, and the user is anonymous afterwards.
- [ ] Commit.

## Step 4: `feat: add model catalog`

- [ ] `catalog` app, model `LLMModel`:
  - `provider` (choices `openai`/`anthropic`/`google`, with display labels
    OpenAI/Anthropic/Google)
  - `api_model_id` (unique)
  - `display_name`
  - `description` (short text)
  - `tier` (choices `value`/`standard`/`premium`)
  - `input_price_micros_per_mtok` and `output_price_micros_per_mtok`
    (`PositiveBigIntegerField`)
  - `is_active` (default `True`)
  - `sort_order`
  - timestamps
  - `Meta.ordering = ["provider", "sort_order", "display_name"]`
  - `__str__` returns "Provider · Display name"
- [ ] Admin:
  - [ ] `list_display` shows provider, display name, tier, prices (as $/1M) and
        active.
  - [ ] `list_filter` on provider, tier and active. `search_fields` on names and ids.
  - [ ] Prices are entered in **dollars per 1M tokens** through a `ModelForm` with
        `DecimalField`s converted to micro-dollars on save, so admins never type µ$.
- [ ] Public page `/models/` (200) lists active models **grouped by provider**. Each
      shows the display name, tier badge, description and "$in / $out per 1M tokens".
- [ ] Nav: add Models.
- [ ] Tests:
  - [ ] `/models/` returns 200, groups by provider and hides inactive models.
  - [ ] The admin form round-trips a dollar price to micro-dollars exactly (e.g. `0.30`
        becomes `300000`).
- [ ] Commit.

## Step 5: `feat: add credit ledger with sign-up credit and admin top-ups`

- [ ] `billing` app:
  - [ ] `Wallet` fields: `user` (a one-to-one field that is the primary key),
        `balance_micros` (`BigIntegerField`, signed, default 0), `updated_at`.
  - [ ] `CreditTransaction` fields:
    - `user` (FK)
    - `amount_micros` (`BigIntegerField`, signed)
    - `kind` (choices `signup`/`topup`/`charge`/`adjustment`)
    - `note`
    - `created_by` (FK to User, nullable)
    - `created_at`
    - `Meta.ordering = ["-created_at"]`

    `charge` is defined now but only used from loop 2.
- [ ] `billing/services.py`: `post_transaction(user, amount_micros, kind, note="",
      created_by=None)`. Inside `transaction.atomic()` it creates the ledger row and
      runs `Wallet.objects.filter(user=user).update(balance_micros=F(...) + amount)`.
      It's the only code path that changes a balance.
- [ ] A sign-up credit signal: `post_save` on `User` with `created=True` runs
      `get_or_create`s the `Wallet`, then
      `post_transaction(user, SIGNUP_CREDIT_MICROS, "signup", "Sign-up credit")`. The
      signal is connected in `BillingConfig.ready()`. It covers users from the sign-up
      form, the admin and `createsuperuser`.
- [ ] Money formatting (`billing/templatetags/money.py`):
  - [ ] `dollars`: two decimal places, rounded **down** to the cent, with the sign
        before the `$`: `1_990_000` → `$1.99`, `1_999_999` → `$1.99`, `-10_000` →
        `-$0.01`, `-1` → `-$0.01`.
  - [ ] `dollars_precise`: up to 6 decimal places, for ledger rows and prices.
  - [ ] A context processor exposes `available_credit_micros` for the logged-in user
        to the nav.
- [ ] Admin:
  - [ ] `CreditTransaction` admin, add-only. The add form has `user`, `amount` in
        **dollars** (`DecimalField`, 6 decimal places, non-zero), `kind` (limited to
        `topup`/`adjustment`) and `note`. `save_model` sets `created_by =
        request.user` and calls `post_transaction`. `has_change_permission` and
        `has_delete_permission` return `False`, so the ledger is append-only.
        `list_display`/`list_filter` show user, kind, amount ($), created by and date.
  - [ ] `Wallet` admin is read-only (balance in $), with a link to that user's
        transactions. No add, change or delete.
  - [ ] Add an inline showing the wallet balance on the `User` admin (read-only).
- [ ] Credit page `/credit/` (login required, 200) shows **Available credit** and
      the user's ledger (date, kind, note, amount).
- [ ] Nav: add "Available credit: $X.XX", linking to `/credit/`.
- [ ] Tests:
  - [ ] A new user (via the sign-up view and via `User.objects.create_user`) has a
        wallet with `2_000_000` and exactly one `signup` transaction.
  - [ ] An admin top-up via the admin add view (logged in as staff) adds the ledger
        row, increases the balance, and records `created_by`.
  - [ ] The ledger can't be changed or deleted in admin (403 on change and delete
        URLs).
  - [ ] Every `dollars` filter case listed above.
  - [ ] `/credit/` returns 200 for a logged-in user and redirects anonymous users
        (302) to log-in. It shows only that user's transactions.
  - [ ] Invariant: `wallet.balance_micros == sum(amount_micros)` after a sequence of
        transactions.
- [ ] Commit.

## Step 6: `feat: add seed command for the model catalog`

- [ ] `catalog/management/commands/seed.py` runs `get_or_create` by `api_model_id`
      for the three models in the table above (tier `value`, with short descriptions).
      It prints `created` or `exists` per model. It never updates or deletes existing
      rows, so admin price edits survive re-runs.
- [ ] Tests (test DB): the first run creates 3 rows with exact µ$ prices. A second run
      creates 0 rows. An edited price survives a re-run.
- [ ] Commit.

## Step 7: `chore: write README setup guide`

- [ ] `README.md` covers:
  - [ ] What the app is (one paragraph).
  - [ ] Requirements (Python 3.12+).
  - [ ] Setup from a fresh clone:
    1. `python3 -m venv .venv` and activate it.
    2. `pip install -r requirements.txt`.
    3. `cp .env.example .env` and fill in the values. Include a command that generates
       a secret key.
    4. `python manage.py migrate`.
    5. `python manage.py seed`.
    6. `python manage.py createsuperuser`.
    7. `python manage.py runserver 0.0.0.0:8000`.
  - [ ] Using it: sign up (you receive $2.00), browse models, and use admin top-ups at
        `/admin/`.
  - [ ] Running tests: `python manage.py test`.
  - [ ] Notes: amounts are stored as micro-dollars. Chat arrives in loop 2.
- [ ] Commit.

## Step 8: Verify the whole loop (no commit)

- [ ] `python manage.py check` and `python manage.py makemigrations --check --dry-run`
      are both clean.
- [ ] `python manage.py test` all pass. Only Django's throwaway test DB is used, and
      `db.sqlite3` is never reset or reseeded.
- [ ] Smoke test: `python manage.py migrate` and `seed` on the dev DB (both additive),
      then `runserver 0.0.0.0:8000`. Click through Home → Models → Sign up → Credit
      ($2.00) → Log out → Log in → Admin top-up → Credit updated, using only nav links.
      Check that every page returns 200.
- [ ] `git status` is clean. `git log main..loop1-foundation --oneline` shows the seven
      commits (steps 1–7). Stop and wait for **rendezvous**.

## Done when

- A fresh clone can be set up from README and `requirements.txt` alone.
- Sign-up grants $2.00 via the ledger. Admins can top up in dollars. Balances show as
  "Available credit $X.XX".
- The catalog holds the three seeded value-tier models at the agreed prices, is
  editable in admin, and is visible at `/models/`.
- Every page is reachable from the nav. Status codes: 200 on success, 302 on
  redirects, 400 on invalid forms.
- No LLM calls exist anywhere in the codebase.
