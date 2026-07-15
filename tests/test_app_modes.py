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
        self.assertEqual([item.value for item in app.title], ["销售数据分析报告"])
        self.assertEqual(len(app.radio), 0)
        self.assertEqual(app.selectbox[0].label, "语言 / Language")
        self.assertEqual(app.selectbox[0].value, "zh")
        self.assertEqual(
            [item.label for item in app.get("file_uploader")],
            ["销售数据文件"],
        )
        page_text = " ".join(item.value for item in app.markdown)
        self.assertIn("上传一张或多张", page_text)
        for removed_label in (
            "Single Table Mode",
            "Multi-Table Dataset Mode",
            "Generic Relationship Mode",
        ):
            self.assertNotIn(removed_label, page_text)

        app.selectbox[0].select("en").run(timeout=10)
        self.assertFalse(app.exception)
        self.assertEqual([item.value for item in app.title], ["Sales Data Analysis Report"])
        self.assertEqual(
            [item.label for item in app.get("file_uploader")],
            ["Sales data files"],
        )

    def test_one_csv_skips_relationship_ui_and_opens_mapping(self):
        app = AppTest.from_file(str(PROJECT_DIR / "app.py")).run(timeout=10)
        app.selectbox[0].select("en").run(timeout=10)
        app.get("file_uploader")[0].upload(
            "coffee.csv", COFFEE_CSV, "text/csv"
        ).run(timeout=20)

        self.assertFalse(app.exception)
        self.assertIn(
            "One table was detected. It was selected automatically as the main "
            "transaction table. Relationship review and table merging are not "
            "required; continue to field mapping.",
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
        mapping_sections = [item.value for item in app.markdown]
        self.assertIn("#### Required transaction fields", mapping_sections)
        self.assertIn("#### Optional analysis fields", mapping_sections)
        self.assertIn("#### Business assumptions", mapping_sections)
        returned_mapping = next(
            item
            for item in app.selectbox
            if item.label == "Mapping for returned (Returned)"
        )
        discount_mapping = next(
            item
            for item in app.selectbox
            if item.label == "Mapping for discount_rate (Discount Rate)"
        )
        mapping_labels = {item.label for item in app.selectbox}
        self.assertIn("Mapping for store_id (Store ID)", mapping_labels)
        self.assertIn("Mapping for store_name (Store Name)", mapping_labels)
        self.assertIn("Not applicable to this business", returned_mapping.options)
        self.assertNotIn("Not mapped", returned_mapping.options)
        self.assertIn(
            "Default 0 (explicit business assumption)",
            discount_mapping.options,
        )
        self.assertNotIn("Not mapped", discount_mapping.options)
        generate_mapping = next(
            item
            for item in app.button
            if item.label == "Validate and Generate Unified Orders Preview"
        )
        self.assertTrue(generate_mapping.disabled)
        self.assertIn(
            "Complete all required mappings, resolve duplicate source-column use, "
            "and confirm active choices before continuing.",
            [item.value for item in app.warning],
        )

    def test_language_switch_keeps_uploaded_and_mapping_state(self):
        app = AppTest.from_file(str(PROJECT_DIR / "app.py")).run(timeout=10)
        app.get("file_uploader")[0].upload(
            "coffee.csv", COFFEE_CSV, "text/csv"
        ).run(timeout=20)
        before_keys = {
            key
            for key in app.session_state.filtered_state
            if key.startswith("generic_")
        }
        before_signature = app.session_state["generic_upload_signature"]
        before_choice = app.session_state["generic_mapping_choice_order_id"]

        app.selectbox[0].select("en").run(timeout=20)

        self.assertFalse(app.exception)
        after_keys = {
            key
            for key in app.session_state.filtered_state
            if key.startswith("generic_")
        }
        self.assertEqual(before_keys, after_keys)
        self.assertEqual(
            app.session_state["generic_upload_signature"], before_signature
        )
        self.assertEqual(
            app.session_state["generic_mapping_choice_order_id"], before_choice
        )
        self.assertIsNotNone(app.session_state["generic_discovery_result"])

    def test_multi_sheet_workbook_enters_relationship_flow(self):
        app = AppTest.from_file(str(PROJECT_DIR / "app.py")).run(timeout=10)
        app.selectbox[0].select("en").run(timeout=10)
        app.get("file_uploader")[0].upload(
            "sales.xlsx",
            multi_sheet_workbook(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ).run(timeout=20)

        self.assertFalse(app.exception)
        subheaders = [item.value for item in app.subheader]
        self.assertIn("Select main transaction table", subheaders)
        self.assertIn("Review table relationships", subheaders)
        self.assertNotIn("Standard Field Mapping", subheaders)
        buttons = {item.label: item for item in app.button}
        self.assertTrue(buttons["Build Approved Join Plan"].disabled)
        self.assertTrue(buttons["Execute Safe Merge"].disabled)
        warnings = [item.value for item in app.warning]
        self.assertIn("Select the main transaction table first.", warnings)
        self.assertIn("Build a valid approved join plan before merging.", warnings)


if __name__ == "__main__":
    unittest.main()
