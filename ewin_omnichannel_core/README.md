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
  identity, contact and open conversation — no duplicates.
- **Replying takes the conversation.** Answering an unassigned conversation
  assigns it to you — there is no separate Take click on the normal path. An
  internal note does not take it (writing a note is not answering the
  customer), and an existing assignment is never overridden, so a colleague's
  conversation stays theirs. The **Take** button remains for claiming a
  conversation without writing anything yet.
- **Realtime.** New messages and assignment changes are pushed over the bus to
  the assigned operator, so the open thread and the conversation list update
  without a manual reload.
- **Discuss mirror.** Every conversation is mirrored into a `discuss.channel`,
  so operators get native Odoo unread badges and notifications, and can reply
  either from the Inbox composer or straight from Discuss — both paths reach
  the customer.
- **Delivery lifecycle.** Messages carry a real state machine
  (`received` → `queued` → `processing` → `sent` → `delivered` → `read`, plus
  `failed` / `cancelled`), so a reply that never arrived is visible instead of
  silently lost.
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
| `omnichannel.identity` | A customer as one provider knows them. Unique per `(account, external_id)`; links to `res.partner`. |
| `omnichannel.conversation` | A thread with one customer on one account. States `new`/`open`/`pending`/`closed`, priority, team, operator, tags, close reason, and the linked `discuss.channel`. Inherits `mail.thread`. |
| `omnichannel.message` | A single message, inbound or outbound, with type, body, attachments, provider ids and the delivery state machine. |
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

## Customer history

A conversation can be linked to the customer records it belongs to — a contact
(`res.partner`) out of the box, a CRM lead when `ewin_omnichannel_crm` is
installed. Every message is then copied into that record's chatter as an
internal log note, so the customer's own history holds the texts: the salesperson
reading a contact sees what was said on WhatsApp without opening the Inbox.

`omnichannel.history.service` owns those copies:

| Method | When | How |
|---|---|---|
| `mirror(message)` | a message is created | `message_post` with `mail.mt_note`, so the chatter refreshes live and no follower is emailed |
| `backfill(conversation, targets)` | a link is added | one batched `mail.message` create, each copy keeping its own message's timestamp |
| `purge(conversation, targets)` | a link is removed, or the conversation is deleted | deletes exactly the copies that link created |

Copies are tracked on `omnichannel.message.history_message_ids`, which is what
lets a mis-attributed conversation be re-pointed without leaving one customer's
texts on another customer's card. `mail.mt_note` is an internal subtype, so the
copies are never visible to a portal user reading their own contact record.

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

Unimplemented methods raise `NotImplementedError`, and the core tolerates that
where the capability is genuinely optional — a polling channel has no webhook
to register, and a provider without media has nothing to download.

## Job queue and scheduled actions

- **`Omnichannel: Process job queue`** — every minute. Runs due jobs, applies
  exponential backoff, and calls the target model's
  `_on_job_permanent_failure` hook once retries are exhausted. The queue itself
  stays channel-agnostic: it knows it may call that hook, not that it is
  dealing with messages.
- **`Omnichannel: Cleanup old events and logs`** — daily. Trims processed
  events and stale log entries so the idempotency table does not grow forever.

## Security

Three groups, under the **EWIN Inbox** application category:

- **Operator** (`group_omni_operator`) — works conversations; sees their own
  and their teams'. Never sees provider credentials.
- **Manager** (`group_omni_manager`) — sees every conversation in the company.
- **Administrator** (`group_omni_admin`) — configuration and credentials.

Provider secrets live on fields restricted to the admin group; connectors expose
a masked companion field so an operator can confirm *a* token is set without
reading it. Record rules scope accounts, identities, conversations, messages,
events, teams, close reasons and error logs by company, and conversations
additionally by operator/team for the operator role.

Menus that read `omnichannel.*` are invisible to users outside these groups —
after installing, grant yourself **EWIN Inbox / Administrator**.

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
