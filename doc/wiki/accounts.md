# Accounts and navigation

## Accounts (`accounts/`)

Accounts use Django's built-in `auth.User`. There's no custom user model.

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

Every page is reachable from the nav bar:

| Who | Links |
|---|---|
| Everyone | Litechat (brand, links home), Home, Models |
| Logged out | Log in, Sign up |
| Logged in | Available credit: $X.XX (→ `/credit/`), "Hi, username", Log out |
| Staff | Admin |

The home page also links to Sign up (when logged out) and to Browse models. The sign-up
and log-in pages link to each other. Styling is inline CSS in `base.html`. There's no
JavaScript.

## HTTP status codes

| Situation | Status |
|---|---|
| Successful GET | 200 |
| Successful form POST (sign-up, log-in, log-out) | 302 redirect |
| Invalid sign-up or log-in form | **400**, re-rendered with errors |
| Logged-in-only page, anonymous visitor | 302 to `/accounts/login/?next=…` |
| Unknown URL | 404 |
| Invalid **Django admin** form | 200. See [Product decisions → Departures from the plan](product-decisions.md#departures-from-the-plan). |
| Changing or deleting a ledger entry in admin | 403 |

Rule for new views: when a form is invalid, render with `status=400` (override
`form_invalid` on class-based views).
