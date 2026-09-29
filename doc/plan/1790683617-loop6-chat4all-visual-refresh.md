# Plan: Loop 6: Chat4All visual refresh (rename, navy and gold, hero landing, auth cards)

- **Date:** 2026-09-29 (Unix 1790683617)
- **Source:** the user's decided list. There's **no study**: these are visual changes with
  no tradeoffs to weigh.
- **Branch:** `loop6-visual-refresh`, off `main`. Don't merge during execute. Wait for the
  rendezvous command.
- **Scope, visual only:**
  1. Rename the app **Litechat → Chat4All** everywhere users see it.
  2. A **navy blue** color scheme across the whole app, with a **gold** accent, keeping
     readable contrast.
  3. A **hero-themed landing page** at `/`.
  4. **Log-in and sign-up restyled** as centered cards.
- **Hard constraints:**
  - No new features beyond the landing page content listed, and **no new dependencies**.
    The emblem is inline SVG, and all CSS stays inline in `base.html`.
  - **No changes to billing or chat behavior:** views, services, the ledger, the proxy
    client, status codes, the JSON contract and the script's behavior stay the same. The
    only script change is the title string in the rename.
  - **The hero theme stays on the landing page.** Every other page only gets the new
    colors.
  - Providers are named as **text**, with no logos, and the emblem is original, with no
    real superhero symbols.
  - Past studies and plans in `doc/study/` and `doc/plan/` are **not edited**. The wiki is
    the living manual, so the next **sync docs** renames it there.
- **No migrations** are expected (no model changes).

## 1. What gets renamed, and what doesn't

