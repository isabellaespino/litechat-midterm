# Architecture

## Stack

Django 5.2 LTS, SQLite, Django's built-in auth and admin, and server-rendered templates.
There's no JavaScript and no frontend framework. The dependencies are `Django` and
`python-dotenv` (see `requirements.txt`). The reasons behind the stack are in the study,
§3.

## Layout

```
config/        project package: settings, root URLs, home view, money helpers
  money.py       micro-dollar conversion and formatting (shared by all apps)
  views.py       home page
  tests.py       home page and money helper tests
accounts/      sign-up form and view; log-in view that returns 400 on bad credentials
catalog/       LLMModel, its admin, the /models/ page, the `seed` command,
               and the `money` template filters (templatetags/money.py)
billing/       Wallet, CreditTransaction, services.py (the only balance writer),
               the sign-up credit signal, the nav context processor, the /credit/ page, admin
templates/     base.html (nav + CSS), home.html, registration/, catalog/, billing/
doc/           study/, plan/, wiki/ (this manual)
```

Dependencies between apps: `billing` and `catalog` both import `config.money`. Every
template that shows money loads the `money` filter library from `catalog`. `accounts`
reads `settings.SIGNUP_CREDIT_MICROS` for the sign-up page text. It doesn't import
`billing`, because the credit itself is granted by a signal.

## Settings (`config/settings.py`)

| Setting | Source / value |
|---|---|
| `SECRET_KEY` | `DJANGO_SECRET_KEY` from `.env`. Startup fails with `ImproperlyConfigured` if it's missing. |
| `DEBUG` | `DJANGO_DEBUG`: on if `1`/`true`/`yes`, otherwise off |
| `ALLOWED_HOSTS` | `DJANGO_ALLOWED_HOSTS`, comma-separated. Defaults to `localhost,127.0.0.1,0.0.0.0` |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY` | From `.env`. Loaded, but not used until loop 2. Backend only. |
| `SIGNUP_CREDIT_MICROS` | `2_000_000` ($2.00) |
| `MAX_OUTPUT_TOKENS` | `1024`. Defined for loop 2. Nothing uses it yet. |
| `LOGIN_URL` / `LOGIN_REDIRECT_URL` / `LOGOUT_REDIRECT_URL` | `login` / `home` / `home` |
| Context processors | Django defaults, plus `billing.context_processors.available_credit` |

`.env` is loaded with `load_dotenv(BASE_DIR / ".env")`. `.env.example` lists every
variable with no values.

## URL map

| Path | Name | View | Access |
|---|---|---|---|
| `/` | `home` | `config.views.home` | anyone |
| `/models/` | `model_list` | `catalog.views.model_list` | anyone |
| `/accounts/signup/` | `signup` | `accounts.views.SignUpView` | logged out (logged-in users are redirected home) |
| `/accounts/login/` | `login` | `accounts.views.LoginView` | logged out (logged-in users are redirected home) |
| `/accounts/logout/` | `logout` | Django `LogoutView` | POST only |
| `/credit/` | `credit` | `billing.views.credit` | logged in |
| `/admin/` | `admin:*` | Django admin | staff |

## Request flow for a logged-in page

1. Middleware authenticates the session.
2. The `available_credit` context processor calls `billing.services.get_wallet(user)`,
   which runs `get_or_create`, and adds `available_credit_micros` to every template.
3. `base.html` renders the nav, including "Available credit: $X.XX", through the
   `dollars` filter.
