from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import re

import pandas as pd
from pandas.api.types import is_bool_dtype, is_datetime64_any_dtype, is_numeric_dtype

from analysis import REQUIRED_COLUMNS
from relationship_aliases import normalize_column_name
from standard_field_models import (
    FieldConversionDiagnostic,
    FieldAvailability,
    FieldMappingRecommendation,
    StandardFieldMappingPlan,
    StandardFieldSelection,
    StandardMappingResult,
)


REQUIRED_TRANSACTION_FIELDS = (
    "order_id",
    "date",
    "product_id",
    "unit_price",
    "quantity",
)
OPTIONAL_ANALYSIS_FIELDS = (
    "customer_id",
    "returned",
    "customer_name",
    "product_name",
    "category",
    "store_id",
    "store_name",
)
BUSINESS_ASSUMPTION_FIELDS = ("discount_rate",)

# Backward-compatible public aliases used by existing callers and tests.
REQUIRED_STANDARD_FIELDS = REQUIRED_TRANSACTION_FIELDS
OPTIONAL_STANDARD_FIELDS = OPTIONAL_ANALYSIS_FIELDS
STANDARD_FIELDS = (
    REQUIRED_TRANSACTION_FIELDS
    + BUSINESS_ASSUMPTION_FIELDS
    + OPTIONAL_ANALYSIS_FIELDS
)
PIPELINE_REQUIRED_OUTPUT_FIELDS = tuple(
    field for field in REQUIRED_COLUMNS if field != "customer_id"
)
RETURN_NOT_PROVIDED_MESSAGE = (
    "Return data was not provided. Return analysis was skipped."
)
RETURN_NOT_APPLICABLE_MESSAGE = "Return analysis: Not applicable."
STORE_NOT_PROVIDED_MESSAGE = (
    "Store data was not provided. Store analysis was skipped."
)
STORE_PARTIALLY_PROVIDED_MESSAGE = (
    "Store data was partially provided. Some transactions could not be assigned "
    "to a store."
)
STORE_NAME_GROUPING_NOTE = (
    "Store analysis is grouped by store name because a stable store ID was not "
    "provided."
)
ENTITY_STANDARD_FIELDS = {
    "customer_id": "customer",
    "customer_name": "customer",
    "product_id": "product",
    "product_name": "product",
    "category": "category",
    "store_id": "store",
    "store_name": "store",
}
KNOWN_ENTITY_ROLES = {
    "customer",
    "shipper",
    "supplier",
    "employee",
    "product",
    "category",
    "store",
    "order_header",
    "order_line",
}
SEVERE_CONVERSION_FAILURE_RATE = 0.05
RECOMMENDATION_THRESHOLD = 50.0
PROFILE_SAMPLE_SIZE = 200

TARGET_TYPES = {
    "order_id": "identifier",
    "date": "date",
    "customer_id": "identifier",
    "product_id": "identifier",
    "unit_price": "money",
    "quantity": "number",
    "discount_rate": "rate",
    "returned": "boolean",
    "customer_name": "text",
    "product_name": "text",
    "category": "text",
    "store_id": "identifier",
    "store_name": "text",
}

# Aliases are deliberately field-specific. Generic words receive less weight than
# business-qualified names so that Order Date beats Delivery Date or a rate-table Date.
FIELD_ALIASES = {
    "order_id": {
        "order id": 60,
        "order number": 60,
        "order no": 60,
        "transaction id": 58,
        "invoice id": 56,
        "订单编号": 60,
        "订单号": 60,
        "单号": 54,
    },
    "date": {
        "order date": 60,
        "transaction date": 58,
        "sales date": 58,
        "purchase date": 56,
        "date": 44,
        "订单日期": 60,
        "交易日期": 58,
        "日期": 44,
    },
    "customer_id": {
        "customer id": 60,
        "customer key": 60,
        "customer code": 58,
        "client id": 58,
        "buyer id": 56,
        "客户编号": 60,
        "客户id": 60,
        "客户编码": 58,
    },
    "product_id": {
        "product id": 60,
        "product key": 60,
        "product code": 58,
        "sku": 56,
        "sku id": 58,
        "产品编号": 60,
        "商品编号": 60,
        "产品id": 60,
    },
    "unit_price": {
        "unit price": 60,
        "unit price usd": 60,
        "sales unit price": 60,
        "sales price": 56,
        "price": 44,
        "单价": 60,
        "销售单价": 60,
        "售价": 56,
    },
    "quantity": {
        "quantity": 60,
        "qty": 60,
        "units": 52,
        "order quantity": 60,
        "数量": 60,
        "件数": 56,
    },
    "discount_rate": {
        "discount rate": 60,
        "discount percent": 60,
        "discount percentage": 60,
        "discount": 52,
        "折扣率": 60,
        "折扣": 52,
    },
    "returned": {
        "returned": 60,
        "is returned": 60,
        "return flag": 60,
        "returned flag": 60,
        "return status": 56,
        "是否退货": 60,
        "退货标记": 60,
        "退货状态": 56,
    },
    "customer_name": {
        "customer name": 60,
        "client name": 58,
        "buyer name": 56,
        "name": 34,
        "客户名称": 60,
        "客户姓名": 60,
        "姓名": 42,
    },
    "product_name": {
        "product name": 60,
        "product detail": 60,
        "product type": 38,
        "item name": 56,
        "sku name": 56,
        "name": 34,
        "产品名称": 60,
        "商品名称": 60,
        "品名": 54,
    },
    "category": {
        "category": 60,
        "product category": 60,
        "item category": 56,
        "类别": 60,
        "分类": 60,
        "品类": 60,
    },
    "store_id": {
        "store id": 60,
        "storeid": 60,
        "store key": 60,
        "shop id": 60,
        "shopid": 60,
        "branch id": 60,
        "branchid": 60,
        "location id": 58,
        "outlet id": 60,
        "门店编号": 60,
        "门店id": 60,
        "店铺编号": 60,
        "分店编号": 60,
    },
    "store_name": {
        "store name": 60,
        "shop name": 60,
        "branch name": 60,
        "store location": 60,
        "shop location": 60,
        "outlet name": 60,
        "location name": 58,
        "门店名称": 60,
        "店铺名称": 60,
        "分店名称": 60,
        "门店位置": 60,
    },
}

