from odoo import models, fields, api, _, tools
from datetime import datetime, timedelta

class SalesCommitment(models.Model):
    _name = 'sales.commitment'
    _description = 'Sales Commitment'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Name', compute='_compute_name', store=True)
    date = fields.Date(string='Commitment Date', default=fields.Date.context_today, 
                      required=True, readonly=True, tracking=True)
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

    commitment_count = fields.Integer(string="Number of Opportunities", 
                                    compute='_compute_counts', store=True)
    pending_count = fields.Integer(string="Pending Opportunities", 
                                 compute='_compute_counts', store=True)
    success_rate = fields.Float(string="Success Rate (%)", 
                              compute='_compute_counts', store=True)
    color = fields.Integer(string='Color Index', compute='_compute_color')

    team_id = fields.Many2one('crm.team', string='Sales Team', 
                             related='user_id.sale_team_id', store=True)

    available_lead_ids = fields.Many2many(
        'crm.lead', 
        compute='_compute_available_leads',
        string='Available Leads'
    )

    @api.depends('user_id')
    def _compute_available_leads(self):
        for record in self:
            # Get all leads already committed by this user
            committed_leads = self.env['sales.commitment.line'].search([
                ('user_id', '=', record.user_id.id)
            ]).mapped('lead_id')
            
            # Get all available leads for this user
            available_leads = self.env['crm.lead'].search([
                ('user_id', '=', record.user_id.id),
                ('id', 'not in', committed_leads.ids)
            ])
            
            record.available_lead_ids = available_leads

    @api.depends('pending_line_ids.lead_id')
    def _compute_excluded_leads(self):
        for record in self:
            record.excluded_lead_ids = record.pending_line_ids.mapped('lead_id')

    @api.model
    def create(self, vals):
        if not vals.get('date'):
            vals['date'] = fields.Date.context_today(self)
        if vals.get('name', _('New')) == _('New'):
            vals['name'] = self.env['ir.sequence'].next_by_code('sales.commitment') or _('New')

        # Create the record first
        result = super().create(vals)

        # Get all pending leads from previous commitments
        if vals.get('user_id'):
            pending_leads = self.env['sales.commitment.line'].search([
                ('lead_id.user_id', '=', vals['user_id']),
                ('lead_id.stage_id.is_won', '=', False),
                ('commitment_id.date', '<', vals.get('date', fields.Date.today())),
                ('is_pending', '=', True)
            ])

            # Create commitment lines for pending leads
            for line in pending_leads:
                self.env['sales.commitment.line'].create({
                    'commitment_id': result.id,
                    'lead_id': line.lead_id.id,
                    'is_pending': True,
                    'initial_stage_id': line.initial_stage_id.id,
                    'original_commitment_date': line.original_commitment_date or line.commitment_id.date
                })

        return result

    def write(self, vals):
        if 'state' not in vals and any(rec.state != 'draft' for rec in self):
            raise ValidationError(_("You cannot modify a committed record!"))
        return super().write(vals)

    @api.depends('user_id', 'date')
    def _compute_name(self):
        for record in self:
            if record.user_id and record.date:
                record.name = _("%s's Commitment - %s") % (
                    record.user_id.name,
                    record.date.strftime('%Y-%m-%d')
                )
            else:
                record.name = _("New Commitment")

    @api.depends('commitment_line_ids.expected_revenue', 'commitment_line_ids.actual_revenue')
    def _compute_total_revenue(self):
        for record in self:
            record.expected_revenue = sum(record.commitment_line_ids.mapped('expected_revenue'))
            record.actual_revenue = sum(record.commitment_line_ids.mapped('actual_revenue'))

    @api.depends('commitment_line_ids', 'commitment_line_ids.lead_id.stage_id.is_won')
    def _compute_counts(self):
        for record in self:
            total = len(record.commitment_line_ids)
            won = len(record.commitment_line_ids.filtered(
                lambda l: l.lead_id.stage_id.is_won))
            record.commitment_count = total
            record.pending_count = len(record.pending_line_ids)
            record.success_rate = (won / total * 100) if total > 0 else 0

    @api.depends('success_rate')
    def _compute_color(self):
        for record in self:
            if record.success_rate >= 80:
                record.color = 10  # green
            elif record.success_rate >= 50:
                record.color = 3   # yellow
            else:
                record.color = 1   # red

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
        ('unique_lead_user', 
         'UNIQUE(lead_id, user_id)', 
         'This lead is already committed! You cannot commit the same lead multiple times.')
    ]

    commitment_id = fields.Many2one('sales.commitment', string='Commitment', required=True, 
                                  ondelete='cascade')
    user_id = fields.Many2one(related='commitment_id.user_id', store=True)
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

    def write(self, vals):
        if any(line.commitment_id.state != 'draft' for line in self):
            raise ValidationError(_("You cannot modify lines of a committed record!"))
        return super().write(vals)

    def unlink(self):
        if any(line.commitment_id.state != 'draft' for line in self):
            raise ValidationError(_("You cannot delete lines from a committed record!"))
        return super().unlink()

    @api.constrains('lead_id', 'user_id')
    def _check_duplicate_lead(self):
        for record in self:
            duplicate = self.search([
                ('lead_id', '=', record.lead_id.id),
                ('user_id', '=', record.user_id.id),
                ('id', '!=', record.id)
            ], limit=1)
            if duplicate:
                raise ValidationError(_(
                    'Lead %(lead)s is already committed in %(date)s commitment!',
                    lead=record.lead_id.name,
                    date=duplicate.commitment_id.date.strftime('%Y-%m-%d')
                ))

    def unlink(self):
        if any(line.is_pending for line in self):
            raise ValidationError(_("You cannot delete pending commitment lines!"))
        return super().unlink()

    @api.depends('lead_id.stage_id', 'commitment_id.date')
    def _compute_is_pending(self):
        today = fields.Date.today()
        for record in self:
            if not record.lead_id.stage_id.is_won:
                if record.commitment_id.date < today:
                    record.is_pending = True
                elif record.original_commitment_date < record.commitment_id.date:
                    record.is_pending = True
                else:
                    record.is_pending = False
            else:
                record.is_pending = False

    @api.depends('lead_id.stage_id')
    def _compute_actual_revenue(self):
        for record in self:
            if record.lead_id.stage_id.is_won:
                record.actual_revenue = record.expected_revenue
            else:
                record.actual_revenue = 0.0

from odoo import models, fields, api, _

class CRMLead(models.Model):
    _inherit = 'crm.lead'

    commitment_line_ids = fields.One2many('sales.commitment.line', 'lead_id', string='Commitments')
    commitment_count = fields.Integer(compute='_compute_commitment_count', string='# Commitments')
    is_committed = fields.Boolean(compute='_compute_is_committed', store=True, 
                                string='In Current Commitment')
    last_commitment_date = fields.Date(compute='_compute_is_committed', store=True)

    @api.depends('commitment_line_ids.commitment_id.date')
    def _compute_is_committed(self):
        today = fields.Date.today()
        for record in self:
            current_commitment = record.commitment_line_ids.filtered(
                lambda l: l.commitment_id.date == today)
            record.is_committed = bool(current_commitment)
            record.last_commitment_date = max(
                record.commitment_line_ids.mapped('commitment_id.date')) if record.commitment_line_ids else False

    def _compute_commitment_count(self):
        for record in self:
            record.commitment_count = len(record.commitment_line_ids)

    def action_view_commitments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Commitments'),
            'res_model': 'sales.commitment',
            'view_mode': 'tree,form',
            'domain': [('commitment_line_ids.lead_id', '=', self.id)],
        }
