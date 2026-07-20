# EWIN Inbox — WhatsApp

A WhatsApp Business connector for **EWIN Inbox**, built directly against
**Meta's WhatsApp Cloud API** (no third-party BSP in the middle). It adds a
WhatsApp channel to Inbox alongside Telegram, Viber and Email, so operators
handle WhatsApp conversations in the same conversation list, with the same
routing, attachments and reply tools as every other channel.

Depends on `ewin_omnichannel_core`.

## What it does

- **Inbound messages** — text, image, document, audio, voice notes, video,
  sticker, location, shared contacts, and emoji reactions, all normalized
  into standard Inbox messages. Interactive button/list replies are
  normalized to their button/option text.
- **Outbound messages** — plain text and media (image / video / audio /
  document) sent from the conversation composer, with attachments uploaded
  to Meta before the message is sent.
- **Delivery status** — inbound status webhooks (`sent` → `delivered` →
  `read`, or `failed`) update the message state. Status transitions are
  monotonic: out-of-order or duplicate status events are ignored, they never
  move a message backwards.
- **Message templates (HSM)** — approved templates are pulled from Meta with
  one click, stored locally, and can be used to message a customer outside
  the 24-hour window.
- **The 24-hour customer-service window** — WhatsApp only allows free-form
  text replies within 24 hours of the customer's last message. Outside that
  window Meta rejects the send and the connector surfaces it as a clear,
  friendly error instead of a raw API failure.

## How it works

- `WhatsAppApiClient` — thin wrapper over the Graph API (`send_text`,
  `send_media`, `send_template`, `upload_media`/`download_media`,
  `list_templates`, `get_phone_number`). Classifies every Graph error as
  retriable or not (rate limits and 5xx retry; invalid token, bad
  parameters, and the 24h-window errors do not) and redacts the access
  token from any error text.
- `omnichannel.connector.whatsapp` — the connector itself: parses inbound
  webhook payloads, applies delivery statuses, sends outbound messages and
  templates, and turns provider errors into user-facing messages via the
  core error log.
- `omnichannel.whatsapp.normalizer` — maps Meta's webhook payload shape
  (`entry[].changes[].value`) into Inbox's normalized message/event format.
- `omnichannel.whatsapp.template` — local cache of approved HSM templates
  (`account_id`, `name`, `language`, `category`, `components`,
  `variables_count`), browsable under **Configuration → WhatsApp
  Templates**.
- A public controller at
  `/omnichannel/webhook/whatsapp/<webhook_uuid>` handles both Meta's
  `GET` verification handshake and the `POST` event delivery.

## Setting up a WhatsApp account (Meta side)

