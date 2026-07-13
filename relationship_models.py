from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class LoadedTable:
    """One independently discoverable table loaded from a CSV or workbook sheet."""

    table_id: str
    table_name: str
    source_name: str
    frame: pd.DataFrame = field(repr=False, compare=False)
    sheet_name: str | None = None
    encoding: str | None = None


@dataclass
class ColumnProfile:
    """Read-only statistical and semantic profile for one source column."""

    table_id: str
    table_name: str
    column_name: str
    position: int
    pandas_dtype: str
    semantic_type: str
    row_count: int
    non_null_count: int
    null_count: int
    null_rate: float
    unique_count: int
    unique_rate: float
    sample_values: tuple[str, ...]
    normalized_name: str
    semantic_tokens: tuple[str, ...]
    is_key_like: bool
    is_measure_like: bool
    numeric_parse_rate: float
    date_parse_rate: float


@dataclass
class TableProfile:
    """Shape, column profiles, and inferred analytical role for one table."""

    table_id: str
    table_name: str
    source_name: str
    sheet_name: str | None
    row_count: int
    column_count: int
    columns: tuple[ColumnProfile, ...]
    role_guess: str = "unknown"
    role_confidence: float = 0.0
    role_evidence: tuple[str, ...] = ()

    def get_column(self, column_name: str) -> ColumnProfile:
        for column in self.columns:
            if column.column_name == column_name:
                return column
        raise KeyError(f"Column {column_name!r} was not found in {self.table_name!r}.")


@dataclass
class RelationshipCandidate:
    """A suggested relationship. Discovery never changes its pending decision state."""

    candidate_id: str
    left_table_id: str
    left_table: str
    left_columns: tuple[str, ...]
    right_table_id: str
    right_table: str
    right_columns: tuple[str, ...]
    relationship_kind: str
    comparison_kinds: tuple[str, ...]
    expected_join_type: str
    confidence_score: float
    confidence_level: str
    score_breakdown: dict[str, float]
    explanation: str
    match_rate: float
    distinct_overlap_rate: float
    left_key_uniqueness: float
    right_key_uniqueness: float
    left_null_key_count: int
    right_null_key_count: int
    right_duplicate_key_count: int
    right_duplicate_row_count: int
    before_row_count: int
    after_row_count: int
    row_count_change: int
    many_to_many_risk: bool
    row_inflation: bool
    fact_to_fact_risk: bool
    blocked: bool
    block_reasons: tuple[str, ...]
    risk_flags: tuple[str, ...]
    decision_status: str = "pending"
    auto_apply: bool = False


@dataclass(frozen=True)
class RelationshipDecision:
    """One explicit user decision about an original or edited candidate."""

    original_candidate_id: str
    status: str
    candidate: RelationshipCandidate
    edited: bool = False


@dataclass(frozen=True)
class ApprovedJoinStep:
    """One ordered, approved many-to-one expansion in a join plan."""

    step_id: str
    source_candidate_id: str
    left_table_id: str
    left_table: str
    left_columns: tuple[str, ...]
    right_table_id: str
    right_table: str
    right_columns: tuple[str, ...]
    comparison_kinds: tuple[str, ...]
    confidence_score: float
    match_rate: float
    right_key_uniqueness: float
    expected_join_type: str
    edited: bool = False


@dataclass(frozen=True)
class ApprovedJoinPlan:
    """A validated, root-connected and topologically ordered join plan."""

    fact_table_id: str
    fact_table: str
    steps: tuple[ApprovedJoinStep, ...]
    validation_status: str
    validation_errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class MergeStepDiagnostic:
    """Observed or preflight diagnostics for one safe merge step."""

    step_id: str
    left_table: str
    right_table: str
    left_columns: tuple[str, ...]
    right_columns: tuple[str, ...]
    rows_before: int
    rows_after: int | None
    matched_rows: int | None
    unmatched_rows: int | None
    match_rate: float | None
    row_growth: int | None
    validation_status: str
    error_message: str = ""


@dataclass
class SafeMergeResult:
    """B1 execution result. Failed runs never expose a merged DataFrame."""

    success: bool
    fact_table_id: str
    fact_table: str
    fact_row_count: int
    final_row_count: int | None
    merged_frame: pd.DataFrame | None = field(repr=False, compare=False)
    diagnostics: tuple[MergeStepDiagnostic, ...]
    error_message: str = ""


@dataclass
class RelationshipDiscoveryResult:
    """Stage A output and the future input boundary for a confirmed merge plan."""

    tables: tuple[LoadedTable, ...]
    table_profiles: tuple[TableProfile, ...]
    relationships: tuple[RelationshipCandidate, ...]
    diagnostics: dict[str, Any]

    def get_table(self, table_id: str) -> LoadedTable:
        for table in self.tables:
            if table.table_id == table_id:
                return table
        raise KeyError(f"Table {table_id!r} was not found in the discovery result.")
