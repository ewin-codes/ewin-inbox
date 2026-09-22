# EWIN Inbox — Telegram Notifications

Notifies staff in Telegram when a customer writes to **EWIN Inbox**. It does
not carry any customer conversation itself — it watches the inbox and pings a
human, in Telegram, that one is waiting.

Depends on `ewin_omnichannel_core`.

## What it does

- **A personal message to the assigned operator**, if that operator has
  connected their own Telegram — or **the shared team chat**, when the
  conversation has no operator yet, or the operator has one but hasn't
  connected Telegram. A notification with nowhere to go is worse than a noisy
  group chat, so the group is the floor, not a fallback for the exceptional
  case.
- **Throttling per conversation**, ten minutes by default (configurable, and a
  window of zero simply never throttles). A customer who sends five messages
  in a row produces one notification, not five — but the very first message of
  a conversation always notifies, whatever the window, so a new conversation
  is never silent.
- **The notification text** is three lines: the channel and the customer's
  name (with their @handle appended alongside it whenever they have one that
  differs from the name — useful both for addressing them back and for
  telling two same-named customers apart), the opening of what they wrote,
  cut to 200 characters (a message with no text of its own, like a photo, is
  named by its type instead), and a link back into that conversation in Odoo.
- **Delivery goes through the shared job queue**, so it arrives with a delay of
  up to about a minute — the same `Omnichannel: Process job queue` cron
  ewin_omnichannel_core runs every minute for every other retriable job in the
  suite. That trade is deliberate: the code that decides *whether* to notify
  runs inside the customer's own inbound webhook request, and it does only two
  cheap, local things there — claim the throttle window and write one row to
  the queue. The actual call to Telegram waits for the next cron tick. Putting
  it there instead means a slow or unreachable Telegram can never delay, or
  fail, the response the channel's own connector owes back to the customer's
  provider for the message that was just received.

## Not the connector's bot

This is a **second Telegram bot**, with its own token, its own webhook route,
and nothing shared with `ewin_omnichannel_telegram`, the customer-facing
connector. That separation is not incidental: the connector's bot is the one
customers write to, and if this module reused it, an operator who opened that
same bot in their own Telegram app to check it — or just to say hello — would
have their message land back in Inbox as a new customer conversation, with the
operator as the customer talking to themselves. Two bots, two identities: one
customers write to, one that only ever writes to staff.

Because it is a separate bot, this module also does not depend on
`ewin_omnichannel_telegram` at all and installs on any database, whether or
not the Telegram connector is present.

## How it works

- **`TelegramNotifyClient`** (`services/notify_api_client.py`) — a thin
  wrapper over the four Bot API calls this module actually uses: `getMe`,
  `setWebhook`, `deleteWebhook`, `sendMessage`. It classifies a failure as
  retriable or terminal from the description Telegram returns, and it never
  lets a bot token reach a log line or an exception message.
- **`omnichannel.telegram.notifier`** (`models/omnichannel_telegram_notifier.py`)
  — one record per company (a constraint refuses a second active one), holding
  the bot token, the group chat id, the throttle window, the webhook
  configuration, and a `state`/`last_error` pair that is the health check at a
  glance. Its three header buttons — **Check Connection**, **Register
  Webhook**, **Remove Webhook** — all call the provider and all catch a
  provider failure the same way: as a sticky red notification, not as an
  exception. That distinction matters. An exception escaping a button would
  roll the whole request back — including the `state = error` / `last_error`
  write that was supposed to record what just happened — so the record would
  keep claiming it was healthy after a failed call. Catching the error and
  returning a notification instead lets that write land, which is what makes
  the state badge trustworthy. (**Remove Webhook** is the one exception: on
  failure it shows the same sticky notification but leaves `state` and
  `last_error` exactly as they were.)
- **`omnichannel.telegram.notification.service`** (`services/notification_service.py`)
  — `schedule(message)` claims the throttle window and enqueues one
  `omnichannel.job` row; `send_notification(notifier_id, message_id)` is the
  job's entry point and the only method this model publishes for the queue to
  call (`_job_methods`). It resolves the recipient and re-reads the notifier
  and the message fresh when the job actually runs, not when it was queued —
  if the conversation changed hands while the job waited, the notification
  goes to whoever holds it now.
- **The hook lives on `omnichannel.message.create()`**
  (`models/omnichannel_message.py`), not on
  `omnichannel_core`'s `message_service.create_inbound`. That service returns
  the row it already has when a provider redelivers an update it already
  processed, and an override placed there could not tell "just created" from
  "found again" without repeating its own deduplication query. A database row
  is born exactly once, so `create()` is where "once" lives. The hook only
  ever acts on inbound customer messages, and any failure in scheduling is
  caught and logged rather than allowed to propagate — this call happens
  inside the channel's own webhook transaction, and a notification add-on has
  no right to cost the customer their message.
