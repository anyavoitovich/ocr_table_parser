import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

NO_DATA = "нет данных"
BASE_DIR = Path(__file__).resolve().parent
OCR_PATH = BASE_DIR / "input_data/ocr.json"
OUTPUT_DIR = BASE_DIR / "results"
OUTPUT_JSON_PATH = OUTPUT_DIR / "result_table.json"

TARGET_HEADERS = ["Position", "Quantity", "UOM", "Vendor name", "Model name", "Unit price"]

SOURCE_HEADERS = {
    "position": ["quote", "line", "no"],
    "quantity": ["ord", "qty"],
    "uom": ["ord", "uom"],
    "description": ["item", "description"],
    "price": ["price"],
}
SOURCE_ORDER = ["position", "quantity", "uom", "description", "price"]


def load_ocr(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("OCR JSON должен быть списком объектов")
    return data


def text(b: Dict[str, Any]) -> str:
    return str(b.get("content", "")).strip()


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def box_xyxy(b: Dict[str, Any]) -> Tuple[int, int, int, int]:
    x, y = int(b["x"]), int(b["y"])
    return x, y, x + int(b.get("w", 0)), y + int(b.get("h", 0))


def union(boxes: List[Dict[str, Any]]) -> Tuple[int, int, int, int]:
    return (
        min(box_xyxy(b)[0] for b in boxes),
        min(box_xyxy(b)[1] for b in boxes),
        max(box_xyxy(b)[2] for b in boxes),
        max(box_xyxy(b)[3] for b in boxes),
    )


def center_x(boxes: List[Dict[str, Any]]) -> float:
    x1, _, x2, _ = union(boxes)
    return (x1 + x2) / 2


def is_near_next(prev: Dict[str, Any], nxt: Dict[str, Any]) -> bool:
    px1, py1, px2, py2 = box_xyxy(prev)
    nx1, ny1, nx2, ny2 = box_xyxy(nxt)
    same_line = abs(ny1 - py1) <= 25 and nx1 >= px1 - 20
    next_line_same_col = 0 <= ny1 - py1 <= 90 and abs(nx1 - px1) <= 120
    next_line_right = 0 <= ny1 - py1 <= 90 and px1 - 40 <= nx1 <= px2 + 220
    return same_line or next_line_same_col or next_line_right


def find_phrase_candidates(ocr: List[Dict[str, Any]], tokens: List[str]) -> List[List[Dict[str, Any]]]:
    words = sorted([b for b in ocr if norm(text(b))], key=lambda b: (int(b["y"]), int(b["x"])))
    out: List[List[Dict[str, Any]]] = []

    def dfs(path: List[Dict[str, Any]], token_i: int) -> None:
        if token_i == len(tokens):
            out.append(path[:])
            return
        prev = path[-1]
        for b in words:
            if b in path:
                continue
            if norm(text(b)).rstrip(".") != tokens[token_i]:
                continue
            if not is_near_next(prev, b):
                continue

            test = path + [b]
            x1, y1, x2, y2 = union(test)
            if x2 - x1 <= 450 and y2 - y1 <= 140:
                dfs(test, token_i + 1)

    for b in words:
        if norm(text(b)).rstrip(".") == tokens[0]:
            if len(tokens) == 1:
                out.append([b])
            else:
                dfs([b], 1)

    def score(cand: List[Dict[str, Any]]) -> Tuple[int, int, int]:
        x1, y1, x2, y2 = union(cand)
        return (y2 - y1, x2 - x1, y1)

    return sorted(out, key=score)


def find_table_headers(ocr: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Ищет headers товарной таблицы.
    Выбирается группа headers, которая расположена в одной области документа
    и соответствует ожидаемому порядку колонок.
    """
    candidates = {name: find_phrase_candidates(ocr, phrase) for name, phrase in SOURCE_HEADERS.items()}
    missing = [name for name, values in candidates.items() if not values]
    if missing:
        raise ValueError(f"Не найдены header-фразы: {missing}")

    best: Optional[Tuple[int, Dict[str, List[Dict[str, Any]]]]] = None

    def rec(i: int, chosen: Dict[str, List[Dict[str, Any]]]) -> None:
        nonlocal best
        if i == len(SOURCE_ORDER):
            centers = [center_x(chosen[n]) for n in SOURCE_ORDER]
            if centers != sorted(centers):
                return
            all_boxes = [b for boxes in chosen.values() for b in boxes]
            x1, y1, x2, y2 = union(all_boxes)
            score = (y2 - y1) * 10000 + (x2 - x1)
            if best is None or score < best[0]:
                best = (score, {k: v[:] for k, v in chosen.items()})
            return
        name = SOURCE_ORDER[i]
        for cand in candidates[name][:20]:
            if chosen:
                current = [b for boxes in chosen.values() for b in boxes]
                _, cy1, _, cy2 = union(current)
                _, ny1, _, ny2 = union(cand)
                if max(cy2, ny2) - min(cy1, ny1) > 170:
                    continue
            chosen[name] = cand
            rec(i + 1, chosen)
            chosen.pop(name)

    rec(0, {})
    if best is None:
        raise ValueError("Header-колонки найдены по отдельности, но не собрались в одну строку таблицы")
    return best[1]


def make_source_columns(headers: Dict[str, List[Dict[str, Any]]], ocr: List[Dict[str, Any]]) -> Dict[str, Tuple[int, int]]:
    """
       Строит границы колонок по координатам найденных headers.
       Это позволяет не использовать фиксированные координаты таблицы.
    """
    centers = [center_x(headers[n]) for n in SOURCE_ORDER]
    left_gap = centers[1] - centers[0]
    right_gap = centers[-1] - centers[-2]
    boundaries = [int(centers[0] - left_gap / 2)]
    for a, b in zip(centers, centers[1:]):
        boundaries.append(int((a + b) / 2))
    boundaries.append(int(centers[-1] + right_gap / 2))

    cols = {name: (boundaries[i], boundaries[i + 1]) for i, name in enumerate(SOURCE_ORDER)}

    _, header_top, _, header_bottom = union([b for boxes in headers.values() for b in boxes])
    price_left, price_right = cols["price"]
    price_words = [b for b in ocr if int(b["y"]) > header_bottom and int(b["x"]) >= price_left - 30]
    if price_words:
        price_right = max(box_xyxy(b)[2] for b in price_words)
        cols["price"] = (price_left, price_right)
    return cols


def words_in_rect(ocr: List[Dict[str, Any]], x1: int, x2: int, y1: int, y2: int) -> List[Dict[str, Any]]:
    result = []
    for b in ocr:
        bx1, by1, bx2, by2 = box_xyxy(b)
        cx = (bx1 + bx2) / 2
        cy = (by1 + by2) / 2
        if x1 <= cx <= x2 and y1 <= cy <= y2:
            result.append(b)
    return sorted(result, key=lambda b: (int(b["y"]), int(b["x"])))


def join_words(boxes: List[Dict[str, Any]]) -> str:
    return " ".join(text(b) for b in boxes if text(b)).strip()


def is_int_value(s: str) -> bool:
    return bool(re.fullmatch(r"\d+", s.strip()))


def is_uom(s: str) -> bool:
    return s.strip().upper() in {"PC"}


def is_price(s: str) -> bool:
    s = s.strip()
    return bool(re.fullmatch(r"\d{1,3}(,\d{3})*(\.\d+)?|\d+(\.\d+)?", s))


def normalize_price(s: str) -> str:
    return s.strip().replace(",", "") or NO_DATA


def find_table_bottom(ocr: List[Dict[str, Any]], header_bottom: int) -> int:
    # Определяет конец товарной таблицы по блоку итогов (Quote Total).
    quote_total_y = []
    for b in ocr:
        if norm(text(b)) == "quote" and int(b["y"]) > header_bottom:
            same_line = words_in_rect(ocr, 0, 10_000, int(b["y"]) - 20, int(b["y"]) + 70)
            if any(norm(text(w)).startswith("total") for w in same_line):
                quote_total_y.append(int(b["y"]))
    return min(quote_total_y) if quote_total_y else max(box_xyxy(b)[3] for b in ocr)


def find_row_tops(ocr: List[Dict[str, Any]], cols: Dict[str, Tuple[int, int]], header_bottom: int, table_bottom: int) -> List[int]:
    #Находит начало каждой товарной строки по номерам позицийв первой колонке таблицы.
    pos_x1, pos_x2 = cols["position"]
    tops = []
    for b in ocr:
        if header_bottom < int(b["y"]) < table_bottom and is_int_value(text(b)):
            bx1, by1, bx2, by2 = box_xyxy(b)
            cx = (bx1 + bx2) / 2
            if pos_x1 <= cx <= pos_x2:
                tops.append(by1 - 10)
    return sorted(set(tops))


def first_matching_text(ocr: List[Dict[str, Any]], x_range: Tuple[int, int], y1: int, y2: int, predicate) -> str:
    boxes = words_in_rect(ocr, x_range[0], x_range[1], y1, y2)
    values = [text(b) for b in boxes if predicate(text(b))]
    return values[0] if values else NO_DATA


def parse_description(description: str) -> Tuple[str, str]:
    if not description or description == NO_DATA:
        return NO_DATA, NO_DATA
    before_memory = re.split(r"\b\d+\s*/\s*\d+\b", description, maxsplit=1)[0].strip()
    parts = before_memory.split(maxsplit=1)
    vendor = parts[0] if parts else NO_DATA
    model = parts[1] if len(parts) > 1 else NO_DATA
    return vendor, model


def extract_unit_price(ocr: List[Dict[str, Any]], price_range: Tuple[int, int], y1: int, y2: int, ) -> str:
    # Извлекает цену товара из блока Price. Используется значение после "Unit Price".
    boxes = words_in_rect(ocr, price_range[0], price_range[1], y1, y2)

    boxes = sorted(boxes, key=lambda b: (int(b["y"]), int(b["x"])))

    for i in range(len(boxes) - 2):
        current = norm(text(boxes[i]))
        next_word = norm(text(boxes[i + 1]))

        if current == "unit" and next_word == "price":
            unit_box = boxes[i]
            price_box = boxes[i + 1]

            _, unit_y1, _, unit_y2 = box_xyxy(unit_box)
            _, price_y1, price_x2, price_y2 = box_xyxy(price_box)

            unit_line_y1 = min(unit_y1, price_y1) - 15
            unit_line_y2 = max(unit_y2, price_y2) + 15

            candidates = []
            for b in boxes[i + 2:]:
                bx1, by1, bx2, by2 = box_xyxy(b)
                cy = (by1 + by2) / 2

                if unit_line_y1 <= cy <= unit_line_y2 and bx1 >= price_x2:
                    if is_price(text(b)):
                        candidates.append(b)

            if candidates:
                candidates = sorted(candidates, key=lambda b: int(b["x"]))
                return normalize_price(text(candidates[0]))

    return NO_DATA

def make_cell(x: int, y: int, w: int, h: int, content: str, column_id: int, row_id: int, is_header: bool) -> Dict[str, Any]:
    return {
        "x": int(x), "y": int(y), "w": int(w), "h": int(h),
        "content": content, "column_id": column_id, "row_id": row_id,
        "is_header": is_header,
    }


def build_target_columns(cols: Dict[str, Tuple[int, int]], row_text_boxes: List[List[Dict[str, Any]]]) -> List[Tuple[int, int]]:
    #Формирует итоговые колонки JSON.
    desc_x1, desc_x2 = cols["description"]
    splits = []
    for boxes in row_text_boxes:
        if len(boxes) >= 2:
            splits.append(int((box_xyxy(boxes[0])[2] + box_xyxy(boxes[1])[0]) / 2))
    vendor_x2 = int(sum(splits) / len(splits)) if splits else int(desc_x1 + (desc_x2 - desc_x1) * 0.35)
    return [cols["position"], cols["quantity"], cols["uom"], (desc_x1, vendor_x2), (vendor_x2, desc_x2), cols["price"]]


def build_table(ocr: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    headers = find_table_headers(ocr)
    cols = make_source_columns(headers, ocr)
    _, header_top, _, header_bottom = union([b for boxes in headers.values() for b in boxes])
    header_top -= 10
    header_bottom += 10
    table_bottom = find_table_bottom(ocr, header_bottom)
    row_tops = find_row_tops(ocr, cols, header_bottom, table_bottom)

    desc_boxes_by_row = []
    for i, row_top in enumerate(row_tops):
        row_bottom = row_tops[i + 1] if i + 1 < len(row_tops) else table_bottom
        desc_boxes_by_row.append(words_in_rect(ocr, cols["description"][0], cols["description"][1], row_top, min(row_top + 90, row_bottom)))
    target_cols = build_target_columns(cols, desc_boxes_by_row)

    result: List[Dict[str, Any]] = []
    for col_id, header in enumerate(TARGET_HEADERS):
        x1, x2 = target_cols[col_id]
        result.append(make_cell(x1, header_top, x2 - x1, header_bottom - header_top, header, col_id, 0, True))

    for i, row_top in enumerate(row_tops):
        row_id = i + 1
        row_bottom = row_tops[i + 1] if i + 1 < len(row_tops) else table_bottom
        position = first_matching_text(ocr, cols["position"], row_top, row_bottom, is_int_value)
        quantity = first_matching_text(ocr, cols["quantity"], row_top, row_bottom, is_int_value)
        uom = first_matching_text(ocr, cols["uom"], row_top, row_bottom, is_uom)
        description = join_words(words_in_rect(ocr, cols["description"][0], cols["description"][1], row_top, min(row_top + 90, row_bottom)))
        vendor, model = parse_description(description)
        unit_price = extract_unit_price(ocr, cols["price"], row_top, row_bottom)
        for col_id, value in enumerate([position, quantity, uom, vendor, model, unit_price]):
            x1, x2 = target_cols[col_id]
            result.append(make_cell(x1, row_top, x2 - x1, row_bottom - row_top, value, col_id, row_id, False))
    return result



def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    ocr = load_ocr(OCR_PATH)
    cells = build_table(ocr)

    OUTPUT_JSON_PATH.write_text(json.dumps(cells, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"JSON: {OUTPUT_JSON_PATH}")
    print(f"Ячеек: {len(cells)}")


if __name__ == "__main__":
    main()
