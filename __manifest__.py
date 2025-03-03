{
    'name': 'Sales Commitment',
    'version': '17.0.1.0.0',
    'category': 'Sales',
    'summary': 'Track sales commitments',
    'depends': ['crm', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/sales_commitment_views.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
