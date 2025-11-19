import ast
import logging
import time   # 👈 NEW
from odoo import models, fields, api, _
from odoo.exceptions import UserError

try:
    import requests
except ImportError:
    requests = None

_logger = logging.getLogger(__name__)


class N8nCampaign(models.Model):
    _name = "n8n.campaign"
    _description = "n8n Campaign Export"

    # --- existing fields (name, target_model, webhook_url, filter_domain, record_count) ---

    delay_seconds = fields.Integer(
        string="Delay (seconds)",
        default=0,
        help="Wait this many seconds before sending the next record to n8n.",
    )

    log_ids = fields.One2many(
        "n8n.campaign.log",
        "campaign_id",
        string="Send Logs",
        readonly=True,
    )

    # ... existing helpers _get_target_model, _get_domain, _compute_record_count ...

    def action_send_to_n8n(self):
        """Send records one-by-one to n8n and log each attempt."""
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
                raise UserError(
                    _("Unsupported target model: %s") % (campaign.target_model,)
                )

            domain = campaign._get_domain()
            leads = model.search(domain)

            _logger.info(
                "Sending %s records one-by-one to n8n webhook %s",
                len(leads),
                campaign.webhook_url,
            )

            for lead in leads:
                email = getattr(lead, "email_from", False) or getattr(
                    lead, "email", False
                )

                # 1) create log as pending
                log = self.env["n8n.campaign.log"].create(
                    {
                        "campaign_id": campaign.id,
                        "lead_id": lead.id,
                        "lead_odoo_id": lead.id,
                        "name": lead.name or "",
                        "email": email or "",
                        "status": "pending",
                    }
                )

                # 2) build payload for single record
                payload = {
                    "campaign_id": campaign.id,
                    "campaign_name": campaign.name,
                    "target_model": campaign.target_model,
                    "count": 1,
                    "records": [
                        {
                            "id": lead.id,
                            "name": lead.name or "",
                            "email": email or "",
                        }
                    ],
                }

                try:
                    response = requests.post(
                        campaign.webhook_url,
                        json=payload,
                        timeout=20,
                    )
                    log.http_status = str(response.status_code)
                    log.sent_at = fields.Datetime.now()

                    if response.ok:
                        log.status = "ok"
                    else:
                        log.status = "error"
                        # short message only
                        log.message = (response.text or "")[:500]

                except Exception as e:
                    _logger.exception("Error sending data to n8n")
                    log.status = "error"
                    log.sent_at = fields.Datetime.now()
                    log.message = str(e)[:500]

                # 3) delay before next lead
                if campaign.delay_seconds and campaign.delay_seconds > 0:
                    time.sleep(campaign.delay_seconds)

        return True
