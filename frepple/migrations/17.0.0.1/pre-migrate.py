def migrate(cr, version):
    if not version:
        return

    cr.execute("DELETE FROM frepple_quote fq WHERE fq.product_id NOT IN (SELECT id FROM product_product)")
    cr.execute("delete from ir_ui_view where arch_db ->> 'en_US' like '%partner_ref_unique%'")
    cr.execute("delete from ir_ui_view where arch_db ->> 'en_US' like '%frepple_write_date%'")

