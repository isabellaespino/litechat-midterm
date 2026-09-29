# Visual design

Loop 6 (plan `doc/plan/1790683617-loop6-chat4all-visual-refresh.md`, with no study,
because these were decided changes). It changed the visuals only: no new features beyond
the landing page content, no new dependencies, and no changes to billing or chat
behavior.

## Name

The app is **Chat4All**. It replicates the core functionality of
[Litechat](https://litechat.ai), which the README says in its second line.
- "Chat4All" appears in every `<title>` (`{% block title %}… · Chat4All`), the nav brand,
  the title the chat script sets after a new chat's first reply (`" · Chat4All"`), and
  Django admin (`site_header = "Chat4All administration"`, set in `config/urls.py`).
- **Not renamed:** `LLM_PROXY_BASE_URL = "https://proxy.litechat.ai"`, which is the real
  proxy's address. The repo folder, and past `doc/study` and `doc/plan` files, are also
  unchanged.
- `config.tests.BrandTests` fails if any rendered page (home, models, log-in, sign-up,
  chat, New chat, My Profile, the delete confirmation, the admin index) contains
  "litechat" in any case.

## Palette: navy with a gold accent

All CSS is inline in `templates/base.html`. Colors are defined **once** as custom
properties on `:root`, and page rules only use `var(--…)`.

| Token | Value | Used for |
|---|---|---|
| `--navy-900` | `#0b1f3a` | nav bar, landing hero, primary text, button text |
| `--navy-800` | `#12305a` | chat sidebar |
| `--navy-700` | `#1c3f73` | links, the user's chat bubbles, sidebar hover and current row |
| `--navy-100` | `#e6ecf5` | table headers, model chip, inline code, flash messages |
| `--page` / `--card` | `#f5f7fb` / `#ffffff` | page background / cards, the model's bubbles |
| `--text` / `--muted` | `#0b1f3a` / `#4a5a73` | text on light backgrounds |
| `--on-navy` / `--muted-on-navy` | `#ffffff` / `#b9c6dc` | text on navy (nav, sidebar, hero) |
| `--gold` / `--gold-hover` / `--gold-soft` | `#f2b705` / `#ffc933` / `#fde9a8` | primary buttons, the current-chat marker, the nav balance, focus ring, tier badges, the emblem |
| `--line` | `#d5deeb` | borders |
| `--error` / `--error-soft` | `#b3261e` / `#fdecea` | errors, the delete button |

**Contrast rules:**
- Every text/background pair used is **≥ 4.5:1** (WCAG AA). The lowest is 5.7:1 (error
  text on its pale background, `--error` on `--error-soft`), and 16 of the 22 pairs are
  ≥ 7:1 (AAA).
- **Gold is text only on navy** (the nav balance, the mobile "Chats" toggle, the landing
  hero's eyebrow). On white it would be about 1.9:1, so on light surfaces gold is only a
  fill with navy text, a border, or a ring.
- **Focus:** `:focus-visible` draws a 3px **gold outline with a navy halo**
  (`box-shadow: 0 0 0 5px var(--navy-900)`). The halo makes the ring visible on light
  backgrounds and the gold makes it visible on navy. The plan had gold only, but a gold
  ring alone fails the 3:1 non-text contrast on white.

**Enforced by tests** (`config.tests.ContrastTests`):
- **The pairs:** the test parses the `:root` tokens out of `base.html`, computes the WCAG
  ratio for every text/background pair the CSS uses (22 pairs), and asserts each is
  ≥ 4.5.
- **The gold rule:** it fails if any rule sets `color: var(--gold)` outside `nav .credit`,
  `.mobile-chats summary` or `body.landing .hero …`.
- **In practice:** a color edit that makes text unreadable fails the suite.

**Where it's applied:**
- **Nav:** navy, with white links and the gold "My Profile · $X.XX".
- **Buttons (`.btn`):** gold with navy text. `.btn.secondary` is navy, `.btn.danger` is
  red, and `.btn.block` is full width.
- **Chat sidebar:** navy, with white titles and muted-on-navy dates. The current chat has
  a gold left border. The × turns red on hover.
- **Bubbles:** the user's are navy with white text, the model's are white.
- **Tables:** headers are navy-tinted, and tier badges are gold-soft.
- **My Profile's per-chat totals** are right-aligned on desktop. At 720px and below they
  sit on their own line under the chat title, because a float there landed mid-sentence
  (fixed in loop 7).
- **Memories** (loop 7) are a list of notes with navy **Delete** buttons (`.btn.secondary
  .small`) and a single-line Add form with a gold **Add** button.

### Include memories switch

This is loop 8. The native checkbox is drawn as a switch with `appearance: none`, so it's
still a real form control, and it uses **existing tokens only**.
- **On:** a `--navy-700` track with a white (`--on-navy`) knob.
- **Off:** a **white track with a `--muted` border and knob**. The plan had a pale
  `--line` track, but that's about 1.3:1 against the page, below WCAG's **3:1 for
  controls**. `--muted` is 6.5:1.
- The label is `--text`, 600 weight, with a muted count, e.g. "Include memories (1)".
- It uses the loop 6 gold focus ring, and has no animation under
  `prefers-reduced-motion`.

### The composer on phones

At 720px and below, the model chip or picker (and the switch) take the first line(s).
**The message box and Send always share their own line**
(`textarea { flex: 1 1 calc(100% - 96px) }`). Loop 8's screenshots showed that adding
the switch squeezed the message box to a sliver. A first fix (a 200px minimum) then
pushed Send onto its own line in chats without the switch. The final rule was measured
at 375px, with and without the switch, and at 1280px.

## Landing page (`/`)

It's `templates/home.html`, rendered by `config.views.home`. **It's the only page with
the hero theme:** it sets `{% block body_class %}landing{% endblock %}`, and all hero
CSS is scoped under `body.landing`. A test asserts no other page has the `landing` class
or an `<svg>`.

1. **Hero** (a full-width navy band):
   - An **original shield emblem** in inline SVG: a navy shield with a gold outline and
     a white speech bubble with three dots. It has `role="img"` and `aria-label="Chat4All
     emblem"`, and no real superhero symbols.
   - The eyebrow "Chat4All" and the h1 "Your everyday hero for AI."
   - The description: "Chat4All gives everyone access to top AI models, with no
     subscription: you only pay for each reply."
   - A **Get started** button (to sign-up), which becomes **Start a chat** (to New
     chat) when logged in, plus a "See all models" link.
2. **How it works**, three steps:
   - "Sign up and get $2.00 free". The amount comes from `SIGNUP_CREDIT_MICROS`.
   - "Pick a model from OpenAI, Anthropic or Google"
   - "Pay only for each reply" (a fraction of a cent, no monthly fee)
3. **"What $2.00 gets you"**, a price snapshot of the **active** catalog models:
   - Each row shows name, provider (as text; there are no logos), tier, price per 1M
     tokens, **≈ per message (estimate)** and **≈ messages for $2.00 (estimate)**.
   - **`catalog/estimates.py`**, `estimate_messages(model, budget_micros)`:
     - `per_message = reply_cost_micros(500, 300, in_price, out_price)`, the **same
       rounding-up formula as real charges**
     - `messages = budget // per_message`, or `None` (shown as "—") for a free model
   - The assumption constants `ASSUMED_INPUT_TOKENS = 500` and `ASSUMED_OUTPUT_TOKENS =
     300` feed both the math and the page text, which says: "These are estimates. They
     assume a message of about 500 input tokens and a 300-token reply, in a new chat.
     Longer chats resend earlier messages, so each reply costs more. You're always
     charged for the real token count."
   - At today's seeded prices:

     | Model | Per message | Messages for $2.00 |
     |---|---|---|
     | Claude Haiku | $0.002 | 1,000 |
     | Gemini Flash | $0.0009 | 2,222 |
     | GPT-5.6 Luna | $0.00085 | 2,352 |

   - At 720px and below, the snapshot table stacks into labeled rows (`data-label`).
- There are no `<img>` elements on the page.
- **Tests:**
  - `config.tests.LandingPageTests` covers the hero, the CTA for logged-out and
    logged-in users, the three steps, the snapshot values, and the snapshot following
    catalog changes: deactivating a model, a price edit (→ 1,379), and a free model
    (→ "—"). It also checks that the theme appears only on `/`.
  - `EstimateTests` covers the helper, including rounding up and free models.

## Log-in and sign-up cards

`templates/registration/login.html` and `signup.html`:
- **The card:** a centered `.auth-card` (max 400px, with a gold top border) on the plain
  page, with none of the hero theme.
- **Headings:** "Welcome back" / "Log in to continue chatting." and "Welcome to Chat4All"
  / "Create an account and get $2.00 of free credit."
- **Fields:** rendered through `registration/_field.html`, each with a visible `<label
  for>`, help text, and its errors (`p.field-error`, `role="alert"`). Non-field errors
  show as `p.form-error`.
- **Labels and autocomplete:** `SignUpForm` labels the second password "Confirm
  password". Django's widgets already set `autocomplete` (`username`,
  `current-password`, `new-password`).
- **The rest of the card:** exactly **one full-width button** (`.btn.block`), and a link
  to the other page. There's no social login.
- **Validation:** the forms use `novalidate`, so validation errors come from the server
  and appear inside the card with the existing **400**, not as browser pop-ups.
- `accounts.tests.AuthCardTests` covers the headings, a label for every input, exactly one
  `btn block` button, the cross-links, "no Google", `next` preserved, and errors inside
  the card with 400.

## Checking visuals

Unit tests can't see a page, so loop 6's verify step (like loops 3–5) drove headless
Chrome. In loop 6 it checked:
- **Contrast in the browser:** for every visible element with its own text (about 600,
  on 8 pages at 1280px and 375px), the WCAG ratio of its computed `color` against the
  nearest opaque ancestor background. Nothing was under AA (4.5, or 3 for large text).
- **Layout:** no horizontal scroll at 375px on any page.
- **Behavior:** the gold ring with its navy halo on keyboard focus, and where Get started
  leads when logged out and logged in.
- **Screenshots:** of every page, which were looked at, not just asserted on.

See [development](development.md#browser-checks-the-chat-script).
