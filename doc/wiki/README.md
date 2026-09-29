# Litechat wiki

The living manual of the codebase. It describes the code as it is on `main`, not as it
was planned. If the two disagree, the code wins and this wiki is out of date.

**State as of loop 3** (merge `15395df`, 2026-09-29):
- Accounts, the model catalog and the credit ledger work.
- **Chat works end to end with the OpenAI model** (GPT-5.6 Luna), in a chatbot-style UI:
  - a sidebar of chats, bubbles in one thread, and Enter to send
  - no reload, with a thinking indicator
  - renaming
- Each reply is charged its actual cost. Costs appear only on **My Profile**, and the nav
  shows "My Profile · $X.XX", updated after every reply.
- The Anthropic and Google models are in the catalog but show as "Coming soon".

## Pages

| Page | What's in it |
|---|---|
| [Architecture](architecture.md) | Apps, directory layout, settings, URL map, request flow |
| [Chat and the LLM proxy](chat.md) | Conversations and messages, the send flow, the chat layout and templates, form vs JSON responses, the inline script, renaming, the `llm` client |
| [Credits and billing](billing.md) | Money representation, wallet and ledger, charging replies, sign-up credit, admin top-ups, the My Profile page, display rules |
| [Model catalog](catalog.md) | `LLMModel` fields, admin, the `/models/` page, which models can chat, the `seed` command |
| [Accounts and navigation](accounts.md) | Sign-up, log-in, log-out, the nav bar, HTTP status codes |
| [Development](development.md) | Setup, running, testing (including the no-network test runner), real-proxy and browser checks, database rules, commit conventions |
| [Product decisions](product-decisions.md) | Why the credit system works the way it does, rejected alternatives, and where the code departs from each plan |

## Source documents

- Study: [`doc/study/1790657879-litechat-clone-feasibility.md`](../study/1790657879-litechat-clone-feasibility.md)
  (decisions log in §10)
- Plan (loop 1): [`doc/plan/1790659225-loop1-foundation.md`](../plan/1790659225-loop1-foundation.md)
- Plan (loop 2): [`doc/plan/1790661385-loop2-openai-chat.md`](../plan/1790661385-loop2-openai-chat.md)
- Study (chat redesign): [`doc/study/1790662970-chatbot-ui-redesign.md`](../study/1790662970-chatbot-ui-redesign.md)
  (decisions in §10)
- Plan (loop 3): [`doc/plan/1790663510-loop3-chat-redesign.md`](../plan/1790663510-loop3-chat-redesign.md)
