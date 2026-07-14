from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pandas as pd

from analysis import make_report_status_table, run_pipeline
from generic_report_models import GenericPreflightIssue, GenericReportPreflight
from standard_field_mapping import REQUIRED_STANDARD_FIELDS
from standard_field_models import FieldAvailability, StandardMappingResult


INVALID_DATE_ACTION_BLOCK = "block"
INVALID_DATE_ACTION_EXCLUDE_MONTHLY = "exclude_from_monthly"
RETURN_NOT_PROVIDED_MESSAGE = (
    "Return data was not provided. Return analysis was skipped."
)
CUSTOMER_NOT_PROVIDED_MESSAGE = (
    "Customer data was not provided. Customer analysis was skipped."
)
CUSTOMER_PARTIALLY_PROVIDED_MESSAGE = (
    "Customer data was only partially provided. Customer analysis was skipped."
)


class GenericReportGenerationError(RuntimeError):
    pass


def field_availability_table(
    availability: Sequence[FieldAvailability],
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "field_name": item.field_name,
                "availability_status": item.availability_status,
                "source_column": item.source_column,
                "default_value": item.default_value,
                "user_confirmed": item.user_confirmed,
                "notes": item.notes,
                "provided_row_count": item.provided_row_count,
                "total_row_count": item.total_row_count,
            }
            for item in availability
        ],
        columns=[
            "field_name",
            "availability_status",
            "source_column",
            "default_value",
            "user_confirmed",
            "notes",
            "provided_row_count",
            "total_row_count",
        ],
    )


def get_field_availability_status(report_tables, field_name: str) -> str:
    table = report_tables.get("field_availability")
    if table is None or table.empty:
        return "provided"
    matches = table[table["field_name"] == field_name]
    if matches.empty:
        return "provided"
    return str(matches.iloc[0]["availability_status"])


def get_field_availability_notes(report_tables, field_name: str) -> str:
    table = report_tables.get("field_availability")
    if table is None or table.empty:
        return ""
    matches = table[table["field_name"] == field_name]
    if matches.empty:
        return ""
    return str(matches.iloc[0]["notes"])


def return_analysis_available(report_tables) -> bool:
    return get_field_availability_status(report_tables, "returned") == "provided"


def customer_analysis_available(report_tables) -> bool:
    return get_field_availability_status(report_tables, "customer_id") == "provided"


def customer_analysis_unavailable_message(report_tables) -> str:
    status = get_field_availability_status(report_tables, "customer_id")
    if status == "partially_provided":
        return CUSTOMER_PARTIALLY_PROVIDED_MESSAGE
    if status == "mapping_conflict":
        return get_field_availability_notes(report_tables, "customer_id")
    return CUSTOMER_NOT_PROVIDED_MESSAGE


def _availability_status(
    mapping_result: StandardMappingResult,
    field_name: str,
) -> str:
    for item in mapping_result.field_availability:
        if item.field_name == field_name:
            return item.availability_status
    return "provided"


