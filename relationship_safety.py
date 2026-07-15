from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


MINIMUM_ORDER_GRAIN_MATCH_RATE = 0.20
NULL_KEY_TOKENS = frozenset({"", "nan", "none", "null", "<na>", "nat"})
ZERO_WIDTH_PATTERN = r"[\u200b\u200c\u200d\ufeff]"
FORMAT_DIAGNOSTIC_SAMPLE_SIZE = 5_000


@dataclass(frozen=True)
class JoinSafetyAssessment:
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
    expected_join_type: str
    many_to_many_risk: bool
    row_inflation: bool
    fact_to_fact_risk: bool
    blocked: bool
    block_reasons: tuple[str, ...]
    risk_flags: tuple[str, ...]
    format_warnings: tuple[str, ...]


def _normalize_text_key_series(series: pd.Series) -> pd.Series:
    values = series.astype("string").str.normalize("NFKC")
    values = values.str.replace(ZERO_WIDTH_PATTERN, "", regex=True)
    values = values.str.replace("\u00a0", " ", regex=False)
    values = values.str.replace(r"\s+", " ", regex=True).str.strip().str.casefold()
    return values.mask(values.isin(NULL_KEY_TOKENS))


def canonicalize_key_series(series: pd.Series, comparison_kind: str) -> pd.Series:
    """Return a normalized copy used for relationship comparison and safe joins."""
    values = _normalize_text_key_series(series)
    if comparison_kind == "date":
        parsed = pd.to_datetime(values, errors="coerce", format="mixed")
        return parsed.dt.normalize().dt.strftime("%Y-%m-%d").astype("string")

    if comparison_kind == "numeric":
        cleaned = values.str.replace(",", "", regex=False)
        numeric = pd.to_numeric(cleaned, errors="coerce")
        normalized = numeric.map(
            lambda value: format(value, ".15g") if pd.notna(value) else pd.NA
        )
        return normalized.astype("string")

    return values


def _leading_zero_format_warning(
    left: pd.Series,
    right: pd.Series,
) -> str | None:
    left_sample = left.dropna().head(FORMAT_DIAGNOSTIC_SAMPLE_SIZE)
    right_sample = right.dropna().head(FORMAT_DIAGNOSTIC_SAMPLE_SIZE)
    left_text = canonicalize_key_series(left_sample, "text").dropna()
    right_text = canonicalize_key_series(right_sample, "text").dropna()
    combined = pd.concat([left_text, right_text], ignore_index=True)
    if not combined.str.match(r"^[+-]?0\d+$", na=False).any():
        return None

    left_numeric = canonicalize_key_series(left_sample, "numeric").dropna()
    right_numeric = canonicalize_key_series(right_sample, "numeric").dropna()
    text_overlap = set(left_text.unique()).intersection(right_text.unique())
    numeric_overlap = set(left_numeric.unique()).intersection(right_numeric.unique())
    if len(numeric_overlap) <= len(text_overlap):
        return None
    return (
        "Key formats may differ because leading zeros are present; values such as "
        "'001' and '1' were not treated as the same text identifier."
    )


def _canonicalize_keys(
    frame: pd.DataFrame,
    columns: tuple[str, ...],
    comparison_kinds: tuple[str, ...],
) -> pd.Series:
    parts = [
        canonicalize_key_series(frame[column], kind).rename(str(index))
        for index, (column, kind) in enumerate(zip(columns, comparison_kinds))
    ]
    key_frame = pd.concat(parts, axis=1)
    valid = key_frame.notna().all(axis=1)
    valid_frame = key_frame.loc[valid]

    if len(columns) == 1:
        return valid_frame.iloc[:, 0]

    tuples = list(valid_frame.itertuples(index=False, name=None))
    return pd.Series(tuples, index=valid_frame.index, dtype="object")


def _uniqueness(counts: pd.Series) -> float:
    row_count = int(counts.sum())
    return float(len(counts) / row_count) if row_count else 0.0


