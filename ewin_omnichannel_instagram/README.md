# EWIN Inbox — Instagram

An **Instagram Direct** connector for **EWIN Inbox**, built directly against
the **Instagram Graph API** using **Instagram business login** — no Facebook
Page and no third-party BSP in the middle. It adds an Instagram channel to
Inbox alongside Telegram, WhatsApp, Messenger, Viber, Email and Live Chat, so
operators handle Instagram DMs in the same conversation list, with the same
routing, attachments and reply tools as every other channel.

Depends on `ewin_omnichannel_core`.

## Installation

Install the core first, then this connector:

```bash
docker compose exec -T odoo odoo -d <your-db> -i ewin_omnichannel_core --stop-after-init --no-http
docker compose exec -T odoo odoo -d <your-db> -i ewin_omnichannel_instagram --stop-after-init --no-http
```

(Or from the Odoo Apps UI: install **EWIN Inbox Core**, then **EWIN Inbox
Instagram**.) After install, create an **Instagram Direct** account under
**Inbox → Configuration → Accounts** — see below.

## What it does

- **Inbound messages** — text, images, audio, video, files and stickers, all
  normalized into standard Inbox messages. **Story mentions** are stored like
  an image (the tagged story media); **story replies** are shown with a marker
  linking back to the story; **shared posts/reels** render as a link.
  **Postbacks** (icebreakers, generic-template and button taps) are normalized
  to their title/payload text.
- **Outbound messages** — plain text and files (image / video / audio /
  document) sent from the conversation composer. A caption on an attachment is
  delivered as its own text message first, because an Instagram attachment
  message cannot carry text.
- **Delivery & read receipts** — Instagram's watermark-based `delivery` and
  `read` events advance the outbound message state (`sent` → `delivered` →
  `read`). Transitions are monotonic: duplicate or out-of-order receipts never
  move a message backwards.
- **Customer profiles** — because the webhook only carries an Instagram-scoped
  user id (IGSID), the connector looks up the customer's name, `@username` and
  picture once, via the Graph profile API, so contacts are named properly
  instead of "Instagram user 123…".
- **Automatic token refresh** — Instagram long-lived tokens expire after 60
  days. A daily job refreshes each account's token well before expiry, so the
  channel keeps working without manual intervention. A **Refresh Token** button
  triggers it on demand.
- **The 24-hour messaging window** — Instagram only allows free-form replies
  within 24 hours of the customer's last message. The conversation shows a
  warning when the window looks closed, and a send outside it is surfaced as a
  clear, friendly error. Optionally, the **Human Agent** tag extends the window
  to 7 days (see below).

## How it works

- `InstagramApiClient` — thin wrapper over the Instagram Graph API
  (`get_me`, `get_user_profile`, `send_text`, `send_attachment`, `download`,
  `refresh_long_lived_token`). Authenticates with the Instagram-scoped access
  token via a Bearer header (never in a URL), classifies every Graph error as
  retriable or not (rate limits and 5xx retry; invalid token, bad parameters
  and the 24h-window error do not), and redacts the token from any error text.
- `omnichannel.connector.instagram` — the connector itself: verifies webhook
  signatures, parses inbound events, applies delivery/read receipts, enriches
  identities with Graph profiles, sends outbound messages, refreshes tokens,
  and turns provider errors into user-facing messages via the core error log.
- `omnichannel.instagram.normalizer` — maps Instagram's `entry[].messaging[]`
  webhook shape into Inbox's normalized message/event format, including the
  Instagram-specific story mention / story reply / share types.
- `omnichannel.instagram.attachment.service` — stores inbound attachments as
  `ir.attachment` with a size cap, filename sanitisation, and neutralisation of
  browser-executable content types.
- A public controller at
  `/omnichannel/webhook/instagram/<webhook_uuid>` handles both Meta's `GET`
  verification handshake and the `POST` event delivery.
- A daily `ir.cron` (**Instagram: refresh access tokens**) calls
  `_cron_ig_refresh_tokens`, which refreshes any token within 10 days of
  expiry.

## Setting up the app (Meta side)

1. In [Meta for Developers](https://developers.facebook.com/apps/), create an
   app (or use an existing Business app) and add the **Instagram** product with
   **API setup with Instagram business login**.
2. Your Instagram account must be a **professional** account (Business or
   Creator).
3. Under **Instagram → API setup with Instagram business login → Generate
   access tokens**, add and select your Instagram account and generate a
   **long-lived access token** (it carries the `instagram_business_manage_messages`
   permission).
4. In the app's **App settings → Basic**, note the **App Secret**.

## Configuring the account in Odoo

1. Go to **Inbox → Configuration → Accounts** and create a new account with
   channel **Instagram Direct**.
2. Fill in:
   - **Access Token** — the long-lived token; visible to the omnichannel admin
     group only, other users see a masked value. It is auto-refreshed before it
     expires.
   - **App Secret** (admin group only)
   - **Instagram Account ID** — optional; learned automatically from
     **Check Connection** or the first event.
   - **Graph API Version** — defaults to `v21.0`, change only if Meta
     deprecates it.
   - **Download Files** / **Max File Size (MB)** / **Auto-create Contacts** /
     **Fetch User Profiles** — same behavior as the other Inbox connectors.
   - **Human Agent Tag** — off by default; see below.
3. Save. The **Webhook Verify Token** is generated automatically the first time
   the account is created — you don't set it, you copy it into Meta (admin
   group only, read-only). Saving the token stamps a 60-day expiry that the
   refresh job then keeps current.

