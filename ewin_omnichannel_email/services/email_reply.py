from markupsafe import Markup

from odoo import api, fields, models
from odoo.tools import format_datetime, is_html_empty

# States in which an outbound message is known to have reached the customer.
# A failed, cancelled or still-scheduled reply was never in their inbox, so it
# has no place in the quoted history.
DELIVERED_STATES = ("sent", "delivered", "read")

# How many earlier messages one email may nest. Each of our own replies quotes
# the one before it, so a run of follow-ups without an answer would otherwise
# grow without end; an answer from the customer ends the run anyway, because
# their mail client has already quoted everything older.
MAX_QUOTE_DEPTH = 10

# How many earlier Message-IDs travel in the References header. Mail clients
# thread on the newest few; RFC 5322 allows trimming the oldest.
MAX_REFERENCES = 20

# Inline style, not a class: mail clients drop <style>, and Gmail recognises
# the gmail_quote classes to fold the quote behind its "..." toggle.
QUOTE_STYLE = "margin:0 0 0 .8ex;border-left:1px solid #ccc;padding-left:1ex"


class EmailReply(models.AbstractModel):
    """What an outgoing email carries beyond the operator's own words.

    The thread in Odoo shows each message once, as it was written. The
    customer's mail client shows the email: the reply, the signatures under
    it, and the conversation so far, quoted. Building that at send time
    rather than storing it keeps the thread readable and lets a scheduled
    reply quote what the customer wrote while it was waiting.
    """

    _name = "omnichannel.email.reply"
    _description = "Email Reply Composer"

    @api.model
    def html(self, message):
        """The HTML body the customer receives for ``message``."""
        return self._as_sent(message, depth=0)

    @api.model
    def references(self, message):
        """The References header: every earlier message of the conversation
        the customer has seen, oldest first, so their client threads the
        reply under the whole exchange and not only the last email."""
        earlier = self._history(message).filtered("external_message_id")
        ids = earlier.sorted(self._chronology).mapped("external_message_id")
        return " ".join(ids[-MAX_REFERENCES:]) or None

    # ---- the body, as the customer saw it ----

    @api.model
    def _as_sent(self, message, depth):
        """``message`` as it reached the customer.

        A customer's email is its own stored body: whatever their client
        quoted under it is already in there. One of ours is rebuilt the way
        ``html`` builds it now — which also means a signature or quote setting
        changed since then is applied to it retroactively.
        """
        if message.direction == "inbound":
            return self._content(message)
        account = message.conversation_id.account_id
        html = self._content(message) + self._signatures(message)
        if account.email_quote_history and depth < MAX_QUOTE_DEPTH:
            previous = self._previous(message)
            if previous:
                html += self._quote(previous, depth + 1)
        return html

    @api.model
    def _content(self, message):
        """The message's own words, with the names of its files: the files
        themselves travel only with the email that carried them."""
        html = message.body or Markup()
        names = message.attachment_ids.mapped("name")
        if names:
            html += Markup("<p><i>%s</i></p>") % self._operator_env(
                message)._("Attachments: %s", ", ".join(names))
        return html

    @api.model
    def _signatures(self, message):
        """The replying operator's own signature, then the account's."""
        account = message.conversation_id.account_id
        signatures = []
        if account.email_signature_operator:
            # sudo: the cron sends scheduled replies as the superuser and an
            # operator may not read a colleague's user record; the signature
            # is going out under that colleague's name either way. Archived
            # users count too: a reply written before they left still goes
            # out signed by them.
            author = message.author_partner_id.sudo().with_context(
                active_test=False).user_ids[:1]
            if author and not is_html_empty(author.signature):
                signatures.append(author.signature)
        if not is_html_empty(account.email_signature):
            signatures.append(account.email_signature)
        return Markup().join(
            Markup('<br/><div class="o_omni_signature">%s</div>') % signature
            for signature in signatures)

    @api.model
    def _quote(self, message, depth):
        return Markup(
            '<br/><div class="gmail_quote">'
            '<div class="gmail_attr">%s</div>'
            '<blockquote class="gmail_quote" style="%s">%s</blockquote>'
            '</div>') % (
                self._attribution(message), QUOTE_STYLE,
                self._as_sent(message, depth))

    @api.model
    def _attribution(self, message):
        """The "On <date>, <who> wrote:" line above a quote, in the
        operator's language and time zone — they are the one writing."""
        name, address = self._author(message)
        who = "%s <%s>" % (name, address) if name and address \
            else name or address or ""
        operator = self._operator(message)
        when = format_datetime(
            self.env, self._moment(message), tz=operator.tz or "UTC",
            dt_format="medium", lang_code=operator.lang)
        return self._operator_env(message)._(
            "On %(date)s, %(author)s wrote:", date=when, author=who)

    @api.model
    def _author(self, message):
        """(name, address) of whoever sent ``message``, as the customer's
        client displayed it."""
        if message.direction == "outbound":
            return message.conversation_id.account_id._email_sender()
        partner = message.author_partner_id
        identity = message.conversation_id.identity_id
        return (partner.name or identity.display_name,
                partner.email or identity.external_id)

    # ---- the history ----

    @api.model
    def _history(self, message):
        """Every message of the conversation the customer had seen before
        ``message`` reached them.

        For the reply being sent right now that is everything already seen —
        a scheduled one included, so it quotes what the customer wrote while
        it waited. For one of ours sent earlier it is what came before it;
        timestamps keep whole seconds, so the id settles a tie.
        """
        seen = message.conversation_id.omni_message_ids.filtered(
            lambda m: m != message
            and not m.is_internal
            and m.message_type != "system"
            and (m.direction == "inbound" or m.state in DELIVERED_STATES))
        if self._is_being_sent(message):
            return seen
        key = self._chronology(message)
        return seen.filtered(lambda m: self._chronology(m) < key)

    @api.model
    def _previous(self, message):
        return self._history(message).sorted(self._chronology)[-1:]

    @api.model
    def _is_being_sent(self, message):
        return message.direction == "outbound" and not message.sent_at

    @api.model
    def _chronology(self, message):
        return (self._moment(message), message.id)

    @api.model
    def _moment(self, message):
        """When the message reached the other side."""
        if message.direction == "inbound":
            return message.received_at or message.create_date
        return message.sent_at or fields.Datetime.now()

    # ---- language ----

    @api.model
    def _operator(self, message):
        conversation = message.conversation_id
        return conversation.operator_id or self.env.user

    @api.model
    def _operator_env(self, message):
        """An environment in the operator's language, for the few words
        this adds to the email. The send may run in the cron, whose own
        environment speaks English whoever wrote the reply."""
        return self.with_context(lang=self._operator(message).lang).env
