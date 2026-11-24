{
    "name": "EWIN Inbox: Live Chat",
    "summary": "Odoo website Live Chat connector for EWIN Inbox",
    "version": "20.0.1.0.1",
    "category": "Productivity/Discuss",
    "author": "EWIN.codes",
    "maintainer": "EWIN.codes",
    "website": "https://ewin.codes",
    "support": "info@ewin.codes",
    "license": "LGPL-3",
    "images": ["static/description/banner.png"],
    "depends": [
        "ewin_omnichannel_core",
        "website_livechat",
    ],
    "data": [
        "data/livechat_channel_data.xml",
        "data/livechat_cron.xml",
        "views/omnichannel_account_views.xml",
    ],
    "application": False,
    "installable": True,
}
