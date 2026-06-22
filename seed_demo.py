"""
Doova OneView — demo data seeder.
Connects directly to the test DB and inserts ~700 realistic records.
Run: python seed_demo.py
"""
import psycopg2
import psycopg2.extras
import uuid
import random
from datetime import date, timedelta, datetime
from decimal import Decimal

random.seed(42)

conn = psycopg2.connect(
    dbname="odoo", user="admin", password="Hf,Li]D55226644",
    host="185.194.219.47", port=5432
)
cur = conn.cursor()
NOW = datetime.now()

TENANT_ID  = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
SUPERUSER_ID = "558aa152-d1ba-4079-b705-85d79888ef50"
COMPANY_ID = 1

MONTH_NAMES = ["January","February","March","April","May","June",
               "July","August","September","October","November","December"]
DAY_NAMES   = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]


# ── 0. Clean up any previous run ─────────────────────────────────────────────
print("0. Cleaning up previous demo data...")
cur.execute("DELETE FROM fact_account_move_lines WHERE tenant_id = %s", (TENANT_ID,))
cur.execute("DELETE FROM fact_account_moves       WHERE tenant_id = %s", (TENANT_ID,))
cur.execute("DELETE FROM fact_sales_order_lines   WHERE tenant_id = %s", (TENANT_ID,))
cur.execute("DELETE FROM fact_sales_orders        WHERE tenant_id = %s", (TENANT_ID,))
cur.execute("DELETE FROM fact_purchase_order_lines WHERE tenant_id = %s", (TENANT_ID,))
cur.execute("DELETE FROM fact_purchase_orders     WHERE tenant_id = %s", (TENANT_ID,))
cur.execute("DELETE FROM fact_stock_quants        WHERE tenant_id = %s", (TENANT_ID,))
cur.execute("DELETE FROM dim_lots                 WHERE tenant_id = %s", (TENANT_ID,))
cur.execute("DELETE FROM dim_users                WHERE tenant_id = %s", (TENANT_ID,))
cur.execute("DELETE FROM dim_products             WHERE tenant_id = %s", (TENANT_ID,))
cur.execute("DELETE FROM dim_product_categories   WHERE tenant_id = %s", (TENANT_ID,))
cur.execute("DELETE FROM dim_partners             WHERE tenant_id = %s", (TENANT_ID,))
cur.execute("DELETE FROM dim_companies            WHERE tenant_id = %s", (TENANT_ID,))
cur.execute("DELETE FROM dim_currencies           WHERE tenant_id = %s", (TENANT_ID,))
cur.execute("DELETE FROM user_tenant_access       WHERE tenant_id = %s", (TENANT_ID,))
cur.execute("DELETE FROM dim_time")
cur.execute("DELETE FROM tenants                  WHERE id        = %s", (TENANT_ID,))
conn.commit()
print("   done.")


# ── 1. Tenant ─────────────────────────────────────────────────────────────────
print("1. Tenant...")
cur.execute("""
INSERT INTO tenants (id,name,odoo_url,odoo_database,api_key_encrypted,
    is_active,sync_status,created_at,updated_at)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
ON CONFLICT (id) DO NOTHING
""", (TENANT_ID, "Doova Trading LLC", "https://demo.doova.com",
      "doova_demo", psycopg2.Binary(b"DEMO_KEY"),
      True, "active", NOW, NOW))


# ── 2. Currency ───────────────────────────────────────────────────────────────
print("2. Currency...")
cur.execute("""
INSERT INTO dim_currencies (tenant_id,odoo_id,code,symbol,is_active,symbol_position,rounding)
VALUES (%s,%s,%s,%s,%s,%s,%s)
ON CONFLICT (tenant_id,odoo_id) DO NOTHING
""", (TENANT_ID, 1, "USD", "$", True, "before", Decimal("0.01")))


# ── 3. Company ────────────────────────────────────────────────────────────────
print("3. Company...")
cur.execute("""
INSERT INTO dim_companies (id,odoo_id,name,currency_code,country_code,is_active,
    created_at,tenant_id,country_id,country_name,currency_id,currency_name,display_name)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
""", (COMPANY_ID, 1, "Doova Trading LLC", "USD", "US", True, NOW,
      TENANT_ID, 233, "United States", 1, "US Dollar", "Doova Trading LLC"))


