"""
Sales order fact table synchronizer — fixed currency_code resolution.

Root cause of NULL currency_code:
  Odoo's currency_id field returns [odoo_currency_id, display_name].
  The display_name CAN differ from the ISO code depending on the Odoo
  language/locale setting (e.g. "US Dollar" instead of "USD").
  The only guaranteed source of the ISO code is dim_currencies.code,
  which is populated by CurrencySynchronizer from res.currency.name.

Fix:
  Replace the inline string extraction with a DB lookup against
  dim_currencies using the Odoo currency integer ID.
  A pre-fetch of dim_currencies IDs → codes is done once per sync run
  to avoid N queries.
"""

import logging
import time
from typing import Tuple, Optional, List, Dict
from odoo_app.etl.syncs.base_synchronizer import BaseSynchronizer

logger = logging.getLogger(__name__)


class SalesOrderSynchronizer(BaseSynchronizer):
    """Synchronizes sale.order and sale.order.line (sales fact tables)"""

    # ── SQL ────────────────────────────────────────────────────────────────

    ORDER_UPSERT_SQL = """
        INSERT INTO fact_sales_orders (
            tenant_id, odoo_id, odoo_name, company_id, partner_id,
            user_id, date_order, date_order_id, state, invoice_status,
            amount_untaxed, amount_tax, amount_total, margin,
            currency_code, odoo_create_date, odoo_write_date, synced_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (tenant_id, odoo_id) DO UPDATE SET
            state            = EXCLUDED.state,
            invoice_status   = EXCLUDED.invoice_status,
            amount_untaxed   = EXCLUDED.amount_untaxed,
            amount_tax       = EXCLUDED.amount_tax,
            amount_total     = EXCLUDED.amount_total,
            margin           = EXCLUDED.margin,
            currency_code    = EXCLUDED.currency_code,
            odoo_create_date = EXCLUDED.odoo_create_date,
            odoo_write_date  = EXCLUDED.odoo_write_date,
            synced_at        = NOW()
    """

    LINE_UPSERT_SQL = """
        INSERT INTO fact_sales_order_lines (
            tenant_id, sales_order_id, odoo_id, odoo_order_id,
            product_id, company_id, product_uom_qty, qty_delivered,
            qty_invoiced, price_unit, price_subtotal, price_total,
            discount, margin, purchase_price, odoo_write_date, synced_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (tenant_id, odoo_id) DO UPDATE SET
            qty_delivered    = EXCLUDED.qty_delivered,
            qty_invoiced     = EXCLUDED.qty_invoiced,
            price_subtotal   = EXCLUDED.price_subtotal,
            margin           = EXCLUDED.margin,
            purchase_price   = EXCLUDED.purchase_price,
            odoo_write_date  = EXCLUDED.odoo_write_date,
            synced_at        = NOW()
    """

    # ── Requested Odoo fields ──────────────────────────────────────────────

    REQ_ORDER_FIELDS = [
        'id', 'name', 'partner_id', 'user_id', 'date_order', 'state',
        'invoice_status', 'amount_untaxed', 'amount_tax', 'amount_total',
        'margin', 'company_id', 'currency_id', 'create_date', 'write_date',
    ]

    REQ_LINE_FIELDS = [
        'id', 'order_id', 'product_id', 'product_uom_qty', 'qty_delivered',
        'qty_invoiced', 'price_unit', 'price_subtotal', 'price_total',
        'discount', 'margin', 'purchase_price', 'company_id', 'write_date',
    ]

    # ── Entry point ────────────────────────────────────────────────────────

    def sync(self, tenant_id: str, last_sync_date: str = None, **kwargs) -> Tuple[int, int]:
        start_time = time.time()
        logger.info(f"[SalesOrderSynchronizer] Starting — tenant={tenant_id}")

        # Pre-fetch dimension ID caches (avoids per-row DB hits)
        self.prefetch_ids('dim_partners', tenant_id)
        self.prefetch_ids('dim_users', tenant_id)
        self.prefetch_ids('dim_companies', tenant_id)
        self.prefetch_ids('dim_products', tenant_id)

        # ── FIX: pre-fetch currency map  odoo_id → ISO code ───────────────
        # dim_currencies must be synced BEFORE sales orders.
        # CurrencySynchronizer stores the ISO code in the `code` column.
        self._currency_map = self._build_currency_map(tenant_id)
        logger.info(
            f"[SalesOrderSynchronizer] Loaded {len(self._currency_map)} currencies: "
            f"{list(self._currency_map.values())}"
        )

        domain = [['write_date', '>', last_sync_date]] if last_sync_date else []

        # Resolve available fields against actual Odoo schema
        order_fields_avail = self._resolve_fields('sale.order', self.REQ_ORDER_FIELDS)
        line_fields_avail  = self._resolve_fields('sale.order.line', self.REQ_LINE_FIELDS)

        synced, failed = 0, 0
        batch_size = 200
        current_batch: List[dict] = []

        try:
            for order in self.fetch_paginated('sale.order', domain, order_fields_avail, batch_size=batch_size):
                current_batch.append(order)
                if len(current_batch) >= batch_size:
                    s, f = self._process_order_batch(tenant_id, current_batch, line_fields_avail)
                    synced += s
                    failed += f
                    current_batch = []

            if current_batch:
                s, f = self._process_order_batch(tenant_id, current_batch, line_fields_avail)
                synced += s
                failed += f

            self.log_sync_performance('sale.order', start_time, synced)
            return synced, failed

        except Exception as e:
            logger.error(f"[SalesOrderSynchronizer] Sync failed: {e}")
            raise

    # ── Currency map ───────────────────────────────────────────────────────

    def _build_currency_map(self, tenant_id: str) -> Dict[int, str]:
        """
        Load  { odoo_id: iso_code }  from dim_currencies for this tenant.

        This is the CORRECT way to resolve currency_code:
          - dim_currencies.odoo_id  = the integer ID from Odoo (currency_id[0])
          - dim_currencies.code     = the ISO code stored by CurrencySynchronizer
                                      from res.currency.name  (e.g. 'USD', 'EUR')

        Why not use currency_id[1] from the Odoo response?
          currency_id[1] is Odoo's display_name for the record, which is
          locale-dependent.  On an Arabic-locale instance it might return
          'دولار أمريكي' instead of 'USD'.  The code column is always ISO.
        """
        rows = self.db.fetch_all(
            "SELECT odoo_id, code FROM dim_currencies WHERE tenant_id = %s",
            (tenant_id,)
        )

        if not rows:
            logger.warning(
                "[SalesOrderSynchronizer] dim_currencies is empty for this tenant. "
                "Ensure CurrencySynchronizer runs BEFORE SalesOrderSynchronizer. "
                "currency_code will be NULL until currencies are synced."
            )
            return {}

        # psycopg2 with RealDictCursor returns dict rows; plain cursor returns tuples.
        # Handle both defensively.
        try:
            return {row['odoo_id']: row['code'] for row in rows}
        except TypeError:
            return {row[0]: row[1] for row in rows}

    def _resolve_currency_code(self, currency_id_field) -> Optional[str]:
        """
        Safely resolve currency_code from Odoo's currency_id Many2one field.

        Odoo returns:
            [7, "USD"]        ← normal case (list or tuple)
            False             ← field not set
            None              ← shouldn't happen but guard anyway

        Resolution order:
            1. Use dim_currencies map (ISO code, locale-safe)  ← preferred
            2. Fall back to currency_id[1] string              ← last resort
            3. Return None if neither is available
        """
        if not currency_id_field:
            return None

        if not isinstance(currency_id_field, (list, tuple)) or len(currency_id_field) < 2:
            return None

        odoo_currency_id: int   = currency_id_field[0]
        display_name:     str   = currency_id_field[1]

        # Primary: look up in the pre-fetched map
        code = self._currency_map.get(odoo_currency_id)
        if code:
            return code

        # Fallback: use the display name directly.
        # Warn so the operator knows currencies need syncing.
        logger.warning(
            f"[SalesOrderSynchronizer] Currency odoo_id={odoo_currency_id} "
            f"not found in dim_currencies. Falling back to display_name='{display_name}'. "
            f"Run CurrencySynchronizer to populate dim_currencies."
        )
        return display_name if display_name else None

    # ── Batch processing ───────────────────────────────────────────────────

    def _process_order_batch(
        self,
        tenant_id: str,
        orders: List[dict],
        line_fields: List[str],
    ) -> Tuple[int, int]:
        """Process one batch of orders + their lines."""

        order_params  = []
        order_odoo_ids = []
        failed = 0

        for order in orders:
            try:
                order_params.append(self._build_order_params(tenant_id, order))
                order_odoo_ids.append(order['id'])
            except Exception as e:
                logger.error(f"[SalesOrderSynchronizer] Error preparing order {order.get('id')}: {e}")
                failed += 1

        if order_params:
            self.execute_upsert_batch(self.ORDER_UPSERT_SQL, order_params)
            order_params.clear()

        # Fetch and upsert lines for all orders in this batch
        line_params: List[tuple] = []
        line_domain = [['order_id', 'in', order_odoo_ids]]

        for line in self.fetch_paginated('sale.order.line', line_domain, line_fields):
            try:
                line_params.append(self._build_line_params(tenant_id, line))

                if len(line_params) >= 1000:
                    self.execute_upsert_batch(self.LINE_UPSERT_SQL, line_params)
                    line_params.clear()

            except Exception as e:
                logger.error(f"[SalesOrderSynchronizer] Error preparing line {line.get('id')}: {e}")
                failed += 1

        if line_params:
            self.execute_upsert_batch(self.LINE_UPSERT_SQL, line_params)
            line_params.clear()

        return len(orders) - failed, failed

    # ── Param builders ─────────────────────────────────────────────────────

    def _build_order_params(self, tenant_id: str, order: dict) -> tuple:
        t = self.transformer
        return (
            tenant_id,
            order['id'],                                                              # odoo_id
            order.get('name'),                                                        # odoo_name
            self.get_internal_id('dim_companies', tenant_id,
                                 t.parse_odoo_many2one(order.get('company_id'))),    # company_id
            self.get_internal_id('dim_partners', tenant_id,
                                 t.parse_odoo_many2one(order.get('partner_id'))),    # partner_id
            self.get_internal_id('dim_users', tenant_id,
                                 t.parse_odoo_many2one(order.get('user_id'))),       # user_id
            t.parse_odoo_datetime(order.get('date_order')),                          # date_order
            t.get_date_id(order.get('date_order')),                                  # date_order_id
            order.get('state'),                                                       # state
            order.get('invoice_status'),                                              # invoice_status
            t.parse_odoo_decimal(order.get('amount_untaxed', 0)),                    # amount_untaxed
            t.parse_odoo_decimal(order.get('amount_tax', 0)),                        # amount_tax
            t.parse_odoo_decimal(order.get('amount_total', 0)),                      # amount_total
            t.parse_odoo_decimal(order.get('margin', 0)),                            # margin
            self._resolve_currency_code(order.get('currency_id')),                   # currency_code ← FIXED
            t.parse_odoo_datetime(order.get('create_date')),                         # odoo_create_date
            t.parse_odoo_datetime(order.get('write_date')),                          # odoo_write_date
        )

    def _build_line_params(self, tenant_id: str, line: dict) -> tuple:
        t = self.transformer
        order_odoo_id = t.parse_odoo_many2one(line.get('order_id'))
        return (
            tenant_id,
            self.get_internal_id('fact_sales_orders', tenant_id, order_odoo_id),     # sales_order_id
            line['id'],                                                               # odoo_id
            order_odoo_id,                                                            # odoo_order_id
            self.get_internal_id('dim_products', tenant_id,
                                 t.parse_odoo_many2one(line.get('product_id'))),     # product_id
            self.get_internal_id('dim_companies', tenant_id,
                                 t.parse_odoo_many2one(line.get('company_id'))),     # company_id
            t.parse_odoo_decimal(line.get('product_uom_qty', 0)),                    # product_uom_qty
            t.parse_odoo_decimal(line.get('qty_delivered', 0)),                      # qty_delivered
            t.parse_odoo_decimal(line.get('qty_invoiced', 0)),                       # qty_invoiced
            t.parse_odoo_decimal(line.get('price_unit', 0)),                         # price_unit
            t.parse_odoo_decimal(line.get('price_subtotal', 0)),                     # price_subtotal
            t.parse_odoo_decimal(line.get('price_total', 0)),                        # price_total
            t.parse_odoo_decimal(line.get('discount', 0)),                           # discount
            t.parse_odoo_decimal(line.get('margin', 0)),                             # margin
            t.parse_odoo_decimal(line.get('purchase_price', 0)),                     # purchase_price
            t.parse_odoo_datetime(line.get('write_date')),                           # odoo_write_date
        )

    # ── Helpers ────────────────────────────────────────────────────────────

    def _resolve_fields(self, model: str, requested: List[str]) -> List[str]:
        """Filter requested fields to only those that exist on the Odoo model."""
        available = self.with_retry(self.odoo.get_fields, model).keys()
        return [f for f in requested if f in available]