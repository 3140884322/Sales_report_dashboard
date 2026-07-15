from __future__ import annotations

import inspect

import pandas as pd
import streamlit as st

from generic_relationship_state import (
    invalidate_generic_mapping_state,
    invalidate_generic_report_state,
)
from generic_report_ui import render_generic_report_generation
from standard_field_mapping import (
    BUSINESS_ASSUMPTION_FIELDS,
    OPTIONAL_ANALYSIS_FIELDS,
    REQUIRED_TRANSACTION_FIELDS,
    build_source_entity_role_map,
    evaluate_field_mapping_recommendation,
    generate_unified_orders,
    recommend_standard_field_mappings,
)
from standard_field_models import StandardFieldSelection


BUTTON_SUPPORTS_ICON = "icon" in inspect.signature(st.button).parameters
LARGE_ROW_WARNING = 500_000
LARGE_COLUMN_WARNING = 200
LARGE_MEMORY_WARNING_BYTES = 250 * 1024 * 1024

STRATEGY_LABELS = {
    "unmapped": "Not mapped",
    "default_zero": "Default 0 (explicit business assumption)",
    "not_provided": "Data not provided (keep as unknown)",
    "not_applicable": "Not applicable to this business",
    "omit": "Omit optional field",
}


def _button(label, icon=None, **kwargs):
    if icon and BUTTON_SUPPORTS_ICON:
        kwargs["icon"] = icon
    return st.button(label, **kwargs)


def _memory_text(memory_bytes):
    if memory_bytes is None:
        return "n/a"
    value = float(memory_bytes)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:,.1f} {unit}"
        value /= 1024
    return f"{value:,.1f} GiB"


def _mapping_signature(frame, source_entity_roles):
    return (
        frame.shape,
        tuple(map(str, frame.columns)),
        tuple(map(str, frame.dtypes)),
        tuple(sorted(source_entity_roles.items())),
    )


def _encode_choice(strategy, source_column=None):
    if strategy == "source" and source_column is not None:
        return f"source::{source_column}"
    return f"strategy::{strategy}"


def _decode_choice(choice):
    kind, value = choice.split("::", 1)
    if kind == "source":
        return "source", value
    return value, None


def _format_choice(choice):
    strategy, source = _decode_choice(choice)
    if strategy == "source":
        return f"Map from source: {source}"
    return STRATEGY_LABELS[strategy]


def _choice_options(field, source_columns):
    special = {
        "discount_rate": ("default_zero",),
        "returned": ("not_provided", "not_applicable"),
        "customer_id": ("not_provided", "omit"),
    }
    if field in special:
        strategies = special[field]
    elif field in OPTIONAL_ANALYSIS_FIELDS:
        strategies = ("omit",)
    else:
        strategies = ("unmapped",)
    return [f"strategy::{strategy}" for strategy in strategies] + [
        f"source::{column}" for column in source_columns
    ]


def _clear_mapping_output():
    st.session_state.pop("generic_standard_mapping_result", None)
    st.session_state.pop("generic_mapping_error", None)
    invalidate_generic_report_state(st.session_state)


def _choice_changed(field):
    st.session_state[f"generic_mapping_confirm_{field}"] = False
    _clear_mapping_output()


def _recommendation_records(recommendations):
    records = []
    for recommendation in recommendations:
        if recommendation.recommended_strategy == "source":
            proposed = recommendation.recommended_source
        else:
            proposed = STRATEGY_LABELS.get(
                recommendation.recommended_strategy,
                recommendation.recommended_strategy,
            )
        records.append(
            {
                "standard_field": recommendation.standard_field,
                "required": recommendation.required,
                "target_type": recommendation.target_type,
                "recommended_source_or_strategy": proposed,
                "confidence": recommendation.confidence_score,
                "explanation": recommendation.explanation,
            }
        )
    return records


def _diagnostic_records(result):
    return [
        {
            "standard_field": diagnostic.standard_field,
            "source_or_strategy": diagnostic.source_or_strategy,
            "confidence": diagnostic.confidence_score,
            "conversion_failures": diagnostic.conversion_failure_count,
            "invalid_values": diagnostic.invalid_value_count,
            "null_values": diagnostic.null_count,
            "null_rate": diagnostic.null_rate,
            "output_dtype": diagnostic.output_dtype,
            "status": diagnostic.status,
            "explanation": diagnostic.explanation,
        }
        for diagnostic in result.diagnostics
    ]