# ── 4. dim_time (2023-01-01 → 2025-06-13) ────────────────────────────────────
print("4. Time dimension...")
rows = []
d = date(2023, 1, 1)
while d <= date(2026, 12, 31):
    date_id = d.year * 10000 + d.month * 100 + d.day
    q = (d.month - 1) // 3 + 1
    dow = d.weekday()
    rows.append((date_id, d, d.year, q, d.month, MONTH_NAMES[d.month-1],
                 d.isocalendar()[1], d.day, dow+1, DAY_NAMES[dow],
                 dow >= 5, False, d.year, q))
    d += timedelta(days=1)
cur.executemany("""
INSERT INTO dim_time (date_id,full_date,year,quarter,month,month_name,week,
    day_of_month,day_of_week,day_name,is_weekend,is_holiday,fiscal_year,fiscal_quarter)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
ON CONFLICT (date_id) DO NOTHING
""", rows)
print(f"   {len(rows)} dates")


# ── 5. Partners ───────────────────────────────────────────────────────────────
print("5. Partners...")
PARTNERS = [
    # db_id, odoo_id, name, is_cust, is_sup, email, phone, country, city, cust_rank, sup_rank
    (1,  1,  "TechVision Corporation",    True,  False, "info@techvision.com",   "+1-555-0101", "US", "New York",    5, 0),
    (2,  2,  "Sunrise Retail Ltd",        True,  False, "buy@sunrise.com",       "+1-555-0102", "US", "Los Angeles", 4, 0),
    (3,  3,  "Global Traders Inc",        True,  False, "orders@globaltraders.com","+1-555-0103","US","Chicago",     6, 0),
    (4,  4,  "Metro Solutions",           True,  False, "metro@solutions.com",   "+1-555-0104", "US", "Houston",     3, 0),
    (5,  5,  "Pacific Ventures",          True,  False, "pv@pacific.com",        "+44-555-0105","GB","London",      5, 0),
    (6,  6,  "Northern Supply Co",        True,  False, "ns@northern.com",       "+1-555-0106", "CA", "Toronto",    4, 0),
    (7,  7,  "Eastern Distributors",      True,  False, "ed@eastern.com",        "+971-555-0107","AE","Dubai",      7, 0),
    (8,  8,  "Summit Enterprises",        True,  False, "se@summit.com",         "+1-555-0108", "US", "Denver",     3, 0),
    (9,  9,  "Coastal Commerce",          True,  False, "cc@coastal.com",        "+1-555-0109", "US", "Miami",      4, 0),
    (10, 10, "Alpine Industries",         True,  False, "ai@alpine.com",         "+41-555-0110","CH","Zurich",      5, 0),
    (11, 11, "Prime Manufacturers",       False, True,  "sales@prime.com",       "+1-555-0201", "US", "Detroit",    0, 6),
    (12, 12, "Atlas Components Ltd",      False, True,  "orders@atlas.com",      "+49-555-0202","DE","Berlin",      0, 5),
    (13, 13, "Continental Goods",         False, True,  "cg@continental.com",    "+33-555-0203","FR","Paris",       0, 4),
    (14, 14, "Pioneer Materials",         False, True,  "pm@pioneer.com",        "+1-555-0204", "US", "Seattle",    0, 5),
    (15, 15, "Delta Wholesale",           False, True,  "dw@delta.com",          "+1-555-0205", "US", "Atlanta",    0, 7),
]
cur.executemany("""
INSERT INTO dim_partners (id,odoo_id,name,partner_type,is_customer,is_supplier,
    email,phone,country_code,city,customer_rank,supplier_rank,is_active,created_at,tenant_id)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
""", [(p[0],p[1],p[2],"company",p[3],p[4],p[5],p[6],p[7],p[8],p[9],p[10],
       True, NOW, TENANT_ID) for p in PARTNERS])

CUSTOMER_IDS = list(range(1, 11))
SUPPLIER_IDS = list(range(11, 16))


# ── 6. Product categories ─────────────────────────────────────────────────────
print("6. Product categories...")
CATS = [
    (1, 1, "Electronics",           "All / Electronics"),
    (2, 2, "Office Supplies",       "All / Office Supplies"),
    (3, 3, "Industrial Equipment",  "All / Industrial Equipment"),
    (4, 4, "Software & Licenses",   "All / Software & Licenses"),
    (5, 5, "Services",              "All / Services"),
]
cur.executemany("""
INSERT INTO dim_product_categories (id,odoo_id,name,complete_name,tenant_id)
VALUES (%s,%s,%s,%s,%s)
""", [(c[0],c[1],c[2],c[3],TENANT_ID) for c in CATS])


