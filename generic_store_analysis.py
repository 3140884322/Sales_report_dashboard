from __future__ import annotations

from dataclasses import dataclass
import re

import pandas as pd

from standard_field_mapping import (
    STORE_NAME_GROUPING_NOTE,
    STORE_NOT_PROVIDED_MESSAGE,
    STORE_PARTIALLY_PROVIDED_MESSAGE,
)


STORE_SUMMARY_COLUMNS = (
    "store_id",
    "store_name",
    "revenue",
    "orders",
    "units",
    "aov",
    "revenue_share",
)
UNASSIGNED_STORE = "Unassigned Store"


@dataclass(frozen=True)
class StoreAnalysisResult:
    availability_status: str
    provided_row_count: int
    total_row_count: int
    notes: str
    grouped_by_name: bool
    summary: pd.DataFrame


def _present_mask(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip()
    return series.notna() & text.ne("")


def _clean_text(series: pd.Series) -> pd.Series:
    present = _present_mask(series)
    return series.astype("string").str.strip().mask(~present, pd.NA)


def _clean_identifier_value(value: object) -> object:
    if pd.isna(value):
        return pd.NA
    text = str(value).strip()
    if not text:
        return pd.NA
    if re.fullmatch(r"[+-]?\d+\.0+", text):
        return text.split(".", 1)[0]
    return text


def _availability_status(availability_table: pd.DataFrame) -> str:
    if availability_table is None or availability_table.empty:
        return "provided"
    matches = availability_table.loc[
        availability_table["field_name"] == "store_analysis",
        "availability_status",
    ]
    return str(matches.iloc[0]) if not matches.empty else "provided"


def _empty_summary() -> pd.DataFrame:
    return pd.DataFrame(columns=STORE_SUMMARY_COLUMNS)


def build_store_analysis(
    enriched_orders: pd.DataFrame,
    availability_table: pd.DataFrame,
) -> StoreAnalysisResult:
    """Aggregate optional store metrics without changing enriched orders."""
    total_rows = len(enriched_orders)
    mapped_status = _availability_status(availability_table)
    if mapped_status == "mapping_conflict":
        matches = availability_table.loc[
            availability_table["field_name"] == "store_analysis", "notes"
        ]
        notes = (
            str(matches.iloc[0])
            if not matches.empty
            else "Store field mapping conflict. Store analysis was skipped."
        )
        return StoreAnalysisResult(
            "mapping_conflict", 0, total_rows, notes, False, _empty_summary()
        )

    store_id = (
        _clean_text(enriched_orders["store_id"]).map(_clean_identifier_value)
        if "store_id" in enriched_orders.columns
        else pd.Series(pd.NA, index=enriched_orders.index, dtype="string")
    )
    store_id = store_id.astype("string")
    store_name = (
        _clean_text(enriched_orders["store_name"])
        if "store_name" in enriched_orders.columns
        else pd.Series(pd.NA, index=enriched_orders.index, dtype="string")
    )
    present = store_id.notna() | store_name.notna()
    provided_rows = int(present.sum())
    grouped_by_name = bool(provided_rows and not store_id.notna().any())

    if provided_rows == 0:
        return StoreAnalysisResult(
            "not_provided",
            0,
            total_rows,
            STORE_NOT_PROVIDED_MESSAGE,
            False,
            _empty_summary(),
        )

    coverage_note = (
        f"Store data was available for {provided_rows:,} of {total_rows:,} "
        "transaction rows."
    )
    if provided_rows < total_rows:
        status = "partially_provided"
        notes = f"{STORE_PARTIALLY_PROVIDED_MESSAGE} {coverage_note}"
    else:
        status = "provided"
        notes = coverage_note
    if grouped_by_name:
        notes = f"{notes} {STORE_NAME_GROUPING_NOTE}"

    work = pd.DataFrame(index=enriched_orders.index)
    work["store_id"] = store_id
    work["source_store_name"] = store_name
    work["group_key"] = pd.Series(UNASSIGNED_STORE, index=work.index, dtype="string")
    id_mask = store_id.notna()
    name_only_mask = ~id_mask & store_name.notna()
    work.loc[id_mask, "group_key"] = "id:" + store_id.loc[id_mask]
    work.loc[name_only_mask, "group_key"] = "name:" + store_name.loc[name_only_mask]
    work["revenue"] = pd.to_numeric(
        enriched_orders["final_revenue"], errors="coerce"
    )
    work["quantity"] = pd.to_numeric(enriched_orders["quantity"], errors="coerce")
    work["order_id"] = enriched_orders["order_id"]

    rows = []
    for group_key, group in work.groupby("group_key", sort=False, dropna=False):
        is_unassigned = group_key == UNASSIGNED_STORE
        ids = group["store_id"].dropna()
        names = group["source_store_name"].dropna()
        store_id_value = ids.iloc[0] if not ids.empty else pd.NA
        if is_unassigned:
            display_name = UNASSIGNED_STORE
        elif not names.empty:
            display_name = names.iloc[0]
        elif pd.notna(store_id_value):
            display_name = f"Store {store_id_value}"
        else:
            display_name = str(group_key).removeprefix("name:")
        revenue = float(group["revenue"].sum())
        orders = int(group["order_id"].nunique(dropna=True))
        units = float(group["quantity"].sum())
        rows.append(
            {
                "store_id": store_id_value,
                "store_name": display_name,
                "revenue": revenue,
                "orders": orders,
                "units": units,
                "aov": revenue / orders if orders else 0.0,
            }
        )

    summary = pd.DataFrame(rows)
    total_revenue = float(summary["revenue"].sum())
    summary["revenue_share"] = (
        summary["revenue"] / total_revenue if total_revenue else 0.0
    )
    summary = summary.sort_values("revenue", ascending=False, kind="stable")
    summary = summary.loc[:, STORE_SUMMARY_COLUMNS].reset_index(drop=True)
    return StoreAnalysisResult(
        status,
        provided_rows,
        total_rows,
        notes,
        grouped_by_name,
        summary,
    )


def valid_store_summary(store_summary: pd.DataFrame) -> pd.DataFrame:
    if store_summary is None or store_summary.empty:
        return _empty_summary()
    return store_summary.loc[
        store_summary["store_name"].ne(UNASSIGNED_STORE)
    ].copy()


def store_analysis_available(report_tables) -> bool:
    availability = report_tables.get("field_availability")
    status = _availability_status(availability)
    summary = report_tables.get("store_summary")
    return status in {"provided", "partially_provided"} and summary is not None


def store_analysis_unavailable_message(report_tables) -> str:
    availability = report_tables.get("field_availability")
    status = _availability_status(availability)
    if status == "mapping_conflict" and availability is not None:
        matches = availability.loc[
            availability["field_name"] == "store_analysis", "notes"
        ]
        if not matches.empty:
            return str(matches.iloc[0])
    return STORE_NOT_PROVIDED_MESSAGE
