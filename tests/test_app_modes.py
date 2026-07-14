from pathlib import Path
import sys
import unittest

from streamlit.testing.v1 import AppTest


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))


class StreamlitModeTests(unittest.TestCase):
    def test_page_exposes_only_single_and_multi_table_modes(self):
        app = AppTest.from_file(str(PROJECT_DIR / "app.py")).run(timeout=10)

        self.assertFalse(app.exception)
        self.assertEqual(len(app.radio), 1)
        self.assertEqual(
            app.radio[0].options,
            ["Single Table Mode", "Multi-Table Dataset Mode"],
        )
        self.assertEqual(
            app.caption[0].value,
            "Upload one table that already contains the sales transaction fields.",
        )

    def test_multi_table_mode_routes_to_relationship_discovery(self):
        app = AppTest.from_file(str(PROJECT_DIR / "app.py")).run(timeout=10)
        app.radio[0].set_value("Multi-Table Dataset Mode").run(timeout=10)

        self.assertFalse(app.exception)
        self.assertEqual(
            app.caption[0].value,
            "Upload multiple related sales, order, product, customer, store, or "
            "other business tables. The system will help identify their "
            "relationships and safely combine them.",
        )
        self.assertEqual([item.value for item in app.subheader], ["Step 1: Upload Tables"])
        self.assertEqual(
            [item.label for item in app.get("file_uploader")],
            ["CSV or xlsx files"],
        )
        self.assertEqual([item.label for item in app.button], ["Discover Relationships"])


if __name__ == "__main__":
    unittest.main()
