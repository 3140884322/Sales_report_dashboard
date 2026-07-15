from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
import re
from statistics import median
from typing import Any

import pandas as pd
from pandas.api.types import (
    is_bool_dtype,
    is_datetime64_any_dtype,
    is_numeric_dtype,
)

from generic_table_reader import read_tabular_sources
from relationship_aliases import (
    ENTITY_ROLE_ALIASES,
    FIELD_ENTITY_ALIASES,
    NameMatch,
    compare_column_names,
    contains_alias,
    is_key_like_name,
    is_measure_like_name,
    normalize_column_name,
    semantic_tokens,
)
from relationship_models import (
    ColumnProfile,
    LoadedTable,
    RelationshipCandidate,
    RelationshipDiscoveryResult,
    TableProfile,
)
from relationship_safety import (
    JoinSafetyAssessment,
    canonicalize_key_series,
    evaluate_join_safety,
)


class RelationshipDiscoveryError(ValueError):
    """Raised when tables cannot be profiled for relationship discovery."""


@dataclass(frozen=True)
class DiscoveryConfig:
    profile_parse_sample_size: int = 5000
    sample_value_count: int = 5
    minimum_name_score: float = 12.0
    minimum_match_rate: float = 0.20
    minimum_candidate_score: float = 45.0
    maximum_prefiltered_pairs_per_table_pair: int = 16
    maximum_composite_components: int = 6
    composite_minimum_right_uniqueness: float = 0.95
    fallback_minimum_non_null_count: int = 5
    fallback_minimum_match_rate: float = 0.85
    fallback_minimum_right_uniqueness: float = 0.98
    fallback_sample_size: int = 2000
    fallback_maximum_columns_per_table: int = 8
    fallback_maximum_pairs_per_table_pair: int = 4
    fallback_maximum_confidence: float = 79.99


@dataclass(frozen=True)
class _TypeMatch:
    compatible: bool
    score: float
    comparison_kind: str
    reason: str


@dataclass
class _PairEvidence:
    left_column: ColumnProfile
    right_column: ColumnProfile
    name_match: NameMatch
    type_match: _TypeMatch
    safety: JoinSafetyAssessment


def _contains_normalized_phrase(value: str, phrase: str) -> bool:
    return contains_alias(value, phrase)


def infer_table_entity_role(
    table: LoadedTable,
) -> tuple[str, float, tuple[str, ...]]:
    """Infer a business entity from table, sheet, file, and column combinations."""
    name_signals = [table.table_name, table.sheet_name or "", table.source_name]
    normalized_signals = [normalize_column_name(value) for value in name_signals if value]
    for role, aliases in ENTITY_ROLE_ALIASES:
        for signal in normalized_signals:
            if any(contains_alias(signal, alias) for alias in aliases):
                return role, 0.98, (f"name signal: {signal}",)

    column_concepts = {
        concept
        for column in table.frame.columns
        for concept in semantic_tokens(column)
    }
    if {"order", "product", "quantity"}.issubset(column_concepts):
        return "order_line", 0.90, ("OrderID + ProductID + Quantity columns",)
    if {"order", "date"}.issubset(column_concepts):
        return "order_header", 0.88, ("OrderID + OrderDate columns",)
    for role, aliases in FIELD_ENTITY_ALIASES:
        if any(
            contains_alias(column, alias)
            for column in table.frame.columns
            for alias in aliases
        ):
            return role, 0.75, ("entity identifier column combination",)
    return "unknown", 0.0, ()


def infer_column_entity_role(
    column_name: str,
    table_entity_role: str,
) -> tuple[str, float, tuple[str, ...]]:
    """Infer what business entity one field identifies or describes."""
    normalized = normalize_column_name(column_name)
    for role, aliases in FIELD_ENTITY_ALIASES:
        if any(contains_alias(normalized, alias) for alias in aliases):
            return role, 0.95, (f"column signal: {normalized}",)
    if table_entity_role != "unknown":
        return table_entity_role, 0.80, (f"inherited from {table_entity_role} table",)
    return "unknown", 0.0, ()


def _display_value(value: Any) -> str:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value)


def _parse_rate(parsed: pd.Series) -> float:
    return float(parsed.notna().mean()) if len(parsed) else 0.0


