# Generated manually by Codex on 2026-05-12

from django.db import migrations, models


def create_stored_files_table(apps, schema_editor):
    table_name = "stored_files"
    existing_tables = schema_editor.connection.introspection.table_names()
    if table_name in existing_tables:
        return

    stored_file = apps.get_model("odoo_app", "StoredFile")
    schema_editor.create_model(stored_file)


def drop_stored_files_table(apps, schema_editor):
    table_name = "stored_files"
    existing_tables = schema_editor.connection.introspection.table_names()
    if table_name not in existing_tables:
        return

    stored_file = apps.get_model("odoo_app", "StoredFile")
    schema_editor.delete_model(stored_file)


class Migration(migrations.Migration):
    dependencies = [
        ("odoo_app", "0003_company_country_id_company_country_name_and_more"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="StoredFile",
                    fields=[
                        ("id", models.BigAutoField(primary_key=True, serialize=False)),
                        ("tenant_id", models.TextField()),
                        ("file_name", models.TextField()),
                        ("stored_filename", models.TextField()),
                        ("file_size", models.BigIntegerField()),
                        ("content_type", models.TextField(blank=True, null=True)),
                        ("storage_path", models.TextField()),
                        ("description", models.TextField(blank=True, null=True)),
                        ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                    ],
                    options={
                        "db_table": "stored_files",
                        "indexes": [
                            models.Index(fields=["tenant_id"], name="idx_stored_files_tenant"),
                            models.Index(fields=["tenant_id", "uploaded_at"], name="idx_stored_files_tenant_ts"),
                        ],
                    },
                ),
            ],
        ),
        migrations.RunPython(create_stored_files_table, drop_stored_files_table),
    ]
