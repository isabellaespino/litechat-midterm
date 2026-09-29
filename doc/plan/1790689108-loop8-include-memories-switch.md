# Plan: Loop 8: "Include memories" switch per chat

- **Date:** 2026-09-29 (Unix 1790689108)
- **Source:** the user's decisions. **There's no study**: the decisions below were made
  directly. It builds on loop 7's Memories (wiki `billing.md#memories`, `chat.md`).
- **Branch:** `loop8-memories-switch`, off `main`. Don't merge during execute. Wait for
  the rendezvous command.
- **Decisions (from the user):**
  1. An **"Include memories" switch next to the message box** lets users choose **per
     chat** whether their memories are sent.
  2. The setting is **saved per chat**.
  3. **New chats start with it on.**
  4. It can be **changed at any time** in a chat, and it **applies from the next
     message**.
  5. When it's **off**, memories aren't sent, but the **Global System Prompt still is**.
  6. It must **work without JavaScript, as a normal form control.**
  7. The switch **only appears when the user has at least one memory.**
  8. **Automatic titles still never include memories** (or the prompt).
  9. **Charging and everything else stay the same.** Tests must mock the proxy.
- **Unchanged:**
  - Charging (the actual cost from the reported usage) and the ledger.
  - The 402 block, status codes, and both response modes.
  - The title flow (`system=None`), the memory limits and endpoints, and the
    per-message estimate on My Profile.
  - No new dependencies. **One migration** (`chat`).

## How it works

- **The field:** `Conversation.include_memories = BooleanField(default=True)`.
  - The migration sets **existing chats to `True`**. That matches loop 7's behavior,
    where memories were always sent, so nothing changes for existing chats until a user
    flips the switch.
- **The switch is part of the composer form** (the same `<form class="composer">` as the
  message).
  - It's a native checkbox, `<input type="checkbox" name="include_memories" value="1">`,
    wrapped in a `<label>` reading "Include memories".
  - A hidden marker, `<input type="hidden" name="memories_switch" value="1">`, is
    rendered **only when the switch is shown**.
  - Browsers don't submit an unchecked checkbox, so the marker is what tells "switched
    off" (marker present, checkbox absent) apart from "no switch on the page" (marker
    absent).
- **Resolving the setting for a send** (`MessageForm.include_memories_for(conversation)`):
  - marker present → `"include_memories" in POST`
  - marker absent (the user has no memories, so no switch was shown) → **unchanged**:
    the chat's saved value, or `True` for a new chat
