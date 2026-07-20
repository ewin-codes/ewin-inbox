# EWIN Inbox — open-source omnichannel inbox for Odoo

EWIN Inbox is an extensible omnichannel platform for Odoo 18 Community. Operators handle
every customer conversation — regardless of channel — from a single inbox inside Odoo. The
core is fully channel-agnostic; the first connector shipped is the **Telegram Bot API**.
Adding a new channel later (WhatsApp, Viber, etc.) means writing a new connector module —
it does not require changing the core.

- **License:** LGPL-3 (see `LICENSE`)
- **Website:** https://ewin.codes

## Modules

| Module | Purpose |
|---|---|
| `ewin_omnichannel_core` | Channel-agnostic core: channels, accounts, identities, conversations, messages, teams, tags, error log, the connector contract, the job queue, and the operator UI (Inbox menu under Discuss). Depends on `base`, `mail`, `contacts`. |
| `ewin_omnichannel_telegram` | Telegram Bot connector: account settings (bot token, webhook), the Telegram API client, webhook controller, inbound/outbound message handling, attachment download/upload. Depends on `ewin_omnichannel_core`. |
| `ewin_omnichannel_livechat` | Live Chat connector: bridges Odoo's own website Live Chat (`website_livechat`) into Inbox as a two-way channel via an in-process `discuss.channel.message_post` hook — no webhook. Depends on `ewin_omnichannel_core`, `website_livechat`. |

All modules use Odoo model names in the `omnichannel.*` namespace (e.g. `omnichannel.conversation`);
only the Odoo *module* names carry the `ewin_` prefix.

## Installation

Install the core first, then the Telegram connector:

```bash
docker compose exec -T odoo odoo -d <your-db> -i ewin_omnichannel_core --stop-after-init --no-http
docker compose exec -T odoo odoo -d <your-db> -i ewin_omnichannel_telegram --stop-after-init --no-http
```

(Or, from the Odoo Apps UI: search "EWIN", install **EWIN Inbox Core**, then **EWIN Inbox
Telegram**.) After install, the **EWIN Inbox** menu appears with Inbox, My
Conversations, Unassigned, All Conversations, Contacts, and Configuration (Channels,
Accounts, Teams, Tags, Error Logs).

## Connect a Telegram bot

1. Create a bot with [@BotFather](https://t.me/BotFather) on Telegram and copy the bot
   token it gives you.
2. In Odoo, as an **Omnichannel: Administrator**, go to **EWIN Inbox → Configuration →
   Accounts** and create a new record:
   - **Channel:** Telegram
   - **Bot Token:** paste the BotFather token (this field is admin-only; other roles only
     ever see a masked value)
   - optionally set default team/operator, welcome message, file-download and
     auto-create-contact preferences
3. Click **Check Connection** — this calls Telegram's `getMe` and fills in the bot username
   and bot ID if the token is valid.
4. Click **Register Webhook** to point Telegram at this Odoo instance. This requires
   `web.base.url` (Settings → Technical → System Parameters) to be a **public, HTTPS**
   URL that Telegram's servers can reach — a local `http://localhost:8069` will not work.
   Registration also generates a per-account random webhook secret that is checked on every
   incoming request (see `SECURITY.md`).
5. Use **Webhook Status** to confirm Telegram has the webhook registered. Outbound delivery
   is verified end-to-end by replying to a real conversation (see Scenario 3 below) — the
   **Send Test** button is a placeholder that requires an existing chat id and currently
   always raises an error if clicked before any conversation exists.
6. Send a message to the bot from Telegram — it should appear as a new conversation in the
   **Inbox**, with a linked Discuss channel, within a few seconds (processed by the
   `omnichannel.job` queue cron, which runs every minute).

Use **Remove Webhook** to disconnect, and the account's **state**/**last error** fields for
at-a-glance troubleshooting.

## Acceptance scenarios (manual QA)

These mirror the scenarios covered by the automated test suite; run them once manually
against a real Telegram bot before a release, since the tests mock the Telegram API.

1. **Connect a bot** — create an Account (channel Telegram), set a valid token, Check
   Connection succeeds, Register Webhook succeeds (requires public HTTPS `web.base.url`).
2. **New customer writes in** — first message from a Telegram user creates an
   `omnichannel.identity`, a `res.partner` contact, a new `omnichannel.conversation`
   (state `new`), and a linked `discuss.channel`; the message appears in the Inbox.
3. **Operator replies** — replying from the conversation composer sends the message to
   Telegram and the `omnichannel.message` record moves to state `sent` (then `delivered`
   once confirmed).
4. **Customer repeats/re-sends** — a second message from the same Telegram user reuses the
   existing identity, contact, and open conversation — no duplicate contact or conversation
   is created.
5. **Attachments both ways** — a photo/document sent by the customer is downloaded and
   attached to the inbound message; a file attached by the operator to an outbound reply is
   uploaded to Telegram (`sendPhoto`/`sendDocument`).
6. **Send error** — if delivery to Telegram fails (e.g. bot blocked by the user, chat not
   found, invalid token), the message is marked `failed` with a friendly reason and an
   `omnichannel.error.log` entry is created; non-retriable errors do not keep retrying.
7. **Permissions** — a user with only the **Omnichannel: Operator** role cannot see the bot
   token or webhook secret fields (admin-only), and cannot see conversations/messages/
   accounts belonging to a different company than their own (multi-company record rules).
8. **Duplicate webhook delivery** — if Telegram redelivers the same `update_id` (e.g. after
   a slow 200 response), the event is recognized as already processed
   (`omnichannel.event` idempotency, unique per account+external event id) and only a
   single message is created.

## License

LGPL-3. See `LICENSE`.