def _render_size_guard(frame):
    memory_bytes = int(frame.memory_usage(index=True, deep=True).sum())
    metrics = st.columns(3)
    metrics[0].metric("Merged rows", f"{len(frame):,}")
    metrics[1].metric("Merged columns", f"{len(frame.columns):,}")
    metrics[2].metric("Estimated memory", _memory_text(memory_bytes))
    if (
        len(frame) >= LARGE_ROW_WARNING
        or len(frame.columns) >= LARGE_COLUMN_WARNING
        or memory_bytes >= LARGE_MEMORY_WARNING_BYTES
    ):
        st.warning(
            "This merged dataset is large. Recommendations use bounded samples and the "
            "page displays only 20-row previews; conversion may still require additional memory."
        )


def _initialize_mapping_state(frame, source_entity_roles):
    signature = _mapping_signature(frame, source_entity_roles)
    if st.session_state.get("generic_mapping_signature") == signature:
        return

    invalidate_generic_mapping_state(st.session_state)
    recommendations = recommend_standard_field_mappings(
        frame, source_entity_roles
    )
    st.session_state["generic_mapping_signature"] = signature
    st.session_state["generic_mapping_recommendations"] = recommendations
    for recommendation in recommendations:
        st.session_state[f"generic_mapping_choice_{recommendation.standard_field}"] = (
            _encode_choice(
                recommendation.recommended_strategy,
                recommendation.recommended_source,
            )
        )
        st.session_state[f"generic_mapping_confirm_{recommendation.standard_field}"] = False
    st.session_state["generic_mapping_extensions"] = []


def _render_field_choices(frame, recommendations, source_entity_roles):
    source_columns = list(map(str, frame.columns))
    selections = []
    inference_records = []

    for section_label, field_label, fields in (
        ("Required transaction fields", "Required", REQUIRED_TRANSACTION_FIELDS),
        ("Optional analysis fields", "Optional", OPTIONAL_ANALYSIS_FIELDS),
        ("Business assumptions", "Assumption", BUSINESS_ASSUMPTION_FIELDS),
    ):
        st.markdown(f"#### {section_label}")
        for field in fields:
            recommendation = next(
                item for item in recommendations if item.standard_field == field
            )
            choice_key = f"generic_mapping_choice_{field}"
            confirm_key = f"generic_mapping_confirm_{field}"
            options = _choice_options(field, source_columns)
            current_choice = st.session_state.get(choice_key)
            if current_choice not in options:
                current_choice = _encode_choice(
                    recommendation.recommended_strategy,
                    recommendation.recommended_source,
                )
                st.session_state[choice_key] = current_choice

            columns = st.columns([1.2, 3.8, 1.2])
            columns[0].markdown(
                f"**{field}**  \n{field_label}"
            )
            columns[1].selectbox(
                f"Mapping for {field}",
                options,
                format_func=_format_choice,
                key=choice_key,
                label_visibility="collapsed",
                on_change=_choice_changed,
                args=(field,),
            )
            strategy, source_column = _decode_choice(st.session_state[choice_key])
            active = strategy != "omit"
            columns[2].checkbox(
                "Confirm",
                key=confirm_key,
                disabled=not active,
                on_change=_clear_mapping_output,
            )
            confirmed = bool(st.session_state.get(confirm_key)) if active else True
            selections.append(
                StandardFieldSelection(
                    standard_field=field,
                    strategy=strategy,
                    source_column=source_column,
                    confirmed=confirmed,
                )
            )

            if strategy == "source":
                inference = evaluate_field_mapping_recommendation(
                    frame,
                    field,
                    source_column,
                    source_entity_roles,
                )
                confidence = inference.confidence_score
                explanation = inference.explanation
            elif strategy == recommendation.recommended_strategy:
                confidence = recommendation.confidence_score
                explanation = recommendation.explanation
            else:
                confidence = 0.0
                explanation = "User-selected fallback strategy."
            inference_records.append(
                {
                    "standard_field": field,
                    "source_or_strategy": _format_choice(st.session_state[choice_key]),
                    "inferred_confidence": confidence,
                    "confirmed": confirmed,
                    "explanation": explanation,
                }
            )

    return tuple(selections), inference_records


