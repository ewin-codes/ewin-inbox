from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import format_datetime

INTERNAL_BADGE = Markup(
    '<span class="o_omni_internal_marker">'
    '<i class="fa fa-lock"></i> Internal note</span>')


class MessageService(models.AbstractModel):
    _name = "omnichannel.message.service"
    _description = "Omnichannel Message Service"

    @api.model
    def create_inbound(self, conversation, normalized_message, attachments=None):
        ext_id = normalized_message.get("external_message_id")
        if ext_id:
            existing = self.env["omnichannel.message"].search([
                ("account_id", "=", conversation.account_id.id),
                ("external_message_id", "=", ext_id),
                ("direction", "=", "inbound"),
            ], limit=1)
            if existing:
                return existing
        now = fields.Datetime.now()
        msg_type = normalized_message.get("type", "text")
        supported = {"text", "image", "document", "audio", "video", "voice",
                     "location", "contact", "sticker"}
        if msg_type not in supported and msg_type != "system":
            msg_type = "unsupported"
        body = normalized_message.get("text") or ""
        if msg_type == "unsupported":
            body = body or "[Unsupported message type — open the source channel to view.]"
        message = self.env["omnichannel.message"].create({
            "conversation_id": conversation.id,
            "direction": "inbound",
            "sender_type": "customer",
            "message_type": msg_type,
            "body": body,
            "external_message_id": normalized_message.get("external_message_id"),
            "external_reply_to_id": normalized_message.get("reply_to_external_message_id"),
            "state": "received",
            "received_at": now,
            "author_partner_id": conversation.partner_id.id or False,
            "attachment_ids": [(6, 0, (attachments or self.env["ir.attachment"]).ids)],
            "raw_payload": normalized_message.get("raw", {}),
        })
        conv_vals = {
            "last_message_at": now,
            "last_customer_message_at": now,
            "state": "open" if conversation.state == "new" and conversation.operator_id
                     else conversation.state,
        }
        if not conversation.first_customer_message_at:
            conv_vals["first_customer_message_at"] = now
        conversation.write(conv_vals)
        self._mirror_to_discuss(conversation, message)
        self.env["omnichannel.history.service"].mirror(message)
        # keep the assigned operator subscribed to the mirror channel so the
        # Discuss systray notifies them of this inbound even when the record
        # is not open (membership may predate their assignment).
        conversation._sync_channel_members()
        conversation._notify_omni_event("message_received")
        return message

    @api.model
    def _mirror_to_discuss(self, conversation, message):
        channel = conversation._ensure_discuss_channel()
        author = message.author_partner_id or conversation.partner_id \
            or self.env.ref("base.partner_root")
        # Internal notes stay in Odoo; prefix a visible badge so they are
        # obvious in the mirrored Discuss thread (they are not sent to the
        # customer). See discuss.channel override which skips forwarding them.
        body = Markup(message.body or "")
        if message.is_internal:
            body = INTERNAL_BADGE + body
        # omni_mirror flags this as our own mirror so the discuss.channel
        # override does not treat it as an operator reply to forward.
        mail_message = channel.with_context(omni_mirror=True).message_post(
            body=body,
            author_id=author.id,
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
            attachment_ids=message.attachment_ids.ids,
        )
        message.mail_message_id = mail_message.id
        return mail_message

    @api.model
    def _finalize_send(self, conversation, message, is_internal=False):
        """Turn a created outbound row into a message the customer, the thread
        and the reports all agree happened.

        This is the one place that sequence lives: set the conversation clock,
        mirror to the customer-facing thread, record in history, notify
        subscribers, and hand to the delivery pipeline. Both ``create_outbound``
        (immediate reply) and ``release_scheduled`` call it; a change to this
        sequence cannot be applied to one path and forgotten in the other.

        The Discuss-reply path (``create_outbound_from_discuss``) finalizes
        separately because its message is already in the channel and must not
        be mirrored twice.
        """
        now = fields.Datetime.now()
        conv_vals = {
            "last_message_at": now,
            "last_operator_message_at": now,
        }
        if not is_internal and not conversation.first_operator_message_at:
            conv_vals["first_operator_message_at"] = now
        conversation.write(conv_vals)
        self._mirror_to_discuss(conversation, message)
        self.env["omnichannel.history.service"].mirror(message)
        conversation._notify_omni_event("message_sent")
        if not is_internal:
            # The first attempt is immediate (synchronous). Only retries go
            # through the ir.cron queue.
            self.env["omnichannel.routing.service"].deliver_outbound(message)

    @api.model
    def create_outbound(self, conversation, body, is_internal=False,
                        attachments=None, scheduled_at=None):
        if scheduled_at:
            if is_internal:
                raise UserError(_(
                    "An internal note is never delivered to the customer, so "
                    "there is nothing to schedule."))
            return self._create_scheduled(
                conversation, body, attachments, scheduled_at)
        # Replying to a customer takes an unassigned conversation automatically
        # (internal notes do not — writing a note is not answering the customer).
        if not is_internal:
            conversation._ensure_operator()
        message = self.env["omnichannel.message"].create({
            "conversation_id": conversation.id,
            "direction": "outbound",
            "sender_type": "operator",
            "is_internal": is_internal,
            "message_type": "text",
            "body": body,
            "author_partner_id": self.env.user.partner_id.id,
            "state": "queued" if not is_internal else "sent",
            "attachment_ids": [(6, 0, (attachments or self.env["ir.attachment"]).ids)],
        })
        self._finalize_send(conversation, message, is_internal)
        return message

    @api.model
    def _create_scheduled(self, conversation, body, attachments, scheduled_at):
        """Park an outbound reply until ``scheduled_at``.

        Everything an immediate reply does beyond creating the row is
        deliberately skipped and left to ``release_scheduled``:

        * no Discuss mirror and no chatter copy — the thread and the customer's
          card must keep showing what the customer has actually seen;
        * no conversation timestamps, and above all no
          ``first_operator_message_at`` — counting a reply from the moment it
          was *planned* would report a two-minute response on a conversation
          the customer waited a day for.

        Scheduling does take the conversation, though: committing to a reply is
        answering, the same as sending one.
        """
        conversation._ensure_operator()
        message = self.env["omnichannel.message"].create({
            "conversation_id": conversation.id,
            "direction": "outbound",
            "sender_type": "operator",
            "is_internal": False,
            "message_type": "text",
            "body": body,
            "author_partner_id": self.env.user.partner_id.id,
            "state": "scheduled",
            "scheduled_at": scheduled_at,
            "scheduled_by": self.env.uid,
            "attachment_ids": [
                (6, 0, (attachments or self.env["ir.attachment"]).ids)],
        })
        conversation.message_post(body=_(
            "Reply scheduled for %(when)s by %(user)s.",
            when=self._format_scheduled(scheduled_at),
            user=self.env.user.name))
        # The realtime signal is what refreshes the clock badge in the
        # conversation list; the panel itself is reloaded by the object button
        # the operator just pressed. See the spec's "Realtime, honestly".
        conversation._notify_omni_event("message_scheduled")
        return message

    @api.model
    def release_scheduled(self, message):
        """Let a scheduled message go — the single door out of ``scheduled``.

        The cron calls it when the time arrives and the panel's "send now"
        button calls it early, which is exactly why the database-level guard on
        the first line matters: both can genuinely fire in the same second, and
        the second caller has to be a no-op rather than a second delivery.

        The state transition is atomic: a conditional UPDATE ensures that only
        one transaction wins the race. The loser finds no rows to update and
        returns False immediately, never reaching the delivery logic.

        Everything ``_create_scheduled`` deferred happens here, in the order a
        reader would expect: the conversation is reopened if it was closed, its
        clock is set, the message appears in the thread and on the customer's
        card, and only then is it handed to the ordinary delivery path — first
        attempt synchronous, transient failure retried by ``omnichannel.job``.
        This method does not reimplement delivery; it releases the brake.

        Returns True if this call performed the release, False if another caller
        already won the race. Callers that post audit events (e.g. "sent by X")
        should post them only on True.
        """
        # Access control at the door: both the cron (superuser) and the "send now"
        # button (operator) go through here. Enforced at the database level, not
        # by checking after an UPDATE that may have no effect.
        message.check_access('write')
        # Flush first: invalidate_recordset below defaults to flush=True,
        # which would otherwise flush a still-pending ORM write to state
        # *after* this UPDATE has already run — overwriting the raw SQL's own
        # result in the wrong direction. Flushing here first means there is
        # nothing left dirty for that later call to flush.
        self.env.flush_all()
        # One statement decides who releases this message. A read followed by a
        # write cannot: the cron holds the row under FOR UPDATE SKIP LOCKED, so a
        # concurrent "send now" passes the state check, blocks on the write, and
        # resumes once the cron has committed — with a cached state that still
        # says scheduled. PostgreSQL re-evaluates this WHERE after the lock is
        # granted, so the loser updates no row and leaves without sending.
        self.env.cr.execute("""
            UPDATE omnichannel_message SET state = 'queued'
             WHERE id = %s AND state = 'scheduled'
         RETURNING id
        """, (message.id,))
        if not self.env.cr.fetchone():
            return False
        message.invalidate_recordset(["state"])
        # The UPDATE goes behind the ORM's back, so the dependency graph must
        # be notified by hand so dependent computed fields recompute.
        message.modified(["state"])
        conversation = message.conversation_id
        if conversation.state == "closed":
            # "Always send": a reply the operator committed to is not swallowed
            # because the thread was closed in the meantime.
            conversation.action_reopen()
        self._finalize_send(conversation, message, is_internal=False)
        return True

    @api.model
    def _format_scheduled(self, when):
        """A send time in the reader's own timezone, for a chatter line."""
        return format_datetime(self.env, fields.Datetime.to_datetime(when))

    @api.model
    def create_outbound_from_discuss(self, conversation, mail_message):
        """An operator typed directly in the linked Discuss channel. Wrap
        the existing mail.message as an outbound omni message and deliver it to
        the provider — without re-mirroring, since it is already in the channel.
        Idempotent on mail_message_id."""
        existing = self.env["omnichannel.message"].search(
            [("mail_message_id", "=", mail_message.id)], limit=1)
        if existing:
            return existing
        now = fields.Datetime.now()
        # An operator answering from the mirrored Discuss channel also takes
        # the conversation if it is still unassigned.
        conversation._ensure_operator()
        message = self.env["omnichannel.message"].create({
            "conversation_id": conversation.id,
            "direction": "outbound",
            "sender_type": "operator",
            "is_internal": False,
            "message_type": "text",
            "body": mail_message.body,
            "author_partner_id": mail_message.author_id.id,
            "mail_message_id": mail_message.id,
            "state": "queued",
            "attachment_ids": [(6, 0, mail_message.attachment_ids.ids)],
        })
        conv_vals = {
            "last_message_at": now,
            "last_operator_message_at": now,
        }
        if not conversation.first_operator_message_at:
            conv_vals["first_operator_message_at"] = now
        conversation.write(conv_vals)
        self.env["omnichannel.history.service"].mirror(message)
        conversation._notify_omni_event("message_sent")
        self.env["omnichannel.routing.service"].deliver_outbound(message)
        return message
