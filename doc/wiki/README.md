# Chat4All wiki

The living manual of the codebase. It describes the code as it is on `main`, not as it
was planned. If the two disagree, the code wins and this wiki is out of date.

**Chat4All** replicates the core functionality of [Litechat](https://litechat.ai):
metered, pay-as-you-go access to LLMs from several providers, for people who won't pay
for a subscription. What counts as "core" is set out in
[Product decisions](product-decisions.md#what-i-identified-as-core).

**State as of loop 7** (merge `69dbf3c`, 2026-09-29):
- Accounts, the model catalog and the credit ledger work.
- **Chat works end to end with all three models**: GPT-5.6 Luna (OpenAI), Claude Haiku
  (Anthropic) and Gemini Flash (Google), each through its own adapter. The UI is
  chatbot-style:
  - a sidebar of chats, bubbles in one thread, and Enter to send
  - no reload, with a thinking indicator
  - renaming
- Each reply is charged its actual cost. Costs appear only on **My Profile**, and the nav
  shows "My Profile · $X.XX", updated after every reply.
- My Profile has an optional **Global System Prompt**, sent as the system prompt in every
  chat with every model.
- Model replies render **sanitized Markdown** (markdown-it-py + nh3: no raw HTML, images
  or styles).
- Chats can be **deleted** (with a confirmation page). Their charges stay in the ledger,
  with no refund, shown as "Deleted chats" on My Profile.
- The sidebar shows each chat's **last-activity date**, localized to the user's time
  zone.
- The app is named **Chat4All** and uses a **navy and gold** design, with contrast
  enforced by tests. `/` is a **hero landing page** with a price snapshot of estimated
  messages per $2.00. Log-in and sign-up are centered cards.
- New chats get an **automatic title** from their own model after the first reply. It's
  free to users: the cost is recorded for admins only.
- **Memories:** up to 10 short notes per user, sent with the Global System Prompt in
  every chat.

## Pages

| Page | What's in it |
|---|---|
| [Architecture](architecture.md) | Apps, directory layout, settings, URL map, request flow |
| [Chat and the LLM proxy](chat.md) | Conversations and messages, the send flow (including deleting a chat mid-reply), automatic titles and their admin-only cost log, the chat layout and templates, form vs JSON responses, the inline script, renaming, deleting, sidebar dates, safe Markdown, the `llm` package with the three provider adapters and their contracts |
| [Credits and billing](billing.md) | Money representation, wallet and ledger, charging replies, sign-up credit, admin top-ups, the My Profile page, the Global System Prompt, Memories, why automatic titles never touch the ledger, display rules |
| [Model catalog](catalog.md) | `LLMModel` fields, admin, the `/models/` page, which models can chat, the `seed` command |
| [Accounts and navigation](accounts.md) | Sign-up, log-in, log-out, the nav bar, HTTP status codes |
| [Visual design](design.md) | The Chat4All name, the navy and gold palette and its contrast rules (and the tests enforcing them), the landing page and its price estimates, the log-in and sign-up cards |
| [Development](development.md) | Setup, running, testing (including the no-network test runner), real-proxy and browser checks, database rules, commit conventions |
| [Product decisions](product-decisions.md) | What I identified as core, what's out of scope and why, why the credit system and the rest work the way they do, rejected alternatives, and where the code departs from each plan |

## Source documents

- Study: [`doc/study/1790657879-litechat-clone-feasibility.md`](../study/1790657879-litechat-clone-feasibility.md)
  (decisions log in §10)
- Plan (loop 1): [`doc/plan/1790659225-loop1-foundation.md`](../plan/1790659225-loop1-foundation.md)
- Plan (loop 2): [`doc/plan/1790661385-loop2-openai-chat.md`](../plan/1790661385-loop2-openai-chat.md)
- Study (chat redesign): [`doc/study/1790662970-chatbot-ui-redesign.md`](../study/1790662970-chatbot-ui-redesign.md)
  (decisions in §10)
- Plan (loop 3): [`doc/plan/1790663510-loop3-chat-redesign.md`](../plan/1790663510-loop3-chat-redesign.md)
- Plan (loop 4): [`doc/plan/1790676012-loop4-all-providers.md`](../plan/1790676012-loop4-all-providers.md)
- Study (Markdown, deleting, dates): [`doc/study/1790678621-loop5-markdown-delete-dates.md`](../study/1790678621-loop5-markdown-delete-dates.md)
  (decisions in §5)
- Plan (loop 5): [`doc/plan/1790681656-loop5-markdown-delete-dates.md`](../plan/1790681656-loop5-markdown-delete-dates.md)
- Plan (loop 6, no study: decided visual changes): [`doc/plan/1790683617-loop6-chat4all-visual-refresh.md`](../plan/1790683617-loop6-chat4all-visual-refresh.md)
- Study (automatic titles, Memories): [`doc/study/1790686669-loop7-auto-titles-memories.md`](../study/1790686669-loop7-auto-titles-memories.md)
  (decisions in §4)
- Plan (loop 7): [`doc/plan/1790687240-loop7-auto-titles-memories.md`](../plan/1790687240-loop7-auto-titles-memories.md)
