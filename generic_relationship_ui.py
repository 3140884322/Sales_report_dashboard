from __future__ import annotations

import hashlib
import inspect

import pandas as pd
import streamlit as st

from confirmed_relationship_plan import (
    JoinPlanValidationError,
    RelationshipApprovalError,
    approve_relationship,
    build_approved_join_plan,
    edit_relationship,
    execute_approved_join_plan,
    reject_relationship,
)
from generic_relationship_state import (
    clear_generic_state_if_uploads_changed,
    invalidate_generic_mapping_state,
    invalidate_generic_plan_state,
    make_generic_upload_signature,
)
from generic_standard_mapping_ui import render_generic_standard_mapping
from relationship_discovery import (
    RelationshipDiscoveryError,
    discover_relationships_from_sources,
    evaluate_relationship_candidate,
)
from ui_guidance import (
    blocked_reason_key,
    render_blocked_reason,
    render_step_guide,
)
from ui_i18n import t


BUTTON_SUPPORTS_ICON = "icon" in inspect.signature(st.button).parameters
SINGLE_TABLE_ROUTE_MESSAGE = t("single.detected", "en")


def _button(label, icon=None, **kwargs):
    if icon and BUTTON_SUPPORTS_ICON:
        kwargs["icon"] = icon
    return st.button(label, **kwargs)


def _widget_token(candidate_id: str) -> str:
    return hashlib.md5(candidate_id.encode("utf-8")).hexdigest()[:12]


def _table_profile_by_id(discovery_result):
    return {
        profile.table_id: profile for profile in discovery_result.table_profiles
    }


def _format_table(discovery_result, table_id):
    profile = _table_profile_by_id(discovery_result)[table_id]
    return (
        f"{profile.table_name} | {profile.role_guess} | "
        f"{profile.row_count:,} {t('common.rows')}"
    )


def _column_mapping_text(left_columns, right_columns):
    return ", ".join(
        f"{left} -> {right}" for left, right in zip(left_columns, right_columns)
    )


def _candidate_title(candidate):
    return (
        f"{candidate.left_table} [{', '.join(candidate.left_columns)}] -> "
        f"{candidate.right_table} [{', '.join(candidate.right_columns)}]"
    )


def _render_candidate_metrics(candidate):
    metrics = st.columns(4)
    metrics[0].metric(t("common.confidence"), f"{candidate.confidence_score:.2f}")
    metrics[1].metric(t("common.match_rate"), f"{candidate.match_rate:.2%}")
    metrics[2].metric(
        t("relationship.right_uniqueness"), f"{candidate.right_key_uniqueness:.2%}"
    )
    metrics[3].metric(t("relationship.expected_join"), candidate.expected_join_type)

    breakdown = pd.DataFrame(
        [
            {"component": t(f"score.{component}"), "points": points}
            for component, points in candidate.score_breakdown.items()
        ]
    )
    st.dataframe(
        breakdown,
        hide_index=True,
        use_container_width=True,
        column_config={
            "component": t("relationship.breakdown.component"),
            "points": t("relationship.breakdown.points"),
        },
    )
    st.write(candidate.explanation)
    if "weak_name_high_value_overlap" in candidate.risk_flags:
        st.info(t("relationship.fallback.explanation"))
    if "key_format_mismatch" in candidate.risk_flags:
        st.warning(t("relationship.format_warning"))
    if candidate.blocked:
        st.info(t("relationship.advice.blocked"))
    elif candidate.confidence_score >= 80 and candidate.match_rate >= 0.8:
        st.info(t("relationship.advice.approve"))
    elif candidate.confidence_score >= 60:
        st.info(t("relationship.advice.review"))
    else:
        st.info(t("relationship.advice.other"))

    if candidate.risk_flags:
        flags = ", ".join(
            t(f"risk.{flag}") for flag in candidate.risk_flags
        )
        st.warning(t("relationship.risk_flags", flags=flags))
    if candidate.block_reasons:
        for reason in candidate.block_reasons:
            st.error(t("relationship.block_reason", reason=reason))


def _set_decision(original_candidate_id, decision):
    decisions = dict(st.session_state.get("generic_relationship_decisions", {}))
    decisions[original_candidate_id] = decision
    st.session_state["generic_relationship_decisions"] = decisions
    invalidate_generic_plan_state(st.session_state)


