from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests
import json

import logging

_logger = logging.getLogger(__name__)

class N8nCampaign(models.Model):
    _inherit = "n8n.campaign"

    # ---------------------------------------------------
    # VODIA SCRIPT GENERATOR FIELDS
    # ---------------------------------------------------
    vodia_openai_api_key = fields.Char(string="OpenAI API Key")
    vodia_assistant_id = fields.Char(string="Assistant ID")
    
    vodia_model = fields.Selection(
        [("gpt-realtime", "gpt-realtime")],
        string="Model",
        default="gpt-realtime",
        required=True
    )

    openai_voice = fields.Selection(
        [
            ("alloy", "Alloy"),
            ("ash", "Ash"),
            ("ballad", "Ballad"),
            ("coral", "Coral"),
            ("echo", "Echo"),
            ("sage", "Sage"),
            ("shimmer", "Shimmer"),
            ("verse", "Verse"),
        ],
        string="OpenAI Voice",
        default="alloy",
        required=True,
        help="Select the voice for the AI agent."
    )
    
    # Codec is removed from UI, hardcoded in script
    
    vodia_webhook_url = fields.Char(string="Webhook URL")
    vodia_webhook_secret = fields.Char(string="Webhook Secret")
    vodia_webhook_url_endcall = fields.Char(string="Webhook URL EndCall")
    
    # --- NEW: AI Dynamic Webhooks (Scalability) ---
    # --- NEW: Outbound Configuration ---
    caller_id = fields.Char(string="Caller ID (ANI)", help="The phone number to present as Caller ID for outbound calls.")
    
    # n8n_ai_prompt_webhook = fields.Char(string="AI Prompt Webhook") # DEPRECATED: Using Assistant ID Bypass
    n8n_ai_tool_webhook = fields.Char(string="AI Tool Webhook")
    n8n_ai_transcript_webhook = fields.Char(string="AI Transcript Webhook")
    n8n_ai_webhook_secret = fields.Char(string="AI Webhook Secret", help="Secret header value for X-Secret authentication in n8n")
    
    # --- NEW: Appointment Scheduling Config ---
    booking_server_url = fields.Char(string="Booking Server URL", default="https://www.workforcesync.io")
    appointment_type_id = fields.Integer(string="Appointment Type ID", default=11)
    
    initial_message = fields.Text(
        string="Initial Message", 
        default="",
        help="Message the AI speaks first. Leave EMPTY for IVR mode (silence/listening)."
    )
    # ----------------------------------------------

    vodia_instructions = fields.Text(string="Instructions")
    
    vodia_generated_script = fields.Text(string="Generated Script", readonly=True)

    def action_clear_vodia_script(self):
        """Clear the generated script."""
        self.ensure_one()
        self.vodia_generated_script = ""

    def action_generate_vodia_script(self):
        """
        Functionality removed as per request.
        """
        pass

    def action_fetch_assistant_instructions(self):
        """Fetch instructions from OpenAI Assistant and update local field."""
        self.ensure_one()
        if not self.vodia_openai_api_key or not self.vodia_assistant_id:
            raise UserError(_("Please provide both OpenAI API Key and Assistant ID."))

        url = f"https://api.openai.com/v1/assistants/{self.vodia_assistant_id}"
        headers = {
            "Authorization": f"Bearer {self.vodia_openai_api_key}",
            "OpenAI-Beta": "assistants=v2"
        }

        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                data = response.json()
                fetched_instr = data.get("instructions", "")
                _logger.info("Fetched instructions for campaign %s: %s", self.name, fetched_instr)
                self.vodia_instructions = fetched_instr
                # Return True/None to force reload so user sees the new data
                return True
            else:
                raise UserError(_("OpenAI API Error: %s") % response.text)
        except Exception as e:
            raise UserError(_("Failed to fetch from OpenAI: %s") % str(e))

    def action_update_assistant_instructions(self):
        """Update OpenAI Assistant instructions with local field content."""
        self.ensure_one()
        if not self.vodia_openai_api_key or not self.vodia_assistant_id:
            raise UserError(_("Please provide both OpenAI API Key and Assistant ID."))

        url = f"https://api.openai.com/v1/assistants/{self.vodia_assistant_id}"
        headers = {
            "Authorization": f"Bearer {self.vodia_openai_api_key}",
            "Content-Type": "application/json",
            "OpenAI-Beta": "assistants=v2"
        }
        payload = {
            "instructions": self.vodia_instructions or ""
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            if response.status_code == 200:
                _logger.info("Updated instructions for campaign %s", self.name)
                return True
            else:
                raise UserError(_("OpenAI API Error: %s") % response.text)
        except Exception as e:
            raise UserError(_("Failed to update OpenAI: %s") % str(e))

class N8nInboundConfig(models.Model):
    _name = "n8n.inbound.config"
    _description = "Inbound Call Routing Configuration"

    name = fields.Char(string="Incoming DID Number (e.g. 1516...)", required=True, help="The phone number customers call (DID). Match this with your FreePBX Inbound Route.")
    
    # OpenAI Config
    assistant_id = fields.Char(string="Assistant ID", required=True)
    openai_api_key = fields.Char(string="OpenAI API Key", required=True)
    model = fields.Selection([("gpt-realtime", "gpt-realtime")], string="Model", default="gpt-realtime")
    instructions = fields.Text(string="System Prompt (Instructions)")

    # Action to update OpenAI Assistant Instructions
    def action_sync_openai(self):
        """
        Updates the OpenAI Assistant with the instructions defined here.
        """
        self.ensure_one()
        if not self.openai_api_key or not self.assistant_id:
            raise UserError(_("Please provide both API Key and Assistant ID."))
        
        url = f"https://api.openai.com/v1/assistants/{self.assistant_id}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.openai_api_key}",
            "OpenAI-Beta": "assistants=v2"
        }
        payload = {
            "instructions": self.instructions or ""
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            if response.status_code == 200:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _("Success"),
                        'message': _("OpenAI Assistant Updated Successfully!"),
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                raise UserError(_("OpenAI API Error: %s") % response.text)
        except Exception as e:
            raise UserError(_("Failed to communicate with OpenAI: %s") % str(e))
