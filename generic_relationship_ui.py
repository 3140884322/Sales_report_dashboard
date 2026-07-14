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


BUTTON_SUPPORTS_ICON = "icon" in inspect.signature(st.button).parameters
SINGLE_TABLE_ROUTE_MESSAGE = (
    "One table was detected. No table relationships are required. "
    "Continue to field mapping."
)


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
        f"{profile.row_count:,} rows"
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
    metrics[0].metric("Confidence", f"{candidate.confidence_score:.2f}")
    metrics[1].metric("Match rate", f"{candidate.match_rate:.2%}")
    metrics[2].metric(
        "Right key uniqueness", f"{candidate.right_key_uniqueness:.2%}"
    )
    metrics[3].metric("Expected join", candidate.expected_join_type)

    breakdown = pd.DataFrame(
        [
            {"component": component, "points": points}
            for component, points in candidate.score_breakdown.items()
        ]
    )
    st.dataframe(breakdown, hide_index=True, use_container_width=True)
    st.write(candidate.explanation)

    if candidate.risk_flags:
        st.warning("Risk flags: " + ", ".join(candidate.risk_flags))
    if candidate.block_reasons:
        for reason in candidate.block_reasons:
            st.error(reason)


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
        st.caption("Decision: Pending")
    elif decision.status == "approved":
        label = "Approved (edited)" if decision.edited else "Approved"
        st.success(f"Decision: {label}")
    elif decision.status == "rejected":
        label = "Rejected (edited)" if decision.edited else "Rejected"
        st.warning(f"Decision: {label}")
    else:
        st.caption("Decision: Edited, pending explicit approval")


def _select_index(options, value):
    return options.index(value) if value in options else None


