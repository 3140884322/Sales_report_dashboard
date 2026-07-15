from io import BytesIO
import importlib.util
import os
from pathlib import Path
import sys
import unittest

import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from confirmed_relationship_plan import (
    approve_relationship,
    build_approved_join_plan,
    execute_approved_join_plan,
)
from generic_report_generation import generate_generic_report, run_generic_report_preflight
from generic_table_reader import (
    GenericTableReaderError,
    MOJIBAKE_UI_MESSAGE_KEY,
    read_tabular_sources,
)
from relationship_aliases import compare_column_names, semantic_tokens
from relationship_discovery import (
    discover_relationships,
    discover_relationships_from_sources,
)
from relationship_safety import canonicalize_key_series
from standard_field_mapping import (
    build_source_entity_role_map,
    generate_unified_orders,
    recommend_standard_field_mappings,
    selections_from_recommendations,
)


def named_bytes(name: str, data: bytes) -> BytesIO:
    source = BytesIO(data)
    source.name = name
    return source


def chinese_workbook() -> BytesIO:
    sales = pd.DataFrame(
        {
            "订单编号": ["O001", "O001", "O002", "O003", "O004", "O005"],
            "销售日期": [
                "2025-01-02",
                "2025-01-02",
                "2025-01-15",
                "2025-02-03",
                "2025-02-18",
                "2025-03-01",
            ],
            "商品编号": ["P01", "P02", "P01", "P03", "P02", "P03"],
            "客户编号": ["C01", "C01", "C02", "C03", "C02", "C03"],
            "门店编号": ["S01", "S01", "S02", "S01", "S02", "S02"],
            "数量": [1, 2, 1, 3, 1, 2],
            "单价": [20.0, 12.0, 20.0, 8.0, 12.0, 8.0],
        }
    )
    products = pd.DataFrame(
        {
            "商品编号": ["P01", "P02", "P03"],
            "商品名称": ["咖啡", "茶", "蛋糕"],
            "品类": ["饮品", "饮品", "食品"],
        }
    )
    customers = pd.DataFrame(
        {
            "客户编号": ["C01", "C02", "C03"],
            "客户名称": ["甲公司", "乙公司", "丙公司"],
        }
    )
    stores = pd.DataFrame(
        {
            "门店编号": ["S01", "S02"],
            "门店名称": ["北京店", "上海店"],
        }
    )
    source = BytesIO()
    with pd.ExcelWriter(source, engine="openpyxl") as writer:
        sales.to_excel(writer, sheet_name="销售明细", index=False)
        products.to_excel(writer, sheet_name="商品档案", index=False)
        customers.to_excel(writer, sheet_name="客户档案", index=False)
        stores.to_excel(writer, sheet_name="门店档案", index=False)
    source.seek(0)
    source.name = "中文销售数据.xlsx"
    return source


def candidate_for(discovery, left_table, left_column, right_table, right_column):
    matches = [
        candidate
        for candidate in discovery.relationships
        if candidate.left_table == left_table
        and candidate.left_columns == (left_column,)
        and candidate.right_table == right_table
        and candidate.right_columns == (right_column,)
    ]
    if not matches:
        return None
    return max(matches, key=lambda item: item.confidence_score)


class ChineseWorkbookEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.discovery = discover_relationships_from_sources(chinese_workbook())
        profile_by_name = {
            profile.table_name: profile for profile in cls.discovery.table_profiles
        }
        cls.fact_profile = profile_by_name["销售明细"]
        expected = (
            ("商品编号", "商品档案", "商品编号"),
            ("客户编号", "客户档案", "客户编号"),
            ("门店编号", "门店档案", "门店编号"),
        )
        cls.selected_candidates = []
        for left_column, right_table, right_column in expected:
            candidate = candidate_for(
                cls.discovery,
                "销售明细",
                left_column,
                right_table,
                right_column,
            )
            if candidate is not None:
                cls.selected_candidates.append(candidate)

        decisions = [approve_relationship(candidate) for candidate in cls.selected_candidates]
        cls.plan = build_approved_join_plan(
            cls.discovery, cls.fact_profile.table_id, decisions
        )
        cls.merge_result = execute_approved_join_plan(cls.discovery, cls.plan)
        source_roles = build_source_entity_role_map(
            cls.discovery, cls.fact_profile.table_id
        )
        cls.recommendations = recommend_standard_field_mappings(
            cls.merge_result.merged_frame, source_roles
        )
        cls.mapping = generate_unified_orders(
            cls.merge_result.merged_frame,
            selections_from_recommendations(cls.recommendations, confirmed=True),
            source_entity_roles=source_roles,
        )
        cls.preflight = run_generic_report_preflight(
            cls.mapping,
            original_fact_row_count=6,
            merged_row_count=cls.merge_result.final_row_count,
        )
        cls.report = generate_generic_report(
            mapping_result=cls.mapping,
            preflight=cls.preflight,
            discovery_result=cls.discovery,
            plan=cls.plan,
            decisions={item.original_candidate_id: item for item in decisions},
        )

    def test_chinese_four_sheet_workbook_discovers_expected_roles_and_relations(self):
        profiles = {
            profile.table_name: profile for profile in self.discovery.table_profiles
        }
        self.assertEqual(len(profiles), 4)
        self.assertEqual(profiles["销售明细"].role_guess, "fact")
        self.assertEqual(profiles["销售明细"].entity_role, "order_line")
        self.assertTrue(profiles["销售明细"].role_score_breakdown)
        self.assertEqual(len(self.selected_candidates), 3)
        self.assertTrue(all(not item.blocked for item in self.selected_candidates))
        self.assertTrue(all(not item.auto_apply for item in self.selected_candidates))

    def test_chinese_workbook_safe_merge_mapping_and_report_succeed(self):
        self.assertTrue(self.merge_result.success, self.merge_result.error_message)
        self.assertEqual(self.merge_result.fact_row_count, 6)
        self.assertEqual(self.merge_result.final_row_count, 6)
        self.assertTrue(all(item.row_growth == 0 for item in self.merge_result.diagnostics))
        self.assertTrue(self.mapping.success, self.mapping.errors)
        self.assertTrue(self.preflight.can_generate)
        self.assertEqual(self.report["status"], "ready")
        self.assertEqual(len(self.report["report_tables"]["enriched_orders"]), 6)


class ChineseCsvEncodingTests(unittest.TestCase):
    CSV_TEXT = "商品编号,商品名称\nP01,咖啡\nP02,茶\n"

    def _read(self, encoding: str, bom: bool = False):
        data = self.CSV_TEXT.encode(encoding)
        if bom:
            data = b"\xef\xbb\xbf" + data
        source = named_bytes(f"products-{encoding}.csv", data)
        source.seek(4)
        tables = read_tabular_sources(source)
        self.assertEqual(source.tell(), 4)
        self.assertEqual(tables[0].frame.columns.tolist(), ["商品编号", "商品名称"])
        self.assertEqual(tables[0].frame.iloc[0, 1], "咖啡")
        return tables[0]

    def test_utf8_csv(self):
        self.assertEqual(self._read("utf-8").encoding, "utf-8")

    def test_utf8_sig_csv(self):
        self.assertEqual(self._read("utf-8", bom=True).encoding, "utf-8-sig")

    def test_gb18030_csv(self):
        self.assertEqual(self._read("gb18030").encoding, "gb18030")

    def test_gbk_csv_is_read_before_permissive_western_fallbacks(self):
        self.assertIn(self._read("gbk").encoding, {"gb18030", "gbk"})

    def test_mojibake_csv_is_rejected_before_relationship_discovery(self):
        text = "ÉÌÆ·±àºÅ,Ãû³Æ\nA01,¿§·È\nA02,²èÒ¶\n"
        with self.assertRaises(GenericTableReaderError) as caught:
            discover_relationships_from_sources(
                named_bytes("mojibake.csv", text.encode("utf-8"))
            )
        self.assertEqual(caught.exception.ui_message_key, MOJIBAKE_UI_MESSAGE_KEY)
        self.assertIn("unreadable text", str(caught.exception))


