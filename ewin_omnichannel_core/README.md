# EWIN Inbox — Core

The channel-agnostic heart of **EWIN Inbox**. It owns the whole conversation
domain — identities, conversations, messages, routing, the retry queue, the
Discuss mirror and reporting — and knows nothing about any specific messaging
provider. Every channel (Telegram, Email, Live Chat, WhatsApp, Messenger,
Instagram, Viber) is a thin addon that implements one contract against this
core.

Depends on `base`, `mail`, `contacts`.

## What it does

- **One inbox for every channel.** Conversations from all connected accounts
  land in the same list, with the same assignment, tagging, priority and
  reply tooling regardless of where the message came from.
- **Contact matching.** An inbound message is resolved to an
  `omnichannel.identity` (the customer as the provider knows them) and, from
  there, to a `res.partner`. The same person writing again reuses the existing
  identity, contact and open conversation — no duplicates. The conversation
  header shows the identity's channel address beside the contact name, so a
  display name shared by two people is never ambiguous.
- **Replying takes the conversation.** Answering an unassigned conversation
  assigns it to you — there is no separate Take click on the normal path. An
  internal note does not take it (writing a note is not answering the
  customer), and an existing assignment is never overridden, so a colleague's
  conversation stays theirs. The **Take** button remains for claiming a
  conversation without writing anything yet.
- **Realtime.** New messages and assignment changes are pushed over the bus to
  the assigned operator, so the open thread and the conversation list update
  without a manual reload.
- **Counters on the menu.** **Inbox** wears a grey badge with the number of
  inbound messages in conversations nobody has taken, and **My Conversations**
  a red one with what is unread in the conversations assigned to the reader.
  Both move on their own over the bus — the grey one for every operator at
  once, the red one for its owner — so nobody has to walk the menu to find out
  whether it holds anything new.
- **Discuss mirror.** Every conversation is mirrored into a `discuss.channel`,
  so operators get native Odoo unread badges and notifications, and can reply
  either from the Inbox composer or straight from Discuss — both paths reach
  the customer. The channel is authorized to the operator group, and a reply
  typed there is only forwarded to the customer if its author may write the
  conversation.
- **Delivery lifecycle.** Messages carry a real state machine
  (`received` → `scheduled` → `queued` → `processing` → `sent` → `delivered` →
  `read`, plus `failed` / `cancelled`), so a reply that never arrived is
  visible instead of silently lost.
- **Retry queue.** The first send attempt is synchronous, inside the operator's
  own request. Only failures fall back to `omnichannel.job` with exponential
  retries, so a healthy send is instant and a flaky provider does not block
  the UI.
- **Quick replies.** Canned templates with a shortcut, optionally scoped to one
  channel, rendered against the current conversation.
- **Close reasons.** Closing a conversation can ask the operator why, from an
  admin-editable list of preset answers plus a free-text comment. The question
  is off by default and can be made optional or mandatory — mandatory means a
  conversation without an answer stays open. The reason is stored on the
  conversation and groupable in the Inbox and the reports.
- **Reporting.** Pivot and graph views over conversations and message volume,
  including a stored first-response time per conversation.

## Data model

