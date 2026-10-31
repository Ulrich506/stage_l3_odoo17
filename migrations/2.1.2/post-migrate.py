from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    dashboard_menu = env.ref(
        "etat_civil.menu_etat_civil_dashboard",
        raise_if_not_found=False,
    )
    if dashboard_menu:
        dashboard_menu.unlink()

    dashboard_action = env.ref(
        "etat_civil.action_etat_civil_dashboard",
        raise_if_not_found=False,
    )
    if dashboard_action:
        dashboard_action.unlink()
