from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest

import pandas as pd
from pandas.testing import assert_frame_equal


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from generic_table_reader import GenericTableReaderError, read_tabular_sources
from relationship_aliases import compare_column_names
from relationship_discovery import discover_relationships, profile_tables


DATASET_DIR = PROJECT_DIR / "Global+Electronics+Retailer"


def named_bytes(data, name):
    uploaded = BytesIO(data)
    uploaded.name = name
    return uploaded


def make_workbook_bytes():
    workbook = BytesIO()
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        pd.DataFrame({"CustomerKey": [1, 2], "Name": ["A", "B"]}).to_excel(
            writer, sheet_name="Customers", index=False
        )
        pd.DataFrame({"Order Number": [10, 11], "CustomerKey": [1, 2]}).to_excel(
            writer, sheet_name="Sales", index=False
        )
    return workbook.getvalue()


def customer_relationship_frames(right_keys=(1, 2, 3)):
    left = pd.DataFrame(
        {
            "Order Number": [101, 102, 103, 104],
            "Order Date": ["2024-01-01"] * 4,
            "CustomerKey": [1, 1, 2, 3],
            "Amount": [10.0, 20.0, 30.0, 40.0],
        }
    )
    right = pd.DataFrame(
        {
            "CustomerKey": list(right_keys),
            "Customer Name": [f"Customer {key}" for key in right_keys],
            "Segment": ["Retail"] * len(right_keys),
        }
    )
    return left, right


def find_candidate(result, left_columns, right_columns):
    for candidate in result.relationships:
        if candidate.left_columns == tuple(left_columns) and candidate.right_columns == tuple(
            right_columns
        ):
            return candidate
    return None


class GenericTableReaderTests(unittest.TestCase):
    def test_csv_reader_supports_paths_and_file_like_objects(self):
        csv_bytes = b"CustomerKey,Name\n1,A\n2,B\n"
        uploaded = named_bytes(csv_bytes, "uploaded.csv")

        with tempfile.TemporaryDirectory(dir=PROJECT_DIR) as temporary_directory:
            csv_path = Path(temporary_directory) / "customers.csv"
            csv_path.write_bytes(csv_bytes)
            tables = read_tabular_sources([csv_path, uploaded])

        self.assertEqual(len(tables), 2)
        self.assertEqual([table.table_name for table in tables], ["customers", "uploaded"])
        self.assertEqual([len(table.frame) for table in tables], [2, 2])
        self.assertEqual(uploaded.tell(), 0)

    def test_csv_reader_sniffs_pipe_delimiter_when_default_is_one_column(self):
        uploaded = named_bytes(
            b"transaction_id|store_id|store_location\n1|5|Astoria\n",
            "coffee.csv",
        )

        tables = read_tabular_sources(uploaded)

        self.assertEqual(
            list(tables[0].frame.columns),
            ["transaction_id", "store_id", "store_location"],
        )

    def test_xlsx_reader_loads_each_sheet_from_path_and_file_like(self):
        workbook_bytes = make_workbook_bytes()
        uploaded = named_bytes(workbook_bytes, "retail.xlsx")

        with tempfile.TemporaryDirectory(dir=PROJECT_DIR) as temporary_directory:
            workbook_path = Path(temporary_directory) / "retail_path.xlsx"
            workbook_path.write_bytes(workbook_bytes)
            path_tables = read_tabular_sources(workbook_path)
            upload_tables = read_tabular_sources(uploaded)

        self.assertEqual(
            [table.table_name for table in path_tables], ["Customers", "Sales"]
        )
        self.assertEqual(
            [table.table_name for table in upload_tables], ["Customers", "Sales"]
        )
        self.assertTrue(all(table.sheet_name for table in upload_tables))

    def test_unnamed_xlsx_file_like_is_detected_from_signature(self):
        tables = read_tabular_sources(BytesIO(make_workbook_bytes()))

        self.assertEqual([table.table_name for table in tables], ["Customers", "Sales"])

    def test_xlsx_reader_rejects_merged_cells(self):
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.merge_cells("A1:B1")
        sheet["A1"] = "Merged title"
        output = BytesIO()
        workbook.save(output)
        workbook.close()

        with self.assertRaisesRegex(GenericTableReaderError, "merged cells"):
            read_tabular_sources(named_bytes(output.getvalue(), "merged.xlsx"))