# ── 7. Products ───────────────────────────────────────────────────────────────
print("7. Products...")
# id, odoo_id, name, code, cat_id, list_price, std_price, type
PRODUCTS = [
    (1,  1,  'Laptop Pro 15"',            "ELEC-001", 1, 1299.00, 800.00, "product"),
    (2,  2,  "Wireless Mouse",             "ELEC-002", 1,   45.00,  15.00, "product"),
    (3,  3,  '4K Monitor 27"',            "ELEC-003", 1,  599.00, 320.00, "product"),
    (4,  4,  "USB-C Hub 7-Port",           "ELEC-004", 1,   89.00,  35.00, "product"),
    (5,  5,  "Wireless Keyboard",          "ELEC-005", 1,  129.00,  55.00, "product"),
    (6,  6,  "Printer Paper A4 (500s)",    "OFFC-001", 2,   18.00,   8.00, "product"),
    (7,  7,  "Ballpoint Pens Box",         "OFFC-002", 2,   12.00,   4.00, "product"),
    (8,  8,  "Whiteboard Markers Set",     "OFFC-003", 2,    8.00,   3.00, "product"),
    (9,  9,  "Ergonomic Office Chair",     "OFFC-004", 2,  349.00, 180.00, "product"),
    (10, 10, "Steel Filing Cabinet",       "OFFC-005", 2,  249.00, 120.00, "product"),
    (11, 11, "Power Drill Set",            "INDL-001", 3,  189.00,  90.00, "product"),
    (12, 12, "Safety Gloves Box (12pr)",   "INDL-002", 3,   35.00,  12.00, "product"),
    (13, 13, "Heavy-Duty Storage Rack",    "INDL-003", 3,  299.00, 150.00, "product"),
    (14, 14, "Professional Hand Tools Kit","INDL-004", 3,   89.00,  40.00, "product"),
    (15, 15, "Diesel Generator 5kW",       "INDL-005", 3, 1299.00, 700.00, "product"),
    (16, 16, "Antivirus License (1yr)",    "SOFT-001", 4,   49.00,   5.00, "service"),
    (17, 17, "Office Suite License (1yr)", "SOFT-002", 4,  299.00,  30.00, "service"),
    (18, 18, "Cloud Storage 1TB (1yr)",    "SOFT-003", 4,   99.00,  10.00, "service"),
    (19, 19, "ERP Subscription (annual)",  "SOFT-004", 4, 1499.00, 200.00, "service"),
    (20, 20, "IT Support Contract (annual)","SERV-001", 5,  799.00, 300.00, "service"),
]
cur.executemany("""
INSERT INTO dim_products (id,odoo_id,odoo_template_id,name,default_code,product_type,
    list_price,standard_price,uom_name,is_active,created_at,category_id,tenant_id)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
""", [(p[0],p[1],p[1],p[2],p[3],p[7],p[5],p[6],"Units",True,NOW,p[4],TENANT_ID)
     for p in PRODUCTS])


# ── 8. Salespeople ────────────────────────────────────────────────────────────
print("8. Salespeople...")
SALESPEOPLE = [
    (1, 1, "Ahmed Al-Hassan", "ahmed@doova.com"),
    (2, 2, "Sarah Thompson",  "sarah@doova.com"),
    (3, 3, "James Wilson",    "james@doova.com"),
]
cur.executemany("""
INSERT INTO dim_users (id,odoo_id,name,email,is_active,tenant_id)
VALUES (%s,%s,%s,%s,%s,%s)
""", [(s[0],s[1],s[2],s[3],True,TENANT_ID) for s in SALESPEOPLE])
SP_IDS = [s[0] for s in SALESPEOPLE]


# ── helpers ───────────────────────────────────────────────────────────────────
def date_id(d): return d.year * 10000 + d.month * 100 + d.day
def D(v):       return Decimal(str(v)).quantize(Decimal("0.01"))

# product lookup: id → (list_price, std_price)
PROD_MAP = {p[0]: (p[5], p[6]) for p in PRODUCTS}
# physical products (for sales lines — include everything to make numbers interesting)
ALL_PROD_IDS = [p[0] for p in PRODUCTS]
# products that can be stocked
STOCK_PROD_IDS = [p[0] for p in PRODUCTS if p[7] == "product"]


# ── 9. Sales orders ───────────────────────────────────────────────────────────
print("9. Sales orders + lines...")

def gen_dates(year, month_range, per_month_range):
    out = []
    for m in month_range:
        for _ in range(random.randint(*per_month_range)):
            out.append(date(year, m, random.randint(1, 28)))
    return out