def _profile_column(
    table: LoadedTable,
    column_name: str,
    position: int,
    config: DiscoveryConfig,
    table_entity_role: str = "unknown",
) -> ColumnProfile:
    series = table.frame[column_name]
    row_count = int(len(series))
    non_null = series.dropna()
    non_null_count = int(len(non_null))
    null_count = row_count - non_null_count
    null_rate = float(null_count / row_count) if row_count else 0.0
    unique_count = int(series.nunique(dropna=True))
    unique_rate = (
        float(unique_count / non_null_count) if non_null_count else 0.0
    )

    concepts = semantic_tokens(column_name)
    key_like = is_key_like_name(column_name, concepts)
    measure_like = is_measure_like_name(column_name, concepts)
    parse_sample = non_null.head(config.profile_parse_sample_size)

    if is_numeric_dtype(series.dtype) and not is_bool_dtype(series.dtype):
        numeric_parse_rate = 1.0 if non_null_count else 0.0
    else:
        numeric_text = (
            parse_sample.astype("string")
            .str.strip()
            .str.replace(r"[$£€¥,\s]", "", regex=True)
        )
        numeric_parse_rate = _parse_rate(
            pd.to_numeric(numeric_text, errors="coerce")
        )

    should_parse_dates = "date" in concepts or is_datetime64_any_dtype(series.dtype)
    if should_parse_dates:
        date_parse_rate = _parse_rate(
            pd.to_datetime(parse_sample, errors="coerce", format="mixed")
        )
    else:
        date_parse_rate = 0.0

    if non_null_count == 0:
        semantic_type = "empty"
    elif is_bool_dtype(series.dtype):
        semantic_type = "boolean"
    elif should_parse_dates and date_parse_rate >= 0.70:
        semantic_type = "date"
    elif "currency" in concepts:
        semantic_type = "categorical_code"
    elif key_like:
        semantic_type = "identifier"
    elif measure_like and numeric_parse_rate >= 0.70:
        semantic_type = "numeric_measure"
    elif is_numeric_dtype(series.dtype):
        semantic_type = "numeric"
    else:
        semantic_type = "text"

    sample_values = tuple(
        _display_value(value)
        for value in non_null.drop_duplicates().head(config.sample_value_count)
    )
    entity_role, entity_confidence, entity_evidence = infer_column_entity_role(
        column_name, table_entity_role
    )
    return ColumnProfile(
        table_id=table.table_id,
        table_name=table.table_name,
        column_name=column_name,
        position=position,
        pandas_dtype=str(series.dtype),
        semantic_type=semantic_type,
        row_count=row_count,
        non_null_count=non_null_count,
        null_count=null_count,
        null_rate=null_rate,
        unique_count=unique_count,
        unique_rate=unique_rate,
        sample_values=sample_values,
        normalized_name=normalize_column_name(column_name),
        semantic_tokens=concepts,
        is_key_like=key_like,
        is_measure_like=measure_like,
        numeric_parse_rate=numeric_parse_rate,
        date_parse_rate=date_parse_rate,
        entity_role=entity_role,
        entity_role_confidence=entity_confidence,
        entity_role_evidence=entity_evidence,
    )


def _validate_table(table: LoadedTable) -> None:
    if not isinstance(table.frame, pd.DataFrame):
        raise RelationshipDiscoveryError(
            f"Table {table.table_name!r} does not contain a pandas DataFrame."
        )
    if not all(isinstance(column, str) for column in table.frame.columns):
        raise RelationshipDiscoveryError(
            f"Table {table.table_name!r} must use text column titles."
        )
    if table.frame.columns.duplicated().any():
        raise RelationshipDiscoveryError(
            f"Table {table.table_name!r} contains duplicate column titles."
        )


def _role_scores(
    profile: TableProfile,
    max_rows: int,
    median_rows: float,
) -> tuple[float, float, list[str], list[str]]:
    columns = profile.columns
    all_concepts = {concept for column in columns for concept in column.semantic_tokens}
    measures = [column for column in columns if column.semantic_type == "numeric_measure"]
    dates = [column for column in columns if column.semantic_type == "date"]
    keys = [column for column in columns if column.is_key_like]
    unique_keys = [
        column
        for column in keys
        if column.unique_rate >= 0.98 and column.null_rate <= 0.05
    ]
    repeated_keys = [column for column in keys if column.unique_rate < 0.95]
    descriptive = [
        column
        for column in columns
        if column.semantic_type in {"text", "categorical_code"}
        and not column.is_key_like
        and not column.is_measure_like
    ]

    fact_score = 0.0
    dimension_score = 0.0
    fact_evidence: list[str] = []
    dimension_evidence: list[str] = []

    if "order" in all_concepts:
        fact_score += 0.25
        fact_evidence.append("order/transaction columns")
    if "line_item" in all_concepts:
        fact_score += 0.10
        fact_evidence.append("line-item grain")
    if measures:
        fact_score += 0.20
        fact_evidence.append("numeric measures")
    if dates:
        fact_score += 0.10
        fact_evidence.append("dated records")
    if len(repeated_keys) >= 2:
        fact_score += 0.20
        fact_evidence.append("multiple repeating foreign-key-like columns")
    if max_rows and profile.row_count == max_rows and max_rows > median_rows:
        fact_score += 0.10
        fact_evidence.append("largest table")
    if median_rows and profile.row_count >= 2 * median_rows:
        fact_score += 0.05
        fact_evidence.append("row count materially above median")
    if profile.entity_role in {"order_line", "order_header"}:
        fact_score += 0.10
        fact_evidence.append("table/file name suggests sales or orders")

    if unique_keys:
        dimension_score += 0.30
        dimension_evidence.append("near-unique key-like column")
    if len(descriptive) >= 2:
        dimension_score += 0.20
        dimension_evidence.append("multiple descriptive attributes")
    if max_rows and profile.row_count <= max_rows * 0.50:
        dimension_score += 0.15
        dimension_evidence.append("smaller than the largest table")
    if all_concepts.intersection({"customer", "product", "store", "category"}):
        dimension_score += 0.15
        dimension_evidence.append("entity-oriented columns")
    if profile.entity_role in {
        "customer", "product", "store", "category", "supplier", "employee",
        "shipper", "region", "warehouse",
    }:
        dimension_score += 0.10
        dimension_evidence.append("table/file name suggests reference data")
    has_categorical_code = any(
        column.semantic_type == "categorical_code" for column in columns
    )
    if (
        dates
        and has_categorical_code
        and "order" not in all_concepts
        and len(columns) <= 4
        and len(measures) <= 1
    ):
        dimension_score += 0.25
        dimension_evidence.append("date/code lookup shape")

    return fact_score, dimension_score, fact_evidence, dimension_evidence