1. In [Meta for Developers](https://developers.facebook.com/apps/), create
   an app (or use an existing Business app) and add the **WhatsApp**
   product.
2. From the WhatsApp product's **API Setup** page, note down:
   - a **permanent access token** (a System User token with
     `whatsapp_business_messaging` and `whatsapp_business_management`
     permissions — the temporary token Meta shows by default expires in 24h
     and is not suitable for production),
   - the **Phone Number ID**,
   - the **WhatsApp Business Account ID (WABA ID)**.
3. In the app's **App Settings → Basic**, note the **App Secret**.

## Configuring the account in Odoo

1. Go to **Inbox → Configuration → Accounts** and create a new account with
   channel **WhatsApp**.
2. Fill in:
   - **Access Token** — the permanent token from step 2 above (visible to
     the omnichannel admin group only; other users see a masked value).
   - **Phone Number ID**
   - **WhatsApp Business Account ID**
   - **App Secret** (admin group only)
   - **Graph API Version** — defaults to `v21.0`, change only if Meta
     deprecates it.
   - **Download Files** / **Max File Size (MB)** / **Auto-create
     Contacts** — same behavior as the other Inbox connectors.
3. Save. The **Webhook Verify Token** is generated automatically the first
   time the account is created — you don't set it, you copy it into Meta
   (admin group only, read-only).
4. Note the account's **Webhook UUID** field (visible after saving) — it is
   part of the callback URL below.

## Configuring the webhook in Meta

In the WhatsApp product's **Configuration** page:

- **Callback URL**:
  `<your-odoo-base-url>/omnichannel/webhook/whatsapp/<webhook_uuid>`
- **Verify Token**: the account's **Webhook Verify Token** value from Odoo.
- **Webhook fields**: subscribe to `messages`.

Meta will call the callback URL with a `GET` request to verify ownership;
the controller checks `hub.verify_token` against the account and echoes
back `hub.challenge` on success.

Back in Odoo, on the account form:

1. Click **Check Connection** — confirms the access token and phone number
   ID are valid and populates **Business Phone**.
2. Click **Sync Templates** — fetches every `APPROVED` template from Meta
   into **Configuration → WhatsApp Templates** (templates no longer
   approved or present remotely are archived, not deleted).

## The 24-hour window and templates

Meta only allows a business to send free-form messages (text, media) to a
customer within 24 hours of that customer's last inbound message. Sending
outside that window fails with Meta error `131047`
(`re-engagement message`) or `131051`; the connector maps these to a plain
error such as:

> The customer has not messaged in the last 24 hours — only approved
> templates can be sent until they reply.

To reach a customer outside the window, use an **approved template**
(`omnichannel.whatsapp.template`, kept up to date via **Sync Templates**).
The connector builds the correct Graph API `components` payload from an
ordered list of variable values and sends it as a `template`-type message,
which reopens the 24-hour window. Sending an HSM template is currently a
backend capability of the connector (`send_template(account, conversation,
template, variables)`); a dedicated "send template" button in the
conversation composer is not implemented yet — see below.

## Security

- **Webhook authentication**: every inbound `POST` is verified against the
  `X-Hub-Signature-256` header — an HMAC-SHA256 of the raw request body
  keyed with the account's App Secret. Requests with a missing or invalid
  signature are dropped with a `200 {}` response (WhatsApp requires webhooks
  to always return 2xx) and logged as a warning; nothing is processed. The
  App Secret is **required**: if it isn't configured on the account, the
  webhook fails closed and rejects every event (logged as a warning) rather
  than accepting unsigned requests.
- Unknown or disabled accounts get an identical empty `200` response, so the
  endpoint doesn't leak which webhook UUIDs are valid.
- **Access Token**, **App Secret** and **Webhook Verify Token** are all
  restricted to the omnichannel admin security group. Non-admin roles see a
  masked value for the Access Token; the App Secret and Webhook Verify Token
  are hidden entirely (not shown at all, not even masked) from non-admin
  roles.
- The access token is never written to logs — API errors and network
  exceptions are redacted before they reach the error log or `_logger`.
- A webhook processing failure never breaks the HTTP response: the
  transaction is rolled back and the event is re-queued as an Inbox job
  (`omnichannel.job`) for retry, rather than surfacing an error to Meta.

## Out of scope / follow-ups

These are intentionally not implemented in this version:

- **Interactive messages** — inbound button/list replies are normalized to
  plain text (the button/option title); outbound interactive messages
  (buttons, lists) are not sent.
- **WhatsApp Flows** are not supported.
- **Embedded Signup** — accounts are configured manually with a permanent
  token; there's no guided in-app onboarding flow for connecting a WABA.
- **Template authoring** — Odoo does not create or submit templates to Meta;
  sync is one-way and pull-only. Admins can still edit the locally cached
  template records, but any such edits are overwritten (or the record is
  archived) on the next **Sync Templates** run.
- **Template send UI** — sending an HSM template is available at the
  connector/model level (`send_template`) but has no conversation-composer
  button yet.
- **Live window countdown** — the 24-hour window is enforced by Meta and
  surfaced as an error on send; there's no per-conversation countdown shown
  in the UI.