- **`tg_last_notified_at`** on `omnichannel.conversation`
  (`models/omnichannel_conversation.py`) is claimed with one conditional
  `UPDATE ... RETURNING id`, guarded by the same `IS NULL OR <= cutoff` test
  the throttle window needs, not a read-then-write. Two inbound messages
  landing in the same instant reach two different workers; both would read
  the same timestamp and both would decide to notify. The conditional
  `UPDATE` lets PostgreSQL settle it instead: exactly one transaction gets a
  row back and may notify, the other gets nothing and leaves quietly.
- **The webhook controller** (`controllers/notify_webhook.py`) answers
  `/omnichannel/notify/telegram/<notifier_uuid>` and understands exactly two
  commands: `/start <token>` in a private chat, which links that chat to the
  user the token belongs to, and `/register` in a group, which adopts that
  group as the notifier's shared chat. Everything else — ordinary chatter,
  any other command — is read and silently ignored.

## Setting it up

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token
   it gives you. This must be a **different bot** from any customer-facing
   Telegram connector already configured.
2. In Odoo, as an **EWIN Inbox / Administrator**, go to
   **EWIN Inbox → Configuration → Telegram Notifications** and create a
   record (nothing is pre-created; one company can hold only one active
   notifier). Paste the token into **Bot Token** — only the admin group can
   read or edit it, everyone else sees it masked. The form walks through the
   rest itself: it shows one step at a time, and each disappears as it is
   done, so what is left on screen is what is left to do.
3. Click **Check Connection**. This calls `getMe` and, on success, fills in
   the bot's username and id and moves the record to **Connected**.
4. Click **Register Webhook** to point Telegram at this database. This
   requires a **public HTTPS `web.base.url`** (Settings → Technical → System
   Parameters) that Telegram's own servers can reach — a local
   `http://localhost:8069` will not work. Pressing it before step 3 is fine:
   it asks `getMe` itself when the bot is still unknown, because every later
   step needs the username and nothing about the two buttons says which comes
   first.
5. Each operator connects individually: **Preferences → EWIN Inbox
   Notifications → Connect Telegram** opens a wizard holding a one-time
   personal link (`https://t.me/<bot>?start=<token>`). The link is a link —
   click it, Telegram opens on the bot, press **Start** — and a copy button
   sits beside it for moving it to another device. It works once and expires
   after 24 hours, whichever comes first, so it is a credential and not
   something to forward. **Disconnect Telegram** clears the binding.

   Do this before step 6. `/register` is accepted only from somebody who has
   already connected their own Telegram, so an administrator who skips it
   finds the group command silently refusing them.
6. Add the bot to the team's Telegram group **as an administrator** — Telegram
   restricts what a plain member bot receives in a group by default, and
   making it an admin is the standard way around that — and send `/register`
   there from an account that (a) has already connected its own Telegram, as
   above, and (b) holds the **EWIN Inbox / Administrator** group. The bot
   confirms in the chat once it has adopted the group; from then on, that
   chat is where an unassigned or not-yet-connected conversation notifies.
   A sender who fails either half of that test gets an answer in the chat
   saying so — a silent refusal is indistinguishable from a webhook that
   never arrived, and sends whoever typed the command off debugging the
   wrong thing.
   **Group Chat ID** on the form is filled in by that command and is not
   something to look up: Telegram shows a group's numeric id nowhere in its
   own interface.

Two questions this ordering answers before they are asked. Nobody types a
Telegram username or a chat id anywhere — an operator's binding is made by
opening their own one-time link, and the group's by the bot itself. And the
account form of a Telegram *channel* carries a note saying so, because that
screen is where somebody looking for "the Telegram settings" lands first and
it is the wrong one: an account is the bot customers write to.

## Security

- **The webhook secret is compared as bytes**, through the core's
  `secret_equals`, not as two `str` values. `hmac.compare_digest` raises
  `TypeError` when a `str` argument holds a non-ASCII character, and WSGI
  hands header values through decoded as Latin-1 — so any caller can put one
  in `X-Telegram-Bot-Api-Secret-Token`. Comparing as `str` would let a stray
  byte raise an exception instead of failing the comparison, and that
  exception would answer differently than an ordinary mismatch — telling an
  unauthenticated caller that a given notifier UUID exists at all. Encoding
  both sides to bytes first keeps every rejection, whatever caused it,
  indistinguishable from every other. Every connector in the suite compares
  its own secret through that same helper.
