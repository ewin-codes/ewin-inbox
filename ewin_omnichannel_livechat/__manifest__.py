{
    "name": "EWIN Inbox: Live Chat",
    "summary": "Odoo website Live Chat connector for EWIN Inbox",
    "version": "18.0.1.0.0",
    "category": "Productivity/Discuss",
    "author": "EWIN.codes",
    "maintainer": "EWIN.codes",
    "website": "https://ewin.codes",
    "support": "odoo@ewin.codes",
    "license": "LGPL-3",
    "depends": [
        "ewin_omnichannel_core",
        "website_livechat",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/livechat_channel_data.xml",
        "data/livechat_cron.xml",
        "views/omnichannel_account_views.xml",
    ],
    "application": False,
    "installable": True,
}
