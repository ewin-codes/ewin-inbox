# EWIN Inbox — CRM

Links **EWIN Inbox** conversations to **CRM leads**, and mirrors what the
customer wrote into the lead's own chatter.

Depends on `ewin_omnichannel_core` and `crm`. Core does not depend on `crm`, so
an installation that has no sales pipeline never sees any of this.

## What it does

- A conversation carries a **Lead**. One lead carries many conversations — the
  customer who writes on Telegram in March and on WhatsApp in June is one lead
  with two conversations.
- Every message of a linked conversation is copied into the lead's chatter as an
  internal log note, live, with its own timestamp and attachments. A salesperson
  reading the lead sees the whole exchange without opening the Inbox.
- **Create Lead** on a conversation opens a lead prefilled from what the channel
  knows about the customer — name, phone, email — already linked, so its chatter
  fills up immediately.
- **Conversations** on the lead counts and opens what is linked; **Link
  Conversation** opens core's picker wizard (`omnichannel.conversation.link.wizard`,
  the same one a contact uses) extended here with a `lead_id`, so pressing it
  attaches existing conversations to the lead instead.
- Unlinking or re-pointing a lead removes exactly the copies that link created.
  Mis-attributing a conversation is recoverable, and no customer's texts are left
  on another customer's card.

## How it works

All of the mirroring lives in `ewin_omnichannel_core`
(`omnichannel.history.service`). This module only tells core that a lead is a
place history goes:

```python
@api.model
def _history_link_fields(self):
    return super()._history_link_fields() + ["lead_id"]

def _history_targets(self):
    return super()._history_targets() + [
        record for record in (self.lead_id,) if record]
```

Core's `write` diffs the targets before and after and calls the service itself,
so adding a link backfills, removing one purges, and neither path needs a line of
CRM-specific code.

Installing or upgrading this module also backfills the history of every
conversation already linked to a lead, through its own
`migrations/18.0.1.1.0/post-migrate.py`. Core ships the same kind of pass, but
Odoo migrates one module at a time and runs each one's post-migrate right
after that module's own models are registered — before this module has
extended `_history_targets()` with `lead_id`. Core's pass therefore only ever
sees the contact; this module's pass, running after its own override is in
force, is what actually reaches a lead. It is idempotent for the same reason
core's is — `backfill` skips a message that already has a copy on a given
target — so it costs nothing on a database core already caught up.

## Access

Linking uses ordinary Odoo access rules: an operator who cannot read a lead
cannot select it. The two buttons carry different groups because they do
different things, and only one of them writes to the pipeline:

- **Create Lead** creates a `crm.lead`, so it is gated on
  `sales_team.group_sale_salesman`.
- **Link Conversation** creates no lead — it writes `lead_id` on conversations,
  and write access to `omnichannel.conversation` belongs to
  `ewin_omnichannel_core.group_omni_operator`, not to sales users. Gating it on
  Sales / User would show a button that fails on submit.

Deleting a lead clears `lead_id` (`ondelete="set null"`) and leaves the
conversation untouched.

The wizard's own ACL row moved to core along with the model it grants access
to; this module no longer ships one. **Upgrade this module together with
core** (`-u ewin_omnichannel_core`, which cascades to every dependent) rather
than on its own: upgrading only `ewin_omnichannel_crm` makes
`ir.model.data._process_end` delete this module's old, now-undeclared ACL
row while core — never marked `to upgrade` — does not recreate its
replacement, leaving the wizard with zero access rows and both Link
Conversation buttons raising an `AccessError` for anyone but the superuser.

## Merging leads

Odoo's merge moves every message of the merged-away leads onto the survivor and
then deletes them, which clears `lead_id` in the database — behind the ORM, so
core's write hook never sees it. `crm.lead._merge_dependences` is overridden to
re-point the conversations at the survivor afterwards, which is what keeps the
copies and the link on the same record: the conversation follows its texts, and
detaching it later still removes exactly them.

## Out of scope

- Starting a conversation from a lead ("message this customer on WhatsApp"):
  provider template and 24-hour-window rules make it a feature of its own.
- Linking one conversation to several leads. A conversation has one owner in CRM.
