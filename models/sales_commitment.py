from odoo import models, fields, api, _
from datetime import datetime, timedelta

class SalesCommitment(models.Model):
    _name = 'sales.commitment'
    _description = 'Sales Commitment'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Name', required=True)
    date = fields.Date(string='Commitment Date', default=fields.Date.context_today, 
                      required=True, tracking=True)
    user_id = fields.Many2one('res.users', string='Salesperson', 
                             default=lambda self: self.env.user, required=True)
    lead_id = fields.Many2one('crm.lead', string='Lead/Opportunity', 
                             domain="[('user_id', '=', user_id)]", required=True)
    initial_stage_id = fields.Many2one('crm.stage', string='Initial Stage', 
                                      related='lead_id.stage_id', store=True)
    current_stage_id = fields.Many2one('crm.stage', string='Current Stage', 
                                      related='lead_id.stage_id', store=True)
    expected_revenue = fields.Float(related='lead_id.expected_revenue', store=True)
    actual_revenue = fields.Float(compute='_compute_actual_revenue', store=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('committed', 'Committed'),
        ('won', 'Won'),
        ('failed', 'Failed')
    ], default='draft', tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('sales.commitment') or _('New')
        return super().create(vals_list)

    @api.depends('lead_id.stage_id')
    def _compute_actual_revenue(self):
        for record in self:
            if record.lead_id.stage_id.is_won:
                record.actual_revenue = record.expected_revenue
            else:
                record.actual_revenue = 0.0

    def action_commit(self):
        self.write({'state': 'committed'})

    @api.model
    def _cron_move_to_next_day(self):
        yesterday = fields.Date.today() - timedelta(days=1)
        commitments = self.search([
            ('date', '=', yesterday),
            ('state', '=', 'committed'),
            ('lead_id.stage_id.is_won', '=', False)
        ])
        commitments.write({
            'date': fields.Date.today(),
            'state': 'draft'
        })