| Model | Purpose |
|---|---|
| `omnichannel.channel` | A channel *type* (Telegram, Email, …). Created by the connector addons as data. |
| `omnichannel.account` | One configured provider account. Holds credentials, defaults, the per-account `webhook_uuid`, and a `draft`/`connected`/`error`/`disabled` state. |
| `omnichannel.identity` | A customer as one provider knows them. Unique per `(account, external_id)`; links to `res.partner`. Its computed `handle` is the channel address to show an operator — `email`, `@username`, `phone` or the raw `external_id`, in that order. |
| `omnichannel.conversation` | A thread with one customer on one account. States `new`/`open`/`pending`/`closed`, priority, team, operator, tags, close reason, and the linked `discuss.channel`. Inherits `mail.thread`. |
| `omnichannel.message` | A single message, inbound or outbound, with type, body, attachments, provider ids and the delivery state machine — including `scheduled`, an operator-deferred reply waiting for its send time. |
| `omnichannel.event` | Raw provider events, deduplicated per `(account, external event id)` — this is what makes redelivered webhooks harmless. |
| `omnichannel.job` | The retry queue: `pending`/`running`/`done`/`failed`, `next_run_at`, `retry_count`, `max_retries`. |
| `omnichannel.team` | An operator team, used for routing and for the "my team" scope. |
| `omnichannel.tag` | Free-form conversation labels. |
| `omnichannel.close.reason` | Preset answers for "why was this closed". Shipped with five defaults, editable under Configuration. |
| `omnichannel.template` | Canned reply with a shortcut, optionally channel-specific. |
| `omnichannel.error.log` | Operator-readable failure log, with the technical detail kept alongside the friendly text. |

`res.partner` gains `omni_source`, `omni_external_id`, `omni_username`,
`omni_first_contact`, the reverse `omni_identity_ids` and `omni_conversation_ids`,
plus a **Conversations** smart button on the contact form, so a contact created
from a chat still looks like an ordinary Odoo contact.

## How a message flows

**Inbound.** The connector's webhook (or poll) hands the core a *normalized
event* — a plain dict, identical in shape for every provider. From there
everything is channel-agnostic:

```
provider → connector.parse_webhook()
         → routing_service.process_event()
             → identity_service.find_or_create()      # customer identity
             → identity_service.ensure_partner()      # res.partner link
             → conversation_service.find_or_create()  # open or reopen a thread
             → connector.download_attachment()        # optional, per account
             → message_service.create_inbound()       # + Discuss mirror
```

**Inbound attachments.** What a connector downloads is stored as an
`ir.attachment` and then anchored on the conversation (`res_model` / `res_id`),
and the Discuss mirror is posted as the system user whenever no real user is
behind the request. Both halves are load-bearing. `message_post` keeps only the
attachments the *calling user* drafted on a composer, and a webhook runs as the
public user — the customer's file would be dropped from the very message that
announces it. And an attachment that hangs off no record is readable by its
creator alone (`ir.attachment.check`), which leaves the operator with a broken
thumbnail while a settings admin — exempt from that rule — sees the file and
cannot reproduce the complaint. Anchored on the conversation, access to a file
is access to the conversation it arrived in: the same answer in the inbox, in
the mirror and in the customer's chatter, all pointing at one binary.

**Outbound.** An operator reply — from the Inbox composer *or* from the mirrored
Discuss channel — becomes an `omnichannel.message` and is sent through the same
door:

```
message_service.create_outbound()
  → routing_service.deliver_outbound()   # first attempt, synchronous
      → connector.send_message()
      └ retriable failure → omnichannel.job → retried by cron
        terminal failure  → message state 'failed' + error log entry
```

Replies typed directly in Discuss are caught by an override of
`discuss.channel.message_post`. The core's own mirror posts carry an
`omni_mirror` context flag and are skipped, which is what keeps the mirror from
echoing messages back to the customer in a loop.

## Scheduled replies

An operator can defer a reply instead of sending it: pick a time in the
composer and **Send** becomes **Schedule**, parking the message until then. A
cross beside the time takes it back and the button returns to Send. One
primary button with one meaning at a time — there is only ever one thing to do
with what is in the composer, and offering two invites the wrong one. The
keyboard shortcut follows the button, so Enter never means something the
screen does not say.

`scheduled` is a state on the message, one step ahead of `queued` — not a
separate model and not a job-queue row — carrying `scheduled_at` (the send
time) and `scheduled_by` on the row itself. Rescheduling is therefore an
ordinary write, which is what makes "editable until it is sent" cheap to
guarantee.

