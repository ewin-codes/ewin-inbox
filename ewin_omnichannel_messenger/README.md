# EWIN Inbox — Messenger

A **Facebook Messenger** connector for **EWIN Inbox**, built directly against
**Meta's Graph API** (no third-party BSP in the middle). It adds a Messenger
channel to Inbox alongside Telegram, Viber, Email and WhatsApp, so operators
handle conversations from a Facebook Page in the same conversation list, with
the same routing, attachments and reply tools as every other channel.

Depends on `ewin_omnichannel_core`.

## Installation

Install the core first, then this connector:

```bash
docker compose exec -T odoo odoo -d <your-db> -i ewin_omnichannel_core --stop-after-init --no-http
docker compose exec -T odoo odoo -d <your-db> -i ewin_omnichannel_messenger --stop-after-init --no-http
```

(Or from the Odoo Apps UI: install **EWIN Inbox Core**, then **EWIN Inbox
Messenger**.) After install, create a **Messenger** account under **Inbox →
Configuration → Accounts** — see below.

## What it does

- **Inbound messages** — text, images, audio, video, files, stickers, shared
  locations and link shares, all normalized into standard Inbox messages.
  **Postbacks** (Get Started, persistent-menu and button taps) are normalized
  to their title/payload text.
- **Outbound messages** — plain text and files (image / video / audio /
  document) sent from the conversation composer. A caption on an attachment
  is delivered as its own text message first, because a Messenger attachment
  message cannot carry text.
- **Delivery & read receipts** — Messenger's watermark-based `delivery` and
  `read` events advance the outbound message state (`sent` → `delivered` →
  `read`). Transitions are monotonic: duplicate or out-of-order receipts
  never move a message backwards.
- **Customer profiles** — because the webhook only carries a page-scoped user
  id (PSID), the connector looks up the customer's name and picture once, via
  the Graph profile API, so contacts are named properly instead of
  "Messenger user 123…".
- **The 24-hour messaging window** — Messenger only allows free-form replies
  within 24 hours of the customer's last message. The conversation shows a
  warning when the window looks closed, and a send outside it is surfaced as
  a clear, friendly error instead of a raw API failure.

## How it works

- `MessengerApiClient` — thin wrapper over the Graph API (`get_page`,
  `get_user_profile`, `send_text`, `send_attachment`, `download`).
  Authenticates with the Page access token via a Bearer header (never in a
  URL), classifies every Graph error as retriable or not (rate limits and
  5xx retry; invalid token, bad parameters and the 24h-window error do not),
  and redacts the token from any error text.
- `omnichannel.connector.messenger` — the connector itself: verifies webhook
  signatures, parses inbound events, applies delivery/read receipts, enriches
  identities with Graph profiles, sends outbound messages, and turns provider
  errors into user-facing messages via the core error log.
- `omnichannel.messenger.normalizer` — maps Meta's `entry[].messaging[]`
  webhook shape into Inbox's normalized message/event format.
- `omnichannel.messenger.attachment.service` — stores inbound attachments as
  `ir.attachment` with a size cap, filename sanitisation, and neutralisation
  of browser-executable content types.
- A public controller at
  `/omnichannel/webhook/messenger/<webhook_uuid>` handles both Meta's `GET`
  verification handshake and the `POST` event delivery.

## Setting up a Messenger app (Meta side)

1. In [Meta for Developers](https://developers.facebook.com/apps/), create an
   app (or use an existing Business app) and add the **Messenger** product.
2. Under **Messenger → Settings → Access Tokens**, connect your Facebook
   **Page** and generate a **Page access token** (prefer a permanent System
   User token with the `pages_messaging` permission — the token shown by
   default can expire).
3. Note the **Page ID** (Page → About, or the Messenger settings page).
4. In the app's **App Settings → Basic**, note the **App Secret**.

## Configuring the account in Odoo

1. Go to **Inbox → Configuration → Accounts** and create a new account with
   channel **Messenger**.
2. Fill in:
   - **Page ID**
   - **Page Access Token** — visible to the omnichannel admin group only;
     other users see a masked value.
   - **App Secret** (admin group only)
   - **Graph API Version** — defaults to `v21.0`, change only if Meta
     deprecates it.
   - **Download Files** / **Max File Size (MB)** / **Auto-create Contacts** /
     **Fetch User Profiles** — same behavior as the other Inbox connectors.
3. Save. The **Webhook Verify Token** is generated automatically the first
   time the account is created — you don't set it, you copy it into Meta
   (admin group only, read-only).
4. Note the account's **Webhook UUID** field (visible after saving) — it is
   part of the callback URL below.

## Configuring the webhook in Meta

In the app's **Messenger → Settings → Webhooks** section (or **Webhooks**
product):