FIELD_CONTEXTS = {
    "order_id": ("order", "transaction", "invoice", "订单", "交易"),
    "date": ("order", "transaction", "sales", "purchase", "订单", "交易"),
    "customer_id": ("customer", "client", "buyer", "客户", "顾客"),
    "product_id": ("product", "sku", "item", "产品", "商品"),
    "unit_price": ("unit", "sales", "product", "单价", "售价"),
    "quantity": ("quantity", "qty", "units", "数量", "件数"),
    "discount_rate": ("discount", "折扣"),
    "returned": ("return", "returned", "退货"),
    "customer_name": ("customer", "client", "buyer", "客户", "顾客"),
    "product_name": ("product", "sku", "item", "产品", "商品"),
    "category": ("product", "category", "类别", "分类", "品类"),
    "store_id": ("store", "shop", "branch", "outlet", "门店", "店铺", "分店"),
    "store_name": ("store", "shop", "branch", "outlet", "location", "门店", "店铺", "分店"),
}

TRUE_VALUES = {
    "true",
    "yes",
    "y",
    "1",
    "returned",
    "return",
    "是",
    "已退货",
    "退货",
}
FALSE_VALUES = {
    "false",
    "no",
    "n",
    "0",
    "not_returned",
    "not returned",
    "否",
    "未退货",
}

ALLOWED_STRATEGIES = {
    "order_id": {"source"},
    "date": {"source"},
    "customer_id": {"source", "not_provided", "omit"},
    "product_id": {"source"},
    "unit_price": {"source"},
    "quantity": {"source"},
    "discount_rate": {"source", "default_zero"},
    "returned": {"source", "not_provided", "not_applicable"},
    "customer_name": {"source", "omit"},
    "product_name": {"source", "omit"},
    "category": {"source", "omit"},
    "store_id": {"source", "omit"},
    "store_name": {"source", "omit"},
}


class StandardFieldMappingError(ValueError):
    def __init__(self, errors: Sequence[str]):
        self.errors = tuple(errors)
        super().__init__(" ".join(self.errors))


def build_source_entity_role_map(
    discovery_result,
    fact_table_id: str,
) -> dict[str, str]:
    """Map merged output column names to discovery entity-role metadata."""
    if discovery_result is None:
        return {}
    roles = {}
    for profile in discovery_result.table_profiles:
        for column in profile.columns:
            output_column = (
                column.column_name
                if profile.table_id == fact_table_id
                else f"{profile.table_id}.{column.column_name}"
            )
            roles[output_column] = column.entity_role
    return roles


@dataclass(frozen=True)
class _ColumnEvidence:
    numeric_rate: float
    date_rate: float
    boolean_rate: float
    text_rate: float
    sample_count: int


def _present_mask(series: pd.Series) -> pd.Series:
    as_text = series.astype("string").str.strip()
    return series.notna() & as_text.ne("")


def _clean_numeric_series(series: pd.Series, percentage: bool = False) -> pd.Series:
    text = series.astype("string").str.strip()
    negative_parentheses = text.str.match(r"^\(.*\)$", na=False)
    percent_mask = text.str.contains("%", regex=False, na=False)
    directly_converted = pd.to_numeric(text, errors="coerce")
    cleaned = text.str.replace(",", "", regex=False)
    cleaned = cleaned.str.replace(r"^\((.*)\)$", r"\1", regex=True)
    cleaned = cleaned.str.replace(r"[^0-9+\-.]", "", regex=True)
    converted = directly_converted.fillna(pd.to_numeric(cleaned, errors="coerce"))
    converted = converted.mask(negative_parentheses, -converted.abs())
    if percentage:
        converted = converted.mask(percent_mask, converted / 100.0)
    return converted.astype("Float64")


def _to_datetime_series(series: pd.Series) -> pd.Series:
    try:
        return pd.to_datetime(series, errors="coerce", format="mixed")
    except (TypeError, ValueError):
        return pd.to_datetime(series, errors="coerce")


def _to_boolean_series(series: pd.Series) -> pd.Series:
    result = pd.Series(pd.NA, index=series.index, dtype="boolean")
    normalized = series.astype("string").str.strip().str.casefold()
    result.loc[normalized.isin(TRUE_VALUES)] = True
    result.loc[normalized.isin(FALSE_VALUES)] = False
    if is_bool_dtype(series.dtype):
        result.loc[series.eq(True)] = True
        result.loc[series.eq(False)] = False
    return result


def _looks_date_like(series: pd.Series) -> pd.Series:
    if is_datetime64_any_dtype(series.dtype):
        return pd.Series(True, index=series.index)
    if is_numeric_dtype(series.dtype):
        return pd.Series(False, index=series.index)
    text = series.astype("string").str.strip()
    return text.str.contains(
        r"(?:\d{4}[-/.年]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|"
        r"jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",
        case=False,
        regex=True,
        na=False,
    )