def _assign_table_roles(profiles: list[TableProfile]) -> None:
    row_counts = [profile.row_count for profile in profiles]
    max_rows = max(row_counts, default=0)
    median_rows = median(row_counts) if row_counts else 0.0

    for profile in profiles:
        fact_score, dimension_score, fact_evidence, dimension_evidence = _role_scores(
            profile, max_rows, median_rows
        )
        if fact_score >= 0.50 and fact_score >= dimension_score + 0.10:
            profile.role_guess = "fact"
            profile.role_confidence = min(1.0, 0.55 + fact_score - dimension_score)
            profile.role_evidence = tuple(fact_evidence)
        elif dimension_score >= 0.40 and dimension_score >= fact_score + 0.05:
            profile.role_guess = "dimension"
            profile.role_confidence = min(
                1.0, 0.55 + dimension_score - fact_score
            )
            profile.role_evidence = tuple(dimension_evidence)
        else:
            profile.role_guess = "unknown"
            profile.role_confidence = max(
                0.20, 0.50 - abs(fact_score - dimension_score)
            )
            profile.role_evidence = tuple(
                (fact_evidence + dimension_evidence)[:4]
            )
        profile.role_score_breakdown = {
            "fact_score": round(fact_score, 3),
            "dimension_score": round(dimension_score, 3),
        }


def _coerce_tables(tables: Any) -> list[LoadedTable]:
    if isinstance(tables, Mapping):
        loaded = []
        for name, frame in tables.items():
            if not isinstance(frame, pd.DataFrame):
                raise RelationshipDiscoveryError(
                    "A table mapping must contain pandas DataFrame values."
                )
            loaded.append(
                LoadedTable(
                    table_id=str(name),
                    table_name=str(name),
                    source_name=f"{name}<dataframe>",
                    frame=frame,
                )
            )
        return loaded

    if isinstance(tables, Sequence) and not isinstance(tables, (str, bytes)):
        loaded = list(tables)
        if not all(isinstance(table, LoadedTable) for table in loaded):
            raise RelationshipDiscoveryError(
                "A table sequence must contain LoadedTable objects."
            )
        return loaded

    raise RelationshipDiscoveryError(
        "Pass a name-to-DataFrame mapping or a sequence of LoadedTable objects."
    )


def profile_tables(
    tables: Any,
    config: DiscoveryConfig | None = None,
) -> tuple[TableProfile, ...]:
    """Profile tables and columns without modifying the source DataFrames."""
    config = config or DiscoveryConfig()
    loaded = _coerce_tables(tables)
    profiles: list[TableProfile] = []

    for table in loaded:
        _validate_table(table)
        entity_role, entity_confidence, entity_evidence = infer_table_entity_role(
            table
        )
        columns = tuple(
            _profile_column(
                table,
                column_name,
                position,
                config,
                entity_role,
            )
            for position, column_name in enumerate(table.frame.columns)
        )
        profiles.append(
            TableProfile(
                table_id=table.table_id,
                table_name=table.table_name,
                source_name=table.source_name,
                sheet_name=table.sheet_name,
                row_count=int(len(table.frame)),
                column_count=int(len(table.frame.columns)),
                columns=columns,
                encoding=table.encoding,
                entity_role=entity_role,
                entity_role_confidence=entity_confidence,
                entity_role_evidence=entity_evidence,
            )
        )

    _assign_table_roles(profiles)
    return tuple(profiles)


