from io import BytesIO
from pathlib import Path
import sys
import unittest

import pandas as pd
from pandas.api.types import is_bool_dtype, is_numeric_dtype


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from analysis import REQUIRED_COLUMNS
from multi_table_loader import MultiTableLoaderError, load_multi_table_dataset


DATASET_DIR = PROJECT_DIR / "Global+Electronics+Retailer"


def dataset_file(file_name):
    """Return one Maven dataset CSV path."""
    return DATASET_DIR / file_name


def file_like(file_name):
    """Return a file-like CSV object for upload-style tests."""
    uploaded = BytesIO(dataset_file(file_name).read_bytes())
    uploaded.name = file_name

    return uploaded


def upload_csv(csv_text, file_name="uploaded.csv"):
    """Return a named BytesIO object for small synthetic CSV tests."""
    uploaded = BytesIO(csv_text.encode("utf-8"))
    uploaded.name = file_name

    return uploaded


def minimal_sales_csv(quantity="2", product_key="100"):
    """Create the smallest Sales.csv fixture needed by the loader."""
    return (
        "Order Number,Line Item,Order Date,Delivery Date,CustomerKey,"
        "StoreKey,ProductKey,Quantity,Currency Code\n"
        f"1,1,1/1/2020,,10,1,{product_key},{quantity},USD\n"
    )


def minimal_products_csv(price="$10.00", product_key="100"):
    """Create the smallest Products.csv fixture needed by the loader."""
    return (
        "ProductKey,Product Name,Unit Price USD,Category\n"
        f"{product_key},Product A,{price},Audio\n"
    )


class MultiTableLoaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.full_result = load_multi_table_dataset(
            sales_source=dataset_file("Sales.csv"),
            products_source=dataset_file("Products.csv"),
            customers_source=dataset_file("Customers.csv"),
            stores_source=dataset_file("Stores.csv"),
            exchange_rates_source=dataset_file("Exchange_Rates.csv"),
        )
        cls.sales_products_result = load_multi_table_dataset(
            sales_source=dataset_file("Sales.csv"),
            products_source=dataset_file("Products.csv"),
        )

    def test_full_five_table_dataset_loads_successfully(self):
        source_summary = self.full_result["source_table_summary"]

        self.assertEqual(
            set(source_summary["table_name"]),
            {"Sales", "Products", "Customers", "Stores", "Exchange_Rates"},
        )
        self.assertTrue(self.full_result["quality_warnings"].empty)

    def test_sales_products_only_mode_succeeds(self):
        result = self.sales_products_result

        self.assertEqual(len(result["unified_orders"]), 62884)
        self.assertEqual(
            set(
                result["merge_summary"].loc[
                    result["merge_summary"]["status"] == "not_uploaded",
                    "right_table",
                ]
            ),
            {"Customers", "Stores", "Exchange_Rates"},
        )

    def test_missing_customers_falls_back_customer_name_to_customer_key(self):
        orders = self.sales_products_result["unified_orders"]

        self.assertTrue(
            (orders["customer_name"] == orders["customer_id"].astype("string")).all()
        )

    def test_missing_stores_leaves_store_extension_fields_empty(self):
        orders = self.sales_products_result["unified_orders"]

        for column in [
            "store_country",
            "store_state",
            "store_square_meters",
            "store_open_date",
        ]:
            self.assertTrue(orders[column].isna().all(), column)

    def test_missing_exchange_rates_leaves_exchange_rate_empty_but_loads(self):
        orders = self.sales_products_result["unified_orders"]

        self.assertEqual(len(orders), 62884)
        self.assertTrue(orders["exchange_rate"].isna().all())

    def test_missing_products_source_raises_error(self):
        with self.assertRaisesRegex(MultiTableLoaderError, "Products.csv is required"):
            load_multi_table_dataset(
                sales_source=dataset_file("Sales.csv"),
                products_source=None,
            )

    def test_products_missing_product_key_raises_error(self):
        products_csv = "Product Name,Unit Price USD,Category\nProduct A,$10.00,Audio\n"

        with self.assertRaisesRegex(MultiTableLoaderError, "ProductKey"):
            load_multi_table_dataset(
                sales_source=upload_csv(minimal_sales_csv(), "Sales.csv"),
                products_source=upload_csv(products_csv, "Products.csv"),
            )

    def test_products_missing_unit_price_usd_raises_error(self):
        products_csv = "ProductKey,Product Name,Category\n100,Product A,Audio\n"

        with self.assertRaisesRegex(MultiTableLoaderError, "Unit Price USD"):
            load_multi_table_dataset(
                sales_source=upload_csv(minimal_sales_csv(), "Sales.csv"),
                products_source=upload_csv(products_csv, "Products.csv"),
            )

    def test_duplicate_product_key_raises_error(self):
        products_csv = (
            "ProductKey,Product Name,Unit Price USD,Category\n"
            "100,Product A,$10.00,Audio\n"
            "100,Product A Duplicate,$12.00,Audio\n"
        )

        with self.assertRaisesRegex(MultiTableLoaderError, "cannot be merged safely"):
            load_multi_table_dataset(
                sales_source=upload_csv(minimal_sales_csv(), "Sales.csv"),
                products_source=upload_csv(products_csv, "Products.csv"),
            )

    def test_duplicate_exchange_rate_date_currency_raises_error(self):
        exchange_rates_csv = (
            "Date,Currency,Exchange\n"
            "1/1/2020,USD,1.0\n"
            "1/1/2020,USD,1.1\n"
        )

        with self.assertRaisesRegex(MultiTableLoaderError, "Exchange_Rates"):
            load_multi_table_dataset(
                sales_source=upload_csv(minimal_sales_csv(), "Sales.csv"),
                products_source=upload_csv(minimal_products_csv(), "Products.csv"),
                exchange_rates_source=upload_csv(
                    exchange_rates_csv,
                    "Exchange_Rates.csv",
                ),
            )

    def test_sales_missing_required_merge_key_raises_error(self):
        sales_csv = (
            "Order Number,Line Item,Order Date,Delivery Date,CustomerKey,"
            "StoreKey,Quantity,Currency Code\n"
            "1,1,1/1/2020,,10,1,2,USD\n"
        )

        with self.assertRaisesRegex(MultiTableLoaderError, "ProductKey"):
            load_multi_table_dataset(
                sales_source=upload_csv(sales_csv, "Sales.csv"),
                products_source=upload_csv(minimal_products_csv(), "Products.csv"),
            )

    def test_unconvertible_product_price_creates_quality_warning(self):
        result = load_multi_table_dataset(
            sales_source=upload_csv(minimal_sales_csv(), "Sales.csv"),
            products_source=upload_csv(
                minimal_products_csv(price="not-a-price"),
                "Products.csv",
            ),
        )

        warnings = result["quality_warnings"]
        self.assertIn("price_conversion_failed_count", set(warnings["check_name"]))
        self.assertTrue(pd.isna(result["unified_orders"].loc[0, "unit_price"]))

    def test_unconvertible_sales_quantity_creates_quality_warning(self):
        result = load_multi_table_dataset(
            sales_source=upload_csv(
                minimal_sales_csv(quantity="not-a-number"),
                "Sales.csv",
            ),
            products_source=upload_csv(minimal_products_csv(), "Products.csv"),
        )

        warnings = result["quality_warnings"]
        self.assertIn("quantity_conversion_failed_count", set(warnings["check_name"]))
        self.assertTrue(pd.isna(result["unified_orders"].loc[0, "quantity"]))

    def test_money_string_with_comma_converts_to_numeric_value(self):
        result = load_multi_table_dataset(
            sales_source=upload_csv(minimal_sales_csv(), "Sales.csv"),
            products_source=upload_csv(
                minimal_products_csv(price='"$1,299.99"'),
                "Products.csv",
            ),
        )

        self.assertEqual(result["unified_orders"].loc[0, "unit_price"], 1299.99)

    def test_cp1252_customer_file_is_supported(self):
        source_summary = self.full_result["source_table_summary"]
        customer_encoding = source_summary.loc[
            source_summary["table_name"] == "Customers",
            "encoding",
        ].iloc[0]

        self.assertEqual(customer_encoding, "cp1252")

    def test_file_path_inputs_are_supported(self):
        result = load_multi_table_dataset(
            sales_source=dataset_file("Sales.csv"),
            products_source=dataset_file("Products.csv"),
        )

        self.assertEqual(len(result["unified_orders"]), 62884)

    def test_file_like_inputs_are_supported(self):
        result = load_multi_table_dataset(
            sales_source=file_like("Sales.csv"),
            products_source=file_like("Products.csv"),
        )

        self.assertEqual(len(result["unified_orders"]), 62884)

    def test_full_dataset_preserves_62884_rows(self):
        self.assertEqual(len(self.full_result["unified_orders"]), 62884)

    def test_unified_orders_contains_all_required_columns(self):
        columns = set(self.full_result["unified_orders"].columns)

        self.assertTrue(set(REQUIRED_COLUMNS).issubset(columns))

    def test_unit_price_is_numeric_dtype(self):
        self.assertTrue(is_numeric_dtype(self.full_result["unified_orders"]["unit_price"]))

    def test_quantity_is_numeric_dtype(self):
        self.assertTrue(is_numeric_dtype(self.full_result["unified_orders"]["quantity"]))

    def test_discount_rate_is_numeric_zero_for_all_rows(self):
        discount_rate = self.full_result["unified_orders"]["discount_rate"]

        self.assertTrue(is_numeric_dtype(discount_rate))
        self.assertTrue((discount_rate == 0).all())

    def test_returned_is_boolean_false_for_all_rows(self):
        returned = self.full_result["unified_orders"]["returned"]

        self.assertTrue(is_bool_dtype(returned))
        self.assertTrue((returned == False).all())  # noqa: E712
        self.assertFalse(returned.map(lambda value: isinstance(value, str)).any())

    def test_all_merges_have_no_row_inflation(self):
        merged_rows = self.full_result["merge_summary"]

        self.assertFalse(merged_rows["row_inflation"].any())

    def test_all_full_dataset_match_rates_are_100_percent(self):
        merged_rows = self.full_result["merge_summary"]

        self.assertTrue((merged_rows["match_rate"] == 1.0).all())


if __name__ == "__main__":
    unittest.main()