| Where | Change |
|---|---|
| `templates/base.html` `<title>` | `{% block title %}Chat4All{% endblock %} · Chat4All` |
| `templates/base.html` nav brand | `Chat4All` |
| `templates/chat/_script.html` | `document.title = … + " · Chat4All"` after a new chat's first reply |
| Home page copy | the new landing page (§3) |
| Django admin | `admin.site.site_header = "Chat4All administration"`, `site_title = "Chat4All admin"`, `index_title = "Site administration"` (set in `config/urls.py`). It currently says "Django administration". |
| `README.md` | the title becomes `# Chat4All`, with a line saying it **replicates the core functionality of [Litechat](https://litechat.ai)** |
| **Not renamed** | `LLM_PROXY_BASE_URL = "https://proxy.litechat.ai"` and its README and test mentions. That's the real LLM proxy's address, not our brand. The repo folder name. Past `doc/study` and `doc/plan` files. |

## 2. Palette (navy and gold), with contrast checked now

Defined once as CSS custom properties in `base.html`'s `:root`, and used everywhere.
There are no hard-coded colors in page rules.

| Token | Value | Used for |
|---|---|---|
| `--navy-900` | `#0b1f3a` | nav bar, landing hero, primary text |
| `--navy-800` | `#12305a` | chat sidebar background |
| `--navy-700` | `#1c3f73` | links, the user's chat bubbles, headings accents |
| `--navy-100` | `#e6ecf5` | soft panels, the current-chat highlight on light backgrounds, table headers |
| `--page` | `#f5f7fb` | page background |
| `--card` | `#ffffff` | cards, the model's bubbles, the composer |
| `--text` | `#0b1f3a` | body text on light backgrounds |
| `--muted` | `#4a5a73` | secondary text on light backgrounds |
| `--on-navy` | `#ffffff` | text on navy |
| `--muted-on-navy` | `#b9c6dc` | secondary text on navy (sidebar dates, nav "Hi, user") |
| `--gold` | `#f2b705` | **accent:** primary buttons (with navy text), the current chat marker, the nav balance, focus rings, badges, the emblem |
| `--gold-soft` | `#fde9a8` | highlight backgrounds (e.g. the tier badge) |
| `--error` | `#b3261e` | errors, the delete button (unchanged hue) |

**WCAG contrast of every text/background pair used (computed for this plan):**

| Text | Background | Ratio |
|---|---|---|
| `--text` | `--page` / `--card` | 15.4 / 16.5 |
| `--muted` | `--page` / `--card` | 6.5 / 7.0 |
| `--navy-700` (links) | `--card` / `--page` | 10.5 / 9.8 |
| `--on-navy` | `--navy-900` / `--navy-800` / `--navy-700` | 16.5 / 13.2 / 10.5 |
| `--muted-on-navy` | `--navy-900` / `--navy-800` | 9.6 / 7.6 |
| `--gold` | `--navy-900` / `--navy-800` | 9.1 / 7.2 |
| `--navy-900` (button text) | `--gold` | 9.1 |
| `--text` | `--navy-100` / `--gold-soft` | 13.9 / 13.7 |
| `--error` / `--on-navy` | `--card` / `--error` | 6.5 / 6.5 |

Every pair is **≥ 4.5:1** (WCAG AA for normal text), and most are ≥ 7:1 (AAA). The rule:
**gold is never used for text on a light background** (it's about 1.9:1 on white). On
light surfaces, gold only appears as a fill (buttons with navy text), a border, or an
underline.

**Applied as:**
- Nav: `--navy-900` background, white links, and a gold "My Profile · $X.XX" balance.
- Buttons: `.btn` is gold with navy text, and a darker gold on hover. `.btn.danger` stays
  red with white text. `.btn.secondary` is navy with white text.
- Links: `--navy-700`.
- Focus: a visible **gold focus ring** (`outline: 3px solid var(--gold)`) on links,
  buttons and fields.
- Chat sidebar: `--navy-800` background, `--on-navy` titles, `--muted-on-navy` dates. The
  current chat has a gold left border and a slightly lighter navy background. The ×
  shows in `--muted-on-navy` and turns red on hover.
- Bubbles: the user's are `--navy-700` with white text. The model's are `--card` with
  `--text`. The composer is a light card.
- Profile, models, admin-facing pages: navy headings, gold tier badges on
  `--gold-soft`, and a navy-tinted table header.
- The Markdown `.md` styles keep their light code and table backgrounds, re-tinted to
  `--navy-100`.

---

## 3. Landing page content (`/`)

This is the **only** page with the hero theme. It's `templates/home.html`, rendered by
`config.views.home`.

1. **Hero section** (full-width `--navy-900` band):
   - **Emblem:** an original **shield drawn in inline SVG** (a gold outline, a navy
     fill, and a white speech bubble with three dots inside), with `role="img"` and
     `aria-label="Chat4All emblem"`. No real superhero symbols, letters or stars.
   - **Headline** (h1): "Your everyday hero for AI."
   - **One-line description:** "Chat4All gives everyone access to top AI models, with no
     subscription: you only pay for each reply."
   - **Get started** button (gold): links to **Sign up** when logged out, and to **New
     chat** when logged in (the label becomes "Start a chat"). There's a secondary text
     link to "See all models".
2. **How it works**, three steps, each with a number badge:
   1. **Sign up and get $2.00 free.** New accounts start with $2.00 of credit, no card
      needed. (The amount comes from `SIGNUP_CREDIT_MICROS`, not a literal.)
   2. **Pick a model from OpenAI, Anthropic or Google.** Choose the one that suits the
      job, and switch any time you start a new chat.
   3. **Pay only for each reply.** A typical reply costs a fraction of a cent, and
      there's no monthly fee.
3. **Price snapshot: "What $2.00 gets you"**, read from the catalog:
   - One row per **active** model (`LLMModel.objects.filter(is_active=True)`), in catalog
     order, showing:
     - model name
     - provider (text)
     - tier
     - price per 1M tokens in/out
     - **the estimated cost per message**
     - **the estimated messages for $2.00**
   - **Assumption, stated on the page:** "Estimates assume a message of about 500 input
     tokens and a 300-token reply, in a new chat. Longer chats resend earlier messages,
     so each reply costs more. You're always charged for the real token count."
   - The column headers say "≈ per message (estimate)" and "≈ messages for $2.00
     (estimate)".
   - **Calculation** (a new pure helper, `catalog/estimates.py`,
     `estimate_messages(model, budget_micros, input_tokens=500, output_tokens=300)`):
     - `per_message = billing.services.reply_cost_micros(500, 300, in_price,
       out_price)`, the **same rounding-up formula** used for real charges
     - `messages = budget_micros // per_message`
     - `budget_micros = settings.SIGNUP_CREDIT_MICROS`
     - If `per_message == 0` (a free model), show "—", with no division by zero.
     - Counts are shown with thousands separators.
   - **With today's seeded prices** (these are test expectations):

     | Model | per message | ≈ messages for $2.00 |
     |---|---|---|
     | Claude Haiku ($1.00 / $5.00) | 500 + 1,500 = 2,000 µ$ = $0.002 | 1,000 |
     | Gemini Flash ($0.30 / $2.50) | 150 + 750 = 900 µ$ = $0.0009 | 2,222 |
     | GPT-5.6 Luna ($0.50 / $2.00) | 250 + 600 = 850 µ$ = $0.00085 | 2,352 |
   - It links to `/models/` for descriptions.
4. There are **no logos and no `<img>`**, just text provider names and the one inline
   SVG.

**Draft copy is above.** It's original and can be edited at review.

## 4. Log-in and sign-up cards

Both pages become a **centered card** (max-width about 400px, vertically offset from the
nav), on the plain navy/light page, **not** the hero theme.

| | Log in | Sign up |
|---|---|---|
| Heading | "Welcome back" | "Welcome to Chat4All" |
| Sub-line | "Log in to continue chatting." | "Create an account and get $2.00 of free credit." (the amount from settings, as today) |
| Fields | **Username**, **Password**, each with a visible `<label for>`, `autocomplete="username"` / `"current-password"` | **Username**, **Password**, **Confirm password**, each labeled, `autocomplete` `"username"` / `"new-password"`. Django's password rules show as small muted help text under the password. |
| Button | **one full-width** gold button, "Log in" | **one full-width** gold button, "Create account" |
| Link | "New to Chat4All? **Sign up**" | "Already have an account? **Log in**" |

- The fields are rendered explicitly (label, input, help, errors) instead of
  `form.as_p`, so labels, spacing and error placement are controlled. Field errors and
  non-field errors ("Please enter a correct username and password…") show inside the
  card with `role="alert"`.
- **No Google or social login**, and no extra buttons.
- **Behavior is unchanged:** invalid → **400**, a logged-in visitor → 302 home, `next`
  is preserved on log-in, and sign-up grants $2.00.

---

## Step 0: Branch

- [ ] `git switch -c loop6-visual-refresh` from an up-to-date `main`.

## Step 1: `feat: rename the app to Chat4All`

- [ ] Everything in the §1 table, **except** the README (Step 5) and the landing copy
      (Step 3). The current home page's single "Litechat" mention is replaced by the new
      page in Step 3; until then it keeps its generic copy.
- [ ] Tests (`config/tests.py`, `BrandTests`):
  - [ ] **No rendered page contains "Litechat"** (case-insensitive): home, models,
        log-in, sign-up, a chat page, New chat, My Profile, the delete confirmation, and
        the admin index (as staff). Each contains "Chat4All" in `<title>`, and the nav
        brand reads "Chat4All".
  - [ ] The admin index shows "Chat4All administration".
  - [ ] The inline chat script sets `" · Chat4All"` and never mentions "Litechat".
- [ ] Commit.

## Step 2: `feat: apply a navy and gold color scheme`

- [ ] Replace the `:root` tokens and restyle as in §2. Only CSS and class names change.
      No layout or behavior changes, except the added focus ring.
- [ ] Tests (`config/tests.py`, `ContrastTests`):
  - [ ] **Parse the `:root` custom properties from `base.html`**, compute WCAG contrast
        for every pair in the §2 table, and assert each is **≥ 4.5**. A future color
        edit that breaks readability then fails the suite.
  - [ ] Guard: no CSS rule sets `color: var(--gold)` except on a navy background (the
        nav balance, the sidebar marker, the hero). A string check covers the known
        selectors.
  - [ ] Every existing test still passes. They check behavior and markup hooks, not
        colors.
- [ ] Commit.

## Step 3: `feat: add a hero landing page with price estimates`

- [ ] `catalog/estimates.py`: `estimate_messages(model, budget_micros, input_tokens=500,
      output_tokens=300) -> (per_message_micros, messages_or_None)`, using
      `billing.services.reply_cost_micros`. It's pure, with no queries.
- [ ] `config/views.home`: its context has `models` (active, catalog order, each
      annotated with `per_message` and `messages`), `budget_micros`
      (`SIGNUP_CREDIT_MICROS`), and the assumption numbers (500 and 300) from constants
      in `catalog/estimates.py`, so the page text and the math can't drift apart.
- [ ] `templates/home.html` as in §3: the hero (SVG emblem, headline, description, Get
      started), How it works, and the price snapshot. It sets a `body_class` of
      `landing`, so hero-only CSS is scoped to it.
- [ ] Hero CSS (scoped under `body.landing`):
  - a full-bleed navy band, a gold emblem, large headline type
  - the three steps as cards with gold number badges
  - the snapshot as a card table, stacking into labeled rows at ≤ 720px
  - no horizontal scroll at 375px
- [ ] Tests (`config/tests.py`, `LandingPageTests`, using `call_command("seed")`):
  - [ ] `GET /` → 200. It has the h1 "Your everyday hero for AI.", the one-line
        description, and an inline `<svg role="img" aria-label="Chat4All emblem">`.
        There's **no `<img>`** on the page.
  - [ ] Get started: anonymous → `href` = sign-up, with the text "Get started". Logged
        in → `href` = New chat, with the text "Start a chat".
  - [ ] How it works: three steps in order, including "$2.00", and "OpenAI",
        "Anthropic", "Google" as text.
  - [ ] Snapshot:
    - rows for the three seeded models with **1,000 / 2,222 / 2,352** messages, and
      per-message **$0.002 / $0.0009 / $0.00085**
    - the words "estimate" and "500 input tokens" and "300-token reply" are present
    - a deactivated model disappears
    - a price edit changes the estimate (e.g. GPT output at $4.00 → 250 + 1,200 = 1,450
      µ$ → 1,379 messages)
    - a zero-price model shows "—" without an error
  - [ ] `estimate_messages` unit tests: the seeded values, rounding up (1 µ$ minimum per
        message whenever any price is non-zero), and `None` for free.
  - [ ] The hero theme is **only** here: `body.landing` is on `/` and on no other page
        (models, log-in, a chat, profile), and the emblem SVG appears only on `/`.
- [ ] Commit.

## Step 4: `feat: restyle log-in and sign-up as centered cards`

- [ ] `templates/registration/login.html` and `signup.html` as in §4. Add the
      `autocomplete` attributes via the form widgets (`SignUpForm` / the log-in form's
      field widgets) or in the explicit markup.
- [ ] CSS: `.auth-card` (centered, max-width 400px, padding, radius, shadow),
      `.field` (label above the input, full-width input), `.btn.block` (width 100%), and
      help and error text styles.
- [ ] Tests (`accounts/tests.py`):
  - [ ] Each page has the welcome heading, a `<label for="id_…">` for every input,
        **exactly one** submit button with class `btn block`, and the cross-link to the
        other page. There's no "Google" anywhere.
  - [ ] Log-in keeps the `next` hidden field. Sign-up shows "$2.00".
  - [ ] Behavior is unchanged (the existing tests cover it): 400 on invalid, 302 for
        logged-in visitors, sign-up credit. Error messages render inside the card with
        `role="alert"`.
- [ ] Commit.

## Step 5: `chore: update README for Chat4All`

- [ ] The title becomes `# Chat4All`, followed by: "Chat4All replicates the core
      functionality of [Litechat](https://litechat.ai): metered, pay-as-you-go access to
      LLMs from several providers, for people who won't pay for a subscription."
- [ ] Replace other **brand** mentions of "Litechat" in the README with "Chat4All". Keep
      the proxy URL `https://proxy.litechat.ai` as is, since it's the service's real
      address.
- [ ] Update the status note to loop 6, and mention the landing page and its estimates.
- [ ] Commit.

## Step 6: Verify (no commit)

- [ ] `check` passes, `makemigrations --check` shows no changes, all tests pass, and
      there's no real HTTP. `pip freeze` is unchanged apart from the existing
      requirements (**no new dependencies**).
- [ ] `grep -riI litechat templates accounts billing catalog chat config llm` finds only
      the proxy URL and its test.
- [ ] Live server on `0.0.0.0:8000`: `/`, `/models/`, `/accounts/login/`,
      `/accounts/signup/` → 200. The protected pages → 302 when anonymous.
- [ ] **Browser check** (headless Chrome over DevTools; `uitest` on the dev DB, already
      authorized). **No proxy calls are needed**; it only opens existing pages.
  - [ ] Screenshots at 1280px **and** 375px of: the landing page (logged out), log-in,
        sign-up (with a validation error showing), a chat, New chat, My Profile,
        `/models/`, and the delete confirmation. **Look at each one.**
  - [ ] **A contrast audit in the browser:** for every visible text element on those
        pages, compute the WCAG ratio between its computed `color` and the nearest
        opaque ancestor background, and flag anything under 4.5.
  - [ ] There's no horizontal scroll at 375px on any of them.
  - [ ] The landing page's Get started goes to sign-up when logged out, and to New chat
        after logging in as `uitest`.
  - [ ] Keyboard focus shows the gold ring on nav links, buttons and fields.
- [ ] `git status` is clean. `git log main..loop6-visual-refresh --oneline` shows five
      commits. Stop and wait for **rendezvous**.

## Done when

- Users see **Chat4All** everywhere: titles, nav, landing, auth pages, admin and README.
  The README credits Litechat as the product it replicates. The proxy URL is unchanged.
- The whole app uses the navy and gold scheme. Every text/background pair is ≥ 4.5:1,
  enforced by a test, with no text failing the browser audit.
- `/` is a hero landing page with an original inline-SVG shield, How it works, and a
  catalog-driven price snapshot with clearly labeled estimates (500 in / 300 out
  tokens), computed with the same rounding as real charges.
- Log-in and sign-up are centered cards with labeled fields, one full-width button, and
  cross-links. There's no social login.
- Billing, chat behavior, status codes and dependencies are unchanged, and every existing
  test still passes.
