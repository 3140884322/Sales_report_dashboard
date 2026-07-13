from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass(frozen=True)
class FieldMappingRecommendation:
    """One explainable source or fallback recommendation for a standard field."""

    standard_field: str
    required: bool
    target_type: str
    recommended_strategy: str
    recommended_source: str | None
    confidence_score: float
    score_breakdown: dict[str, float]
    explanation: str


@dataclass(frozen=True)
class StandardFieldSelection:
    """One explicit user choice. Required mappings are inert until confirmed."""

    standard_field: str
    strategy: str
    source_column: str | None = None
    confirmed: bool = False


@dataclass(frozen=True)
class StandardFieldMappingPlan:
    """Validated B2.1 boundary that B2.2 can consume without UI state."""

    selections: tuple[StandardFieldSelection, ...]
    selected_extension_columns: tuple[str, ...]
    validation_status: str
    validation_errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class FieldConversionDiagnostic:
    """Observed conversion quality for one selected standard field."""

    standard_field: str
    required: bool
    source_or_strategy: str
    confidence_score: float
    score_breakdown: dict[str, float]
    source_non_null_count: int
    conversion_failure_count: int
    invalid_value_count: int
    null_count: int
    null_rate: float
    output_dtype: str
    status: str
    explanation: str


@dataclass(frozen=True)
class FieldAvailability:
    """Auditable availability and assumption metadata for one standard field."""

    field_name: str
    availability_status: str
    source_column: str | None
    default_value: object | None
    user_confirmed: bool
    notes: str


@dataclass
class StandardMappingResult:
    """B2.1 output. Successful results contain only approved output columns."""

    success: bool
    plan: StandardFieldMappingPlan | None
    unified_orders: pd.DataFrame | None = field(repr=False, compare=False)
    diagnostics: tuple[FieldConversionDiagnostic, ...]
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    source_row_count: int
    output_row_count: int | None
    source_column_count: int
    output_column_count: int | None
    source_memory_bytes: int
    output_memory_bytes: int | None
    report_columns: tuple[str, ...]
    field_availability: tuple[FieldAvailability, ...] = ()
