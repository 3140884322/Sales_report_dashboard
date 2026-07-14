from io import BytesIO
from pathlib import Path
import sys
import unittest

import pandas as pd
from streamlit.testing.v1 import AppTest


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))


COFFEE_CSV = (
    b"transaction_id,transaction_date,transaction_qty,product_id,unit_price,product_category,product_type\n"
    b"1,2024-01-01,2,P1,3.50,Coffee,Gourmet brewed coffee\n"
    b"2,2024-01-02,1,P2,4.00,Tea,Brewed Chai tea\n"
)


def multi_sheet_workbook():
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(
            {
                "Order ID": [1, 2],
                "Order Date": ["2024-01-01", "2024-01-02"],
                "Product ID": ["P1", "P2"],
                "Unit Price": [3.5, 4.0],
                "Quantity": [2, 1],
            }
        ).to_excel(writer, sheet_name="Orders", index=False)
        pd.DataFrame(
            {
                "Product ID": ["P1", "P2"],
                "Product Name": ["Coffee", "Tea"],
                "Category": ["Beverages", "Beverages"],
            }
        ).to_excel(writer, sheet_name="Products", index=False)
    return output.getvalue()


class UnifiedUploadPageTests(unittest.TestCase):
    def test_page_has_one_upload_entry_and_no_mode_selector(self):
        app = AppTest.from_file(str(PROJECT_DIR / "app.py")).run(timeout=10)

        self.assertFalse(app.exception)
        self.assertEqual([item.value for item in app.title], ["Upload Sales Data"])
        self.assertEqual(len(app.radio), 0)
        self.assertEqual(
            [item.label for item in app.get("file_uploader")],
            ["Sales data files"],
        )
        page_text = " ".join(item.value for item in app.markdown)
        self.assertIn("Upload one or more CSV/XLSX files", page_text)
        for removed_label in (
            "Single Table Mode",
            "Multi-Table Dataset Mode",
            "Generic Relationship Mode",
        ):
            self.assertNotIn(removed_label, page_text)

    def test_one_csv_skips_relationship_ui_and_opens_mapping(self):
        app = AppTest.from_file(str(PROJECT_DIR / "app.py")).run(timeout=10)
        app.get("file_uploader")[0].upload(
            "coffee.csv", COFFEE_CSV, "text/csv"
        ).run(timeout=20)

        self.assertFalse(app.exception)
        self.assertIn(
            "One table was detected. No table relationships are required. "
            "Continue to field mapping.",
            [item.value for item in app.info],
        )
        subheaders = [item.value for item in app.subheader]
        self.assertIn("Standard Field Mapping", subheaders)
        self.assertNotIn("Select Main Transaction Table", subheaders)
        self.assertNotIn("Review Relationship Candidates", subheaders)
        metrics = {item.label: item.value for item in app.metric}
        self.assertEqual(metrics["Main transaction table"], "coffee")
        self.assertEqual(metrics["Rows"], "2")
        self.assertEqual(metrics["Confirmed relationships"], "0")

    def test_multi_sheet_workbook_enters_relationship_flow(self):
        app = AppTest.from_file(str(PROJECT_DIR / "app.py")).run(timeout=10)
        app.get("file_uploader")[0].upload(
            "sales.xlsx",
            multi_sheet_workbook(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ).run(timeout=20)

        self.assertFalse(app.exception)
        subheaders = [item.value for item in app.subheader]
        self.assertIn("Select Main Transaction Table", subheaders)
        self.assertIn("Review Relationship Candidates", subheaders)
        self.assertNotIn("Standard Field Mapping", subheaders)


if __name__ == "__main__":
    unittest.main()
