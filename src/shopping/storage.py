"""
Google Sheets への保存・読み込み・削除。

Streamlit に依存しない。スプレッドシートは呼び出し側で開いて渡す。

保存データは3シートで管理し、save_id を共通キーにする。
    saved_data : 保存パターンの一覧
    products   : 保存パターンごとの商品データ
    settings   : 保存パターンごとの設定値
"""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread

from shopping.calc import MAX_PRODUCTS

SAVED_DATA_SHEET = "saved_data"
PRODUCTS_SHEET = "products"
SETTINGS_SHEET = "settings"

SAVED_DATA_HEADERS = ["save_id", "name", "saved_at"]
PRODUCT_HEADERS = ["save_id", "name", "ap", "apt", "baby", "rp", "rpt", "rurl"]
SETTING_HEADERS = ["save_id", "setting", "value"]

SETTING_DEFAULTS = {"max_shops": 10, "min_shop_price": 1000, "bonus_cap": 7000, "spu_multiplier": 0}

MAX_SAVE_NAME_LENGTH = 50

JST = ZoneInfo("Asia/Tokyo")


# ===========================================================================
# 値の変換
# ===========================================================================


def safe_int(value, default=0):
    """Google Sheetsから取得した値を安全に整数へ変換する。"""

    try:
        if value is None or str(value).strip() == "":
            return int(default)
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def normalize_bool(value):
    if isinstance(value, bool):
        return value

    return str(value).strip().lower() in {"true", "1", "yes", "on"}


def make_default_product():
    """新規商品の初期値。"""

    return {"name": "", "ap": 0, "apt": 1, "baby": False, "rp": 0, "rpt": 0, "rurl": ""}


# ===========================================================================
# シートの値 → データ
# ===========================================================================


def _column_reader(values, headers):
    """見出し行から列の位置を探し、行から列名で値を読む関数を返す。見出しが合わなければ None。"""

    if not values:
        return None

    header = [str(x).strip() for x in values[0]]

    try:
        indexes = {name: header.index(name) for name in headers}
    except ValueError:
        return None

    def cell(row, name):
        idx = indexes[name]
        return row[idx] if idx < len(row) else ""

    return cell


def parse_saved_data(values):
    """saved_data シートの値から保存パターン一覧を作る。"""

    cell = _column_reader(values, SAVED_DATA_HEADERS)

    if cell is None:
        return []

    records = []

    for row in values[1:]:
        save_id = str(cell(row, "save_id")).strip()
        name = str(cell(row, "name")).strip()

        if not save_id or not name:
            continue

        records.append(
            {"save_id": save_id, "name": name, "saved_at": str(cell(row, "saved_at")).strip()}
        )

    return records


def parse_products(values, save_id):
    """products シートの値から、指定 save_id の商品リストを作る。"""

    cell = _column_reader(values, PRODUCT_HEADERS)

    if cell is None:
        return []

    products = []

    for row in values[1:]:
        if str(cell(row, "save_id")).strip() != save_id:
            continue

        if not any(str(cell(row, name)).strip() for name in PRODUCT_HEADERS[1:]):
            continue

        products.append(
            {
                "name": str(cell(row, "name")),
                "ap": safe_int(cell(row, "ap")),
                "apt": safe_int(cell(row, "apt"), 1),
                "baby": normalize_bool(cell(row, "baby")),
                "rp": safe_int(cell(row, "rp")),
                "rpt": safe_int(cell(row, "rpt")),
                "rurl": str(cell(row, "rurl")),
            }
        )

    return products


def parse_settings(values, save_id):
    """settings シートの値から、指定 save_id の設定を作る。"""

    settings = dict(SETTING_DEFAULTS)
    cell = _column_reader(values, SETTING_HEADERS)

    if cell is None:
        return settings

    for row in values[1:]:
        if str(cell(row, "save_id")).strip() != save_id:
            continue

        key = str(cell(row, "setting")).strip()

        if key in SETTING_DEFAULTS:
            settings[key] = safe_int(cell(row, "value"), SETTING_DEFAULTS[key])

    return settings


# ===========================================================================
# データ → シートの値
# ===========================================================================


def product_rows(save_id, products):
    return [
        [
            save_id,
            str(item.get("name", "")),
            safe_int(item.get("ap", 0)),
            safe_int(item.get("apt", 1), 1),
            bool(item.get("baby", False)),
            safe_int(item.get("rp", 0)),
            safe_int(item.get("rpt", 0)),
            str(item.get("rurl", "")),
        ]
        for item in products
    ]


def setting_rows(save_id, settings):
    return [
        [save_id, key, safe_int(settings.get(key), default)]
        for key, default in SETTING_DEFAULTS.items()
    ]


