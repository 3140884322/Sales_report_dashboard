from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


CONCEPT_ALIASES = {
    "customer": {"customer", "client", "buyer", "客户", "顾客", "买家"},
    "product": {"product", "sku", "产品", "商品", "货品"},
    "store": {"store", "shop", "branch", "门店", "店铺", "分店"},
    "order": {"order", "transaction", "订单", "交易"},
    "line_item": {"line item", "lineitem", "line no", "明细行", "行项目", "行号"},
    "date": {"date", "day", "日期", "时间"},
    "currency": {"currency", "币种", "货币"},
    "exchange_rate": {"exchange", "exchange rate", "fx rate", "汇率"},
    "key": {
        "key",
        "id",
        "identifier",
        "code",
        "no",
        "number",
        "sku",
        "编号",
        "编码",
        "代码",
        "主键",
    },
    "name": {"name", "title", "名称", "姓名"},
    "quantity": {"quantity", "qty", "units", "数量", "件数"},
    "amount": {"amount", "total", "sales", "revenue", "金额", "销售额", "收入"},
    "price": {"price", "unit price", "售价", "单价"},
    "cost": {"cost", "unit cost", "成本"},
    "category": {"category", "subcategory", "类别", "分类", "品类"},
    "country": {"country", "国家"},
    "state": {"state", "province", "省", "州"},
    "city": {"city", "城市"},
}

KEY_CONCEPTS = {"key"}
MEASURE_CONCEPTS = {"quantity", "amount", "price", "cost", "exchange_rate"}
GENERIC_NAME_CONCEPTS = {"key", "name"}


@dataclass(frozen=True)
class NameMatch:
    score: float
    reason: str


def normalize_column_name(name: object) -> str:
    text = unicodedata.normalize("NFKC", str(name)).strip()
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    text = re.sub(r"(?<=[\u4e00-\u9fff])(?=[A-Za-z0-9])", " ", text)
    text = re.sub(r"(?<=[A-Za-z0-9])(?=[\u4e00-\u9fff])", " ", text)
    text = re.sub(r"[_\-./\\]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip().casefold()
    return text


def _contains_alias(normalized_name: str, alias: str) -> bool:
    normalized_alias = normalize_column_name(alias)
    if not normalized_alias:
        return False
    if re.search(r"[\u4e00-\u9fff]", normalized_alias):
        return normalized_alias.replace(" ", "") in normalized_name.replace(" ", "")
    if " " in normalized_alias:
        return normalized_alias in normalized_name
    return normalized_alias in normalized_name.split()


def semantic_tokens(name: object) -> tuple[str, ...]:
    normalized = normalize_column_name(name)
    concepts = [
        concept
        for concept, aliases in CONCEPT_ALIASES.items()
        if any(_contains_alias(normalized, alias) for alias in aliases)
    ]
    return tuple(concepts)


def is_key_like_name(name: object, concepts: tuple[str, ...] | None = None) -> bool:
    concepts = concepts if concepts is not None else semantic_tokens(name)
    return bool(KEY_CONCEPTS.intersection(concepts))


def is_measure_like_name(name: object, concepts: tuple[str, ...] | None = None) -> bool:
    concepts = concepts if concepts is not None else semantic_tokens(name)
    return bool(MEASURE_CONCEPTS.intersection(concepts))


def compare_column_names(left_name: object, right_name: object) -> NameMatch:
    left_normalized = normalize_column_name(left_name)
    right_normalized = normalize_column_name(right_name)
    if left_normalized == right_normalized:
        return NameMatch(25.0, "normalized column names are identical")

    left_concepts = set(semantic_tokens(left_name))
    right_concepts = set(semantic_tokens(right_name))
    shared = left_concepts.intersection(right_concepts)
    if not shared:
        left_words = set(left_normalized.split())
        right_words = set(right_normalized.split())
        word_overlap = left_words.intersection(right_words)
        if word_overlap:
            return NameMatch(10.0, f"shared name token(s): {', '.join(sorted(word_overlap))}")
        return NameMatch(0.0, "no column-name or alias alignment")

    shared_business = shared.difference(GENERIC_NAME_CONCEPTS)
    if shared_business:
        left_business = left_concepts.difference(GENERIC_NAME_CONCEPTS)
        right_business = right_concepts.difference(GENERIC_NAME_CONCEPTS)
        if left_business == right_business:
            score = 22.0 if ("key" in left_concepts) == ("key" in right_concepts) else 20.0
        elif left_business.issubset(right_business) or right_business.issubset(left_business):
            score = 18.0
        else:
            score = 15.0
        return NameMatch(score, f"shared semantic alias(es): {', '.join(sorted(shared_business))}")

    if shared == {"key"}:
        return NameMatch(8.0, "both names look like identifiers")
    return NameMatch(7.0, f"shared generic concept(s): {', '.join(sorted(shared))}")