- **An empty stored secret rejects the request; it never waves it through.**
  The webhook address is not a credential on its own — Telegram's servers also
  know it — so a notifier with no secret registered yet must refuse, not
  accept unsigned updates. That rule lives inside `secret_equals` as well.
- **An unknown notifier UUID answers exactly like a bad secret**: a silent
  `200` with nothing else. The route never distinguishes "this address does
  not exist" from "this address exists but you're not authorized," so probing
  UUIDs learns nothing.
- **The whole request is one `try`/`except` with a single exit**: whatever
  happens — bad JSON, an unhandled command shape, an internal error — the
  response is always an empty `200`. Telegram retries an update it did not
  get a fast success for, and a retry against a webhook that had already half
  applied its effect the first time would double it (link a chat twice,
  register a group twice).
- **The bot token and the webhook secret are both restricted to
  `ewin_omnichannel_core.group_omni_admin`**; every other role sees a
  fixed-length mask instead of the token, and never sees the secret at all.
  Provider error text is redacted before it reaches the record, the error
  log, or the Python logger, so a `/bot<token>/...` URL embedded in a network
  exception can't leak the token through a stack trace either.
- **The linking token that connects an operator's own Telegram is a one-time
  credential, and it is treated like one.** It expires 24 hours after
  `Connect Telegram` is pressed, and it is consumed — cleared from the
  record — the moment it is presented to the bot, successfully or not; a
  token that has already been tried once cannot be tried again on the chance
  the clock was wrong. The field that holds it,
  `res.users.omni_tg_link_token`, is closed to everyone but
  `base.group_system`: `res.users` is readable by every internal user, so a
  field of that sensitivity cannot ride along on the model's normal ACL. The
  link itself is handed to the operator through a transient wizard
  (`omnichannel.telegram.link`) instead — and that wizard carries its own
  `ir.rule` scoping it to `create_uid = user.id`. That rule is required
  because a `TransientModel` gets **no** creator-only restriction of its own
  in Odoo 18; without it, any operator holding ordinary read access to the
  wizard model could `search_read` it and read out a colleague's still-valid
  one-time link.
- **`/register` only takes effect from a Telegram account that has already
  linked itself to an Odoo user holding the administrator group.** The
  webhook address travels to Telegram's own servers once it's registered, so
  simply knowing it, or being present in the group, proves nothing about who
  someone is.

## Known limits

- **Telegram's own rate limit can drop a notification under a burst.**
  Telegram accepts roughly 20 messages a minute into one group chat, and
  `omnichannel.job._cron_process_jobs` drains up to 50 jobs per tick. A
  burst — an email connector's first poll bringing in fifty conversations at
  once, say — can push past that and get a `429` back. The client does not
  read `parameters.retry_after` from that response and does not pace sends
  to stay under the limit, so a `429` is just another retriable failure: the
  queue's own backoff handles it, but a big enough burst can exhaust a job's
  retries before Telegram lets it through, and that notification is dropped
  (the error log records it, so it is not lost silently).

## Out of scope

These are intentionally not implemented in this version:

- **Action buttons on the notification** — an inline "Claim" or "Reply"
  button would need its own callback-query handling and its own
  authorization story on top of the one `/register` already has; the
  notification's job is to say a message is waiting, not to become a second
  place conversations are worked from.
- **Replying to the customer from Telegram** — answering from a phone would
  make Telegram a second client of the conversation, with its own ordering,
  translation and attachment handling to keep consistent with Odoo's; the
  "Open conversation" link in every notification is the intended way back in.
- **Attachments in the notification** — forwarding the customer's photo or
  file would repeat a transfer Odoo already completed on the way in; the text
  preview is enough to recognize the message, and the deep link opens the
  real attachment.
- **Notifications for outbound or system events** — this module exists to
  tell a human that a customer is waiting on them, which is what an inbound
  customer message means; an operator's own reply, or a routing/assignment
  change, is not something that operator needs pushed back to their own
  phone.
- **Digests** — a periodic summary would need its own scheduler and its own
  memory of what it has already reported, on top of the per-conversation
  throttle this module already has; that is a second cadence to reason about
  for the same underlying guarantee ("don't repeat yourself"), not a
  refinement of this one.
- **Quiet hours** — Telegram already gives every recipient mute and Do Not
  Disturb on the chat itself; a second, per-notifier schedule here would just
  be one more place notifications can be silently off.
