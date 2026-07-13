from io import BytesIO
from pathlib import Path

import pandas as pd

from analysis import REQUIRED_COLUMNS


ENCODING_CANDIDATES = ["utf-8-sig", "utf-8", "cp1252", "latin1"]

SALES_REQUIRED_COLUMNS = [
    "Order Number",
    "Line Item",
    "Order Date",
    "CustomerKey",
    "StoreKey",
    "ProductKey",
    "Quantity",
    "Currency Code",
]

PRODUCTS_REQUIRED_COLUMNS = [
    "ProductKey",
    "Product Name",
    "Unit Price USD",
    "Category",
]

CUSTOMERS_REQUIRED_COLUMNS = ["CustomerKey", "Name"]
STORES_REQUIRED_COLUMNS = ["StoreKey"]
EXCHANGE_RATES_REQUIRED_COLUMNS = ["Date", "Currency", "Exchange"]

QUALITY_WARNING_COLUMNS = [
    "severity",
    "check_name",
    "table_name",
    "issue_count",
    "message",
]

MERGE_SUMMARY_COLUMNS = [
    "right_table",
    "left_keys",
    "right_keys",
    "before_row_count",
    "after_row_count",
    "row_count_change",
    "unmatched_count",
    "matched_count",
    "match_rate",
    "right_key_duplicate_row_count",
    "right_key_duplicate_key_count",
    "many_to_many_risk",
    "row_inflation",
    "status",
]

SOURCE_TABLE_SUMMARY_COLUMNS = [
    "table_name",
    "file_name",
    "encoding",
    "row_count",
    "column_count",
    "columns",
]


class MultiTableLoaderError(ValueError):
    """Raised when a multi-table dataset cannot be safely loaded."""


def _source_name(source):
    """Return a readable file name for a path or uploaded file-like object."""
    if isinstance(source, (str, Path)):
        return Path(source).name

    return getattr(source, "name", "uploaded_file")


def _read_source_bytes(source):
    """Read bytes from a path or file-like object without assuming encoding."""
    if source is None:
        raise MultiTableLoaderError("A CSV source was required but was not provided.")

    if isinstance(source, (str, Path)):
        return Path(source).read_bytes()

    if hasattr(source, "getvalue"):
        data = source.getvalue()
    else:
        try:
            source.seek(0)
        except (AttributeError, OSError):
            pass
        data = source.read()

    if isinstance(data, str):
        return data.encode("utf-8")

    return data


def read_csv_with_encoding_fallback(source, table_name):
    """Read a CSV path or file-like object using a small encoding fallback list."""
    data = _read_source_bytes(source)
    last_error = None

    for encoding in ENCODING_CANDIDATES:
        try:
            frame = pd.read_csv(BytesIO(data), encoding=encoding)
            return frame, {
                "table_name": table_name,
                "file_name": _source_name(source),
                "encoding": encoding,
                "row_count": len(frame),
                "column_count": len(frame.columns),
                "columns": list(frame.columns),
                "preview": frame.head(5).to_dict("records"),
            }
        except UnicodeDecodeError as error:
            last_error = error

    raise MultiTableLoaderError(
        f"Could not read {table_name}. Tried encodings: "
        f"{', '.join(ENCODING_CANDIDATES)}. Last error: {last_error}"
    )


def _make_empty_quality_warnings():
    """Return an empty quality warnings table with stable columns."""
    return pd.DataFrame(columns=QUALITY_WARNING_COLUMNS)


def _add_quality_warning(rows, severity, check_name, table_name, issue_count, message):
    """Append one quality warning row."""
    rows.append(
        {
            "severity": severity,
            "check_name": check_name,
            "table_name": table_name,
            "issue_count": int(issue_count) if pd.notna(issue_count) else 0,
            "message": message,
        }
    )


def _validate_required_columns(frame, required_columns, table_name):
    """Stop early when a table does not contain required columns."""
    missing_columns = [
        column for column in required_columns if column not in frame.columns
    ]

    if missing_columns:
        missing_text = ", ".join(missing_columns)
        found_text = ", ".join(frame.columns)
        raise MultiTableLoaderError(
            f"{table_name} is missing required column(s): {missing_text}. "
            f"Columns found: {found_text}"
        )


