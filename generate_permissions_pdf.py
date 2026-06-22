#!/usr/bin/env python
"""
Generate Permissions_API.pdf
Documents the RBAC permission system and how the frontend must use it.
Run: python generate_permissions_pdf.py
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether,
)
from reportlab.lib.enums import TA_CENTER, TA_RIGHT

# ── Colours ──────────────────────────────────────────────────────────────────
BLUE         = colors.HexColor('#1a73e8')
DARK_GRAY    = colors.HexColor('#212121')
MID_GRAY     = colors.HexColor('#666666')
LIGHT_GRAY   = colors.HexColor('#f5f5f5')
BORDER_GRAY  = colors.HexColor('#e0e0e0')
CODE_BG      = colors.HexColor('#1e2a3a')
GREEN        = colors.HexColor('#2e7d32')
RED          = colors.HexColor('#c62828')
AMBER_BG     = colors.HexColor('#fffde7')
AMBER_BORDER = colors.HexColor('#f9a825')
ENDPOINT_BG  = colors.HexColor('#e8f0fe')

PAGE_W, PAGE_H = A4
MARGIN = 20 * mm
W = PAGE_W - 2 * MARGIN   # usable content width

# ── Styles ────────────────────────────────────────────────────────────────────
_base = getSampleStyleSheet()

def _s(name, **kw):
    kw.setdefault('fontName', 'Helvetica')
    return ParagraphStyle(name, parent=_base['Normal'], **kw)

S_TITLE   = _s('t',  fontSize=28, textColor=BLUE,          leading=36, fontName='Helvetica-Bold')
S_SUB     = _s('su', fontSize=11, textColor=MID_GRAY,      leading=16)
S_BODY    = _s('bo', fontSize=10, textColor=DARK_GRAY,     leading=15)
S_SECT    = _s('se', fontSize=14, textColor=DARK_GRAY,     leading=20, fontName='Helvetica-Bold', spaceBefore=4)
S_SUBH    = _s('sh', fontSize=11, textColor=BLUE,          leading=16, fontName='Helvetica-Bold', spaceBefore=4)
S_CODE    = _s('co', fontSize=8,  textColor=colors.white,  leading=13, fontName='Courier')
S_NOTE    = _s('no', fontSize=9,  textColor=colors.HexColor('#5d4037'), leading=14, fontName='Helvetica-Oblique')
S_TH      = _s('th', fontSize=9,  textColor=DARK_GRAY,     fontName='Helvetica-Bold')
S_TD      = _s('td', fontSize=9,  textColor=DARK_GRAY)
S_RED     = _s('re', fontSize=10, textColor=RED,           fontName='Helvetica-Bold')
S_FOOTER  = _s('fo', fontSize=9,  textColor=MID_GRAY,      alignment=TA_CENTER)

# ── Reusable helpers ──────────────────────────────────────────────────────────

def rule(thick=1, color=BORDER_GRAY, before=2, after=6):
    return HRFlowable(width='100%', thickness=thick, color=color,
                      spaceBefore=before, spaceAfter=after)

def sp(n=3):
    return Spacer(1, n * mm)

def section(text):
    return KeepTogether([sp(2), Paragraph(text, S_SECT), rule()])

def p(text):
    return Paragraph(text, S_BODY)

def subh(text):
    return Paragraph(text, S_SUBH)

def note(text):
    t = Table([[Paragraph(f'<b>Note:</b> {text}', S_NOTE)]], colWidths=[W])
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), AMBER_BG),
        ('BOX',           (0, 0), (-1, -1), 1, AMBER_BORDER),
        ('LEFTPADDING',   (0, 0), (-1, -1), 10),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 10),
        ('TOPPADDING',    (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    return t

def code_block(lines):
    escaped = [
        ln.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        for ln in lines
    ]
    joined = '<br/>'.join(escaped)
    t = Table([[Paragraph(joined, S_CODE)]], colWidths=[W])
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), CODE_BG),
        ('LEFTPADDING',   (0, 0), (-1, -1), 12),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 12),
        ('TOPPADDING',    (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
    ]))
    return t

def endpoint(method, path, desc, color=BLUE):
    mp = Paragraph(f'<b>{method}</b>', _s('em', fontSize=10, textColor=color, fontName='Helvetica-Bold'))
    pp = Paragraph(f'<font name="Courier" size="10">{path}</font>', S_BODY)
    dp = Paragraph(f'<i>{desc}</i>', _s('ed', fontSize=9, textColor=MID_GRAY, alignment=TA_RIGHT))
    t = Table([[mp, pp, dp]], colWidths=[14 * mm, 85 * mm, W - 14 * mm - 85 * mm])
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), ENDPOINT_BG),
        ('BOX',           (0, 0), (-1, -1), 1, BLUE),
        ('LEFTPADDING',   (0, 0), (-1, -1), 10),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 10),
        ('TOPPADDING',    (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    return t

def step(n, text):
    badge = Paragraph(f'<b>{n}</b>',
                      _s(f'sn{n}', fontSize=9, textColor=colors.white,
                         fontName='Helvetica-Bold', alignment=TA_CENTER))
    body = Paragraph(text, S_BODY)
    t = Table([[badge, body]], colWidths=[7 * mm, W - 7 * mm - 5 * mm])
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (0, 0), BLUE),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING',   (0, 0), (0, 0), 0),
        ('RIGHTPADDING',  (0, 0), (0, 0), 0),
        ('LEFTPADDING',   (1, 0), (1, 0), 8),
    ]))
    return t

def dtable(headers, rows, widths=None):
    if widths is None:
        widths = [W / len(headers)] * len(headers)
    th_row = [Paragraph(h, S_TH) for h in headers]
    td_rows = [[Paragraph(str(c), S_TD) for c in row] for row in rows]
    t = Table([th_row] + td_rows, colWidths=widths)
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, 0), LIGHT_GRAY),
        ('GRID',          (0, 0), (-1, -1), 0.5, BORDER_GRAY),
        ('LEFTPADDING',   (0, 0), (-1, -1), 8),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 8),
        ('TOPPADDING',    (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
    ]))
    return t

# ── Story ─────────────────────────────────────────────────────────────────────
story = []

# ── Header ────────────────────────────────────────────────────────────────────
story += [
    Paragraph('Permissions &amp; RBAC API', S_TITLE),
    sp(2),
    Paragraph('Doova One View · Authentication Module', S_SUB),
    sp(3),
    rule(thick=2, color=BLUE, before=0, after=8),
    sp(1),
    p('This document explains how the authentication system changed from a simple role field '
      'to a full Role-Based Access Control (RBAC) system, and how the frontend must use the '
      'permissions list returned by the API to control access to features and routes.'),
]

# ── 1. How It Works ───────────────────────────────────────────────────────────
story += [
    section('How It Works'),
    p('The system is built on three layers:'),
    sp(2),
    step('1', '<b>Permission</b> — an atomic capability codename '
              '(e.g. <font name="Courier">view_sales</font>, '
              '<font name="Courier">export_reports</font>).'),
    sp(2),
    step('2', '<b>Role</b> — a named group of permissions '
              '(e.g. <i>manager</i>, <i>accountant</i>). '
              'A role bundles together all the capabilities that user type needs.'),
    sp(2),
    step('3', '<b>User</b> — assigned one or more roles, inheriting every permission from every '
              'assigned role. Users with <font name="Courier">is_superuser = true</font> '
              'bypass all permission checks on the server.'),
    sp(3),
    note('Permissions are <b>never stored inside the JWT token</b>. '
         'The frontend must call <font name="Courier">GET /auth/profile</font> after login '
         'to get the current permission list. This guarantees that a role change takes effect '
         'immediately — no token re-issue is required.'),
]

# ── 2. After Login ────────────────────────────────────────────────────────────
story += [
    section('After Login — Fetch the User’s Permissions'),
    p('The <font name="Courier">POST /auth/login</font> endpoint returns <b>only tokens</b> '
      '(access + refresh). It does <b>not</b> include roles or permissions. '
      'After logging in, immediately call <font name="Courier">GET /auth/profile</font>.'),
    sp(3),
    endpoint('GET', '/auth/profile', 'Returns profile, roles, and permissions', color=GREEN),
    sp(4),
    subh('Request header'),
    code_block([
        'GET /auth/profile',
        'Authorization: Bearer <access_token>',
    ]),
    sp(4),
    subh('Example response'),
    code_block([
        '{',
        '  "id": "b3f4a912-1234-...",',
        '  "email": "ali@example.com",',
        '  "full_name": "Ali El Hadi",',
        '  "is_active": true,',
        '  "created_at": "2025-01-15T09:00:00Z",',
        '  "last_login_at": "2025-06-15T10:30:00Z",',
        '  "roles": ["manager"],',
        '  "permissions": [',
        '    "export_accounting", "export_inventory", "export_purchases",',
        '    "export_reports", "export_sales", "use_agent",',
        '    "view_accounting", "view_inventory", "view_kpi",',
        '    "view_master_data", "view_purchases", "view_reports",',
        '    "view_sales", "view_tenants", "view_users"',
        '  ]',
        '}',
    ]),
    sp(4),
    subh('Responses'),
    dtable(
        ['HTTP Code', 'Meaning', 'Body'],
        [
            ['200', 'Success', 'Full UserResponse object (see above)'],
            ['401', 'Token missing or expired',
             '{"detail": "Authentication credentials were not provided."}'],
        ],
        widths=[20 * mm, 55 * mm, W - 20 * mm - 55 * mm],
    ),
]

# ── 3. All Permissions ────────────────────────────────────────────────────────
story += [
    section('All Available Permissions'),
    p('Every permission codename and the feature it gates. '
      'The <font name="Courier">permissions</font> array in the API response is '
      'always sorted alphabetically.'),
    sp(2),
    dtable(
        ['Codename', 'Module', 'Description'],
        [
            ['view_tenants',      'Tenants',     'View tenant list'],
            ['manage_tenants',    'Tenants',     'Create, update, and delete tenants'],
            ['view_users',        'Users',       'View user list and details'],
            ['manage_users',      'Users',       'Create and deactivate users'],
            ['manage_roles',      'RBAC',        'Create roles, assign permissions to roles, assign roles to users'],
            ['view_sales',        'Sales',       'View sales orders and summaries'],
            ['export_sales',      'Sales',       'Export sales data to file'],
            ['view_purchases',    'Purchases',   'View purchase orders'],
            ['export_purchases',  'Purchases',   'Export purchase data to file'],
            ['view_accounting',   'Accounting',  'View journal entries and account moves'],
            ['export_accounting', 'Accounting',  'Export accounting data to file'],
            ['view_inventory',    'Inventory',   'View stock and inventory levels'],
            ['export_inventory',  'Inventory',   'Export inventory data to file'],
            ['view_kpi',          'KPI',         'View KPI dashboards'],
            ['view_reports',      'Reports',     'View generated reports'],
            ['export_reports',    'Reports',     'Download and export reports'],
            ['use_agent',         'AI Agent',    'Send queries to the AI agent'],
            ['view_master_data',  'Master Data', 'View partners, products, and companies'],
        ],
        widths=[48 * mm, 33 * mm, W - 48 * mm - 33 * mm],
    ),
]

# ── 4. Default Roles ──────────────────────────────────────────────────────────
story += [
    section('Default Roles'),
    p('Three roles are seeded by default. Custom roles can be created and managed via the admin RBAC API.'),
    sp(2),
    dtable(
        ['Role', 'Count', 'Permissions Included'],
        [
            ['owner',
             '18 (all)',
             'All permissions — full access to every feature'],
            ['manager',
             '15',
             'view_tenants, view_users, view_sales, export_sales, view_purchases, '
             'export_purchases, view_accounting, export_accounting, view_inventory, '
             'export_inventory, view_kpi, view_reports, export_reports, use_agent, '
             'view_master_data'],
            ['accountant',
             '9',
             'view_sales, view_purchases, view_accounting, export_accounting, '
             'view_inventory, view_kpi, view_reports, use_agent, view_master_data'],
        ],
        widths=[25 * mm, 18 * mm, W - 25 * mm - 18 * mm],
    ),
]

# ── 5. How Frontend Uses Permissions ─────────────────────────────────────────
story += [
    section('How the Frontend Must Use Permissions'),
    p('After calling <font name="Courier">GET /auth/profile</font>, store the '
      '<font name="Courier">permissions</font> array in your global app state '
      '(Redux store, Pinia store, React context, etc.). '
      'Before rendering any feature or navigating to a guarded route, '
      'check whether the required codename is present in that array.'),
    sp(3),
    subh('Example (JavaScript / TypeScript)'),
    code_block([
        '// 1. After login, immediately fetch the user profile',
        'const res    = await fetch("/auth/profile", {',
        '  headers: { Authorization: `Bearer ${accessToken}` },',
        '});',
        'const profile = await res.json();',
        '',
        '// 2. Store permissions in a Set for O(1) lookup',
        'const permissions = new Set(profile.permissions);',
        '',
        '// 3. Guard UI elements',
        'const canViewSales   = permissions.has("view_sales");',
        'const canExportSales = permissions.has("export_sales");',
        'const canUseAgent    = permissions.has("use_agent");',
        '',
        '// 4. Guard a route (React Router example)',
        'if (!permissions.has("view_accounting")) {',
        '  return <Navigate to="/forbidden" />;',
        '}',
    ]),
    sp(3),
    note('<b>Superuser:</b> When <font name="Courier">is_superuser</font> is '
         '<font name="Courier">true</font> in the profile response, the server bypasses '
         'all permission checks. The frontend may optionally skip permission checks for '
         'superusers as well, but the server is always the final authority.'),
]

# ── 6. Handling 403 ──────────────────────────────────────────────────────────
story += [
    section('Handling 403 Errors'),
    p('When a request is rejected because the user lacks a required permission, '
      'the server returns <b>HTTP 403 Forbidden</b>. '
      'The body always names the missing permission codenames:'),
    sp(2),
    code_block([
        '// 403 Forbidden response body',
        '{',
        '  "detail": "Missing permissions: view_sales, export_sales"',
        '}',
    ]),
    sp(3),
    dtable(
        ['HTTP Code', 'Meaning', 'What to show the user'],
        [
            ['401', 'Not authenticated — token is missing or expired',
             'Redirect to login page and clear all stored tokens'],
            ['403', 'Authenticated but lacks the required permission',
             'Show a "You do not have access to this feature" message — do NOT redirect to login'],
        ],
        widths=[20 * mm, 72 * mm, W - 20 * mm - 72 * mm],
    ),
]

# ── 7. Common Mistakes ────────────────────────────────────────────────────────
story += [
    section('Common Mistakes to Avoid'),
    sp(2),
]

mistakes = [
    ('Checking roles instead of permissions',
     'Always check a specific codename '
     '(e.g. <font name="Courier">permissions.has("view_sales")</font>), not the role name. '
     'A role can be updated to add or remove permissions without being renamed.'),
    ('Reading permissions from the JWT',
     'Permissions are <b>not</b> encoded in the access token. '
     'Decoding the JWT will not give you permissions. '
     'Always call <font name="Courier">GET /auth/profile</font>.'),
    ('Caching permissions indefinitely',
     'An admin may reassign a user’s role at any time. '
     'Re-fetch <font name="Courier">GET /auth/profile</font> on each app reload '
     'or after a known role change to stay in sync.'),
    ('Treating 403 as “not logged in”',
     '<b>403</b> = authenticated but lacks permission. '
     '<b>401</b> = not authenticated. '
     'Handle them with different UI flows — a 403 must not redirect to the login page.'),
    ('Relying only on frontend guards',
     'The server enforces permissions on every request regardless of what the frontend does. '
     'Frontend checks are for UX only — never treat them as a security boundary.'),
    ('Wrong Authorization header',
     'Always send <font name="Courier">Authorization: Bearer &lt;token&gt;</font> '
     '(capital B, one space after “Bearer”). '
     'Missing or malformed headers result in a 401 error.'),
]

mistake_rows = [
    [Paragraph(f'x  {label}', S_RED), Paragraph(text, S_TD)]
    for label, text in mistakes
]
mt = Table(mistake_rows, colWidths=[62 * mm, W - 62 * mm])
mt.setStyle(TableStyle([
    ('GRID',          (0, 0), (-1, -1), 0.5, BORDER_GRAY),
    ('LEFTPADDING',   (0, 0), (-1, -1), 8),
    ('RIGHTPADDING',  (0, 0), (-1, -1), 8),
    ('TOPPADDING',    (0, 0), (-1, -1), 7),
    ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
    ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
    ('BACKGROUND',    (0, 0), (0, -1),  colors.HexColor('#fff5f5')),
]))
story.append(mt)

# ── Footer ────────────────────────────────────────────────────────────────────
story += [
    sp(10),
    rule(thick=0.5, color=BORDER_GRAY, before=0, after=3),
    Paragraph('Doova One View — Internal API Reference', S_FOOTER),
]

# ── Build ─────────────────────────────────────────────────────────────────────
OUTPUT = 'Permissions_API.pdf'
doc = SimpleDocTemplate(
    OUTPUT,
    pagesize=A4,
    leftMargin=MARGIN,
    rightMargin=MARGIN,
    topMargin=MARGIN,
    bottomMargin=MARGIN,
)
doc.build(story)
print(f'Generated: {OUTPUT}')