def _render_relationship_editor(discovery_result, original_candidate):
    token = _widget_token(original_candidate.candidate_id)
    st.markdown("##### Edit relationship")
    table_ids = [profile.table_id for profile in discovery_result.table_profiles]
    left_table_id = st.selectbox(
        "Left table",
        table_ids,
        index=_select_index(table_ids, original_candidate.left_table_id),
        format_func=lambda value: _format_table(discovery_result, value),
        key=f"generic_edit_{token}_left_table",
    )
    right_options = [table_id for table_id in table_ids if table_id != left_table_id]
    right_table_id = st.selectbox(
        "Right table",
        right_options,
        index=_select_index(right_options, original_candidate.right_table_id),
        format_func=lambda value: _format_table(discovery_result, value),
        key=f"generic_edit_{token}_{left_table_id}_right_table",
    )
    key_size = st.radio(
        "Key size",
        [1, 2],
        index=0 if len(original_candidate.left_columns) == 1 else 1,
        format_func=lambda value: "Single column" if value == 1 else "Two-column composite",
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
                f"Left key {index + 1}",
                left_options,
                index=_select_index(left_options, default_left),
                placeholder="Select a left column",
                key=(
                    f"generic_edit_{token}_{left_table_id}_{key_size}_"
                    f"left_column_{index}"
                ),
            )
        )
        selected_right.append(
            columns[1].selectbox(
                f"Right key {index + 1}",
                right_column_options,
                index=_select_index(right_column_options, default_right),
                placeholder="Select a right column",
                key=(
                    f"generic_edit_{token}_{right_table_id}_{key_size}_"
                    f"right_column_{index}"
                ),
            )
        )

    action_columns = st.columns(2)
    with action_columns[0]:
        recalculate = _button(
            "Recalculate score & safety",
            icon=":material/calculate:",
            key=f"generic_edit_{token}_recalculate",
            use_container_width=True,
        )
    with action_columns[1]:
        close_editor = _button(
            "Close editor",
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

    st.markdown("##### Recalculated candidate")
    st.write(_candidate_title(edited_candidate))
    _render_candidate_metrics(edited_candidate)
    approve_columns = st.columns(2)
    with approve_columns[0]:
        approve_edited = _button(
            "Approve edited",
            icon=":material/check:",
            key=f"generic_edit_{token}_approve_edited",
            disabled=edited_candidate.blocked,
            use_container_width=True,
        )
    with approve_columns[1]:
        reject_edited = _button(
            "Reject edited",
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
                "Approve",
                icon=":material/check:",
                key=f"generic_candidate_{token}_approve",
                disabled=candidate.blocked,
                use_container_width=True,
            )
        with actions[1]:
            edit_clicked = _button(
                "Edit",
                icon=":material/edit:",
                key=f"generic_candidate_{token}_edit",
                use_container_width=True,
            )
        with actions[2]:
            reject_clicked = _button(
                "Reject",
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

    st.markdown(f"#### Recommended ({len(recommended)})")
    for candidate in recommended:
        _render_candidate(discovery_result, candidate)

    st.markdown(f"#### Needs Review ({len(needs_review)})")
    for candidate in needs_review:
        _render_candidate(discovery_result, candidate)

    with st.expander(f"Other Candidates ({len(other)})", expanded=False):
        for index, candidate in enumerate(other):
            if index:
                st.divider()
            _render_candidate(discovery_result, candidate, embedded=True)

    st.markdown(f"#### Blocked ({len(blocked)})")
    for candidate in blocked:
        _render_candidate(discovery_result, candidate)


def _table_profile_records(discovery_result):
    return [
        {
            "table": profile.table_name,
            "source": profile.source_name,
            "sheet": profile.sheet_name or "",
            "rows": profile.row_count,
            "columns": profile.column_count,
            "role": profile.role_guess,
            "role_confidence": profile.role_confidence,
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

    st.info(SINGLE_TABLE_ROUTE_MESSAGE)
    route_metrics = st.columns(3)
    route_metrics[0].metric("Main transaction table", table.table_name)
    route_metrics[1].metric("Rows", f"{len(table.frame):,}")
    route_metrics[2].metric("Confirmed relationships", "0")

    if not merge_result.success or merge_result.merged_frame is None:
        st.error(merge_result.error_message or "Single-table preparation failed.")
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
    st.subheader("Approved Join Plan")
    st.write(f"Explicitly approved relationships: {approved_count}")
    build_clicked = _button(
        "Build Approved Join Plan",
        icon=":material/account_tree:",
        key="generic_build_approved_plan",
        disabled=(
            not fact_table_id
            or (approved_count == 0 and len(discovery_result.tables) > 1)
        ),
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
        st.error(error)

    plan = st.session_state.get("generic_approved_plan")
    if plan is None:
        return

    st.dataframe(
        pd.DataFrame(_plan_records(plan)),
        hide_index=True,
        use_container_width=True,
        column_config={
            "match_rate": st.column_config.NumberColumn(format="percent"),
            "right_key_uniqueness": st.column_config.NumberColumn(format="percent"),
        },
    )
    execute_clicked = _button(
        "Execute Safe Merge",
        icon=":material/play_arrow:",
        key="generic_execute_safe_merge",
    )
    if execute_clicked:
        with st.spinner("Executing approved many-to-one joins..."):
            invalidate_generic_mapping_state(st.session_state)
            st.session_state["generic_merge_result"] = execute_approved_join_plan(
                discovery_result, plan
            )
        st.rerun()

    merge_result = st.session_state.get("generic_merge_result")
    if merge_result is None:
        return

    st.subheader("Merge Execution Summary")
    if merge_result.success:
        st.success("Approved join plan completed without row growth.")
    else:
        st.error(merge_result.error_message)
    st.dataframe(
        pd.DataFrame(_diagnostic_records(merge_result)),
        hide_index=True,
        use_container_width=True,
        column_config={"match_rate": st.column_config.NumberColumn(format="percent")},
    )
    if not merge_result.success or merge_result.merged_frame is None:
        return

    row_metrics = st.columns(2)
    row_metrics[0].metric("Original fact rows", f"{merge_result.fact_row_count:,}")
    row_metrics[1].metric("Final merged rows", f"{merge_result.final_row_count:,}")
    st.markdown("#### Merged dataset preview")
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
    st.subheader("Upload")
    uploaded_files = st.file_uploader(
        "Sales data files",
        type=["csv", "xlsx"],
        accept_multiple_files=True,
        key="generic_uploaded_files",
    )
    signature = make_generic_upload_signature(uploaded_files)
    files_changed = clear_generic_state_if_uploads_changed(
        st.session_state, signature
    )
    if files_changed and uploaded_files:
        st.info("Files changed. Previous discovery, decisions, plan, and merge output were cleared.")

    discovery_result = st.session_state.get("generic_discovery_result")
    if uploaded_files and discovery_result is None:
        try:
            with st.spinner("Reading and profiling uploaded tables..."):
                discovery_result = discover_relationships_from_sources(uploaded_files)
            _initialize_discovery_state(discovery_result)
        except Exception as error:
            st.error(f"Relationship discovery failed: {error}")
            return None

    if discovery_result is None:
        return

    with st.expander("Detected table profiles", expanded=True):
        st.dataframe(
            pd.DataFrame(_table_profile_records(discovery_result)),
            hide_index=True,
            use_container_width=True,
            column_config={
                "role_confidence": st.column_config.NumberColumn(format="percent")
            },
        )

    if len(discovery_result.tables) == 1:
        return _render_single_table_route(discovery_result)

    st.subheader("Select Main Transaction Table")
    table_ids = [profile.table_id for profile in discovery_result.table_profiles]
    fact_table_id = st.selectbox(
        "Main transaction table",
        [None] + table_ids,
        index=0,
        format_func=lambda value: (
            "Select a fact table"
            if value is None
            else _format_table(discovery_result, value)
        ),
        key="generic_fact_table_id",
    )
    if st.session_state.get("generic_fact_table_snapshot") != fact_table_id:
        st.session_state["generic_fact_table_snapshot"] = fact_table_id
        invalidate_generic_plan_state(st.session_state)

    st.subheader("Review Relationship Candidates")
    if discovery_result.relationships:
        _render_candidate_groups(discovery_result)
    else:
        st.info("No reasonable relationship candidates were detected.")

    return _render_plan_and_merge(discovery_result, fact_table_id)
