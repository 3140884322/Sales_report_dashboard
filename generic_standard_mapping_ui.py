from __future__ import annotations

import inspect
from dataclasses import dataclass

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
from ui_guidance import blocked_reason_key, render_blocked_reason, render_step_guide
from ui_i18n import field_help, field_label, get_language, t


BUTTON_SUPPORTS_ICON = "icon" in inspect.signature(st.button).parameters
LARGE_ROW_WARNING = 500_000
LARGE_COLUMN_WARNING = 200
LARGE_MEMORY_WARNING_BYTES = 250 * 1024 * 1024

DIRECT_CHOICE_STRATEGIES = frozenset(
    {"unmapped", "not_provided", "not_applicable", "omit"}
)
ASSUMPTION_CHOICE_STRATEGIES = frozenset({"default_zero"})
LEGACY_DISPLAY_STRATEGIES = {
    "Not mapped": "unmapped",
    "Default 0 (explicit business assumption)": "default_zero",
    "Data not provided (keep as unknown)": "not_provided",
    "Not applicable to this business": "not_applicable",
    "Omit optional field": "omit",
    "未映射": "unmapped",
    "默认 0（明确业务假设）": "default_zero",
    "数据未提供（保持未知）": "not_provided",
    "不适用于此业务": "not_applicable",
    "不使用此可选字段": "omit",
}
LEGACY_SOURCE_PREFIXES = ("Map from source: ", "映射来源列：")


@dataclass(frozen=True)
class DecodedMappingChoice:
    strategy: str
    source_column: str | None
    normalized_choice: str
    error: str | None = None

    @property
    def valid(self):
        return self.error is None


def _button(label, icon=None, **kwargs):
    if icon and BUTTON_SUPPORTS_ICON:
        kwargs["icon"] = icon
    return st.button(label, **kwargs)


def _memory_text(memory_bytes):
    if memory_bytes is None:
        return t("common.not_available")
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
        return f"column::{source_column}"
    if strategy in ASSUMPTION_CHOICE_STRATEGIES:
        return f"assumption::{strategy}"
    if strategy in DIRECT_CHOICE_STRATEGIES:
        return strategy
    raise ValueError(f"Unsupported mapping strategy: {strategy!r}")


def _decode_choice(choice):
    if not isinstance(choice, str) or not choice:
        return DecodedMappingChoice(
            "unmapped",
            None,
            "unmapped",
            f"Invalid empty mapping choice: {choice!r}",
        )
    if choice in DIRECT_CHOICE_STRATEGIES:
        return DecodedMappingChoice(choice, None, choice)

    legacy_strategy = LEGACY_DISPLAY_STRATEGIES.get(choice)
    if legacy_strategy is not None:
        return _decode_choice(_encode_choice(legacy_strategy))
    for prefix in LEGACY_SOURCE_PREFIXES:
        if choice.startswith(prefix) and choice[len(prefix) :]:
            return _decode_choice(f"column::{choice[len(prefix):]}")

    kind, separator, value = choice.partition("::")
    if not separator or not value:
        return DecodedMappingChoice(
            "unmapped",
            None,
            "unmapped",
            f"Unknown mapping choice: {choice!r}",
        )
    if kind == "column":
        return DecodedMappingChoice("source", value, f"column::{value}")
    if kind == "assumption" and value in ASSUMPTION_CHOICE_STRATEGIES:
        return DecodedMappingChoice(value, None, f"assumption::{value}")

    # Migrate stable values stored by versions released before this option schema.
    if kind == "source":
        return DecodedMappingChoice("source", value, f"column::{value}")
    if kind == "strategy":
        if value in DIRECT_CHOICE_STRATEGIES:
            return DecodedMappingChoice(value, None, value)
        if value in ASSUMPTION_CHOICE_STRATEGIES:
            return DecodedMappingChoice(value, None, f"assumption::{value}")

    return DecodedMappingChoice(
        "unmapped",
        None,
        "unmapped",
        f"Unknown mapping choice: {choice!r}",
    )


def _format_choice(choice, language=None):
    decoded = _decode_choice(choice)
    if not decoded.valid:
        return t("strategy.invalid_saved", language)
    if decoded.strategy == "source":
        return t("strategy.source", language, source=decoded.source_column)
    return t(f"strategy.{decoded.strategy}", language)


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
    return [_encode_choice(strategy) for strategy in strategies] + [
        _encode_choice("source", column) for column in source_columns
    ]


def _clear_mapping_output():
    st.session_state.pop("generic_standard_mapping_result", None)
    st.session_state.pop("generic_mapping_error", None)
    invalidate_generic_report_state(st.session_state)


