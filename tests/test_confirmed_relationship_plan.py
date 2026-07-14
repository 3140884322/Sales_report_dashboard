from io import BytesIO
from pathlib import Path
import sys
import unittest

import pandas as pd
from pandas.testing import assert_frame_equal


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from confirmed_relationship_plan import (
    JoinPlanValidationError,
    RelationshipApprovalError,
    approve_relationship,
    build_approved_join_plan,
    execute_approved_join_plan,
    pending_relationship,
    reject_relationship,
)
from generic_relationship_state import (
    clear_generic_state_if_uploads_changed,
    make_generic_upload_signature,
)
from generic_table_reader import read_tabular_sources
from relationship_discovery import (
    discover_relationships,
    evaluate_relationship_candidate,
)


DATASET_DIR = PROJECT_DIR / "Global+Electronics+Retailer"


def basic_frames():
    sales = pd.DataFrame(
        {
            "Order Number": [1, 2, 3, 4],
            "Order Date": ["2024-01-01"] * 4,
            "CustomerKey": [10, 10, 11, 12],
            "BuyerCode": [10, 10, 11, 12],
            "ProductKey": [100, 101, 100, 102],
            "Amount": [10.0, 20.0, 30.0, 40.0],
        }
    )
    customers = pd.DataFrame(
        {
            "CustomerKey": [10, 11, 12],
            "Customer Name": ["A", "B", "C"],
            "Segment": ["Retail", "Retail", "Wholesale"],
        }
    )
    products = pd.DataFrame(
        {
            "ProductKey": [100, 101, 102],
            "Product Name": ["P1", "P2", "P3"],
            "Category": ["A", "A", "B"],
        }
    )
    return sales, customers, products


def basic_discovery():
    sales, customers, products = basic_frames()
    return discover_relationships(
        {"Sales": sales, "Customers": customers, "Products": products}
    )


def candidate_to(result, right_table, left_columns=None):
    for candidate in result.relationships:
        if candidate.right_table != right_table:
            continue
        if left_columns is not None and candidate.left_columns != tuple(left_columns):
            continue
        return candidate
    raise AssertionError(f"No candidate found for right table {right_table!r}.")


class RelationshipDecisionTests(unittest.TestCase):
    def test_high_confidence_candidate_requires_explicit_approval(self):
        result = basic_discovery()
        candidate = candidate_to(result, "Customers", ("CustomerKey",))

        self.assertGreaterEqual(candidate.confidence_score, 80)
        self.assertEqual(candidate.decision_status, "pending")
        self.assertFalse(candidate.auto_apply)
        decision = approve_relationship(candidate)
        self.assertEqual(decision.status, "approved")

    def test_rejected_candidate_is_not_added_to_plan(self):
        result = basic_discovery()
        customer_candidate = candidate_to(result, "Customers", ("CustomerKey",))
        product_candidate = candidate_to(result, "Products", ("ProductKey",))
        decisions = [
            approve_relationship(customer_candidate),
            reject_relationship(product_candidate),
        ]

        plan = build_approved_join_plan(result, "Sales", decisions)

        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(plan.steps[0].right_table, "Customers")

    def test_pending_candidate_is_not_implicitly_approved(self):
        result = basic_discovery()
        candidate = candidate_to(result, "Customers", ("CustomerKey",))

        with self.assertRaisesRegex(JoinPlanValidationError, "explicitly approved"):
            build_approved_join_plan(result, "Sales", [pending_relationship(candidate)])

    def test_edit_to_new_single_column_relationship_recalculates_candidate(self):
        result = basic_discovery()
        original = candidate_to(result, "Customers", ("CustomerKey",))

        edited = evaluate_relationship_candidate(
            result,
            "Sales",
            ("BuyerCode",),
            "Customers",
            ("CustomerKey",),
        )
        decision = approve_relationship(
            edited, original_candidate_id=original.candidate_id, edited=True
        )

        self.assertEqual(edited.left_columns, ("BuyerCode",))
        self.assertEqual(edited.match_rate, 1.0)
        self.assertTrue(decision.edited)
        self.assertEqual(decision.status, "approved")

    def test_edit_to_two_column_composite_key_recalculates_candidate(self):
        sales = pd.DataFrame(
            {
                "Order Number": [1, 2, 3, 4],
                "Order Date": ["2024-01-01", "2024-01-01", "2024-01-02", "2024-01-02"],
                "Currency Code": ["USD", "CAD", "USD", "CAD"],
                "Amount": [10, 20, 30, 40],
            }
        )
        rates = pd.DataFrame(
            {
                "Date": ["2024-01-01", "2024-01-01", "2024-01-02", "2024-01-02"],
                "Currency": ["USD", "CAD", "USD", "CAD"],
                "Exchange": [1.0, 1.3, 1.0, 1.4],
            }
        )
        result = discover_relationships({"Sales": sales, "Rates": rates})

        edited = evaluate_relationship_candidate(
            result,
            "Sales",
            ("Order Date", "Currency Code"),
            "Rates",
            ("Date", "Currency"),
        )

        self.assertEqual(edited.relationship_kind, "composite")
        self.assertEqual(edited.comparison_kinds, ("date", "text"))
        self.assertEqual(edited.right_key_uniqueness, 1.0)
        self.assertFalse(edited.blocked)

    def test_blocked_relationship_cannot_be_approved(self):
        sales, customers, _ = basic_frames()
        customers = pd.concat([customers, customers.iloc[[0]]], ignore_index=True)
        result = discover_relationships({"Sales": sales, "Customers": customers})
        candidate = candidate_to(result, "Customers", ("CustomerKey",))

        self.assertTrue(candidate.blocked)
        with self.assertRaisesRegex(RelationshipApprovalError, "cannot be approved"):
            approve_relationship(candidate)