def _render_decision_status(candidate):
    decision = st.session_state.get("generic_relationship_decisions", {}).get(
        candidate.candidate_id
    )
    if decision is None:
        st.caption(t("relationship.decision.pending"))
    elif decision.status == "approved":
        key = "relationship.decision.approved_edited" if decision.edited else "relationship.decision.approved"
        st.success(t(key))
    elif decision.status == "rejected":
        key = "relationship.decision.rejected_edited" if decision.edited else "relationship.decision.rejected"
        st.warning(t(key))
    else:
        st.caption(t("relationship.decision.edited_pending"))


def _select_index(options, value):
    return options.index(value) if value in options else None


def _render_relationship_editor(discovery_result, original_candidate):
    token = _widget_token(original_candidate.candidate_id)
    st.markdown(f"##### {t('relationship.editor.title')}")
    table_ids = [profile.table_id for profile in discovery_result.table_profiles]
    left_table_id = st.selectbox(
        t("relationship.editor.left_table"),
        table_ids,
        index=_select_index(table_ids, original_candidate.left_table_id),
        format_func=lambda value: _format_table(discovery_result, value),
        key=f"generic_edit_{token}_left_table",
    )
    right_options = [table_id for table_id in table_ids if table_id != left_table_id]
    right_table_id = st.selectbox(
        t("relationship.editor.right_table"),
        right_options,
        index=_select_index(right_options, original_candidate.right_table_id),
        format_func=lambda value: _format_table(discovery_result, value),
        key=f"generic_edit_{token}_{left_table_id}_right_table",
    )
    key_size = st.radio(
        t("relationship.editor.key_size"),
        [1, 2],
        index=0 if len(original_candidate.left_columns) == 1 else 1,
        format_func=lambda value: t("relationship.editor.single") if value == 1 else t("relationship.editor.composite"),
        horizontal=True,
        key=f"generic_edit_{token}_key_size",
    )

    profiles = _table_profile_by_id(discovery_result)
    left_options = [
        column.column_name for column in profiles[left_table_id].columns
    ]
    right_column_options = [
        column.column_name for column in profiles[right_table_id].columns
    ]
    selected_left = []
    selected_right = []
    for index in range(key_size):
        default_left = (
            original_candidate.left_columns[index]
            if left_table_id == original_candidate.left_table_id
            and index < len(original_candidate.left_columns)
            else None
        )
        default_right = (
            original_candidate.right_columns[index]
            if right_table_id == original_candidate.right_table_id
            and index < len(original_candidate.right_columns)
            else None
        )
        columns = st.columns(2)
        selected_left.append(
            columns[0].selectbox(
                t("relationship.editor.left_key", number=index + 1),
                left_options,
                index=_select_index(left_options, default_left),
                placeholder=t("relationship.editor.select_left"),
                key=(
                    f"generic_edit_{token}_{left_table_id}_{key_size}_"
                    f"left_column_{index}"
                ),
            )
        )
        selected_right.append(
            columns[1].selectbox(
                t("relationship.editor.right_key", number=index + 1),
                right_column_options,
                index=_select_index(right_column_options, default_right),
                placeholder=t("relationship.editor.select_right"),
                key=(
                    f"generic_edit_{token}_{right_table_id}_{key_size}_"
                    f"right_column_{index}"
                ),
            )
        )

    action_columns = st.columns(2)
    with action_columns[0]:
        recalculate = _button(
            t("relationship.editor.recalculate"),
            icon=":material/calculate:",
            key=f"generic_edit_{token}_recalculate",
            use_container_width=True,
        )
    with action_columns[1]:
        close_editor = _button(
            t("relationship.editor.close"),
            icon=":material/close:",
            key=f"generic_edit_{token}_close",
            use_container_width=True,
        )
    if close_editor:
        st.session_state.pop("generic_editing_candidate_id", None)
        st.rerun()

    if recalculate:
        try:
            edited_candidate = evaluate_relationship_candidate(
                discovery_result,
                left_table_id,
                tuple(selected_left),
                right_table_id,
                tuple(selected_right),
            )
            edited_candidates = dict(
                st.session_state.get("generic_edited_candidates", {})
            )
            edited_candidates[original_candidate.candidate_id] = edited_candidate
            st.session_state["generic_edited_candidates"] = edited_candidates
            _set_decision(
                original_candidate.candidate_id,
                edit_relationship(original_candidate, edited_candidate),
            )
            st.rerun()
        except (RelationshipDiscoveryError, KeyError) as error:
            st.error(str(error))

    edited_candidate = st.session_state.get("generic_edited_candidates", {}).get(
        original_candidate.candidate_id
    )
    if edited_candidate is None:
        return

    st.markdown(f"##### {t('relationship.editor.recalculated')}")
    st.write(_candidate_title(edited_candidate))
    _render_candidate_metrics(edited_candidate)
    approve_columns = st.columns(2)
    with approve_columns[0]:
        approve_edited = _button(
            t("relationship.editor.approve"),
            icon=":material/check:",
            key=f"generic_edit_{token}_approve_edited",
            disabled=edited_candidate.blocked,
            use_container_width=True,
        )
    with approve_columns[1]:
        reject_edited = _button(
            t("relationship.editor.reject"),
            icon=":material/close:",
            key=f"generic_edit_{token}_reject_edited",
            use_container_width=True,
        )
    if approve_edited:
        try:
            _set_decision(
                original_candidate.candidate_id,
                approve_relationship(
                    edited_candidate,
                    original_candidate_id=original_candidate.candidate_id,
                    edited=True,
                ),
            )
            st.session_state.pop("generic_editing_candidate_id", None)
            st.rerun()
        except RelationshipApprovalError as error:
            st.error(str(error))
    if reject_edited:
        _set_decision(
            original_candidate.candidate_id,
            reject_relationship(
                edited_candidate,
                original_candidate_id=original_candidate.candidate_id,
                edited=True,
            ),
        )
        st.session_state.pop("generic_editing_candidate_id", None)
        st.rerun()


