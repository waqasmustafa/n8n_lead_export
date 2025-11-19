import ast
import logging
import time
from datetime import time as dt_time  # for time-of-day comparison

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

    # ---------------------------------------------------
    # FIELDS
    # ---------------------------------------------------
    name = fields.Char(
        string="Campaign Name",
        required=True,
    )

    target_model = fields.Selection(
        [
            ("crm.lead", "Lead / Opportunity"),
        ],
        string="Target From",
        default="crm.lead",
        required=True,
    )

    webhook_url = fields.Char(
        string="n8n Webhook URL",
        required=True,
        help="Paste the URL of the n8n webhook.",
    )

    filter_domain = fields.Char(
        string="Filter",
        default="[]",
        help="Build record filter using domain widget.",
    )

    record_count = fields.Integer(
        string="Matching Records",
        compute="_compute_record_count",
        readonly=True,
    )

    delay_seconds = fields.Integer(
        string="Delay (seconds)",
        default=0,
        help="Wait this many seconds before sending the next record to n8n.",
    )

    # 🔁 toggle field
    is_active = fields.Boolean(
        string="Active",
        default=False,
        help="If active, this campaign will be processed automatically by the scheduler.",
    )

    # 🕒 start / end time (time-of-day, local to owner)
    start_time = fields.Float(
        string="Start Time",
        help="Local time-of-day (campaign owner's timezone) when sending is allowed to start.",
        default=0.0,  # 00:00
    )

    end_time = fields.Float(
        string="End Time",
        help="Local time-of-day (campaign owner's timezone) when sending must stop.",
        default=23.99,  # ~23:59
    )

    log_ids = fields.One2many(
        "n8n.campaign.log",
        "campaign_id",
        string="Send Logs",
        readonly=True,
    )

    # ---------------------------------------------------
    # COMPUTE & HELPERS
    # ---------------------------------------------------
    @api.depends("filter_domain", "target_model")
    def _compute_record_count(self):
        for campaign in self:
            model = campaign._get_target_model()
            domain = campaign._get_domain()
            if not model:
                campaign.record_count = 0
                continue
            campaign.record_count = model.search_count(domain)

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

    # ---- Time helpers -----------------------------------------------------

    @staticmethod
    def _float_to_time(value):
        """Convert float hour (e.g. 13.5) into datetime.time(13, 30)."""
        if value is False or value is None:
            return None
        hours = int(value)
        minutes = int(round((value - hours) * 60))
        # safety clamp
        hours = max(0, min(23, hours))
        minutes = max(0, min(59, minutes))
        return dt_time(hours, minutes, 0)

    def _is_within_time_window(self):
        """Return True if current time (owner's timezone) is within Start–End window."""
        self.ensure_one()

        # Use campaign owner timezone if available, else current user
        owner = self.create_uid or self.env.user

        now_utc = fields.Datetime.now()
        # Convert to owner's local time using Odoo helper
        local_now = fields.Datetime.context_timestamp(owner, now_utc)
        local_t = local_now.time()

        start_t = self._float_to_time(self.start_time) or dt_time(0, 0, 0)
        end_t = self._float_to_time(self.end_time) or dt_time(23, 59, 59)

        # Simple inclusive check (no overnight window for now)
        return start_t <= local_t <= end_t

    # ---------------------------------------------------
    # CORE SENDING LOGIC (reused by cron + manual)
    # ---------------------------------------------------
    def _send_pending_leads_via_n8n(self):
        """
        Send ALL matching leads to n8n (always resend),
        respecting delay_seconds and logging each attempt.
        """
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
                "Sending %s records to n8n webhook %s",
                len(leads),
                campaign.webhook_url,
            )

            Log = self.env["n8n.campaign.log"]

            for lead in leads:
                email = getattr(lead, "email_from", False) or getattr(
                    lead, "email", False
                )

                # 1) create log as pending
                log = Log.create(
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

    # ---------------------------------------------------
    # MANUAL ACTION (debug / manual send)
    # ---------------------------------------------------
    def action_send_to_n8n(self):
        """Manual trigger – send all matching leads now."""
        return self._send_pending_leads_via_n8n()

    # ---------------------------------------------------
    # CRON ENTRY POINT
    # ---------------------------------------------------
    @api.model
    def _cron_run_n8n_campaigns(self):
        """Cron: auto-run active campaigns inside their time window."""
        campaigns = self.search([("is_active", "=", True)])
        if not campaigns:
            return

        for campaign in campaigns:
            # Respect time window (owner's timezone)
            if not campaign._is_within_time_window():
                continue
            campaign._send_pending_leads_via_n8n()
