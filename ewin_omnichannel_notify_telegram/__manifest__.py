{
    "name": "EWIN Inbox: Telegram Notifications",
    "summary": "Notify operators in Telegram when a customer writes",
    "version": "18.0.1.0.0",
    "category": "Productivity/Discuss",
    "author": "EWIN.codes",
    "maintainer": "EWIN.codes",
    "website": "https://ewin.codes",
    "support": "info@ewin.codes",
    "license": "LGPL-3",
    "depends": [
        "ewin_omnichannel_core",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/omnichannel_telegram_notifier_views.xml",
        "views/omnichannel_telegram_link_wizard_views.xml",
        "views/res_users_views.xml",
        "views/notify_menus.xml",
    ],
    "application": False,
    "installable": True,
}
