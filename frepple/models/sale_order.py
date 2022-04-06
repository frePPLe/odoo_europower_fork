import os
import logging
from odoo import models, api, fields

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    frepple_write_date = fields.Datetime(string='Write Date (frePPLe)',compute='_compute_frepple_write_date', store=True)

    @api.depends('order_line.frepple_write_date')
    def _compute_frepple_write_date(self):
        for order in self:
            order.frepple_write_date = max(order.order_line.filtered(lambda l: l.frepple_write_date).mapped('frepple_write_date') or [False])


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    frepple_write_date = fields.Datetime(string='Write Date (frePPLe)')