from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Give the existing WhatsApp, Instagram and Live Chat mirrors their avatar.

    A mirror channel takes its brand avatar once, when it is created, and those
    three channels shipped none — so every conversation already opened on them
    sits in the Discuss sidebar as a generic '#'. New mirrors now get the
    avatar on creation; this fills in the ones that predate it.

    Only mirrors still without an image are touched, so an avatar somebody set
    by hand stays.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    conversations = env["omnichannel.conversation"].with_context(
        active_test=False).search([
            ("channel_id.code", "in", ("whatsapp", "instagram", "livechat")),
            ("discuss_channel_id", "!=", False),
        ])
    for code in set(conversations.mapped("channel_id.code")):
        avatar = conversations._channel_avatar_b64(code)
        if not avatar:
            continue
        mirrors = conversations.filtered(
            lambda conv: conv.channel_id.code == code).discuss_channel_id
        mirrors.filtered(lambda channel: not channel.image_128).write(
            {"image_128": avatar})
