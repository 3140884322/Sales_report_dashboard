from dataclasses import replace
from pathlib import Path
import sys
import unittest

import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from app import make_action_required_table, make_data_limitations_table
from confirmed_relationship_plan import (
    approve_relationship,
    build_approved_join_plan,
    execute_approved_join_plan,
)
from generic_report_generation import (
    customer_analysis_available,
    generate_generic_report,
    get_field_availability_status,
    run_generic_report_preflight,
)
from relationship_discovery import (
    discover_relationships,
    evaluate_relationship_candidate,
)
from standard_field_mapping import (
    build_source_entity_role_map,
    generate_unified_orders,
    recommend_standard_field_mappings,
    selections_from_recommendations,
)
from relationship_safety import (
    MINIMUM_ORDER_GRAIN_MATCH_RATE,
    evaluate_join_safety,
)


def northwind_tables():
    return {
        "Order Details": pd.DataFrame(
            {
                "OrderID": [1, 1, 2, 3, 4, 5, 6, 6],
                "ProductID": [10, 11, 10, 12, 11, 12, 10, 11],
                "UnitPrice": [10.0, 20.0, 10.0, 30.0, 20.0, 30.0, 10.0, 20.0],
                "Quantity": [1, 2, 4, 1, 1, 1, 1, 1],
                "Discount": [0.0] * 8,
            }
        ),
        "Orders": pd.DataFrame(
            {
                "OrderID": [1, 2, 3, 4, 5, 6],
                "CustomerID": ["ALFKI", "ANATR", "ALFKI", "AROUT", "ANATR", "ALFKI"],
                "EmployeeID": [1, 2, 1, 2, 1, 2],
                "OrderDate": [
                    "2024-01-01",
                    "2024-01-31",
                    "2024-02-01",
                    "2024-02-29",
                    "2024-03-01",
                    "2024-03-10",
                ],
                "ShipVia": [1, 2, 1, 3, 2, 1],
            }
        ),
        "Customers": pd.DataFrame(
            {
                "CustomerID": ["ALFKI", "ANATR", "AROUT"],
                "CompanyName": [
                    "Alfreds Futterkiste",
                    "Ana Trujillo Emparedados",
                    "Around the Horn",
                ],
            }
        ),
        "Products": pd.DataFrame(
            {
                "ProductID": [10, 11, 12],
                "ProductName": ["Chai", "Chang", "Aniseed Syrup"],
                "SupplierID": [1, 2, 1],
                "CategoryID": [1, 1, 2],
            }
        ),
        "Categories": pd.DataFrame(
            {
                "CategoryID": [1, 2],
                "CategoryName": ["Beverages", "Condiments"],
            }
        ),
        "Shippers": pd.DataFrame(
            {
                "ShipperID": [1, 2, 3],
                "CompanyName": [
                    "Speedy Express",
                    "United Package",
                    "Federal Shipping",
                ],
            }
        ),
        "Suppliers": pd.DataFrame(
            {
                "SupplierID": [1, 2],
                "CompanyName": ["Exotic Liquids", "New Orleans Cajun Delights"],
            }
        ),
        "Employees": pd.DataFrame(
            {
                "EmployeeID": [1, 2],
                "LastName": ["Davolio", "Fuller"],
            }
        ),
    }


RELATIONSHIPS = (
    ("Order Details", ("OrderID",), "Orders", ("OrderID",)),
    ("Order Details", ("ProductID",), "Products", ("ProductID",)),
    ("Orders", ("CustomerID",), "Customers", ("CustomerID",)),
    ("Orders", ("ShipVia",), "Shippers", ("ShipperID",)),
    ("Orders", ("EmployeeID",), "Employees", ("EmployeeID",)),
    ("Products", ("CategoryID",), "Categories", ("CategoryID",)),
    ("Products", ("SupplierID",), "Suppliers", ("SupplierID",)),
)


def build_northwind_flow():
    discovery = discover_relationships(northwind_tables())
    decisions = []
    for relationship in RELATIONSHIPS:
        candidate = evaluate_relationship_candidate(discovery, *relationship)
        decisions.append(approve_relationship(candidate))
    plan = build_approved_join_plan(discovery, "Order Details", decisions)
    merge_result = execute_approved_join_plan(discovery, plan)
    roles = build_source_entity_role_map(discovery, merge_result.fact_table_id)
    recommendations = recommend_standard_field_mappings(
        merge_result.merged_frame,
        roles,
    )
    selections = selections_from_recommendations(recommendations, confirmed=True)
    mapping = generate_unified_orders(
        merge_result.merged_frame,
        selections,
        selected_extension_columns=("Products.CategoryID",),
        source_entity_roles=roles,
    )
    preflight = run_generic_report_preflight(
        mapping,
        original_fact_row_count=merge_result.fact_row_count,
        merged_row_count=merge_result.final_row_count,
    )
    report = generate_generic_report(
        mapping_result=mapping,
        preflight=preflight,
        discovery_result=discovery,
        plan=plan,
        decisions={decision.original_candidate_id: decision for decision in decisions},
    )
    return {
        "discovery": discovery,
        "plan": plan,
        "merge": merge_result,
        "roles": roles,
        "recommendations": recommendations,
        "selections": selections,
        "mapping": mapping,
        "preflight": preflight,
        "report": report,
    }


class NorthwindGenericAccuracyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.flow = build_northwind_flow()

    def test_entity_roles_distinguish_ambiguous_business_entities(self):
        profiles = {
            profile.table_id: profile for profile in self.flow["discovery"].table_profiles
        }

        self.assertEqual(profiles["Customers"].entity_role, "customer")
        self.assertEqual(profiles["Shippers"].entity_role, "shipper")
        self.assertEqual(profiles["Suppliers"].entity_role, "supplier")
        self.assertEqual(profiles["Employees"].entity_role, "employee")
        self.assertEqual(
            profiles["Customers"].get_column("CompanyName").entity_role,
            "customer",
        )
        self.assertEqual(
            profiles["Shippers"].get_column("CompanyName").entity_role,
            "shipper",
        )

    def test_mapping_uses_customer_and_category_descriptions(self):
        recommendations = {
            item.standard_field: item for item in self.flow["recommendations"]
        }

        self.assertEqual(
            recommendations["customer_name"].recommended_source,
            "Customers.CompanyName",
        )
        self.assertEqual(
            recommendations["category"].recommended_source,
            "Categories.CategoryName",
        )
        self.assertNotIn(
            recommendations["customer_name"].recommended_source,
            {"Shippers.CompanyName", "Suppliers.CompanyName"},
        )

    def test_northwind_does_not_infer_a_store_from_other_entities(self):
        report_tables = self.flow["report"]["report_tables"]
        self.assertEqual(
            get_field_availability_status(report_tables, "store_analysis"),
            "not_provided",
        )
        self.assertNotIn("store_summary", report_tables)

    def test_safe_merge_and_unified_orders_preserve_line_grain(self):
        merge_result = self.flow["merge"]
        mapping = self.flow["mapping"]
        order_candidate = evaluate_relationship_candidate(
            self.flow["discovery"],
            "Order Details",
            ("OrderID",),
            "Orders",
            ("OrderID",),
        )

        self.assertTrue(merge_result.success, merge_result.error_message)
        self.assertEqual(order_candidate.expected_join_type, "many_to_one")
        self.assertEqual(order_candidate.right_key_uniqueness, 1.0)
        self.assertGreaterEqual(
            order_candidate.match_rate,
            MINIMUM_ORDER_GRAIN_MATCH_RATE,
        )
        self.assertEqual(
            order_candidate.before_row_count,
            order_candidate.after_row_count,
        )
        self.assertEqual(merge_result.fact_row_count, 8)
        self.assertEqual(merge_result.final_row_count, 8)
        self.assertTrue(mapping.success, mapping.errors)
        self.assertEqual(len(mapping.unified_orders), 8)
        self.assertEqual(
            set(mapping.unified_orders["category"]),
            {"Beverages", "Condiments"},
        )
        self.assertIn("Products.CategoryID", mapping.unified_orders.columns)

        low_match = evaluate_join_safety(
            pd.DataFrame({"OrderID": [1, 90, 91, 92, 93, 94]}),
            pd.DataFrame({"OrderID": [1, 2, 3]}),
            ("OrderID",),
            ("OrderID",),
            ("numeric",),
            "fact",
            "fact",
            "order_line",
            "order_header",
        )
        self.assertLess(low_match.match_rate, MINIMUM_ORDER_GRAIN_MATCH_RATE)
        self.assertTrue(low_match.blocked)
        self.assertIn("order_line_to_header_low_match", low_match.risk_flags)

    def test_report_uses_real_customers_not_carriers_or_suppliers(self):
        report = self.flow["report"]
        tables = report["report_tables"]
        customer_names = set(tables["customer_summary"]["customer_name"])

        self.assertEqual(report["status"], "ready")
        self.assertTrue(customer_analysis_available(tables))
        self.assertIn("Alfreds Futterkiste", customer_names)
        self.assertNotIn("Speedy Express", customer_names)
        self.assertNotIn("Exotic Liquids", customer_names)
        self.assertNotIn("1.0", set(tables["category_summary"]["category"]))

    def test_partial_last_month_remains_visible_but_is_not_ranked_or_anomalous(self):
        report = self.flow["report"]
        monthly = report["report_tables"]["monthly_summary"]
        march = monthly.loc[monthly["year_month"].astype(str) == "2024-03"].iloc[0]
        anomalies = report["report_tables"]["anomalies"]
        markdown = report["summary_text"]

        self.assertEqual(len(monthly), 3)
        self.assertTrue(bool(march["is_partial_period"]))
        self.assertEqual(march["partial_reason"], "Partial month through 2024-03-10")
        affected = anomalies.get("affected_month", pd.Series(dtype="object"))
        self.assertFalse((affected.astype(str) == "2024-03").any())
        self.assertIn("Partial month through 2024-03-10", markdown)
        ranking_lines = [line for line in markdown.splitlines() if "complete month" in line]
        self.assertTrue(all("2024-03" not in line for line in ranking_lines))

    def test_complete_month_drop_has_business_label_and_audit_fields(self):
        anomalies = self.flow["report"]["report_tables"]["anomalies"]
        revenue_drops = anomalies.loc[
            anomalies["anomaly_type"] == "sales_drop_over_20_percent"
        ]

        self.assertEqual(len(revenue_drops), 1)
        drop = revenue_drops.iloc[0]
        self.assertEqual(
            drop["anomaly_label"],
            "Monthly revenue dropped by more than 20%",
        )
        self.assertEqual(str(drop["affected_month"]), "2024-02")
        self.assertEqual(str(drop["previous_month"]), "2024-01")
        self.assertFalse(bool(drop["whether_current_period_is_partial"]))
        self.assertIn("February 2024 revenue decreased", drop["details"])

    def test_optional_data_limitations_are_separate_from_business_issues(self):
        report = self.flow["report"]
        action = make_action_required_table(report)
        limitations = make_data_limitations_table(report)

        self.assertFalse(action["Issue"].str.contains("expense|return", case=False).any())
        self.assertTrue(
            limitations["Limitation"].str.contains("Expense data", case=False).any()
        )
        self.assertTrue(
            limitations["Limitation"].str.contains("Return data", case=False).any()
        )
        self.assertFalse(action["Issue"].str.contains("sales_drop_over", case=False).any())

    def test_customer_mapping_conflict_skips_customer_analysis_and_flags_review(self):
        selections = tuple(
            replace(
                selection,
                source_column="Shippers.CompanyName",
                confirmed=True,
            )
            if selection.standard_field == "customer_name"
            else selection
            for selection in self.flow["selections"]
        )
        mapping = generate_unified_orders(
            self.flow["merge"].merged_frame,
            selections,
            source_entity_roles=self.flow["roles"],
        )
        availability = {
            item.field_name: item for item in mapping.field_availability
        }
        preflight = run_generic_report_preflight(mapping)
        report = generate_generic_report(
            mapping_result=mapping,
            preflight=preflight,
            discovery_result=self.flow["discovery"],
            plan=self.flow["plan"],
            decisions={},
        )

        self.assertTrue(mapping.success, mapping.errors)
        self.assertEqual(
            availability["customer_id"].availability_status,
            "mapping_conflict",
        )
        self.assertTrue(preflight.can_generate)
        self.assertEqual(report["status"], "review_required")
        self.assertTrue(report["report_tables"]["customer_summary"].empty)
        self.assertIn("Customer field mapping conflict", report["summary_text"])


class IdentifierDisplayFallbackTests(unittest.TestCase):
    def test_numeric_category_id_uses_stable_display_label(self):
        frame = pd.DataFrame(
            {
                "OrderID": [1, 2],
                "OrderDate": ["2024-01-01", "2024-01-31"],
                "ProductID": [10, 11],
                "UnitPrice": [5.0, 8.0],
                "Quantity": [1, 2],
                "CategoryID": [1.0, 2.0],
            }
        )
        roles = {
            "OrderID": "order_header",
            "OrderDate": "order_header",
            "ProductID": "product",
            "UnitPrice": "order_line",
            "Quantity": "order_line",
            "CategoryID": "category",
        }
        recommendations = recommend_standard_field_mappings(frame, roles)
        mapping = generate_unified_orders(
            frame,
            selections_from_recommendations(recommendations, confirmed=True),
            source_entity_roles=roles,
        )

        self.assertTrue(mapping.success, mapping.errors)
        self.assertEqual(
            mapping.unified_orders["category"].tolist(),
            ["Category 1", "Category 2"],
        )
        self.assertNotIn(
            "Category 1.0",
            mapping.unified_orders["category"].tolist(),
        )


if __name__ == "__main__":
    unittest.main()