def _choice_changed(field):
    choice_key = f"generic_mapping_choice_{field}"
    error_key = f"generic_mapping_choice_error_{field}"
    choice = st.session_state.get(choice_key)
    decoded = _decode_choice(choice)
    if decoded.valid:
        st.session_state[choice_key] = decoded.normalized_choice
        st.session_state.pop(error_key, None)
    else:
        st.session_state[error_key] = choice
    strategy = decoded.strategy
    st.session_state[f"generic_mapping_confirm_{field}"] = (
        decoded.valid
        and field in OPTIONAL_ANALYSIS_FIELDS
        and strategy in {"not_provided", "not_applicable", "omit"}
    )
    _clear_mapping_output()


def _recommendation_records(recommendations):
    records = []
    for recommendation in recommendations:
        if recommendation.recommended_strategy == "source":
            proposed = recommendation.recommended_source
        else:
            proposed = t(f"strategy.{recommendation.recommended_strategy}")
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
    metrics[0].metric(t("mapping.merged_rows"), f"{len(frame):,}")
    metrics[1].metric(t("mapping.merged_columns"), f"{len(frame.columns):,}")
    metrics[2].metric(t("mapping.memory"), _memory_text(memory_bytes))
    if (
        len(frame) >= LARGE_ROW_WARNING
        or len(frame.columns) >= LARGE_COLUMN_WARNING
        or memory_bytes >= LARGE_MEMORY_WARNING_BYTES
    ):
        st.warning(t("mapping.large_warning"))


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
        st.session_state[f"generic_mapping_confirm_{recommendation.standard_field}"] = (
            recommendation.standard_field in OPTIONAL_ANALYSIS_FIELDS
            and recommendation.recommended_strategy
            in {"not_provided", "not_applicable", "omit"}
        )
    st.session_state["generic_mapping_extensions"] = []