## Configuring the webhook in Meta

In the app's **Instagram → API setup with Instagram business login → Configure
webhooks** section:

- **Callback URL**:
  `<your-odoo-base-url>/omnichannel/webhook/instagram/<webhook_uuid>`
- **Verify Token**: the account's **Webhook Verify Token** value from Odoo.
- **Subscription fields**: subscribe to `messages`, `messaging_postbacks` and
  `messaging_seen`.

Meta calls the callback URL with a `GET` request to verify ownership; the
controller checks `hub.verify_token` against the account and echoes back
`hub.challenge` on success. Back in Odoo, click **Check Connection** on the
account form to confirm the token is valid and populate the **Username** and
**Instagram Account ID**.

## The Human Agent tag

Instagram's standard messaging window is 24 hours. Meta's **Human Agent** tag
extends it to **7 days** for replies sent by a human agent, which suits a
helpdesk. It is **off by default** because it requires Meta's *Human Agent*
feature to be approved for your app — enabling it without approval makes
out-of-window sends fail. When **Human Agent Tag** is on and the window is
closed, outbound replies are sent with `tag=HUMAN_AGENT`; otherwise they use
the standard `RESPONSE` messaging type.

## Acceptance scenarios (manual QA)

These mirror the automated test suite; run them once against a real Instagram
professional account before a release, since the tests mock the Graph API.

1. **Connect an account** — create an Account (channel Instagram Direct) with a
   valid access token and App Secret; **Check Connection** succeeds and fills in
   **Username** and **Instagram Account ID**. Configure the webhook in Meta with
   the account's callback URL and Verify Token; Meta's `GET` handshake returns
   the challenge.
2. **New customer writes in** — a first DM from an Instagram user creates an
   `omnichannel.identity`, a `res.partner` (named from the Graph profile), a new
   `omnichannel.conversation` (state `new`) and a linked `discuss.channel`; the
   message appears in the Inbox.
3. **Operator replies** — replying from the conversation composer sends the
   message to Instagram and the `omnichannel.message` moves to `sent`, then
   `delivered`/`read` once the receipts arrive.
4. **Customer repeats** — a second message from the same user reuses the
   existing identity, contact and open conversation — no duplicates.
5. **Attachments both ways** — an image/file sent by the customer is downloaded
   and attached to the inbound message; a file attached by the operator is
   uploaded to Instagram with the Send API.
6. **Story mention & reply** — a story mention arrives with the story media
   attached; a reply to one of your stories shows the "Replied to your story"
   marker.
7. **Send outside the window** — replying more than 24 hours after the
   customer's last message fails with a friendly "outside the 24-hour window"
   error and an `omnichannel.error.log` entry (unless the Human Agent tag is
   enabled and approved); the send is not retried.
8. **Token refresh** — the daily job refreshes a token approaching expiry;
   **Refresh Token** does it on demand and updates **Token Expires**.
9. **Permissions** — an **Omnichannel: Operator** cannot see the access token,
   App Secret or Verify Token (admin-only), nor records of another company.
10. **Duplicate webhook delivery** — a redelivered event with the same message
    id is recognised as already processed (`omnichannel.event` idempotency) and
    only a single message is created.

## Security

- **Webhook authentication**: every inbound `POST` is verified against the
  `X-Hub-Signature-256` header — an HMAC-SHA256 of the raw request body keyed
  with the account's App Secret. Requests with a missing or invalid signature
  are dropped with a `200 {}` response (Meta requires webhooks to always return
  2xx) and logged as a warning; nothing is processed. The App Secret is
  **required**: if it isn't configured on the account, the webhook fails closed
  and rejects every event rather than accepting unsigned requests.
- Unknown or disabled accounts get an identical empty `200` response, so the
  endpoint doesn't leak which webhook UUIDs are valid.
- **Access Token**, **App Secret** and **Webhook Verify Token** are all
  restricted to the omnichannel admin security group. Non-admin roles see a
  masked value for the token; the App Secret and Verify Token are hidden
  entirely.
- The access token is never written to logs — API errors and network
  exceptions are redacted before they reach the error log or `_logger`.
- A webhook processing failure never breaks the HTTP response: the transaction
  is rolled back and the event is re-queued as an Inbox job (`omnichannel.job`)
  for retry, rather than surfacing an error to Meta.

## Out of scope / follow-ups

These are intentionally not implemented in this version:

- **Message echoes** — messages the account sends from elsewhere (e.g. the
  Instagram app) arrive as `is_echo` events and are ignored, to avoid
  duplicating the connector's own outbound sends.
- **Message reactions** — inbound reaction events are ignored.
- **Structured & interactive messages** — outbound generic/button templates and
  quick replies are not sent; inbound quick replies are normalized to their
  text.
- **Instagram-via-Facebook-Page** — this connector uses Instagram business
  login (standalone). The alternative path (an Instagram account linked to a
  Facebook Page, messaged through `graph.facebook.com` with a Page access
  token) is not supported here — use the Messenger connector for Page-based
  setups.
