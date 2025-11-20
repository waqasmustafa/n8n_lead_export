# __manifest__.py

{
    "name": "AI Call Lead Export",
    "version": "18.0.1.0.0",
    "summary": "Automated AI Call Campaigns: Export Leads to Webhook with Tagging & Logging",
    "description": """
AI Call Lead Export
===================
This module automates the process of sending Odoo CRM Leads to an external AI Calling service via Webhook.

Key Features:
-------------
*   **Campaign Management:** Create multiple campaigns with specific filters (e.g., by Stage, Tag, Country).
*   **Automated Scheduling:** Set specific time windows (Start/End Time) for campaigns to run, respecting your local timezone.
*   **Throttling:** Control the speed of exports with a configurable delay between requests.
*   **Webhook Integration:** Sends Lead ID, Name, Email, and Phone Number to your specified Webhook URL.
*   **Smart Tagging:** Automatically tags leads as "AI Call" upon successful export to prevent duplicate calls.
*   **Detailed Logging:** Tracks every attempt with status (Pending, OK, Error), HTTP response codes, and timestamps.
*   **Manual & Auto Modes:** Trigger campaigns manually or let the Cron job handle it automatically.
    """,
    "category": "CRM",
    "author": "Waqas Mustafa",
    "depends": ["crm"],
    "data": [
        "security/ir.model.access.csv",
        "views/n8n_campaign_views.xml",
        "data/n8n_cron.xml",
    ],
    "icon": "static/description/icon.png",
    "application": True,
    "license": "LGPL-3",
}
