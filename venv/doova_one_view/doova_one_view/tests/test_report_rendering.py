# doova_one_view/tests/test_report_rendering.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

from pathlib import Path
from django.test import TestCase
from unittest.mock import patch
from doova_one_view.api.agent.tools_refactored.reporting_v2 import generate_report_tool


class TestReportRendering(TestCase):

    def test_pdf_generation_with_toc_and_kpi_cards(self):
        sample_markdown = """
## Revenue Analysis
The revenue performance was strong across all quarters.

## Executive Takeaways
- Revenue increased 15% YoY.
- Operating margins remained healthy at 22%.

```chart
{
  "chart_type": "bar",
  "title": "Quarterly Revenue",
  "labels": ["Q1", "Q2", "Q3", "Q4"],
  "values": [120000, 150000, 180000, 210000]
}
```

## Risk Factors
- Supply chain delays in international regions.
"""
        with patch("doova_one_view.api.agent.tools_refactored.reporting_v2.get_sales_summary_tool") as mock_sales, \
             patch("doova_one_view.api.agent.tools_refactored.reporting_v2.get_business_health_score_tool") as mock_health, \
             patch("doova_one_view.api.agent.tools_refactored.reporting_v2.calculate_pnl_tool") as mock_pnl:

            mock_sales.return_value = {"total_revenue": 660000}
            mock_health.return_value = {"business_health_score": 85}
            mock_pnl.return_value = {"ebit": 145000}

            result = generate_report_tool(
                tenant_id="test_tenant_phase3",
                custom_content=sample_markdown,
                base_currency="USD",
            )

            self.assertIn("filename", result)
            filename = result["filename"]

            from django.conf import settings
            reports_dir = Path(getattr(settings, "REPORTS_DIR", Path("reports")))
            pdf_path = reports_dir / filename

            self.assertTrue(pdf_path.exists())
            self.assertGreater(pdf_path.stat().st_size, 1000)

            # Cleanup
            if pdf_path.exists():
                pdf_path.unlink()


if __name__ == "__main__":
    import unittest
    unittest.main()