```
message_service.create_outbound(scheduled_at=…)   # parks the row, sends nothing
  └ Omnichannel: Send scheduled messages (cron, 1 min)
      → message_service.release_scheduled()
          → Discuss mirror + chatter copy + conversation timestamps
          → routing_service.deliver_outbound()    # the ordinary send path
```

Nothing is mirrored to the thread or the customer's card while the reply
waits: both must keep showing what the customer has actually seen. For the
same reason `first_operator_message_at` — and so `first_response_seconds` — is
set when the message really goes out, not when it was planned. `sent_at` and
`scheduled_at` both survive delivery, so the row still carries what was
planned alongside what actually happened.

`release_scheduled` is the single door out of `scheduled`, whether the cron
calls it or an operator presses **Send now**. A conditional
`UPDATE … SET state = 'queued' WHERE id = %s AND state = 'scheduled'
RETURNING id` decides who releases a given row, so a caller that loses the
race gets `False` back and stops — never a second delivery. The same method
opens with an access check, so the operator-facing action is governed by the
ordinary record rules while the cron, running as the system, is not blocked
by them.

The cron, **`Omnichannel: Send scheduled messages`**, does not lock its whole
batch at once. It first collects the due rows with a plain, lock-free
`SELECT`, then — immediately before releasing each one — re-takes that single
row with `SELECT … FOR UPDATE SKIP LOCKED` and re-checks `scheduled_at <= now`
at that moment. The per-row re-check is what catches an operator who moved the
send time while a backlog was draining; a lock held across the whole batch
would not, because a commit releases every lock a transaction holds at once,
not one row at a time. `SKIP LOCKED` is what keeps two overlapping cron runs
off each other's rows instead of one blocking on the other.

- **Visible, without taking the chat's room.** A **Scheduled *n*** tab appears
  above the thread as soon as a reply is waiting and disappears when none is —
  the chat itself is never shortened. Opening it swaps the thread for the
  waiting replies drawn the same way: a bubble each, with the avatar and name
  of whoever scheduled it, grouped under the day it is due. Its count follows
  the same `omni.inbox` bus signal the thread does, so a reply the cron has
  just released leaves the tab on its own rather than at the next page reload.
  The pane reads its rows straight from the server rather than through a
  one2many of the conversation, because a one2many can only be refreshed by
  reloading the whole record — which would throw away whatever is half-typed in
  the composer. The conversation list carries a clock badge, and
  **EWIN Inbox → Scheduled** shows every pending send across all conversations.
  The Message Volume report
  excludes the `scheduled` and `cancelled` states by default — a removable
  "Real Volume" filter, not a hard domain, so a reply that has not gone out —
  or never will — does not inflate outbound volume, and the Scheduled and
  Cancelled filters on the same search view stay reachable for a reader who
  wants to see them.
- **Editable until it leaves.** Wording and send time can both be changed, and
  the reply can be sent early or cancelled, while the message is `scheduled`;
  afterwards `write` refuses. The rule lives in the model, not in the view,
  because any client can write over RPC.
- **Edited in the composer it was written in.** Clicking a waiting reply loads
  it back into the composer — same textarea, same quick replies, same
  send-later control. The primary button becomes **Reschedule** and Send is
  not offered at all: the reply already exists, so "send it now" belongs on the
  reply itself, in the pane. The keyboard shortcut applies the edit too, for
  the same reason — a second, hidden meaning for the same key is how a
  deferred reply goes out hours early. Called over RPC anyway, Send during an
  edit still delivers *that* row rather than leaving a duplicate behind.
  `composer_editing_message_id` is what holds reply and composer together, and
  an amber strip above the composer says so with a way back out.
