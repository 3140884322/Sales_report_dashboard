from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

from standard_field_mapping import (
    REQUIRED_TRANSACTION_FIELDS,
    recommend_standard_field_mappings,
)
from ui_guidance import (
    STATUS_COMPLETED,
    STATUS_SKIPPED,
    blocked_reason_key,
    derive_workflow_statuses,
    workflow_records,
)
from ui_i18n import (
    EN,
    FIELD_DISPLAY_NAMES,
    TRANSLATIONS,
    ZH,
    field_label,
    set_language,
    t,
)


class TranslationTests(unittest.TestCase):
    def test_chinese_and_english_keys_have_complete_parity(self):
        self.assertEqual(set(EN), set(ZH))

    def test_missing_translation_falls_back_to_english_then_key(self):
        reduced_zh = dict(ZH)
        reduced_zh.pop("app.title")
        with patch.dict(TRANSLATIONS, {"zh": reduced_zh}):
            self.assertEqual(t("app.title", "zh"), EN["app.title"])
            self.assertEqual(t("missing.test.key", "zh"), "missing.test.key")

    def test_language_switch_preserves_workflow_session_state(self):
        discovery = object()
        decisions = {"relationship": object()}
        mapping = object()
        state = {
            "generic_uploaded_files": [object()],
            "generic_discovery_result": discovery,
            "generic_relationship_decisions": decisions,
            "generic_standard_mapping_result": mapping,
        }

        set_language(state, "en")

        self.assertIs(state["generic_discovery_result"], discovery)
        self.assertIs(state["generic_relationship_decisions"], decisions)
        self.assertIs(state["generic_standard_mapping_result"], mapping)
        self.assertEqual(state["ui_language"], "en")

    def test_core_mapping_recommendations_are_language_independent(self):
        frame = pd.DataFrame(
            {
                "Order ID": [1, 2],
                "Order Date": ["2024-01-01", "2024-01-02"],
                "Product ID": ["A", "B"],
                "Unit Price": [10.0, 20.0],
                "Quantity": [1, 2],
            }
        )
        state = {}
        set_language(state, "en")
        english = recommend_standard_field_mappings(frame)
        set_language(state, "zh")
        chinese = recommend_standard_field_mappings(frame)

        self.assertEqual(english, chinese)

    def test_internal_standard_fields_are_not_translated(self):
        expected = ("order_id", "date", "product_id", "unit_price", "quantity")
        self.assertEqual(REQUIRED_TRANSACTION_FIELDS, expected)
        for field in expected:
            self.assertTrue(field_label(field, "zh").startswith(field))
            self.assertIn(field, FIELD_DISPLAY_NAMES["zh"])


class WorkflowGuidanceTests(unittest.TestCase):
    def test_single_table_marks_relationship_and_merge_as_skipped(self):
        state = {
            "generic_discovery_result": SimpleNamespace(tables=(object(),)),
            "generic_fact_table_id": "orders",
        }
        statuses = derive_workflow_statuses(state)

        self.assertEqual(statuses[4], STATUS_SKIPPED)
        self.assertEqual(statuses[5], STATUS_SKIPPED)
        records = workflow_records(state, "en")
        self.assertIn("Skipped", records[3]["Status"])
        self.assertIn("Skipped", records[4]["Status"])

    def test_multi_table_completed_path_includes_all_eight_steps(self):
        state = {
            "generic_discovery_result": SimpleNamespace(tables=(object(), object())),
            "generic_fact_table_id": "orders",
            "generic_relationship_decisions": {
                "candidate": SimpleNamespace(status="approved")
            },
            "generic_approved_plan": object(),
            "generic_merge_result": SimpleNamespace(success=True),
            "generic_standard_mapping_result": SimpleNamespace(success=True),
            "generic_report_result": object(),
        }
        statuses = derive_workflow_statuses(state)

        self.assertEqual(len(statuses), 8)
        self.assertTrue(all(status == STATUS_COMPLETED for status in statuses.values()))

    def test_disabled_action_reason_keys_are_dynamic(self):
        self.assertEqual(
            blocked_reason_key("build_plan", fact_selected=False),
            "plan.blocked.fact",
        )
        self.assertEqual(
            blocked_reason_key("build_plan", approved_count=0),
            "plan.blocked.relationships",
        )
        self.assertEqual(
            blocked_reason_key("execute_merge", plan_ready=False),
            "merge.blocked.no_plan",
        )
        self.assertEqual(
            blocked_reason_key("generate_mapping", incomplete_count=2),
            "mapping.generate_blocked",
        )
        self.assertEqual(
            blocked_reason_key(
                "generate_report", preflight_ready=True, confirmed=False
            ),
            "preflight.generate_blocked.confirm",
        )

    def test_workflow_records_are_localized_without_changing_status_keys(self):
        state = {}
        english = workflow_records(state, "en")
        chinese = workflow_records(state, "zh")

        self.assertEqual(len(english), len(chinese))
        self.assertEqual(len(english), 8)
        self.assertNotEqual(english[0], chinese[0])
        self.assertEqual(derive_workflow_statuses(state)[1], "current")


if __name__ == "__main__":
    unittest.main()