def _type_match(
    left: ColumnProfile,
    right: ColumnProfile,
    name_score: float,
) -> _TypeMatch:
    left_type = left.semantic_type
    right_type = right.semantic_type
    if "empty" in {left_type, right_type} or "boolean" in {left_type, right_type}:
        return _TypeMatch(False, 0.0, "text", "empty/boolean columns are not join keys")

    if (left.is_measure_like and not left.is_key_like) or (
        right.is_measure_like and not right.is_key_like
    ):
        return _TypeMatch(False, 0.0, "numeric", "measure columns are not candidate keys")

    if left_type == "date" or right_type == "date":
        if left_type == right_type == "date":
            return _TypeMatch(True, 15.0, "date", "both columns parse as dates")
        return _TypeMatch(False, 0.0, "date", "date and non-date types are incompatible")

    if left.numeric_parse_rate >= 0.90 and right.numeric_parse_rate >= 0.90:
        if left.is_key_like or right.is_key_like or name_score >= 20.0:
            leading_zero_identifier = any(
                re.match(r"^[+-]?0\d+$", sample.strip())
                for column in (left, right)
                for sample in column.sample_values
            )
            if leading_zero_identifier:
                return _TypeMatch(
                    True,
                    12.0,
                    "text",
                    "numeric-looking identifiers preserve leading zeros",
                )
            score = 15.0 if left_type == right_type else 12.0
            return _TypeMatch(True, score, "numeric", "both columns are numeric-compatible")

    text_types = {"identifier", "categorical_code", "text"}
    if left_type in text_types and right_type in text_types:
        score = 14.0 if left_type == right_type else 12.0
        return _TypeMatch(True, score, "text", "both columns are text/code-compatible")

    if left_type == right_type == "numeric" and name_score >= 20.0:
        return _TypeMatch(True, 12.0, "numeric", "matching numeric columns")

    return _TypeMatch(False, 0.0, "text", "column data types are incompatible")


def _orient_table_pair(
    first: TableProfile,
    second: TableProfile,
) -> tuple[TableProfile, TableProfile]:
    if first.role_guess == "fact" and second.role_guess != "fact":
        return first, second
    if second.role_guess == "fact" and first.role_guess != "fact":
        return second, first
    if first.role_guess == "dimension" and second.role_guess == "unknown":
        return second, first
    if second.role_guess == "dimension" and first.role_guess == "unknown":
        return first, second
    if first.row_count >= second.row_count:
        return first, second
    return second, first


def _prefilter_column_pairs(
    left: TableProfile,
    right: TableProfile,
    config: DiscoveryConfig,
) -> list[tuple[ColumnProfile, ColumnProfile, NameMatch, _TypeMatch]]:
    pairs = []
    for left_column in left.columns:
        for right_column in right.columns:
            name_match = compare_column_names(
                left_column.column_name, right_column.column_name
            )
            if name_match.score < config.minimum_name_score:
                continue

            type_match = _type_match(left_column, right_column, name_match.score)
            if not type_match.compatible:
                continue

            semantic_join_signal = set(left_column.semantic_tokens).intersection(
                {"date", "currency", "customer", "product", "store", "order", "line_item"}
            ) or set(right_column.semantic_tokens).intersection(
                {"date", "currency", "customer", "product", "store", "order", "line_item"}
            )
            if not (
                left_column.is_key_like
                or right_column.is_key_like
                or semantic_join_signal
                or name_match.score == 25.0
            ):
                continue

            pairs.append((left_column, right_column, name_match, type_match))

    pairs.sort(
        key=lambda pair: (
            pair[2].score + pair[3].score,
            max(pair[0].unique_rate, pair[1].unique_rate),
        ),
        reverse=True,
    )
    return pairs[: config.maximum_prefiltered_pairs_per_table_pair]


def _fallback_eligible_columns(
    profile: TableProfile,
    config: DiscoveryConfig,
    *,
    right_side: bool,
) -> list[ColumnProfile]:
    eligible = []
    excluded_types = {"empty", "boolean", "date", "numeric_measure"}
    for column in profile.columns:
        if column.semantic_type in excluded_types or column.is_measure_like:
            continue
        if column.non_null_count < config.fallback_minimum_non_null_count:
            continue
        if column.unique_count < config.fallback_minimum_non_null_count:
            continue
        if right_side and column.unique_rate < config.fallback_minimum_right_uniqueness:
            continue
        name_candidate = "name" in column.semantic_tokens and column.unique_rate >= 0.98
        if not (column.is_key_like or name_candidate):
            continue
        eligible.append(column)
    eligible.sort(
        key=lambda column: (
            column.is_key_like,
            column.unique_rate,
            column.non_null_count,
            column.column_name,
        ),
        reverse=True,
    )
    return eligible[: config.fallback_maximum_columns_per_table]


