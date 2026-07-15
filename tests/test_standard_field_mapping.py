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
    BUSINESS_ASSUMPTION_FIELDS,
    OPTIONAL_ANALYSIS_FIELDS,
    REQUIRED_STANDARD_FIELDS,
    RETURN_NOT_APPLICABLE_MESSAGE,
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
        availability = next(
            item
            for item in self.result.field_availability
            if item.field_name == "returned"
        )
        self.assertEqual(availability.availability_status, "provided")

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

    def test_returned_not_applicable_remains_missing_without_warning(self):
        selections = replace_selection(
            confirmed_recommendations(self.frame),
            "returned",
            strategy="not_applicable",
            source_column=None,
            confirmed=True,
        )

        result = generate_unified_orders(self.frame, selections)
        returned = result.unified_orders["returned"]
        availability = next(
            item
            for item in result.field_availability
            if item.field_name == "returned"
        )

        self.assertTrue(result.success, result.errors)
        self.assertTrue(returned.isna().all())
        self.assertEqual(availability.availability_status, "not_applicable")
        self.assertEqual(availability.notes, RETURN_NOT_APPLICABLE_MESSAGE)
        self.assertFalse(
            any("Return data was not provided" in warning for warning in result.warnings)
        )

    def test_unified_orders_contains_all_analysis_required_columns(self):
        self.assertEqual(
            ("order_id", "date", "product_id", "unit_price", "quantity"),
            REQUIRED_STANDARD_FIELDS,
        )
        self.assertIn("returned", OPTIONAL_ANALYSIS_FIELDS)
        self.assertIn("discount_rate", BUSINESS_ASSUMPTION_FIELDS)
        self.assertTrue(set(REQUIRED_COLUMNS).issubset(self.result.unified_orders.columns))

    def test_missing_customer_id_remains_unknown_without_temporary_values(self):
        frame = standard_source_frame().drop(columns=["CustomerKey"])
        result = generate_unified_orders(frame, confirmed_recommendations(frame))

        self.assertTrue(result.success, result.errors)
        self.assertTrue(result.unified_orders["customer_id"].isna().all())
        availability = next(
            item
            for item in result.field_availability
            if item.field_name == "customer_id"
        )
        self.assertEqual(availability.availability_status, "not_provided")
        self.assertTrue(
            any("Customer analysis was skipped" in item for item in result.warnings)
        )

    def test_partially_missing_customer_id_is_recorded(self):
        frame = standard_source_frame()
        frame.loc[1, "CustomerKey"] = None

        result = generate_unified_orders(frame, confirmed_recommendations(frame))

        self.assertTrue(result.success, result.errors)
        availability = next(
            item
            for item in result.field_availability
            if item.field_name == "customer_id"
        )
        self.assertEqual(availability.availability_status, "partially_provided")
        self.assertEqual(availability.provided_row_count, 3)
        self.assertEqual(availability.total_row_count, 4)
        self.assertEqual(result.unified_orders["customer_id"].isna().sum(), 1)

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


class CustomerAvailabilityBoundaryTests(unittest.TestCase):
    def _map(self, customer_values=None, *, include_customer=True):
        frame = standard_source_frame()
        if include_customer:
            frame["CustomerKey"] = customer_values
        else:
            frame = frame.drop(columns=["CustomerKey"])
        return generate_unified_orders(frame, confirmed_recommendations(frame))

    def _availability(self, result):
        return next(
            item
            for item in result.field_availability
            if item.field_name == "customer_id"
        )

    def test_missing_customer_column_is_not_provided(self):
        frame = standard_source_frame().drop(columns=["CustomerKey"])
        selections = confirmed_recommendations(frame)
        selections = replace_selection(
            selections,
            "customer_id",
            strategy="omit",
            source_column=None,
            confirmed=True,
        )
        result = generate_unified_orders(frame, selections)

        availability = self._availability(result)
        self.assertTrue(result.success, result.errors)
        self.assertNotIn("customer_id", result.unified_orders.columns)
        self.assertEqual(availability.availability_status, "not_provided")
        self.assertEqual(availability.provided_row_count, 0)
        self.assertEqual(availability.total_row_count, 4)

    def test_all_na_customer_values_are_not_provided(self):
        result = self._map([None, pd.NA, None, pd.NA])

        availability = self._availability(result)
        self.assertEqual(availability.availability_status, "not_provided")
        self.assertEqual(availability.provided_row_count, 0)

    def test_empty_and_whitespace_customer_values_are_not_provided(self):
        result = self._map(["", " ", "   ", "\t"])

        availability = self._availability(result)
        self.assertEqual(availability.availability_status, "not_provided")
        self.assertEqual(availability.provided_row_count, 0)
        self.assertTrue(result.unified_orders["customer_id"].isna().all())

    def test_partially_empty_customer_values_are_partially_provided(self):
        result = self._map(["C-1", "", "  ", None])

        availability = self._availability(result)
        self.assertEqual(availability.availability_status, "partially_provided")
        self.assertEqual(availability.provided_row_count, 1)
        self.assertEqual(availability.total_row_count, 4)
        self.assertIn("1 / 4 valid rows", availability.notes)

    def test_all_non_empty_customer_values_are_provided(self):
        result = self._map(["C-1", "C-2", "C-3", "C-4"])

        availability = self._availability(result)
        self.assertEqual(availability.availability_status, "provided")
        self.assertEqual(availability.provided_row_count, 4)
        self.assertEqual(availability.total_row_count, 4)

    def test_customer_name_is_not_used_as_customer_id(self):
        frame = standard_source_frame().drop(columns=["CustomerKey"])
        frame["Customer Name"] = ["Alice", "Bob", "Alice", "Carol"]
        recommendations = recommend_standard_field_mappings(frame)
        recommended = {
            item.standard_field: (
                item.recommended_strategy,
                item.recommended_source,
            )
            for item in recommendations
        }

        result = generate_unified_orders(
            frame,
            selections_from_recommendations(recommendations, confirmed=True),
        )

        self.assertEqual(recommended["customer_id"], ("not_provided", None))
        self.assertEqual(recommended["customer_name"], ("source", "Customer Name"))
        self.assertTrue(result.unified_orders["customer_id"].isna().all())
        self.assertEqual(
            result.unified_orders["customer_name"].tolist(),
            ["Alice", "Bob", "Alice", "Carol"],
        )


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
