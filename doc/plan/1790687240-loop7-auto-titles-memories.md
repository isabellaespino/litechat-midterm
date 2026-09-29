# Plan: Loop 7: automatic chat titles (app-paid, admin-only cost) and Memories

- **Date:** 2026-09-29 (Unix 1790687240)
- **Source study:** `doc/study/1790686669-loop7-auto-titles-memories.md`, with the
  decisions in **§4**. Decision #1 overrides the study's billing recommendation in §2.4:
  titles are free to users and recorded for admins only.
- **Builds on:** loop 6 on `main` (wiki `chat.md`, `billing.md`, `design.md`).
- **Branch:** `loop7-titles-memories`, off `main`. Don't merge during execute. Wait for
  the rendezvous command.
- **Scope:**
  1. **Automatic titles.** After a new chat's first reply, a separate request asks the
     **chat's own model** for a short title.
     - It's **free and invisible to the user:** no ledger row, no balance change, and
       nothing on My Profile or in the credit history.
     - Each attempt's usage and cost are recorded in an **admin-only** log.
     - **Every new chat gets an attempt, regardless of balance.**
     - A failure keeps the provisional first-line title, and the user is never charged.
  2. **Memories.** Up to **10 notes of at most 200 characters** each, added on My Profile
     and deleted immediately (no confirmation). They're sent with the Global System
     Prompt in every chat, to every provider. Only the user adds them; AI-generated
     memories are out of scope.
- **Unchanged:**
  - The user's ledger and `balance == sum(ledger)`.
  - My Profile's **single "Spent" total, for replies only**, and its reconciliation:
    (per-chat totals + deleted chats = spent; added − spent = balance).
  - The 402 block and reply charging.
  - The first reply's latency.
  - The adapters' request formats, except the new optional output cap and timeout.
- **No new dependencies. Two migrations:** `chat` (`title_source` and `TitleGeneration`)
  and `accounts` (`Memory`).

## Fixed values

| Name | Value | Where |
|---|---|---|
| `TITLE_MAX_OUTPUT_TOKENS` | `20` | `config/settings.py` |
| `TITLE_TIMEOUT_SECONDS` | `20` | `config/settings.py` (replies keep 120) |
| `TITLE_EXCERPT_CHARS` | `1000` | the first message and the first reply are each truncated to this |
| `TITLE_MAX_CHARS` (auto) | `60` | the cleaned title is capped, with `…` |
| `MEMORY_MAX_COUNT` | `10` | `accounts/models.py` |
| `MEMORY_MAX_CHARS` | `200` | `accounts/models.py` |

**The title prompt**, sent as one `user` message, with `system=None` (no Global System
Prompt, no memories):

```
Write a short title (3 to 6 words) for this conversation. Reply with the title only:
no quotes, no Markdown, no ending punctuation. Use the conversation's language.

User: <first user message, ≤1000 chars>
Assistant: <first reply, ≤1000 chars>
```

A single message keeps Anthropic's alternation rule trivially satisfied.

**How the system text is built from the Global System Prompt and memories**
(`accounts.services.system_text_for(user)`, which replaces `system_prompt_for` at send
time):

```
<Global System Prompt, if set>

About the user (notes they asked you to remember):
- <memory 1>
- <memory 2>
```

With only one of the two set, the result is just that part. With neither, it's `None`,
so there's still no system field at all.

---

## Step 0: Branch

- [ ] `git switch -c loop7-titles-memories` from an up-to-date `main`.

## Step 1: `feat: allow a per-call output cap and timeout in the proxy client`

- [ ] `llm.complete(llm_model, messages, system=None, max_output_tokens=None,
      timeout=None)`, passed down to each adapter:
  - `max_output_tokens`, defaulting to `settings.MAX_OUTPUT_TOKENS`, sets OpenAI
    `max_tokens`, Anthropic `max_tokens` and Google `generationConfig.maxOutputTokens`
  - `timeout`, defaulting to `settings.LLM_TIMEOUT_SECONDS`, is passed to
    `http.post_json`
