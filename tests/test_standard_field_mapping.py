from dataclasses import replace
from pathlib import Path
import sys
import unittest

import pandas as pd
from pandas.testing import assert_frame_equal


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from analysis import REQUIRED_COLUMNS
from confirmed_relationship_plan import (
    approve_relationship,
    build_approved_join_plan,
    execute_approved_join_plan,
)
from generic_table_reader import read_tabular_sources
from relationship_discovery import discover_relationships
from standard_field_mapping import (
    REQUIRED_STANDARD_FIELDS,
    generate_unified_orders,
    recommend_standard_field_mappings,
    selections_from_recommendations,
)


DATASET_DIR = PROJECT_DIR / "Global+Electronics+Retailer"


def standard_source_frame():
    return pd.DataFrame(
        {
            "Order Number": ["A-1", "A-2", "A-3", "A-4"],
            "Order Date": ["2024-01-01", "2024/01/02", "Jan 3 2024", "2024-01-04"],
            "CustomerKey": [10, 11, 12, 13],
            "ProductKey": [100, 101, 102, 103],
            "Unit Price": ["$1,299.50", "EUR 20.25", "30", "40.00"],
            "Quantity": ["1", "2 units", "3", "4"],
            "Discount Rate": ["10%", "0", "0.25", "5%"],
            "Returned": ["yes", "0", "退货", "未退货"],
        }
    )


def confirmed_recommendations(frame):
    return list(
        selections_from_recommendations(
            recommend_standard_field_mappings(frame), confirmed=True
        )
    )


def replace_selection(selections, standard_field, **changes):
    return [
        replace(selection, **changes)
        if selection.standard_field == standard_field
        else selection
        for selection in selections
    ]


class StandardFieldRecommendationTests(unittest.TestCase):
    def test_recommendations_are_not_confirmed_by_default(self):
        frame = standard_source_frame()

        selections = selections_from_recommendations(
            recommend_standard_field_mappings(frame)
        )

        self.assertTrue(all(not selection.confirmed for selection in selections))
        result = generate_unified_orders(frame, selections)
        self.assertFalse(result.success)
        self.assertTrue(any("not confirmed" in error for error in result.errors))

    def test_user_can_override_recommended_source(self):
        frame = standard_source_frame()
        frame["Backup Price"] = ["1.25", "2.50", "3.75", "4.00"]
        selections = confirmed_recommendations(frame)
        selections = replace_selection(
            selections,
            "unit_price",
            strategy="source",
            source_column="Backup Price",
            confirmed=True,
        )

        result = generate_unified_orders(frame, selections)

        self.assertTrue(result.success, result.errors)
        self.assertEqual(result.unified_orders["unit_price"].tolist(), [1.25, 2.5, 3.75, 4.0])

    def test_duplicate_source_mapping_is_rejected(self):
        frame = standard_source_frame()
        selections = confirmed_recommendations(frame)
        selections = replace_selection(
            selections,
            "customer_id",
            strategy="source",
            source_column="Order Number",
            confirmed=True,
        )

        result = generate_unified_orders(frame, selections)

        self.assertFalse(result.success)
        self.assertTrue(any("mapped to both" in error for error in result.errors))

    def test_missing_required_field_is_rejected(self):
        frame = standard_source_frame()
        selections = confirmed_recommendations(frame)
        selections = replace_selection(
            selections,
            "product_id",
            strategy="unmapped",
            source_column=None,
            confirmed=False,
        )

        result = generate_unified_orders(frame, selections)

        self.assertFalse(result.success)
        self.assertTrue(any("product_id" in error for error in result.errors))


class StandardFieldConversionTests(unittest.TestCase):
    def setUp(self):
        self.frame = standard_source_frame()
        self.original = self.frame.copy(deep=True)
        self.result = generate_unified_orders(
            self.frame, confirmed_recommendations(self.frame)
        )

    def tearDown(self):
        assert_frame_equal(self.frame, self.original)

    def test_money_strings_are_converted(self):
        self.assertTrue(self.result.success, self.result.errors)
        self.assertEqual(
            self.result.unified_orders["unit_price"].tolist(),
            [1299.5, 20.25, 30.0, 40.0],
        )

    def test_dates_are_converted(self):
        self.assertTrue(self.result.success, self.result.errors)
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(self.result.unified_orders["date"]))
        self.assertEqual(self.result.unified_orders["date"].isna().sum(), 0)

    def test_quantities_are_converted(self):
        self.assertTrue(self.result.success, self.result.errors)
        self.assertEqual(
            self.result.unified_orders["quantity"].tolist(),
            [1.0, 2.0, 3.0, 4.0],
        )

    def test_returned_values_are_converted_to_nullable_boolean(self):
        self.assertTrue(self.result.success, self.result.errors)
        returned = self.result.unified_orders["returned"]
        self.assertEqual(str(returned.dtype), "boolean")
        self.assertEqual(returned.tolist(), [True, False, True, False])

    def test_severe_conversion_failure_blocks_output(self):
        frame = standard_source_frame()
        frame["Quantity"] = ["bad", "bad", "3", "4"]

        result = generate_unified_orders(frame, confirmed_recommendations(frame))

        self.assertFalse(result.success)
        self.assertIsNone(result.unified_orders)
        self.assertTrue(any("quantity conversion failed" in error for error in result.errors))


