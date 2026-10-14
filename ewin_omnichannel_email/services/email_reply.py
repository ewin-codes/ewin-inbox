from lxml import html as lxml_html
from markupsafe import Markup, escape

from odoo import api, fields, models
from odoo.tools import format_datetime

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

# Inline styles, not classes: mail clients drop <style>, and Gmail recognises
# the gmail_quote classes to fold the quote behind its "..." toggle. The gap
# above the quote is a margin rather than a <br/>: it collapses into the
# reply's own paragraph margin, so the two make one blank line, not two.
QUOTE_STYLE = "margin:1em 0 0"
BLOCKQUOTE_STYLE = "margin:0 0 0 .8ex;border-left:1px solid #ccc;padding-left:1ex"

# The quote's own elements, by the classes it is built with, and the inline
# style each must carry. An edited quote comes back through the HTML
# sanitizer, which keeps the classes but drops ``border-left`` — the grey bar
# that makes a quote look like one.
QUOTE_ELEMENT_STYLES = (
    ("//div[contains(concat(' ', @class, ' '), ' gmail_quote ')]", QUOTE_STYLE),
    ("//blockquote[contains(concat(' ', @class, ' '), ' gmail_quote ')]",
     BLOCKQUOTE_STYLE),
)


class EmailReply(models.AbstractModel):
    """What an outgoing email carries beyond the reply itself.

    The thread in Odoo shows each message once, as it was written — the
    signature included, since the composer puts it into the reply. The
    customer's mail client shows the email: that reply, and the conversation
    so far quoted under it. Building the quote at send time rather than
    storing it keeps the thread readable and lets a scheduled reply quote
    what the customer wrote while it was waiting.
    """

    _name = "omnichannel.email.reply"
    _description = "Email Reply Composer"

    @api.model
    def html(self, message):
        """The HTML body the customer receives for ``message``."""
        return self._as_sent(message, depth=0)

    @api.model
    def quote_for_next_reply(self, conversation):
        """The quote a reply written now would carry, for the composer to
        show folded under the textarea. Empty when quoting is off or there
        is nothing to quote yet."""
        if not conversation.account_id.email_quote_history:
            return Markup()
        previous = self._seen(conversation).sorted(self._chronology)[-1:]
        return self._quote(previous, depth=1) if previous else Markup()

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
        ``html`` builds it now — which also means a quote setting changed
        since then is applied to it retroactively.
        """
        if message.direction == "inbound":
            return self._content(message)
        account = message.conversation_id.account_id
        html = self._content(message)
        if message.quote_edited:
            # The operator opened the quote in the composer and changed it:
            # theirs goes out as they left it, deleted parts and all.
            return html + self._restyled(message.quote_body)
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
                message.conversation_id)._("Attachments: %s", ", ".join(names))
        return html

    @api.model
    def _restyled(self, quote):
        """An edited quote with the inline styles of its quote elements put
        back, so it reaches the customer looking like the one we build."""
        if not quote:
            return Markup()
        root = lxml_html.fragment_fromstring(str(quote), create_parent="div")
        for xpath, style in QUOTE_ELEMENT_STYLES:
            for element in root.xpath(xpath):
                element.set("style", style)
        inner = "".join(
            lxml_html.tostring(child, encoding="unicode") for child in root)
        return escape(root.text or "") + Markup(inner)

    @api.model
    def _quote(self, message, depth):
        return Markup(
            '<div class="gmail_quote" style="%s">'
            '<div class="gmail_attr">%s</div>'
            '<blockquote class="gmail_quote" style="%s">%s</blockquote>'
            '</div>') % (
                QUOTE_STYLE, self._attribution(message), BLOCKQUOTE_STYLE,
                self._as_sent(message, depth))

    @api.model
    def _attribution(self, message):
        """The "On <date>, <who> wrote:" line above a quote, in the
        operator's language and time zone — they are the one writing."""
        name, address = self._author(message)
        who = "%s <%s>" % (name, address) if name and address \
            else name or address or ""
        operator = self._operator(message.conversation_id)
        when = format_datetime(
            self.env, self._moment(message), tz=operator.tz or "UTC",
            dt_format="medium", lang_code=operator.lang)
        return self._operator_env(message.conversation_id)._(
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
        seen = self._seen(message.conversation_id) - message
        if self._is_being_sent(message):
            return seen
        key = self._chronology(message)
        return seen.filtered(lambda m: self._chronology(m) < key)

    @api.model
    def _seen(self, conversation):
        """Every message of the conversation that reached the customer, in
        either direction."""
        return conversation.omni_message_ids.filtered(
            lambda m: not m.is_internal
            and m.message_type != "system"
            and (m.direction == "inbound" or m.state in DELIVERED_STATES))

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
    def _operator(self, conversation):
        return conversation.operator_id or self.env.user

    @api.model
    def _operator_env(self, conversation):
        """An environment in the operator's language, for the few words
        this adds to the email. The send may run in the cron, whose own
        environment speaks English whoever wrote the reply."""
        return self.with_context(lang=self._operator(conversation).lang).env