- [ ] Nothing else changes: replies keep 1,024 and 120 s.
- [ ] Tests (`llm/tests.py`): add rows to the provider table:
  - [ ] Each adapter sends the overridden cap in its own field, and the override reaches
        `requests.post(timeout=…)`.
  - [ ] The defaults are unchanged: the existing request-shape tests still assert 1,024
        and 120.
- [ ] Commit.

## Step 2: `feat: record title generation costs for admins`

- [ ] `chat.TitleGeneration`, an **admin-only operator cost log, never shown to users.**
      Fields:
  - `conversation` (FK, `SET_NULL`, nullable), and `user` (FK, `SET_NULL`, nullable),
    so an admin can see whose chat it was
  - `llm_model` (FK, `PROTECT`)
  - `status`: `ok` (the title was saved), `unusable` (the model answered but the text
    couldn't be used), `superseded` (the model answered but a rename happened first),
    `chat_deleted`, or `failed` (the proxy call failed)
  - `title` (the cleaned title, or blank)
  - `input_tokens`, `output_tokens`, `usage_estimated`
  - `input_price_micros_per_mtok`, `output_price_micros_per_mtok` (a snapshot)
  - `cost_micros`, computed with `reply_cost_micros`, the same formula as real charges
  - `error_status` (the 502/503 we would have returned, for `failed`)
  - `created_at`
- [ ] **Not linked to the user's ledger in any way.** No `CreditTransaction`, and no
      `Wallet` change.
- [ ] Admin: **"Title generations (app cost)"**, a read-only list:
  - columns: date, user, chat (a link while it exists), model, status, tokens in/out,
    cost ($)
  - filters on status and model, and search by username
  - above the list: "Total app cost for the rows shown: $X" (`changelist_view`
    `extra_context`, summing the filtered queryset)
  - no add, change or delete
- [ ] Tests:
  - [ ] The admin list renders (200) with dollar costs and the total.
  - [ ] Add, change and delete are all forbidden (403).
  - [ ] Non-staff can't reach it.
- [ ] Commit.

## Step 3: `feat: name chats automatically after the first reply`

- [ ] `Conversation.title_source`: `provisional`, `generating`, `auto`, `user`,
      `failed`.
  - **The migration default for existing rows is `user`**, so there's no retroactive
    titling. The model default is also `user`.
  - `send_message` sets `provisional` when it **creates** a chat, with the title from
    `title_from`, as today.
  - Rename (`chat_rename`) sets `user`, in the same `update()`.
- [ ] `chat/titles.py`:
  - [ ] `build_title_prompt(conversation)`: the fixed instruction, plus the first user
        message and the first assistant reply, each truncated to 1,000 characters.
  - [ ] `clean_title(text)`:
    - the first non-empty line only
    - strip surrounding quotes, `#`, `*`, `_` and backticks
    - drop a leading "Title:"
    - collapse whitespace, and drop a trailing `.`, `:` or `;`
    - cap at 60 characters with `…`
    - return `""` if nothing meaningful is left: empty, only punctuation, or exactly
      "title" or "untitled"
  - [ ] `generate_title(conversation)`:
    1. **Claim it:** `Conversation.objects.filter(pk=…, title_source="provisional")
       .update(title_source="generating")`. Zero rows updated → return **"conflict"**
       without calling the proxy.
    2. Call `llm.complete(conversation.llm_model, [prompt], system=None,
       max_output_tokens=20, timeout=20)` **outside any transaction**.
    3. `LLMError` → log `failed` (0 tokens, 0 cost, `error_status`), and set
       `title_source="failed"` only if the chat is still `generating`. Return
       "failed".
    4. Otherwise compute the cost, and clean the title. Then, **in one atomic block:**
       - if the chat is gone → log `chat_deleted` and return "deleted"
       - `filter(pk=…, title_source="generating").update(title=…, title_source="auto")`
         when the cleaned title is usable
       - if that updated 0 rows (a rename set `user` meanwhile) → log `superseded` and
         return "conflict"
       - unusable text → set `title_source="failed"` (the provisional title stays),
         log `unusable`, and return "unusable"
       - otherwise → log `ok` and return "ok"

       The update uses `update()`, so the title doesn't bump `updated_at` or reorder
       the sidebar, like a rename.
  - [ ] Every outcome writes exactly one `TitleGeneration` row, **except** the
        "conflict before claiming" case, which makes no call and costs nothing. **No
        outcome touches the user's wallet or ledger.**
- [ ] Endpoint `POST /chats/<id>/title/` (`chat_title`), JSON only. It uses
      `chat_login_required` and `require_POST`, and is **not** balance-gated (decision
      #1: every new chat gets an attempt).

  | Result | Status and body |
  |---|---|
  | `ok` | **200** `{"changed": true, "title", "sidebar_html"}` |
  | `unusable` | **200** `{"changed": false, "title": <provisional>}` |
  | `conflict` (not provisional: renamed, already titled, or another request is generating) | **409** `{"error"}` |
  | `failed` | **502 / 503** `{"error"}`, matching the `LLMError` status |
  | `deleted` / another user's chat / unknown | **404** `{"error"}` |
  | logged out | **401** |
  | GET | **405** |

  The response has **no `balance`**, because nothing was charged.
- [ ] Script (`_script.html`):
  - [ ] After a new chat's first reply (the `main_html` branch), call
        `requestTitle(chat_url)`, a `fetch` POST to `chat_url + "title/"` with
        `Accept: application/json` and the `X-CSRFToken` header taken from the
        composer's `csrfmiddlewaretoken`.
  - [ ] **On load**, if the chat header has `data-title-source="provisional"`, call it
        too. That covers a tab closed before the request fired, or a chat created
        without JS and later opened with JS. `failed` is never retried.
  - [ ] On `changed: true`, while still on that chat's URL:
    - set the header `<h1>` and the rename input's value
    - set `document.title` to `"<title> · Chat4All"`
    - replace every `[data-sidebar-list]` with `sidebar_html` (which re-localizes the
      dates)
  - [ ] Every other status is **ignored silently.** It's a background nicety, and
        nothing is shown to the user.
  - [ ] **The nav balance is not touched.**
  - [ ] `_main.html`: the header carries `data-title-source="{{
        conversation.title_source }}"`.
- [ ] Tests (`chat/tests.py`, `AutoTitleTests`, mocking `llm.http.requests.post` with a
      provider-shaped reply for **each of the three providers**):
  - [ ] **The first send is unchanged:** the same statuses and latency path, with a
        provisional title and `title_source="provisional"`. One proxy call per send, so
        the title isn't requested inside the send.
  - [ ] **Success:**
    - a mocked "Trip to Rome." → the title becomes "Trip to Rome", and the source is
      `auto`
    - the request used the **chat's own model**, `max_output_tokens` 20, timeout 20,
      **no system field** (even with a Global System Prompt and memories set), and the
      prompt contains the truncated first message and reply
    - one `TitleGeneration` `ok` row, with tokens and cost equal to `reply_cost_micros`
      at that model's price
  - [ ] **Free and invisible:**
    - the wallet balance and the ledger row count are unchanged
    - My Profile's "Spent", the per-chat totals and "Deleted chats" are unchanged, and
      the reconciliation equations still hold
    - neither My Profile, the chat page nor the nav contains the title call's cost or
      tokens
  - [ ] **Regardless of balance:** with the balance at 0 or negative (after a first reply
        that went negative), the title call still happens and is logged, and the user
        is still not charged.
  - [ ] **Failure:** a proxy 500 → 502, and a 429 → 503. The provisional title stays, the
        source is `failed`, there's a `failed` log row with 0 cost, and a second POST →
        409 (no retry).
  - [ ] **Unusable output** (`""`, `"."`, `"Title"`) → 200 `changed: false`, the
        provisional title is kept, and the row is `unusable` **with its cost**. The user
        isn't charged.
  - [ ] **Rename races:**
    - rename first, then POST title → 409, with no proxy call and no log row
    - rename **during** the call (the mock renames, then returns) → 409, the user's
      title kept, and the row is `superseded` with its cost
  - [ ] **Delete during the call** → 404 and a `chat_deleted` row with `conversation`
        NULL. The ledger is unchanged.
  - [ ] **Double request:** a second POST while `generating` → 409 with no proxy call.
  - [ ] Existing chats (source `user`) → 409. Another user's chat → 404. Logged out →
        401. GET → 405.
  - [ ] `clean_title` unit cases: quotes, `**Bold**`, `# Heading`, "Title: X", a
        trailing period, multiple lines, 80 characters → 60 with `…`, and the unusable
        cases.
  - [ ] Titles render **escaped** in the header and sidebar (e.g. `<b>x</b>` shows
        literally).
  - [ ] Script hooks (string checks): `requestTitle` is called after the `main_html`
        swap and on load when `data-title-source="provisional"`; it sends `X-CSRFToken`;
        and it never calls `updateBalance`.
- [ ] Commit.

## Step 4: `feat: add Memories on My Profile`

- [ ] `accounts.Memory`: `user` FK (CASCADE, `related_name="memories"`), `text`
      (`CharField(max_length=200)`), `created_at`, ordered `created_at, id`.
- [ ] `MemoryForm`: `text` stripped, required, at most 200 characters. Its `clean()`,
      given the user, rejects:
  - an 11th memory: "You can keep up to 10 memories. Delete one to add another."
  - a case-insensitive duplicate: "You already have that memory."
- [ ] Endpoints (`accounts/views.py`, `login_required` and `require_POST`):
  - [ ] `POST /profile/memories/` (`memory_add`):
    - valid → 302 to `/profile/#memories`, with "Memory added."
    - invalid → **400**, the full My Profile with the error and the draft, through
      `render_profile(status=400, memory_form=form)`
  - [ ] `POST /profile/memories/<id>/delete/` (`memory_delete`) → **immediate** delete,
        then 302 to `/profile/#memories` with "Memory deleted." Another user's memory,
        or an unknown one → **404**.
  - [ ] GET → 405. Logged out → 302 to log-in.
- [ ] `accounts.services.system_text_for(user)` (as above). `chat.services.send_message`
      uses it instead of `system_prompt_for`. The title call doesn't (it passes
      `system=None`).
- [ ] My Profile (`billing/profile.html`), a **"Memories"** section (`id="memories"`)
      right after the Global System Prompt:
  - the help text from study §3.1
  - the list, each with a **Delete** button (a POST form, `aria-label="Delete memory
    “…”"`)
  - "N of 10" beside the heading
  - the add form (a single-line input with `maxlength="200"`, and an **Add** button),
    hidden at 10 with "Delete a memory to add another."
- [ ] **Per-message estimate** (study §3.3), under the prompt and memories: "Your system
      prompt and memories add about N tokens to every message (≈ $X with Claude Haiku,
      $Y with GPT-5.6 Luna, $Z with Gemini Flash). Estimate."
  - It uses `ceil(len(system_text) / 4)` and `reply_cost_micros(N, 0, …)` for each
    **active** model.
  - It's shown only when a prompt or memories exist.
  - It's labeled as an estimate.
  - It isn't a charge, and **"Spent" and the other totals are unaffected.**
- [ ] Admin: a read-only **"Memories"** inline on the user admin, like the Global System
      Prompt inline.
- [ ] Tests:
  - [ ] Add → 302 and stored stripped. The profile lists it with a Delete button and
        "1 of 10".
  - [ ] Validation → 400 with nothing stored:
    - empty or whitespace-only
    - 201 characters
    - an 11th memory (10 exist)
    - a case-insensitive duplicate
  - [ ] Delete → 302, gone immediately, with no confirmation page (the POST alone
        deletes). Another user's memory → 404, and it still exists. GET → 405.
        Anonymous → 302.
  - [ ] **Sent in every chat, for each provider:**
    - memories only → the system field is exactly the memory block, in each provider's
      format
    - prompt plus memories → the prompt, a blank line, then the block
    - neither → no system field at all
    - read at send time: adding or deleting affects the next message in an existing chat
  - [ ] Isolation: another user's memories are never sent. The title call carries no
        system field even when memories exist.
  - [ ] The per-message estimate is shown with the right numbers for a known text
        length, hidden when there's nothing to send, and leaves "Spent" unchanged.
  - [ ] The admin user page shows the Memories inline, read-only.
- [ ] Commit.

## Step 5: `chore: update README for automatic titles and Memories`

- [ ] Using the app:
  - [ ] New chats get a short **automatic title** a moment after the first reply. It's
        free: it costs nothing and doesn't appear in your usage. Renaming always wins,
        and without JavaScript the first line of your message stays as the title.
  - [ ] **Memories** on My Profile: up to 10 notes of 200 characters, sent with every
        message to every model, counted as input tokens (with the estimate shown there).
        Delete any time.
- [ ] Admin: "Title generations (app cost)" shows what automatic titles cost the app.
- [ ] Update the status note to loop 7.
- [ ] Commit.

## Step 6: Verify (no commit)

- [ ] `check` passes. `makemigrations --check` is clean after the two committed
      migrations. All tests pass with no real HTTP, and `requirements.txt` is unchanged.
- [ ] `migrate` on the dev DB: it applies the two migrations. Existing chats become
      `title_source="user"`. Never reset.
- [ ] **Real proxy, each of the three models** (on a throwaway DB, JSON mode, one retry
      per call; the keys are checked without printing them):
  - [ ] A new chat's first reply, then `POST …/title/` → 200 with a sensible 3–6-word
        title. The `TitleGeneration` row's cost equals the formula at that model's
        price.
  - [ ] **The user's balance and ledger are unchanged by the title call.** Only the
        reply's charge exists.
  - [ ] Memories ("Always answer in exactly one sentence", "I'm a student") plus a
        Global System Prompt are accepted by all three providers, and the replies
        visibly follow them.
- [ ] **Browser check** (headless Chrome over DevTools; `uitest` on the dev DB, already
      authorized):
  - [ ] New chat → the first reply arrives as before. **The sidebar and header switch
        from the first-line title to the generated title without a reload**, the nav
        balance changes only by the reply's cost, and My Profile shows no title cost.
  - [ ] My Profile: add two memories (they appear with "2 of 10" and the estimate),
        delete one (gone immediately), and try a 201-character one (the error shows,
        with 400).
  - [ ] Screenshots of the new chat before and after its title, and of My Profile's
        Memories section at 1280px and 375px. **Look at them.**
  - [ ] Admin: "Title generations (app cost)" lists the attempts with costs and a total.
- [ ] `git status` is clean. `git log main..loop7-titles-memories --oneline` shows five
      commits. Stop and wait for **rendezvous**.

## Done when

- Every new chat gets a title attempt after its first reply, from its own model, in a
  separate request.
  - The first reply's latency is unchanged, and the title updates in the header and
    sidebar without a reload.
  - A failure keeps the first-line title. A rename always wins, and there are no
    retries.
- Title calls are **free and invisible to users:** there's no ledger row and no balance
  change, and nothing on My Profile, in the credit history or in the nav. Their tokens
  and cost are recorded in the admin-only "Title generations (app cost)".
- Users can keep up to **10 memories of 200 characters** on My Profile, deleted
  immediately. They're sent with the Global System Prompt to every provider, with the
  per-message token estimate shown, and never sent with title calls.
- My Profile keeps one replies-only "Spent", and every reconciliation still holds. No
  new dependencies.
