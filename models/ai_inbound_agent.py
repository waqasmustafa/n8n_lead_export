from odoo import models, fields, api

class AiInboundAgent(models.Model):
    _name = 'ai.inbound.agent'
    _description = 'AI Inbound Agent Configuration'

    name = fields.Char(string='Agent Name', required=True)
    inbound_number = fields.Char(string='Inbound DID Number', required=True, help="The phone number this agent answers (e.g. 5162100561).")
    active = fields.Boolean(default=True)
    
    agent_type = fields.Selection([
        ('general', 'General Inquiry'),
        ('odoo', 'Odoo Data Access')
    ], string='Agent Type', default='general', required=True)

    # General Agent Settings
    system_prompt = fields.Text(string='System Prompt', help="Instructions for the AI behavior.")
    initial_message = fields.Char(string='Initial Greeting', default="Hello, how can I help you?", required=True)
    
    # AI Settings
    openai_voice = fields.Selection([
        ('alloy', 'Alloy'),
        ('echo', 'Echo'),
        ('fable', 'Fable'),
        ('onyx', 'Onyx'),
        ('nova', 'Nova'),
        ('shimmer', 'Shimmer')
    ], string='OpenAI Voice', default='alloy')
    
    openai_api_key = fields.Char(string='OpenAI API Key (Override)', help="Leave empty to use server default.")
    assistant_id = fields.Char(string='Assistant ID (Override)', help="Leave empty to use server default or system prompt.")

    # Odoo Agent Settings
    odoo_url = fields.Char(string='Odoo URL')
    odoo_db = fields.Char(string='Odoo Database')
    odoo_user = fields.Char(string='Odoo User (Email)')
    odoo_api_key = fields.Char(string='Odoo API Key')

    allowed_list_ids = fields.One2many('ai.inbound.whitelist', 'agent_id', string='Allowed Callers')

    _sql_constraints = [
        ('inbound_number_unique', 'unique(inbound_number)', 'This Inbound Number is already assigned to another agent!')
    ]