class ChineseAliasAndFallbackTests(unittest.TestCase):
    def test_enterprise_aliases_and_mixed_language_keys_share_semantics(self):
        pairs = (
            ("单据号", "订单编号", "order"),
            ("货号", "物料编码", "product"),
            ("会员卡号", "客商编号", "customer"),
            ("网点代码", "机构编码", "store"),
            ("商品ID", "物料_ID", "product"),
            ("Customer编号", "customer_id", "customer"),
            ("Store_Code", "门店编号", "store"),
        )
        for left, right, concept in pairs:
            with self.subTest(left=left, right=right):
                self.assertIn(concept, semantic_tokens(left))
                self.assertIn(concept, semantic_tokens(right))
                self.assertGreaterEqual(compare_column_names(left, right).score, 15.0)

    def test_enterprise_aliases_generate_three_dimension_candidates(self):
        sales = pd.DataFrame(
            {
                "单据号": [f"D{i:02d}" for i in range(1, 7)],
                "货号": ["M01", "M02", "M03", "M01", "M02", "M03"],
                "会员卡号": ["K01", "K02", "K03", "K01", "K02", "K03"],
                "网点代码": ["N01", "N02", "N03", "N01", "N02", "N03"],
                "数量": [1, 2, 1, 2, 1, 2],
            }
        )
        discovery = discover_relationships(
            {
                "交易明细": sales,
                "物料档案": pd.DataFrame({"物料编码": ["M01", "M02", "M03"]}),
                "客商档案": pd.DataFrame({"客商编号": ["K01", "K02", "K03"]}),
                "机构表": pd.DataFrame({"机构编码": ["N01", "N02", "N03"]}),
            }
        )
        expected = {
            ("货号", "物料档案", "物料编码"),
            ("会员卡号", "客商档案", "客商编号"),
            ("网点代码", "机构表", "机构编码"),
        }
        observed = {
            (item.left_columns[0], item.right_table, item.right_columns[0])
            for item in discovery.relationships
            if not item.blocked and len(item.left_columns) == 1
        }
        self.assertTrue(expected.issubset(observed))

    def test_high_overlap_weak_name_fallback_is_needs_review_only(self):
        sales = pd.DataFrame(
            {
                "订单编号": [f"O{i}" for i in range(1, 7)],
                "业务编码": [f"X{i}" for i in range(1, 7)],
                "数量": [1, 2, 1, 2, 1, 2],
                "单价": [10, 11, 12, 13, 14, 15],
            }
        )
        dimension = pd.DataFrame(
            {
                "主数据编码": [f"X{i}" for i in range(1, 7)],
                "商品名称": [f"商品{i}" for i in range(1, 7)],
            }
        )
        discovery = discover_relationships({"销售明细": sales, "商品档案": dimension})
        fallback = [
            item
            for item in discovery.relationships
            if "weak_name_high_value_overlap" in item.risk_flags
        ]
        self.assertEqual(len(fallback), 1)
        candidate = fallback[0]
        self.assertEqual(candidate.left_columns, ("业务编码",))
        self.assertEqual(candidate.right_columns, ("主数据编码",))
        self.assertGreaterEqual(candidate.match_rate, 0.85)
        self.assertLess(candidate.confidence_score, 80.0)
        self.assertEqual(candidate.confidence_level, "medium")
        self.assertEqual(candidate.decision_status, "pending")
        self.assertFalse(candidate.auto_apply)
        self.assertIn("name_similarity", candidate.score_breakdown)
        self.assertIn("row_growth_risk", candidate.score_breakdown)


