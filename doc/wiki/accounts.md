# Accounts and navigation

## Accounts (`accounts/`)

Accounts use Django's built-in `auth.User`. There's no custom user model. Per-user
preferences live in **`accounts.UserSettings`**, a one-to-one to the user (related name
`chat_settings`) created on first use by `accounts.services.get_settings()`. Today it
holds one preference, the **Global System Prompt**; see
[billing → Global System Prompt](billing.md#global-system-prompt).

- **Sign-up** (`SignUpView`, `/accounts/signup/`): a `UserCreationForm` with username,
  password and confirmation, plus Django's password validators. When valid, it creates
  the user, logs them in and redirects home. The page shows the sign-up credit amount,
  read from settings.
- **Log-in** (`LoginView`, a subclass of Django's): `redirect_authenticated_user = True`.
  Bad credentials return **400**.
- **Log-out** (Django `LogoutView`): POST only, as Django 5 requires. The nav shows it as
  a button inside a form with a CSRF token.
- Logged-in users who open sign-up or log-in are redirected home.

## Navigation (`templates/base.html`)

Every page is reachable from the nav bar or from a link on another page:

| Who | Nav links |
|---|---|
| Everyone | Litechat (brand, links home), Home, Models |
| Logged in | **Chats** (→ `/chats/`, which opens the latest chat), **My Profile · $X.XX** (→ `/profile/`; the balance updates after each reply), "Hi, username", Log out |
| Logged out | Log in, Sign up |
| Staff | Admin |

Other links:
- **Home page:** Start a chat (logged in) or Sign up (logged out), plus Browse models.
- **Chat sidebar:** **+ New chat** and every chat. On phones it's behind a "Chats"
  toggle.
- **My Profile:** links to each chat and to New chat.
- **`/models/`:** Start a chat on chat-enabled models.
- **Sign-up and log-in pages:** link to each other.

Styling is inline CSS in `base.html`. The only JavaScript is the chat pages' inline
enhancement script, and every page works without it.

## HTTP status codes

| Situation | Status |
|---|---|
| Successful GET | 200 |
| Successful form POST (sign-up, log-in, log-out, new chat, send, rename) | 302 redirect |
| Successful fetch/JSON send from the chat script | **200** JSON |
| Invalid form in our views (sign-up, log-in, new chat, send, rename) | **400**, re-rendered with errors (or JSON) |
| Sending with a balance of $0 or less | **402** |
| Proxy failure while sending | **502**, or **503** for rate limits, timeouts and outages (see [chat](chat.md#two-response-modes-form-posts-and-fetch-json)) |
| Logged-in-only page, anonymous visitor | 302 to `/accounts/login/?next=…` |
| Chat JSON request, logged out | **401** JSON (fetch would silently follow a redirect) |
| `/chats/` | 302 to the latest chat, or New chat |
| `/credit/` (moved) | **301** to `/profile/` |
| GET on the rename endpoint or the system prompt endpoint | 405 |
| Saving a system prompt over 4,000 characters | **400**, My Profile re-rendered with the error |
| Another user's chat, unknown chat, unknown URL | 404 |
| Invalid **Django admin** form | 200. See [Product decisions → Departures from the plan](product-decisions.md#departures-from-the-plan). |
| Changing or deleting a ledger entry in admin; adding, changing or deleting a conversation in admin | 403 |

Rule for new views: when a form is invalid, render with `status=400` (override
`form_invalid` on class-based views, or pass `status=400` to `render`).