class MissingFieldStrategyTests(unittest.TestCase):
    def setUp(self):
        self.frame = standard_source_frame().drop(
            columns=["Discount Rate", "Returned"]
        )
        self.result = generate_unified_orders(
            self.frame, confirmed_recommendations(self.frame)
        )

    def test_discount_rate_explicit_default_is_zero(self):
        self.assertTrue(self.result.success, self.result.errors)
        self.assertEqual(self.result.unified_orders["discount_rate"].tolist(), [0.0] * 4)
        diagnostic = next(
            item for item in self.result.diagnostics if item.standard_field == "discount_rate"
        )
        self.assertEqual(diagnostic.status, "confirmed_default")

    def test_returned_not_provided_remains_missing(self):
        self.assertTrue(self.result.success, self.result.errors)
        returned = self.result.unified_orders["returned"]
        self.assertEqual(str(returned.dtype), "boolean")
        self.assertTrue(returned.isna().all())
        diagnostic = next(
            item for item in self.result.diagnostics if item.standard_field == "returned"
        )
        self.assertEqual(diagnostic.status, "not_provided")

    def test_unified_orders_contains_all_analysis_required_columns(self):
        self.assertEqual(tuple(REQUIRED_COLUMNS), REQUIRED_STANDARD_FIELDS)
        self.assertTrue(set(REQUIRED_COLUMNS).issubset(self.result.unified_orders.columns))

    def test_missing_customer_id_can_use_temporary_order_level_values(self):
        frame = standard_source_frame().drop(columns=["CustomerKey"])
        result = generate_unified_orders(frame, confirmed_recommendations(frame))

        self.assertTrue(result.success, result.errors)
        self.assertEqual(
            result.unified_orders["customer_id"].tolist(),
            [
                "TEMP-CUSTOMER-ORDER-A-1",
                "TEMP-CUSTOMER-ORDER-A-2",
                "TEMP-CUSTOMER-ORDER-A-3",
                "TEMP-CUSTOMER-ORDER-A-4",
            ],
        )
        self.assertTrue(any("cannot identify customers" in item for item in result.warnings))

    def test_only_explicit_extension_columns_are_retained(self):
        frame = standard_source_frame()
        frame["Audit Note"] = ["a", "b", "c", "d"]
        selections = confirmed_recommendations(frame)

        default_result = generate_unified_orders(frame, selections)
        extended_result = generate_unified_orders(
            frame, selections, selected_extension_columns=["Audit Note"]
        )

        self.assertNotIn("Audit Note", default_result.unified_orders.columns)
        self.assertIn("Audit Note", extended_result.unified_orders.columns)


class MavenStandardFieldMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        paths = [
            DATASET_DIR / "Sales.csv",
            DATASET_DIR / "Products.csv",
            DATASET_DIR / "Customers.csv",
            DATASET_DIR / "Stores.csv",
            DATASET_DIR / "Exchange_Rates.csv",
        ]
        discovery = discover_relationships(read_tabular_sources(paths))
        approved = []
        expected_keys = {
            "Products": "ProductKey",
            "Customers": "CustomerKey",
            "Stores": "StoreKey",
        }
        for candidate in discovery.relationships:
            mapping = dict(zip(candidate.left_columns, candidate.right_columns))
            known_dimension = (
                candidate.right_table in expected_keys
                and candidate.left_columns == (expected_keys[candidate.right_table],)
            )
            known_exchange = (
                candidate.right_table == "Exchange_Rates"
                and mapping
                == {"Currency Code": "Currency", "Order Date": "Date"}
            )
            if (known_dimension or known_exchange) and not candidate.blocked:
                approved.append(approve_relationship(candidate))
        plan = build_approved_join_plan(discovery, "Sales", approved)
        cls.merge_result = execute_approved_join_plan(discovery, plan)
        cls.recommendations = recommend_standard_field_mappings(
            cls.merge_result.merged_frame
        )
        selections = selections_from_recommendations(
            cls.recommendations, confirmed=True
        )
        cls.mapping_result = generate_unified_orders(
            cls.merge_result.merged_frame, selections
        )

    def test_maven_standard_fields_are_recommended(self):
        recommended = {
            item.standard_field: (item.recommended_strategy, item.recommended_source)
            for item in self.recommendations
        }
        self.assertEqual(recommended["order_id"], ("source", "Order Number"))
        self.assertEqual(recommended["date"], ("source", "Order Date"))
        self.assertEqual(recommended["customer_id"], ("source", "CustomerKey"))
        self.assertEqual(recommended["product_id"], ("source", "ProductKey"))
        self.assertEqual(
            recommended["unit_price"], ("source", "Products.Unit Price USD")
        )
        self.assertEqual(recommended["quantity"], ("source", "Quantity"))
        self.assertEqual(recommended["discount_rate"], ("default_zero", None))
        self.assertEqual(recommended["returned"], ("not_provided", None))

    def test_maven_unified_orders_preserves_62884_rows(self):
        self.assertTrue(self.mapping_result.success, self.mapping_result.errors)
        self.assertEqual(self.mapping_result.source_row_count, 62884)
        self.assertEqual(self.mapping_result.output_row_count, 62884)
        self.assertEqual(len(self.mapping_result.unified_orders), 62884)
        self.assertTrue(
            set(REQUIRED_COLUMNS).issubset(self.mapping_result.unified_orders.columns)
        )


if __name__ == "__main__":
    unittest.main()
