from __future__ import annotations

from collections.abc import Mapping

import pandas as pd
import streamlit as st

from ui_i18n import get_language, t


WORKFLOW_STEPS = tuple(range(1, 9))
STATUS_NOT_STARTED = "not_started"
STATUS_CURRENT = "current"
STATUS_COMPLETED = "completed"
STATUS_ACTION_REQUIRED = "action_required"
STATUS_SKIPPED = "skipped"


def derive_workflow_statuses(state: Mapping) -> dict[int, str]:
    """Derive display-only workflow state from stable internal session keys."""
    discovery = state.get("generic_discovery_result")
    tables = tuple(getattr(discovery, "tables", ())) if discovery else ()
    table_count = len(tables)
    single_table = table_count == 1
    fact_table_id = state.get("generic_fact_table_id")
    decisions = state.get("generic_relationship_decisions", {})
    approved_count = sum(
        getattr(decision, "status", None) == "approved"
        for decision in decisions.values()
    )
    plan = state.get("generic_approved_plan")
    merge_result = state.get("generic_merge_result")
    mapping_result = state.get("generic_standard_mapping_result")
    report_result = state.get("generic_report_result")

    statuses = {step: STATUS_NOT_STARTED for step in WORKFLOW_STEPS}
    statuses[1] = STATUS_COMPLETED if discovery else STATUS_CURRENT
    if not discovery:
        return statuses

    statuses[2] = STATUS_COMPLETED
    statuses[3] = (
        STATUS_COMPLETED
        if single_table or fact_table_id
        else STATUS_ACTION_REQUIRED
    )

    if single_table:
        statuses[4] = STATUS_SKIPPED
        statuses[5] = STATUS_SKIPPED
    else:
        if approved_count:
            statuses[4] = STATUS_COMPLETED
        elif fact_table_id:
            statuses[4] = STATUS_ACTION_REQUIRED
        else:
            statuses[4] = STATUS_NOT_STARTED

        if getattr(merge_result, "success", False):
            statuses[5] = STATUS_COMPLETED
        elif plan is not None:
            statuses[5] = STATUS_CURRENT
        elif approved_count:
            statuses[5] = STATUS_ACTION_REQUIRED

    merge_ready = single_table or getattr(merge_result, "success", False)
    if getattr(mapping_result, "success", False):
        statuses[6] = STATUS_COMPLETED
    elif mapping_result is not None:
        statuses[6] = STATUS_ACTION_REQUIRED
    elif merge_ready:
        statuses[6] = STATUS_CURRENT

    if report_result is not None:
        statuses[7] = STATUS_COMPLETED
        statuses[8] = STATUS_COMPLETED
    elif state.get("generic_report_error"):
        statuses[7] = STATUS_ACTION_REQUIRED
        statuses[8] = STATUS_ACTION_REQUIRED
    elif getattr(mapping_result, "success", False):
        statuses[7] = STATUS_CURRENT
        statuses[8] = STATUS_NOT_STARTED
    return statuses


def workflow_records(state: Mapping, language: str = "en") -> list[dict]:
    statuses = derive_workflow_statuses(state)
    return [
        {
            t("workflow.step", language): f"{step}/8",
            t("workflow.name", language): t(f"step.{step}.title", language),
            t("workflow.status", language): t(
                f"workflow.status.{statuses[step]}", language
            ),
        }
        for step in WORKFLOW_STEPS
    ]


def render_workflow_progress(state: Mapping | None = None) -> None:
    state = state or st.session_state
    language = get_language(state)
    st.subheader(t("workflow.title", language))
    st.dataframe(
        pd.DataFrame(workflow_records(state, language)),
        hide_index=True,
        use_container_width=True,
    )


def render_step_guide(step_number: int) -> None:
    language = get_language()
    title = t(f"step.{step_number}.title", language)
    lines = [
        f"**{t('guide.step', language, number=step_number, total=8, title=title)}**",
        f"**{t('guide.goal', language)}:** {t(f'step.{step_number}.goal', language)}",
        f"**{t('guide.action', language)}:** {t(f'step.{step_number}.action', language)}",
        f"**{t('guide.completion', language)}:** {t(f'step.{step_number}.completion', language)}",
        f"**{t('guide.next', language)}:** {t(f'step.{step_number}.next', language)}",
    ]
    st.info("\n\n".join(lines))


def blocked_reason_key(
    action: str,
    *,
    fact_selected: bool = True,
    approved_count: int = 0,
    plan_ready: bool = False,
    incomplete_count: int = 0,
    preflight_ready: bool = True,
    confirmed: bool = False,
) -> str | None:
    if action == "build_plan":
        if not fact_selected:
            return "plan.blocked.fact"
        if approved_count == 0:
            return "plan.blocked.relationships"
    elif action == "execute_merge" and not plan_ready:
        return "merge.blocked.no_plan"
    elif action == "generate_mapping" and incomplete_count:
        return "mapping.generate_blocked"
    elif action == "generate_report":
        if not preflight_ready:
            return "preflight.generate_blocked.issues"
        if not confirmed:
            return "preflight.generate_blocked.confirm"
    return None


def render_blocked_reason(reason_key: str | None, **kwargs) -> None:
    if reason_key:
        st.warning(t(reason_key, **kwargs))


def render_glossary() -> None:
    with st.expander(t("glossary.title"), expanded=False):
        st.markdown(t("glossary.body"))