def _render_candidate(discovery_result, candidate, embedded=False):
    context = st.container() if embedded else st.expander(_candidate_title(candidate))
    with context:
        if embedded:
            st.markdown(f"##### {_candidate_title(candidate)}")
        _render_candidate_metrics(candidate)
        _render_decision_status(candidate)
        token = _widget_token(candidate.candidate_id)
        actions = st.columns(3)
        with actions[0]:
            approve_clicked = _button(
                t("relationship.approve"),
                icon=":material/check:",
                key=f"generic_candidate_{token}_approve",
                disabled=candidate.blocked,
                use_container_width=True,
            )
        with actions[1]:
            edit_clicked = _button(
                t("relationship.edit"),
                icon=":material/edit:",
                key=f"generic_candidate_{token}_edit",
                use_container_width=True,
            )
        with actions[2]:
            reject_clicked = _button(
                t("relationship.reject"),
                icon=":material/close:",
                key=f"generic_candidate_{token}_reject",
                use_container_width=True,
            )
        if approve_clicked:
            try:
                _set_decision(
                    candidate.candidate_id, approve_relationship(candidate)
                )
                st.session_state.pop("generic_editing_candidate_id", None)
                st.rerun()
            except RelationshipApprovalError as error:
                st.error(str(error))
        if edit_clicked:
            st.session_state["generic_editing_candidate_id"] = candidate.candidate_id
            st.rerun()
        if reject_clicked:
            _set_decision(
                candidate.candidate_id, reject_relationship(candidate)
            )
            st.session_state.pop("generic_editing_candidate_id", None)
            st.rerun()

        if st.session_state.get("generic_editing_candidate_id") == candidate.candidate_id:
            st.divider()
            _render_relationship_editor(discovery_result, candidate)


def _render_candidate_groups(discovery_result):
    relationships = discovery_result.relationships
    recommended = [
        candidate
        for candidate in relationships
        if not candidate.blocked and candidate.confidence_score >= 80
    ]
    needs_review = [
        candidate
        for candidate in relationships
        if not candidate.blocked and 60 <= candidate.confidence_score < 80
    ]
    other = [
        candidate
        for candidate in relationships
        if not candidate.blocked and candidate.confidence_score < 60
    ]
    blocked = [candidate for candidate in relationships if candidate.blocked]

    st.markdown(f"#### {t('relationships.recommended', count=len(recommended))}")
    for candidate in recommended:
        _render_candidate(discovery_result, candidate)

    st.markdown(f"#### {t('relationships.needs_review', count=len(needs_review))}")
    for candidate in needs_review:
        _render_candidate(discovery_result, candidate)

    with st.expander(t("relationships.other", count=len(other)), expanded=False):
        for index, candidate in enumerate(other):
            if index:
                st.divider()
            _render_candidate(discovery_result, candidate, embedded=True)

    st.markdown(f"#### {t('relationships.blocked', count=len(blocked))}")
    for candidate in blocked:
        _render_candidate(discovery_result, candidate)


