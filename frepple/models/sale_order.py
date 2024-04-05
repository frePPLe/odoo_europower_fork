import os
import logging
from odoo import models, api, fields, exceptions
import requests
import jwt
import time
import datetime

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    frepple_write_date = fields.Datetime(string='Write Date (frePPLe)',compute='_compute_frepple_write_date', store=True)

    def action_frepple_quote(self):
        for sale_order in self:
            
            # -----[ BUILD THE REQUEST BODY ]-----
            request_body = {"demands": []}
            for line in sale_order.order_line:
                if line.product_id.type == "product":
                    product_name = "[" + str(line.product_id.default_code) + "] " + str(line.product_id.name)
                    if sale_order.picking_policy == "direct":
                        policy = "independend"
                    else:
                        policy = "alltogether"

                    if sale_order.commitment_date:
                        due_date = sale_order.commitment_date.strftime("%Y-%m-%dT%H:%M:%S")
                    else:
                        due_date = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

                    request_body["demands"].append({
                        "name": line.id,
                        # E-POWER - CUSTOMIZATION: e-power uses older frepple version
                        # "owner": sale_order.id,
                        # "policy": policy,
                        "quantity": int(line.product_uom_qty),
                        "description": "",
                        "due": due_date,
                        "item": {"name": product_name},
                        "location": {"name": sale_order.warehouse_id.id},
                        "customer": {"name": sale_order.partner_shipping_id.id},
                        "minshipment": int(line.product_uom_qty), # Minimum shipment = Per how many do you want to ship | Zelfde als quantity in the knop
                        "maxlateness": 86400000, #  Binnen x aantal seconden moet ik het hebben | Niet Belangrijk dus staat op 1000 dagen
                        "priority": 20 # Niet belangrijk, ik neem info over van wat de quote tool doet.
                    })
                
            # -----[ CREATE AUTH TOKEN ]-----
            encode_params = dict(
                exp=round(time.time()) + 600, user=sale_order.env.user.login
            )
            user_company_webtoken = sale_order.env.user.company_id.webtoken_key
            if not user_company_webtoken:
                raise exceptions.UserError("FrePPLe company web token not configured")
            
            base_url = sale_order.env.user.company_id.frepple_server
            if not base_url:
                raise exceptions.UserError("frePPLe web server not configured")
            
            webtoken = jwt.encode(encode_params, user_company_webtoken, algorithm="HS256")
            if not isinstance(webtoken, str):
                webtoken = webtoken.decode("ascii")


            # -----[ PERFORM THE REQUEST ]-----
            
            headers = {
                'Authorization': 'Bearer ' + str(webtoken),
                'Content-Type': 'application/json'
            }
            # E-POWER Customization
            #action = "quote"
            action = "inquiry"
            

            frepple_response = requests.post(base_url + "quote/" + str(action) + "/", headers=headers, json=request_body)
            response_status_code = frepple_response.status_code
            if response_status_code == 401:
                raise exceptions.UserError("User is not authorized to use FrePPLe")

            response_json = frepple_response.json()
            # -----[ CONSTRUCT THE NOTE BODY ]-----
            # prepare finding the furthest date of all products
            furthest_end_date = None

            note_body = '<p><font style="font-size: 18px;">--- FrePPle Quote ---</font></p><ul>'

            has_na = False

            for demand in response_json["demands"]:
                product_name = demand["item"]["name"]
                try:
                    end_date = datetime.datetime.strptime(demand["pegging"][0]["operationplan"]["end"].split("T")[0], "%Y-%m-%d")
                    if furthest_end_date is None or end_date > furthest_end_date:
                        furthest_end_date = end_date
                    end_date = end_date.strftime("%Y-%m-%d")
                except Exception as e:
                    has_na = True
                    end_date = "N/A"

                note_body = note_body + "<li><p>" + product_name + " => <b>" + str(end_date) + "</b></p></li>" 

            # -----[ SEND THE NOTE ]-----
            note_body = note_body + "</ul>"
            sale_order.message_post(body=note_body)

            # -----[ UPDATE THE DELIVERY DATE ]-----
            
            # E-POWER CUSTOMIZATION
            # if furthest_end_date and sale_order.commitment_date != furthest_end_date:
            #     sale_order.commitment_date = furthest_end_date

            if furthest_end_date and sale_order.xx_requested_delivery_date != furthest_end_date and not has_na:
                sale_order.xx_requested_delivery_date = furthest_end_date

    @api.depends('order_line.frepple_write_date')
    def _compute_frepple_write_date(self):
        for order in self:
            order.frepple_write_date = max(order.order_line.filtered(lambda l: l.frepple_write_date).mapped('frepple_write_date') or [False])


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    frepple_write_date = fields.Datetime(string='Write Date (frePPLe)')