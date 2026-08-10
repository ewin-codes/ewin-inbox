# EWIN Inbox — Telegram

A Telegram Bot connector for **EWIN Inbox**, built directly on the
**Telegram Bot API**. It adds a Telegram channel to Inbox alongside Email,
Live Chat, WhatsApp, Messenger, Instagram and Viber, so operators answer
Telegram chats in the same conversation list, with the same routing,
attachments and reply tools as every other channel.

Depends on `ewin_omnichannel_core`.

## What it does

- **Inbound messages** — text, photo, document, audio, voice notes, video,
  sticker, location and shared contacts, normalized into standard Inbox
  messages. Media is downloaded into `ir.attachment` when the account allows
  it, subject to a per-account size cap.
- **Outbound messages** — plain text and attachments sent from the conversation
  composer, uploaded to Telegram as `sendPhoto` or `sendDocument` depending on
  the file.
- **Duplicate delivery is harmless** — Telegram redelivers an update if it does
  not get a fast `200`. Each update is recorded as an `omnichannel.event` keyed
  by its `update_id`, so a redelivery is recognised and does not create a second
  message.
- **Friendly failures** — bot blocked, chat not found, invalid token and
  missing permissions are translated into plain sentences on the message and in
  the error log, instead of a raw API error.

## How it works

- `TelegramApiClient` — thin wrapper over the Bot API (`getMe`, `sendMessage`,
  `sendPhoto`, `sendDocument`, `getFile`, `setWebhook`, `deleteWebhook`,
  `getWebhookInfo`). Classifies errors as retriable or terminal and keeps the
  bot token out of any error text.
- `omnichannel.connector.telegram` — the connector: verifies the webhook
  secret, records the event, normalizes the update, sends outbound messages and
  maps provider errors to operator-facing text.
- `omnichannel.telegram.normalizer` — maps a Telegram `update` into Inbox's
  normalized message/event shape.
- `TelegramAttachmentService` — resolves a Telegram `file_id` to a download URL
  and stores the file as an `ir.attachment`.
- A public controller at
  `/omnichannel/webhook/telegram/<account_uuid>` receives updates.

## Connecting a bot

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token it
   gives you.
2. In Odoo, as an **EWIN Inbox / Administrator**, go to
   **EWIN Inbox → Configuration → Accounts** and create a record:
   - **Channel:** Telegram
   - **Bot Token:** the BotFather token (admin-only — other roles see a masked
     value)
   - optionally a default team and operator, and the file-download /
     max-size / auto-create-contact preferences
3. Click **Check Connection**. This calls `getMe` and fills in the bot username
   and bot id if the token is valid.
4. Click **Register Webhook** to point Telegram at this Odoo instance.
5. Click **Webhook Status** to confirm Telegram has the webhook on file.
6. Message the bot from Telegram. The conversation appears in the **Inbox**
   with a linked Discuss channel.

**Register Webhook requires a public HTTPS `web.base.url`** (Settings →
Technical → System Parameters) that Telegram's servers can actually reach — a
local `http://localhost:8069` will not work. Registration also generates a
random per-account webhook secret, which is checked on every incoming request.

Use **Remove Webhook** to disconnect. The account's **state** and **last error**
fields are the at-a-glance health check.

> **Send Test** is deliberately not a smoke test: Telegram cannot be messaged
> without a known chat id, so the button raises an explanatory error until a
> real conversation exists. Verify outbound delivery by replying to an actual
> conversation.

## Security

- **Webhook authentication**: `setWebhook` registers a random secret, and every
  inbound request must present it in the `X-Telegram-Bot-Api-Secret-Token`
  header. The comparison is constant-time; a mismatch is logged and the update
  is dropped without being processed.
- Unknown or disabled accounts get the same empty response as a bad secret, so
  the endpoint does not reveal which webhook UUIDs are valid.
- **Bot Token** and **Webhook Secret** are restricted to the omnichannel admin
  group; other roles see a masked token and no secret at all.
- The token is never written to logs — API errors are redacted before they
  reach the error log or the Python logger.
- A processing failure does not break the HTTP response: the transaction is
  rolled back and the update is re-queued as an `omnichannel.job`, so Telegram
  is not told to retry a message Odoo has already accepted.

## Out of scope

These are intentionally not implemented in this version:

- **Bot commands, keyboards and inline queries** — inbound callback data and
  custom keyboards are not handled; the connector is a two-way message pipe,
  not a bot framework.
- **Editing and deleting messages** — Telegram `edited_message` updates and
  message deletions are not reflected in Inbox.
- **Groups and channels** — the connector targets one-to-one customer chats.
- **Polling mode** — updates arrive by webhook only; there is no `getUpdates`
  long-poll fallback for hosts without a public HTTPS endpoint.
