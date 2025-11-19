from odoo import models, fields


class N8nCampaignLog(models.Model):
    _name = "n8n.campaign.log"
    _description = "n8n Campaign Send Log"
    _order = "id desc"

    campaign_id = fields.Many2one(
        "n8n.campaign",
        required=True,
        ondelete="cascade"
    )

    lead_id = fields.Many2one("crm.lead", string="Lead")
    lead_odoo_id = fields.Integer(string="Lead ID")
    name = fields.Char(string="Lead Name")
    email = fields.Char(string="Email")

    status = fields.Selection(
        [
            ("pending", "Pending"),
            ("ok", "OK"),
            ("error", "Error"),
        ],
        default="pending"
    )

    http_status = fields.Char(string="HTTP Status")
    message = fields.Char(string="Message")
    sent_at = fields.Datetime(string="Sent At")
