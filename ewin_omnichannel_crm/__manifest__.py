{
    "name": "EWIN Inbox: CRM",
    "summary": "Link EWIN Inbox conversations to CRM leads",
    "version": "18.0.1.0.0",
    "category": "Productivity/Discuss",
    "author": "EWIN.codes",
    "maintainer": "EWIN.codes",
    "website": "https://ewin.codes",
    "support": "info@ewin.codes",
    "license": "LGPL-3",
    "depends": [
        "ewin_omnichannel_core",
        "crm",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/omnichannel_conversation_views.xml",
        "views/omnichannel_conversation_link_wizard_views.xml",
        "views/crm_lead_views.xml",
    ],
    "application": False,
    "installable": True,
}