def _fallback_type_match(
    left: ColumnProfile,
    right: ColumnProfile,
    name_score: float,
) -> _TypeMatch:
    match = _type_match(left, right, name_score)
    if match.compatible:
        return match
    if (
        left.numeric_parse_rate >= 0.90
        and right.numeric_parse_rate >= 0.90
        and (left.is_key_like or right.is_key_like)
    ):
        return _TypeMatch(
            True,
            10.0,
            "numeric",
            "both columns contain numeric-compatible identifier values",
        )
    return match


def _entity_role_consistent(left: ColumnProfile, right: ColumnProfile) -> bool:
    left_direct = any(
        evidence.startswith("column signal")
        for evidence in left.entity_role_evidence
    )
    right_direct = any(
        evidence.startswith("column signal")
        for evidence in right.entity_role_evidence
    )
    if not (left_direct and right_direct):
        return True
    return left.entity_role == right.entity_role


def _sample_match_rate(
    left_frame: pd.DataFrame,
    right_frame: pd.DataFrame,
    left_column: str,
    right_column: str,
    comparison_kind: str,
    sample_size: int,
) -> float:
    left_values = canonicalize_key_series(
        left_frame[left_column].head(sample_size), comparison_kind
    )
    right_values = canonicalize_key_series(
        right_frame[right_column].head(sample_size), comparison_kind
    ).dropna()
    valid_left = left_values.dropna()
    if valid_left.empty or right_values.empty:
        return 0.0
    return float(valid_left.isin(set(right_values.unique())).mean())


def _fallback_column_pairs(
    left_profile: TableProfile,
    right_profile: TableProfile,
    left_frame: pd.DataFrame,
    right_frame: pd.DataFrame,
    regular_candidates: list[RelationshipCandidate],
    config: DiscoveryConfig,
    diagnostics: dict[str, Any],
) -> list[tuple[ColumnProfile, ColumnProfile, NameMatch, _TypeMatch]]:
    used_left = {
        candidate.left_columns[0]
        for candidate in regular_candidates
        if len(candidate.left_columns) == 1 and not candidate.blocked
    }
    used_right = {
        candidate.right_columns[0]
        for candidate in regular_candidates
        if len(candidate.right_columns) == 1 and not candidate.blocked
    }
    ranked = []
    left_columns = _fallback_eligible_columns(
        left_profile, config, right_side=False
    )
    right_columns = _fallback_eligible_columns(
        right_profile, config, right_side=True
    )
    for left_column in left_columns:
        for right_column in right_columns:
            diagnostics["fallback_pairs_screened"] += 1
            if (
                left_column.column_name in used_left
                or right_column.column_name in used_right
            ):
                continue
            name_match = compare_column_names(
                left_column.column_name, right_column.column_name
            )
            if name_match.score >= config.minimum_name_score:
                continue
            if not _entity_role_consistent(left_column, right_column):
                continue
            type_match = _fallback_type_match(
                left_column, right_column, name_match.score
            )
            if not type_match.compatible:
                continue
            sample_rate = _sample_match_rate(
                left_frame,
                right_frame,
                left_column.column_name,
                right_column.column_name,
                type_match.comparison_kind,
                config.fallback_sample_size,
            )
            diagnostics["fallback_sample_comparisons"] += 1
            if sample_rate < config.fallback_minimum_match_rate:
                continue
            ranked.append(
                (
                    sample_rate,
                    right_column.unique_rate,
                    type_match.score,
                    left_column,
                    right_column,
                    name_match,
                    type_match,
                )
            )
    ranked.sort(
        key=lambda item: (item[0], item[1], item[2], item[3].column_name, item[4].column_name),
        reverse=True,
    )
    return [
        (left, right, name, type_match)
        for _, _, _, left, right, name, type_match in ranked[
            : config.fallback_maximum_pairs_per_table_pair
        ]
    ]


def _role_fit_score(left_role: str, right_role: str, right_is_smaller: bool) -> float:
    if left_role == "fact" and right_role == "dimension":
        return 10.0
    if left_role == "fact" and right_role == "unknown":
        return 7.0
    if left_role == "unknown" and right_role == "dimension":
        return 7.0
    if left_role == "fact" and right_role == "fact":
        return 0.0
    return 5.0 if right_is_smaller else 3.0


