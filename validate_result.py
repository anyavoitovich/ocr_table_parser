import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple


BASE_DIR = Path(__file__).resolve().parent

CSV_PATH = BASE_DIR / "input_data/samsung.csv"
OUTPUT_DIR = BASE_DIR / "results"
RESULT_JSON_PATH = OUTPUT_DIR / "result_table.json"
CHECK_JSON_PATH = OUTPUT_DIR / "check_result.json"

def load_csv(path: Path) -> Tuple[List[str], List[List[str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = [
            [cell.strip() for cell in row if cell.strip()]
            for row in csv.reader(f, delimiter=";")
        ]

    if not rows:
        raise ValueError("CSV пустой")

    return rows[0], rows[1:]


def load_result_json(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("result_table.json должен быть списком ячеек")

    return data


def table_from_json_cells(cells: List[Dict[str, Any]]) -> List[List[str]]: #Собирает обычную таблицу из JSON-ячеек.

    max_row = max(cell["row_id"] for cell in cells)
    max_col = max(cell["column_id"] for cell in cells)

    table = [
        ["" for _ in range(max_col + 1)]
        for _ in range(max_row + 1)
    ]

    for cell in cells:
        row_id = cell["row_id"]
        column_id = cell["column_id"]
        table[row_id][column_id] = str(cell["content"]).strip()

    return table


def validate_against_csv(cells: List[Dict[str, Any]], csv_headers: List[str], csv_rows: List[List[str]],) -> Dict[str, Any]:
    #Сравнивает результат парсинга с эталонным CSV.

    actual_table = table_from_json_cells(cells)
    expected_table = [csv_headers] + csv_rows

    passed = actual_table == expected_table

    errors = []

    max_len = max(len(actual_table), len(expected_table))

    for i in range(max_len):
        actual_row = actual_table[i] if i < len(actual_table) else None
        expected_row = expected_table[i] if i < len(expected_table) else None

        if actual_row != expected_row:
            errors.append({
                "row": i,
                "expected": expected_row,
                "actual": actual_row,
            })

    return {
        "passed": passed,
        "expected_table": expected_table,
        "actual_table": actual_table,
        "errors": errors,
    }


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    csv_headers, csv_rows = load_csv(CSV_PATH)
    cells = load_result_json(RESULT_JSON_PATH)

    check = validate_against_csv(cells, csv_headers, csv_rows)

    CHECK_JSON_PATH.write_text(
        json.dumps(check, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"Проверка: {'PASSED' if check['passed'] else 'FAILED'}")
    print(f"Файл проверки: {CHECK_JSON_PATH}")

    if check["errors"]:
        print("Ошибки:")
        for error in check["errors"]:
            print(error)


if __name__ == "__main__":
    main()