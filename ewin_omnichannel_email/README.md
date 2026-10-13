# EWIN Inbox — Email

An email connector for **EWIN Inbox**: inbound over **IMAP**, outbound over
**SMTP**, with proper RFC 2822 threading. It turns a shared mailbox
(`support@…`, `sales@…`) into an Inbox channel, so email lands in the same
conversation list as Telegram, WhatsApp or Live Chat, with the same routing,
assignment and reply tools.

Depends on `ewin_omnichannel_core`.

This is the one connector with **no webhook** — there is nothing for a provider
to call back. Mail is pulled on a schedule instead, which also means it works
on a host with no public HTTPS endpoint at all.

## What it does

- **Inbound mail** — unread messages are fetched from the configured folder,
  parsed into standard Inbox messages, and marked seen only after they have
  been stored. Attachments are downloaded into `ir.attachment` when the account
  allows it, subject to a per-account size cap.
- **Outbound replies** — sent from the conversation composer as HTML mail from
  the mailbox address, with the operator's attachments included.
- **Real threading** — a reply carries a generated `Message-ID` and quotes the
  last inbound message in `In-Reply-To` and `References`, and keeps the thread's
  `Subject` with an `Re:` prefix. The customer's mail client threads the
  conversation the way they expect, and their answer comes back to the same
  Inbox conversation instead of opening a new one.
- **One bad mail does not stop the run** — each message is committed on its own;
  a message that fails to parse is rolled back, logged, and polling continues
  with the next one. A message the server refuses to mark seen after it was
  stored is logged as exactly that; the next poll fetches it again and
  skips it as a duplicate. Likewise, one broken account never blocks the
  others.

## How it works

- `EmailClient` — IMAP and SMTP transport. Fetches unseen mail, marks it seen,
  and sends over an authenticated TLS connection.
- `omnichannel.connector.email` — the connector: the poll loop, message
  processing, outbound send, and provider-error handling.
- `omnichannel.email.normalizer` — parses an `email.message` into Inbox's
  normalized shape, deriving the event id from the `Message-ID` (synthesised
  from a content hash when the sender omits one) and the thread reference from
  `In-Reply-To` / `References`. A quoted `Message-ID` decides which
  conversation the mail joins, and nothing more: the message is credited to the
  address that actually sent it, so a third party quoting a reference appears
  as themselves rather than as the customer. The sender's address is reported
  as the identity's `email`, which is what the conversation header shows next
  to the contact name.
- `EmailAttachmentService` — extracts MIME parts into `ir.attachment`.
- Scheduled action **`EWIN Email Poll`** runs `poll_all()` every 2 minutes.

## Configuring an account

Go to **EWIN Inbox → Configuration → Accounts**, create a record with channel
**Email**, and fill in:

| Field | Notes |
|---|---|
| **Email Address** | The mailbox address. Also the SMTP login and the `From` of every reply. |
| **From Name** | Display name on outgoing mail. Defaults to the account name. |
| **Password** | Admin-only; other roles see a masked value. Use an app password where the provider requires one. |
| **IMAP Host / Port / SSL** | Defaults to port 993 with SSL. |
| **SMTP Host / Port / Security** | Defaults to port 587 with STARTTLS. |
| **Mailbox Folder** | Defaults to `INBOX`. |
| **Download Files / Max File Size (MB) / Auto-create Contacts** | Same behaviour as every other Inbox connector. |

Click **Check Connection**. It verifies **both** IMAP and SMTP and reports
whichever side is broken — so a mailbox that receives fine but cannot send is
caught at setup, not the first time an operator's reply silently disappears.

> Many hosts block outbound ports 25 and 465. If sending times out, use
> **587 + STARTTLS**.

## Security

- **TLS is mandatory.** Setting SMTP security to `none` is rejected at
  connection time; the client refuses to authenticate over plaintext rather
  than leaking the mailbox password onto the wire.
- **The server's certificate is verified**, on IMAP as well as SMTP and on both
  the implicit-TLS and the STARTTLS path: every connection is opened with an
  explicit `ssl.create_default_context()`. Handed no context, `imaplib` builds
  an *unverified* one — encrypted, but accepting any certificate for any
  hostname, which is exactly what a MITM needs to collect the mailbox password
  on the next poll.
- When the SMTP connection is made to a resolved IPv4 address (a workaround for
  hosts publishing an unroutable AAAA record), the real hostname is restored on
  the connection before STARTTLS, so SNI and certificate validation still run
  against the host and not the IP. The workaround costs no TLS guarantees.
- **Password** is restricted to the omnichannel admin group; other roles see
  only a masked value.
- Credentials are never written to logs — transport errors are reported as the
  provider's message, not the session transcript.

## Out of scope

These are intentionally not implemented in this version:

- **OAuth 2 / XOAUTH2** — authentication is username + password (or an app
  password). Gmail and Microsoft 365 tenants that have disabled basic auth are
  not supported.
- **Push (IMAP IDLE)** — mail is polled every two minutes, so inbound email has
  up to a two-minute latency; there is no long-lived IDLE connection.
- **Inline images and rich quoting** — the reply body is the composer's HTML;
  quoted history and `cid:` inline images are not rebuilt.
- **Cc / Bcc and multi-recipient threads** — a conversation is one customer
  address; additional recipients on an inbound mail are not carried into the
  reply.
- **Bounce and auto-reply handling** — delivery status notifications and
  vacation autoresponders are treated as ordinary inbound mail.