- **Nothing outlives the reply.** A reply that leaves while it is open in a
  composer — cancelled from the pane, released by the cron — takes the editor
  down with it: `_release_composer_edit` clears the link from whichever
  conversation holds it, so no banner is left announcing an edit of something
  that no longer exists. Only the link goes; the operator's words stay in the
  composer, ready to be scheduled again as a new reply.

  `_apply_scheduled_edit` takes the row lock through `_check_reschedulable`
  before writing. That guard is load-bearing on the **Send** path in
  particular: Send changes the wording without touching the send time, so the
  model's own reschedule check never runs, and without the explicit lock an
  edit could land on a reply the cron delivered a moment earlier. The
  operator's text stays in the composer when that happens — it is theirs to
  schedule again, not ours to discard. Files already attached to the reply are
  kept and anything added while editing is appended: the composer never held
  them, so their absence from it is not a request to delete them.
- **Cancelling keeps the row** (`cancelled`): operators hold no unlink right on
  messages, and a decision not to send is worth recording.
- **Anyone who can see the conversation** may reschedule or cancel, author or
  not — otherwise a colleague's pending replies are stuck when they are away.
  Every action is posted to the conversation's chatter by name.
- **Accuracy is one minute**, bounded by the cron interval. The only rule on
  the time is that it must be strictly in the future, enforced on both create
  and reschedule.
- **A closed conversation is reopened** and the reply still goes out. Deferring
  is a commitment, and a silently swallowed reply is worse than a reopened
  thread.
- **A release that raises does not stop the batch, and is retried forever.**
  The message simply stays `scheduled` — there is deliberately no retry
  counter, since duplicating the job queue's own retry bookkeeping inside this
  cron would blur the distinction "Job queue and scheduled actions" below
  draws between the two. Each failed attempt is recorded as an
  `omnichannel.error.log` entry (category `internal`), which is the only way
  to notice a pending reply whose time has passed but never went out — the
  panel row alone looks no different from one still waiting its turn. Because
  the delivery attempt is synchronous inside the cron's own transaction, a
  crash between a successful send and that iteration's commit means the next
  tick resends it, the same trade-off the ordinary synchronous first attempt
  in `deliver_outbound` already makes.

## Menu badges

The two menus an operator lives in wear their own number, so the answer to
"is there anything new?" is on screen instead of one click away.

| Menu | Colour | Counts |
|---|---|---|
| **Inbox** | grey | inbound messages in conversations that are not closed and have no operator |
| **My Conversations** | red | unread messages in the conversations assigned to the reader |

Grey is the queue that belongs to whoever is free; red is addressed to the
reader personally, and is the one worth leaving another app for. Both are
message counts, not conversation counts, and `omni_menu_counters()` reads them
with the caller's own rights — the record rules decide what an operator is
told about.

There is no read state to subtract from the grey one: reading is a
`discuss.channel` membership, and an untaken conversation has no member, so
nothing in it has been read by anyone. Taking it — or closing it — is what
empties the number.

Neither is polled. The server pushes an empty `omni.menu.counters` over the
bus and the client asks for both numbers again:

- **to the operator group**, from `_notify_omni_event` — that is, on every new
  message, assignment and closure. `ir.websocket._build_bus_channel_list`
  subscribes every user to a channel per group they hold, so the unclaimed
  queue, which belongs to nobody and has no personal channel to aim at,
  needs no channel of its own. The ping carries no ids on purpose: it reaches
  operators whose record rules keep that conversation out of their own lists.
- **to one partner**, from `_mark_read` — reading is what makes the red badge
  fall, and the number is the reader's own.

