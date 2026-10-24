import csv
import io
import re


def analyze_csv(csv_content: str) -> dict:
    result = {
        "total_rows": 0,
        "missing_required_fields": [],
        "duplicate_ids": [],
        "invalid_emails": [],
        "error": None,
    }

    if not csv_content or not csv_content.strip():
        return result

    required_headers = {"id", "name", "email"}
    id_rows = {}

    try:
        reader = csv.DictReader(
            io.StringIO(csv_content, newline=""),
            strict=True,
        )

        headers = reader.fieldnames

        if not headers:
            result["error"] = "Malformed CSV: missing header row"
            return result

        normalized_headers = [
            header.strip() if header is not None else ""
            for header in headers
        ]

        missing_columns = sorted(
            required_headers - set(normalized_headers)
        )

        if missing_columns:
            result["error"] = (
                "Missing required columns: "
                + ", ".join(missing_columns)
            )
            return result

        for row_number, row in enumerate(reader, start=2):
            result["total_rows"] += 1

            # Detect rows containing more values than the header defines.
            if None in row:
                result["error"] = (
                    f"Malformed CSV: too many fields on row {row_number}"
                )
                return result

            missing_fields = [
                field
                for field in ("id", "name", "email")
                if row.get(field) is None or not row[field].strip()
            ]

            if missing_fields:
                result["missing_required_fields"].append({
                    "row_number": row_number,
                    "missing_fields": missing_fields,
                })

            record_id = row.get("id", "").strip()

            if record_id:
                id_rows.setdefault(record_id, []).append(row_number)

            email = row.get("email", "").strip()

            if email and not re.fullmatch(
                r"[^@\s]+@[^@\s]+\.[^@\s]+",
                email,
            ):
                result["invalid_emails"].append({
                    "row_number": row_number,
                    "invalid_email": email,
                })

        result["duplicate_ids"] = [
            {"id": record_id, "rows": rows}
            for record_id, rows in id_rows.items()
            if len(rows) > 1
        ]

    except csv.Error as exc:
        result["error"] = f"Malformed CSV: {exc}"

    return result
