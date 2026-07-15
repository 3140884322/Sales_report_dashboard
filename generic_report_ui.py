from __future__ import annotations

import hashlib
import inspect
import traceback

import pandas as pd
import streamlit as st

from generic_relationship_state import (
    clear_generic_report_if_inputs_changed,
    make_generic_upload_signature,
)
from generic_report_generation import (
    INVALID_DATE_ACTION_BLOCK,
    INVALID_DATE_ACTION_EXCLUDE_MONTHLY,
    GenericReportGenerationError,
    build_data_preparation_summary,
    field_availability_table,
    generate_generic_report,
    run_generic_report_preflight,
)
from standard_field_mapping import StandardFieldMappingError
from ui_guidance import blocked_reason_key, render_blocked_reason, render_step_guide
from ui_i18n import get_language, t


BUTTON_SUPPORTS_ICON = "icon" in inspect.signature(st.button).parameters
LARGE_EXCEL_ROW_WARNING = 50_000


def _button(label, icon=None, **kwargs):
    if icon and BUTTON_SUPPORTS_ICON:
        kwargs["icon"] = icon
    return st.button(label, **kwargs)


def _memory_text(memory_bytes):
    value = float(memory_bytes)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:,.1f} {unit}"
        value /= 1024
    return f"{value:,.1f} GiB"


def _mapping_report_signature(mapping_result, expenses_file):
    selections = tuple(
        (
            item.standard_field,
            item.strategy,
            item.source_column,
            item.confirmed,
        )
        for item in mapping_result.plan.selections
    )
    expense_signature = make_generic_upload_signature(
        [expenses_file] if expenses_file is not None else []
    )
    digest = hashlib.md5(repr(selections).encode("utf-8")).hexdigest()
    return (
        mapping_result.source_row_count,
        mapping_result.output_row_count,
        mapping_result.report_columns,
        digest,
        expense_signature,
    )


def _clear_report_output():
    st.session_state.pop("generic_report_result", None)
    st.session_state.pop("generic_report_error", None)
    st.session_state["generic_report_confirm"] = False


def _conversion_records(mapping_result):
    return [
        {
            "standard_field": item.standard_field,
            "source_or_strategy": item.source_or_strategy,
            "conversion_failures": item.conversion_failure_count,
            "invalid_values": item.invalid_value_count,
            "null_values": item.null_count,
            "status": item.status,
        }
        for item in mapping_result.diagnostics
    ]


def _preflight_options(mapping_result):
    language = get_language()
    orders = mapping_result.unified_orders
    prices = pd.to_numeric(orders["unit_price"], errors="coerce")
    quantities = pd.to_numeric(orders["quantity"], errors="coerce")
    dates = pd.to_datetime(orders["date"], errors="coerce", format="mixed")
    critical_count = int(
        (prices.isna() | prices.lt(0) | quantities.isna() | quantities.le(0)).sum()
    )
    invalid_date_count = int(dates.isna().sum())

    if invalid_date_count:
        st.markdown(f"#### {t('preflight.invalid_date_title')}")
        st.caption(t("preflight.invalid_date_explain"))
        date_action = st.radio(
            t("preflight.invalid_date_question"),
            [INVALID_DATE_ACTION_BLOCK, INVALID_DATE_ACTION_EXCLUDE_MONTHLY],
            format_func=lambda value, language=language: (
                t("preflight.invalid_date_block", language)
                if value == INVALID_DATE_ACTION_BLOCK
                else t("preflight.invalid_date_continue", language)
            ),
            key="generic_report_date_action",
            on_change=_clear_report_output,
        )
    else:
        date_action = INVALID_DATE_ACTION_EXCLUDE_MONTHLY

    if critical_count:
        st.markdown(f"#### {t('preflight.critical_title')}")
        st.caption(t("preflight.critical_help"))
        exclude_critical = st.checkbox(
            t("preflight.exclude_critical", count=f"{critical_count:,}"),
            key="generic_report_exclude_critical",
            on_change=_clear_report_output,
        )
    else:
        exclude_critical = False

    return date_action, exclude_critical