def _score_candidate(
    name_matches: tuple[NameMatch, ...],
    type_matches: tuple[_TypeMatch, ...],
    safety: JoinSafetyAssessment,
    left_profile: TableProfile,
    right_profile: TableProfile,
    fallback: bool = False,
) -> tuple[float, dict[str, float], str]:
    name_score = sum(match.score for match in name_matches) / len(name_matches)
    type_score = sum(match.score for match in type_matches) / len(type_matches)
    value_score = 30.0 * safety.match_rate
    uniqueness_score = 20.0 * safety.right_key_uniqueness
    role_score = _role_fit_score(
        left_profile.role_guess,
        right_profile.role_guess,
        right_profile.row_count <= left_profile.row_count,
    )

    penalty = 0.0
    if safety.fact_to_fact_risk:
        penalty -= 20.0
    if safety.right_null_key_count:
        penalty -= 5.0
    if safety.many_to_many_risk:
        penalty -= 15.0
    elif safety.right_duplicate_key_count:
        penalty -= 10.0
    if safety.row_inflation:
        penalty -= 10.0
    penalty = max(penalty, -30.0)

    if fallback:
        breakdown = {
            "name_similarity": round(name_score, 2),
            "value_overlap": round(value_score, 2),
            "right_key_uniqueness": round(uniqueness_score, 2),
            "type_compatibility": round(type_score, 2),
            "row_growth_risk": -10.0 if safety.row_inflation else 0.0,
            "entity_role_consistency": round(role_score, 2),
            "other_safety_penalty": round(
                penalty + (10.0 if safety.row_inflation else 0.0), 2
            ),
        }
    else:
        breakdown = {
            "name_alignment": round(name_score, 2),
            "type_compatibility": round(type_score, 2),
            "value_overlap": round(value_score, 2),
            "right_key_uniqueness": round(uniqueness_score, 2),
            "table_role_fit": round(role_score, 2),
            "safety_penalty": round(penalty, 2),
        }
    score = round(max(0.0, min(100.0, sum(breakdown.values()))), 2)

    name_reasons = "; ".join(match.reason for match in name_matches)
    type_reasons = "; ".join(match.reason for match in type_matches)
    explanation = (
        f"Name alignment {name_score:.1f}/25 ({name_reasons}); "
        f"type compatibility {type_score:.1f}/15 ({type_reasons}); "
        f"left-row match {safety.match_rate:.1%} contributes {value_score:.1f}/30; "
        f"right-key uniqueness {safety.right_key_uniqueness:.1%} contributes "
        f"{uniqueness_score:.1f}/20; table-role fit contributes {role_score:.1f}/10"
    )
    if penalty:
        explanation += f"; safety risks contribute {penalty:.1f} points"
    if fallback:
        explanation += (
            "; column-name similarity is weak, but the actual values overlap "
            "strongly; confirm whether they represent the same business identifier"
        )
    explanation += "."
    return score, breakdown, explanation


def _make_candidate(
    left_profile: TableProfile,
    right_profile: TableProfile,
    left_columns: tuple[ColumnProfile, ...],
    right_columns: tuple[ColumnProfile, ...],
    name_matches: tuple[NameMatch, ...],
    type_matches: tuple[_TypeMatch, ...],
    safety: JoinSafetyAssessment,
    fallback: bool = False,
    fallback_maximum_confidence: float = 79.99,
) -> RelationshipCandidate:
    score, breakdown, explanation = _score_candidate(
        name_matches, type_matches, safety, left_profile, right_profile, fallback
    )
    if fallback:
        score = min(score, fallback_maximum_confidence)
    confidence_level = "high" if score >= 80 else "medium" if score >= 60 else "low"
    left_names = tuple(column.column_name for column in left_columns)
    right_names = tuple(column.column_name for column in right_columns)
    candidate_id = (
        f"{left_profile.table_id}[{'+'.join(left_names)}]->"
        f"{right_profile.table_id}[{'+'.join(right_names)}]"
    )
    return RelationshipCandidate(
        candidate_id=candidate_id,
        left_table_id=left_profile.table_id,
        left_table=left_profile.table_name,
        left_columns=left_names,
        right_table_id=right_profile.table_id,
        right_table=right_profile.table_name,
        right_columns=right_names,
        relationship_kind="composite" if len(left_names) > 1 else "single_column",
        comparison_kinds=tuple(match.comparison_kind for match in type_matches),
        expected_join_type=safety.expected_join_type,
        confidence_score=score,
        confidence_level=confidence_level,
        score_breakdown=breakdown,
        explanation=explanation,
        match_rate=safety.match_rate,
        distinct_overlap_rate=safety.distinct_overlap_rate,
        left_key_uniqueness=safety.left_key_uniqueness,
        right_key_uniqueness=safety.right_key_uniqueness,
        left_null_key_count=safety.left_null_key_count,
        right_null_key_count=safety.right_null_key_count,
        right_duplicate_key_count=safety.right_duplicate_key_count,
        right_duplicate_row_count=safety.right_duplicate_row_count,
        before_row_count=safety.before_row_count,
        after_row_count=safety.after_row_count,
        row_count_change=safety.row_count_change,
        many_to_many_risk=safety.many_to_many_risk,
        row_inflation=safety.row_inflation,
        fact_to_fact_risk=safety.fact_to_fact_risk,
        blocked=safety.blocked,
        block_reasons=safety.block_reasons,
        risk_flags=(
            safety.risk_flags + (("weak_name_high_value_overlap",) if fallback else ())
        ),
    )


