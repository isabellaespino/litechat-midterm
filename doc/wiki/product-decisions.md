# Product decisions

This page explains why the product works the way it does, which alternatives were
rejected, and where the code departs from each loop's plan. The detailed analysis is in
the study (`doc/study/1790657879-litechat-clone-feasibility.md`, §6 and §10).

## Who it's for

People who want occasional access to LLMs from several providers but **won't pay for a
subscription**. Every decision below serves that user: pay only for what you use, see
exactly what you spent, and never be billed for more than you put in.

## The credit system

### 1. Prepaid credit, charged per token

**Decision.** Each user has a prepaid US dollar balance, shown as "Available credit"
(e.g. `$1.99`). Each reply is charged by its **actual token usage**, as reported by the
proxy:
`input_tokens × input_price + output_tokens × output_price`, rounded up to the next
micro-dollar. Sending is blocked when the balance is **$0.00 or less**. A reply that
costs more than the remaining balance is still charged in full, so the balance can go
slightly negative.

**Why.**
- **Prepaid** means the operator never extends credit. There are no invoices, no
  collections and no surprise bills. Users can't spend money they haven't put in, apart
  from a bounded overshoot on one final reply.
- **Per token** matches how LLM costs actually arise: the proxy reports input and output
  tokens separately, and long chats cost more because the whole history is resent every
  turn. Charging per token passes that through honestly, and a short question costs
  almost nothing.
