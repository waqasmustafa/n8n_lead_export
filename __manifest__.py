# __manifest__.py

{
    "name": "AI Call Lead Export",
    "version": "18.0.1.0.0",
    "summary": "Send filtered leads to n8n Webhook",
    "category": "CRM",
    "author": "Waqas Mustafa",
    "depends": ["crm"],
    "data": [
        "security/ir.model.access.csv",
        "views/n8n_campaign_views.xml",
        "data/n8n_cron.xml",   # ⬅️ NEW
    ],
    "application": False,
    "license": "LGPL-3",
}
