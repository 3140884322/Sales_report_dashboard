from dataclasses import replace
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest

import pandas as pd
from openpyxl import load_workbook


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from analysis import run_pipeline
from confirmed_relationship_plan import (
    approve_relationship,
    build_approved_join_plan,
    execute_approved_join_plan,
    reject_relationship,
)
from generic_relationship_state import clear_generic_report_if_inputs_changed
from generic_report_generation import (
    INVALID_DATE_ACTION_EXCLUDE_MONTHLY,
    build_data_preparation_summary,
    generate_generic_report,
    return_analysis_available,
    run_generic_report_preflight,
)
from generic_table_reader import read_tabular_sources
from multi_table_loader import load_multi_table_dataset
from relationship_discovery import discover_relationships
from standard_field_mapping import (
    generate_unified_orders,
    recommend_standard_field_mappings,
    selections_from_recommendations,
)


DATASET_DIR = PROJECT_DIR / "Global+Electronics+Retailer"


def base_source_frame():
    return pd.DataFrame(
        {
            "Order Number": ["A-1", "A-2", "A-3", "A-4"],
            "Order Date": ["2024-01-01", "2024-01-02", "2024-02-01", "2024-02-02"],
            "CustomerKey": [10, 11, 12, 13],
            "ProductKey": [100, 101, 102, 103],
            "Unit Price": [10.0, 20.0, 30.0, 40.0],
            "Quantity": [1, 2, 3, 4],
        }
    )


def base_mapping_result():
    frame = base_source_frame()
    recommendations = recommend_standard_field_mappings(frame)
    selections = selections_from_recommendations(recommendations, confirmed=True)
    return generate_unified_orders(frame, selections)


def changed_unified(mapping_result, **columns):
    unified = mapping_result.unified_orders.copy(deep=True)
    for column, values in columns.items():
        unified[column] = values
    return replace(mapping_result, unified_orders=unified)


def empty_plan():
    return SimpleNamespace(fact_table="Sales", fact_table_id="Sales", steps=())


class GenericPreflightRuleTests(unittest.TestCase):
    def test_any_invalid_unit_price_blocks_without_explicit_exclusion(self):
        mapping = changed_unified(base_mapping_result(), unit_price=[10, None, 30, 40])

        preflight = run_generic_report_preflight(mapping)

        self.assertFalse(preflight.can_generate)
        self.assertEqual(preflight.excluded_row_count, 0)
        self.assertTrue(any(issue.issue_code == "invalid_price_or_quantity" for issue in preflight.issues))

    def test_any_invalid_quantity_blocks_without_explicit_exclusion(self):
        mapping = changed_unified(base_mapping_result(), quantity=[1, 0, 3, 4])

        preflight = run_generic_report_preflight(mapping)

        self.assertFalse(preflight.can_generate)
        self.assertEqual(preflight.excluded_row_count, 0)

    def test_invalid_order_id_always_blocks(self):
        mapping = changed_unified(base_mapping_result(), order_id=["A-1", None, "A-3", "A-4"])

        preflight = run_generic_report_preflight(mapping)

        self.assertFalse(preflight.can_generate)
        self.assertTrue(any(issue.issue_code == "invalid_order_id" for issue in preflight.issues))

    def test_discount_rate_outside_zero_to_one_blocks(self):
        mapping = changed_unified(base_mapping_result(), discount_rate=[0, 0, 1.2, 0])

        preflight = run_generic_report_preflight(mapping)

        self.assertFalse(preflight.can_generate)
        self.assertTrue(any(issue.issue_code == "invalid_discount_rate" for issue in preflight.issues))

    def test_invalid_date_requires_explicit_continue_decision(self):
        source = base_source_frame()
        source["Order Date"] = ["2024-01-01", "bad-date", "bad-date", "2024-02-02"]
        mapping = generate_unified_orders(
            source,
            selections_from_recommendations(
                recommend_standard_field_mappings(source), confirmed=True
            ),
        )

        blocked = run_generic_report_preflight(mapping)
        continued = run_generic_report_preflight(
            mapping,
            invalid_date_action=INVALID_DATE_ACTION_EXCLUDE_MONTHLY,
        )

        self.assertFalse(blocked.can_generate)
        self.assertEqual(blocked.monthly_analysis_excluded_row_count, 0)
        self.assertTrue(continued.can_generate)
        self.assertTrue(mapping.success)
        self.assertEqual(continued.monthly_analysis_excluded_row_count, 2)
        self.assertEqual(continued.calculation_row_count, 4)

    def test_rows_are_never_silently_excluded(self):
        mapping = changed_unified(base_mapping_result(), quantity=[1, 0, 3, 4])

        blocked = run_generic_report_preflight(mapping)
        excluded = run_generic_report_preflight(
            mapping,
            exclude_invalid_price_quantity_rows=True,
        )

        self.assertEqual(blocked.excluded_row_count, 0)
        self.assertEqual(blocked.calculation_row_count, 4)
        self.assertTrue(excluded.can_generate)
        self.assertEqual(excluded.excluded_row_count, 1)
        self.assertEqual(excluded.calculation_row_count, 3)
        self.assertIn("quantity", excluded.excluded_rows_detail.iloc[0]["exclusion_reason"])

    def test_mapping_availability_records_assumptions_and_unavailable_fields(self):
        mapping = base_mapping_result()
        availability = {
            item.field_name: item for item in mapping.field_availability
        }

        self.assertEqual(availability["discount_rate"].availability_status, "assumed_default")
        self.assertEqual(availability["discount_rate"].default_value, 0.0)
        self.assertTrue(availability["discount_rate"].user_confirmed)
        self.assertEqual(availability["returned"].availability_status, "not_provided")


class SmallGenericReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mapping = base_mapping_result()
        cls.preflight = run_generic_report_preflight(cls.mapping)
        cls.report_without_expenses = generate_generic_report(
            mapping_result=cls.mapping,
            preflight=cls.preflight,
            discovery_result=None,
            plan=empty_plan(),
            decisions={},
        )
        expenses = BytesIO(
            b"expense_id,date,expense_category,amount\n"
            b"E-1,2024-01-15,Marketing,5\n"
            b"E-2,2024-02-15,Rent,7\n"
        )
        expenses.name = "expenses.csv"
        cls.report_with_expenses = generate_generic_report(
            mapping_result=cls.mapping,
            preflight=cls.preflight,
            discovery_result=None,
            plan=empty_plan(),
            decisions={},
            expenses_source=expenses,
        )

    def test_returned_not_provided_is_not_a_zero_percent_claim(self):
        tables = self.report_without_expenses["report_tables"]

        self.assertFalse(return_analysis_available(tables))
        self.assertTrue(tables["monthly_summary"]["return_rate"].isna().all())
        self.assertFalse(
            (tables["anomalies"]["anomaly_type"] == "return_rate_over_15_percent").any()
        )
        returned_check = tables["post_conversion_data_quality"].loc[
            tables["post_conversion_data_quality"]["check_name"]
            == "invalid_returned_count"
        ].iloc[0]
        self.assertEqual(returned_check["status"], "not_applicable")
        self.assertEqual(int(returned_check["issue_count"]), 0)

    def test_return_chart_availability_gate_is_false(self):
        self.assertFalse(
            return_analysis_available(self.report_without_expenses["report_tables"])
        )

    def test_markdown_marks_return_analysis_not_available(self):
        summary = self.report_without_expenses["summary_text"]

        self.assertIn("Return Analysis: Not Available", summary)
        self.assertIn("Return data was not provided", summary)
        self.assertNotIn("0.0% return", summary)
        self.assertNotIn("treated as not returned", summary)

    def test_no_expenses_skips_finance_module(self):
        finance_status = self.report_without_expenses["report_tables"]["finance_status"]
        status = finance_status.loc[
            finance_status["metric"] == "finance_module_status", "value"
        ].iloc[0]
        self.assertEqual(status, "skipped")

    def test_optional_expenses_generates_finance_module(self):
        tables = self.report_with_expenses["report_tables"]
        status = tables["finance_status"].loc[
            tables["finance_status"]["metric"] == "finance_module_status", "value"
        ].iloc[0]

        self.assertEqual(status, "passed")
        self.assertFalse(tables["cash_flow_summary"].empty)

    def test_excel_and_markdown_download_payloads_are_created(self):
        report = self.report_without_expenses

        self.assertGreater(len(report["excel_bytes"]), 1_000)
        self.assertTrue(report["summary_text"].startswith("# Sales Reporting Summary"))
        workbook = load_workbook(BytesIO(report["excel_bytes"]), read_only=True)
        try:
            self.assertIn("data_preparation_summary", workbook.sheetnames)
            self.assertIn("field_availability", workbook.sheetnames)
            self.assertIn("excluded_rows_detail", workbook.sheetnames)
        finally:
            workbook.close()

    def test_session_signature_prevents_duplicate_generation(self):
        cached_result = object()
        signature = ("mapping", "expenses")
        state = {
            "generic_report_signature": signature,
            "generic_report_result": cached_result,
        }

        unchanged = clear_generic_report_if_inputs_changed(state, signature)
        changed = clear_generic_report_if_inputs_changed(state, ("new",))

        self.assertFalse(unchanged)
        self.assertTrue(changed)
        self.assertNotIn("generic_report_result", state)


class MavenGenericEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        paths = [
            DATASET_DIR / "Sales.csv",
            DATASET_DIR / "Products.csv",
            DATASET_DIR / "Customers.csv",
            DATASET_DIR / "Stores.csv",
            DATASET_DIR / "Exchange_Rates.csv",
        ]
        cls.discovery = discover_relationships(read_tabular_sources(paths))
        approved = []
        cls.delivery_candidate = None
        expected_keys = {
            "Products": "ProductKey",
            "Customers": "CustomerKey",
            "Stores": "StoreKey",
        }
        for candidate in cls.discovery.relationships:
            mapping = dict(zip(candidate.left_columns, candidate.right_columns))
            known_dimension = (
                candidate.right_table in expected_keys
                and candidate.left_columns == (expected_keys[candidate.right_table],)
            )
            known_exchange = (
                candidate.right_table == "Exchange_Rates"
                and mapping == {"Currency Code": "Currency", "Order Date": "Date"}
            )
            if (known_dimension or known_exchange) and not candidate.blocked:
                approved.append(approve_relationship(candidate))
            elif "Delivery Date" in candidate.left_columns:
                cls.delivery_candidate = candidate
        cls.decisions = {
            item.original_candidate_id: item for item in approved
        }
        if cls.delivery_candidate is not None:
            rejected = reject_relationship(cls.delivery_candidate)
            cls.decisions[rejected.original_candidate_id] = rejected
        cls.plan = build_approved_join_plan(cls.discovery, "Sales", cls.decisions)
        cls.merge_result = execute_approved_join_plan(cls.discovery, cls.plan)
        recommendations = recommend_standard_field_mappings(
            cls.merge_result.merged_frame
        )
        selections = selections_from_recommendations(
            recommendations, confirmed=True
        )
        cls.mapping_result = generate_unified_orders(
            cls.merge_result.merged_frame, selections
        )
        cls.preflight = run_generic_report_preflight(
            cls.mapping_result,
            original_fact_row_count=cls.merge_result.fact_row_count,
            merged_row_count=cls.merge_result.final_row_count,
        )
        cls.report = generate_generic_report(
            mapping_result=cls.mapping_result,
            preflight=cls.preflight,
            discovery_result=cls.discovery,
            plan=cls.plan,
            decisions=cls.decisions,
        )

    def test_maven_generic_mode_generates_end_to_end_report(self):
        self.assertTrue(self.preflight.can_generate)
        self.assertIn(self.report["status"], {"ready", "review_required"})
        self.assertGreater(len(self.report["excel_bytes"]), 100_000)

    def test_maven_enriched_orders_preserves_62884_rows(self):
        enriched = self.report["report_tables"]["enriched_orders"]
        self.assertEqual(len(enriched), 62884)

    def test_confirmed_discount_default_enters_report(self):
        enriched = self.report["report_tables"]["enriched_orders"]
        self.assertTrue(enriched["discount_rate"].eq(0).all())
        availability = self.report["field_availability"]
        status = availability.loc[
            availability["field_name"] == "discount_rate", "availability_status"
        ].iloc[0]
        self.assertEqual(status, "assumed_default")

    def test_return_unavailable_is_blank_in_excel(self):
        workbook = load_workbook(BytesIO(self.report["excel_bytes"]), read_only=True)
        try:
            worksheet = workbook["monthly_summary"]
            headers = [cell.value for cell in next(worksheet.iter_rows(min_row=1, max_row=1))]
            return_column = headers.index("return_rate") + 1
            values = [
                row[0].value
                for row in worksheet.iter_rows(
                    min_row=2,
                    min_col=return_column,
                    max_col=return_column,
                )
            ]
            self.assertTrue(values)
            self.assertTrue(all(value is None for value in values))
        finally:
            workbook.close()

    def test_data_preparation_summary_records_relationships_and_rows(self):
        summary = self.report["data_preparation_summary"]
        approved_rows = summary[summary["section"] == "approved_relationship"]
        rejected_rows = summary[summary["section"] == "rejected_relationship"]
        final_rows = summary.loc[
            summary["item"] == "final_calculation_rows", "value"
        ].iloc[0]

        self.assertEqual(len(approved_rows), 4)
        self.assertGreaterEqual(len(rejected_rows), 1)
        self.assertEqual(int(final_rows), 62884)

    def test_maven_multi_table_mode_still_loads(self):
        result = load_multi_table_dataset(
            DATASET_DIR / "Sales.csv",
            DATASET_DIR / "Products.csv",
            DATASET_DIR / "Customers.csv",
            DATASET_DIR / "Stores.csv",
            DATASET_DIR / "Exchange_Rates.csv",
        )
        self.assertEqual(len(result["unified_orders"]), 62884)


class ExistingModeCompatibilityTests(unittest.TestCase):
    def test_single_table_pipeline_still_generates_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            tables, excel_path, summary_path = run_pipeline(
                PROJECT_DIR / "input" / "sample_orders.csv",
                PROJECT_DIR / "input" / "sample_expenses.csv",
                temp / "single.xlsx",
                temp / "single.md",
            )

            self.assertFalse(tables["enriched_orders"].empty)
            self.assertTrue(excel_path.exists())
            self.assertTrue(summary_path.exists())


if __name__ == "__main__":
    unittest.main()
