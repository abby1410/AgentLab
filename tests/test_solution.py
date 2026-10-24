import sys
from pathlib import Path

# Add the workspace directory so tests can import solution.py
PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_DIR = PROJECT_ROOT / "workspace"
sys.path.insert(0, str(WORKSPACE_DIR))

from solution import analyze_csv


def test_valid_csv():
    csv_data = (
        "id,name,email\n"
        "1,Alice,alice@example.com\n"
        "2,Bob,bob@example.com\n"
    )
    result = analyze_csv(csv_data)

    assert result["total_rows"] == 2
    assert result["missing_required_fields"] == []
    assert result["duplicate_ids"] == []
    assert result["invalid_emails"] == []


def test_missing_required_fields():
    csv_data = "id,name,email\n1,,alice@example.com\n"
    result = analyze_csv(csv_data)

    assert result["missing_required_fields"]


def test_duplicate_ids():
    csv_data = (
        "id,name,email\n"
        "1,Alice,alice@example.com\n"
        "1,Bob,bob@example.com\n"
    )
    result = analyze_csv(csv_data)

    assert result["duplicate_ids"]


def test_invalid_emails():
    csv_data = "id,name,email\n1,Alice,not-an-email\n"
    result = analyze_csv(csv_data)

    assert result["invalid_emails"]


def test_empty_input():
    result = analyze_csv("")

    assert isinstance(result, dict)
    assert result["total_rows"] == 0


def test_missing_required_columns():
    csv_data = "id,name\n1,Alice\n"
    result = analyze_csv(csv_data)

    assert result.get("error") or result.get("missing_columns")


def test_result_is_json_serializable():
    import json

    result = analyze_csv("id,name,email\n1,Alice,alice@example.com\n")
    json.dumps(result)


def test_malformed_csv_returns_error():
    csv_data = 'id,name,email\n1,"Alice,alice@example.com\n'
    result = analyze_csv(csv_data)

    assert result.get("error")