def _render_field_choices(frame, recommendations, source_entity_roles):
    source_columns = list(map(str, frame.columns))
    language = get_language()
    selections = []
    inference_records = []
    choice_errors = []

    for section_key, field_type_key, fields in (
        ("mapping.required_section", "common.required", REQUIRED_TRANSACTION_FIELDS),
        ("mapping.optional_section", "common.optional", OPTIONAL_ANALYSIS_FIELDS),
        ("mapping.assumption_section", "common.assumption", BUSINESS_ASSUMPTION_FIELDS),
    ):
        st.markdown(f"#### {t(section_key)}")
        for field in fields:
            recommendation = next(
                item for item in recommendations if item.standard_field == field
            )
            choice_key = f"generic_mapping_choice_{field}"
            confirm_key = f"generic_mapping_confirm_{field}"
            error_key = f"generic_mapping_choice_error_{field}"
            options = _choice_options(field, source_columns)
            current_choice = st.session_state.get(choice_key)
            decoded_current = _decode_choice(current_choice)
            if decoded_current.valid:
                current_choice = decoded_current.normalized_choice
                st.session_state[choice_key] = current_choice
            if not decoded_current.valid or current_choice not in options:
                st.session_state[error_key] = current_choice
                current_choice = _encode_choice(
                    recommendation.recommended_strategy,
                    recommendation.recommended_source,
                )
                if current_choice not in options:
                    current_choice = options[0]
                st.session_state[choice_key] = current_choice
                st.session_state[confirm_key] = False

            invalid_saved_choice = st.session_state.get(error_key)
            if invalid_saved_choice is not None:
                choice_errors.append(
                    t(
                        "mapping.invalid_saved_choice",
                        field=field_label(field),
                        choice=repr(invalid_saved_choice),
                    )
                )

            columns = st.columns([1.2, 3.8, 1.2])
            columns[0].markdown(
                f"**{field_label(field)}**  \n{t(field_type_key)}"
            )
            columns[0].caption(field_help(field))
            columns[1].selectbox(
                t("mapping.for_field", field=field_label(field)),
                options,
                format_func=lambda choice, language=language: _format_choice(
                    choice, language
                ),
                key=choice_key,
                on_change=_choice_changed,
                args=(field,),
            )
            decoded = _decode_choice(st.session_state[choice_key])
            strategy = decoded.strategy
            source_column = decoded.source_column
            active = strategy != "omit"
            confirmation_not_required = (
                field in OPTIONAL_ANALYSIS_FIELDS
                and strategy in {"not_provided", "not_applicable", "omit"}
            )
            if confirmation_not_required:
                st.session_state[confirm_key] = True
            columns[2].checkbox(
                (
                    t("common.no_confirmation_needed")
                    if confirmation_not_required
                    else t("common.confirm")
                ),
                key=confirm_key,
                disabled=not active or confirmation_not_required,
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
                explanation = t("mapping.user_fallback")
            inference_records.append(
                {
                    "standard_field": field,
                    "source_or_strategy": _format_choice(
                        st.session_state[choice_key], language
                    ),
                    "inferred_confidence": confidence,
                    "confirmed": confirmed,
                    "explanation": explanation,
                }
            )

    return tuple(selections), inference_records, tuple(choice_errors)


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

    render_step_guide(6)
    st.subheader(t("mapping.title"))
    st.write(t("mapping.intro"))
    _render_size_guard(frame)
    source_entity_roles = build_source_entity_role_map(
        discovery_result, merge_result.fact_table_id
    )
    _initialize_mapping_state(frame, source_entity_roles)
    recommendations = st.session_state["generic_mapping_recommendations"]

    with st.expander(t("mapping.recommendations"), expanded=True):
        st.dataframe(
            pd.DataFrame(_recommendation_records(recommendations)),
            hide_index=True,
            use_container_width=True,
            column_config={
                "standard_field": t("mapping.column.standard_field"),
                "required": t("mapping.column.required"),
                "target_type": t("mapping.column.target_type"),
                "recommended_source_or_strategy": t("mapping.column.recommendation"),
                "confidence": t("common.confidence"),
                "explanation": t("mapping.column.explanation"),
            },
        )
        st.caption(t("mapping.recommendation_notice"))

    selections, inference_records, choice_errors = _render_field_choices(
        frame,
        recommendations,
        source_entity_roles,
    )
    st.markdown(f"#### {t('mapping.current_summary')}")
    st.dataframe(
        pd.DataFrame(inference_records),
        hide_index=True,
        use_container_width=True,
        column_config={
            "standard_field": t("mapping.column.standard_field"),
            "source_or_strategy": t("mapping.column.source_strategy"),
            "inferred_confidence": t("common.confidence"),
            "confirmed": t("table.column.confirmed"),
            "explanation": t("mapping.column.explanation"),
        },
    )

    live_errors, source_usage = _live_mapping_errors(selections)
    live_errors = choice_errors + live_errors
    required_confirmed = sum(
        selection.strategy != "unmapped" and selection.confirmed
        for selection in selections
        if selection.standard_field in REQUIRED_TRANSACTION_FIELDS
    )
    st.info(
        t(
            "mapping.required_progress",
            confirmed=required_confirmed,
            total=len(REQUIRED_TRANSACTION_FIELDS),
        )
    )
    extension_columns = st.multiselect(
        t("mapping.additional"),
        list(map(str, frame.columns)),
        key="generic_mapping_extensions",
        help=t("mapping.additional_help"),
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
        st.warning(t("mapping.incomplete", count=len(live_errors)))
        with st.expander(t("mapping.checks", count=len(live_errors)), expanded=False):
            for error in live_errors:
                st.warning(t("mapping.error_item", error=error))

    mapping_block_reason = blocked_reason_key(
        "generate_mapping", incomplete_count=len(live_errors)
    )
    render_blocked_reason(mapping_block_reason)
    generate_clicked = _button(
        t("mapping.generate"),
        icon=":material/check_circle:",
        key="generic_mapping_generate",
        disabled=bool(live_errors),
    )
    if generate_clicked:
        with st.spinner(t("mapping.spinner")):
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

    st.subheader(t("mapping.preview_title"))
    st.caption(t("mapping.preview_explanation"))
    if result.success:
        st.success(t("mapping.passed"))
    else:
        st.error(t("mapping.blocked"))
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
                "standard_field": t("mapping.column.standard_field"),
                "source_or_strategy": t("mapping.column.source_strategy"),
                "confidence": t("common.confidence"),
                "conversion_failures": t("mapping.column.conversion_failures"),
                "invalid_values": t("mapping.column.invalid_values"),
                "null_values": t("mapping.column.null_values"),
                "null_rate": st.column_config.NumberColumn(
                    t("mapping.column.null_rate"), format="percent"
                ),
                "output_dtype": t("mapping.column.output_type"),
                "status": t("common.status"),
                "explanation": t("mapping.column.explanation"),
            },
        )
    if not result.success or result.unified_orders is None:
        return

    output_metrics = st.columns(4)
    output_metrics[0].metric(t("mapping.unified_rows"), f"{result.output_row_count:,}")
    output_metrics[1].metric(t("mapping.unified_columns"), f"{result.output_column_count:,}")
    output_metrics[2].metric(t("mapping.unified_memory"), _memory_text(result.output_memory_bytes))
    output_metrics[3].metric(t("mapping.preview_rows"), f"{min(20, result.output_row_count):,}")
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