def _table_profile_records(discovery_result):
    return [
        {
            "table": profile.table_name,
            "source": profile.source_name,
            "sheet": profile.sheet_name or "",
            "encoding": profile.encoding or "",
            "rows": profile.row_count,
            "columns": profile.column_count,
            "role": profile.role_guess,
            "role_confidence": profile.role_confidence,
            "role_score_breakdown": ", ".join(
                f"{key}={value:.3f}"
                for key, value in profile.role_score_breakdown.items()
            ),
            "entity_role": profile.entity_role,
            "entity_confidence": profile.entity_role_confidence,
        }
        for profile in discovery_result.table_profiles
    ]


def _plan_records(plan):
    return [
        {
            "step": step.step_id,
            "relationship": (
                f"{step.left_table} [{', '.join(step.left_columns)}] -> "
                f"{step.right_table} [{', '.join(step.right_columns)}]"
            ),
            "confidence": step.confidence_score,
            "match_rate": step.match_rate,
            "right_key_uniqueness": step.right_key_uniqueness,
            "expected_join": step.expected_join_type,
            "edited": step.edited,
        }
        for step in plan.steps
    ]


def _diagnostic_records(merge_result):
    return [
        {
            "step": diagnostic.step_id,
            "right_table": diagnostic.right_table,
            "rows_before": diagnostic.rows_before,
            "rows_after": diagnostic.rows_after,
            "matched_rows": diagnostic.matched_rows,
            "unmatched_rows": diagnostic.unmatched_rows,
            "match_rate": diagnostic.match_rate,
            "row_growth": diagnostic.row_growth,
            "validation_status": diagnostic.validation_status,
            "error": diagnostic.error_message,
        }
        for diagnostic in merge_result.diagnostics
    ]


def build_single_table_join_result(discovery_result):
    """Build and execute the zero-relationship plan for a one-table upload."""
    if len(discovery_result.tables) != 1:
        raise ValueError("Single-table routing requires exactly one detected table.")

    fact_table_id = discovery_result.tables[0].table_id
    plan = build_approved_join_plan(discovery_result, fact_table_id, {})
    merge_result = execute_approved_join_plan(discovery_result, plan)
    return plan, merge_result


def _initialize_discovery_state(discovery_result):
    st.session_state["generic_discovery_result"] = discovery_result
    st.session_state["generic_relationship_decisions"] = {}
    st.session_state["generic_edited_candidates"] = {}
    st.session_state.pop("generic_fact_table_id", None)
    st.session_state.pop("generic_fact_table_snapshot", None)
    invalidate_generic_plan_state(st.session_state)


def _render_single_table_route(discovery_result):
    table = discovery_result.tables[0]
    plan = st.session_state.get("generic_approved_plan")
    merge_result = st.session_state.get("generic_merge_result")
    if plan is None or merge_result is None:
        plan, merge_result = build_single_table_join_result(discovery_result)
        st.session_state["generic_fact_table_id"] = table.table_id
        st.session_state["generic_fact_table_snapshot"] = table.table_id
        st.session_state["generic_approved_plan"] = plan
        st.session_state["generic_merge_result"] = merge_result

    render_step_guide(3)
    st.info(t("single.detected"))
    route_metrics = st.columns(3)
    route_metrics[0].metric(t("single.main_table"), table.table_name)
    route_metrics[1].metric(t("common.rows"), f"{len(table.frame):,}")
    route_metrics[2].metric(t("single.relationship_count"), "0")

    if not merge_result.success or merge_result.merged_frame is None:
        st.error(merge_result.error_message or t("single.failed"))
        return None

    return render_generic_standard_mapping(
        merge_result,
        discovery_result=discovery_result,
        plan=plan,
        decisions={},
    )