class RelationshipKeyNormalizationTests(unittest.TestCase):
    NORMALIZATION_VALUES = ["Ａ００１", "A002\u200b", "A003\u00a0", "\ufeffA004"]
    NORMALIZED_VALUES = ["a001", "a002", "a003", "a004"]

    def _assert_normalization_backend(self, dtype):
        source = pd.Series(self.NORMALIZATION_VALUES, dtype=dtype)
        original = source.copy(deep=True)

        normalized = canonicalize_key_series(source, "text")

        self.assertEqual(normalized.tolist(), self.NORMALIZED_VALUES)
        pd.testing.assert_series_equal(source, original)

    def test_relationship_key_normalization_with_object_dtype(self):
        self._assert_normalization_backend("object")

    def test_relationship_key_normalization_with_pandas_string_dtype(self):
        self._assert_normalization_backend("string[python]")

    @unittest.skipUnless(
        importlib.util.find_spec("pyarrow") is not None,
        "pyarrow is not installed",
    )
    def test_relationship_key_normalization_with_pyarrow_string_dtype(self):
        with pd.option_context("mode.string_storage", "pyarrow"):
            self._assert_normalization_backend("string[pyarrow]")

    def test_nfkc_spaces_and_hidden_characters_match_without_mutating_sources(self):
        original_keys = ["Ａ００１", "A002\u200b", "A\u00a0003", " a004 ", "A005"]
        sales = pd.DataFrame(
            {
                "订单编号": [f"O{i}" for i in range(1, 6)],
                "商品编号": original_keys,
                "数量": [1, 1, 1, 1, 1],
            }
        )
        products = pd.DataFrame(
            {
                "商品编号": ["A001", "A002", "A 003", "A004", "A005"],
                "商品名称": ["甲", "乙", "丙", "丁", "戊"],
            }
        )
        discovery = discover_relationships({"销售明细": sales, "商品档案": products})
        candidate = candidate_for(
            discovery, "销售明细", "商品编号", "商品档案", "商品编号"
        )
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.match_rate, 1.0)
        plan = build_approved_join_plan(
            discovery,
            next(item.table_id for item in discovery.tables if item.table_name == "销售明细"),
            [approve_relationship(candidate)],
        )
        result = execute_approved_join_plan(discovery, plan)
        self.assertTrue(result.success, result.error_message)
        self.assertEqual(result.final_row_count, 5)
        self.assertEqual(sales["商品编号"].tolist(), original_keys)
        self.assertEqual(result.merged_frame["商品编号"].tolist(), original_keys)

    def test_leading_zero_business_ids_are_not_silently_coerced(self):
        sales = pd.DataFrame(
            {
                "订单编号": [f"O{i}" for i in range(1, 7)],
                "商品编号": [f"00{i}" for i in range(1, 7)],
                "数量": [1, 1, 1, 1, 1, 1],
            }
        )
        products = pd.DataFrame(
            {"商品编号": [1, 2, 3, 4, 5, 6], "商品名称": list("甲乙丙丁戊己")}
        )
        discovery = discover_relationships({"销售明细": sales, "商品档案": products})
        self.assertTrue(discovery.diagnostics["format_warnings"])
        self.assertFalse(
            any(
                item.left_columns == ("商品编号",)
                and item.right_columns == ("商品编号",)
                for item in discovery.relationships
            )
        )
        self.assertEqual(sales["商品编号"].iloc[0], "001")

        left = pd.Series([1, 2, 3], dtype="int64")
        right = pd.Series([1, 2, 3], dtype="int64")
        self.assertEqual(
            canonicalize_key_series(left, "numeric").tolist(),
            canonicalize_key_series(right, "numeric").tolist(),
        )

    def test_amount_quantity_year_and_low_cardinality_overlap_do_not_become_strong_keys(self):
        left = pd.DataFrame(
            {
                "订单编号": [f"O{i}" for i in range(1, 7)],
                "销售额": [10, 20, 30, 40, 50, 60],
                "数量": [1, 2, 1, 2, 1, 2],
                "年份": [2021, 2022, 2023, 2024, 2025, 2026],
                "状态": [1, 2, 1, 2, 1, 2],
            }
        )
        right = pd.DataFrame(
            {
                "金额参考": [10, 20, 30, 40, 50, 60],
                "状态代码": [1, 2, 1, 2, 1, 2],
                "门店编号": [2021, 2022, 2023, 2024, 2025, 2026],
                "序号": [1, 2, 1, 2, 1, 2],
            }
        )
        discovery = discover_relationships({"销售记录": left, "参考数据": right})
        self.assertFalse(
            any(
                item.confidence_score >= 80 and not item.blocked
                for item in discovery.relationships
            )
        )
        self.assertTrue(all(not item.auto_apply for item in discovery.relationships))

    def test_fallback_comparisons_are_deterministically_bounded(self):
        rows = 500
        left = pd.DataFrame(
            {
                f"业务编码{column}": [f"L{column}-{row}" for row in range(rows)]
                for column in range(12)
            }
        )
        right = pd.DataFrame(
            {
                f"主数据代码{column}": [f"R{column}-{row}" for row in range(rows)]
                for column in range(12)
            }
        )
        discovery = discover_relationships({"销售明细": left, "商品档案": right})
        self.assertLessEqual(discovery.diagnostics["fallback_sample_comparisons"], 64)
        self.assertLessEqual(discovery.diagnostics["fallback_full_comparisons"], 4)
        self.assertEqual(discovery.diagnostics["fallback_candidate_count"], 0)


class ArrowBackedAcceptanceWorkbookTests(unittest.TestCase):
    workbook_path = Path(
        os.environ.get(
            "SALES_DASHBOARD_ACCEPTANCE_XLSX",
            "/Users/xiaoma/Desktop/test data/"
            "Sales_Report_Dashboard_功能验收数据包_兼容版/"
            "02_中文多表_标准关系.xlsx",
        )
    )

    @unittest.skipUnless(
        importlib.util.find_spec("pyarrow") is not None,
        "pyarrow is not installed",
    )
    def test_actual_chinese_multitable_workbook_with_arrow_string_storage(self):
        if not self.workbook_path.is_file():
            self.skipTest(f"Acceptance workbook not found: {self.workbook_path}")

        with pd.option_context("mode.string_storage", "pyarrow"):
            discovery = discover_relationships_from_sources(self.workbook_path)

        self.assertEqual(
            [table.table_name for table in discovery.tables],
            ["销售明细", "商品档案", "客户档案", "门店档案"],
        )
        expected = {
            ("商品编号", "商品档案", "商品编号"),
            ("客户编号", "客户档案", "客户编号"),
            ("门店编号", "门店档案", "门店编号"),
        }
        observed = {
            (candidate.left_columns[0], candidate.right_table, candidate.right_columns[0])
            for candidate in discovery.relationships
            if len(candidate.left_columns) == 1 and not candidate.blocked
        }
        self.assertTrue(expected.issubset(observed))


if __name__ == "__main__":
    unittest.main()
