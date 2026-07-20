{
    "name": "EWIN Inbox WhatsApp",
    "summary": "WhatsApp Business (Meta Cloud API) connector for EWIN Inbox",
    "version": "18.0.1.0.0",
    "category": "Productivity/Discuss",
    "author": "EWIN",
    "website": "https://ewin.codes",
    "license": "LGPL-3",
    "depends": [
        "ewin_omnichannel_core",
    ],
    "data": [
        "data/whatsapp_channel_data.xml",
        "security/ir.model.access.csv",
        "views/omnichannel_account_views.xml",
        "views/whatsapp_template_views.xml",
        "views/whatsapp_send_template_views.xml",
        "views/omnichannel_conversation_views.xml",
    ],
    "application": False,
    "installable": True,
}
