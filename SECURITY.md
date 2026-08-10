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

The following controls are implemented in `ewin_omnichannel_core` and
`ewin_omnichannel_telegram`:

- **Webhook endpoint hardening.** Each `omnichannel.account` gets its own random UUID
  (`webhook_uuid`), and the public webhook route
  (`/omnichannel/webhook/<channel_code>/<account_uuid>`) is looked up by that UUID rather
  than a predictable ID. On top of the UUID, Telegram's `X-Telegram-Bot-Api-Secret-Token`
  header is verified against a per-account random secret generated at webhook registration
  time, using `hmac.compare_digest` (constant-time comparison) to avoid timing side
  channels. Requests with a missing/incorrect secret, an unknown account UUID, a disabled
  account, or a malformed body are rejected with a plain `200 OK` and no job is enqueued —
  the webhook never leaks whether an account exists or why a request was rejected.
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
  conversation, message, team, and event restrict each record to its own company (or a
  global/no-company record), so users in Company A never see conversations, messages, or
  account configuration belonging to Company B.
- **Raw payload isolation.** The raw inbound payload (`omnichannel.message.raw_payload`) is
  an admin-only field, kept for debugging/audit but not exposed to operators.

## Known limitations

This is an MVP-scope implementation. It has not undergone a third-party security audit.
In particular: there is no automated reclaim of stuck/crashed queue jobs, and the
constant-time secret check does not fully equalize response timing between an "unknown
account" and a "wrong secret" rejection (the webhook UUID itself has enough entropy that
this is a low-risk gap). Please report anything you find via the channel above rather than
relying on this list being exhaustive.