def _render_preflight_summary(preflight, mapping_result):
    metrics = st.columns(6)
    metrics[0].metric(t("preflight.original_rows"), f"{preflight.original_fact_row_count:,}")
    metrics[1].metric(t("preflight.merged_rows"), f"{preflight.merged_row_count:,}")
    metrics[2].metric(t("preflight.unified_rows"), f"{preflight.unified_row_count:,}")
    metrics[3].metric(t("preflight.excluded_rows"), f"{preflight.excluded_row_count:,}")
    metrics[4].metric(t("preflight.calculation_rows"), f"{preflight.calculation_row_count:,}")
    metrics[5].metric(t("preflight.memory"), _memory_text(preflight.estimated_memory_bytes))

    date_range = (
        t("common.not_available")
        if preflight.date_min is None
        else f"{preflight.date_min.date()} to {preflight.date_max.date()}"
    )
    st.write(t("preflight.date_range", date_range=date_range))
    st.write(t(
        "preflight.monthly_excluded",
        count=f"{preflight.monthly_analysis_excluded_row_count:,}",
    ))

    st.markdown(f"#### {t('preflight.availability')}")
    st.dataframe(
        field_availability_table(mapping_result.field_availability),
        hide_index=True,
        use_container_width=True,
        column_config={
            "field_name": t("availability.column.field"),
            "availability_status": t("availability.column.status"),
            "source_column": t("availability.column.source"),
            "default_value": t("availability.column.default"),
            "user_confirmed": t("availability.column.user_confirmed"),
            "notes": t("table.column.notes"),
            "provided_row_count": t("availability.column.provided_rows"),
            "total_row_count": t("availability.column.total_rows"),
        },
    )

    diagnostic_columns = st.columns(2)
    with diagnostic_columns[0]:
        st.markdown(f"#### {t('preflight.conversions')}")
        st.dataframe(
            pd.DataFrame(_conversion_records(mapping_result)),
            hide_index=True,
            use_container_width=True,
            column_config={
                "standard_field": t("mapping.column.standard_field"),
                "source_or_strategy": t("mapping.column.source_strategy"),
                "conversion_failures": t("mapping.column.conversion_failures"),
                "invalid_values": t("mapping.column.invalid_values"),
                "null_values": t("mapping.column.null_values"),
                "status": t("common.status"),
            },
        )
    with diagnostic_columns[1]:
        st.markdown(f"#### {t('preflight.nulls')}")
        st.dataframe(
            pd.DataFrame(
                [
                    {"standard_field": field, "null_values": count}
                    for field, count in preflight.required_null_counts.items()
                ]
            ),
            hide_index=True,
            use_container_width=True,
            column_config={
                "standard_field": t("mapping.column.standard_field"),
                "null_values": t("mapping.column.null_values"),
            },
        )

    if not preflight.critical_rows_preview.empty:
        with st.expander(t("preflight.invalid_price_rows"), expanded=True):
            st.dataframe(
                preflight.critical_rows_preview,
                hide_index=True,
                use_container_width=True,
            )
    if not preflight.invalid_date_rows_preview.empty:
        with st.expander(t("preflight.invalid_date_rows"), expanded=True):
            st.dataframe(
                preflight.invalid_date_rows_preview,
                hide_index=True,
                use_container_width=True,
            )

    for issue in preflight.issues:
        if issue.severity == "critical":
            st.error(t(
                "preflight.issue",
                field=issue.field_name,
                message=issue.message,
                count=f"{issue.row_count:,}",
            ))
        else:
            st.warning(issue.message)
    for warning in preflight.warnings:
        st.warning(warning)


def render_generic_report_generation(
    *,
    discovery_result,
    plan,
    decisions,
    merge_result,
    mapping_result,
):
    """Render B2.2 preflight, explicit confirmation, and cached report generation."""
    render_step_guide(7)
    st.subheader(t("preflight.title"))
    st.write(t("preflight.intro"))
    st.info(t("preflight.classification"))
    expenses_file = st.file_uploader(
        t("preflight.expenses_label"),
        type=["csv"],
        key="generic_report_expenses_file",
        help=t("preflight.expenses_help"),
    )
    signature = _mapping_report_signature(mapping_result, expenses_file)
    clear_generic_report_if_inputs_changed(st.session_state, signature)

    date_action, exclude_critical = _preflight_options(mapping_result)
    preflight = run_generic_report_preflight(
        mapping_result,
        original_fact_row_count=merge_result.fact_row_count,
        merged_row_count=merge_result.final_row_count,
        invalid_date_action=date_action,
        exclude_invalid_price_quantity_rows=exclude_critical,
    )
    _render_preflight_summary(preflight, mapping_result)

    preparation_summary = build_data_preparation_summary(
        discovery_result=discovery_result,
        plan=plan,
        decisions=decisions,
        mapping_result=mapping_result,
        preflight=preflight,
    )
    with st.expander(t("preflight.preparation"), expanded=True):
        st.dataframe(
            preparation_summary.astype("string"),
            hide_index=True,
            use_container_width=True,
            column_config={
                "section": t("table.column.section"),
                "item": t("table.column.item"),
                "value": t("table.column.value"),
                "notes": t("table.column.notes"),
            },
        )

    if preflight.calculation_row_count >= LARGE_EXCEL_ROW_WARNING:
        st.info(t("preflight.large_excel"))

    confirmed = st.checkbox(
        t("preflight.confirm"),
        key="generic_report_confirm",
        disabled=not preflight.can_generate,
        on_change=lambda: st.session_state.pop("generic_report_result", None),
    )
    report_block_reason = blocked_reason_key(
        "generate_report",
        preflight_ready=preflight.can_generate,
        confirmed=confirmed,
    )
    render_blocked_reason(report_block_reason)
    generate_clicked = _button(
        t("preflight.generate"),
        icon=":material/analytics:",
        key="generic_report_generate",
        disabled=not preflight.can_generate or not confirmed,
    )
    if generate_clicked:
        progress = st.progress(0, text=t("preflight.progress.5"))

        def update_progress(percent, message):
            progress.progress(percent, text=t(f"preflight.progress.{percent}"))

        try:
            report_result = generate_generic_report(
                mapping_result=mapping_result,
                preflight=preflight,
                discovery_result=discovery_result,
                plan=plan,
                decisions=decisions,
                expenses_source=expenses_file,
                progress_callback=update_progress,
            )
            st.session_state["generic_report_result"] = report_result
            st.session_state.pop("generic_report_error", None)
            st.rerun()
        except (
            GenericReportGenerationError,
            StandardFieldMappingError,
            ValueError,
        ) as error:
            st.session_state["generic_report_error"] = {
                "message": str(error),
                "traceback": traceback.format_exc(),
            }
        except Exception as error:
            st.session_state["generic_report_error"] = {
                "message": t("preflight.report_failed", error=error),
                "traceback": traceback.format_exc(),
            }

    report_error = st.session_state.get("generic_report_error")
    if report_error:
        st.error(report_error["message"])
        with st.expander(t("common.debug_details")):
            st.code(report_error["traceback"])

    report_result = st.session_state.get("generic_report_result")
    if report_result is not None:
        st.success(t("preflight.report_cached"))
    return report_result
