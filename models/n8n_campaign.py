# -*- coding: utf-8 -*-
import logging
from datetime import datetime, timedelta

import pytz
import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Time slots helper (for dropdowns 00:00–23:30 in 30-minute steps)
# ---------------------------------------------------------------------------
def _get_time_slots():
    slots = []
    for hour in range(0, 24):
        for minute in (0, 30):
            value = f"{hour:02d}:{minute:02d}"
            label_hour = hour % 12 or 12
            label_min = f"{minute:02d}"
            am_pm = "AM" if hour < 12 else "PM"
            label = f"{label_hour}:{label_min} {am_pm}"
            slots.append((value, label))
    return slots


TIME_SLOTS = _get_time_slots()


class N8nCampaign(models.Model):
    _name = "n8n.campaign"
    _description = "n8n Campaign"

    # ------------------------------------------------------------------
    # Fields
    # ------------------------------------------------------------------
    name = fields.Char(string="Campaign Name", required=True)

    target_model = fields.Selection(
        selection=[("crm.lead", "Lead / Opportunity")],
        string="Target From",
        required=True,
        default="crm.lead",
    )

    webhook_url = fields.Char(string="n8n Webhook URL", required=True)

    filter_domain = fields.Char(
        string="Filter",
        default="[]",
        help="Domain used to select records to send (Odoo domain syntax).",
    )

    record_count = fields.Integer(
        string="Matching Records",
        compute="_compute_record_count",
        readonly=True,
    )

    # Schedule / control
    is_active = fields.Boolean(string="Active", default=False)

    # NEW NAMES so that DB creates proper selection fields
    start_time_slot = fields.Selection(
        selection=TIME_SLOTS,
        string="Start Time",
        help="Local time (based on user timezone) when this campaign may start sending.",
    )

    end_time_slot = fields.Selection(
        selection=TIME_SLOTS,
        string="End Time",
        help="Local time (based on user timezone) when this campaign must stop sending.",
    )

    delay_seconds = fields.Integer(
        string="Delay (seconds)",
        default=5,
        help="Delay in seconds between sending each record to n8n.",
    )

    next_run_at = fields.Datetime(
        string="Next Run At",
        help="Internal field used by cron to respect delay_seconds.",
    )

    # Logs
    log_ids = fields.One2many(
        "n8n.campaign.log",
        "campaign_id",
        string="Send Logs",
    )

    # ------------------------------------------------------------------
    # Computed fields
    # ------------------------------------------------------------------
    @api.depends("target_model", "filter_domain")
    def _compute_record_count(self):
        for campaign in self:
            count = 0
            if campaign.target_model:
                try:
                    domain = safe_eval(campaign.filter_domain or "[]")
                except Exception as e:
                    _logger.warning(
                        "Invalid domain on n8n.campaign %s: %s",
                        campaign.id,
                        e,
                    )
                    domain = []
                try:
                    count = campaign.env[campaign.target_model].search_count(domain)
                except Exception as e:
                    _logger.warning(
                        "Error computing record_count for n8n.campaign %s: %s",
                        campaign.id,
                        e,
                    )
            campaign.record_count = count

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_domain(self):
        self.ensure_one()
        try:
            return safe_eval(self.filter_domain or "[]")
        except Exception as e:
            _logger.warning("Invalid domain on campaign %s: %s", self.id, e)
            return []

    def _get_target_records(self):
        """All records matching filter for this campaign."""
        self.ensure_one()
        if not self.target_model:
            return self.env["crm.lead"].browse()
        domain = self._get_domain()
        return self.env[self.target_model].search(domain, order="id")

    # ---- Time helpers -------------------------------------------------
    def _get_user_local_time(self):
        """
        Return (local_time_str, now_utc)
        local_time_str -> 'HH:MM' in user's timezone.
        """
        self.ensure_one()
        user = self.env.user
        tz_name = user.tz or "UTC"
        tz = pytz.timezone(tz_name)

        now_utc = datetime.utcnow().replace(tzinfo=pytz.UTC)
        local_dt = now_utc.astimezone(tz)
        local_str = f"{local_dt.hour:02d}:{local_dt.minute:02d}"
        return local_str, now_utc

    @staticmethod
    def _time_to_minutes(value):
        if not value:
            return None
        try:
            h, m = map(int, value.split(":"))
            return h * 60 + m
        except Exception:
            return None

    def _is_within_schedule(self, local_time_str):
        """Check if given local time (HH:MM) is between start_time_slot and end_time_slot."""
        self.ensure_one()

        # If no schedule defined -> always allowed
        if not self.start_time_slot and not self.end_time_slot:
            return True

        now_min = self._time_to_minutes(local_time_str)
        if now_min is None:
            return True

        start_min = (
            self._time_to_minutes(self.start_time_slot)
            if self.start_time_slot
            else 0
        )
        end_min = (
            self._time_to_minutes(self.end_time_slot)
            if self.end_time_slot
            else (24 * 60 - 1)
        )

        return start_min <= now_min <= end_min

    # ---- Sending helpers ----------------------------------------------
    def _get_next_lead_to_send(self):
        """Return next crm.lead that has not been sent yet (no log)."""
        self.ensure_one()

        all_records = self._get_target_records()
        if not all_records:
            return None

        sent_ids = set(self.log_ids.mapped("lead_id").ids)

        for rec in all_records:
            if rec.id not in sent_ids:
                return rec
        return None

    def _send_lead_to_n8n(self, record):
        """Send single lead to n8n and create/update log."""
        self.ensure_one()

        if not self.webhook_url:
            raise UserError(_("n8n Webhook URL is required."))

        if self.target_model != "crm.lead":
            # For now we only support crm.lead
            raise UserError(_("Only CRM Lead model is supported at this time."))

        payload = {
            "campaign_id": self.id,
            "campaign_name": self.name,
            "target_model": self.target_model,
            "count": 1,
            "records": [
                {
                    "id": record.id,
                    "name": record.name,
                    "email": record.email_from or "",
                }
            ],
        }

        # Create pending log
        log = self.env["n8n.campaign.log"].create(
            {
                "campaign_id": self.id,
                "lead_id": record.id,
                "lead_odoo_id": record.id,
                "name": record.name,
                "email": record.email_from or "",
                "status": "pending",
            }
        )

        http_status = None
        msg = ""
        status = "ok"

        try:
            response = requests.post(self.webhook_url, json=payload, timeout=20)
            http_status = response.status_code
            msg = response.text[:1000] if response.text else ""
            response.raise_for_status()
            status = "ok"
        except Exception as e:
            status = "error"
            msg = str(e)
            _logger.error(
                "Error sending lead %s for campaign %s to n8n: %s",
                record.id,
                self.id,
                e,
            )

        log.write(
            {
                "status": status,
                "http_status": str(http_status) if http_status is not None else False,
                "message": msg,
                "sent_at": fields.Datetime.now(),
            }
        )

    # ------------------------------------------------------------------
    # Manual button (optional)
    # ------------------------------------------------------------------
    def action_send_to_n8n(self):
        """
        Manual send for testing: sends exactly ONE next record per campaign.
        """
        for campaign in self:
            record = campaign._get_next_lead_to_send()
            if not record:
                raise UserError(
                    _("No more records to send for campaign %s.") % campaign.name
                )
            campaign._send_lead_to_n8n(record)

    # ------------------------------------------------------------------
    # Cron entry point
    # ------------------------------------------------------------------
    @api.model
    def cron_run_n8n_campaigns(self):
        """
        Called by ir.cron (every minute, for example).
        - Checks active flag
        - Checks start/end time window (user timezone)
        - Respects delay_seconds using next_run_at
        - Sends exactly ONE record per eligible campaign per run
        """
        campaigns = self.search([("is_active", "=", True)])
        for campaign in campaigns:
            try:
                local_time_str, now_utc = campaign._get_user_local_time()

                # Check time window
                if not campaign._is_within_schedule(local_time_str):
                    continue

                # Respect delay
                if campaign.next_run_at and now_utc < campaign.next_run_at:
                    continue

                # Next unsent record
                record = campaign._get_next_lead_to_send()
                if not record:
                    # Nothing left to send; you could auto-deactivate here if desired
                    continue

                campaign._send_lead_to_n8n(record)

                delay = max(campaign.delay_seconds or 0, 0)
                campaign.next_run_at = now_utc + timedelta(seconds=delay)

            except Exception as e:
                _logger.error(
                    "Error in cron_run_n8n_campaigns for campaign %s: %s",
                    campaign.id,
                    e,
                )