def evaluate_join_safety(
    left: pd.DataFrame,
    right: pd.DataFrame,
    left_columns: tuple[str, ...],
    right_columns: tuple[str, ...],
    comparison_kinds: tuple[str, ...],
    left_role: str,
    right_role: str,
    left_entity_role: str = "unknown",
    right_entity_role: str = "unknown",
) -> JoinSafetyAssessment:
    """Compute join cardinality and row inflation without performing a merge."""
    if len(left_columns) != len(right_columns):
        raise ValueError("Left and right relationship keys must have equal lengths.")
    if len(left_columns) != len(comparison_kinds):
        raise ValueError("Every relationship key needs a comparison kind.")

    left_keys = _canonicalize_keys(left, left_columns, comparison_kinds)
    right_keys = _canonicalize_keys(right, right_columns, comparison_kinds)
    left_counts = left_keys.value_counts(dropna=True, sort=False)
    right_counts = right_keys.value_counts(dropna=True, sort=False)
    left_null_key_count = int(len(left) - len(left_keys))
    right_null_key_count = int(len(right) - len(right_keys))

    right_index = right_counts.index
    matched_left_counts = left_counts[left_counts.index.isin(right_index)]
    matched_row_count = int(matched_left_counts.sum())
    match_rate = float(matched_row_count / len(left)) if len(left) else 0.0
    distinct_overlap_rate = (
        float(len(matched_left_counts) / len(left_counts)) if len(left_counts) else 0.0
    )

    right_duplicates = right_counts[right_counts > 1]
    right_duplicate_key_count = int(len(right_duplicates))
    right_duplicate_row_count = int(right_duplicates.sum())

    left_duplicate_keys = set(left_counts[left_counts > 1].index)
    right_duplicate_keys = set(right_duplicates.index)
    many_to_many_keys = left_duplicate_keys.intersection(right_duplicate_keys)
    many_to_many_risk = bool(many_to_many_keys)

    right_multiplicity = right_counts.reindex(left_counts.index).fillna(1)
    additional_rows = int(
        ((right_multiplicity - 1).clip(lower=0) * left_counts).sum()
    )
    before_row_count = int(len(left))
    after_row_count = before_row_count + additional_rows
    row_inflation = additional_rows > 0

    left_key_uniqueness = _uniqueness(left_counts)
    right_key_uniqueness = _uniqueness(right_counts)
    left_is_unique = not left_counts.empty and left_key_uniqueness == 1.0
    right_is_unique = not right_counts.empty and right_key_uniqueness == 1.0
    if left_is_unique and right_is_unique:
        expected_join_type = "one_to_one"
    elif right_is_unique:
        expected_join_type = "many_to_one"
    elif left_is_unique:
        expected_join_type = "one_to_many"
    else:
        expected_join_type = "many_to_many"

    is_order_line_to_header = (
        left_entity_role == "order_line" and right_entity_role == "order_header"
    )
    fact_to_fact_risk = (
        left_role == "fact"
        and right_role == "fact"
        and not is_order_line_to_header
    )
    block_reasons: list[str] = []
    risk_flags: list[str] = []
    format_warnings = tuple(
        warning
        for left_column, right_column in zip(left_columns, right_columns)
        if (warning := _leading_zero_format_warning(
            left[left_column], right[right_column]
        ))
    )
    if format_warnings:
        risk_flags.append("key_format_mismatch")

    if right_null_key_count:
        risk_flags.append("right_key_nulls")
        block_reasons.append(
            f"Right relationship key contains {right_null_key_count} null key row(s)."
        )
    if right_duplicate_key_count:
        risk_flags.append("right_key_not_unique")
        block_reasons.append(
            "Right key is not unique: "
            f"{right_duplicate_key_count} duplicate key group(s) across "
            f"{right_duplicate_row_count} row(s)."
        )
    if many_to_many_risk:
        risk_flags.append("many_to_many")
        block_reasons.append(
            "Many-to-many risk: at least one matched key repeats on both tables."
        )
    if row_inflation:
        risk_flags.append("row_inflation")
        block_reasons.append(
            "Dry-run left join would increase rows from "
            f"{before_row_count} to {after_row_count} (+{additional_rows})."
        )
    if fact_to_fact_risk:
        risk_flags.append("fact_to_fact")
        block_reasons.append(
            "Both tables are classified as fact tables; their grains may differ."
        )
    if is_order_line_to_header and match_rate < MINIMUM_ORDER_GRAIN_MATCH_RATE:
        risk_flags.append("order_line_to_header_low_match")
        block_reasons.append(
            "Order-line to order-header match rate "
            f"{match_rate:.1%} is below the required "
            f"{MINIMUM_ORDER_GRAIN_MATCH_RATE:.1%}."
        )

    return JoinSafetyAssessment(
        match_rate=match_rate,
        distinct_overlap_rate=distinct_overlap_rate,
        left_key_uniqueness=left_key_uniqueness,
        right_key_uniqueness=right_key_uniqueness,
        left_null_key_count=left_null_key_count,
        right_null_key_count=right_null_key_count,
        right_duplicate_key_count=right_duplicate_key_count,
        right_duplicate_row_count=right_duplicate_row_count,
        before_row_count=before_row_count,
        after_row_count=after_row_count,
        row_count_change=additional_rows,
        expected_join_type=expected_join_type,
        many_to_many_risk=many_to_many_risk,
        row_inflation=row_inflation,
        fact_to_fact_risk=fact_to_fact_risk,
        blocked=bool(block_reasons),
        block_reasons=tuple(block_reasons),
        risk_flags=tuple(risk_flags),
        format_warnings=format_warnings,
    )