def evaluate_relationship_candidate(
    discovery_result: RelationshipDiscoveryResult,
    left_table_id: str,
    left_columns: Sequence[str],
    right_table_id: str,
    right_columns: Sequence[str],
) -> RelationshipCandidate:
    """Re-score one user-selected mapping with the same Stage A safety rules."""
    left_names = tuple(left_columns)
    right_names = tuple(right_columns)
    if len(left_names) not in {1, 2} or len(right_names) != len(left_names):
        raise RelationshipDiscoveryError(
            "A relationship must use one column or two aligned composite-key columns."
        )
    if len(set(left_names)) != len(left_names) or len(set(right_names)) != len(
        right_names
    ):
        raise RelationshipDiscoveryError(
            "Composite relationship columns must be distinct on each table."
        )
    if left_table_id == right_table_id:
        raise RelationshipDiscoveryError("A relationship cannot join a table to itself.")

    profile_by_id = {
        profile.table_id: profile for profile in discovery_result.table_profiles
    }
    try:
        left_profile = profile_by_id[left_table_id]
        right_profile = profile_by_id[right_table_id]
    except KeyError as error:
        raise RelationshipDiscoveryError(
            f"Unknown table in edited relationship: {error.args[0]!r}."
        ) from error

    left_profiles = tuple(left_profile.get_column(name) for name in left_names)
    right_profiles = tuple(right_profile.get_column(name) for name in right_names)
    name_matches = tuple(
        compare_column_names(left.column_name, right.column_name)
        for left, right in zip(left_profiles, right_profiles)
    )
    type_matches = tuple(
        _type_match(left, right, name.score)
        for left, right, name in zip(left_profiles, right_profiles, name_matches)
    )
    incompatible = [match.reason for match in type_matches if not match.compatible]
    if incompatible:
        raise RelationshipDiscoveryError(
            "Edited relationship has incompatible key types: " + "; ".join(incompatible)
        )

    left_table = discovery_result.get_table(left_table_id)
    right_table = discovery_result.get_table(right_table_id)
    safety = evaluate_join_safety(
        left_table.frame,
        right_table.frame,
        left_names,
        right_names,
        tuple(match.comparison_kind for match in type_matches),
        left_profile.role_guess,
        right_profile.role_guess,
        left_profile.entity_role,
        right_profile.entity_role,
    )
    return _make_candidate(
        left_profile,
        right_profile,
        left_profiles,
        right_profiles,
        name_matches,
        type_matches,
        safety,
    )