so_dates = sorted(
    gen_dates(2023, range(1,13), (3,6)) +   # 2023: full year, moderate volume
    gen_dates(2024, range(1,13), (4,7)) +   # 2024: full year, growing volume
    gen_dates(2025, range(1,13), (5,9)) +   # 2025: full year, peak volume (last year)
    gen_dates(2026, range(1, 7), (4,7))    # 2026: Jan–Jun YTD (this year)
)

so_rows  = []
sol_rows = []
so_db_id = 1
sol_db_id = 1

for i, od in enumerate(so_dates):
    partner_id   = random.choice(CUSTOMER_IDS)
    sp_id        = random.choice(SP_IDS)
    state        = random.choices(["sale","done"], weights=[0.55,0.45])[0]
    inv_status   = random.choices(["invoiced","to invoice","nothing"], weights=[0.65,0.25,0.1])[0]
    n_lines      = random.randint(2, 3)
    sel_prods    = random.sample(ALL_PROD_IDS, n_lines)

    untaxed = D(0); tax = D(0); order_margin = D(0)

    for prod_id in sel_prods:
        lp, sp = PROD_MAP[prod_id]
        qty      = random.choice([1,2,3,5,10])
        disc     = random.choice([0,0,0,5,10])
        pu       = D(lp)
        sub      = D(lp * qty * (1 - disc/100))
        tot      = D(lp * qty * (1 - disc/100) * 1.15)
        margin   = D((lp - sp) * qty * (1 - disc/100))
        untaxed += sub; tax += tot - sub; order_margin += margin
        sol_rows.append((
            sol_db_id, sol_db_id, so_db_id,      # id, odoo_id, odoo_order_id
            D(qty), D(qty) if state=="done" else D(0),
            D(qty) if inv_status=="invoiced" else D(0),
            pu, sub, tot, D(disc), margin, D(sp),
            NOW, NOW, COMPANY_ID, prod_id, so_db_id, TENANT_ID
        ))
        sol_db_id += 1

    so_rows.append((
        so_db_id, so_db_id, f"SO{so_db_id:05d}",
        datetime.combine(od, datetime.min.time()), None, None,
        state, inv_status,
        untaxed.quantize(D("0.01")),
        tax.quantize(D("0.01")),
        (untaxed+tax).quantize(D("0.01")),
        order_margin.quantize(D("0.01")),
        "USD", NOW, NOW, COMPANY_ID, partner_id, TENANT_ID,
        date_id(od), sp_id
    ))
    so_db_id += 1

cur.executemany("""
INSERT INTO fact_sales_orders
  (id,odoo_id,odoo_name,date_order,validity_date,commitment_date,
   state,invoice_status,amount_untaxed,amount_tax,amount_total,margin,
   currency_code,odoo_write_date,synced_at,company_id,partner_id,tenant_id,
   date_order_id,user_id)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
""", so_rows)

cur.executemany("""
INSERT INTO fact_sales_order_lines
  (id,odoo_id,odoo_order_id,product_uom_qty,qty_delivered,qty_invoiced,
   price_unit,price_subtotal,price_total,discount,margin,purchase_price,
   odoo_write_date,synced_at,company_id,product_id,sales_order_id,tenant_id)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
""", sol_rows)
print(f"   {len(so_rows)} orders, {len(sol_rows)} lines")


# ── 10. Purchase orders ───────────────────────────────────────────────────────
print("10. Purchase orders + lines...")

po_dates = sorted(
    gen_dates(2023, range(1,13), (2,4)) +
    gen_dates(2024, range(1,13), (2,4)) +
    gen_dates(2025, range(1,13), (3,5)) +
    gen_dates(2026, range(1, 7), (2,4))
)

po_rows  = []
pol_rows = []
po_db_id = 1
pol_db_id = 1