def _profile_column(series: pd.Series) -> _ColumnEvidence:
    sample = series.loc[_present_mask(series)].head(PROFILE_SAMPLE_SIZE)
    count = len(sample)
    if count == 0:
        return _ColumnEvidence(0.0, 0.0, 0.0, 0.0, 0)

    numeric = _clean_numeric_series(sample)
    boolean = _to_boolean_series(sample)
    date_like = _looks_date_like(sample)
    date_values = _to_datetime_series(sample.where(date_like))
    text_rate = float(sample.astype("string").notna().mean())
    return _ColumnEvidence(
        numeric_rate=float(numeric.notna().mean()),
        date_rate=float(date_values.notna().mean()),
        boolean_rate=float(boolean.notna().mean()),
        text_rate=text_rate,
        sample_count=count,
    )


def _normalized_local_name(column: object) -> str:
    local_name = str(column).rsplit(".", 1)[-1]
    return normalize_column_name(local_name)


def _contains_phrase(normalized: str, phrase: str) -> bool:
    normalized_phrase = normalize_column_name(phrase)
    if re.search(r"[\u4e00-\u9fff]", normalized_phrase):
        return normalized_phrase.replace(" ", "") in normalized.replace(" ", "")
    return bool(
        re.search(rf"(?:^|\s){re.escape(normalized_phrase)}(?:$|\s)", normalized)
    )


def _source_entity_role(
    source_column: object,
    source_entity_roles: Mapping[str, str] | None = None,
) -> str:
    source_name = str(source_column)
    if source_entity_roles and source_name in source_entity_roles:
        return source_entity_roles[source_name]

    normalized = normalize_column_name(source_name)
    role_aliases = (
        (
            "shipper",
            (
                "shipper",
                "shippers",
                "shipping",
                "carrier",
                "carriers",
                "freight",
                "ship via",
            ),
        ),
        ("supplier", ("supplier", "suppliers", "vendor", "vendors")),
        (
            "employee",
            ("employee", "employees", "salesperson", "salespeople", "sales person"),
        ),
        (
            "customer",
            ("customer", "customers", "client", "clients", "buyer", "buyers"),
        ),
        ("category", ("category", "categories", "subcategory")),
        ("product", ("product", "products", "sku", "item", "items")),
        ("store", ("store", "stores", "shop", "branch", "outlet")),
    )
    for role, aliases in role_aliases:
        if any(_contains_phrase(normalized, alias) for alias in aliases):
            return role
    return "unknown"


def _identifier_display_source(source_column: object) -> bool:
    local = _normalized_local_name(source_column)
    words = set(local.split())
    return bool(words.intersection({"id", "key", "code", "number", "no"}))


def _format_identifier(value: object) -> object:
    if pd.isna(value):
        return pd.NA
    text = str(value).strip()
    if not text:
        return pd.NA
    numeric = pd.to_numeric(pd.Series([text]), errors="coerce").iloc[0]
    if pd.notna(numeric) and float(numeric).is_integer():
        return str(int(numeric))
    return text


def _entity_display_series(series: pd.Series, label: str) -> pd.Series:
    identifiers = series.map(_format_identifier).astype("string")
    return (label + " " + identifiers).mask(identifiers.isna(), pd.NA)


def _name_alias_score(standard_field: str, column: object) -> float:
    local = _normalized_local_name(column)
    aliases = FIELD_ALIASES[standard_field]
    if local in aliases:
        return float(aliases[local])

    matching = [
        weight
        for alias, weight in aliases.items()
        if _contains_phrase(local, alias)
    ]
    return float(max(matching) - 8) if matching else 0.0


def _context_score(standard_field: str, column: object) -> float:
    normalized = normalize_column_name(column)
    return 10.0 if any(
        _contains_phrase(normalized, context)
        for context in FIELD_CONTEXTS[standard_field]
    ) else 0.0


def _compatibility_rate(target_type: str, evidence: _ColumnEvidence) -> float:
    if target_type in {"money", "number", "rate"}:
        return evidence.numeric_rate
    if target_type == "date":
        return evidence.date_rate
    if target_type == "boolean":
        return evidence.boolean_rate
    return evidence.text_rate


def _score_source_column(
    standard_field: str,
    column: object,
    evidence: _ColumnEvidence,
    source_entity_roles: Mapping[str, str] | None = None,
) -> tuple[float, dict[str, float], str]:
    target_type = TARGET_TYPES[standard_field]
    name_score = _name_alias_score(standard_field, column)
    context_score = _context_score(standard_field, column)
    compatibility = _compatibility_rate(target_type, evidence)
    semantic_score = round(15.0 * compatibility, 2)
    sample_score = round(15.0 * compatibility, 2)
    expected_entity = ENTITY_STANDARD_FIELDS.get(standard_field)
    source_entity = _source_entity_role(column, source_entity_roles)
    entity_role_score = 0.0
    if expected_entity and source_entity == expected_entity:
        entity_role_score = 20.0
    elif expected_entity and source_entity in KNOWN_ENTITY_ROLES:
        entity_role_score = -70.0

    display_identifier_penalty = 0.0
    if standard_field in {
        "customer_name",
        "product_name",
        "category",
        "store_name",
    } and (
        _identifier_display_source(column)
    ):
        display_identifier_penalty = -45.0

    score = (
        name_score
        + context_score
        + semantic_score
        + sample_score
        + entity_role_score
        + display_identifier_penalty
    )
    if standard_field in {"store_id", "store_name"} and name_score == 0:
        score = min(score, RECOMMENDATION_THRESHOLD - 1)
    if target_type in {"money", "number", "rate", "date", "boolean"}:
        if evidence.sample_count and compatibility < 0.5:
            score = min(score, 45.0)
    score = round(max(0.0, min(score, 100.0)), 2)
    breakdown = {
        "column_name_alias": round(name_score, 2),
        "business_context": round(context_score, 2),
        "semantic_type": semantic_score,
        "sample_value_compatibility": sample_score,
        "entity_role_consistency": entity_role_score,
        "identifier_display_penalty": display_identifier_penalty,
    }
    explanation = (
        f"Column name contributes {name_score:.0f} points; business context contributes "
        f"{context_score:.0f}; {compatibility:.0%} of sampled values are compatible "
        f"with target type {target_type}; source entity role is {source_entity}."
    )
    return score, breakdown, explanation


