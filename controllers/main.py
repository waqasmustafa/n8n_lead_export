from odoo import http
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)

class AIInboundController(http.Controller):

    @http.route('/ai/inbound/config', type='json', auth='public', methods=['POST'], csrf=False)
    def get_inbound_config(self, **kwargs):
        """
        API Endpoint for Node.js server to fetch inbound agent config.
        Input: { "did": "5162100561", "caller_id": "+1555..." }
        Output: JSON config or error.
        """
        did = kwargs.get('did')
        caller_id = kwargs.get('caller_id')
        
        if not did:
            return {'error': 'Missing DID'}

        # remove any '+' or non-digit chars from DID for matching if needed, 
        # but let's assume exact match first as per Odoo field.
        # It's safer to strip '+' from input did if stored without it, or match both.
        # Let's clean the input DID just in case.
        clean_did = ''.join(filter(str.isdigit, str(did)))
        
        # Search for active agent
        # We try to match exact first, then maybe contained. 
        # But 'inbound_number' should be unique and exact ideally.
        agent = request.env['ai.inbound.agent'].sudo().search([
            ('inbound_number', 'ilike', clean_did), # ilike for robustness
            ('active', '=', True)
        ], limit=1)

        if not agent:
            # Fallback check: maybe stored with +?
            agent = request.env['ai.inbound.agent'].sudo().search([
                ('inbound_number', '=', did),
                ('active', '=', True)
            ], limit=1)
        
        if not agent:
            _logger.warning(f"No Inbound Agent found for DID {did} (Clean: {clean_did})")
            return {'error': 'No active agent found for this number'}

        response = {
            'agent_id': agent.id,
            'name': agent.name,
            'type': agent.agent_type,
            'voice': agent.openai_voice,
            'initial_message': agent.initial_message,
        }

        # --- Security Check for Odoo Agents ---
        if agent.agent_type == 'odoo':
            # Whitelist Check
            if not caller_id:
                return {'error': 'Caller ID required for Odoo Agent', 'code': 403}
            
            # Allow clean matching for caller_id too
            # clean_caller = ''.join(filter(str.isdigit, str(caller_id)))
            # We search in whitelist.
            # Whitelist numbers might be stored as +1... or 1...
            # A simple robust way is: check if stored number appears in caller_id or vice versa.
            # But let's assume exact match or simple suffix match for now.
            
            allowed = request.env['ai.inbound.whitelist'].sudo().search([
                ('agent_id', '=', agent.id),
                ('phone_number', '=', caller_id) # Strict match for security first
            ], limit=1)

            if not allowed:
                 # Try ignoring '+'
                allowed = request.env['ai.inbound.whitelist'].sudo().search([
                    ('agent_id', '=', agent.id),
                    ('phone_number', '=', caller_id.replace('+',''))
                ], limit=1)

            if not allowed:
                return {'error': 'Unauthorized Caller ID', 'code': 403}

            # If Authorized, return credentials
            response.update({
                'odoo_url': agent.odoo_url,
                'odoo_db': agent.odoo_db,
                'odoo_user': agent.odoo_user,
                'odoo_api_key': agent.odoo_api_key,
                'assistant_id': agent.assistant_id, # Optional override
                'openai_api_key': agent.openai_api_key, # Optional override
            })
            
        else:
            # General Agent
            response.update({
                'system_prompt': agent.system_prompt,
                'openai_api_key': agent.openai_api_key,
                'assistant_id': agent.assistant_id,
            })

        return response
