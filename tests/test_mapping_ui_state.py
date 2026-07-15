from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

import generic_standard_mapping_ui as mapping_ui
from confirmed_relationship_plan import (
    approve_relationship,
    build_approved_join_plan,
    execute_approved_join_plan,
)
from generic_report_generation import (
    generate_generic_report,
    run_generic_report_preflight,
)
from generic_table_reader import read_tabular_sources
from relationship_discovery import discover_relationships
from standard_field_mapping import (
    build_source_entity_role_map,
    generate_unified_orders,
    recommend_standard_field_mappings,
    selections_from_recommendations,
)


COFFEE_CSV = (
    b"transaction_id,transaction_date,transaction_qty,product_id,unit_price,"
    b"product_category,product_type\n"
    b"1,2024-01-01,2,P1,3.50,Coffee,Gourmet brewed coffee\n"
    b"2,2024-01-02,1,P2,4.00,Tea,Brewed Chai tea\n"
)


def load_coffee_app(language="zh"):
    app = AppTest.from_file(str(PROJECT_DIR / "app.py")).run(timeout=10)
    if language != "zh":
        app.selectbox[0].select(language).run(timeout=10)
    app.get("file_uploader")[0].upload(
        "coffee.csv", COFFEE_CSV, "text/csv"
    ).run(timeout=20)
    return app


def mapping_state(app):
    return {
        key: value
        for key, value in app.session_state.filtered_state.items()
        if key.startswith("generic_mapping_choice_")
        or key.startswith("generic_mapping_confirm_")
    }


class MappingChoiceCodecTests(unittest.TestCase):
    def test_not_provided_is_a_direct_internal_value(self):
        decoded = mapping_ui._decode_choice("not_provided")

        self.assertTrue(decoded.valid)
        self.assertEqual(decoded.strategy, "not_provided")
        self.assertEqual(decoded.normalized_choice, "not_provided")

    def test_unmapped_is_a_direct_internal_value(self):
        decoded = mapping_ui._decode_choice("unmapped")

        self.assertTrue(decoded.valid)
        self.assertEqual(decoded.strategy, "unmapped")
        self.assertEqual(decoded.normalized_choice, "unmapped")

    def test_source_column_may_contain_double_colons(self):
        encoded = mapping_ui._encode_choice("source", "ERP::Order ID")
        decoded = mapping_ui._decode_choice(encoded)

        self.assertEqual(encoded, "column::ERP::Order ID")
        self.assertTrue(decoded.valid)
        self.assertEqual(decoded.strategy, "source")
        self.assertEqual(decoded.source_column, "ERP::Order ID")

    def test_legacy_stable_values_are_migrated_without_changing_mapping(self):
        source = mapping_ui._decode_choice("source::Order ID")
        assumption = mapping_ui._decode_choice("strategy::default_zero")

        self.assertEqual(source.normalized_choice, "column::Order ID")
        self.assertEqual(source.source_column, "Order ID")
        self.assertEqual(assumption.normalized_choice, "assumption::default_zero")
        self.assertEqual(assumption.strategy, "default_zero")

    def test_legacy_chinese_and_english_display_values_are_safely_migrated(self):
        chinese = mapping_ui._decode_choice("映射来源列：Order ID")
        english = mapping_ui._decode_choice("Map from source: Order ID")

        self.assertTrue(chinese.valid)
        self.assertTrue(english.valid)
        self.assertEqual(chinese.normalized_choice, "column::Order ID")
        self.assertEqual(english.normalized_choice, "column::Order ID")

    def test_unknown_legacy_display_value_is_recorded_and_does_not_crash(self):
        state = {
            "generic_mapping_choice_order_id": "Translated mapping text",
            "generic_mapping_confirm_order_id": True,
        }

        with patch.object(mapping_ui.st, "session_state", state):
            with patch.object(mapping_ui, "_clear_mapping_output"):
                mapping_ui._choice_changed("order_id")

        self.assertEqual(
            state["generic_mapping_choice_error_order_id"],
            "Translated mapping text",
        )
        self.assertFalse(state["generic_mapping_confirm_order_id"])
        self.assertFalse(
            mapping_ui._decode_choice("Translated mapping text").valid
        )