def evaluate_field_mapping_recommendation(
    frame: pd.DataFrame,
    standard_field: str,
    source_column: str,
    source_entity_roles: Mapping[str, str] | None = None,
) -> FieldMappingRecommendation:
    """Re-score a user-selected source using the same explainable rules."""
    if standard_field not in STANDARD_FIELDS:
        raise KeyError(f"Unknown standard field: {standard_field!r}.")
    if source_column not in frame.columns:
        raise KeyError(f"Source column {source_column!r} was not found.")
    evidence = _profile_column(frame[source_column])
    score, breakdown, explanation = _score_source_column(
        standard_field,
        source_column,
        evidence,
        source_entity_roles,
    )
    return FieldMappingRecommendation(
        standard_field=standard_field,
        required=standard_field in REQUIRED_STANDARD_FIELDS,
        target_type=TARGET_TYPES[standard_field],
        recommended_strategy="source",
        recommended_source=source_column,
        confidence_score=score,
        score_breakdown=breakdown,
        explanation=explanation,
    )


def _fallback_recommendation(standard_field: str) -> FieldMappingRecommendation:
    required = standard_field in REQUIRED_STANDARD_FIELDS
    if standard_field == "discount_rate":
        strategy = "default_zero"
        confidence = 55.0
        explanation = (
            "No compatible discount field was found. Explicit default 0 is available, "
            "but it must be confirmed because it asserts that no discount was applied."
        )
    elif standard_field == "returned":
        strategy = "not_provided"
        confidence = 55.0
        explanation = (
            "No compatible returned field was found. Keep the field as data-not-provided "
            "with nullable values; this does not mean no orders were returned."
        )
    elif standard_field == "customer_id":
        strategy = "not_provided"
        confidence = 55.0
        explanation = (
            "No customer identifier was found. Customer data can be marked as not "
            "provided so customer analysis is skipped without inventing identifiers."
        )
    elif required:
        strategy = "unmapped"
        confidence = 0.0
        explanation = "No source column met the minimum recommendation threshold."
    else:
        strategy = "omit"
        confidence = 0.0
        explanation = "No source column met the minimum recommendation threshold."

    return FieldMappingRecommendation(
        standard_field=standard_field,
        required=required,
        target_type=TARGET_TYPES[standard_field],
        recommended_strategy=strategy,
        recommended_source=None,
        confidence_score=confidence,
        score_breakdown={
            "column_name_alias": 0.0,
            "business_context": 0.0,
            "semantic_type": 0.0,
            "sample_value_compatibility": 0.0,
            "entity_role_consistency": 0.0,
            "identifier_display_penalty": 0.0,
        },
        explanation=explanation,
    )


def recommend_standard_field_mappings(
    frame: pd.DataFrame,
    source_entity_roles: Mapping[str, str] | None = None,
) -> tuple[FieldMappingRecommendation, ...]:
    """Recommend unique source mappings without changing the merged DataFrame."""
    evidence = {column: _profile_column(frame[column]) for column in frame.columns}
    scored_pairs = []
    for standard_field in STANDARD_FIELDS:
        for column in frame.columns:
            score, breakdown, explanation = _score_source_column(
                standard_field,
                column,
                evidence[column],
                source_entity_roles,
            )
            if score >= RECOMMENDATION_THRESHOLD:
                scored_pairs.append(
                    (
                        score,
                        standard_field in REQUIRED_STANDARD_FIELDS,
                        standard_field,
                        column,
                        breakdown,
                        explanation,
                    )
                )

    assigned_fields: dict[str, FieldMappingRecommendation] = {}
    assigned_columns = set()
    for score, required, standard_field, column, breakdown, explanation in sorted(
        scored_pairs,
        key=lambda item: (item[0], item[1], item[2]),
        reverse=True,
    ):
        if standard_field in assigned_fields or column in assigned_columns:
            continue
        assigned_fields[standard_field] = FieldMappingRecommendation(
            standard_field=standard_field,
            required=required,
            target_type=TARGET_TYPES[standard_field],
            recommended_strategy="source",
            recommended_source=column,
            confidence_score=score,
            score_breakdown=breakdown,
            explanation=explanation,
        )
        assigned_columns.add(column)

    return tuple(
        assigned_fields.get(field, _fallback_recommendation(field))
        for field in STANDARD_FIELDS
    )


