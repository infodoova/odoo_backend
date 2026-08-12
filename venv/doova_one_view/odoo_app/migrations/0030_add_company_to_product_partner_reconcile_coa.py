"""
Add company FK to Product, Partner, AccountPartialReconcile, and ChartOfAccounts models.

These models correspond to Odoo objects that have company_id fields, but were
previously synced without capturing the company relationship. This enables
filtering KPIs and data by company within a multi-company tenant.
"""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('odoo_app', '0029_delete_stale_permissions'),
    ]

    operations = [
        # ── Product ───────────────────────────────────────────────────────
        migrations.AddField(
            model_name='product',
            name='company',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to='odoo_app.company',
            ),
        ),

        # ── Partner ───────────────────────────────────────────────────────
        migrations.AddField(
            model_name='partner',
            name='company',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to='odoo_app.company',
            ),
        ),

        # ── AccountPartialReconcile ───────────────────────────────────────
        migrations.AddField(
            model_name='accountpartialreconcile',
            name='company',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to='odoo_app.company',
            ),
        ),

        # ── ChartOfAccounts ───────────────────────────────────────────────
        migrations.AddField(
            model_name='chartofaccounts',
            name='company',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to='odoo_app.company',
            ),
        ),
    ]