def _count_key_null_rows(frame, keys):
    """Count rows where any merge key is missing."""
    return int(frame[keys].isna().any(axis=1).sum())


def _duplicate_key_stats(frame, keys):
    """Return duplicate row count and duplicate key group count for a key set."""
    duplicate_mask = frame.duplicated(keys, keep=False)
    duplicate_row_count = int(duplicate_mask.sum())

    if duplicate_row_count:
        duplicate_key_count = int(
            frame.loc[duplicate_mask, keys].drop_duplicates().shape[0]
        )
    else:
        duplicate_key_count = 0

    return duplicate_row_count, duplicate_key_count


def _format_key_mapping(left_keys, right_keys):
    """Create readable merge key text for diagnostics."""
    return ", ".join(
        f"{left_key} -> {right_key}"
        for left_key, right_key in zip(left_keys, right_keys)
    )


def _skipped_merge_summary(right_table, status):
    """Create a merge summary row for an optional table that was skipped."""
    return {
        "right_table": right_table,
        "left_keys": "",
        "right_keys": "",
        "before_row_count": pd.NA,
        "after_row_count": pd.NA,
        "row_count_change": pd.NA,
        "unmatched_count": pd.NA,
        "matched_count": pd.NA,
        "match_rate": pd.NA,
        "right_key_duplicate_row_count": pd.NA,
        "right_key_duplicate_key_count": pd.NA,
        "many_to_many_risk": False,
        "row_inflation": False,
        "status": status,
    }


def _merge_many_to_one(
    left,
    right,
    left_keys,
    right_keys,
    right_table,
    quality_rows,
    right_columns=None,
    display_left_keys=None,
    display_right_keys=None,
):
    """Left join one dimension table and return merge diagnostics."""
    left_keys = list(left_keys)
    right_keys = list(right_keys)
    display_left_keys = display_left_keys or left_keys
    display_right_keys = display_right_keys or right_keys

    before_row_count = len(left)
    right_columns = list(right_columns or right.columns)
    right_columns = list(dict.fromkeys(right_keys + right_columns))
    right_subset = right[right_columns].copy()

    left_key_null_count = _count_key_null_rows(left, left_keys)
    right_key_null_count = _count_key_null_rows(right_subset, right_keys)

    if left_key_null_count:
        _add_quality_warning(
            quality_rows,
            "warning",
            "left_merge_key_null_count",
            "Sales",
            left_key_null_count,
            f"{left_key_null_count} Sales row(s) have missing merge key(s) "
            f"for {right_table}.",
        )

    if right_key_null_count:
        _add_quality_warning(
            quality_rows,
            "warning",
            "right_merge_key_null_count",
            right_table,
            right_key_null_count,
            f"{right_key_null_count} {right_table} row(s) have missing merge key(s).",
        )

    duplicate_row_count, duplicate_key_count = _duplicate_key_stats(
        right_subset,
        right_keys,
    )
    left_duplicate_row_count, _ = _duplicate_key_stats(left, left_keys)
    many_to_many_risk = bool(duplicate_row_count and left_duplicate_row_count)

    if duplicate_row_count:
        key_text = _format_key_mapping(display_left_keys, display_right_keys)
        raise MultiTableLoaderError(
            f"{right_table} cannot be merged safely. The right-side merge key "
            f"contains {duplicate_key_count} duplicate key value(s) involving "
            f"{duplicate_row_count} row(s). This can create many-to-many row "
            f"inflation. Merge key: {key_text}."
        )

    indicator_name = f"__merge_{right_table.lower().replace(' ', '_')}"

    try:
        merged = left.merge(
            right_subset,
            left_on=left_keys,
            right_on=right_keys,
            how="left",
            validate="many_to_one",
            indicator=indicator_name,
        )
    except pd.errors.MergeError as error:
        raise MultiTableLoaderError(
            f"{right_table} failed many-to-one merge validation: {error}"
        ) from error

    after_row_count = len(merged)
    unmatched_count = int((merged[indicator_name] == "left_only").sum())
    matched_count = before_row_count - unmatched_count
    match_rate = matched_count / before_row_count if before_row_count else 1.0
    row_inflation = after_row_count > before_row_count

    if unmatched_count:
        _add_quality_warning(
            quality_rows,
            "warning",
            "merge_unmatched_count",
            right_table,
            unmatched_count,
            f"{unmatched_count} Sales row(s) did not match {right_table}.",
        )

    if row_inflation:
        raise MultiTableLoaderError(
            f"{right_table} merge increased row count from {before_row_count} "
            f"to {after_row_count}. The merge was stopped to avoid inflated sales."
        )

    merged = merged.drop(columns=[indicator_name])
    summary = {
        "right_table": right_table,
        "left_keys": ", ".join(display_left_keys),
        "right_keys": ", ".join(display_right_keys),
        "before_row_count": before_row_count,
        "after_row_count": after_row_count,
        "row_count_change": after_row_count - before_row_count,
        "unmatched_count": unmatched_count,
        "matched_count": matched_count,
        "match_rate": match_rate,
        "right_key_duplicate_row_count": duplicate_row_count,
        "right_key_duplicate_key_count": duplicate_key_count,
        "many_to_many_risk": many_to_many_risk,
        "row_inflation": row_inflation,
        "status": "merged",
    }

    return merged, summary