def replace_rows(values, headers, save_id, new_rows):
    """
    シートの値のうち save_id の行を new_rows に置き換えた、シート全体の値を返す。

    元より行数が減る場合は空行で埋めて同じ行数にする。
    1回の update で書き切ることで、途中で失敗しても元のデータが残る。
    """

    width = len(headers)

    if not values or not any(str(x).strip() for x in values[0]):
        return [list(headers)] + [list(r) for r in new_rows]

    header = [str(x).strip() for x in values[0]]

    while header and header[-1] == "":
        header.pop()

    if header != headers:
        raise ValueError(
            f"シートの見出し行が想定と違うため、書き込みを中止しました（想定: {', '.join(headers)}）"
        )

    kept = []
    insert_at = None

    for row in values[1:]:
        row = (list(row) + [""] * width)[:width]

        if str(row[0]).strip() == save_id:
            if insert_at is None:
                insert_at = len(kept)
            continue

        if not any(str(x).strip() for x in row):
            continue

        kept.append(row)

    if insert_at is None:
        insert_at = len(kept)

    result = [list(headers)] + kept[:insert_at] + [list(r) for r in new_rows] + kept[insert_at:]

    result += [[""] * width for _ in range(len(values) - len(result))]

    return result


# ===========================================================================
# Google Sheets への読み書き
# ===========================================================================


class SheetStorage:
    """保存データを Google Sheets に読み書きする。"""

    def __init__(self, spreadsheet, clock=None):
        self.spreadsheet = spreadsheet
        self.clock = clock or (lambda: datetime.now(JST))

    def _worksheet(self, title, cols):
        try:
            return self.spreadsheet.worksheet(title)
        except gspread.WorksheetNotFound:
            return self.spreadsheet.add_worksheet(title=title, rows=100, cols=cols)

    def _read(self, title, headers):
        ws = self._worksheet(title, len(headers))
        return ws, ws.get_all_values()

    def _write_rows(self, title, headers, save_id, new_rows):
        ws, values = self._read(title, headers)
        result = replace_rows(values, headers, save_id, new_rows)

        rows = max(int(ws.row_count), len(result))
        cols = max(int(ws.col_count), len(headers))

        if rows > ws.row_count or cols > ws.col_count:
            ws.resize(rows=rows, cols=cols)

        ws.update(values=result, range_name="A1", value_input_option="RAW")

    def list_saved(self):
        _, values = self._read(SAVED_DATA_SHEET, SAVED_DATA_HEADERS)
        return parse_saved_data(values)

    def save(self, save_name, products, settings, overwrite_save_id=None):
        save_name = str(save_name).strip()

        if not save_name:
            raise ValueError("保存名を入力してください。")

        if len(save_name) > MAX_SAVE_NAME_LENGTH:
            raise ValueError(f"保存名は{MAX_SAVE_NAME_LENGTH}文字以内で入力してください。")

        save_id = overwrite_save_id

        if not save_id:
            same_name = [r for r in self.list_saved() if r["name"] == save_name]
            save_id = same_name[0]["save_id"] if same_name else uuid.uuid4().hex

        saved_at = self.clock().strftime("%Y-%m-%d %H:%M:%S")

        # 一覧は最後に書く。途中で失敗しても、中身の無い保存データが一覧に載らない。
        self._write_rows(PRODUCTS_SHEET, PRODUCT_HEADERS, save_id, product_rows(save_id, products))
        self._write_rows(SETTINGS_SHEET, SETTING_HEADERS, save_id, setting_rows(save_id, settings))
        self._write_rows(
            SAVED_DATA_SHEET, SAVED_DATA_HEADERS, save_id, [[save_id, save_name, saved_at]]
        )

        return save_id, save_name

    def load(self, save_id):
        if not save_id:
            raise ValueError("読み込む保存データを選択してください。")

        record = next((r for r in self.list_saved() if r["save_id"] == save_id), None)

        if record is None:
            raise ValueError("指定された保存データが見つかりません。")

        _, product_values = self._read(PRODUCTS_SHEET, PRODUCT_HEADERS)
        products = parse_products(product_values, save_id)

        if len(products) > MAX_PRODUCTS:
            raise ValueError(
                f"保存データの商品が{len(products)}個あり、上限の{MAX_PRODUCTS}個を超えています。"
            )

        if not products:
            products = [make_default_product()]

        _, setting_values = self._read(SETTINGS_SHEET, SETTING_HEADERS)

        return record, products, parse_settings(setting_values, save_id)

    def delete(self, save_id):
        if not save_id:
            raise ValueError("削除する保存データを選択してください。")

        records = self.list_saved()

        if not any(r["save_id"] == save_id for r in records):
            raise ValueError("削除する保存データが見つかりません。")

        # 一覧から先に消す。途中で失敗しても、一覧に載った中身の無いデータは残らない。
        self._write_rows(SAVED_DATA_SHEET, SAVED_DATA_HEADERS, save_id, [])
        self._write_rows(PRODUCTS_SHEET, PRODUCT_HEADERS, save_id, [])
        self._write_rows(SETTINGS_SHEET, SETTING_HEADERS, save_id, [])

        return [r for r in records if r["save_id"] != save_id]
