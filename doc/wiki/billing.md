# Credits and billing

Users hold a **prepaid US dollar balance** called "Available credit". It counts down as
replies are charged and goes up when an admin tops it up. The reasons for this design
are in [Product decisions](product-decisions.md). Users see the balance in the nav
("My Profile · $X.XX") and all of their usage on [My Profile](#my-profile).

## Money representation

Every amount is a whole number of **micro-dollars** (µ$): `1 USD = 1_000_000`. That
covers balances, ledger amounts, message costs and model prices. A single reply costs a
fraction of a cent (in loop 2's real check, $0.00011), so cents are too coarse, and
floats drift.

Helpers live in `config/money.py`:

| Function | Behavior | Examples |
|---|---|---|
| `dollars_to_micros(Decimal)` | Exact conversion. Raises `ValueError` for more than 6 decimal places. | `0.30` → `300000` |
| `micros_to_dollars(int)` | Exact `Decimal` | `500000` → `0.5` |
| `format_dollars(int)` | Dollars and cents, **rounded down** to the cent, with thousands separators | `1_999_999` → `$1.99`, `-1` → `-$0.01` |
| `format_dollars_precise(int)` | Up to 6 decimal places, at least 2 | `2_200` → `$0.0022`, `300_000` → `$0.30` |

Templates use the same functions as filters: `{% load money %}`, then
`{{ x|dollars }}` or `{{ x|dollars_precise }}` (`catalog/templatetags/money.py`).

**Display rules:**
- Balances use `dollars`, which rounds down so we never overstate what the user can
  spend.
- Ledger rows, reply costs and prices use `dollars_precise`.
- Raw µ$ values never appear in the UI or the admin.
- Reply costs and token counts appear only on My Profile and in admin, **never on the
  chat pages**.

## Models (`billing/models.py`)

**`Wallet`**, one per user (the primary key is the user):

- `balance_micros`: a signed `BigIntegerField`. It's signed because a reply is charged
  its actual cost even if that takes the balance slightly negative.
- `updated_at`.

**`CreditTransaction`**, the append-only ledger:

- `user`
- `amount_micros`: signed
- `kind`: `signup`, `topup`, `charge` or `adjustment`
- `note`
- `message`: one-to-one to the `chat.Message` a `charge` paid for, or null
- `created_by`: the admin who made it, or null
- `created_at`

Rows are ordered newest first. `str()` shows dollars, e.g. "Top-up $5.00 for alice" or
"Charge -$0.0011 for alice". Admin uses this text in page titles, breadcrumbs, "was
added" messages and Recent actions.

**Invariant:** `wallet.balance_micros == sum(CreditTransaction.amount_micros)` for the
user. It's tested in `billing/tests.py::LedgerTests` and `chat/tests.py`.

## The only way to change a balance (`billing/services.py`)

- `record_transaction(txn)`: inside `transaction.atomic()`, it ensures the wallet
  exists, saves the ledger row, and applies
  `UPDATE wallet SET balance_micros = balance_micros + amount`, using `F()`. There's no
  read-modify-write in Python, so concurrent transactions can't overwrite each other.
- `post_transaction(user, amount_micros, kind, note="", created_by=None, message=None)`:
  builds a `CreditTransaction`, then calls `record_transaction`.
- `get_wallet(user)`: `get_or_create`. A user who existed before billing was added gets
  a $0.00 wallet here, not the sign-up credit.

Never assign `wallet.balance_micros` directly anywhere else.

## Charging a reply

`reply_cost_micros(input_tokens, output_tokens, input_price, output_price)` computes
`ceil((input_tokens × input_price + output_tokens × output_price) / 1_000_000)`, with
prices in µ$ per 1M tokens and integer arithmetic only. Rounding up means no reply is
free because of rounding. For example:
- 1,000 in + 300 out on GPT-5.6 Luna = 1,100 µ$ ($0.0011).
- 183 in + 9 out = 109.5, which rounds up to 110 µ$ ($0.00011).

The charge flow (details in [Chat → The send flow](chat.md#the-send-flow)):

1. **Before calling the proxy**, the view refuses to send if
   `get_wallet(user).balance_micros <= 0`, with **402**.
2. After a successful reply, one atomic block saves both messages and posts a `charge`
   of `-cost` linked to the assistant message. The charge applies even if the balance
   goes negative. The overshoot is bounded by the 1,024-output-token cap, and the next
   send is then blocked.
3. If the proxy fails (`LLMError`), **nothing is charged** and nothing is saved.

**Concurrency:** two tabs sending at the same moment can both pass the balance check.
Both charges then apply via `F()`, so the overdraft is at most two replies. We accept
that; `select_for_update` does nothing on SQLite.

## Sign-up credit

`billing/signals.py` connects `post_save` on the user model in `BillingConfig.ready()`.
When a user is **created** (not merely saved, and not during fixture loading), it posts
a `signup` transaction of `SIGNUP_CREDIT_MICROS` ($2.00) with the note "Sign-up credit".
It fires for every way a user can be created: the sign-up form, Django admin,
`createsuperuser` and `create_user`.

## Admin

- **Credit transactions → Add** is the top-up form. It has these fields:
  - user (an autocomplete field)
  - **amount in dollars** (up to 6 decimal places)
  - kind: `topup` or `adjustment` only (`signup` and `charge` are system-only)
  - note

  Validation: the amount can't be zero, and a top-up can't be negative (use an
  adjustment to remove credit). `save_model` converts the dollars to µ$, sets
  `created_by`, and calls `record_transaction`.
- **List columns:** date, user, kind, amount ($), note, created by, and **Chat** (for
  `charge` rows, a link to the conversation).
- **Append-only:** `has_change_permission` and `has_delete_permission` return `False`.
  Opening an existing entry shows a read-only page. Saving it or deleting it returns 403.
- **Wallets:** read-only list and detail pages. They show the balance in dollars and a
  "View transactions" link to that user's ledger, filtered. There's no add, change or
  delete.
- **Users:** the standard user admin plus a read-only "Available credit" inline.

## My Profile

**Nav bar** (logged in): **"My Profile · $X.XX"**, linking to `/profile/`. The amount is
in `<span data-nav-balance>`, and on the chat pages the script updates it from each
reply's JSON `balance`, so it's current after every reply without a reload.

**`/profile/`** (`billing.views.profile`, login required; anonymous visitors → 302 to
log-in) shows:
- **Account:** username and member since.
- **Available credit:** shown large (`dollars`), with "Contact an administrator to add
  credit."
- **Totals:** credit added (the non-`charge` ledger sum), spent on replies (the `charge`
  sum, as a positive number), and the balance. Added − spent = balance = the ledger sum.
- **Usage by chat:**
  - Chats are annotated with the reply count (assistant messages), summed input and
    output tokens, total cost and last used. They're ordered explicitly
    (`.order_by("-updated_at", "-id")`) and paginated 20 per page
    (`Paginator.get_page`, so `?page=abc` still gives 200).
  - Each chat is a `<details>` that expands to its replies: date/time, tokens in and
    out, cost, and "(estimated)" or "(cut short)" where they apply.
  - Replies come from **one query** for the whole page, grouped in Python. The number
    of queries doesn't grow with the number of chats, and a test checks this.
- **Credit added:** sign-up credit, top-ups and adjustments, with date, type, note and
  amount.

**`/credit/`** (the loop 1–2 credit page) now returns a **301** to `/profile/`.

**Chat pages** show no costs. At $0 or less they show an out-of-credit notice linking to
My Profile, and disable the composer.
