# Litechat wiki

The living manual of the codebase. It describes the code as it is on `main`, not as it
was planned. If the two disagree, the code wins and this wiki is out of date.

**State as of loop 1** (merge `f4f4cf8`, 2026-09-29): accounts, the model catalog and
the credit ledger work. **No LLM calls exist yet.** Chatting and per-reply charging
arrive in loop 2.

## Pages

| Page | What's in it |
|---|---|
| [Architecture](architecture.md) | Apps, directory layout, settings, URL map, request flow |
| [Credits and billing](billing.md) | Money representation, wallet and ledger, sign-up credit, admin top-ups, display rules |
| [Model catalog](catalog.md) | `LLMModel` fields, admin, the `/models/` page, the `seed` command |
| [Accounts and navigation](accounts.md) | Sign-up, log-in, log-out, the nav bar, HTTP status codes |
| [Development](development.md) | Setup, running, testing, database rules, commit conventions |
| [Product decisions](product-decisions.md) | Why the credit system works the way it does, rejected alternatives, and where the code departs from the plan |

## Source documents

- Study: [`doc/study/1790657879-litechat-clone-feasibility.md`](../study/1790657879-litechat-clone-feasibility.md)
- Plan (loop 1): [`doc/plan/1790659225-loop1-foundation.md`](../plan/1790659225-loop1-foundation.md)