def clean_money_series(series):
    """Convert money strings such as '$1,234.56' to numeric values."""
    cleaned = (
        series.astype("string")
        .str.replace("$", "", regex=False)
        .str.replace(",", "", regex=False)
        .str.strip()
    )

    return pd.to_numeric(cleaned, errors="coerce")


def _to_numeric_with_warning(series, table_name, column_name, quality_rows):
    """Convert a series to numeric and record failed conversions."""
    converted = pd.to_numeric(series, errors="coerce")
    failed_count = int(converted.isna().sum() - series.isna().sum())

    if failed_count:
        _add_quality_warning(
            quality_rows,
            "critical",
            f"{column_name.lower().replace(' ', '_')}_conversion_failed_count",
            table_name,
            failed_count,
            f"{failed_count} non-empty {column_name} value(s) could not be "
            "converted to numbers. Values were left as missing, not filled.",
        )

    return converted


def _date_conversion_warning(series, table_name, column_name, quality_rows):
    """Record date parsing failures without changing the original date column."""
    parsed = pd.to_datetime(series, errors="coerce", format="mixed")
    failed_count = int(parsed.isna().sum() - series.isna().sum())

    if failed_count:
        _add_quality_warning(
            quality_rows,
            "warning",
            f"{column_name.lower().replace(' ', '_')}_date_parse_failed_count",
            table_name,
            failed_count,
            f"{failed_count} non-empty {column_name} value(s) could not be "
            "parsed as dates.",
        )

    return parsed


def _get_column(frame, column_name, default=pd.NA):
    """Return a column when present, otherwise an NA-filled series."""
    if column_name in frame.columns:
        return frame[column_name]

    return pd.Series([default] * len(frame), index=frame.index)


def _prepare_products(products):
    """Select product fields needed for standard orders and useful extensions."""
    available_columns = [
        column
        for column in [
            "ProductKey",
            "Product Name",
            "Brand",
            "Color",
            "Unit Cost USD",
            "Unit Price USD",
            "SubcategoryKey",
            "Subcategory",
            "CategoryKey",
            "Category",
        ]
        if column in products.columns
    ]

    return products[available_columns].copy()


def _prepare_customers(customers):
    """Select and rename customer fields so they do not collide with store fields."""
    available_columns = [
        column
        for column in [
            "CustomerKey",
            "Gender",
            "Name",
            "City",
            "State Code",
            "State",
            "Zip Code",
            "Country",
            "Continent",
            "Birthday",
        ]
        if column in customers.columns
    ]
    prepared = customers[available_columns].copy()

    return prepared.rename(
        columns={
            "Gender": "Customer Gender",
            "Name": "Customer Name",
            "City": "Customer City",
            "State Code": "Customer State Code",
            "State": "Customer State",
            "Zip Code": "Customer Zip Code",
            "Country": "Customer Country",
            "Continent": "Customer Continent",
            "Birthday": "Customer Birthday",
        }
    )