class ApprovedJoinPlanTests(unittest.TestCase):
    def test_single_table_can_build_and_execute_plan_without_relationships(self):
        sales, _, _ = basic_frames()
        result = discover_relationships({"Sales": sales})

        plan = build_approved_join_plan(result, "Sales", [])
        merge_result = execute_approved_join_plan(result, plan)

        self.assertEqual(plan.steps, ())
        self.assertTrue(merge_result.success)
        self.assertEqual(merge_result.fact_row_count, len(sales))
        self.assertEqual(merge_result.final_row_count, len(sales))
        assert_frame_equal(merge_result.merged_frame, sales)

    def test_fact_table_must_be_explicitly_selected(self):
        result = basic_discovery()
        candidate = candidate_to(result, "Customers", ("CustomerKey",))

        with self.assertRaisesRegex(JoinPlanValidationError, "fact table"):
            build_approved_join_plan(result, None, [approve_relationship(candidate)])

    def test_cycle_plan_is_rejected(self):
        first = pd.DataFrame({"Entity ID": [1, 2], "Name": ["A", "B"]})
        second = pd.DataFrame({"Entity ID": [1, 2], "Name": ["A", "B"]})
        result = discover_relationships({"First": first, "Second": second})
        forward = evaluate_relationship_candidate(
            result, "First", ("Entity ID",), "Second", ("Entity ID",)
        )
        backward = evaluate_relationship_candidate(
            result, "Second", ("Entity ID",), "First", ("Entity ID",)
        )

        with self.assertRaisesRegex(JoinPlanValidationError, "cycle"):
            build_approved_join_plan(
                result,
                "First",
                [approve_relationship(forward), approve_relationship(backward)],
            )

    def test_duplicate_dimension_table_is_rejected(self):
        sales, customers, _ = basic_frames()
        customers["BuyerCode"] = customers["CustomerKey"]
        result = discover_relationships({"Sales": sales, "Customers": customers})
        first = evaluate_relationship_candidate(
            result, "Sales", ("CustomerKey",), "Customers", ("CustomerKey",)
        )
        second = evaluate_relationship_candidate(
            result, "Sales", ("BuyerCode",), "Customers", ("BuyerCode",)
        )

        with self.assertRaisesRegex(JoinPlanValidationError, "more than once"):
            build_approved_join_plan(
                result,
                "Sales",
                [approve_relationship(first), approve_relationship(second)],
            )

    def test_disconnected_relationship_is_rejected(self):
        sales, customers, products = basic_frames()
        categories = pd.DataFrame(
            {"Category": ["A", "B"], "Category Name": ["Alpha", "Beta"]}
        )
        result = discover_relationships(
            {
                "Sales": sales,
                "Customers": customers,
                "Products": products,
                "Categories": categories,
            }
        )
        disconnected = evaluate_relationship_candidate(
            result, "Products", ("Category",), "Categories", ("Category",)
        )

        with self.assertRaisesRegex(JoinPlanValidationError, "Unreachable"):
            build_approved_join_plan(
                result, "Sales", [approve_relationship(disconnected)]
            )


