# Architecture

## Stack

Django 5.2 LTS, SQLite, Django's built-in auth and admin, and server-rendered templates.
There's no frontend framework. The chat pages have one small inline script that
progressively enhances their forms (see [chat](chat.md#the-script-progressive-enhancement)),
and everything works without it. The dependencies are `Django`,
`python-dotenv` and `requests` (see `requirements.txt`). The reasons behind the stack
are in the study, §3, and the reasons for each dependency in §7.

## Layout

```
config/        project package: settings, root URLs, home view, money helpers
  money.py       micro-dollar conversion and formatting (shared by all apps)
  test_runner.py NoNetworkTestRunner: fails any real HTTP request during tests
  views.py       home page
  tests.py       home page and money helper tests
accounts/      sign-up form and view; log-in view that returns 400 on bad credentials
catalog/       LLMModel, its admin, the /models/ page, the `seed` command,
               and the `money` template filters (templatetags/money.py)
billing/       Wallet, CreditTransaction, services.py (the only balance writer, plus
               reply_cost_micros), the sign-up credit signal, the nav context
               processor, the My Profile page (/profile/), admin
chat/          Conversation, Message, services.py (send_message), forms, views
               (form + JSON modes, rename), admin
llm/           plain Python package (not a Django app): the backend-only proxy client
  __init__.py    LLMReply, LLMError, complete() which dispatches by provider
  openai.py      the OpenAI Chat Completions adapter
templates/     base.html (nav + all CSS, incl. the chat app layout), home.html,
               registration/, catalog/, billing/profile.html,
               chat/ (layout.html + partials _sidebar, _main, _message, _composer,
               _out_of_credit, _script)
doc/           study/, plan/, wiki/ (this manual)
```

**Dependencies between apps:**
- `chat` depends on `llm` (to get replies), `billing` (to charge) and `catalog` (the
  model).
- `billing.CreditTransaction` has a one-to-one link to `chat.Message`, so billing's
  second migration depends on chat's first.
- `billing.views.profile` reads `chat.Conversation` and `chat.Message` for the usage
  history.
- `billing` and `catalog` both import `config.money`, and every template that shows
  money loads the `money` filters from `catalog`.
- `accounts` doesn't import `billing`, because the sign-up credit is granted by a signal.

## Settings (`config/settings.py`)

| Setting | Source / value |
|---|---|
| `SECRET_KEY` | `DJANGO_SECRET_KEY` from `.env`. Startup fails with `ImproperlyConfigured` if it's missing. |
| `DEBUG` | `DJANGO_DEBUG`: on if `1`/`true`/`yes`, otherwise off |
| `ALLOWED_HOSTS` | `DJANGO_ALLOWED_HOSTS`, comma-separated. Defaults to `localhost,127.0.0.1,0.0.0.0` |
| `OPENAI_API_KEY` | From `.env`, backend only. Required to chat. If it's empty, sending returns 503. |
| `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY` | From `.env`. Loaded, but unused until those providers are enabled. |
| `LLM_PROXY_BASE_URL` | `https://proxy.litechat.ai`. Not a secret, so it isn't in `.env`. |
| `LLM_TIMEOUT_SECONDS` | `120` (study §10 #12: the proxy's response time varies, and a slow reply beats a failed one) |
| `CHAT_PROVIDERS` | `["openai"]`: providers whose models can be picked in chat |
| `CHAT_MESSAGE_MAX_CHARS` | `8000` |
| `MAX_OUTPUT_TOKENS` | `1024`, sent as `max_tokens` on every request |
| `SIGNUP_CREDIT_MICROS` | `2_000_000` ($2.00) |
| `LOGIN_URL` / `LOGIN_REDIRECT_URL` / `LOGOUT_REDIRECT_URL` | `login` / `home` / `home` |
| Context processors | Django defaults, plus `billing.context_processors.available_credit` |
| `TEST_RUNNER` | `config.test_runner.NoNetworkTestRunner` |

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
| `/profile/` | `profile` | `billing.views.profile` (My Profile) | logged in |
| `/credit/` | — | `RedirectView` → **301** to `/profile/` | anyone |
| `/chats/` | `chat_list` | `chat.views.chat_list`: 302 to the latest chat, or to New chat | logged in |
| `/chats/new/` | `chat_new` | `chat.views.chat_new` (GET page, POST starts a chat; form or JSON) | logged in |
| `/chats/<id>/` | `chat_detail` | `chat.views.chat_detail` (GET page, POST sends; form or JSON) | logged in, owner only (404 otherwise) |
| `/chats/<id>/rename/` | `chat_rename` | `chat.views.chat_rename` (POST only) | logged in, owner only |
| `/admin/` | `admin:*` | Django admin | staff |

## Request flow for a logged-in page

1. Middleware authenticates the session.
2. The `available_credit` context processor calls `billing.services.get_wallet(user)`,
   which runs `get_or_create`, and adds `available_credit_micros` to every template.
3. `base.html` renders the nav, including "My Profile ·
   `<span data-nav-balance>$X.XX</span>`", through the `dollars` filter. On chat pages,
   the script rewrites that span from each JSON reply's `balance`.

For what happens when a message is sent, see [Chat → The send flow](chat.md#the-send-flow).