class MappingLanguageStateTests(unittest.TestCase):
    def assert_stable_internal_values(self, app):
        choices = {
            key: value
            for key, value in app.session_state.filtered_state.items()
            if key.startswith("generic_mapping_choice_")
        }
        self.assertTrue(choices)
        for value in choices.values():
            self.assertTrue(
                value in mapping_ui.DIRECT_CHOICE_STRATEGIES
                or value.startswith("column::")
                or value.startswith("assumption::"),
                value,
            )

    def test_chinese_mode_uses_labels_only_for_display(self):
        app = load_coffee_app("zh")

        self.assertFalse(app.exception)
        self.assert_stable_internal_values(app)
        order_choice = next(
            item
            for item in app.selectbox
            if item.key == "generic_mapping_choice_order_id"
        )
        self.assertEqual(order_choice.value, "column::transaction_id")
        self.assertIn("映射来源列：transaction_id", order_choice.options)

    def test_english_mode_uses_labels_only_for_display(self):
        app = load_coffee_app("en")

        self.assertFalse(app.exception)
        self.assert_stable_internal_values(app)
        order_choice = next(
            item
            for item in app.selectbox
            if item.key == "generic_mapping_choice_order_id"
        )
        self.assertEqual(order_choice.value, "column::transaction_id")
        self.assertIn("Map from source: transaction_id", order_choice.options)

    def test_partial_chinese_mapping_survives_switch_to_english(self):
        app = load_coffee_app("zh")
        next(
            item
            for item in app.checkbox
            if item.key == "generic_mapping_confirm_order_id"
        ).check().run(timeout=20)
        before = mapping_state(app)

        next(
            item for item in app.selectbox if item.key == "ui_language"
        ).select("en").run(timeout=20)

        self.assertFalse(app.exception)
        self.assertEqual(mapping_state(app), before)
        self.assertEqual(
            app.session_state["generic_mapping_choice_order_id"],
            "column::transaction_id",
        )

    def test_partial_english_mapping_survives_switch_to_chinese(self):
        app = load_coffee_app("en")
        next(
            item
            for item in app.checkbox
            if item.key == "generic_mapping_confirm_order_id"
        ).check().run(timeout=20)
        before = mapping_state(app)

        next(
            item for item in app.selectbox if item.key == "ui_language"
        ).select("zh").run(timeout=20)

        self.assertFalse(app.exception)
        self.assertEqual(mapping_state(app), before)
        self.assertEqual(
            app.session_state["generic_mapping_choice_order_id"],
            "column::transaction_id",
        )


class ActualEnglishWorkbookEndToEndTests(unittest.TestCase):
    workbook_path = Path(
        "/Users/xiaoma/Desktop/test data/"
        "Sales_Report_Dashboard_功能验收数据包_兼容版/"
        "03_English_MultiTable_Clean.xlsx"
    )

    @unittest.skipUnless(workbook_path.is_file(), "Acceptance workbook not found")
    def test_actual_english_workbook_mapping_preflight_and_report(self):
        discovery = discover_relationships(read_tabular_sources(self.workbook_path))
        fact = next(
            profile
            for profile in discovery.table_profiles
            if profile.table_name == "Sales"
        )
        decisions = [
            approve_relationship(candidate)
            for candidate in discovery.relationships
            if candidate.left_table == "Sales" and not candidate.blocked
        ]
        plan = build_approved_join_plan(discovery, fact.table_id, decisions)
        merge = execute_approved_join_plan(discovery, plan)
        source_roles = build_source_entity_role_map(discovery, fact.table_id)
        recommendations = recommend_standard_field_mappings(
            merge.merged_frame, source_roles
        )
        mapping = generate_unified_orders(
            merge.merged_frame,
            selections_from_recommendations(recommendations, confirmed=True),
            source_entity_roles=source_roles,
        )
        preflight = run_generic_report_preflight(
            mapping,
            original_fact_row_count=fact.row_count,
            merged_row_count=merge.final_row_count,
        )
        report = generate_generic_report(
            mapping_result=mapping,
            preflight=preflight,
            discovery_result=discovery,
            plan=plan,
            decisions={item.original_candidate_id: item for item in decisions},
        )

        self.assertEqual(
            [profile.table_name for profile in discovery.table_profiles],
            ["Sales", "Products", "Customers", "Stores"],
        )
        self.assertEqual(len(plan.steps), 3)
        self.assertTrue(merge.success, merge.error_message)
        self.assertEqual(merge.fact_row_count, 96)
        self.assertEqual(merge.final_row_count, 96)
        self.assertTrue(mapping.success, mapping.errors)
        self.assertTrue(preflight.can_generate)
        self.assertEqual(report["status"], "ready")
        self.assertEqual(len(report["report_tables"]["enriched_orders"]), 96)
        self.assertTrue(report["excel_bytes"])
        self.assertTrue(report["summary_text"])


if __name__ == "__main__":
    unittest.main()
