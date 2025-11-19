# -*- coding: utf-8 -*-
import ast
import logging
import time as pytime
from datetime import datetime

from odoo import models, fields, api, _
from odoo.exceptions import UserError

import pytz

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

_logger = logging.getLogger(__name__)


class N8nCampaign(models.Model):
    _name = "n8n.campaign"
    _description = "n8n Campaign Export"

    # -------------------------------------------------------------------------
    # FIELDS
    # -------------------------------------------------------------------------
    name = fields.Char(string="Campaign Name", required=True)

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
        help="Paste the URL of the n8n webhook.",
    )

    # Domain for selecting records
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
        help="Wait this many seconds between sending each record.",
    )

    # 🔥 NEW: toggle + time window
    is_active = fields.Boolean(
        string="Active",
        default=False,
        help="If active, cron will automatically send leads to n8n "
             "within the start/end time window.",
    )

    # Stored as float hours; use widget='float_time' in the view
    start_time = fields.Float(
        string="Start Time",
        help="Local start time (user timezone) when this campaign can send.",
    )
    end_time = fields.Float(
        string="End Time",
        help="Local end time (user timezone) when this campaign stops sending.",
    )

    log_ids = fields.One2many(
        "n8n.campaign.log",
        "campaign_id",
        string="Send Logs",
        readonly=True,
    )

    # -------------------------------------------------------------------------
    # HELPERS
    # -------------------------------------------------------------------------
    @api.depends("filter_domain", "target_model")
    def _compute_record_count(self):
        for campaign in self:
            model = campaign._get_target_model()
            if not model:
                campaign.record_count = 0
                continue
            domain = campaign._get_domain()
            try:
                campaign.record_count = model.search_count(domain)
            except Exception:
                # In case domain is broken, don't crash the UI
                campaign.record_count = 0

    def _get_target_model(self):
        """Return env model object based on target_model selection."""
        self.ensure_one()
        if self.target_model == "crm.lead":
            return self.env["crm.lead"]
        return None

    def _get_domain(self):
        """Parse filter_domain string into a proper domain list."""
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

    # --- Time / timezone helpers ---------------------------------------------
    def _get_user_tz_now(self):
        """Return 'now' in the campaign owner's timezone."""
        self.ensure_one()
        user = self.create_uid or self.env.user
        tz_name = user.tz or "UTC"
        try:
            tz = pytz.timezone(tz_name)
        except Exception:  # fallback
            tz = pytz.UTC
        return datetime.now(tz)

    def _is_within_time_window(self):
        """Check if current local time is within start/end window.

        Uses campaign creator's timezone (create_uid.tz).
        """
        self.ensure_one()
        # No window configured -> always allowed
        if not self.start_time and not self.end_time:
            return True

        now_local = self._get_user_tz_now()
        now_float = now_local.hour + now_local.minute / 60.0

        # If only start is set
        if self.start_time and not self.end_time:
            return now_float >= self.start_time

        # If only end is set
        if self.end_time and not self.start_time:
            return now_float <= self.end_time

        # Both set
        if self.start_time <= self.end_time:
            return self.start_time <= now_float <= self.end_time

        # Edge case: start > end (crosses midnight) -> e.g., 22:00–02:00
        return now_float >= self.start_time or now_float <= self.end_time

    # --- Core sending logic ---------------------------------------------------
    def _prepare_lead_payload(self, lead):
        email = getattr(lead, "email_from", False) or getattr(lead, "email", False)
        return {
            "id": lead.id,
            "name": lead.name or "",
            "email": email or "",
        }

    def _send_leads_to_n8n(self, leads, skip_already_ok=False):
        """Send given leads to n8n one-by-one and log each attempt."""
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

            for lead in leads:
                # Optionally skip records already sent successfully
                if skip_already_ok:
                    ok_log = campaign.log_ids.filtered(
                        lambda l: l.lead_odoo_id == lead.id and l.status == "ok"
                    )
                    if ok_log:
                        continue

                payload = {
                    "campaign_id": campaign.id,
                    "campaign_name": campaign.name,
                    "target_model": campaign.target_model,
                    "count": 1,
                    "records": [campaign._prepare_lead_payload(lead)],
                }

                # Create log as 'pending'
                email = payload["records"][0]["email"]
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

                try:
                    _logger.info(
                        "Sending lead %s to n8n webhook %s",
                        lead.id,
                        campaign.webhook_url,
                    )
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

                # Delay between records (if configured)
                if campaign.delay_seconds and campaign.delay_seconds > 0:
                    pytime.sleep(campaign.delay_seconds)

    # -------------------------------------------------------------------------
    # MANUAL ACTION (if you still want to trigger manually from debug, etc.)
    # -------------------------------------------------------------------------
    def action_send_to_n8n(self):
        """Manual send: ignore active/time window, just send all matching."""
        for campaign in self:
            model = campaign._get_target_model()
            if not model:
                raise UserError(
                    _("Unsupported target model: %s") % (campaign.target_model,)
                )
            domain = campaign._get_domain()
            leads = model.search(domain)
            campaign._send_leads_to_n8n(leads, skip_already_ok=False)
        return True

    # -------------------------------------------------------------------------
    # CRON ENTRY POINT
    # -------------------------------------------------------------------------
    @api.model
    def cron_run_n8n_campaigns(self):
        """Called by ir.cron: send leads for active campaigns
        inside their local time window.
        """
        campaigns = self.search([("is_active", "=", True)])
        for campaign in campaigns:
            # Time window check
            if not campaign._is_within_time_window():
                continue

            model = campaign._get_target_model()
            if not model:
                continue

            try:
                domain = campaign._get_domain()
            except UserError:
                # Invalid domain -> skip this campaign for now
                _logger.warning(
                    "Campaign %s has invalid domain, skipping...", campaign.id
                )
                continue

            leads = model.search(domain)
            if not leads:
                continue

            _logger.info(
                "Cron: sending %s leads for campaign %s to n8n",
                len(leads),
                campaign.name,
            )
            # In cron we usually don't want duplicates → skip already OK
            campaign._send_leads_to_n8n(leads, skip_already_ok=True)