- **When it applies:** to **the message sent with it, and every later one** ("applies
  from the next message"). The value is **saved on the chat when that send succeeds**,
  in the same transaction as the messages and the charge.
  - A send that fails (400, 402, 502 or 503) saves nothing, exactly as today. The
    re-rendered page keeps the posted checkbox state along with the draft, so a resend
    carries it.
- **Without JS** it's an ordinary checkbox in an ordinary form: toggle it, press Send,
  and the full page reloads with the saved state.
- **With JS** nothing changes: the script already builds `new FormData(form)` before
  disabling the composer, so the checkbox and marker ride along. After a new chat's
  first reply, the swapped-in `main_html` renders the switch from the saved value.
- **Toggling without sending isn't saved.** Reloading shows the chat's saved setting
  again. That's what "applies from the next message" means here: the setting is saved
  together with the message it first applies to, so what the switch shows is always
  what the next send uses. (Saving on toggle would need a separate endpoint, plus a
  second no-JS form or button next to the message box. Not included; see Risks.)
- **Sending:** `send_message(…, include_memories=True)` passes it to
  `accounts.services.system_text_for(user, include_memories=…)`:
  - on → prompt, a blank line, then the memory block (loop 7, unchanged)
  - off → **the Global System Prompt only**
  - off with no prompt → `None`, so **no system field at all** for every provider
- **Titles:** `generate_title` keeps `system=None`, so neither memories nor the prompt
  are sent, whatever the switch says.

## UI

- **Where:** in `_composer.html`'s `.composer-row`, **next to the message box**:
  - New chat: the model picker, the switch, the textarea, then Send
  - Existing chat: the model chip, the switch, the textarea, then Send
- **Shown only when** `user_memory_count > 0`.
  - `chat_context` adds `user_memory_count`, one `count()` query.
  - It's also added when the JSON new-chat branch renders `_main.html`.
- **Checked state:**
  - New chat → checked
  - existing chat → `conversation.include_memories`
  - after a failed POST → the posted value
- **Label and help:** "Include memories", with a small muted count ("2") and a `title`
  reading "Send your memories from My Profile with this chat's messages".
  - It's a real `<label for=…>`, so the whole label toggles it and screen readers
    announce it.
  - It's keyboard-focusable, with the loop 6 gold focus ring.
- **Styling:** a compact switch-styled checkbox using the existing palette tokens
  (`--navy-700` when checked, `--line` when off, and a white knob). It's drawn with CSS
  on the native checkbox (`appearance: none`), so it stays a real form control. There
  are no new colors, so `ContrastTests` is unchanged. The label text is `--text` on
  `--page` (15.4:1).
- **Phones:** the composer row already wraps at 720px and below. The switch takes its
  own line above the textarea, with no horizontal scroll.
- **My Profile's estimate** now reads: "Your system prompt and memories add about N
  tokens to every message in chats with memories switched on (≈ …). Chats with the
  switch off send only your system prompt. Estimate." The numbers are unchanged, since
  it stays an upper bound.

---

## Step 0: Branch

- [ ] `git switch -c loop8-memories-switch` from an up-to-date `main`.

## Step 1: `feat: save an include-memories setting per chat`

- [ ] `Conversation.include_memories = models.BooleanField(default=True)`. The migration
      is `chat.0004_include_memories`, and existing rows become `True`.
- [ ] `accounts.services.system_text_for(user, include_memories=True)`. When it's
      `False`, the memory block is skipped (the prompt is still included). Return `None`
      when nothing is left.
- [ ] `chat.services.send_message(user, llm_model, text, conversation=None,
      include_memories=True)`:
  - Pass it to `system_text_for`.
  - A new chat is created with `include_memories=…`.
  - For an existing chat, save it in the **same atomic block** as the exchange, with
    `conversation.include_memories = …` and `save(update_fields=["updated_at",
    "include_memories"])`.
  - The in-flight-delete paths are unchanged: nothing is saved on the chat, and the
    charge is kept.
- [ ] Conversation admin: show "Include memories" (read-only), and add it to
      `list_filter`.
- [ ] Tests (`chat/tests.py`, `accounts/tests.py`, mocking `llm.http.requests.post`):
  - [ ] `system_text_for(user, include_memories=False)`: prompt only; `None` with no
        prompt; memories-only users get `None`. `True` is unchanged from loop 7.
  - [ ] `send_message(…, include_memories=False)` for **each provider**:
    - with a prompt: the system field is exactly the prompt, with no "About the user"
    - without a prompt: **no system field at all**
    - a new chat saves `include_memories=False`
    - an existing chat's value is updated in the same send
  - [ ] Existing chats created before the migration (the model default) are `True`,
        and memories are still sent to them.
  - [ ] **Charging is unchanged:** the same reply costs the same whatever the switch
        says (the charge comes from the reported usage). `balance == sum(ledger)`.
  - [ ] **Titles:** with memories present and the switch **on**, the title call still
        has no system field.
- [ ] Commit.

## Step 2: `feat: add an Include memories switch next to the message box`

- [ ] `chat/forms.py`: `MessageForm` (and so `NewChatForm`) gets
      `include_memories = BooleanField(required=False)` and `memories_switch =
      BooleanField(required=False, widget=HiddenInput)`, plus
      `include_memories_for(conversation)` as defined above.
- [ ] `chat/views.py`:
  - `chat_new` and `chat_detail` pass `form.include_memories_for(conversation or None)`
    to `send_message`.
  - `chat_context` adds `user_memory_count`, and passes it through the JSON new-chat
    `main_html` render too.
  - Status codes and error paths are unchanged.
- [ ] `templates/chat/_composer.html`:
  - Inside `.composer-row`, **only if `user_memory_count`**, add the label and checkbox
    plus the hidden `memories_switch` marker.
  - The checked state: posted value (bound form) → saved value (existing chat) →
    `True` (new chat).
  - The switch is **not** disabled when out of credit or while a reply is pending. It's
    only a setting, and the server still blocks at 402.
- [ ] CSS in `base.html`: `.memory-switch` and the switch-styled checkbox (§UI). The
      checked state is `--navy-700`, and focus uses the existing ring. Nothing is added
      to the `:root` tokens.
- [ ] My Profile estimate clause (§UI).
- [ ] **No change to `_script.html`.** Tests assert that `new FormData(form)` still comes
      before `setBusy(form, true)`, so the switch is submitted.
- [ ] Tests (`chat/tests.py`, `SwitchTests`):
  - [ ] **Visibility:** with no memories there's no switch and no marker, on New chat or
        an existing chat. With 1 or more memories, both are present.
  - [ ] **Default on:** New chat renders it **checked**.
  - [ ] **Off in a new chat (form mode):**
    - the POST has the marker and no checkbox → 302
    - the chat is saved with `include_memories=False`
    - the proxy request carries the Global System Prompt only (checked per provider)
    - the chat page renders the switch **unchecked**
  - [ ] **Change in an existing chat:**
    - on to off: that very send carries no memories, the setting is saved, and the page
      shows it unchecked
    - back on: the next send carries them again
    - both in **form mode and JSON mode** (`HTTP_ACCEPT` JSON, where the script's
      `FormData` posts the same fields)
    - after a JSON new-chat first reply, `main_html` renders the switch with the saved
      state
  - [ ] **No switch shown** (the user deleted all their memories): a POST without the
        marker leaves the chat's saved value untouched, e.g. a chat saved `False` stays
        `False`. There are no memories to send either way.
  - [ ] **Failures save nothing:**
    - a 400 (empty message), 402 (balance 0) or 502 (proxy 500), each with the switch
      turned off
    - the DB value is unchanged
    - the re-rendered composer shows the **posted** state (unchecked), with the draft
    - the proxy isn't called for the 400 or 402
  - [ ] **No-JS form control:** the checkbox has `name="include_memories"` and a `<label
        for>`, sits inside `form.composer`, and the marker is a hidden input in the same
        form.
  - [ ] **Script unchanged:** `new FormData(form)` comes before `setBusy(form, true)`.
  - [ ] **Titles:** after a new chat started with the switch **on**, `POST
        /chats/<id>/title/` → the proxy body has no system field and no memory text.
  - [ ] My Profile's estimate text includes the new clause, and "Spent" is unchanged.
- [ ] Commit.

## Step 3: `chore: update README for the Include memories switch`

- [ ] Using the app:
  - The switch next to the message box (shown once you have a memory), on by default.
  - It's saved per chat, and applies from the next message you send.
  - Off means your memories aren't sent, but your Global System Prompt still is.
  - Titles never include either.
- [ ] Update the status note to loop 8.
- [ ] Commit.

## Step 4: Verify (no commit)

- [ ] `check` passes, `makemigrations --check` is clean (after `chat.0004`), all tests
      pass with no real HTTP, and `requirements.txt` is unchanged.
- [ ] `migrate` on the dev DB: it applies `chat.0004`, and every existing chat has
      `include_memories=True`. Never reset.
- [ ] **Real proxy, each of the three models** (on a throwaway DB, JSON mode, one retry
      per call; the keys are checked without printing them):
  - Add the memory "Always answer in exactly one sentence." Set the Global System Prompt
    to "Mention the word 'banana' somewhere in every reply."
  - **Switch on:** one sentence, containing "banana".
  - **Switch off (same chat, next message):** usually more than one sentence (the
    memory isn't sent), and **still contains "banana"** (the prompt still is).
  - Report the outcomes as observed. Every provider is DeepSeek Flash underneath, so
    following the prompt is likely but not guaranteed. What must hold is what the
    request carried, which the mocked tests prove, and the charges matching the formula.
- [ ] **Browser check** (headless Chrome over DevTools; `uitest` on the dev DB, already
      authorized):
  - [ ] With no memories, there's no switch in the composer.
  - [ ] Add one memory. New chat shows the switch **checked**, next to the message box.
  - [ ] Turn it off and send with Enter → the reply arrives with no reload. After a
        reload the switch is **off**, and the dev DB chat has `include_memories=False`.
  - [ ] Turn it back on and send → after a reload it's **on**.
  - [ ] **With JavaScript disabled:** toggle the switch, click Send, and the full page
        reloads with the new state saved.
  - [ ] Keyboard: Tab reaches the switch, Space toggles it, and the gold focus ring
        shows.
  - [ ] Screenshots at 1280px and 375px (switch on, and switch off). **Look at them.**
        Run the contrast audit on the chat page, and check there's no horizontal scroll.
  - [ ] Clean up: delete `uitest`'s memory afterwards.
- [ ] `git status` is clean. `git log main..loop8-memories-switch --oneline` shows three
      commits. Stop and wait for **rendezvous**.

## Risks

- **Toggling without sending isn't persisted** (see "How it works"). This is deliberate:
  the switch is part of the message form, so it works without JS and is always exactly
  what the next send uses.
- **A deleted-then-re-added memory** doesn't change any chat's setting. Chats that were
  switched off stay off.
- **The profile estimate is an upper bound** once some chats have memories switched
  off. The wording says so.

## Done when

- Users who have at least one memory see an **"Include memories"** switch next to the
  message box. It's on for new chats, saved per chat, and changeable at any time,
  applying from the next message.
- Off means the Global System Prompt is sent without memories. Off with no prompt means
  there's no system field at all. This holds for every provider.
- It's a normal form control that works without JavaScript. The script needed no
  changes.
- Titles never include memories or the prompt. Charging, the ledger, the 402 block and
  status codes are unchanged, and the proxy is mocked in every test.