def selections_from_recommendations(
    recommendations: Iterable[FieldMappingRecommendation],
    *,
    confirmed: bool = False,
) -> tuple[StandardFieldSelection, ...]:
    """Create UI defaults while keeping confirmation false unless explicitly requested."""
    return tuple(
        StandardFieldSelection(
            standard_field=recommendation.standard_field,
            strategy=recommendation.recommended_strategy,
            source_column=recommendation.recommended_source,
            confirmed=confirmed,
        )
        for recommendation in recommendations
    )


def _selection_map(
    selections: Iterable[StandardFieldSelection],
) -> tuple[dict[str, StandardFieldSelection], list[str]]:
    by_field = {}
    errors = []
    for selection in selections:
        if selection.standard_field not in STANDARD_FIELDS:
            errors.append(f"Unknown standard field {selection.standard_field!r}.")
        elif selection.standard_field in by_field:
            errors.append(
                f"Standard field {selection.standard_field!r} was selected more than once."
            )
        else:
            by_field[selection.standard_field] = selection
    return by_field, errors


def build_standard_mapping_plan(
    frame: pd.DataFrame,
    selections: Iterable[StandardFieldSelection],
    selected_extension_columns: Sequence[str] = (),
) -> StandardFieldMappingPlan:
    """Validate explicit choices before any unified order conversion is attempted."""
    by_field, errors = _selection_map(selections)
    source_usage: dict[str, str] = {}

    for field in REQUIRED_TRANSACTION_FIELDS:
        selection = by_field.get(field)
        if selection is None or selection.strategy == "unmapped":
            errors.append(f"Required standard field {field!r} is not mapped.")
            continue
        if not selection.confirmed:
            errors.append(f"Required standard field {field!r} is not confirmed.")

    for field in BUSINESS_ASSUMPTION_FIELDS + ("returned",):
        selection = by_field.get(field)
        if selection is None or selection.strategy in {"unmapped", "omit"}:
            errors.append(f"A strategy must be selected for {field!r}.")
            continue
        if not selection.confirmed:
            errors.append(f"Standard field {field!r} is not confirmed.")

    for field, selection in by_field.items():
        allowed = ALLOWED_STRATEGIES[field]
        if selection.strategy not in allowed:
            errors.append(
                f"Strategy {selection.strategy!r} is not allowed for {field!r}."
            )
            continue
        if selection.strategy == "source":
            if selection.source_column is None:
                errors.append(f"Standard field {field!r} has no source column.")
                continue
            if selection.source_column not in frame.columns:
                errors.append(
                    f"Source column {selection.source_column!r} for {field!r} was not found."
                )
                continue
            previous_field = source_usage.get(selection.source_column)
            if previous_field is not None:
                errors.append(
                    f"Source column {selection.source_column!r} is mapped to both "
                    f"{previous_field!r} and {field!r}."
                )
            else:
                source_usage[selection.source_column] = field
        elif selection.source_column is not None:
            errors.append(
                f"Strategy {selection.strategy!r} for {field!r} cannot also use a source column."
            )
        if selection.strategy != "omit" and not selection.confirmed:
            errors.append(f"Standard field {field!r} is not confirmed.")

    extension_columns = tuple(dict.fromkeys(selected_extension_columns))
    for column in extension_columns:
        if column not in frame.columns:
            errors.append(f"Extension column {column!r} was not found.")
        if column in source_usage:
            errors.append(
                f"Extension column {column!r} is already used for standard field "
                f"{source_usage[column]!r}."
            )
        if column in STANDARD_FIELDS:
            errors.append(
                f"Extension column {column!r} conflicts with a standard output field."
            )

    if errors:
        raise StandardFieldMappingError(tuple(dict.fromkeys(errors)))

    ordered_selections = tuple(
        by_field.get(field, StandardFieldSelection(field, "omit"))
        for field in STANDARD_FIELDS
    )
    return StandardFieldMappingPlan(
        selections=ordered_selections,
        selected_extension_columns=extension_columns,
        validation_status="passed",
    )


def _strategy_recommendation(
    selection: StandardFieldSelection,
) -> FieldMappingRecommendation:
    fallback = _fallback_recommendation(selection.standard_field)
    if selection.strategy == fallback.recommended_strategy:
        return fallback
    explanations = {
        "default_zero": "User explicitly selected a constant discount rate of 0.",
        "not_provided": "User explicitly marked returned data as not provided.",
        "not_applicable": "User explicitly marked return analysis as not applicable.",
        "temporary_row_id": "User selected a generated row-level customer identifier.",
        "temporary_order_id": "User selected a generated order-level customer identifier.",
        "omit": "Optional field was omitted.",
    }
    return FieldMappingRecommendation(
        standard_field=selection.standard_field,
        required=selection.standard_field in REQUIRED_STANDARD_FIELDS,
        target_type=TARGET_TYPES[selection.standard_field],
        recommended_strategy=selection.strategy,
        recommended_source=None,
        confidence_score=0.0,
        score_breakdown={
            "column_name_alias": 0.0,
            "business_context": 0.0,
            "semantic_type": 0.0,
            "sample_value_compatibility": 0.0,
            "entity_role_consistency": 0.0,
            "identifier_display_penalty": 0.0,
        },
        explanation=explanations.get(selection.strategy, "User-selected strategy."),
    )