class SafeMergeExecutionTests(unittest.TestCase):
    def test_many_to_one_merge_succeeds_without_changing_source_frames(self):
        result = basic_discovery()
        candidate = candidate_to(result, "Customers", ("CustomerKey",))
        original_sales = result.get_table("Sales").frame.copy(deep=True)
        original_customers = result.get_table("Customers").frame.copy(deep=True)
        plan = build_approved_join_plan(
            result, "Sales", [approve_relationship(candidate)]
        )

        merge_result = execute_approved_join_plan(result, plan)

        self.assertTrue(merge_result.success)
        self.assertEqual(merge_result.fact_row_count, 4)
        self.assertEqual(merge_result.final_row_count, 4)
        self.assertEqual(merge_result.diagnostics[0].validation_status, "passed")
        self.assertEqual(merge_result.diagnostics[0].row_growth, 0)
        self.assertIn("Customers.Customer Name", merge_result.merged_frame.columns)
        assert_frame_equal(result.get_table("Sales").frame, original_sales)
        assert_frame_equal(result.get_table("Customers").frame, original_customers)

    def test_row_inflation_during_execution_stops_without_merged_output(self):
        result = basic_discovery()
        candidate = candidate_to(result, "Customers", ("CustomerKey",))
        plan = build_approved_join_plan(
            result, "Sales", [approve_relationship(candidate)]
        )
        customers = result.get_table("Customers").frame
        customers.loc[len(customers)] = customers.iloc[0]

        merge_result = execute_approved_join_plan(result, plan)

        self.assertFalse(merge_result.success)
        self.assertIsNone(merge_result.merged_frame)
        self.assertEqual(
            merge_result.diagnostics[0].validation_status, "blocked_preflight"
        )
        self.assertGreater(merge_result.diagnostics[0].row_growth, 0)


class GenericRelationshipStateTests(unittest.TestCase):
    def test_upload_change_clears_discovery_decisions_plan_and_merge_state(self):
        old_file = BytesIO(b"id\n1\n")
        old_file.name = "old.csv"
        new_file = BytesIO(b"id\n2\n")
        new_file.name = "new.csv"
        old_signature = make_generic_upload_signature([old_file])
        new_signature = make_generic_upload_signature([new_file])
        state = {
            "generic_upload_signature": old_signature,
            "generic_discovery_result": object(),
            "generic_relationship_decisions": {"a": object()},
            "generic_approved_plan": object(),
            "generic_merge_result": object(),
            "generic_standard_mapping_result": object(),
            "generic_mapping_recommendations": (object(),),
            "generic_report_result": object(),
            "generic_report_confirm": True,
            "generic_fact_table_id": "Sales",
            "generic_candidate_a_action": "approved",
            "generic_mapping_choice_order_id": "source::Order Number",
            "unrelated_state": "keep",
        }

        changed = clear_generic_state_if_uploads_changed(state, new_signature)

        self.assertTrue(changed)
        self.assertEqual(state["generic_upload_signature"], new_signature)
        self.assertEqual(state["unrelated_state"], "keep")
        self.assertNotIn("generic_discovery_result", state)
        self.assertNotIn("generic_relationship_decisions", state)
        self.assertNotIn("generic_approved_plan", state)
        self.assertNotIn("generic_merge_result", state)
        self.assertNotIn("generic_standard_mapping_result", state)
        self.assertNotIn("generic_mapping_recommendations", state)
        self.assertNotIn("generic_report_result", state)
        self.assertNotIn("generic_report_confirm", state)
        self.assertNotIn("generic_fact_table_id", state)
        self.assertNotIn("generic_candidate_a_action", state)
        self.assertNotIn("generic_mapping_choice_order_id", state)


class MavenConfirmedMergeTests(unittest.TestCase):
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
        cls.delivery_candidate = None
        approved = []
        for candidate in cls.discovery.relationships:
            mapping = dict(zip(candidate.left_columns, candidate.right_columns))
            if candidate.right_table in {"Products", "Customers", "Stores"}:
                expected_left = {
                    "Products": "ProductKey",
                    "Customers": "CustomerKey",
                    "Stores": "StoreKey",
                }[candidate.right_table]
                if candidate.left_columns == (expected_left,) and not candidate.blocked:
                    approved.append(approve_relationship(candidate))
            elif candidate.right_table == "Exchange_Rates":
                if mapping == {
                    "Currency Code": "Currency",
                    "Order Date": "Date",
                } and not candidate.blocked:
                    approved.append(approve_relationship(candidate))
                elif "Delivery Date" in candidate.left_columns:
                    cls.delivery_candidate = candidate
        cls.approved = approved
        cls.plan = build_approved_join_plan(cls.discovery, "Sales", approved)
        cls.merge_result = execute_approved_join_plan(cls.discovery, cls.plan)

    def test_maven_four_approved_relationships_preserve_62884_rows(self):
        self.assertEqual(len(self.plan.steps), 4)
        self.assertTrue(self.merge_result.success)
        self.assertEqual(self.merge_result.fact_row_count, 62884)
        self.assertEqual(self.merge_result.final_row_count, 62884)
        self.assertTrue(
            all(diagnostic.row_growth == 0 for diagnostic in self.merge_result.diagnostics)
        )

    def test_rejected_delivery_date_candidate_does_not_enter_plan(self):
        self.assertIsNotNone(self.delivery_candidate)
        decisions = self.approved + [reject_relationship(self.delivery_candidate)]

        plan = build_approved_join_plan(self.discovery, "Sales", decisions)

        self.assertFalse(
            any("Delivery Date" in step.left_columns for step in plan.steps)
        )


if __name__ == "__main__":
    unittest.main()