for i, od in enumerate(po_dates):
    partner_id = random.choice(SUPPLIER_IDS)
    sp_id      = random.choice(SP_IDS)
    state      = random.choices(["purchase","done"], weights=[0.6,0.4])[0]
    inv_status = random.choices(["invoiced","to invoice","nothing"], weights=[0.6,0.3,0.1])[0]
    n_lines    = random.randint(2, 3)
    # purchase physical products primarily
    sel_prods  = random.sample(STOCK_PROD_IDS, min(n_lines, len(STOCK_PROD_IDS)))

    untaxed = D(0); tax = D(0)

    for prod_id in sel_prods:
        lp, sp  = PROD_MAP[prod_id]
        cost    = D(sp * 1.05)          # we pay slightly above std cost
        qty     = random.choice([5, 10, 20, 50])
        sub     = D(float(cost) * qty)
        tot     = D(float(cost) * qty * 1.15)
        untaxed += sub; tax += tot - sub
        pol_rows.append((
            pol_db_id, pol_db_id, po_db_id,
            D(qty), D(qty) if state=="done" else D(0),
            D(qty) if inv_status=="invoiced" else D(0),
            cost, sub, tot,
            datetime.combine(od + timedelta(days=14), datetime.min.time()),
            f"Purchase of {prod_id}",
            NOW, NOW, COMPANY_ID, prod_id, po_db_id, TENANT_ID
        ))
        pol_db_id += 1

    date_approve = datetime.combine(od + timedelta(days=1), datetime.min.time())
    po_rows.append((
        po_db_id, po_db_id, f"PO{po_db_id:05d}",
        datetime.combine(od, datetime.min.time()),
        datetime.combine(od + timedelta(days=14), datetime.min.time()),
        date_approve, state, inv_status,
        untaxed.quantize(D("0.01")),
        tax.quantize(D("0.01")),
        (untaxed+tax).quantize(D("0.01")),
        "USD", None, NOW, NOW, COMPANY_ID, partner_id, TENANT_ID,
        date_id(od), sp_id
    ))
    po_db_id += 1

cur.executemany("""
INSERT INTO fact_purchase_orders
  (id,odoo_id,odoo_name,date_order,date_planned,date_approve,
   state,invoice_status,amount_untaxed,amount_tax,amount_total,
   currency_code,partner_ref,odoo_write_date,synced_at,
   company_id,partner_id,tenant_id,date_order_id,user_id)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
""", po_rows)

cur.executemany("""
INSERT INTO fact_purchase_order_lines
  (id,odoo_id,odoo_order_id,product_qty,qty_received,qty_invoiced,
   price_unit,price_subtotal,price_total,date_planned,name,
   odoo_write_date,synced_at,company_id,product_id,purchase_order_id,tenant_id)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
""", pol_rows)
print(f"   {len(po_rows)} orders, {len(pol_rows)} lines")


# ── 11. Account moves (invoices + bills) ──────────────────────────────────────
print("11. Account moves + lines...")

am_rows  = []
aml_rows = []
am_db_id = 1
aml_db_id = 1

# Customer invoices (out_invoice) — one per sold+invoiced sales order
invoiced_so = [r for r in so_rows if r[7] == "invoiced"]   # invoice_status col index 7
for so in invoiced_so:
    so_db    = so[0]
    so_date  = so[3].date()
    inv_date = so_date + timedelta(days=random.randint(1,5))
    due_date = inv_date + timedelta(days=30)
    amt      = so[10]  # amount_total
    # some paid, some overdue
    is_paid  = random.random() < 0.65
    overdue  = not is_paid and due_date < date.today()
    pstate   = "paid" if is_paid else ("not_paid" if overdue else "not_paid")
    residual = D(0) if is_paid else amt

    am_rows.append((
        am_db_id, am_db_id, f"INV/{inv_date.year}/{am_db_id:05d}",
        inv_date, inv_date, due_date,
        "out_invoice", "posted", pstate,
        D(float(amt)/1.15), amt - D(float(amt)/1.15), amt, residual,
        "USD", f"SO{so_db:05d}", None,
        NOW, NOW, COMPANY_ID,
        so[16],       # partner_id
        TENANT_ID,
        date_id(inv_date), date_id(inv_date)
    ))

    # Two lines: revenue + tax
    revenue  = D(float(amt)/1.15)
    tax_amt  = amt - revenue
    aml_rows.append((
        aml_db_id, aml_db_id, am_db_id,
        "1100", "Accounts Receivable", "asset_receivable",
        amt, D(0), amt, amt, "USD", None, None, None,
        "Invoice line",
        NOW, NOW, am_db_id, COMPANY_ID, so[16], None, TENANT_ID
    ))
    aml_db_id += 1
    aml_rows.append((
        aml_db_id, aml_db_id, am_db_id,
        "4000", "Sales Revenue", "income",
        D(0), revenue, D(0-float(revenue)), revenue, "USD", None, None, None,
        "Revenue",
        NOW, NOW, am_db_id, COMPANY_ID, so[16], None, TENANT_ID
    ))
    aml_db_id += 1
    am_db_id += 1

