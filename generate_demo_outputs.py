from analysis import run_pipeline


DEMO_CASES = [
    {
        "name": "clean_case",
        "input": "sample_data/clean_case/input/orders.csv",
        "expenses": "sample_data/clean_case/input/expenses.csv",
        "excel": "sample_data/clean_case/output/sales_report.xlsx",
        "summary": "sample_data/clean_case/output/summary.md",
        "config": None,
    },
    {
        "name": "quality_issues_case",
        "input": "sample_data/quality_issues_case/input/orders.csv",
        "expenses": "sample_data/quality_issues_case/input/expenses.csv",
        "excel": "sample_data/quality_issues_case/output/sales_report.xlsx",
        "summary": "sample_data/quality_issues_case/output/summary.md",
        "config": None,
    },
    {
        "name": "mapped_columns_case",
        "input": "sample_data/mapped_columns_case/input/orders_chinese.csv",
        "expenses": "sample_data/mapped_columns_case/input/expenses_chinese.csv",
        "excel": "sample_data/mapped_columns_case/output/sales_report.xlsx",
        "summary": "sample_data/mapped_columns_case/output/summary.md",
        "config": "sample_data/mapped_columns_case/config.json",
    },
]


def generate_demo_outputs():
    """Generate Excel and Markdown outputs for all demo cases."""
    generated_outputs = []

    for case in DEMO_CASES:
        print(f"Generating demo output for {case['name']}...")
        _, excel_output, summary_output = run_pipeline(
            csv_path=case["input"],
            expenses_path=case["expenses"],
            excel_path=case["excel"],
            summary_path=case["summary"],
            config_path=case["config"],
        )
        generated_outputs.append((case["name"], excel_output, summary_output))

    return generated_outputs


if __name__ == "__main__":
    outputs = generate_demo_outputs()

    print()
    print("Demo outputs generated:")
    for case_name, excel_output, summary_output in outputs:
        print(f"- {case_name}:")
        print(f"  Excel: {excel_output}")
        print(f"  Summary: {summary_output}")
