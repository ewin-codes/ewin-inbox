from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Mark the conversations already set aside as read.

    Waiting for the customer and closing now mark a conversation read for
    everyone in its mirror. Those parked or closed before that keep whatever
    was unread at the time, and the conversation list goes on showing it on
    their rows; this clears it the way the buttons do today.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["omnichannel.conversation"].with_context(active_test=False).search([
        ("state", "in", ("pending", "closed")),
        ("discuss_channel_id", "!=", False),
    ])._mark_read_by()