def _prepare_stores(stores):
    """Select and rename store fields so they do not collide with customer fields."""
    available_columns = [
        column
        for column in [
            "StoreKey",
            "Country",
            "State",
            "Square Meters",
            "Open Date",
        ]
        if column in stores.columns
    ]
    prepared = stores[available_columns].copy()

    return prepared.rename(
        columns={
            "Country": "Store Country",
            "State": "Store State",
            "Square Meters": "Store Square Meters",
            "Open Date": "Store Open Date",
        }
    )


def _prepare_exchange_rates(exchange_rates):
    """Parse exchange-rate dates and keep the currency conversion fields."""
    prepared = exchange_rates.copy()
    prepared["__exchange_date_key"] = pd.to_datetime(
        prepared["Date"],
        errors="coerce",
        format="mixed",
    )

    return prepared[["__exchange_date_key", "Currency", "Exchange"]].copy()


def _make_source_summary(source_metadata):
    """Create the source table summary DataFrame."""
    rows = [
        {
            "table_name": item["table_name"],
            "file_name": item["file_name"],
            "encoding": item["encoding"],
            "row_count": item["row_count"],
            "column_count": item["column_count"],
            "columns": item["columns"],
        }
        for item in source_metadata
    ]

    return pd.DataFrame(rows, columns=SOURCE_TABLE_SUMMARY_COLUMNS)


def _find_sales_unit_price_column(merged):
    """Find an actual Sales price column if one is present."""
    for column in ["Unit Price", "Sales Unit Price", "Sales Price", "Price"]:
        if column in merged.columns:
            return column

    return None


def _standardize_orders(merged, quality_rows):
    """Convert merged Maven tables into the standard order table."""
    sales_price_column = _find_sales_unit_price_column(merged)

    if sales_price_column:
        raw_unit_price = merged[sales_price_column]
        price_source = f"Sales.{sales_price_column}"
    else:
        raw_unit_price = merged["Unit Price USD"]
        price_source = "Products.Unit Price USD"

    unit_price = clean_money_series(raw_unit_price)
    failed_price_count = int(unit_price.isna().sum() - raw_unit_price.isna().sum())

    if failed_price_count:
        _add_quality_warning(
            quality_rows,
            "critical",
            "price_conversion_failed_count",
            "Products",
            failed_price_count,
            f"{failed_price_count} non-empty unit price value(s) could not be "
            "converted to numbers. Values were left as missing, not filled.",
        )

    quantity = _to_numeric_with_warning(
        merged["Quantity"],
        "Sales",
        "Quantity",
        quality_rows,
    )
    _date_conversion_warning(
        merged["Order Date"],
        "Sales",
        "Order Date",
        quality_rows,
    )

    product_unit_price_usd = clean_money_series(merged["Unit Price USD"])
    product_unit_cost_usd = (
        clean_money_series(merged["Unit Cost USD"])
        if "Unit Cost USD" in merged.columns
        else pd.Series([pd.NA] * len(merged), index=merged.index)
    )

    customer_name = (
        merged["Customer Name"]
        if "Customer Name" in merged.columns
        else merged["CustomerKey"].astype("string")
    )

    unified = pd.DataFrame(
        {
            "order_id": merged["Order Number"],
            "date": merged["Order Date"],
            "customer_id": merged["CustomerKey"],
            "product_id": merged["ProductKey"],
            "unit_price": unit_price,
            "quantity": quantity,
            "discount_rate": 0.0,
            "returned": False,
            "customer_name": customer_name,
            "product_name": merged["Product Name"],
            "category": merged["Category"],
            "line_item": merged["Line Item"],
            "delivery_date": _get_column(merged, "Delivery Date"),
            "store_id": _get_column(merged, "StoreKey"),
            "currency_code": _get_column(merged, "Currency Code"),
            "unit_price_usd": product_unit_price_usd,
            "unit_cost_usd": product_unit_cost_usd,
            "brand": _get_column(merged, "Brand"),
            "color": _get_column(merged, "Color"),
            "subcategory_key": _get_column(merged, "SubcategoryKey"),
            "subcategory": _get_column(merged, "Subcategory"),
            "category_key": _get_column(merged, "CategoryKey"),
            "customer_gender": _get_column(merged, "Customer Gender"),
            "customer_city": _get_column(merged, "Customer City"),
            "customer_state_code": _get_column(merged, "Customer State Code"),
            "customer_state": _get_column(merged, "Customer State"),
            "customer_zip_code": _get_column(merged, "Customer Zip Code"),
            "customer_country": _get_column(merged, "Customer Country"),
            "customer_continent": _get_column(merged, "Customer Continent"),
            "customer_birthday": _get_column(merged, "Customer Birthday"),
            "store_country": _get_column(merged, "Store Country"),
            "store_state": _get_column(merged, "Store State"),
            "store_square_meters": _get_column(merged, "Store Square Meters"),
            "store_open_date": _get_column(merged, "Store Open Date"),
            "exchange_rate": _get_column(merged, "Exchange"),
        }
    )

    missing_required = [
        column for column in REQUIRED_COLUMNS if column not in unified.columns
    ]

    if missing_required:
        missing_text = ", ".join(missing_required)
        raise MultiTableLoaderError(
            "Unified orders table is missing analysis.py required column(s): "
            f"{missing_text}."
        )

    metadata = {
        "price_source": price_source,
        "unit_price_currency": "USD",
        "discount_policy": "No discount field exists in the Maven dataset; discount_rate is set to 0.",
        "returned_policy": "No returned field exists in the Maven dataset; returned is set to False.",
        "currency_policy": (
            "unit_price uses USD values. Exchange_Rates is preserved as "
            "exchange_rate for audit but is not applied to unit_price."
        ),
        "standard_columns": list(REQUIRED_COLUMNS)
        + ["customer_name", "product_name", "category"],
        "extension_columns": [
            column for column in unified.columns if column not in REQUIRED_COLUMNS
        ],
    }

    return unified, metadata


