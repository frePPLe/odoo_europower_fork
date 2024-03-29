# -*- coding: utf-8 -*-
#
# Copyright (C) 2014 by frePPLe bv
#
# This library is free software; you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero
# General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public
# License along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
import odoo
import logging
import pytz

from xml.etree.cElementTree import iterparse
from datetime import datetime
from pytz import timezone

logger = logging.getLogger(__name__)


class importer(object):
    def __init__(self, req, database=None, company=None, mode=1):
        self.env = req.env
        self.database = database
        self.company = company
        self.datafile = req.httprequest.files.get("frePPLe plan")

        # The mode argument defines different types of runs:
        #  - Mode 1:
        #    Export of the complete plan. This first erase all previous frePPLe
        #    proposals in draft state.
        #  - Mode 2:
        #    Incremental export of some proposed transactions from frePPLe.
        #    In this mode mode we are not erasing any previous proposals.
        self.mode = int(mode)

    def run(self):
        msg = []

        proc_order = self.env["purchase.order"]
        proc_orderline = self.env["purchase.order.line"]
        mfg_order = self.env["mrp.production"]
        # if self.mode == 1:
        #     # Cancel previous draft purchase quotations
        #     m = self.env["purchase.order"]
        #     recs = m.search([("state", "=", "draft"), ("origin", "=", "frePPLe")])
        #     recs.write({"state": "cancel"})
        #     recs.unlink()
        #     msg.append("Removed %s old draft purchase orders" % len(recs))

        #     # Cancel previous draft manufacturing orders
        #     recs = mfg_order.search(
        #         [
        #             "|",
        #             ("state", "=", "draft"),
        #             ("state", "=", "cancel"),
        #             ("origin", "=", "frePPLe"),
        #         ]
        #     )
        #     recs.write({"state": "cancel"})
        #     recs.unlink()
        #     msg.append("Removed %s old draft manufacturing orders" % len(recs))

        # Parsing the XML data file
        countproc = 0
        countmfg = 0

        # dictionary that stores as key the supplier id and the associated po id
        # this dict is used to aggregate the exported POs for a same supplier
        # into one PO in odoo with multiple lines
        supplier_reference = {}

        # dictionary that stores as key a tuple (product id, supplier id)
        # and as value a poline odoo object
        # this dict is used to aggregate POs for the same product supplier
        # into one PO with sum of quantities and min date
        product_supplier_dict = {}

        logger.warning("start parsing")
        for event, elem in iterparse(self.datafile, events=("start", "end")):
            logger.warning("%s %s" % (event, elem.tag))
            if event == "end" and elem.tag == "operationplan":
                uom_id, item_id = elem.get("item_id").split(",")
                try:
                    ordertype = elem.get("ordertype")
                    if ordertype == "PO":
                        # Create purchase order
                        supplier_id = int(elem.get("supplier").split(" ", 1)[0])
                        quantity = elem.get("quantity")
                        date_planned = elem.get("end")
                        if date_planned:
                            date_planned = datetime.strptime(
                                date_planned, "%Y-%m-%d %H:%M:%S"
                            )
                        date_ordered = elem.get("start")
                        if date_ordered:
                            date_ordered = datetime.strptime(
                                date_ordered, "%Y-%m-%d %H:%M:%S"
                            )
                        if supplier_id not in supplier_reference:
                            po = proc_order.create(
                                {
                                    "company_id": self.company.id,
                                    "partner_id": int(
                                        elem.get("supplier").split(" ", 1)[0]
                                    ),
                                    # TODO Odoo has no place to store the location and criticality
                                    # int(elem.get('location_id')),
                                    # elem.get('criticality'),
                                    "origin": "frePPLe",
                                }
                            )
                            supplier_reference[supplier_id] = {
                                "id": po.id,
                                "min_planned": date_planned,
                                "min_ordered": date_ordered,
                                "po": po,
                            }
                            po.onchange_partner_id()
                        else:
                            if (
                                date_planned
                                < supplier_reference[supplier_id]["min_planned"]
                            ):
                                supplier_reference[supplier_id][
                                    "min_planned"
                                ] = date_planned
                            if (
                                date_ordered
                                < supplier_reference[supplier_id]["min_ordered"]
                            ):
                                supplier_reference[supplier_id][
                                    "min_ordered"
                                ] = date_ordered

                        quantity = elem.get("quantity")
                        date_planned = (
                            timezone(self.env.user.tz)
                            .localize(datetime.strptime(elem.get("end"), "%Y-%m-%d %H:%M:%S"),
                                      is_dst=None)
                            .astimezone(pytz.utc)
                        ).strftime("%Y-%m-%d %H:%M:%S")
                        if (item_id, supplier_id) not in product_supplier_dict:
                            price_unit = 0
                            product = self.env["product.product"].browse(int(item_id))
                            product_supplierinfo = self.env[
                                "product.supplierinfo"
                            ].search(
                                [
                                    ("name", "=", supplier_id),
                                    (
                                        "product_tmpl_id",
                                        "=",
                                        product.product_tmpl_id.id,
                                    ),
                                    ("min_qty", "<=", quantity),
                                ],
                                limit=1,
                                order="min_qty desc",
                            )
                            if product_supplierinfo:
                                price_unit = product_supplierinfo.price
                            po_line = proc_orderline.create(
                                {
                                    "order_id": supplier_reference[supplier_id]["id"],
                                    "product_id": int(item_id),
                                    "product_qty": quantity,
                                    "product_uom": int(uom_id),
                                    "date_planned": date_planned,
                                    "price_unit": price_unit,
                                    "name": elem.get("item"),
                                }
                            )
                            po_line._product_id_change()
                            product_supplier_dict[(item_id, supplier_id)] = po_line

                        else:
                            po_line = product_supplier_dict[(item_id, supplier_id)]
                            po_line.date_planned = min(
                                po_line.date_planned,
                                date_planned,
                            )
                            po_line.product_qty = po_line.product_qty + float(quantity)
                        countproc += 1
                    # TODO Create a distribution order
                    # elif ????:
                    else:
                        # Create manufacturing order
                        picking_type_id = mfg_order._get_default_picking_type()
                        bom_id = self.env['mrp.bom'].browse(int(elem.get("operation").rsplit(" ", 1)[1]))

                        date_planned_start = (
                            timezone(self.env.user.tz)
                            .localize(datetime.strptime(elem.get("start"), "%Y-%m-%d %H:%M:%S"),
                                      is_dst=None)
                            .astimezone(pytz.utc)
                        ).strftime("%Y-%m-%d %H:%M:%S")
                        date_planned_finished = (
                            timezone(self.env.user.tz)
                            .localize(datetime.strptime(elem.get("end"), "%Y-%m-%d %H:%M:%S"),
                                      is_dst=None)
                            .astimezone(pytz.utc)
                        ).strftime("%Y-%m-%d %H:%M:%S")
                        logger.error(
                            "creating MO %s "
                            % {
                                "product_qty": elem.get("quantity"),
                                "date_planned_start": date_planned_start,
                                "date_planned_finished": date_planned_finished,
                                "product_id": int(item_id),
                                "company_id": self.company.id,
                                "product_uom_id": int(uom_id),
                                "location_src_id": int(elem.get("location_id")),
                                "location_dest_id": int(elem.get("location_id")),
                                "bom_id": bom_id.id,
                                "picking_type_id": bom_id.picking_type_id.id
                                or picking_type_id,
                                "qty_producing": 0.00,
                                # TODO no place to store the criticality
                                # elem.get('criticality'),
                                "origin": "frePPLe",
                                "xx_operator_qty": elem.get("xx_operator_qty"),
                            }
                        )
                        mo = mfg_order.create(
                            {
                                "product_qty": elem.get("quantity"),
                                "date_planned_start": date_planned_start,
                                "date_planned_finished": date_planned_finished,
                                "product_id": int(item_id),
                                "company_id": self.company.id,
                                "product_uom_id": int(uom_id),
                                "location_src_id": int(elem.get("location_id")),
                                "location_dest_id": int(elem.get("location_id")),
                                "bom_id": bom_id.id,
                                "picking_type_id": bom_id.picking_type_id.id or picking_type_id,
                                "qty_producing": 0.00,
                                # TODO no place to store the criticality
                                # elem.get('criticality'),
                                "origin": "frePPLe",
                                "xx_operator_qty": elem.get("xx_operator_qty"),
                            })
                        try:
                            mo._onchange_workorder_ids()
                        except Exception as e:
                            logger.error(
                                "error creating _onchange_workorder_ids %s " % e
                            )
                        # try:
                        #     mo._onchange_bom_id()
                        # except Exception:
                        #     pass
                        try:
                            mo.onchange_picking_type()
                        except Exception as e:
                            logger.error("error onchange_picking_type %s " % e)
                        try:
                            mo._onchange_move_raw()
                        except Exception as e:
                            logger.error("error _onchange_move_raw %s " % e)
                        try:
                            mo._create_update_move_finished()
                        except Exception as e:
                            logger.error("error _create_update_move_finished %s " % e)
                        try:
                            mo.action_confirm()
                        except Exception as e:
                            logger.error("error action_confirm %s " % e)
                        try:
                            mo.button_plan()
                        except Exception as e:
                            logger.error("error button_plan %s " % e)
                        try:
                            mo.action_assign()
                        except Exception as e:
                            logger.error("error action_assign %s " % e)
                        try:
                            mo.picking_ids.action_confirm()
                            mo.picking_ids.action_assign()
                        except Exception as e:
                            logger.error(
                                "error picking_ids.action_confirm  picking_ids.action_assign %s "
                                % e
                            )

                        countmfg += 1
                except Exception as e:
                    logger.error("Exception %s" % e)
                    msg.append(str(e))
                # Remove the element now to keep the DOM tree small
                root.clear()
            elif event == "end" and elem.tag == "demand":
                try:
                    deliverydate = (
                        timezone(self.env.user.tz)
                        .localize(datetime.strptime(elem.get("deliverydate"), "%Y-%m-%d %H:%M:%S"),
                                  is_dst=None)
                        .astimezone(pytz.utc)
                    ).strftime("%Y-%m-%d %H:%M:%S")
                    sol_name = elem.get("name").rsplit(" ", 1)
                    for so_line in self.env["sale.order.line"].search(
                        [("id", "=", sol_name[1])], limit=1
                    ):
                        so_line.sale_delivery_date = (
                            datetime.strptime(deliverydate, "%Y-%m-%d %H:%M:%S")
                        ).date()
                        so_line.frepple_write_date = datetime.now()
                        so_line.order_id._compute_commitment_date()

                except Exception as e:
                    logger.error("Exception %s" % e)
                    msg.append(str(e))
                # Remove the element now to keep the DOM tree small
                root.clear()
            elif event == "start" and elem.tag in ["operationplans", "demands"]:
                # Remember the root element
                root = elem

        # Update PO RFQ order_deadline and receipt date
        for sup in supplier_reference.values():
            if sup["min_planned"]:
                sup["po"].date_planned = sup["min_planned"]
            if sup["min_ordered"]:
                sup["po"].date_order = sup["min_ordered"]

        # Be polite, and reply to the post
        msg.append("Processed %s uploaded procurement orders" % countproc)
        msg.append("Processed %s uploaded manufacturing orders" % countmfg)
        return "\n".join(msg)
