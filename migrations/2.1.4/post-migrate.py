from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    languages = env["res.lang"].with_context(active_test=False)
    language = languages.search([("code", "=", "mg_MG")], limit=1)
    if not language:
        languages._create_lang("mg_MG", "Malagasy")
    elif not language.active:
        language.active = True
