# OCR Table Parser

Extracts purchased items from OCR results and saves them as JSON.

## Run locally

```bash
python table_parser.py
python validate_result.py
```

## Run with Docker

```bash
docker build -t ocr-table-parser .
docker run --rm -v "$(pwd)/results:/app/results" ocr-table-parser
```

Output files:

```text
results/result_table.json
results/check_result.json
```