def _render_plan_and_merge(discovery_result, fact_table_id):
    decisions = st.session_state.get("generic_relationship_decisions", {})
    approved_count = sum(
        decision.status == "approved" for decision in decisions.values()
    )
    render_step_guide(5)
    st.subheader(t("plan.title"))
    st.write(t("plan.count", count=approved_count))
    st.info(t("plan.explanation"))
    build_reason = blocked_reason_key(
        "build_plan",
        fact_selected=bool(fact_table_id),
        approved_count=approved_count,
    )
    render_blocked_reason(build_reason)
    build_clicked = _button(
        t("plan.build"),
        icon=":material/account_tree:",
        key="generic_build_approved_plan",
        disabled=bool(build_reason),
    )
    if build_clicked:
        try:
            invalidate_generic_mapping_state(st.session_state)
            plan = build_approved_join_plan(
                discovery_result, fact_table_id, decisions
            )
            st.session_state["generic_approved_plan"] = plan
            st.session_state.pop("generic_merge_result", None)
            st.session_state.pop("generic_plan_error", None)
            st.rerun()
        except JoinPlanValidationError as error:
            st.session_state.pop("generic_approved_plan", None)
            st.session_state.pop("generic_merge_result", None)
            st.session_state["generic_plan_error"] = error.errors

    plan_errors = st.session_state.get("generic_plan_error", ())
    for error in plan_errors:
        st.error(t("plan.error", error=error))

    plan = st.session_state.get("generic_approved_plan")
    if plan is None:
        merge_reason = blocked_reason_key("execute_merge", plan_ready=False)
        render_blocked_reason(merge_reason)
        _button(
            t("merge.execute"),
            icon=":material/play_arrow:",
            key="generic_execute_safe_merge_disabled",
            disabled=True,
        )
        return

    st.dataframe(
        pd.DataFrame(_plan_records(plan)),
        hide_index=True,
        use_container_width=True,
        column_config={
            "step": t("table.column.step"),
            "relationship": t("table.column.relationship"),
            "confidence": t("common.confidence"),
            "match_rate": st.column_config.NumberColumn(
                t("common.match_rate"), format="percent"
            ),
            "right_key_uniqueness": st.column_config.NumberColumn(
                t("relationship.right_uniqueness"), format="percent"
            ),
            "expected_join": t("relationship.expected_join"),
            "edited": t("table.column.edited"),
        },
    )
    execute_clicked = _button(
        t("merge.execute"),
        icon=":material/play_arrow:",
        key="generic_execute_safe_merge",
    )
    if execute_clicked:
        with st.spinner(t("merge.spinner")):
            invalidate_generic_mapping_state(st.session_state)
            st.session_state["generic_merge_result"] = execute_approved_join_plan(
                discovery_result, plan
            )
        st.rerun()

    merge_result = st.session_state.get("generic_merge_result")
    if merge_result is None:
        return

    st.subheader(t("merge.title"))
    if merge_result.success:
        st.success(t("merge.success"))
    else:
        st.error(t("merge.error", error=merge_result.error_message))
    st.caption(t("merge.explanation"))
    st.dataframe(
        pd.DataFrame(_diagnostic_records(merge_result)),
        hide_index=True,
        use_container_width=True,
        column_config={
            "step": t("table.column.step"),
            "right_table": t("table.column.right_table"),
            "rows_before": t("table.column.rows_before"),
            "rows_after": t("table.column.rows_after"),
            "matched_rows": t("table.column.matched_rows"),
            "unmatched_rows": t("table.column.unmatched_rows"),
            "match_rate": st.column_config.NumberColumn(
                t("common.match_rate"), format="percent"
            ),
            "row_growth": t("table.column.row_growth"),
            "validation_status": t("table.column.validation"),
            "error": t("table.column.error"),
        },
    )
    if not merge_result.success or merge_result.merged_frame is None:
        return

    row_metrics = st.columns(2)
    row_metrics[0].metric(t("merge.original_rows"), f"{merge_result.fact_row_count:,}")
    row_metrics[1].metric(t("merge.final_rows"), f"{merge_result.final_row_count:,}")
    st.markdown(f"#### {t('merge.preview')}")
    st.dataframe(
        merge_result.merged_frame.head(20),
        hide_index=True,
        use_container_width=True,
    )
    return render_generic_standard_mapping(
        merge_result,
        discovery_result=discovery_result,
        plan=plan,
        decisions=decisions,
    )