class ProfilingTests(unittest.TestCase):
    def test_table_and_column_profiles_include_required_metrics(self):
        frame = pd.DataFrame({"CustomerKey": [1, 2, 2, None], "Name": ["A", "B", None, "D"]})
        original = frame.copy(deep=True)

        profile = profile_tables({"Customers": frame})[0]
        key_profile = profile.get_column("CustomerKey")

        self.assertEqual(profile.row_count, 4)
        self.assertEqual(profile.column_count, 2)
        self.assertEqual(key_profile.null_count, 1)
        self.assertAlmostEqual(key_profile.null_rate, 0.25)
        self.assertEqual(key_profile.unique_count, 2)
        self.assertAlmostEqual(key_profile.unique_rate, 2 / 3)
        self.assertTrue(key_profile.sample_values)
        assert_frame_equal(frame, original)

    def test_fact_dimension_and_unknown_roles_are_available(self):
        sales, customers = customer_relationship_frames()
        unknown = pd.DataFrame({"Comment": ["a", "b", "c"]})
        profiles = profile_tables(
            {"Sales": sales, "Customers": customers, "Notes": unknown}
        )
        roles = {profile.table_name: profile.role_guess for profile in profiles}

        self.assertEqual(roles["Sales"], "fact")
        self.assertEqual(roles["Customers"], "dimension")
        self.assertEqual(roles["Notes"], "unknown")


class RelationshipCandidateTests(unittest.TestCase):
    def test_chinese_and_english_column_aliases_are_matched(self):
        left = pd.DataFrame(
            {
                "订单编号": [1, 2, 3, 4],
                "订单日期": ["2024-01-01"] * 4,
                "客户编号": [10, 10, 11, 12],
                "销售额": [100, 200, 300, 400],
            }
        )
        right = pd.DataFrame(
            {
                "Customer ID": [10, 11, 12],
                "Customer Name": ["A", "B", "C"],
                "Segment": ["R", "R", "W"],
            }
        )

        result = discover_relationships({"交易": left, "Customers": right})
        candidate = find_candidate(result, ("客户编号",), ("Customer ID",))

        self.assertIsNotNone(candidate)
        self.assertGreaterEqual(candidate.score_breakdown["name_alignment"], 20)
        self.assertIn("semantic alias", candidate.explanation)

    def test_identical_column_names_get_full_name_score(self):
        sales, products = customer_relationship_frames()
        result = discover_relationships({"Sales": sales, "Customers": products})
        candidate = find_candidate(result, ("CustomerKey",), ("CustomerKey",))

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.score_breakdown["name_alignment"], 25.0)

    def test_incompatible_types_are_filtered_before_value_overlap(self):
        left = pd.DataFrame(
            {
                "CustomerKey": [1, 2, 3],
                "Order Date": ["2024-01-01"] * 3,
                "Amount": [10, 20, 30],
            }
        )
        right = pd.DataFrame(
            {
                "CustomerKey": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
                "Name": ["A", "B", "C"],
            }
        )

        result = discover_relationships({"Sales": left, "Customers": right})

        self.assertIsNone(find_candidate(result, ("CustomerKey",), ("CustomerKey",)))
        self.assertEqual(result.diagnostics["value_overlap_comparisons"], 0)

    def test_high_value_overlap_produces_high_confidence_pending_candidate(self):
        sales, customers = customer_relationship_frames()
        original_sales = sales.copy(deep=True)
        original_customers = customers.copy(deep=True)

        result = discover_relationships({"Sales": sales, "Customers": customers})
        candidate = find_candidate(result, ("CustomerKey",), ("CustomerKey",))

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.match_rate, 1.0)
        self.assertGreaterEqual(candidate.confidence_score, 80)
        self.assertEqual(candidate.decision_status, "pending")
        self.assertFalse(candidate.auto_apply)
        self.assertTrue(candidate.score_breakdown)
        self.assertTrue(candidate.explanation)
        assert_frame_equal(sales, original_sales)
        assert_frame_equal(customers, original_customers)

    def test_non_unique_right_key_is_blocked_with_reason(self):
        sales, customers = customer_relationship_frames(right_keys=(1, 1, 2, 3))
        result = discover_relationships({"Sales": sales, "Customers": customers})
        candidate = find_candidate(result, ("CustomerKey",), ("CustomerKey",))

        self.assertIsNotNone(candidate)
        self.assertTrue(candidate.blocked)
        self.assertGreater(candidate.right_duplicate_key_count, 0)
        self.assertIn("right_key_not_unique", candidate.risk_flags)
        self.assertTrue(any("not unique" in reason for reason in candidate.block_reasons))

    def test_row_inflation_is_predicted_and_blocked_without_merge(self):
        sales, customers = customer_relationship_frames(right_keys=(1, 1, 2, 3))
        result = discover_relationships({"Sales": sales, "Customers": customers})
        candidate = find_candidate(result, ("CustomerKey",), ("CustomerKey",))

        self.assertIsNotNone(candidate)
        self.assertTrue(candidate.row_inflation)
        self.assertEqual(candidate.before_row_count, 4)
        self.assertEqual(candidate.after_row_count, 6)
        self.assertEqual(candidate.row_count_change, 2)
        self.assertFalse(result.diagnostics["merge_executed"])

    def test_many_to_many_relationship_is_blocked(self):
        sales, customers = customer_relationship_frames(right_keys=(1, 1, 2, 3))
        result = discover_relationships({"Sales": sales, "Customers": customers})
        candidate = find_candidate(result, ("CustomerKey",), ("CustomerKey",))

        self.assertIsNotNone(candidate)
        self.assertTrue(candidate.many_to_many_risk)
        self.assertTrue(candidate.blocked)
        self.assertIn("many_to_many", candidate.risk_flags)

    def test_fact_to_fact_relationship_is_blocked(self):
        left = pd.DataFrame(
            {
                "Order Number": [1, 2, 3],
                "Order Date": ["2024-01-01", "2024-01-02", "2024-01-03"],
                "Amount": [10, 20, 30],
            }
        )
        right = pd.DataFrame(
            {
                "Order Number": [1, 2, 3],
                "Order Date": ["2024-01-01", "2024-01-02", "2024-01-03"],
                "Revenue": [10, 20, 30],
            }
        )

        result = discover_relationships({"OrdersA": left, "OrdersB": right})
        candidate = find_candidate(result, ("Order Number",), ("Order Number",))

        self.assertIsNotNone(candidate)
        self.assertTrue(candidate.fact_to_fact_risk)
        self.assertTrue(candidate.blocked)
        self.assertIn("fact_to_fact", candidate.risk_flags)

    def test_two_column_composite_key_is_suggested(self):
        left = pd.DataFrame(
            {
                "Order ID": [1, 1, 2, 2, 1, 1, 2, 2],
                "Line No": [1, 2, 1, 2, 1, 2, 1, 2],
                "Order Date": ["2024-01-01"] * 8,
                "Amount": [10, 20, 30, 40, 10, 20, 30, 40],
            }
        )
        right = pd.DataFrame(
            {
                "Order ID": [1, 1, 2, 2],
                "Line No": [1, 2, 1, 2],
                "RecordKey": [101, 102, 103, 104],
                "Status": ["ok"] * 4,
                "Description": ["A", "B", "C", "D"],
            }
        )

        result = discover_relationships({"OrderLines": left, "LineLookup": right})
        composite = find_candidate(
            result, ("Order ID", "Line No"), ("Order ID", "Line No")
        )

        self.assertIsNotNone(composite)
        self.assertEqual(composite.relationship_kind, "composite")
        self.assertEqual(composite.expected_join_type, "many_to_one")
        self.assertEqual(composite.right_key_uniqueness, 1.0)
        self.assertFalse(composite.blocked)

    def test_prefilter_limits_value_overlap_comparisons(self):
        sales, customers = customer_relationship_frames()
        for index in range(20):
            sales[f"Metric {index}"] = range(len(sales))
            customers[f"Attribute {index}"] = [f"x-{index}-{row}" for row in range(len(customers))]

        result = discover_relationships({"Sales": sales, "Customers": customers})

        self.assertGreater(result.diagnostics["column_pairs_screened"], 400)
        self.assertLess(result.diagnostics["value_overlap_comparisons"], 10)

    def test_no_reasonable_relationship_returns_empty_candidates(self):
        left = pd.DataFrame({"CustomerKey": [1, 2, 3], "Label": ["A", "B", "C"]})
        right = pd.DataFrame({"CustomerKey": [101, 102, 103], "Label": ["X", "Y", "Z"]})

        result = discover_relationships({"Left": left, "Right": right})

        self.assertEqual(result.relationships, ())

    def test_alias_helper_exposes_human_readable_reason(self):
        match = compare_column_names("客户编号", "Customer ID")

        self.assertGreaterEqual(match.score, 20)
        self.assertIn("semantic alias", match.reason)


class MavenRelationshipDiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        paths = [
            DATASET_DIR / "Sales.csv",
            DATASET_DIR / "Products.csv",
            DATASET_DIR / "Customers.csv",
            DATASET_DIR / "Stores.csv",
            DATASET_DIR / "Exchange_Rates.csv",
        ]
        cls.result = discover_relationships(read_tabular_sources(paths))

    def test_maven_four_known_relationships_are_identified(self):
        safe_candidates = [
            candidate for candidate in self.result.relationships if not candidate.blocked
        ]

        def has_mapping(left_table, right_table, mapping):
            return any(
                candidate.left_table == left_table
                and candidate.right_table == right_table
                and dict(zip(candidate.left_columns, candidate.right_columns)) == mapping
                for candidate in safe_candidates
            )

        self.assertTrue(has_mapping("Sales", "Products", {"ProductKey": "ProductKey"}))
        self.assertTrue(has_mapping("Sales", "Customers", {"CustomerKey": "CustomerKey"}))
        self.assertTrue(has_mapping("Sales", "Stores", {"StoreKey": "StoreKey"}))
        self.assertTrue(
            has_mapping(
                "Sales",
                "Exchange_Rates",
                {"Order Date": "Date", "Currency Code": "Currency"},
            )
        )


if __name__ == "__main__":
    unittest.main()