def _invalid_order_id_mask(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip()
    return series.isna() | text.eq("")


def _issue_preview(frame, mask, reasons, limit=20):
    if not mask.any():
        return pd.DataFrame(columns=["unified_row_number", "order_id", "reason"])
    columns = [
        column
        for column in (
            "order_id",
            "date",
            "unit_price",
            "quantity",
            "discount_rate",
        )
        if column in frame.columns
    ]
    preview = frame.loc[mask, columns].head(limit).copy()
    preview.insert(0, "unified_row_number", frame.index.get_indexer(preview.index) + 1)
    preview["reason"] = [reasons[index] for index in preview.index]
    return preview.reset_index(drop=True)


def run_generic_report_preflight(
    mapping_result: StandardMappingResult,
    *,
    original_fact_row_count: int | None = None,
    merged_row_count: int | None = None,
    invalid_date_action: str = INVALID_DATE_ACTION_BLOCK,
    exclude_invalid_price_quantity_rows: bool = False,
) -> GenericReportPreflight:
    """Apply field-specific report gates without mutating unified_orders."""
    if invalid_date_action not in {
        INVALID_DATE_ACTION_BLOCK,
        INVALID_DATE_ACTION_EXCLUDE_MONTHLY,
    }:
        raise ValueError(f"Unknown invalid date action: {invalid_date_action!r}.")

    if not mapping_result.success or mapping_result.unified_orders is None:
        issues = (
            GenericPreflightIssue(
                "mapping_not_ready",
                "mapping",
                "critical",
                0,
                "Standard field mapping has not produced a validated unified_orders dataset.",
            ),
        )
        return GenericReportPreflight(
            can_generate=False,
            calculation_orders=None,
            issues=issues,
            warnings=(),
            excluded_rows_detail=pd.DataFrame(),
            critical_rows_preview=pd.DataFrame(),
            invalid_date_rows_preview=pd.DataFrame(),
            original_fact_row_count=original_fact_row_count or 0,
            merged_row_count=merged_row_count or 0,
            unified_row_count=0,
            excluded_row_count=0,
            calculation_row_count=0,
            monthly_analysis_excluded_row_count=0,
            required_null_counts={},
            conversion_failure_counts={},
            date_min=None,
            date_max=None,
            estimated_memory_bytes=0,
            invalid_date_action=invalid_date_action,
            explicit_critical_exclusion=exclude_invalid_price_quantity_rows,
        )

    source = mapping_result.unified_orders
    frame = source.copy(deep=False)
    issues = []
    warnings = []

    order_invalid = _invalid_order_id_mask(frame["order_id"])
    prices = pd.to_numeric(frame["unit_price"], errors="coerce")
    quantities = pd.to_numeric(frame["quantity"], errors="coerce")
    discounts = pd.to_numeric(frame["discount_rate"], errors="coerce")
    dates = pd.to_datetime(frame["date"], errors="coerce", format="mixed")
    price_invalid = prices.isna() | prices.lt(0)
    quantity_invalid = quantities.isna() | quantities.le(0)
    discount_invalid = discounts.isna() | discounts.lt(0) | discounts.gt(1)
    excludable_mask = price_invalid | quantity_invalid

    reasons = {index: [] for index in frame.index}
    for index in frame.index[price_invalid]:
        reasons[index].append("unit_price is missing, non-numeric, or negative")
    for index in frame.index[quantity_invalid]:
        reasons[index].append("quantity is missing, non-numeric, or not positive")

    excluded_detail = pd.DataFrame(
        columns=["unified_row_number", "order_id", "exclusion_reason"]
    )
    if excludable_mask.any() and exclude_invalid_price_quantity_rows:
        excluded = frame.loc[excludable_mask].copy()
        excluded_detail = pd.DataFrame(
            {
                "unified_row_number": frame.index.get_indexer(excluded.index) + 1,
                "order_id": excluded["order_id"].astype("string").tolist(),
                "exclusion_reason": [
                    "; ".join(reasons[index]) for index in excluded.index
                ],
            }
        )
        frame = frame.loc[~excludable_mask].copy()
        warnings.append(
            f"{len(excluded_detail):,} row(s) were explicitly excluded from all report calculations."
        )
    elif excludable_mask.any():
        issues.append(
            GenericPreflightIssue(
                "invalid_price_or_quantity",
                "unit_price, quantity",
                "critical",
                int(excludable_mask.sum()),
                "Invalid unit_price or quantity rows must be fixed or explicitly excluded.",
                excludable=True,
            )
        )

    critical_preview = _issue_preview(
        source,
        excludable_mask,
        {index: "; ".join(value) for index, value in reasons.items()},
    )

    remaining_order_invalid = _invalid_order_id_mask(frame["order_id"])
    if remaining_order_invalid.any():
        issues.append(
            GenericPreflightIssue(
                "invalid_order_id",
                "order_id",
                "critical",
                int(remaining_order_invalid.sum()),
                "order_id contains missing or empty values and cannot be reported.",
            )
        )

    remaining_discounts = pd.to_numeric(frame["discount_rate"], errors="coerce")
    remaining_discount_invalid = (
        remaining_discounts.isna()
        | remaining_discounts.lt(0)
        | remaining_discounts.gt(1)
    )
    if remaining_discount_invalid.any():
        issues.append(
            GenericPreflightIssue(
                "invalid_discount_rate",
                "discount_rate",
                "critical",
                int(remaining_discount_invalid.sum()),
                "discount_rate must be present and within 0-1 for every calculation row.",
            )
        )

    remaining_dates = pd.to_datetime(frame["date"], errors="coerce", format="mixed")
    invalid_dates = remaining_dates.isna()
    date_reasons = {index: "date could not be parsed" for index in frame.index}
    date_preview = _issue_preview(frame, invalid_dates, date_reasons)
    if invalid_dates.any():
        if invalid_date_action == INVALID_DATE_ACTION_BLOCK:
            issues.append(
                GenericPreflightIssue(
                    "invalid_date_decision_required",
                    "date",
                    "critical",
                    int(invalid_dates.sum()),
                    "Invalid dates require an explicit decision before report generation.",
                )
            )
        else:
            warnings.append(
                f"{int(invalid_dates.sum()):,} row(s) will be excluded from monthly analysis only."
            )

    returned_status = _availability_status(mapping_result, "returned")
    if returned_status == "not_provided":
        if frame["returned"].notna().any():
            issues.append(
                GenericPreflightIssue(
                    "returned_availability_mismatch",
                    "returned",
                    "critical",
                    int(frame["returned"].notna().sum()),
                    "returned is marked not_provided but contains non-null values.",
                )
            )
        else:
            warnings.append(RETURN_NOT_PROVIDED_MESSAGE)
    elif frame["returned"].isna().any():
        warnings.append(
            f"returned contains {int(frame['returned'].isna().sum()):,} unknown value(s)."
        )

    customer_status = _availability_status(mapping_result, "customer_id")
    if customer_status == "not_provided":
        warnings.append(CUSTOMER_NOT_PROVIDED_MESSAGE)
    elif customer_status == "partially_provided":
        warnings.append(CUSTOMER_PARTIALLY_PROVIDED_MESSAGE)
        customer_availability = next(
            (
                item
                for item in mapping_result.field_availability
                if item.field_name == "customer_id"
            ),
            None,
        )
        if customer_availability is not None:
            warnings.append(
                "Non-empty customer_id rows: "
                f"{customer_availability.provided_row_count or 0:,} / "
                f"{customer_availability.total_row_count or len(frame):,} valid rows."
            )
    elif customer_status == "mapping_conflict":
        conflict = next(
            (
                item.notes
                for item in mapping_result.field_availability
                if item.field_name == "customer_id"
            ),
            "Customer field mapping conflict. Customer analysis was skipped.",
        )
        warnings.append(conflict)

    for optional_field in ("customer_name", "product_name", "category"):
        if optional_field not in frame.columns:
            warnings.append(
                f"Optional descriptive field {optional_field} is unavailable."
            )

    if frame.empty:
        issues.append(
            GenericPreflightIssue(
                "no_calculation_rows",
                "dataset",
                "critical",
                0,
                "No rows remain for report calculations.",
            )
        )

    if not frame.empty:
        frame["unit_price"] = pd.to_numeric(frame["unit_price"], errors="coerce")
        frame["quantity"] = pd.to_numeric(frame["quantity"], errors="coerce")
        frame["discount_rate"] = pd.to_numeric(
            frame["discount_rate"], errors="coerce"
        )
        frame["date"] = remaining_dates

    required_null_counts = {
        field: int(frame[field].isna().sum())
        for field in REQUIRED_STANDARD_FIELDS
        if field in frame.columns
    }
    conversion_failure_counts = {
        item.standard_field: item.conversion_failure_count
        for item in mapping_result.diagnostics
    }
    valid_dates = remaining_dates.dropna()
    date_min = valid_dates.min() if not valid_dates.empty else None
    date_max = valid_dates.max() if not valid_dates.empty else None
    can_generate = not any(item.severity == "critical" for item in issues)
    estimated_memory = int(frame.memory_usage(index=True, deep=True).sum())

    return GenericReportPreflight(
        can_generate=can_generate,
        calculation_orders=frame if can_generate else frame,
        issues=tuple(issues),
        warnings=tuple(dict.fromkeys(warnings)),
        excluded_rows_detail=excluded_detail,
        critical_rows_preview=critical_preview,
        invalid_date_rows_preview=date_preview,
        original_fact_row_count=original_fact_row_count or len(source),
        merged_row_count=merged_row_count or len(source),
        unified_row_count=len(source),
        excluded_row_count=len(excluded_detail),
        calculation_row_count=len(frame),
        monthly_analysis_excluded_row_count=(
            int(invalid_dates.sum())
            if invalid_date_action == INVALID_DATE_ACTION_EXCLUDE_MONTHLY
            else 0
        ),
        required_null_counts=required_null_counts,
        conversion_failure_counts=conversion_failure_counts,
        date_min=date_min,
        date_max=date_max,
        estimated_memory_bytes=estimated_memory,
        invalid_date_action=invalid_date_action,
        explicit_critical_exclusion=exclude_invalid_price_quantity_rows,
    )


def build_data_preparation_summary(
    *,
    discovery_result,
    plan,
    decisions: Mapping[str, Any],
    mapping_result: StandardMappingResult,
    preflight: GenericReportPreflight,
) -> pd.DataFrame:
    """Build a compact audit trail for web, Markdown, and Excel."""
    rows = [
        {
            "section": "fact_table",
            "item": "selected_fact_table",
            "value": plan.fact_table,
            "notes": plan.fact_table_id,
        },
        {
            "section": "row_counts",
            "item": "original_fact_rows",
            "value": preflight.original_fact_row_count,
            "notes": "Before approved joins.",
        },
        {
            "section": "row_counts",
            "item": "merged_dataset_rows",
            "value": preflight.merged_row_count,
            "notes": "After safe many-to-one joins.",
        },
        {
            "section": "row_counts",
            "item": "unified_orders_rows",
            "value": preflight.unified_row_count,
            "notes": "Before explicit report exclusions.",
        },
        {
            "section": "row_counts",
            "item": "excluded_rows",
            "value": preflight.excluded_row_count,
            "notes": "Explicitly excluded from all calculations.",
        },
        {
            "section": "row_counts",
            "item": "monthly_analysis_excluded_rows",
            "value": preflight.monthly_analysis_excluded_row_count,
            "notes": "Invalid-date rows retained elsewhere but excluded from monthly analysis.",
        },
        {
            "section": "row_counts",
            "item": "final_calculation_rows",
            "value": preflight.calculation_row_count,
            "notes": "Rows passed to run_pipeline.",
        },
    ]

    for step in plan.steps:
        rows.append(
            {
                "section": "approved_relationship",
                "item": step.step_id,
                "value": (
                    f"{step.left_table} [{', '.join(step.left_columns)}] -> "
                    f"{step.right_table} [{', '.join(step.right_columns)}]"
                ),
                "notes": f"match_rate={step.match_rate:.2%}; confidence={step.confidence_score:.2f}",
            }
        )

    for decision in decisions.values():
        if decision.status != "rejected":
            continue
        candidate = decision.candidate
        rows.append(
            {
                "section": "rejected_relationship",
                "item": decision.original_candidate_id,
                "value": (
                    f"{candidate.left_table} [{', '.join(candidate.left_columns)}] -> "
                    f"{candidate.right_table} [{', '.join(candidate.right_columns)}]"
                ),
                "notes": "Explicitly rejected by user.",
            }
        )

    for item in mapping_result.field_availability:
        rows.append(
            {
                "section": "field_mapping",
                "item": item.field_name,
                "value": item.source_column or item.availability_status,
                "notes": item.notes,
            }
        )

    for reason, count in preflight.excluded_rows_detail.get(
        "exclusion_reason", pd.Series(dtype="string")
    ).value_counts().items():
        rows.append(
            {
                "section": "excluded_rows",
                "item": reason,
                "value": int(count),
                "notes": "User-confirmed exclusion.",
            }
        )

    return pd.DataFrame(rows, columns=["section", "item", "value", "notes"])


def _adapt_generic_report_tables(
    report_tables,
    availability_table,
    preparation_summary,
    excluded_rows_detail,
):
    tables = dict(report_tables)
    tables["field_availability"] = availability_table
    tables["data_preparation_summary"] = preparation_summary
    tables["excluded_rows_detail"] = excluded_rows_detail
    adapted = False

    if not customer_analysis_available(tables):
        tables["customer_summary"] = tables["customer_summary"].iloc[0:0].copy()
        validation = tables["validation_report"].copy()
        customer_checks = validation["check_name"].isin(
            {
                "customer_summary_revenue_equals_enriched_orders_final_revenue",
                "customer_gross_revenue_equals_enriched_orders_gross_revenue",
                "customer_units_equals_enriched_orders_units",
            }
        )
        validation.loc[
            customer_checks,
            ["expected_value", "actual_value", "difference"],
        ] = pd.NA
        validation.loc[customer_checks, "status"] = "not_applicable"
        tables["validation_report"] = validation
        adapted = True

    if get_field_availability_status(tables, "returned") == "not_provided":
        quality = tables["post_conversion_data_quality"].copy()
        invalid_mask = quality["check_name"] == "invalid_returned_count"
        quality.loc[invalid_mask, "issue_count"] = 0
        quality.loc[invalid_mask, "status"] = "not_applicable"
        quality = pd.concat(
            [
                quality,
                pd.DataFrame(
                    [
                        {
                            "check_name": "return_analysis_not_available",
                            "issue_count": 0,
                            "status": "not_available",
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )
        tables["post_conversion_data_quality"] = quality

        for table_name in (
            "monthly_summary",
            "category_summary",
            "customer_summary",
            "top_products",
        ):
            table = tables[table_name].copy()
            if "return_rate" in table.columns:
                table["return_rate"] = pd.Series(
                    pd.NA, index=table.index, dtype="Float64"
                )
            tables[table_name] = table

        anomalies = tables["anomalies"]
        if not anomalies.empty:
            tables["anomalies"] = anomalies.loc[
                anomalies["anomaly_type"] != "return_rate_over_15_percent"
            ].copy()
        adapted = True

    if adapted:
        tables["report_status"] = make_report_status_table(
            tables["data_quality_report"],
            tables["post_conversion_data_quality"],
            tables["validation_report"],
            tables["expense_post_conversion_quality"],
        )
        if (
            get_field_availability_status(tables, "customer_id")
            == "mapping_conflict"
            and tables["report_status"].iloc[0]["status"] != "failed"
        ):
            status = tables["report_status"].copy()
            status.loc[0, "status"] = "review_required"
            status.loc[0, "reason"] = (
                "Customer field mapping conflict; customer analysis was skipped."
            )
            status.loc[0, "warning_count"] = int(
                status.loc[0, "warning_count"]
            ) + 1
            tables["report_status"] = status

    return tables


def _generic_markdown_sections(
    preparation_summary: pd.DataFrame,
    availability_table: pd.DataFrame,
) -> str:
    lines = ["## Data Preparation Summary"]
    for _, row in preparation_summary.iterrows():
        lines.append(
            f"- {row['section']} / {row['item']}: {row['value']}. {row['notes']}"
        )

    lines.extend(["", "## Field Availability and Assumptions"])
    for _, row in availability_table.iterrows():
        source = row["source_column"] if pd.notna(row["source_column"]) else "N/A"
        default = row["default_value"] if pd.notna(row["default_value"]) else "N/A"
        lines.append(
            f"- {row['field_name']}: {row['availability_status']}; source={source}; "
            f"default={default}; user_confirmed={row['user_confirmed']}."
        )

    returned_status = get_field_availability_status(
        {"field_availability": availability_table}, "returned"
    )
    lines.extend(["", "## Return Analysis"])
    if returned_status == "not_provided":
        lines.extend(
            [
                "- Return Analysis: Not Available.",
                f"- {RETURN_NOT_PROVIDED_MESSAGE}",
                "- Return adjustments were not applied because return status was unavailable.",
            ]
        )
    else:
        lines.append("- Return Analysis: Available.")

    customer_status = get_field_availability_status(
        {"field_availability": availability_table}, "customer_id"
    )
    lines.extend(["", "## Customer Analysis"])
    if customer_status == "not_provided":
        lines.extend(
            [
                "- Customer Analysis: Not Available.",
                f"- {CUSTOMER_NOT_PROVIDED_MESSAGE}",
            ]
        )
    elif customer_status == "partially_provided":
        lines.extend(
            [
                "- Customer Analysis: Not Available.",
                f"- {CUSTOMER_PARTIALLY_PROVIDED_MESSAGE}",
            ]
        )
    elif customer_status == "mapping_conflict":
        conflict_notes = get_field_availability_notes(
            {"field_availability": availability_table}, "customer_id"
        )
        lines.extend(
            [
                "- Customer Analysis: Not Available.",
                f"- {conflict_notes}",
            ]
        )
    else:
        lines.append("- Customer Analysis: Available.")
    return "\n".join(lines)


def _insert_generic_markdown(summary_text, generic_sections):
    marker = "\n## Method"
    if marker in summary_text:
        return summary_text.replace(marker, f"\n\n{generic_sections}{marker}", 1)
    return summary_text.rstrip() + "\n\n" + generic_sections + "\n"


def _append_transparency_sheets(excel_path, report_tables):
    with pd.ExcelWriter(
        excel_path,
        engine="openpyxl",
        mode="a",
        if_sheet_exists="replace",
    ) as writer:
        if (
            not customer_analysis_available(report_tables)
            and "customer_summary" in writer.book.sheetnames
        ):
            writer.book.remove(writer.book["customer_summary"])
        for table_name, sheet_name in (
            ("data_preparation_summary", "data_preparation_summary"),
            ("field_availability", "field_availability"),
            ("excluded_rows_detail", "excluded_rows_detail"),
        ):
            report_tables[table_name].to_excel(
                writer, sheet_name=sheet_name, index=False
            )
            worksheet = writer.book[sheet_name]
            worksheet.freeze_panes = "A2"
            for cells in worksheet.columns:
                longest = max(
                    (len(str(cell.value)) for cell in cells if cell.value is not None),
                    default=0,
                )
                worksheet.column_dimensions[cells[0].column_letter].width = min(
                    longest + 2, 45
                )


def _read_source_bytes(source: Any) -> bytes:
    if isinstance(source, (str, Path)):
        return Path(source).read_bytes()
    original_position = None
    try:
        original_position = source.tell()
    except (AttributeError, OSError, ValueError):
        pass
    try:
        if hasattr(source, "getvalue"):
            data = source.getvalue()
        else:
            source.seek(0)
            data = source.read()
    finally:
        if original_position is not None:
            try:
                source.seek(original_position)
            except (AttributeError, OSError, ValueError):
                pass
    return data.encode("utf-8") if isinstance(data, str) else bytes(data)


def generate_generic_report(
    *,
    mapping_result: StandardMappingResult,
    preflight: GenericReportPreflight,
    discovery_result,
    plan,
    decisions: Mapping[str, Any],
    expenses_source=None,
    progress_callback: Callable[[int, str], None] | None = None,
):
    """Run the existing pipeline once, adding Generic transparency metadata."""
    def update(percent, message):
        if progress_callback is not None:
            progress_callback(percent, message)

    update(5, "1/5 Validating unified orders")
    if not preflight.can_generate or preflight.calculation_orders is None:
        raise GenericReportGenerationError(
            "Generic report preflight has unresolved critical issues."
        )
    if not mapping_result.success:
        raise GenericReportGenerationError("Standard field mapping is not valid.")

    availability = field_availability_table(mapping_result.field_availability)
    preparation = build_data_preparation_summary(
        discovery_result=discovery_result,
        plan=plan,
        decisions=decisions,
        mapping_result=mapping_result,
        preflight=preflight,
    )

    with TemporaryDirectory() as temp_dir_name:
        update(20, "2/5 Preparing temporary input")
        temp_dir = Path(temp_dir_name)
        orders_path = temp_dir / "orders.csv"
        expenses_path = temp_dir / "expenses.csv"
        excel_path = temp_dir / "sales_report.xlsx"
        summary_path = temp_dir / "summary.md"
        pipeline_orders = preflight.calculation_orders.copy(deep=False)
        if "customer_id" not in pipeline_orders.columns:
            pipeline_orders = pipeline_orders.assign(
                customer_id=pd.Series(
                    pd.NA, index=pipeline_orders.index, dtype="string"
                )
            )
        pipeline_orders.to_csv(orders_path, index=False)
        pipeline_expenses_path = expenses_path
        if expenses_source is not None:
            expenses_path.write_bytes(_read_source_bytes(expenses_source))

        update(40, "3/5 Running analysis")

        def transform(report_tables):
            return _adapt_generic_report_tables(
                report_tables,
                availability,
                preparation,
                preflight.excluded_rows_detail,
            )

        report_tables, excel_output, summary_output = run_pipeline(
            csv_path=orders_path,
            expenses_path=pipeline_expenses_path,
            excel_path=excel_path,
            summary_path=summary_path,
            report_tables_transform=transform,
        )

        update(75, "4/5 Generating Excel")
        _append_transparency_sheets(excel_output, report_tables)
        generic_sections = _generic_markdown_sections(preparation, availability)
        summary_text = _insert_generic_markdown(
            summary_output.read_text(encoding="utf-8"), generic_sections
        )
        summary_output.write_text(summary_text, encoding="utf-8")

        update(95, "5/5 Finalizing downloads")
        status_row = report_tables["report_status"].iloc[0]
        duplicate_detail = report_tables["duplicate_rows_detail"]
        duplicate_group_count = (
            int(duplicate_detail["duplicate_group_id"].nunique())
            if not duplicate_detail.empty
            else 0
        )
        result = {
            "report_kind": "generic",
            "status": status_row["status"],
            "reason": status_row["reason"],
            "expenses_uploaded": expenses_source is not None,
            "report_tables": report_tables,
            "original_row_count": preflight.original_fact_row_count,
            "calculation_row_count": preflight.calculation_row_count,
            "removed_row_count": 0,
            "excluded_row_count": preflight.excluded_row_count,
            "monthly_analysis_excluded_row_count": (
                preflight.monthly_analysis_excluded_row_count
            ),
            "duplicate_group_count": duplicate_group_count,
            "duplicate_row_count": len(duplicate_detail),
            "duplicate_rows_detail": duplicate_detail,
            "excluded_rows_detail": preflight.excluded_rows_detail,
            "field_availability": availability,
            "data_preparation_summary": preparation,
            "excel_bytes": excel_output.read_bytes(),
            "summary_text": summary_text,
        }
        update(100, "Report ready")
        return result