def _field_availability(
    plan: StandardFieldMappingPlan,
    output: pd.DataFrame | None = None,
    customer_mapping_issue: str | None = None,
    store_mapping_issue: str | None = None,
) -> tuple[FieldAvailability, ...]:
    records = []
    for selection in plan.selections:
        provided_row_count = None
        total_row_count = None
        if selection.strategy == "source":
            status = "provided"
            default_value = None
            notes = f"Mapped from source column {selection.source_column}."
        elif selection.strategy == "default_zero":
            status = "assumed_default"
            default_value = 0.0
            notes = (
                "User confirmed a default value of 0. This is a business "
                "assumption, not an observed source value."
            )
        elif selection.strategy == "not_provided":
            status = "not_provided"
            default_value = None
            if selection.standard_field == "returned":
                notes = RETURN_NOT_PROVIDED_MESSAGE
            else:
                notes = (
                    "Source data was not provided. Values remain unknown and must "
                    "not be interpreted as false or zero."
                )
        elif selection.strategy == "not_applicable":
            status = "not_applicable"
            default_value = None
            notes = RETURN_NOT_APPLICABLE_MESSAGE
        elif selection.strategy in {"temporary_row_id", "temporary_order_id"}:
            status = "generated_temporary"
            default_value = None
            notes = (
                "User confirmed generated temporary identifiers; repeat-customer "
                "analysis may be limited."
            )
        else:
            status = "omitted"
            default_value = None
            notes = "Optional standard field was not selected."

        if selection.standard_field == "customer_id" and output is not None:
            total_row_count = len(output)
            if "customer_id" in output.columns:
                customer_present = _present_mask(output["customer_id"])
                provided_row_count = int(customer_present.sum())
            else:
                provided_row_count = 0

            count_note = (
                f"Non-empty customer_id rows: {provided_row_count:,} / "
                f"{total_row_count:,} valid rows."
            )
            if provided_row_count == 0:
                status = "not_provided"
                notes = (
                    "Customer data was not provided. Customer analysis must be skipped. "
                    + count_note
                )
            elif provided_row_count < total_row_count:
                status = "partially_provided"
                notes = (
                    "Customer data was only partially provided. Customer analysis was "
                    f"skipped. {count_note}"
                )
            else:
                status = "provided"
                notes = (
                    f"Mapped from source column {selection.source_column}. "
                    + count_note
                )
            if customer_mapping_issue and provided_row_count:
                status = "mapping_conflict"
                notes = f"{customer_mapping_issue} {count_note}"

        if selection.standard_field in {"store_id", "store_name"} and output is not None:
            total_row_count = len(output)
            if selection.standard_field in output.columns:
                present = _present_mask(output[selection.standard_field])
                provided_row_count = int(present.sum())
            else:
                provided_row_count = 0
            if selection.strategy == "source":
                if provided_row_count == 0:
                    status = "not_provided"
                elif provided_row_count < total_row_count:
                    status = "partially_provided"
                else:
                    status = "provided"
                notes = (
                    f"Non-empty {selection.standard_field} rows: "
                    f"{provided_row_count:,} / {total_row_count:,} valid rows."
                )

        records.append(
            FieldAvailability(
                field_name=selection.standard_field,
                availability_status=status,
                source_column=selection.source_column,
                default_value=default_value,
                user_confirmed=selection.confirmed or selection.strategy == "omit",
                notes=notes,
                provided_row_count=provided_row_count,
                total_row_count=total_row_count,
            )
        )
    if output is not None:
        total_row_count = len(output)
        store_present = pd.Series(False, index=output.index)
        source_columns = []
        user_confirmed = True
        for field in ("store_id", "store_name"):
            selection = next(
                item for item in plan.selections if item.standard_field == field
            )
            user_confirmed = user_confirmed and (
                selection.confirmed or selection.strategy == "omit"
            )
            if selection.strategy == "source":
                source_columns.append(str(selection.source_column))
            if field in output.columns:
                store_present = store_present | _present_mask(output[field])

        provided_row_count = int(store_present.sum())
        coverage_note = (
            f"Store data was available for {provided_row_count:,} of "
            f"{total_row_count:,} transaction rows."
        )
        if store_mapping_issue and provided_row_count:
            status = "mapping_conflict"
            notes = f"{store_mapping_issue} {coverage_note}"
        elif provided_row_count == 0:
            status = "not_provided"
            notes = STORE_NOT_PROVIDED_MESSAGE
        elif provided_row_count < total_row_count:
            status = "partially_provided"
            notes = f"{STORE_PARTIALLY_PROVIDED_MESSAGE} {coverage_note}"
        else:
            status = "provided"
            notes = coverage_note

        store_id_count = (
            int(_present_mask(output["store_id"]).sum())
            if "store_id" in output.columns
            else 0
        )
        store_name_count = (
            int(_present_mask(output["store_name"]).sum())
            if "store_name" in output.columns
            else 0
        )
        if store_id_count == 0 and store_name_count:
            notes = f"{notes} {STORE_NAME_GROUPING_NOTE}"

        records.append(
            FieldAvailability(
                field_name="store_analysis",
                availability_status=status,
                source_column=", ".join(source_columns) or None,
                default_value=None,
                user_confirmed=user_confirmed,
                notes=notes,
                provided_row_count=provided_row_count,
                total_row_count=total_row_count,
            )
        )
    return tuple(records)


