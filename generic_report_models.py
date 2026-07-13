from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass(frozen=True)
class GenericPreflightIssue:
    """One blocking or reviewable issue found before Generic reporting."""

    issue_code: str
    field_name: str
    severity: str
    row_count: int
    message: str
    excludable: bool = False


@dataclass
class GenericReportPreflight:
    """Explicit calculation and exclusion plan for a confirmed unified dataset."""

    can_generate: bool
    calculation_orders: pd.DataFrame | None = field(repr=False, compare=False)
    issues: tuple[GenericPreflightIssue, ...]
    warnings: tuple[str, ...]
    excluded_rows_detail: pd.DataFrame = field(repr=False, compare=False)
    critical_rows_preview: pd.DataFrame = field(repr=False, compare=False)
    invalid_date_rows_preview: pd.DataFrame = field(repr=False, compare=False)
    original_fact_row_count: int
    merged_row_count: int
    unified_row_count: int
    excluded_row_count: int
    calculation_row_count: int
    monthly_analysis_excluded_row_count: int
    required_null_counts: dict[str, int]
    conversion_failure_counts: dict[str, int]
    date_min: pd.Timestamp | None
    date_max: pd.Timestamp | None
    estimated_memory_bytes: int
    invalid_date_action: str
    explicit_critical_exclusion: bool