def render_generic_relationship_mode():
    """Render the unified one-or-more-table data preparation flow."""
    render_step_guide(1)
    st.subheader(t("upload.title"))
    with st.expander(t("upload.help.title"), expanded=False):
        st.markdown(t("upload.help.body"))
    uploaded_files = st.file_uploader(
        t("upload.label"),
        type=["csv", "xlsx"],
        accept_multiple_files=True,
        key="generic_uploaded_files",
    )
    signature = make_generic_upload_signature(uploaded_files)
    files_changed = clear_generic_state_if_uploads_changed(
        st.session_state, signature
    )
    if files_changed and uploaded_files:
        st.info(t("upload.changed"))

    discovery_result = st.session_state.get("generic_discovery_result")
    if uploaded_files and discovery_result is None:
        try:
            with st.spinner(t("upload.spinner")):
                discovery_result = discover_relationships_from_sources(uploaded_files)
            _initialize_discovery_state(discovery_result)
        except Exception as error:
            error_key = getattr(error, "ui_message_key", None)
            user_message = t(error_key) if error_key else str(error)
            st.error(t("upload.failed", error=user_message))
            return None

    if discovery_result is None:
        return

    st.success(
        t(
            "upload.summary",
            file_count=len(uploaded_files or ()),
            table_count=len(discovery_result.tables),
        )
    )
    render_step_guide(2)
    st.subheader(t("tables.title"))
    st.write(t("tables.explanation"))
    with st.expander(t("tables.expander"), expanded=True):
        st.caption(t("tables.terms"))
        st.dataframe(
            pd.DataFrame(_table_profile_records(discovery_result)),
            hide_index=True,
            use_container_width=True,
            column_config={
                "table": t("table.column.table"),
                "source": t("table.column.source"),
                "sheet": t("table.column.sheet"),
                "encoding": t("table.column.encoding"),
                "rows": t("table.column.rows"),
                "columns": t("table.column.columns"),
                "role": t("table.column.role"),
                "role_score_breakdown": t("table.column.role_breakdown"),
                "role_confidence": st.column_config.NumberColumn(
                    t("table.column.role_confidence"), format="percent"
                ),
                "entity_role": t("table.column.entity_role"),
                "entity_confidence": st.column_config.NumberColumn(
                    t("table.column.entity_confidence"), format="percent"
                ),
            },
        )
    st.warning(t("tables.warning"))

    if len(discovery_result.tables) == 1:
        return _render_single_table_route(discovery_result)

    render_step_guide(3)
    st.subheader(t("fact.title"))
    st.write(t("fact.guidance"))
    table_ids = [profile.table_id for profile in discovery_result.table_profiles]
    recommended_profile = max(
        discovery_result.table_profiles,
        key=lambda profile: (
            profile.role_guess == "fact",
            profile.role_confidence,
            profile.row_count,
        ),
    )
    st.info(t("fact.recommendation", table=recommended_profile.table_name))
    st.caption(t("fact.recommendation_reason"))
    fact_table_id = st.selectbox(
        t("fact.label"),
        [None] + table_ids,
        index=0,
        format_func=lambda value: (
            t("fact.placeholder")
            if value is None
            else _format_table(discovery_result, value)
        ),
        key="generic_fact_table_id",
    )
    if st.session_state.get("generic_fact_table_snapshot") != fact_table_id:
        st.session_state["generic_fact_table_snapshot"] = fact_table_id
        invalidate_generic_plan_state(st.session_state)

    if not fact_table_id:
        st.warning(t("fact.blocked"))

    render_step_guide(4)
    st.subheader(t("relationships.title"))
    with st.expander(t("relationships.help.title"), expanded=False):
        st.markdown(t("relationships.help.body"))
        st.markdown(t("relationships.metrics_help"))
    if discovery_result.relationships:
        _render_candidate_groups(discovery_result)
    else:
        st.info(t("relationships.no_candidates"))
        st.caption(t("relationships.no_candidates_guidance"))
        if discovery_result.diagnostics.get("format_warnings"):
            st.warning(t("relationship.format_warning"))

    return _render_plan_and_merge(discovery_result, fact_table_id)