def _customer_mapping_issue(
    plan: StandardFieldMappingPlan,
    source_entity_roles: Mapping[str, str] | None,
) -> str | None:
    selections = {item.standard_field: item for item in plan.selections}
    customer_id = selections["customer_id"]
    customer_name = selections["customer_name"]
    if customer_id.strategy != "source":
        return None

    id_role = _source_entity_role(
        customer_id.source_column, source_entity_roles
    )
    if id_role != "customer":
        return (
            "Customer field mapping conflict: customer_id source "
            f"{customer_id.source_column!r} is classified as {id_role}, not customer. "
            "Customer analysis was skipped."
        )

    if customer_name.strategy != "source":
        return None
    name_role = _source_entity_role(
        customer_name.source_column, source_entity_roles
    )
    if name_role != "customer":
        return (
            "Customer field mapping conflict: customer_name source "
            f"{customer_name.source_column!r} is classified as {name_role}, while "
            f"customer_id source {customer_id.source_column!r} is customer. "
            "Customer analysis was skipped."
        )
    return None


def _store_mapping_issue(
    plan: StandardFieldMappingPlan,
    source_entity_roles: Mapping[str, str] | None,
) -> str | None:
    selections = {item.standard_field: item for item in plan.selections}
    for field in ("store_id", "store_name"):
        selection = selections[field]
        if selection.strategy != "source":
            continue
        role = _source_entity_role(selection.source_column, source_entity_roles)
        if role in KNOWN_ENTITY_ROLES and role != "store":
            return (
                f"Store field mapping conflict: {field} source "
                f"{selection.source_column!r} is classified as {role}, not store. "
                "Store analysis was skipped."
            )
    return None


def _convert_selection(
    frame: pd.DataFrame,
    selection: StandardFieldSelection,
    converted_fields: Mapping[str, pd.Series],
    source_entity_roles: Mapping[str, str] | None = None,
) -> tuple[pd.Series, FieldConversionDiagnostic, tuple[str, ...], tuple[str, ...]]:
    field = selection.standard_field
    required = field in REQUIRED_STANDARD_FIELDS
    warnings = []
    errors = []
    invalid_count = 0

    if selection.strategy == "source":
        raw = frame[selection.source_column]
        recommendation = evaluate_field_mapping_recommendation(
            frame,
            field,
            selection.source_column,
            source_entity_roles,
        )
        present = _present_mask(raw)
        if TARGET_TYPES[field] == "date":
            converted = _to_datetime_series(raw)
        elif TARGET_TYPES[field] in {"money", "number", "rate"}:
            converted = _clean_numeric_series(
                raw, percentage=TARGET_TYPES[field] == "rate"
            )
        elif TARGET_TYPES[field] == "boolean":
            converted = _to_boolean_series(raw)
        elif field == "category" and _identifier_display_source(
            selection.source_column
        ):
            converted = _entity_display_series(raw, "Category")
        else:
            converted = raw.astype("string").str.strip().mask(~present, pd.NA)
        source_non_null_count = int(present.sum())
        conversion_failure_count = int((present & converted.isna()).sum())
        source_or_strategy = selection.source_column
    elif selection.strategy == "default_zero":
        converted = pd.Series(0.0, index=frame.index, dtype="Float64")
        recommendation = _strategy_recommendation(selection)
        source_non_null_count = len(frame)
        conversion_failure_count = 0
        source_or_strategy = "Default 0"
        warnings.append(
            "discount_rate is explicitly set to 0 for every row; this is a business assumption."
        )
    elif selection.strategy in {"not_provided", "not_applicable"}:
        dtype = "boolean" if field == "returned" else "string"
        converted = pd.Series(pd.NA, index=frame.index, dtype=dtype)
        recommendation = _strategy_recommendation(selection)
        source_non_null_count = 0
        conversion_failure_count = 0
        source_or_strategy = (
            "Data not provided"
            if selection.strategy == "not_provided"
            else "Not applicable"
        )
        if field == "returned" and selection.strategy == "not_provided":
            warnings.append(
                RETURN_NOT_PROVIDED_MESSAGE
            )
        elif field == "customer_id":
            warnings.append(
                "Customer data was not provided. Customer analysis was skipped."
            )
    elif selection.strategy == "temporary_row_id":
        converted = pd.Series(
            [f"TEMP-CUSTOMER-ROW-{index + 1}" for index in range(len(frame))],
            index=frame.index,
            dtype="string",
        )
        recommendation = _strategy_recommendation(selection)
        source_non_null_count = len(frame)
        conversion_failure_count = 0
        source_or_strategy = "Temporary row-level ID"
        warnings.append(
            "customer_id uses generated row-level values and cannot identify repeat customers."
        )
    elif selection.strategy == "temporary_order_id":
        order_ids = converted_fields.get("order_id")
        if order_ids is None:
            converted = pd.Series(pd.NA, index=frame.index, dtype="string")
            errors.append("Temporary order-level customer IDs require a converted order_id.")
        else:
            converted = "TEMP-CUSTOMER-ORDER-" + order_ids.astype("string")
        recommendation = _strategy_recommendation(selection)
        source_non_null_count = int(converted.notna().sum())
        conversion_failure_count = 0
        source_or_strategy = "Temporary order-level ID"
        warnings.append(
            "customer_id uses generated order-level values and cannot identify customers across orders."
        )
    else:
        raise StandardFieldMappingError(
            [f"Strategy {selection.strategy!r} cannot produce {field!r}."]
        )

    if field == "unit_price":
        invalid_count = int((converted < 0).fillna(False).sum())
    elif field == "quantity":
        invalid_count = int((converted <= 0).fillna(False).sum())
    elif field == "discount_rate":
        invalid_count = int(
            ((converted < 0) | (converted > 1)).fillna(False).sum()
        )

    failure_denominator = max(source_non_null_count, 1)
    failure_rate = conversion_failure_count / failure_denominator
    invalid_rate = invalid_count / failure_denominator
    null_count = int(converted.isna().sum())
    null_rate = null_count / len(converted) if len(converted) else 0.0

    status = "passed"
    if selection.strategy in {"not_provided", "not_applicable"}:
        status = selection.strategy
    elif selection.strategy.startswith("temporary_"):
        status = "warning"
    elif selection.strategy == "default_zero":
        status = "confirmed_default"
    elif (
        field != "date"
        and failure_rate >= SEVERE_CONVERSION_FAILURE_RATE
        and conversion_failure_count
    ):
        status = "blocked"
        errors.append(
            f"{field} conversion failed for {conversion_failure_count:,} of "
            f"{source_non_null_count:,} non-empty values ({failure_rate:.2%})."
        )
    elif invalid_rate >= SEVERE_CONVERSION_FAILURE_RATE and invalid_count:
        status = "blocked"
        errors.append(
            f"{field} contains {invalid_count:,} out-of-range values "
            f"({invalid_rate:.2%} of non-empty source values)."
        )
    elif conversion_failure_count or invalid_count or (required and null_count):
        status = "warning"
        warnings.append(
            f"{field} has {conversion_failure_count:,} conversion failures, "
            f"{invalid_count:,} invalid values, and {null_count:,} null output values."
        )

    if required and selection.strategy != "not_provided" and len(converted) and null_count == len(converted):
        status = "blocked"
        errors.append(f"Required standard field {field!r} converted entirely to null values.")

    diagnostic = FieldConversionDiagnostic(
        standard_field=field,
        required=required,
        source_or_strategy=source_or_strategy,
        confidence_score=recommendation.confidence_score,
        score_breakdown=recommendation.score_breakdown,
        source_non_null_count=source_non_null_count,
        conversion_failure_count=conversion_failure_count,
        invalid_value_count=invalid_count,
        null_count=null_count,
        null_rate=null_rate,
        output_dtype=str(converted.dtype),
        status=status,
        explanation=recommendation.explanation,
    )
    return converted, diagnostic, tuple(errors), tuple(warnings)


