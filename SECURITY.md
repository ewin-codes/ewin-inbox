# Security Policy

## Reporting a Vulnerability

Do not report security vulnerabilities through public GitHub issues. Public disclosure
before a fix is available puts all users at risk.

Send reports privately to **info@ewin.codes** with the subject **`[SECURITY] EWIN Inbox`**.
Include the affected module, version, reproduction steps and possible impact — especially
anything involving leaked tokens, webhook secrets, or authentication bypass. Do not include
real provider credentials or customer data.

We will acknowledge your report and work with you on a coordinated fix and disclosure
timeline.

## Security posture

The following controls are implemented in `ewin_omnichannel_core` and the connector
addons; Telegram is used below wherever one connector has to stand for all of them:

- **Webhook endpoint hardening.** Each `omnichannel.account` gets its own random UUID
  (`webhook_uuid`), and every connector declares its own route with the channel as a
  literal path segment (`/omnichannel/webhook/telegram/<account_uuid>`), looked up by that
  UUID rather than a predictable ID. The channel is never a route parameter: a converter
  there would also claim the paths of channels whose controller lives elsewhere or does not
  exist, and a payload arriving that way would be verified against the wrong connector's
  secret — one it does not have. On top of the UUID, the provider's signature is verified:
  Telegram's `X-Telegram-Bot-Api-Secret-Token` against a per-account random secret,
  Viber's `X-Viber-Content-Signature` and Meta's `X-Hub-Signature-256` as HMAC-SHA256 over
  the raw request body, always with `hmac.compare_digest` (constant-time) to avoid timing
  side channels. Every comparison goes through `ewin_omnichannel_core.tools.security`'s
  `secret_equals`, which compares the two values **as UTF-8 bytes**: `compare_digest`
  raises `TypeError` on a `str` holding a character outside ASCII, and a header value
  reaches Python decoded as Latin-1 while a query string carries whatever the caller
  likes — so comparing as `str` would let one crafted byte raise where a mismatch
  returns `False`, and the resulting error page would tell an unauthenticated caller
  that the account exists. The same helper carries the fail-**closed** rule: an account
  with no secret configured rejects the request rather than skipping the check.
  Requests with a missing/incorrect signature, an unknown account UUID, a disabled
  account, or a malformed body are rejected with a plain `200 OK` and no job is
  enqueued — the webhook never leaks whether an account exists or why a request was
  rejected.
- **Transport security.** IMAP and SMTP connections are opened with an explicit
  `ssl.create_default_context()` on both the implicit-TLS and the STARTTLS path, so the
  mail server's certificate and hostname are verified before the mailbox password is sent.
  (`imaplib` and `smtplib` default to an *unverified* context when handed none.) Plaintext
  SMTP auth is refused at three levels: an ORM constraint on the account, the connector,
  and the client itself.
- **Inbound authorship.** A message is credited to the correspondent who sent it, never to
  the conversation's customer. Email threads on a quoted `Message-ID` — which anyone who
  has seen one message of a thread can quote — so attributing by thread would file a
  stranger's words as the customer's own in the inbox, in Discuss, and permanently in
  their contact and lead chatter. For the same reason a threaded reply from another sender
  cannot backfill the customer contact's email address.
- **Secrets never logged or exported.** The bot token (`tg_bot_token`) and webhook secret
  (`tg_webhook_secret`) are plain `Char` fields restricted to the
  `ewin_omnichannel_core.group_omni_admin` group; every other role sees a masked
  placeholder field instead (`tg_bot_token_masked`). Errors raised by the Telegram API
  client are passed through a redaction helper that strips the token out of any
  `/bot<token>/...` URL fragment before the error text reaches logs, the error log model,
  or the UI — so a network failure can never leak the token via its exception message.
- **Idempotent event processing.** Inbound webhook payloads are recorded as
  `omnichannel.event` rows with a unique `(account_id, external_event_id)` constraint
  before being queued for processing, so a redelivered/duplicated Telegram update produces
  at most one message.
- **Content sanitation.** Message bodies are stored as `Html` fields with
  `sanitize=True, sanitize_attributes=True`, stripping unsafe markup/attributes before
  the content is displayed or mirrored into Discuss.
- **Attachment hardening.** Uploaded/downloaded file names are sanitized before storage;
  a blocklist of dangerous extensions (`.exe`, `.bat`, `.cmd`, `.sh`, `.js`, `.msi`, …) is
  rejected outright. Attachments whose declared MIME type is HTML/XHTML/SVG are
  neutralized to a generic binary MIME type before being stored as `ir.attachment`, to
  prevent stored-XSS via a mislabeled upload. File size is capped per account
  (`tg_max_file_size`, default 20 MB) and oversize downloads degrade gracefully (the
  message is still created; the attachment is skipped and logged) instead of aborting
  message processing.
- **Outbound API hardening.** All calls to the Telegram Bot API go through a single
  `requests`-based client with an explicit timeout on every call, so a slow/unresponsive
  Telegram endpoint cannot hang the job queue worker indefinitely.
- **Access control & multi-company isolation.** Three role groups —
  `omni_operator` / `omni_manager` / `omni_admin` (each implying the previous) — gate
  `ir.model.access.csv` permissions per model. `ir.rule` record rules on account, identity,
  conversation, message, team, event, template, tag, close reason and error log restrict
  each record to its own company (or a global/no-company record), so users in Company A
  never see conversations, messages, canned replies, or account configuration belonging to
  Company B. Conversations and messages are additionally scoped by operator/team for the
  operator role.
- **Account actions are administration.** The buttons on the account form connect,
  register webhooks and rotate credentials, and they do it with `sudo()` because the
  credentials are admin-only fields. Since `call_button` reaches any public method on a
  model the caller can read, they all pass through one doorway
  (`omnichannel.account._run_connector_action`) that asks for write on the account first.
- **The job queue is not a generic bridge.** `omnichannel.job` rows name a model and a
  method, and the cron that drains them runs as superuser. A model therefore has to
  publish a method before the queue will call it, by name, in a `_job_methods` frozenset —
  `parse_webhook_job` on the connector contract, `send_outbound` on the routing service.
  Anything else fails terminally. No group holds write on the model; every producer
  enqueues through `sudo()`.
- **The Discuss mirror is scoped.** The `discuss.channel` that mirrors a conversation is
  authorized to the operator group. Left to Odoo's default it would be stamped with
  `base.group_user`, whose read rule admits every employee — and through the same rule
  portal and public users — to the full customer history, attachments and internal notes.
  A reply typed in the mirror is forwarded to the customer only if its author may write
  the conversation; membership of the channel is not authority over the customer.
- **Raw payload isolation.** The raw inbound payload (`omnichannel.message.raw_payload`) is
  an admin-only field, kept for debugging/audit but not exposed to operators.

## Known limitations

This is an MVP-scope implementation. It has not undergone a third-party security audit.
In particular: there is no automated reclaim of stuck/crashed queue jobs, and the
constant-time secret check does not fully equalize response timing between an "unknown
account" and a "wrong secret" rejection (the webhook UUID itself has enough entropy that
this is a low-risk gap). Please report anything you find via the channel above rather than
relying on this list being exhaustive.
