from odoo import models, fields, api, _, tools
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
    company_id = fields.Many2one('res.company', string='Company', required=True, 
                                default=lambda self: self.env.company)
    company_currency = fields.Many2one(
        'res.currency',
        string='Company Currency',
        related='company_id.currency_id',
        readonly=True,
        store=True,
    )
    commitment_line_ids = fields.One2many('sales.commitment.line', 'commitment_id', 
                                        string='Opportunities')
    expected_revenue = fields.Monetary(
        string="Total Expected Revenue",
        compute='_compute_total_revenue',
        currency_field='company_currency',
        store=True
    )
    actual_revenue = fields.Monetary(
        string="Total Actual Revenue",
        compute='_compute_total_revenue',
        currency_field='company_currency',
        store=True
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('committed', 'Committed'),
        ('won', 'Won'),
        ('failed', 'Failed')
    ], default='draft', tracking=True)

    pending_line_ids = fields.One2many('sales.commitment.line', 'commitment_id',
                                     domain=[('is_pending', '=', True)],
                                     string='Pending Opportunities')
    new_line_ids = fields.One2many('sales.commitment.line', 'commitment_id',
                                  domain=[('is_pending', '=', False)],
                                  string='New Opportunities')
    excluded_lead_ids = fields.Many2many('crm.lead', compute='_compute_excluded_leads',
                                       string='Excluded Leads')

    @api.depends('pending_line_ids.lead_id')
    def _compute_excluded_leads(self):
        for record in self:
            record.excluded_lead_ids = record.pending_line_ids.mapped('lead_id')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('sales.commitment') or _('New')
        return super().create(vals_list)

    @api.model
    def create(self, vals):
        # Get pending leads from previous commitments
        if vals.get('user_id'):
            pending_leads = self.env['sales.commitment.line'].search([
                ('lead_id.user_id', '=', vals['user_id']),
                ('lead_id.stage_id.is_won', '=', False),
                ('is_pending', '=', True)
            ])
            
            result = super().create(vals)
            
            # Copy pending leads to new commitment
            for lead in pending_leads:
                self.env['sales.commitment.line'].create({
                    'commitment_id': result.id,
                    'lead_id': lead.lead_id.id,
                    'is_pending': True,
                    'initial_stage_id': lead.initial_stage_id.id,
                    'original_commitment_date': lead.original_commitment_date
                })
            
            return result
        return super().create(vals)

    @api.depends('commitment_line_ids.expected_revenue', 'commitment_line_ids.actual_revenue')
    def _compute_total_revenue(self):
        for record in self:
            record.expected_revenue = sum(record.commitment_line_ids.mapped('expected_revenue'))
            record.actual_revenue = sum(record.commitment_line_ids.mapped('actual_revenue'))

    def action_commit(self):
        self.write({'state': 'committed'})

    @api.model
    def _cron_move_to_next_day(self):
        yesterday = fields.Date.today() - timedelta(days=1)
        commitments = self.search([
            ('date', '=', yesterday),
            ('state', '=', 'committed'),
            ('commitment_line_ids.lead_id.stage_id.is_won', '=', False)
        ])
        commitments.write({
            'date': fields.Date.today(),
            'state': 'draft'
        })

class SalesCommitmentLine(models.Model):
    _name = 'sales.commitment.line'
    _description = 'Sales Commitment Line'
    _sql_constraints = [
        ('unique_lead_per_day', 
         'UNIQUE(lead_id, commitment_id)', 
         'You cannot commit the same lead twice in one commitment!')
    ]

    commitment_id = fields.Many2one('sales.commitment', string='Commitment', required=True, 
                                  ondelete='cascade')
    lead_id = fields.Many2one('crm.lead', string='Lead/Opportunity', required=True,
                             domain="[('user_id', '=', parent.user_id)]")
    date_deadline = fields.Date(related='lead_id.date_deadline', string='Deadline', store=True)
    date_closed = fields.Datetime(related='lead_id.date_closed', string='Closing Date', store=True)
    initial_stage_id = fields.Many2one('crm.stage', string='Initial Stage', store=True)
    stage_id = fields.Many2one(related='lead_id.stage_id', string='Current Stage', store=True)
    expected_revenue = fields.Monetary(related='lead_id.expected_revenue', string='Expected Revenue',
                                     currency_field='company_currency', store=True)
    actual_revenue = fields.Monetary(compute='_compute_actual_revenue', string='Actual Revenue',
                                   currency_field='company_currency', store=True)
    company_currency = fields.Many2one(related='commitment_id.company_currency')
    is_pending = fields.Boolean('Is Pending', default=False)
    original_commitment_date = fields.Date('Original Commitment Date', 
                                         default=fields.Date.context_today)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('lead_id'):
                lead = self.env['crm.lead'].browse(vals['lead_id'])
                if not vals.get('is_pending'):  # Only for new commitments
                    vals['initial_stage_id'] = lead.stage_id.id
                    vals['original_commitment_date'] = fields.Date.today()
        return super().create(vals_list)

    def unlink(self):
        if any(line.is_pending for line in self):
            raise ValidationError(_("You cannot delete pending commitment lines!"))
        return super().unlink()

    @api.depends('lead_id.stage_id', 'commitment_id.date')
    def _compute_is_pending(self):
        today = fields.Date.today()
        for record in self:
            if (record.commitment_id.date < today and 
                not record.lead_id.stage_id.is_won):
                record.is_pending = True

    @api.depends('lead_id.stage_id')
    def _compute_actual_revenue(self):
        for record in self:
            if record.lead_id.stage_id.is_won:
                record.actual_revenue = record.expected_revenue
            else:
                record.actual_revenue = 0.0