# Vendor bills (in_invoice) — one per purchased+invoiced PO
invoiced_po = [r for r in po_rows if r[7] == "invoiced"]
for po in invoiced_po:
    po_db    = po[0]
    po_date  = po[3].date()
    bill_date = po_date + timedelta(days=random.randint(3,7))
    due_date  = bill_date + timedelta(days=45)
    amt       = po[10]
    is_paid   = random.random() < 0.60
    pstate    = "paid" if is_paid else "not_paid"
    residual  = D(0) if is_paid else amt

    am_rows.append((
        am_db_id, am_db_id, f"BILL/{bill_date.year}/{am_db_id:05d}",
        bill_date, bill_date, due_date,
        "in_invoice", "posted", pstate,
        D(float(amt)/1.15), amt - D(float(amt)/1.15), amt, residual,
        "USD", f"PO{po_db:05d}", None,
        NOW, NOW, COMPANY_ID,
        po[15],       # partner_id
        TENANT_ID,
        date_id(bill_date), date_id(bill_date)
    ))

    exp      = D(float(amt)/1.15)
    tax_amt  = amt - exp
    aml_rows.append((
        aml_db_id, aml_db_id, am_db_id,
        "5000", "Cost of Goods Sold", "expense",
        exp, D(0), exp, exp, "USD", None, None, None,
        "Bill line",
        NOW, NOW, am_db_id, COMPANY_ID, po[15], None, TENANT_ID
    ))
    aml_db_id += 1
    aml_rows.append((
        aml_db_id, aml_db_id, am_db_id,
        "2100", "Accounts Payable", "liability_payable",
        D(0), amt, D(0-float(amt)), amt, "USD", None, None, None,
        "Payable",
        NOW, NOW, am_db_id, COMPANY_ID, po[15], None, TENANT_ID
    ))
    aml_db_id += 1
    am_db_id += 1

cur.executemany("""
INSERT INTO fact_account_moves
  (id,odoo_id,odoo_name,date,invoice_date,invoice_date_due,
   move_type,state,payment_state,
   amount_untaxed,amount_tax,amount_total,amount_residual,
   currency_code,invoice_origin,ref,
   odoo_write_date,synced_at,company_id,partner_id,tenant_id,
   date_id,invoice_date_id)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
""", am_rows)

cur.executemany("""
INSERT INTO fact_account_move_lines
  (id,odoo_id,odoo_move_id,account_code,account_name,account_type,
   debit,credit,balance,amount_currency,currency_code,
   quantity,price_unit,price_subtotal,name,
   odoo_write_date,synced_at,
   account_move_id,company_id,partner_id,product_id,tenant_id)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
""", aml_rows)
print(f"   {len(am_rows)} moves, {len(aml_rows)} move lines")


# ── 12. Stock quants (current inventory) ──────────────────────────────────────
print("12. Stock quants...")
sq_rows = []
for i, prod_id in enumerate(STOCK_PROD_IDS, start=1):
    qty = random.randint(10, 500)
    res = random.randint(0, min(qty, 50))
    sq_rows.append((
        i, i, "WH/Stock", D(qty), D(res),
        datetime(2024, 1, 1), NOW, NOW,
        COMPANY_ID, None, prod_id, TENANT_ID
    ))

cur.executemany("""
INSERT INTO fact_stock_quants
  (id,odoo_id,location_name,quantity,reserved_quantity,
   in_date,odoo_write_date,synced_at,
   company_id,lot_id,product_id,tenant_id)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
""", sq_rows)
print(f"   {len(sq_rows)} quants")


# ── 13. user_tenant_access — link superuser to tenant ────────────────────────
print("13. User tenant access...")
cur.execute("""
INSERT INTO user_tenant_access (id,can_view_all_companies,allowed_company_ids,
    created_at,tenant_id,user_id)
VALUES (%s,%s,%s,%s,%s,%s)
""", (1, True, None, NOW, TENANT_ID, SUPERUSER_ID))


# ── commit ────────────────────────────────────────────────────────────────────
conn.commit()
cur.close()
conn.close()
print("\nDemo data inserted successfully.")
print(f"  Tenant ID : {TENANT_ID}")
print(f"  Company ID: {COMPANY_ID}")
print(f"  Sales orders : {len(so_rows)}")
print(f"  Purchase orders : {len(po_rows)}")
print(f"  Account moves : {len(am_rows)}")
print(f"  Stock quants : {len(sq_rows)}")
