# Credits and billing

Users hold a **prepaid US dollar balance** called "Available credit". It counts down as
replies are charged (from loop 2) and goes up when an admin tops it up. The reasons for
this design are in [Product decisions](product-decisions.md).

## Money representation

Every amount is a whole number of **micro-dollars** (µ$): `1 USD = 1_000_000`. That
covers balances, ledger amounts and model prices. A single reply costs a fraction of a
cent, so cents are too coarse, and floats drift.

Helpers live in `config/money.py`:

| Function | Behavior | Examples |
|---|---|---|
| `dollars_to_micros(Decimal)` | Exact conversion. Raises `ValueError` for more than 6 decimal places. | `0.30` → `300000` |
| `micros_to_dollars(int)` | Exact `Decimal` | `500000` → `0.5` |
| `format_dollars(int)` | Dollars and cents, **rounded down** to the cent, with thousands separators | `1_999_999` → `$1.99`, `-1` → `-$0.01` |
| `format_dollars_precise(int)` | Up to 6 decimal places, at least 2 | `2_200` → `$0.0022`, `300_000` → `$0.30` |

Templates use the same functions as filters: `{% load money %}`, then
`{{ x|dollars }}` or `{{ x|dollars_precise }}` (`catalog/templatetags/money.py`).

**Display rules:** balances use `dollars`, which rounds down so we never overstate what
the user can spend. Ledger rows and prices use `dollars_precise`.

## Models (`billing/models.py`)

**`Wallet`**, one per user (the primary key is the user):

- `balance_micros`: a signed `BigIntegerField`. It's signed because a reply is charged
  its actual cost even if that takes the balance slightly negative (from loop 2).
- `updated_at`.

**`CreditTransaction`**, the append-only ledger:

- `user`
- `amount_micros`: signed
- `kind`: `signup`, `topup`, `charge` (reserved for loop 2) or `adjustment`
- `note`
- `created_by`: the admin who made it, or null
- `created_at`

Rows are ordered newest first.

**Invariant:** `wallet.balance_micros == sum(CreditTransaction.amount_micros)` for the
user. It's tested in `billing/tests.py::LedgerTests`.

## The only way to change a balance (`billing/services.py`)

- `record_transaction(txn)`: inside `transaction.atomic()`, it ensures the wallet
  exists, saves the ledger row, and applies
  `UPDATE wallet SET balance_micros = balance_micros + amount`, using `F()`. There's no
  read-modify-write in Python, so concurrent transactions can't overwrite each other.
- `post_transaction(user, amount_micros, kind, note="", created_by=None)`: builds a
  `CreditTransaction`, then calls `record_transaction`.
- `get_wallet(user)`: `get_or_create`. A user who existed before billing was added gets
  a $0.00 wallet here, not the sign-up credit.

Never assign `wallet.balance_micros` directly anywhere else.

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
  - kind: `topup` or `adjustment` only
  - note

  Validation: the amount can't be zero, and a top-up can't be negative (use an
  adjustment to remove credit). `save_model` converts the dollars to µ$, sets
  `created_by`, and calls `record_transaction`.
- **Append-only:** `has_change_permission` and `has_delete_permission` return `False`.
  Opening an existing entry shows a read-only page. Saving it or deleting it returns 403.
- **Wallets:** read-only list and detail pages. They show the balance in dollars and a
  "View transactions" link to that user's ledger, filtered. There's no add, change or
  delete.
- **Users:** the standard user admin plus a read-only "Available credit" inline.

## User-facing pages

- **Nav bar** (logged in): "Available credit: $X.XX", which links to `/credit/`.
- **`/credit/`**: the balance, and the user's own ledger (date, type, note, amount).
  Anonymous visitors are redirected to log-in.
