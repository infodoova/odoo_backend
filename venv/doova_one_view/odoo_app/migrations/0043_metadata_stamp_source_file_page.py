from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('odoo_app', '0042_accountmoveline_full_reconcile_id'),
    ]

    operations = [
        # 1. Add page_count to stored_files (how many pages the PDF has)
        migrations.AddField(
            model_name='storedfile',
            name='page_count',
            field=models.IntegerField(null=True, blank=True,
                                      help_text='Total page count for PDF files.'),
        ),
        # 2. Add source stamp columns to fact_account_move_lines
        #    Every transaction extracted from a PDF carries the file name + page number.
        migrations.RunSQL(
            sql="""
                ALTER TABLE fact_account_move_lines
                  ADD COLUMN IF NOT EXISTS source_file_name   TEXT,
                  ADD COLUMN IF NOT EXISTS source_page_number INTEGER;

                CREATE INDEX IF NOT EXISTS idx_faml_source_file
                  ON fact_account_move_lines (source_file_name)
                  WHERE source_file_name IS NOT NULL;
            """,
            reverse_sql="""
                ALTER TABLE fact_account_move_lines
                  DROP COLUMN IF EXISTS source_file_name,
                  DROP COLUMN IF EXISTS source_page_number;
            """,
        ),
        # 3. Add source stamp to fact_account_moves as well (move-level stamp)
        migrations.RunSQL(
            sql="""
                ALTER TABLE fact_account_moves
                  ADD COLUMN IF NOT EXISTS source_file_name   TEXT,
                  ADD COLUMN IF NOT EXISTS source_page_number INTEGER;
            """,
            reverse_sql="""
                ALTER TABLE fact_account_moves
                  DROP COLUMN IF EXISTS source_file_name,
                  DROP COLUMN IF EXISTS source_page_number;
            """,
        ),
    ]