def load_multi_table_dataset(
    sales_source,
    products_source,
    customers_source=None,
    stores_source=None,
    exchange_rates_source=None,
):
    """Load Maven Global Electronics Retailer tables into one orders table.

    Parameters can be filesystem paths or file-like objects such as Streamlit
    UploadedFile instances. Sales and Products are required. Customers, Stores,
    and Exchange_Rates are optional. The function returns a dictionary with:
    unified_orders, merge_summary, quality_warnings, source_table_summary, and
    metadata.
    """
    if sales_source is None:
        raise MultiTableLoaderError("Sales.csv is required for multi-table mode.")

    if products_source is None:
        raise MultiTableLoaderError("Products.csv is required for multi-table mode.")

    quality_rows = []
    source_metadata = []
    merge_summary_rows = []

    sales, metadata = read_csv_with_encoding_fallback(sales_source, "Sales")
    source_metadata.append(metadata)
    products, metadata = read_csv_with_encoding_fallback(products_source, "Products")
    source_metadata.append(metadata)

    _validate_required_columns(sales, SALES_REQUIRED_COLUMNS, "Sales.csv")
    _validate_required_columns(products, PRODUCTS_REQUIRED_COLUMNS, "Products.csv")

    merged = sales.copy()
    merged, summary = _merge_many_to_one(
        merged,
        _prepare_products(products),
        ["ProductKey"],
        ["ProductKey"],
        "Products",
        quality_rows,
        display_left_keys=["Sales.ProductKey"],
        display_right_keys=["Products.ProductKey"],
    )
    merge_summary_rows.append(summary)

    if customers_source is not None:
        customers, metadata = read_csv_with_encoding_fallback(
            customers_source,
            "Customers",
        )
        source_metadata.append(metadata)
        _validate_required_columns(
            customers,
            CUSTOMERS_REQUIRED_COLUMNS,
            "Customers.csv",
        )
        merged, summary = _merge_many_to_one(
            merged,
            _prepare_customers(customers),
            ["CustomerKey"],
            ["CustomerKey"],
            "Customers",
            quality_rows,
            display_left_keys=["Sales.CustomerKey"],
            display_right_keys=["Customers.CustomerKey"],
        )
        merge_summary_rows.append(summary)
    else:
        merge_summary_rows.append(_skipped_merge_summary("Customers", "not_uploaded"))
        _add_quality_warning(
            quality_rows,
            "info",
            "optional_table_not_uploaded",
            "Customers",
            0,
            "Customers.csv was not uploaded; customer_name falls back to CustomerKey.",
        )

    if stores_source is not None:
        stores, metadata = read_csv_with_encoding_fallback(stores_source, "Stores")
        source_metadata.append(metadata)
        _validate_required_columns(stores, STORES_REQUIRED_COLUMNS, "Stores.csv")
        merged, summary = _merge_many_to_one(
            merged,
            _prepare_stores(stores),
            ["StoreKey"],
            ["StoreKey"],
            "Stores",
            quality_rows,
            display_left_keys=["Sales.StoreKey"],
            display_right_keys=["Stores.StoreKey"],
        )
        merge_summary_rows.append(summary)
    else:
        merge_summary_rows.append(_skipped_merge_summary("Stores", "not_uploaded"))
        _add_quality_warning(
            quality_rows,
            "info",
            "optional_table_not_uploaded",
            "Stores",
            0,
            "Stores.csv was not uploaded; store attributes are omitted.",
        )

    if exchange_rates_source is not None:
        exchange_rates, metadata = read_csv_with_encoding_fallback(
            exchange_rates_source,
            "Exchange_Rates",
        )
        source_metadata.append(metadata)
        _validate_required_columns(
            exchange_rates,
            EXCHANGE_RATES_REQUIRED_COLUMNS,
            "Exchange_Rates.csv",
        )
        merged["__order_date_key"] = pd.to_datetime(
            merged["Order Date"],
            errors="coerce",
            format="mixed",
        )
        merged, summary = _merge_many_to_one(
            merged,
            _prepare_exchange_rates(exchange_rates),
            ["__order_date_key", "Currency Code"],
            ["__exchange_date_key", "Currency"],
            "Exchange_Rates",
            quality_rows,
            right_columns=["Exchange"],
            display_left_keys=["Sales.Order Date", "Sales.Currency Code"],
            display_right_keys=["Exchange_Rates.Date", "Exchange_Rates.Currency"],
        )
        merged = merged.drop(
            columns=[
                column
                for column in ["__order_date_key", "__exchange_date_key", "Currency"]
                if column in merged.columns
            ]
        )
        merge_summary_rows.append(summary)
    else:
        merge_summary_rows.append(
            _skipped_merge_summary("Exchange_Rates", "not_uploaded")
        )
        _add_quality_warning(
            quality_rows,
            "info",
            "optional_table_not_uploaded",
            "Exchange_Rates",
            0,
            "Exchange_Rates.csv was not uploaded; exchange_rate is left missing.",
        )

    unified_orders, standardization_metadata = _standardize_orders(
        merged,
        quality_rows,
    )

    merge_summary = pd.DataFrame(
        merge_summary_rows,
        columns=MERGE_SUMMARY_COLUMNS,
    )
    quality_warnings = (
        pd.DataFrame(quality_rows, columns=QUALITY_WARNING_COLUMNS)
        if quality_rows
        else _make_empty_quality_warnings()
    )
    source_table_summary = _make_source_summary(source_metadata)

    metadata = {
        "dataset_name": "Maven Analytics Global Electronics Retailer",
        "sales_row_count": len(sales),
        "final_row_count": len(unified_orders),
        "required_columns_present": all(
            column in unified_orders.columns for column in REQUIRED_COLUMNS
        ),
        "line_item_key": ["Order Number", "Line Item"],
        "source_table_previews": {
            item["table_name"]: {
                "columns": item["columns"],
                "head": item["preview"],
            }
            for item in source_metadata
        },
    }
    metadata.update(standardization_metadata)

    return {
        "unified_orders": unified_orders,
        "merge_summary": merge_summary,
        "quality_warnings": quality_warnings,
        "source_table_summary": source_table_summary,
        "metadata": metadata,
    }
