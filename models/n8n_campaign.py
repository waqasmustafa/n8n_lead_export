import ast
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    import requests
except ImportError:
    requests = None


class N8nCampaign(models.Model):
    _name = "n8n.campaign"
    _description = "n8n Lead Export Campaign"

    name = fields.Char(string="Campaign Name", required=True)

    target_model = fields.Selection(
        selection=[
            ("crm.lead", "Lead / Opportunity"),
            # future: ("res.partner", "Contacts"),
        ],
        string="Target From",
        default="crm.lead",
        required=True,
    )

    webhook_url = fields.Char(
        string="n8n Webhook URL",
        help="Paste the n8n Webhook URL here.",
        required=True,
    )

    filter_domain = fields.Char(
        string="Filter",
        default="[]",
        help="Filter for records to send. Use the domain builder UI.",
    )

    record_count = fields.Integer(
        string="Matching Records",
        compute="_compute_record_count",
        readonly=True,
    )

    @api.depends("filter_domain", "target_model")
    def _compute_record_count(self):
        for campaign in self:
            model = campaign._get_target_model()
            domain = campaign._get_domain()
            if model is None:
                campaign.record_count = 0
                continue
            campaign.record_count = model.search_count(domain)

    # -----------------------------
    # Helpers
    # -----------------------------
    def _get_target_model(self):
        """Return env model object based on target_model selection."""
        self.ensure_one()
        if self.target_model == "crm.lead":
            return self.env["crm.lead"]
        return None

    def _get_domain(self):
        """Parse the domain string into a Python list."""
        self.ensure_one()
        if not self.filter_domain:
            return []
        try:
            value = ast.literal_eval(self.filter_domain)
            if isinstance(value, (list, tuple)):
                return value
            raise ValueError("Domain must be list/tuple")
        except Exception as e:
            raise UserError(_("Invalid domain in Filter: %s") % e)

    # -----------------------------
    # Main Action
    # -----------------------------
    def action_send_to_n8n(self):
        """Collect matching records and send them to the n8n Webhook URL."""
        if requests is None:
            raise UserError(
                _(
                    "The Python 'requests' library is not available on the server. "
                    "Please install it to send data to n8n."
                )
            )

        for campaign in self:
            if not campaign.webhook_url:
                raise UserError(_("Please set the n8n Webhook URL first."))

            model = campaign._get_target_model()
            if model is None:
                raise UserError(_("Unsupported target model: %s") % (campaign.target_model,))

            domain = campaign._get_domain()
            records = model.search(domain)

            # Build payload: ID, Name, Email only
            payload_records = []
            for rec in records:
                email = getattr(rec, "email_from", False) or getattr(rec, "email", False)
                payload_records.append(
                    {
                        "id": rec.id,
                        "name": rec.name or "",
                        "email": email or "",
                    }
                )

            payload = {
                "campaign_id": campaign.id,
                "campaign_name": campaign.name,
                "target_model": campaign.target_model,
                "count": len(payload_records),
                "records": payload_records,
            }

            _logger.info("Sending %s records to n8n webhook %s", len(payload_records), campaign.webhook_url)

            try:
                response = requests.post(
                    campaign.webhook_url,
                    json=payload,
                    timeout=20,
                )
                response.raise_for_status()
            except Exception as e:
                _logger.exception("Error sending data to n8n")
                raise UserError(_("Error sending data to n8n:\n%s") % e)

        return True