- **Callback URL**:
  `<your-odoo-base-url>/omnichannel/webhook/messenger/<webhook_uuid>`
- **Verify Token**: the account's **Webhook Verify Token** value from Odoo.
- **Subscription fields**: subscribe to `messages`, `messaging_postbacks`,
  `message_deliveries` and `message_reads`, then subscribe the **Page** to
  the app.

Meta calls the callback URL with a `GET` request to verify ownership; the
controller checks `hub.verify_token` against the account and echoes back
`hub.challenge` on success. Back in Odoo, click **Check Connection** on the
account form to confirm the Page access token is valid and populate **Page
Name**.

## Acceptance scenarios (manual QA)

These mirror the automated test suite; run them once against a real Facebook
Page before a release, since the tests mock the Graph API.

1. **Connect a Page** — create an Account (channel Messenger) with a valid
   Page ID, Page access token and App Secret; **Check Connection** succeeds and
   fills in **Page Name**. Configure the webhook in Meta with the account's
   callback URL and Verify Token; Meta's `GET` handshake returns the challenge.
2. **New customer writes in** — a first message from a Messenger user creates
   an `omnichannel.identity`, a `res.partner` (named from the Graph profile),
   a new `omnichannel.conversation` (state `new`) and a linked
   `discuss.channel`; the message appears in the Inbox.
3. **Operator replies** — replying from the conversation composer sends the
   message to Messenger and the `omnichannel.message` moves to `sent`, then
   `delivered`/`read` once the receipts arrive.
4. **Customer repeats** — a second message from the same user reuses the
   existing identity, contact and open conversation — no duplicates.
5. **Attachments both ways** — an image/file sent by the customer is
   downloaded and attached to the inbound message; a file attached by the
   operator is uploaded to Messenger with the Send API.
6. **Send outside the window** — replying more than 24 hours after the
   customer's last message fails with a friendly "outside the 24-hour window"
   error and an `omnichannel.error.log` entry; the send is not retried.
7. **Permissions** — an **Omnichannel: Operator** cannot see the Page token,
   App Secret or Verify Token (admin-only), nor records of another company.
8. **Duplicate webhook delivery** — a redelivered event with the same message
   id is recognised as already processed (`omnichannel.event` idempotency) and
   only a single message is created.

## Security

- **Webhook authentication**: every inbound `POST` is verified against the
  `X-Hub-Signature-256` header — an HMAC-SHA256 of the raw request body keyed
  with the account's App Secret. Requests with a missing or invalid signature
  are dropped with a `200 {}` response (Meta requires webhooks to always
  return 2xx) and logged as a warning; nothing is processed. The App Secret is
  **required**: if it isn't configured on the account, the webhook fails
  closed and rejects every event rather than accepting unsigned requests.
- Unknown or disabled accounts get an identical empty `200` response, so the
  endpoint doesn't leak which webhook UUIDs are valid.
- **Page Access Token**, **App Secret** and **Webhook Verify Token** are all
  restricted to the omnichannel admin security group. Non-admin roles see a
  masked value for the token; the App Secret and Verify Token are hidden
  entirely.
- The access token is never written to logs — API errors and network
  exceptions are redacted before they reach the error log or `_logger`.
- A webhook processing failure never breaks the HTTP response: the
  transaction is rolled back and the event is re-queued as an Inbox job
  (`omnichannel.job`) for retry, rather than surfacing an error to Meta.

## Out of scope / follow-ups

These are intentionally not implemented in this version:

- **Message echoes** — messages the Page sends from elsewhere (e.g. the
  Facebook Page Inbox) arrive as `is_echo` events and are ignored, to avoid
  duplicating the connector's own outbound sends. Ingesting human-agent
  echoes from other tools is a possible future enhancement.
- **Message reactions** — inbound reaction events are ignored.
- **Message tags & the Human Agent window** — sending outside the 24-hour
  window via an approved message tag (e.g. `HUMAN_AGENT`) is not wired up;
  outbound sends use the standard `RESPONSE` messaging type.
- **Structured & interactive messages** — outbound generic/button templates
  and quick replies are not sent; inbound quick replies are normalized to
  their text.
- **Handover Protocol** — `standby` events (secondary receiver) are not
  processed.
