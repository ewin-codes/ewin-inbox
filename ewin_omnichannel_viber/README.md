# EWIN Inbox — Viber

A Viber Bot connector for **EWIN Inbox**, built on the **Viber Public Account /
Bot API**. It adds a Viber channel to Inbox alongside Telegram, Email, Live
Chat, WhatsApp, Messenger and Instagram, so operators answer Viber chats in the
same conversation list, with the same routing, attachments and reply tools.

Depends on `ewin_omnichannel_core`.

> **Status: unverified.** The implementation is complete and covered by tests,
> but it has not yet been exercised against a live Viber Public Account. Test
> it in staging before putting it in front of customers.

## What it does

- **Inbound messages** — text, picture, video, file, shared contacts, location
  and URL messages, normalized into standard Inbox messages. Media is
  downloaded into `ir.attachment` when the account allows it, subject to a
  per-account size cap.
- **Lifecycle events** — the webhook subscribes to `subscribed`,
  `unsubscribed` and `conversation_started` alongside `message`. They are
  acknowledged so Viber does not retry them, but only a `message` event carries
  customer content and creates a conversation.
- **Outbound messages** — text and media sent from the conversation composer.
- **Friendly failures** — Viber's numeric send codes (invalid token, customer
  not registered, bot blocked, account suspended, "the customer must write
  first", …) are translated into plain sentences on the message and in the
  error log instead of a bare status number.

## How it works

- `ViberApiClient` — thin wrapper over the Bot API (`get_account_info`,
  `set_webhook`, `remove_webhook`, `send_message`, `download_media`).
  Classifies errors as retriable or terminal and keeps the auth token out of
  any error text.
- `omnichannel.connector.viber` — the connector: verifies the callback
  signature, records the event, normalizes it, sends outbound messages and maps
  provider codes to operator-facing text.
- `omnichannel.viber.normalizer` — maps a Viber callback into Inbox's
  normalized message/event shape.
- `ViberAttachmentService` — fetches media from the URL Viber supplies and
  stores it as an `ir.attachment`.
- A public controller at `/omnichannel/viber/webhook/<account_uuid>` receives
  callbacks.

**Outbound media works by URL, not upload.** Viber's servers fetch the file
themselves, so the connector hands them a tokenised
`/web/content/<id>?access_token=…&download=true` link to the attachment. The
token is unguessable and scopes the download to that one attachment — but it
does mean outbound media requires a `web.base.url` that Viber can reach from
the public internet.

## Connecting a bot

1. Create a **Public Account** or bot in the
   [Viber admin panel](https://partners.viber.com/) and copy its auth token.
2. In Odoo, as an **EWIN Inbox / Administrator**, go to
   **EWIN Inbox → Configuration → Accounts** and create a record:
   - **Channel:** Viber
   - **Auth Token:** the token from Viber (admin-only — other roles see a
     masked value)
   - optionally a default team and operator, and the file-download /
     max-size / auto-create-contact preferences
3. Click **Check Connection**. This calls `get_account_info` and fills in the
   bot name, URI and id if the token is valid.
4. Click **Register Webhook**. This subscribes to the `message`, `subscribed`,
   `unsubscribed` and `conversation_started` events.
5. Click **Webhook Status** to confirm Viber has the callback on file.
6. Message the bot from Viber. The conversation appears in the **Inbox** with a
   linked Discuss channel.

**Register Webhook requires a public HTTPS `web.base.url`** (Settings →
Technical → System Parameters) that Viber's servers can actually reach — Viber
rejects a callback URL it cannot verify, and a local `http://localhost:8069`
will not work.

Use **Remove Webhook** to disconnect. The account's **state** and **last error**
fields are the at-a-glance health check.

## Security

- **Webhook authentication**: Viber signs every callback with
  `X-Viber-Content-Signature`, an HMAC-SHA256 of the raw request body keyed
  with the account's auth token. The connector recomputes it over the raw bytes
  and compares in constant time; a mismatch is logged and the callback is
  dropped without being processed.
- Unknown or disabled accounts get the same empty response as a bad signature,
  so the endpoint does not reveal which webhook UUIDs are valid.
- **Auth Token** is restricted to the omnichannel admin group; other roles see
  only a masked value.
- The token is never written to logs — API errors are redacted before they
  reach the error log or the Python logger.
- A processing failure does not break the HTTP response: the transaction is
  rolled back and the callback is re-queued as an `omnichannel.job`.

## Out of scope

These are intentionally not implemented in this version:

- **Keyboards and rich media** — Viber carousels, rich media messages and reply
  keyboards are neither sent nor interpreted.
- **Delivery and read receipts** — Viber's `delivered` / `seen` callbacks are
  not mapped onto the message state machine, so a Viber message stops at
  `sent`.
- **Broadcast messaging** — the connector answers conversations; it does not
  send to subscriber lists.
- **Stickers as media** — inbound stickers are not resolved to an image.
