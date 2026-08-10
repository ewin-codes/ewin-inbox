{
    "name": "EWIN Inbox: Email",
    "summary": "Email (IMAP/SMTP) connector for EWIN Inbox",
    "version": "18.0.1.0.0",
    "category": "Productivity/Discuss",
    "author": "EWIN.codes",
    "maintainer": "EWIN.codes",
    "website": "https://ewin.codes",
    "support": "info@ewin.codes",
    "license": "LGPL-3",
    "depends": ["ewin_omnichannel_core"],
    "data": [
        "data/email_channel_data.xml",
        "security/ir.model.access.csv",
        "views/omnichannel_account_views.xml",
    ],
    "application": False,
    "installable": True,
}
