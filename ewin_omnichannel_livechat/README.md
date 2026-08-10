# EWIN Inbox — Live Chat

A connector that bridges Odoo's own website **Live Chat** (`website_livechat`)
into **EWIN Inbox** as a two-way channel. Visitors on your site keep using the
normal live-chat widget; operators answer from the same Inbox conversation
list, routing and reply tools used for Telegram, WhatsApp, Viber and Email.

Depends on `ewin_omnichannel_core` and `website_livechat`.

## How it works

Every other connector talks to an external provider over a webhook or a
poll. Live Chat is different: the "provider" is Odoo itself, so there is
**no webhook**. Two `discuss.channel` records are involved, and it is
important not to confuse them:

- **L — the live session.** The `discuss.channel` (channel_type
  `livechat`) that `website_livechat` creates for the visitor's browser tab.
  This is the external transport: it is what the visitor's widget actually
  renders, and it is where a reply has to be posted for the visitor to see
  it.
- **M — the operator mirror.** The `discuss.channel` that
  `ewin_omnichannel_core` creates for every conversation, regardless of
  channel, so operators get native Discuss notifications, mentions and
  unread counts. M is not visible to the visitor.

Ingestion is in-process: `discuss.channel.message_post()` is overridden
(`models/discuss_channel.py`) to inspect every message posted into a
bridged `livechat` channel. When the post is a genuine visitor message (not
the operator's own, not a system notification, not one of our own outbound
posts) it is normalized and handed to the core
`omnichannel.routing_service.process_event()` — the same entry point every
webhook connector uses — which creates or updates the
`omnichannel.conversation`/`omnichannel.message` and mirrors it into M.
Outbound replies from Inbox are posted back into L by
`omnichannel.connector.livechat.send_message()`.

## Setting up a Live Chat account

