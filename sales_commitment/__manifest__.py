{
    'name': 'Sales Commitment Tracker',
    'version': '17.0.1.0.0',
    'category': 'Sales',
    'summary': 'Track daily sales commitments',
    'description': """
        Allow salespeople to track their daily commitments for closing deals.
    """,
    'depends': ['sale_crm', 'crm'],
    'data': [
        'security/ir.model.access.csv',
        'security/sales_commitment_security.xml',
        'views/sales_commitment_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
