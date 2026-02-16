from odoo import models, fields

class AiInboundWhitelist(models.Model):
    _name = 'ai.inbound.whitelist'
    _description = 'AI Inbound Caller Whitelist'

    agent_id = fields.Many2one('ai.inbound.agent', string='Agent', required=True, ondelete='cascade')
    phone_number = fields.Char(string='Phone Number', required=True, help="E.164 format preferred (e.g. +1516...)")
    note = fields.Char(string='Note / User Name')
