from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


RELATIONSHIP_FIELD_ALIASES = {
    "order": {
        "order id", "order number", "order no", "transaction id", "invoice id",
        "订单号", "订单编号", "交易号", "交易编号", "单据号", "单据编号",
        "销售单号", "销售单编号", "流水号", "小票号", "凭证号",
    },
    "product": {
        "product id", "product key", "product code", "item id", "item code",
        "sku", "sku id", "sku code", "商品号", "商品编号", "商品编码",
        "产品编号", "产品编码", "货号", "货品编号", "货品编码",
        "物料号", "物料编号", "物料编码", "sku编号", "sku编码",
        "款号", "条码", "商品条码",
    },
    "customer": {
        "customer id", "customer key", "customer code", "client id", "buyer id",
        "客户号", "客户编号", "客户编码", "顾客编号", "顾客编码",
        "会员号", "会员编号", "会员编码", "会员卡号", "买家编号",
        "买家id", "客商号", "客商编号", "客商编码",
    },
    "store": {
        "store id", "store key", "store code", "shop id", "shop code",
        "branch id", "branch code", "outlet id", "location id", "门店号",
        "门店编号", "门店编码", "店铺编号", "店铺编码", "网点号",
        "网点编号", "网点代码", "分店编号", "机构号", "机构编号",
        "机构编码", "组织号", "组织编号", "组织编码", "销售点编号", "营业点编号",
    },
    "supplier": {
        "supplier id", "supplier code", "vendor id", "vendor code",
        "供应商号", "供应商编号", "供应商编码",
    },
    "employee": {
        "employee id", "employee code", "salesperson id", "sales person id",
        "员工号", "员工编号", "业务员编号", "销售员编号",
    },
}


ENTITY_ROLE_ALIASES = (
    ("order_line", (
        "order details", "order detail", "order lines", "order line",
        "销售表", "销售明细", "销售记录", "订单明细", "交易表",
        "交易明细", "出库明细", "零售明细", "流水表", "销售流水",
        "小票明细", "单据明细",
    )),
    ("order_header", (
        "orders", "sales orders", "order headers", "订单表", "订单主表",
    )),
    ("customer", (
        "customers", "customer", "clients", "buyers", "客户表", "客户档案",
        "客户主数据", "顾客表", "会员表", "会员档案", "买家表", "客商表", "客商档案",
    )),
    ("shipper", ("shippers", "shipper", "shipping", "carriers", "carrier", "承运商", "配送商", "物流商")),
    ("supplier", ("suppliers", "supplier", "vendors", "vendor", "供应商表", "供应商档案")),
    ("employee", ("employees", "employee", "salespeople", "salesperson", "员工表", "业务员表")),
    ("category", ("categories", "category", "product categories", "品类表", "商品分类表")),
    ("product", (
        "products", "product", "items", "skus", "商品表", "商品档案", "商品主数据",
        "产品表", "产品档案", "物料表", "物料档案", "物料主数据", "sku表",
    )),
    ("store", (
        "stores", "store", "shops", "branches", "门店表", "门店档案", "店铺表",
        "网点表", "网点档案", "分店表", "组织表", "组织机构表", "机构表", "营业点", "销售点",
    )),
    ("region", ("regions", "region", "territories", "territory", "地区表", "区域表")),
    ("warehouse", ("warehouses", "warehouse", "仓库表")),
)


FIELD_ENTITY_ALIASES = (
    ("customer", tuple(sorted(RELATIONSHIP_FIELD_ALIASES["customer"])) + ("customer", "customers", "client", "clients", "buyer", "buyers", "客户", "顾客", "会员", "客商")),
    ("shipper", ("shipper", "shippers", "ship via", "shipping", "carrier", "carriers", "freight", "承运商", "配送商", "物流商")),
    ("supplier", tuple(sorted(RELATIONSHIP_FIELD_ALIASES["supplier"])) + ("supplier", "suppliers", "vendor", "vendors", "供应商")),
    ("employee", tuple(sorted(RELATIONSHIP_FIELD_ALIASES["employee"])) + ("employee", "employees", "salesperson", "salespeople", "sales person", "员工", "业务员", "销售员")),
    ("category", ("category", "categories", "subcategory", "品类", "类别", "分类")),
    ("product", tuple(sorted(RELATIONSHIP_FIELD_ALIASES["product"])) + ("product", "products", "sku", "skus", "item", "items", "商品", "产品", "物料", "货品")),
    ("store", tuple(sorted(RELATIONSHIP_FIELD_ALIASES["store"])) + ("store", "stores", "shop", "shops", "branch", "branches", "outlet", "outlets", "门店", "店铺", "网点", "分店", "机构", "组织")),
    ("order_line", ("order detail", "line item", "line number", "订单明细", "单据明细", "行项目")),
    ("order_header", tuple(sorted(RELATIONSHIP_FIELD_ALIASES["order"])) + ("order", "invoice", "订单", "单据", "交易")),
)


STANDARD_FIELD_RELATIONSHIP_ALIASES = {
    "order_id": RELATIONSHIP_FIELD_ALIASES["order"],
    "product_id": RELATIONSHIP_FIELD_ALIASES["product"],
    "customer_id": RELATIONSHIP_FIELD_ALIASES["customer"],
    "store_id": RELATIONSHIP_FIELD_ALIASES["store"],
}


CONCEPT_ALIASES = {
    "customer": {"customer", "client", "buyer", "客户", "顾客", "买家", "会员", "客商"} | RELATIONSHIP_FIELD_ALIASES["customer"],
    "product": {"product", "sku", "item", "产品", "商品", "货品", "物料"} | RELATIONSHIP_FIELD_ALIASES["product"],
    "store": {"store", "shop", "branch", "outlet", "门店", "店铺", "分店", "网点", "机构", "组织"} | RELATIONSHIP_FIELD_ALIASES["store"],
    "order": {"order", "transaction", "invoice", "订单", "交易", "单据", "流水", "小票", "凭证"} | RELATIONSHIP_FIELD_ALIASES["order"],
    "supplier": {"supplier", "vendor", "供应商"} | RELATIONSHIP_FIELD_ALIASES["supplier"],
    "employee": {"employee", "salesperson", "员工", "业务员", "销售员"} | RELATIONSHIP_FIELD_ALIASES["employee"],
    "line_item": {"line item", "lineitem", "line no", "明细行", "行项目", "行号"},
    "date": {"date", "day", "year", "日期", "时间", "年份", "年度"},
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
        "号",
        "条码",
    } | set().union(*RELATIONSHIP_FIELD_ALIASES.values()),
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


def contains_alias(value: object, alias: str) -> bool:
    """Return whether a normalized English, Chinese, or mixed alias is present."""
    return _contains_alias(normalize_column_name(value), alias)


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