def _discover_table_pair(
    left_profile: TableProfile,
    right_profile: TableProfile,
    left_table: LoadedTable,
    right_table: LoadedTable,
    config: DiscoveryConfig,
    diagnostics: dict[str, Any],
) -> list[RelationshipCandidate]:
    prefiltered = _prefilter_column_pairs(left_profile, right_profile, config)
    diagnostics["prefiltered_column_pairs"] += len(prefiltered)
    evidence_rows: list[_PairEvidence] = []
    candidates: list[RelationshipCandidate] = []

    for left_column, right_column, name_match, type_match in prefiltered:
        diagnostics["value_overlap_comparisons"] += 1
        safety = evaluate_join_safety(
            left_table.frame,
            right_table.frame,
            (left_column.column_name,),
            (right_column.column_name,),
            (type_match.comparison_kind,),
            left_profile.role_guess,
            right_profile.role_guess,
            left_profile.entity_role,
            right_profile.entity_role,
        )
        diagnostics["format_warnings"].extend(safety.format_warnings)
        if safety.match_rate < config.minimum_match_rate:
            continue

        evidence = _PairEvidence(
            left_column=left_column,
            right_column=right_column,
            name_match=name_match,
            type_match=type_match,
            safety=safety,
        )
        evidence_rows.append(evidence)
        candidate = _make_candidate(
            left_profile,
            right_profile,
            (left_column,),
            (right_column,),
            (name_match,),
            (type_match,),
            safety,
        )
        if candidate.confidence_score >= config.minimum_candidate_score:
            candidates.append(candidate)

    composite_components = sorted(
        evidence_rows,
        key=lambda evidence: (
            evidence.name_match.score + evidence.type_match.score,
            evidence.safety.match_rate,
        ),
        reverse=True,
    )[: config.maximum_composite_components]

    for first, second in combinations(composite_components, 2):
        if first.left_column.column_name == second.left_column.column_name:
            continue
        if first.right_column.column_name == second.right_column.column_name:
            continue

        maximum_single_uniqueness = max(
            first.safety.right_key_uniqueness,
            second.safety.right_key_uniqueness,
        )
        diagnostics["composite_comparisons"] += 1
        left_columns = (first.left_column, second.left_column)
        right_columns = (first.right_column, second.right_column)
        type_matches = (first.type_match, second.type_match)
        safety = evaluate_join_safety(
            left_table.frame,
            right_table.frame,
            tuple(column.column_name for column in left_columns),
            tuple(column.column_name for column in right_columns),
            tuple(match.comparison_kind for match in type_matches),
            left_profile.role_guess,
            right_profile.role_guess,
            left_profile.entity_role,
            right_profile.entity_role,
        )
        diagnostics["format_warnings"].extend(safety.format_warnings)
        if safety.match_rate < config.minimum_match_rate:
            continue
        if safety.right_key_uniqueness < config.composite_minimum_right_uniqueness:
            continue
        if safety.right_key_uniqueness <= maximum_single_uniqueness + 0.01:
            continue

        candidate = _make_candidate(
            left_profile,
            right_profile,
            left_columns,
            right_columns,
            (first.name_match, second.name_match),
            type_matches,
            safety,
        )
        if candidate.confidence_score >= config.minimum_candidate_score:
            candidates.append(candidate)

    fallback_pairs = _fallback_column_pairs(
        left_profile,
        right_profile,
        left_table.frame,
        right_table.frame,
        candidates,
        config,
        diagnostics,
    )
    for left_column, right_column, name_match, type_match in fallback_pairs:
        diagnostics["fallback_full_comparisons"] += 1
        safety = evaluate_join_safety(
            left_table.frame,
            right_table.frame,
            (left_column.column_name,),
            (right_column.column_name,),
            (type_match.comparison_kind,),
            left_profile.role_guess,
            right_profile.role_guess,
            left_profile.entity_role,
            right_profile.entity_role,
        )
        diagnostics["format_warnings"].extend(safety.format_warnings)
        if safety.match_rate < config.fallback_minimum_match_rate:
            continue
        if safety.right_key_uniqueness < config.fallback_minimum_right_uniqueness:
            continue
        if safety.blocked or safety.fact_to_fact_risk or safety.row_inflation:
            continue
        candidate = _make_candidate(
            left_profile,
            right_profile,
            (left_column,),
            (right_column,),
            (name_match,),
            (type_match,),
            safety,
            fallback=True,
            fallback_maximum_confidence=config.fallback_maximum_confidence,
        )
        if candidate.confidence_score >= config.minimum_candidate_score:
            candidates.append(candidate)
            diagnostics["fallback_candidate_count"] += 1

    return candidates


def discover_relationships(
    tables: Any,
    config: DiscoveryConfig | None = None,
) -> RelationshipDiscoveryResult:
    """Profile tables and return pending relationship suggestions; never merge data."""
    config = config or DiscoveryConfig()
    loaded = _coerce_tables(tables)
    profiles = list(profile_tables(loaded, config))
    table_by_id = {table.table_id: table for table in loaded}
    diagnostics: dict[str, Any] = {
        "table_count": len(loaded),
        "table_pairs": 0,
        "column_pairs_screened": 0,
        "prefiltered_column_pairs": 0,
        "value_overlap_comparisons": 0,
        "composite_comparisons": 0,
        "fallback_pairs_screened": 0,
        "fallback_sample_comparisons": 0,
        "fallback_full_comparisons": 0,
        "fallback_candidate_count": 0,
        "format_warnings": [],
        "candidate_count": 0,
        "blocked_candidate_count": 0,
        "merge_executed": False,
    }
    candidates: list[RelationshipCandidate] = []

    for first, second in combinations(profiles, 2):
        diagnostics["table_pairs"] += 1
        diagnostics["column_pairs_screened"] += len(first.columns) * len(second.columns)
        left_profile, right_profile = _orient_table_pair(first, second)
        candidates.extend(
            _discover_table_pair(
                left_profile,
                right_profile,
                table_by_id[left_profile.table_id],
                table_by_id[right_profile.table_id],
                config,
                diagnostics,
            )
        )

    deduplicated = {candidate.candidate_id: candidate for candidate in candidates}
    ordered = sorted(
        deduplicated.values(),
        key=lambda candidate: (
            candidate.confidence_score,
            candidate.relationship_kind == "composite",
            candidate.match_rate,
        ),
        reverse=True,
    )
    diagnostics["candidate_count"] = len(ordered)
    diagnostics["blocked_candidate_count"] = sum(
        candidate.blocked for candidate in ordered
    )

    return RelationshipDiscoveryResult(
        tables=tuple(loaded),
        table_profiles=tuple(profiles),
        relationships=tuple(ordered),
        diagnostics=diagnostics,
    )


def discover_relationships_from_sources(
    sources: Any,
    config: DiscoveryConfig | None = None,
) -> RelationshipDiscoveryResult:
    """Read CSV/xlsx sources and run Stage A discovery."""
    return discover_relationships(read_tabular_sources(sources), config=config)