- **Charging the actual cost** (instead of refusing or cutting off a reply the balance
  can't fully cover) means users never get an unexpectedly truncated answer. The
  overshoot is bounded by the 1,024-output-token cap. At the most expensive seeded price
  ($5.00 per 1M output tokens), that's about half a cent of output per reply.
- **Micro-dollars** (whole integers, 1 USD = 1,000,000) are needed because one reply
  costs a fraction of a cent. For example, 1,000 input plus 300 output tokens on GPT-5.6
  Luna costs $0.0011. Loop 2's real check charged $0.00011 and $0.000114 for two short
  replies. Integers stay exact under concurrent `F()` updates. Balances are displayed
  rounded *down* to the cent, so we never overstate what's available.
- **No charge on failure:** if the proxy errors or times out, the user pays nothing and
  nothing is saved. Their draft stays in the form, so they can resend.

### 2. $2.00 sign-up credit

**Decision.** Every new user automatically receives $2.00, recorded as a `signup`
ledger entry. It's granted by a signal, so it applies however the account is created.

**Why.**
- It lets a new user try every model straight away, without waiting for an admin top-up.
  At the seeded prices, $2.00 covers hundreds of typical short replies.
- It's a ledger entry, not a starting balance written directly, so it shows in the
  user's history and keeps the invariant `balance == sum(ledger)`.
- It's small enough that the cost of abuse (making throwaway accounts for free credit)
  is limited. If abuse becomes a problem, the amount is one setting
  (`SIGNUP_CREDIT_MICROS`).

### 3. Per-model prices

**Decision.** Every model in the catalog has its own input and output price per 1M
tokens, editable in Django admin. The seeded models are all value tier: Claude Haiku
$1.00 / $5.00, GPT-5.6 Luna $0.50 / $2.00, Gemini Flash $0.30 / $2.50.

**Why.**
- Real providers price their models differently, and users choose partly on cost.
  Showing the price next to each model makes the choice informed.
- Input and output are priced separately because they're reported separately and
  usually cost different amounts. A single blended price would overcharge short-answer
  chats and undercharge long answers.
- Prices live in the database, not in code, so operators can change them, or add
  models, without a deploy. Each charged reply stores a snapshot of the prices it used,
  so later price edits don't rewrite history.

### 4. An append-only ledger

**Decision.** Every change to a balance is a `CreditTransaction` row: `signup`,
`topup`, `charge` (linked to the reply it paid for) or `adjustment`. The wallet balance is updated in the same database
transaction, and never edited directly. In admin, ledger rows can be added but not
changed or deleted. Mistakes are corrected with an `adjustment`, which may be negative.

**Why.**
- **Auditability:** every cent can be traced to a reason, a time and either the admin
  who made it (top-ups) or the exact reply it paid for (charges). Users see the same
  history on `/credit/`.
- **Correctness:** if admins edited balances directly, an edit made from a stale form
  could silently overwrite a charge that landed in the meantime. Ledger inserts plus
  atomic `F()` increments can't lose updates.
- **Verifiability:** `balance == sum(ledger)` can always be checked, and it's covered by
  tests.

### 5. Waiting up to 120 seconds for the proxy

**Decision.** `LLM_TIMEOUT_SECONDS = 120` (study §10 #12). It was 60 in the loop 2 plan.

**Why.** The proxy's response time varies widely. In loop 2's real check, one call hit
the 60-second timeout, and a retry took close to 60 seconds. For the user, a slow reply
is better than a failed one. A timeout still charges nothing, so the only cost of the
longer wait is the user's time. The call runs outside any database transaction, so a
slow reply doesn't block other users.

## Rejected alternatives

| Alternative | Why we rejected it |
|---|---|
| **Monthly subscriptions** | This is exactly what the target user won't pay. A subscription charges light users for capacity they don't use and needs recurring billing, plan tiers and cancellation flows. It would also still need usage caps to protect the operator from heavy users, which brings metering back anyway. |
| **Flat per-message pricing** | Simple to explain, but the cost of a message varies by orders of magnitude: a one-line question in a new chat is tiny, while a long answer deep into a chat (with the whole history resent) is expensive. A flat price either overcharges short messages (bad for our price-sensitive users) or loses money on long ones, and it gives users no reason to prefer cheaper models or shorter chats. |
| **No credits (free, or billed afterwards)** | Free, unmetered access exposes the operator to unbounded proxy costs, with nothing to stop one user from using up the budget. Billing after use (invoicing for usage) means extending credit to anonymous sign-ups, handling unpaid bills, and integrating a payment processor before launch. Prepaid credit avoids both: usage is limited by what's been paid (or granted), and top-ups can start as a manual admin action. |
| Admins editing the balance directly | No audit trail, and it can lose updates when an admin's save races with a charge (see §4). |
| Floats or cents for money | Floats drift. Cents can't represent one reply's cost. |
| Capping each reply to what the balance can afford | Users near $0 would get surprise truncated answers. We chose to charge the actual cost and allow a bounded, slightly negative balance instead. |
| Saving the user's message when the proxy fails | It would leave an unanswered message in the history, which would then be resent on every later turn. We save nothing and keep the draft in the form instead. |
| Streaming replies | Needs browser JavaScript and makes billing on disconnect ambiguous. Whole replies keep the pages template-only and charging exact. |

## Departures from the plan

### Loop 1

The loop 1 plan (`doc/plan/1790659225-loop1-foundation.md`) was followed step by step,
in seven commits. The code differs from it in these places:

1. **Invalid forms in Django admin return 200. The app's own forms return 400.**
   - The app's forms (sign-up, log-in, new chat and send) re-render invalid
     submissions with **400**, following the study's status-code decision.
     `SignUpView.form_invalid` and `LoginView.form_invalid` pass `status=400`.
   - Django admin re-renders an invalid add or change form with **200**. That's how
     Django's `ModelAdmin` is built. Examples are a negative top-up, or a price with more
     than 6 decimal places. We didn't override it: admin is a staff-only internal tool,
     overriding would mean customizing admin internals for no user benefit, and the error
     messages still show. Tests assert this (`AdminTopUpTests.test_negative_top_up_is_rejected`
     expects 200 and no ledger row).
   - **Rule:** views we write return 400 for invalid forms. Django admin keeps its own
     behavior.
2. **Existing ledger entries can be viewed in admin (200) but not changed or deleted
   (403).** The plan expected 403 on the change URL. Django admin gives a read-only page
   to anyone with view permission, which is useful for auditing. Posting a change and
   opening or posting the delete page return 403, and tests check this.
3. **The money helpers live in `config/money.py`, and the template filters in
   `catalog/templatetags/money.py`,** not in `billing` as planned. The catalog (step 4)
   needed dollar conversion and formatting before the billing app existed (step 5), and
   both apps use the same helpers.
4. **Users who existed before billing** get a $0.00 wallet when first seen
   (`get_wallet`), not the sign-up credit. Only newly created users get the $2.00. At
   loop 1 the dev database had no users, so this affected no one.
5. **Verifying the full click-through without touching the dev database.** The plan's
   smoke test (sign up, top up, and so on) was run by following nav links on a throwaway
   test database, so no test accounts were written to `db.sqlite3`. The live server on
   `0.0.0.0:8000` was checked with GET requests only.

### Loop 2

The loop 2 plan (`doc/plan/1790661385-loop2-openai-chat.md`) was followed in six
commits, plus one follow-up fix. The code differs from it in these places:

1. **Timeout raised from 60 to 120 seconds** (`fix: raise LLM proxy timeout to 120
   seconds`). The plan set 60. See decision 5 above.
2. **The chat list is ordered explicitly.** The plan relied on
   `Conversation.Meta.ordering`, but Django **ignores `Meta.ordering` on querysets that
   aggregate** (the list counts and sums messages). A test caught that chats came back
   in arbitrary order. The view now calls `.order_by("-updated_at", "-id")`. Keep this
   in mind for any future annotated query.
3. **The out-of-credit notice shows when the page loads.** The plan only described the
   notice on a blocked send (402). The chat pages now also show it at $0 or less when
   first loaded (200), so users learn before typing a message. The 402 on send is
   unchanged.
4. **The inactive-model check comes before the balance check.** Sending to a chat whose
   model was deactivated returns 400 even if the user is also out of credit, because
   topping up wouldn't help. The plan didn't specify the order.
5. **`LLMError` takes its status in the constructor** (`LLMError(status, message)`),
   rather than being set afterwards. There's no behavior change.
6. **Real-proxy verification ran on a throwaway database.** As in loop 1, the plan's
   end-to-end check signed up, started a chat, sent two real messages and checked the
   ledger, all on a temporary test database following nav links. `db.sqlite3` only
   received the two new migrations.