1. In **Live Chat → Configuration → Live Chat Channels**, create an
   `im_livechat.channel` for the site (or reuse an existing one) and add
   **exactly one** operator to it: a dedicated technical user (the "bridge
   operator"), not a real human agent. EWIN Inbox owns routing and
   assignment; the bridge operator's only job is to keep the session
   channel open and available so `website_livechat` offers a chat window to
   visitors.
2. Do **not** attach a chatbot script to this Live Chat channel. EWIN owns
   the conversation flow (routing, teams, canned replies); a chatbot
   answering inside L would compete with it and its scripted messages would
   be ingested as if they were operator replies.
3. In Odoo, as an **Omnichannel: Administrator**, go to **EWIN Inbox →
   Configuration → Accounts** and create a new record:
   - **Channel:** Live Chat
   - **Live Chat Channel:** the `im_livechat.channel` from step 1
   - **Bridge Operator:** the same technical user added as its operator
4. Click **Check Connection** — this validates that the bridge operator is
   indeed an operator of the selected Live Chat channel, pins the bridge
   user's presence online, and marks the account connected.

## Routing

EWIN Inbox owns routing end to end: identity resolution, conversation
creation/assignment, teams, tags and canned replies all work exactly as for
any other channel. The bridge operator does not do any of that — its sole
role is technical, keeping the `im_livechat.channel` session available so a
visitor is offered a chat window at all. A human operator never needs to be
logged in as the bridge user; they work from the Inbox conversation like
any other channel.

## Identity

A visitor's identity is resolved with a hybrid strategy
(`services/livechat_normalizer.py`), preferring the most specific signal
available:

1. **`res.partner`** — if the live session's `website.visitor` is linked to
   a partner (a logged-in or previously identified visitor), that partner is
   used.
2. **`website.visitor`** — an anonymous but tracked visitor (has a
   `website.visitor` record without a partner).
3. **Guest** — a `discuss.channel` guest member with no visitor record.
4. **Session fallback** — if none of the above is available, the identity
   falls back to the live channel id itself so the message can still be
   ingested.

## Attachments

Attachments flow natively both ways, with no upload/download step to any
external service. Inbound: the normalizer lists the `ir.attachment`s already
on the visitor's message in L; the core's routing service resolves each one
through `connector.download_attachment()`, which makes an independent copy
(`ir.attachment.copy()`) so the inbound `omnichannel.message` owns its own
attachment rather than sharing the live session's record. Outbound: a file
an operator attaches to a reply in Inbox is passed straight through
(`attachment_ids`) to `message_post()` on L.

## Lifecycle

- **Visitor leaves** — when the live session ends from the visitor's side
  (`discuss.channel._close_livechat_session()`), the linked
  `omnichannel.conversation` is moved to **pending** rather than closed, so
  an operator can review and close it deliberately.
- **Operator closes in EWIN** — a conversation that actually closes
  (`omnichannel.conversation._close()`, reached from the Close button or the
  close-reason wizard) posts a closing notice into L (so the visitor sees the
  conversation ended) and then ends the live session
  (`_close_livechat_session()`). The notice is a plain system post, not a new
  inbound message — it does not get re-ingested.

## Bridge presence heartbeat

`website_livechat` only offers a chat window to visitors if at least one
channel operator is online (`bus.presence`). Because the bridge operator is
a headless technical user, no browser session ever calls in on its behalf,
so its presence would read as offline within a few minutes and
`im_livechat` would stop offering sessions on that channel entirely. A cron
(`cron_livechat_bridge_presence`, every 6 hours) pins the presence of every
connected account's bridge user back to `online`
(`omnichannel.account._cron_livechat_bridge_presence()` /
`_livechat_ensure_bridge_presence()`), independent of whether anyone is
actually watching that user's session.

## Operating it day to day

Operators answer from the **EWIN Inbox** conversation, not from the raw
Live Chat window in Discuss. A visitor's message creates (or reopens) an
`omnichannel.conversation`; the operator opens it in Inbox and replies with
the normal composer — the reply is delivered into the visitor's widget by
the connector.

**Assignment drives live delivery.** An operator only receives native
push/sound/unread badges for a conversation once they are its operator,
because the mirror channel (M) subscribes the assigned operator, not every
user. There are two ways to get there:

- Set a **Default Operator** and/or **Default Team** on the account
  (**Configuration → Accounts**). New conversations are then created already
  assigned and **open**, and the operator is notified immediately.
- Leave it unset and let conversations land in the **New / Unassigned**
  queue; an operator picks one up with **Take** on the conversation. Until a
  conversation is taken it sits in the queue: its messages are stored and
  visible when you open it, but no live notification is pushed — that is the
  intended queue behaviour, not a lost message.

## Troubleshooting

- **"The visitor's messages reach Discuss but never appear in Inbox."** You
  are almost certainly chatting as the operator. Because the bridge operator
  (or any operator) is identified as non-visitor, a message you post while
  logged in as that user is treated as an operator reply and is not ingested
  as an inbound customer message. Test from a **logged-out / incognito
  browser** so you are a real anonymous visitor. Genuine visitor messages
  are ingested; the operator's own are not, by design.
- **"Messages are in the conversation but I get no notification and the
  thread doesn't refresh live."** The conversation is **unassigned**
  (Operator is empty). Click **Take**, or set a Default Operator/Team so new
  conversations auto-assign. Assignment is what subscribes you to the mirror
  channel.
- **"Nothing lands at all."** Confirm the account is **Connected** (run
  **Check Connection**) and that the `im_livechat.channel` the visitor's
  session actually uses is the one selected on the account. Ingestion never
  raises into the visitor's request: an internal failure is recorded in
  **Configuration → Logs** (`omnichannel.error.log`, category *internal*)
  without losing the visitor's message — check there if a message is
  missing.

## Tests

```bash
docker exec odoo-web odoo -c /etc/odoo/odoo.conf -d odoo-test \
  -u ewin_omnichannel_livechat --test-enable --stop-after-init \
  --http-port=8269 --test-tags /ewin_omnichannel_livechat
```

`--http-port=8269` avoids colliding with the running server on 8069. A
green run ends with `0 failed, 0 error(s) of N tests`.