def generate_unified_orders(
    frame: pd.DataFrame,
    selections: Iterable[StandardFieldSelection],
    selected_extension_columns: Sequence[str] = (),
    source_entity_roles: Mapping[str, str] | None = None,
) -> StandardMappingResult:
    """Validate and convert a merged dataset without mutating it or running analysis.py."""
    source_memory = int(frame.memory_usage(index=True, deep=True).sum())
    try:
        plan = build_standard_mapping_plan(
            frame, selections, selected_extension_columns
        )
    except StandardFieldMappingError as error:
        return StandardMappingResult(
            success=False,
            plan=None,
            unified_orders=None,
            diagnostics=(),
            errors=error.errors,
            warnings=(),
            source_row_count=len(frame),
            output_row_count=None,
            source_column_count=len(frame.columns),
            output_column_count=None,
            source_memory_bytes=source_memory,
            output_memory_bytes=None,
            report_columns=(),
        )

    output = pd.DataFrame(index=frame.index.copy())
    converted_fields = {}
    diagnostics = []
    errors = []
    warnings = []
    for selection in plan.selections:
        if selection.strategy == "omit":
            continue
        converted, diagnostic, field_errors, field_warnings = _convert_selection(
            frame,
            selection,
            converted_fields,
            source_entity_roles,
        )
        output[selection.standard_field] = converted
        converted_fields[selection.standard_field] = converted
        diagnostics.append(diagnostic)
        errors.extend(field_errors)
        warnings.extend(field_warnings)

    for column in plan.selected_extension_columns:
        output[column] = frame[column].copy(deep=False)

    customer_mapping_issue = _customer_mapping_issue(
        plan, source_entity_roles
    )
    store_mapping_issue = _store_mapping_issue(plan, source_entity_roles)
    availability = _field_availability(
        plan,
        output,
        customer_mapping_issue,
        store_mapping_issue,
    )
    if customer_mapping_issue:
        warnings.append(customer_mapping_issue)
    if store_mapping_issue:
        warnings.append(store_mapping_issue)

    missing_required = [
        field for field in PIPELINE_REQUIRED_OUTPUT_FIELDS if field not in output.columns
    ]
    if missing_required:
        errors.append(
            "Unified orders output is missing required field(s): "
            + ", ".join(missing_required)
            + "."
        )
    if len(output) != len(frame):
        errors.append("Field mapping changed the row count and was blocked.")

    errors = list(dict.fromkeys(errors))
    warnings = list(dict.fromkeys(warnings))
    if errors:
        return StandardMappingResult(
            success=False,
            plan=plan,
            unified_orders=None,
            diagnostics=tuple(diagnostics),
            errors=tuple(errors),
            warnings=tuple(warnings),
            source_row_count=len(frame),
            output_row_count=None,
            source_column_count=len(frame.columns),
            output_column_count=None,
            source_memory_bytes=source_memory,
            output_memory_bytes=None,
            report_columns=(),
            field_availability=availability,
        )

    output_memory = int(output.memory_usage(index=True, deep=True).sum())
    return StandardMappingResult(
        success=True,
        plan=plan,
        unified_orders=output,
        diagnostics=tuple(diagnostics),
        errors=(),
        warnings=tuple(warnings),
        source_row_count=len(frame),
        output_row_count=len(output),
        source_column_count=len(frame.columns),
        output_column_count=len(output.columns),
        source_memory_bytes=source_memory,
        output_memory_bytes=output_memory,
        report_columns=tuple(output.columns),
        field_availability=availability,
    )