def _live_mapping_errors(selections):
    errors = []
    source_usage = {}
    for selection in selections:
        if selection.standard_field in REQUIRED_TRANSACTION_FIELDS:
            if selection.strategy == "unmapped":
                errors.append(f"{selection.standard_field} is not mapped.")
            elif not selection.confirmed:
                errors.append(f"{selection.standard_field} is not confirmed.")
        elif selection.strategy != "omit" and not selection.confirmed:
            errors.append(f"{selection.standard_field} is selected but not confirmed.")

        if selection.strategy == "source":
            previous = source_usage.get(selection.source_column)
            if previous:
                errors.append(
                    f"{selection.source_column} is used by both {previous} and "
                    f"{selection.standard_field}."
                )
            else:
                source_usage[selection.source_column] = selection.standard_field
    return tuple(errors), source_usage


def render_generic_standard_mapping(
    merge_result,
    *,
    discovery_result=None,
    plan=None,
    decisions=None,
):
    """Render B2.1 only after B1 has produced a successful, stable merged frame."""
    frame = merge_result.merged_frame
    if not merge_result.success or frame is None:
        return

    st.subheader("Standard Field Mapping")
    _render_size_guard(frame)
    source_entity_roles = build_source_entity_role_map(
        discovery_result, merge_result.fact_table_id
    )
    _initialize_mapping_state(frame, source_entity_roles)
    recommendations = st.session_state["generic_mapping_recommendations"]

    with st.expander("Automatic mapping recommendations", expanded=True):
        st.dataframe(
            pd.DataFrame(_recommendation_records(recommendations)),
            hide_index=True,
            use_container_width=True,
        )
        st.caption(
            "Recommendations are never approval. Confirm every required mapping or fallback explicitly."
        )

    selections, inference_records = _render_field_choices(
        frame,
        recommendations,
        source_entity_roles,
    )
    st.markdown("#### Current mapping summary")
    st.dataframe(
        pd.DataFrame(inference_records),
        hide_index=True,
        use_container_width=True,
    )

    live_errors, source_usage = _live_mapping_errors(selections)
    extension_columns = st.multiselect(
        "Additional source columns to retain",
        list(map(str, frame.columns)),
        key="generic_mapping_extensions",
        help=(
            "The unified dataset contains required fields, confirmed optional fields, "
            "and only these explicitly retained extensions."
        ),
        on_change=_clear_mapping_output,
    )
    extension_conflicts = [
        column for column in extension_columns if column in source_usage
    ]
    if extension_conflicts:
        live_errors += tuple(
            f"{column} is already used as a standard field source and cannot also be an extension."
            for column in extension_conflicts
        )

    if live_errors:
        with st.expander(f"Mapping checks ({len(live_errors)} incomplete)", expanded=False):
            for error in live_errors:
                st.warning(error)

    generate_clicked = _button(
        "Validate & Generate Unified Orders Preview",
        icon=":material/check_circle:",
        key="generic_mapping_generate",
        disabled=bool(live_errors),
    )
    if generate_clicked:
        with st.spinner("Validating conversions and generating a bounded preview..."):
            invalidate_generic_report_state(st.session_state)
            st.session_state["generic_standard_mapping_result"] = generate_unified_orders(
                frame,
                selections,
                extension_columns,
                source_entity_roles,
            )
        st.rerun()

    result = st.session_state.get("generic_standard_mapping_result")
    if result is None:
        return

    st.subheader("Unified Orders Preview")
    if result.success:
        st.success("Standard field mapping passed.")
    else:
        st.error("Standard field mapping is blocked.")
    for error in result.errors:
        st.error(error)
    for warning in result.warnings:
        st.warning(warning)

    if result.diagnostics:
        st.dataframe(
            pd.DataFrame(_diagnostic_records(result)),
            hide_index=True,
            use_container_width=True,
            column_config={
                "null_rate": st.column_config.NumberColumn(format="percent")
            },
        )
    if not result.success or result.unified_orders is None:
        return

    output_metrics = st.columns(4)
    output_metrics[0].metric("Unified rows", f"{result.output_row_count:,}")
    output_metrics[1].metric("Unified columns", f"{result.output_column_count:,}")
    output_metrics[2].metric("Unified memory", _memory_text(result.output_memory_bytes))
    output_metrics[3].metric("Preview rows", f"{min(20, result.output_row_count):,}")
    st.dataframe(
        result.unified_orders.head(20),
        hide_index=True,
        use_container_width=True,
    )
    if discovery_result is None or plan is None:
        return None
    return render_generic_report_generation(
        discovery_result=discovery_result,
        plan=plan,
        decisions=decisions or {},
        merge_result=merge_result,
        mapping_result=result,
    )
