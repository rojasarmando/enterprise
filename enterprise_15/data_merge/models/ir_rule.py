from odoo import api, models
from odoo.exceptions import ValidationError


class IrModel(models.Model):
    _inherit = 'ir.rule'

    @api.constrains('active', 'domain_force', 'model_id')
    def _check_domain(self):
        try:
            return super()._check_domain()
        except ValidationError:
            if self.env.context.get("install_module") == "data_merge":
                return None
            raise