On the client the numbers live in the `omni_menu_counters` service and the
badge is drawn by an extension of Odoo's three navbar templates
(`web.NavBar.SectionsMenu`, its `MoreDropdown` overflow and the phone
sidebar's `web.SectionMenu`). The service asks the server for nothing until
the navbar reports EWIN Inbox is the open app, so a user working in Sales pays
nothing for it. Odoo resolves OWL template inheritance in the browser, where a
target that has moved fails as a console message and an app that quietly
renders without its badges — `tests/test_menu_badge_assets.py` runs the same
lookups against the installed Odoo source, so an upgrade that renames a navbar
template fails the suite instead.

## Customer history

A conversation can be linked to the customer records it belongs to — a contact
(`res.partner`) out of the box, a CRM lead when `ewin_omnichannel_crm` is
installed. Every message is then copied into that record's chatter as an
internal log note, so the customer's own history holds the texts: the salesperson
reading a contact sees what was said on WhatsApp without opening the Inbox.

A contact carries both a **Conversations** smart button, which opens what is
already linked, and a **Link Conversation** button, which opens a picker and
attaches existing ones — the button an operator reaches for when they went
looking for a conversation on a contact that has none yet, which is exactly
when it must not be hidden. The picker itself,
`omnichannel.conversation.link.wizard`, is a single shared model: it writes a
`partner_id` by default, and a bridge overriding its `_link_values()` hook can
point the write at its own record instead — `ewin_omnichannel_crm` does this to
link a lead, reusing the same wizard and the same write-through-`write()`
guarantee, with its own picker form, rather than shipping a second,
near-identical wizard.

`omnichannel.history.service` owns those copies:

| Method | When | How |
|---|---|---|
| `mirror(message)` | a message is created | `message_post` with `mail.mt_note`, so the chatter refreshes live and no follower is emailed |
| `backfill(conversation, targets)` | a link is added | one batched `mail.message` create, ledger rows included |
| `purge(conversation, targets)` | a link is removed, or the conversation or one of its messages is deleted | deletes exactly the copies that link created |

Both paths produce the same copy: the timestamp of the message it represents —
a history stamped "now" reads as a single event rather than a conversation —
and the very same `ir.attachment` records, so one binary serves however many
records the history reaches. The live path links those attachments after
posting rather than passing them to `message_post`, which keeps only the
attachments the *calling user* drafted on a composer: an inbound webhook has no
real user behind it, and `sudo()` raises privileges without changing who is
calling.

Copies are tracked on `omnichannel.message.history_message_ids` (its other end
is `mail.message.omni_message_ids`, which is what lets a backfill write the
ledger in the same create as the copies). That ledger is what lets a
mis-attributed conversation be re-pointed without leaving one customer's texts
on another customer's card, and what makes deleting a message or a conversation
take its copies with it. `mail.mt_note` is an internal subtype, so the copies
are never visible to a portal user reading their own contact record.

Which records receive the history is a per-installation question, so core does
not hard-code it:

```python
class OmnichannelConversation(models.Model):
    _inherit = "omnichannel.conversation"

    @api.model
    def _history_link_fields(self):
        return super()._history_link_fields() + ["lead_id"]

    def _history_targets(self):
        return super()._history_targets() + [
            record for record in (self.lead_id,) if record]
```

That is the whole of what `ewin_omnichannel_crm` has to say about mirroring;
`write` and `unlink` in core diff the targets by `(model, id)` and call the
service themselves.

`ewin_omnichannel_crm` implements exactly that override to add CRM leads as a
second destination — see its own README.

Installing or upgrading core backfills the history of every conversation
already linked to a contact, so an existing database shows its past
immediately rather than only mirroring from the moment of install onward. It
runs once through `post_init_hook` on a fresh install and through
`migrations/18.0.1.1.0/post-migrate.py` on an upgrade, it is idempotent, and
it logs its progress — on a database with years of conversations it is the
slow part of the install.

Core's own pass only ever sees `_history_targets()` as core itself defines
it: Odoo migrates one module at a time, in dependency order, and runs each
module's post-migrate right after that module's own models are registered —
before a dependent like `ewin_omnichannel_crm` has extended anything. A
conversation linked to a lead and nothing else is walked past by core's
backfill, contact-only, with no error. Reaching it takes the bridge's own
pass, over the same conversations, once its own override is in force — see
`ewin_omnichannel_crm`'s README.

## The connector contract

A channel addon implements the `omnichannel.connector` AbstractModel and
registers itself as `omnichannel.connector.<channel_code>`. The core resolves it
by name from the account — it never imports a connector directly.

| Method | Responsibility |
|---|---|
| `validate_configuration` / `connect` / `disconnect` | Credential checks and the account's connected state |
| `register_webhook` / `remove_webhook` | Provider-side callback registration (no-op for polling channels) |
| `parse_webhook` | Raw provider payload → list of normalized events |
| `normalize_incoming_message` | Provider message → the universal message shape |
| `send_message` / `send_attachment` | Outbound delivery |
| `download_attachment` | Provider media → `ir.attachment` |
| `get_external_profile` | Customer profile lookup, where the provider offers one |
| `handle_provider_error` | Provider error → operator-friendly text + error log |
| `_notify_ui` | The toast a button answers with — implemented here, not per connector |

Unimplemented methods raise `NotImplementedError`, and the core tolerates that
where the capability is genuinely optional — a polling channel has no webhook
to register, and a provider without media has nothing to download.

Two rules bind the methods a button reaches — the account form's `connect`,
`register_webhook`, `remove_webhook` and whatever else a channel adds, and a
wizard's send just the same:

- **A provider failure is reported by returning, not by raising.** The failure
  path records what went wrong on the account — the error state, `last_error`,
  a journal row — and Odoo commits a request only when it returns successfully.
  Raising rolls that record away with the rest of the request, so the operator
  reads the message and the form behind it comes back looking untouched. A
  method with two callers — one that catches, like the poll cron isolating one
  account from the next, and one that does not, like a button — keeps raising
  and gets a thin wrapper for the button to call.
  `_notify_ui(text, kind="danger")` — defined once on the contract, so every
  connector answers the same way — returns a sticky red toast that says the
  same thing and lets the write land. A `UserError` stays right for what the
  user must fix *before* anything is attempted — a missing credential, a
  refused setting — because nothing has been written yet.
- **The secret of an inbound callback is compared with
  `ewin_omnichannel_core.tools.security.secret_equals`**, never with
  `hmac.compare_digest` directly. It compares bytes and refuses an unset
  expected value; SECURITY.md explains what each of those prevents.

## Job queue and scheduled actions

- **`Omnichannel: Process job queue`** — every minute. Runs due jobs, applies
  exponential backoff, and calls the target model's
  `_on_job_permanent_failure` hook once retries are exhausted. The queue itself
  stays channel-agnostic: it knows it may call that hook, not that it is
  dealing with messages.

  A job row names a model and a method, and this cron runs as superuser — so a
  model has to **publish** a method before the queue will call it, by listing
  the name in a `_job_methods` frozenset. The connector contract publishes
  `parse_webhook_job`, the routing service publishes `send_outbound`, and a row
  naming anything else fails terminally instead of being retried. Producers
  enqueue through `sudo()`; no group holds write on `omnichannel.job`.
- **`Omnichannel: Cleanup old events and logs`** — daily. Trims processed
  events and stale log entries so the idempotency table does not grow forever.
- **`Omnichannel: Send scheduled messages`** — every minute. Collects the due
  rows with a lock-free `SELECT`, then re-takes and releases them one at a
  time with `FOR UPDATE SKIP LOCKED`, re-checking the send time at that
  moment — so a reschedule that lands mid-run is honoured and two overlapping
  runs never fight over the same row. See "Scheduled replies" above.

## Security

Three groups, under the **EWIN Inbox** application category:

- **Operator** (`group_omni_operator`) — works conversations; sees their own
  and their teams'. Never sees provider credentials.
- **Manager** (`group_omni_manager`) — sees every conversation in the company.
- **Administrator** (`group_omni_admin`) — configuration and credentials.

Provider secrets live on fields restricted to the admin group; connectors expose
a masked companion field so an operator can confirm *a* token is set without
reading it. That companion's compute reads the secret through `sudo()` on
purpose: it is the field the operator group sees *instead of* the secret, so
needing the access it stands in for would make the whole account form an
`AccessError` for exactly the group it was added for. Deriving a fixed-length
mask is not the access the connector's `_client()` guards. Record rules scope accounts, identities, conversations, messages,
events, teams, templates, tags, close reasons and error logs by company, and
conversations and messages additionally by operator/team for the operator role —
a message inherits its scope from the conversation it belongs to, the same
operator, unassigned, or team-member test.

Menus that read `omnichannel.*` are invisible to users outside these groups —
after installing, grant yourself **EWIN Inbox / Administrator**.

Three boundaries are worth naming, because each of them is somewhere a
reasonable reading would put the control elsewhere:

- **The mirror channel is authorized to the operator group, not to the
  conversation's scope.** `discuss.channel` expresses access as one group or as
  membership, and neither can express "the assigned operator, their team, and
  anyone the conversation is unassigned to". Restricting it to the group is
  what keeps the customer history and the internal notes away from the rest of
  the company; inside the inbox group the mirror is readable more widely than
  the conversation list is. Which conversations an operator *works* is still
  `rule_conversation_operator_scope`, and sending to the customer from the
  mirror is checked against the conversation, not against channel membership.
- **The account form's buttons ask for write on the account.** They connect,
  register webhooks and rotate credentials, all through `sudo()` inside the
  connector, and `call_button` reaches any public method on a model the caller
  can read — so the check lives in `_run_connector_action`, the one doorway
  they share, rather than in the menu that hides them.
- **An inbound message is credited to the correspondent who sent it**, not to
  the conversation's customer. Email threads on a quoted `Message-ID`, which
  anyone who has seen one message of a thread can quote; crediting the customer
  would file a stranger's words as theirs in the inbox, in Discuss, and in
  their contact and lead chatter.

## Writing a new connector

1. Create an addon depending on `ewin_omnichannel_core`.
2. Ship an `omnichannel.channel` data record with your `code`.
3. Extend `omnichannel.account` with the credential and preference fields your
   provider needs, putting secrets behind `group_omni_admin`.
4. Implement `omnichannel.connector.<code>` — at minimum `connect`,
   `parse_webhook` (or a poll cron), `send_message` and `handle_provider_error`.
5. Add a normalizer that turns the provider payload into the universal shape,
   and — for webhook channels — a public controller that authenticates the
   callback before handing it to the connector.
6. Register the channel's brand marker in `omnichannel_conversation.py`, so the
   conversation lists show it instead of the generic bubble: an entry in
   `CHANNEL_ICONS` when the bundled FontAwesome 4.7 carries the brand glyph, or
   a 128×128 PNG at `static/src/img/channel_<code>.png` listed in
   `CHANNEL_IMAGE_ICONS` when it does not (FontAwesome has no Viber or
   Messenger glyph, and a missing class renders as a blank cell rather than
   failing).
7. Override `omnichannel.account._get_public_address()` for your channel code
   — the address a customer writes to (a mailbox, `@bot`, phone, page), read
   under `sudo()`, an empty string when unknown — and call `super()` for every
   other code. The Telegram notifier names the inbox by it.

If your connector needs to react when a conversation actually closes (ending
a live session, notifying a third party, and so on), override
`_close(reason, note)`, not `action_close`. `action_close` is the button: with
the close-reason setting on `optional` or `required` it opens a wizard and
writes nothing, so any side effect hung off it fires before — or even without
— the conversation ever closing. `_close` is the one place every close, from
any source, actually goes through.

The core's `test_connector_contract.py` covers the contract itself; the shipped
connectors are the worked examples. `test_conversation.py` fails a connector
that ships no brand marker, and pins every glyph referenced against the
stylesheet Odoo actually serves.

## Out of scope

- **Bots and automation** — no chatbot, no auto-reply rules, no SLA escalation.
  Routing is account defaults plus manual assignment.
- **Skill-based or load-based routing** — teams and default operators only.
- **Cross-channel identity merge** — the same human on Telegram and WhatsApp is
  two identities; they can point at the same `res.partner`, but the core does
  not merge them automatically.
