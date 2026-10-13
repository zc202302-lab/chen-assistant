"""Ordered startup schema ownership. Existing idempotent migration bodies stay intact."""
from importlib import import_module

SCHEMA_STAGES = {
    'base': (('db', 'init_db'),),
    'workspace': (
        ('v101_recipe_template_patch', 'ensure_v101_recipe_templates'),
        ('v13_customer_documents', 'ensure_v13_customer_documents'),
        ('v143_customer_resources', 'ensure_customer_resources_v143'),
        ('v162_number_inbox', 'ensure_number_inbox_schema'),
    ),
    'runtime': (
        ('payment_schedule', 'ensure_payment_date_schema'),
        ('promotions', 'ensure_promotion_schema'),
        ('v10_routes', 'ensure_v10_schema'),
        ('v160_information_center', 'ensure_v160_schema'),
        ('work_lists', 'ensure_work_lists_schema'),
        ('work_list_import', 'ensure_work_list_import_schema'),
    ),
}


def initialize_schema(stage):
    for module, name in SCHEMA_STAGES[stage]:
        getattr(import_module('app.' + module), name)()
