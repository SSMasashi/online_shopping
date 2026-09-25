"""
src/shopping/storage.py のテスト。

Google Sheets への保存・読み込み・削除を、実際のGoogle Sheetsに接続せずに
テストするため、gspreadのSpreadsheet/Worksheet互換のフェイクを使う。

実装はまだ存在しないか書きかけの可能性があるため、CLAUDE.mdで示された仕様を
正としてテストを先に書く（テスト駆動開発）。特に、リファクタリング前の実装が
持っていた次の不具合が再発しないことを重点的に確認する。

    - 全件を ws.clear() してから書き直すためデータが消えうる
    - value_input_option="USER_ENTERED" で商品名が数式として実行される
    - 見出しが違うと他の保存データを捨てる
"""

import datetime

import pytest
from fakes import FakeSpreadsheet, FakeWorksheet

from shopping.calc import MAX_PRODUCTS
from shopping.storage import (
    MAX_SAVE_NAME_LENGTH,
    PRODUCT_HEADERS,
    PRODUCTS_SHEET,
    SAVED_DATA_HEADERS,
    SAVED_DATA_SHEET,
    SETTING_DEFAULTS,
    SETTING_HEADERS,
    SETTINGS_SHEET,
    SheetStorage,
    make_default_product,
    normalize_bool,
    parse_products,
    parse_saved_data,
    parse_settings,
    replace_rows,
    safe_int,
)

# ===========================================================================
# テスト用ヘルパー
# ===========================================================================


def make_product(
    name="商品", ap=1000, apt=1, baby=False, rp=1000, rpt=1, rurl="https://example.com"
):
    """save() に渡す商品dictを作るヘルパー（save_idは含まない）。"""

    return {"name": name, "ap": ap, "apt": apt, "baby": baby, "rp": rp, "rpt": rpt, "rurl": rurl}


def fixed_clock(dt=None):
    """常に同じdatetimeを返すclock関数を作るヘルパー。"""

    fixed_dt = dt or datetime.datetime(2024, 1, 1, 12, 0, 0)
    return lambda: fixed_dt


def saved_data_values(*rows):
    """saved_dataシートの2次元リスト（見出し付き）を作るヘルパー。"""

    return [list(SAVED_DATA_HEADERS)] + [list(row) for row in rows]


def products_values(*rows):
    """productsシートの2次元リスト（見出し付き）を作るヘルパー。"""

    return [list(PRODUCT_HEADERS)] + [list(row) for row in rows]


def settings_values(*rows):
    """settingsシートの2次元リスト（見出し付き）を作るヘルパー。"""

    return [list(SETTING_HEADERS)] + [list(row) for row in rows]


def settings_rows_for(save_id, settings=None):
    """指定save_id分のsettings行を、SETTING_DEFAULTSのキー順で作るヘルパー。"""

    source = settings if settings is not None else SETTING_DEFAULTS
    return [[save_id, key, str(source[key])] for key in SETTING_DEFAULTS]


# ===========================================================================
# safe_int
# ===========================================================================


class TestSafeInt:
    """safe_int（安全な整数変換）のテスト。"""

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_None_空文字_空白はdefaultになる(self, value):
        """境界値: None・空文字・空白文字列はいずれもdefault値になる。"""

        assert safe_int(value, default=7) == 7

    def test_defaultを省略すると0になる(self):
        """defaultを省略した場合の既定値は0。"""

        assert safe_int(None) == 0

    def test_小数の文字列は切り捨てて整数になる(self):
        """ "3.7" は int(float("3.7")) の仕様どおり3になる。"""

        assert safe_int("3.7") == 3

    def test_通常の整数文字列を変換できる(self):
        """ "5" のような通常の整数文字列は5に変換される。"""

        assert safe_int("5") == 5

    def test_整数そのものを渡してもよい(self):
        """すでにintの値を渡してもそのまま返る。"""

        assert safe_int(5) == 5

    def test_変換できない文字列はdefaultになる(self):
        """ "abc" のような変換不能な文字列はdefaultになる。"""

        assert safe_int("abc", default=9) == 9


# ===========================================================================
# normalize_bool
# ===========================================================================


class TestNormalizeBool:
    """normalize_bool（真偽値の正規化）のテスト。"""

    def test_bool型はそのまま返る(self):
        """すでにbool型の値はそのまま返る。"""

        assert normalize_bool(True) is True
        assert normalize_bool(False) is False

    @pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "YES", "on", "On", " true "])
    def test_真として扱う文字列(self, value):
        """ "true","1","yes","on"（大文字小文字・前後空白を無視）はTrueになる。"""

        assert normalize_bool(value) is True

    @pytest.mark.parametrize("value", ["false", "0", "no", "off", "", "abc", None])
    def test_偽として扱う値(self, value):
        """真として扱う文字列以外はFalseになる。"""

        assert normalize_bool(value) is False


# ===========================================================================
# make_default_product
# ===========================================================================


class TestMakeDefaultProduct:
    """make_default_product（既定の商品dict）のテスト。"""

    def test_既定の商品dictが返る(self):
        """仕様どおりのキーと初期値を持つdictが返る。"""

        assert make_default_product() == {
            "name": "",
            "ap": 0,
            "apt": 1,
            "baby": False,
            "rp": 0,
            "rpt": 0,
            "rurl": "",
        }

    def test_呼び出すたびに独立したdictが返る(self):
        """返り値を書き換えても次の呼び出し結果に影響しない。"""

        first = make_default_product()
        first["name"] = "書き換え"
        assert make_default_product()["name"] == ""


# ===========================================================================
# parse_saved_data
# ===========================================================================


class TestParseSavedData:
    """parse_saved_data（saved_dataシートのパース）のテスト。"""

    def test_通常のデータを読み取れる(self):
        """見出しどおりの並びなら、そのまま各列を読み取れる。"""

        values = saved_data_values(["id1", "名前1", "2024-01-01 00:00:00"])
        assert parse_saved_data(values) == [
            {"save_id": "id1", "name": "名前1", "saved_at": "2024-01-01 00:00:00"}
        ]

    def test_列の順番が違っても見出し名で読み取れる(self):
        """見出しの列順が異なっていても、列名を頼りに正しく読み取れる。"""

        values = [["name", "save_id", "saved_at"], ["名前1", "id1", "2024-01-01 00:00:00"]]
        assert parse_saved_data(values) == [
            {"save_id": "id1", "name": "名前1", "saved_at": "2024-01-01 00:00:00"}
        ]

    def test_短い行は不足列が空文字になる(self):
        """境界値: saved_at列が無い短い行は、saved_atが空文字として扱われる。"""

        values = [list(SAVED_DATA_HEADERS), ["id1", "名前1"]]
        assert parse_saved_data(values) == [{"save_id": "id1", "name": "名前1", "saved_at": ""}]

    def test_save_idまたはnameが空の行は飛ばされる(self):
        """save_idが空、またはnameが空の行はどちらも結果から除外される。"""

        values = [
            list(SAVED_DATA_HEADERS),
            ["", "名前1", "2024-01-01 00:00:00"],
            ["id2", "", "2024-01-02 00:00:00"],
            ["id3", "名前3", "2024-01-03 00:00:00"],
        ]
        assert parse_saved_data(values) == [
            {"save_id": "id3", "name": "名前3", "saved_at": "2024-01-03 00:00:00"}
        ]

    def test_前後の空白は除去される(self):
        """各セルの値はstripされてから返る。"""

        values = [list(SAVED_DATA_HEADERS), ["  id1  ", "  名前1  ", "  2024-01-01 00:00:00  "]]
        assert parse_saved_data(values) == [
            {"save_id": "id1", "name": "名前1", "saved_at": "2024-01-01 00:00:00"}
        ]

    def test_必要な列が無ければ空リストになる(self):
        """name列が存在しない見出しの場合、空リストが返る。"""

        values = [["save_id", "saved_at"], ["id1", "2024-01-01 00:00:00"]]
        assert parse_saved_data(values) == []

    def test_空のvaluesは空リストになる(self):
        """境界値: values自体が空リストの場合、空リストを返す。"""

        assert parse_saved_data([]) == []


# ===========================================================================
# parse_products
# ===========================================================================


class TestParseProducts:
    """parse_products（productsシートのパース）のテスト。"""

    def test_通常のデータを読み取れる(self):
        """見出しどおりの並びで、各列がsafe_int/normalize_boolを通して読み取れる。"""

        values = products_values(
            ["id1", "商品1", "1000", "3", "true", "2000", "2", "https://a.example.com"]
        )
        assert parse_products(values, "id1") == [
            {
                "name": "商品1",
                "ap": 1000,
                "apt": 3,
                "baby": True,
                "rp": 2000,
                "rpt": 2,
                "rurl": "https://a.example.com",
            }
        ]

    def test_列の順番が違っても見出し名で読み取れる(self):
        """見出しの列順が異なっていても、列名を頼りに正しく読み取れる。"""

        headers = ["rurl", "save_id", "name", "rp", "rpt", "ap", "apt", "baby"]
        values = [headers, ["https://a", "id1", "商品A", "2000", "2", "1000", "1", "true"]]

        assert parse_products(values, "id1") == [
            {
                "name": "商品A",
                "ap": 1000,
                "apt": 1,
                "baby": True,
                "rp": 2000,
                "rpt": 2,
                "rurl": "https://a",
            }
        ]

    def test_指定したsave_idの行だけ抽出される(self):
        """別のsave_idの行は無視され、一致する行だけが返る。"""

        values = products_values(
            ["id1", "商品1", "1000", "1", "False", "1000", "1", "https://a"],
            ["id2", "商品2", "2000", "1", "False", "2000", "1", "https://b"],
        )
        result = parse_products(values, "id2")
        assert len(result) == 1
        assert result[0]["name"] == "商品2"

    def test_短い行は不足列がsafe_intのdefaultで補われる(self):
        """境界値: 途中から列が無い行は、apが0、apt既定1などで補われる。"""

        values = [list(PRODUCT_HEADERS), ["id1", "商品1"]]
        assert parse_products(values, "id1") == [
            {"name": "商品1", "ap": 0, "apt": 1, "baby": False, "rp": 0, "rpt": 0, "rurl": ""}
        ]

    def test_save_id以外が全部空の行は飛ばされる(self):
        """save_idはあるが他の列が全て空文字の行は結果に含まれない。"""

        values = products_values(["id1", "", "", "", "", "", "", ""])
        assert parse_products(values, "id1") == []

    def test_見出しが想定と違えば空リストになる(self):
        """必要な列が見つからない見出しの場合、空リストが返る。"""

        values = [["a", "b", "c"], ["id1", "商品1", "1000"]]
        assert parse_products(values, "id1") == []

    def test_babyの正規化が反映される(self):
        """ "TRUE" や "0" のような値もnormalize_boolを通してbool化される。"""

        values = products_values(
            ["id1", "商品1", "1000", "1", "TRUE", "1000", "1", ""],
            ["id1", "商品2", "1000", "1", "0", "1000", "1", ""],
        )
        result = parse_products(values, "id1")
        assert result[0]["baby"] is True
        assert result[1]["baby"] is False


# ===========================================================================
# parse_settings
# ===========================================================================


class TestParseSettings:
    """parse_settings（settingsシートのパース）のテスト。"""

    def test_該当データが無ければデフォルトのコピーが返る(self):
        """行が無い場合はSETTING_DEFAULTSと同じ内容だが別オブジェクトが返る。"""

        result = parse_settings([], "id1")
        assert result == SETTING_DEFAULTS
        assert result is not SETTING_DEFAULTS

    def test_該当save_idの設定で上書きされる(self):
        """一致するsave_id・既知のキーの行だけが値を上書きする。"""

        values = settings_values(
            ["id1", "max_shops", "3"], ["id1", "bonus_cap", "5000"], ["id2", "max_shops", "99"]
        )
        result = parse_settings(values, "id1")

        expected = dict(SETTING_DEFAULTS)
        expected["max_shops"] = 3
        expected["bonus_cap"] = 5000
        assert result == expected

    def test_知らないキーは無視される(self):
        """SETTING_DEFAULTSに無いキーの行は無視される。"""

        values = settings_values(["id1", "unknown_key", "999"])
        assert parse_settings(values, "id1") == SETTING_DEFAULTS

    def test_value列が不正な場合はそのキーの既定値になる(self):
        """境界値: safe_intで変換できないvalueは、そのキーの既定値にフォールバックする。"""

        values = settings_values(["id1", "max_shops", "abc"])
        result = parse_settings(values, "id1")
        assert result["max_shops"] == SETTING_DEFAULTS["max_shops"]


# ===========================================================================
# replace_rows
# ===========================================================================


class TestReplaceRows:
    """replace_rows（シート書き込み用の2次元リスト作成）のテスト。"""

    def test_空のシートは見出しと新規行だけになる(self):
        """values=[] の場合、[headers] + new_rows がそのまま返る。"""

        new_rows = [["id1", "名前1", "2024-01-01 00:00:00"]]
        result = replace_rows([], SAVED_DATA_HEADERS, "id1", new_rows)
        assert result == [list(SAVED_DATA_HEADERS)] + new_rows

    def test_見出し行が全部空文字のシートも空扱いになる(self):
        """1行目が全セル空文字の場合も、空シートと同じ扱いになる。"""

        values = [["", "", ""]]
        new_rows = [["id1", "名前1", "2024-01-01 00:00:00"]]
        result = replace_rows(values, SAVED_DATA_HEADERS, "id1", new_rows)
        assert result == [list(SAVED_DATA_HEADERS)] + new_rows

    def test_見出しのみでデータが無いシートに新規行を追加できる(self):
        """見出しだけあってデータ行が無い場合、新規行が追加される。"""

        values = [list(SAVED_DATA_HEADERS)]
        new_rows = [["id1", "名前1", "2024-01-01 00:00:00"]]
        result = replace_rows(values, SAVED_DATA_HEADERS, "id1", new_rows)
        assert result == [list(SAVED_DATA_HEADERS)] + new_rows

    def test_他のsave_idの行は残り対象の行だけ差し替わる(self):
        """
        リファクタリング前の不具合（他の保存データが消える）が
        再発しないことを確認する中心的なテスト。
        """

        values = [
            list(SAVED_DATA_HEADERS),
            ["id1", "名前1", "2024-01-01 00:00:00"],
            ["id2", "名前2", "2024-01-02 00:00:00"],
            ["id3", "名前3", "2024-01-03 00:00:00"],
        ]
        new_rows = [["id2", "新名前2", "2024-02-02 00:00:00"]]

        result = replace_rows(values, SAVED_DATA_HEADERS, "id2", new_rows)

        assert result == [
            list(SAVED_DATA_HEADERS),
            ["id1", "名前1", "2024-01-01 00:00:00"],
            ["id2", "新名前2", "2024-02-02 00:00:00"],
            ["id3", "名前3", "2024-01-03 00:00:00"],
        ]

    def test_商品のように1つのsave_idに複数行あっても元の位置に差し込まれる(self):
        """複数行を1つのsave_idに差し替える場合も、元の位置に挿入される。"""

        values = [
            list(PRODUCT_HEADERS),
            ["id1", "A商品", "1000", "1", "False", "1000", "1", "https://a"],
            ["id2", "B商品1", "1000", "1", "False", "1000", "1", "https://b1"],
            ["id2", "B商品2", "2000", "1", "False", "2000", "1", "https://b2"],
            ["id3", "C商品", "1500", "1", "False", "1500", "1", "https://c"],
        ]
        new_rows = [
            ["id2", "B商品new1", "1100", "1", "False", "1100", "1", "https://b1new"],
            ["id2", "B商品new2", "1200", "1", "False", "1200", "1", "https://b2new"],
            ["id2", "B商品new3", "1300", "1", "False", "1300", "1", "https://b3new"],
        ]

        result = replace_rows(values, PRODUCT_HEADERS, "id2", new_rows)

        assert result[0] == list(PRODUCT_HEADERS)
        assert result[1][0] == "id1"
        assert result[2:5] == new_rows
        assert result[5][0] == "id3"
        assert len(result) == 6  # 元5行 + 新3行 - 旧2行

    def test_save_idが元に無い場合は末尾に追加される(self):
        """一致するsave_idの行が無ければ、新規行は末尾に追加される。"""

        values = [list(SAVED_DATA_HEADERS), ["id1", "名前1", "2024-01-01 00:00:00"]]
        new_rows = [["id-new", "新規", "2024-03-01 00:00:00"]]

        result = replace_rows(values, SAVED_DATA_HEADERS, "id-new", new_rows)

        assert result == [
            list(SAVED_DATA_HEADERS),
            ["id1", "名前1", "2024-01-01 00:00:00"],
            ["id-new", "新規", "2024-03-01 00:00:00"],
        ]

    def test_空行は除去され元の行数を保つため空行が足される(self):
        """全セル空の行は除去されるが、元の行数を保つために末尾に空行が補われる。"""

        values = [
            list(SAVED_DATA_HEADERS),
            ["id1", "名前1", "2024-01-01 00:00:00"],
            ["", "", ""],
            ["id2", "名前2", "2024-01-02 00:00:00"],
        ]
        # id2を同内容で置き換え、行数の変化を空行除去だけに絞る
        new_rows = [["id2", "名前2", "2024-01-02 00:00:00"]]

        result = replace_rows(values, SAVED_DATA_HEADERS, "id2", new_rows)

        assert result == [
            list(SAVED_DATA_HEADERS),
            ["id1", "名前1", "2024-01-01 00:00:00"],
            ["id2", "名前2", "2024-01-02 00:00:00"],
            ["", "", ""],
        ]

    def test_対象save_idを削除して元より短くなる場合は空行で行数を保つ(self):
        """new_rowsが空（削除）で行数が減る場合、末尾に空行が補われ元の行数のままになる。"""

        values = [
            list(SAVED_DATA_HEADERS),
            ["id1", "名前1", "2024-01-01 00:00:00"],
            ["id2", "名前2", "2024-01-02 00:00:00"],
            ["id3", "名前3", "2024-01-03 00:00:00"],
        ]

        result = replace_rows(values, SAVED_DATA_HEADERS, "id2", [])

        assert result == [
            list(SAVED_DATA_HEADERS),
            ["id1", "名前1", "2024-01-01 00:00:00"],
            ["id3", "名前3", "2024-01-03 00:00:00"],
            ["", "", ""],
        ]

    def test_短い既存行はheadersの長さに揃えられる(self):
        """境界値: 既存データの列が足りない行は、空文字で埋められてheaders長になる。"""

        values = [list(SAVED_DATA_HEADERS), ["id1", "名前1"]]

        result = replace_rows(values, SAVED_DATA_HEADERS, "id-none", [])

        assert result == [list(SAVED_DATA_HEADERS), ["id1", "名前1", ""]]

    def test_見出しが一致しないとValueError(self):
        """必要な列が欠けている見出しの場合、書き込みを中止するためValueErrorになる。"""

        values = [["save_id", "name"], ["id1", "名前1"]]
        with pytest.raises(ValueError):
            replace_rows(values, SAVED_DATA_HEADERS, "id1", [])

    def test_見出しの列順が違うとValueError(self):
        """列の順番が違う見出しは、書き込みでは完全一致とみなされずValueErrorになる。"""

        values = [["name", "save_id", "saved_at"], ["名前1", "id1", "2024-01-01 00:00:00"]]
        with pytest.raises(ValueError):
            replace_rows(values, SAVED_DATA_HEADERS, "id1", [])

    def test_見出しの末尾に空セルがあっても一致とみなされる(self):
        """見出し行の末尾の空セルは無視して比較されるため、ValueErrorにならない。"""

        values = [list(SAVED_DATA_HEADERS) + ["", ""], ["id1", "名前1", "2024-01-01 00:00:00"]]
        new_rows = [["id1", "新名前1", "2024-02-01 00:00:00"]]

        result = replace_rows(values, SAVED_DATA_HEADERS, "id1", new_rows)

        assert result[0][: len(SAVED_DATA_HEADERS)] == list(SAVED_DATA_HEADERS)
        assert result[1] == new_rows[0]


# ===========================================================================
# SheetStorage.list_saved
# ===========================================================================


class TestSheetStorageListSaved:
    """SheetStorage.list_saved のテスト。"""

    def test_一覧をパースして返す(self):
        """saved_dataシートの内容がparse_saved_data相当の形で返る。"""

        values = saved_data_values(["id1", "名前1", "2024-01-01 00:00:00"])
        spreadsheet = FakeSpreadsheet({SAVED_DATA_SHEET: values})
        storage = SheetStorage(spreadsheet, clock=fixed_clock())

        assert storage.list_saved() == [
            {"save_id": "id1", "name": "名前1", "saved_at": "2024-01-01 00:00:00"}
        ]

    def test_シートが無い場合はadd_worksheetで作られ空リストになる(self):
        """saved_dataシートが無い場合、作成された上で空リストが返る。"""

        spreadsheet = FakeSpreadsheet({})
        storage = SheetStorage(spreadsheet, clock=fixed_clock())

        assert storage.list_saved() == []
        assert SAVED_DATA_SHEET in spreadsheet.add_worksheet_calls


# ===========================================================================
# SheetStorage.save
# ===========================================================================


class TestSheetStorageSave:
    """SheetStorage.save のテスト。"""

    def test_別の保存データの行が消えない(self):
        """
        リファクタリング前の一番の不具合（ws.clear()で全件消える）が
        再発しないことを確認する。
        """

        spreadsheet = FakeSpreadsheet(
            {
                SAVED_DATA_SHEET: saved_data_values(
                    ["other-id", "他の保存", "2024-01-01 00:00:00"]
                ),
                PRODUCTS_SHEET: products_values(
                    ["other-id", "他の商品", "1000", "1", "False", "1000", "1", "https://other"]
                ),
                SETTINGS_SHEET: settings_values(*settings_rows_for("other-id")),
            }
        )
        storage = SheetStorage(spreadsheet, clock=fixed_clock())

        storage.save("新しい保存", [make_product(name="新商品")], dict(SETTING_DEFAULTS))

        saved = parse_saved_data(spreadsheet.sheets[SAVED_DATA_SHEET].get_all_values())
        assert "other-id" in {row["save_id"] for row in saved}

        other_products = parse_products(
            spreadsheet.sheets[PRODUCTS_SHEET].get_all_values(), "other-id"
        )
        assert len(other_products) == 1
        assert other_products[0]["name"] == "他の商品"

        other_settings = parse_settings(
            spreadsheet.sheets[SETTINGS_SHEET].get_all_values(), "other-id"
        )
        assert other_settings == SETTING_DEFAULTS

    def test_商品名が数式のような文字列でもそのままRAWで書き込まれる(self):
        """
        リファクタリング前の不具合（USER_ENTEREDで数式が実行される）が
        再発しないことを確認する。
        """

        spreadsheet = FakeSpreadsheet({})
        storage = SheetStorage(spreadsheet, clock=fixed_clock())
        formula_like_name = '=IMPORTXML("https://example.com", "//a")'

        storage.save("保存1", [make_product(name=formula_like_name)], dict(SETTING_DEFAULTS))

        products_ws = spreadsheet.sheets[PRODUCTS_SHEET]
        call = products_ws.update_calls[0]
        assert call["value_input_option"] == "RAW"

        written_names = [row[1] for row in call["values"][1:]]
        assert formula_like_name in written_names

    def test_clearは呼ばれない(self):
        """既存データがある状態で保存しても、どのシートのclearも呼ばれない。"""

        spreadsheet = FakeSpreadsheet(
            {
                SAVED_DATA_SHEET: saved_data_values(["id1", "既存", "2024-01-01 00:00:00"]),
                PRODUCTS_SHEET: products_values(
                    ["id1", "商品1", "1000", "1", "False", "1000", "1", ""]
                ),
                SETTINGS_SHEET: settings_values(*settings_rows_for("id1")),
            }
        )
        storage = SheetStorage(spreadsheet, clock=fixed_clock())

        storage.save("新規", [make_product()], dict(SETTING_DEFAULTS))

        for ws in spreadsheet.sheets.values():
            assert ws.clear_calls == 0

    def test_各シートへのupdateは1回ずつでproducts_settings_saved_dataの順(self):
        """updateの呼び出し順序がproducts -> settings -> saved_dataで、各1回であること。"""

        spreadsheet = FakeSpreadsheet({})
        storage = SheetStorage(spreadsheet, clock=fixed_clock())

        storage.save("保存1", [make_product()], dict(SETTING_DEFAULTS))

        assert spreadsheet.call_log == [PRODUCTS_SHEET, SETTINGS_SHEET, SAVED_DATA_SHEET]
        for sheet_name in (PRODUCTS_SHEET, SETTINGS_SHEET, SAVED_DATA_SHEET):
            assert len(spreadsheet.sheets[sheet_name].update_calls) == 1

    def test_productsの書き込みに失敗するとsaved_dataに新しい保存データが載らない(self):
        """
        書き込み順序がproducts -> settings -> saved_dataであることを利用し、
        productsで失敗したら一覧（saved_data）が元のまま変わらないことを確認する。
        """

        original_saved_data = saved_data_values(["id1", "既存", "2024-01-01 00:00:00"])
        spreadsheet = FakeSpreadsheet(
            {SAVED_DATA_SHEET: [list(row) for row in original_saved_data]}
        )
        spreadsheet.sheets[PRODUCTS_SHEET] = FakeWorksheet(
            PRODUCTS_SHEET, values=[], call_log=spreadsheet.call_log, fail_on_update=True
        )
        storage = SheetStorage(spreadsheet, clock=fixed_clock())

        with pytest.raises(Exception):
            storage.save("新規保存", [make_product()], dict(SETTING_DEFAULTS))

        assert spreadsheet.sheets[SAVED_DATA_SHEET].get_all_values() == original_saved_data
        assert spreadsheet.sheets[SAVED_DATA_SHEET].update_calls == []
        assert (
            SETTINGS_SHEET not in spreadsheet.sheets
            or spreadsheet.sheets[SETTINGS_SHEET].update_calls == []
        )

    def test_同名の保存データがあれば同じsave_idで上書きされ一覧の位置が変わらない(self):
        """同名保存は新規追加ではなく上書きになり、一覧内の並び順も変わらない。"""

        spreadsheet = FakeSpreadsheet(
            {
                SAVED_DATA_SHEET: saved_data_values(
                    ["id-a", "A", "2024-01-01 00:00:00"],
                    ["id-b", "B", "2024-01-02 00:00:00"],
                    ["id-c", "C", "2024-01-03 00:00:00"],
                )
            }
        )
        clock_dt = datetime.datetime(2024, 5, 1, 9, 0, 0)
        storage = SheetStorage(spreadsheet, clock=fixed_clock(clock_dt))

        save_id, name = storage.save("B", [make_product(name="更新後商品")], dict(SETTING_DEFAULTS))

        assert save_id == "id-b"
        assert name == "B"

        rows = spreadsheet.sheets[SAVED_DATA_SHEET].get_all_values()[1:]
        assert [row[0] for row in rows] == ["id-a", "id-b", "id-c"]

        updated = parse_saved_data(spreadsheet.sheets[SAVED_DATA_SHEET].get_all_values())
        updated_b = next(r for r in updated if r["save_id"] == "id-b")
        assert updated_b["saved_at"] == "2024-05-01 09:00:00"

    def test_overwrite_save_idを指定すると名前が違ってもそのIDが使われる(self):
        """overwrite_save_idが優先され、同名検索より先にそのIDで上書きされる。"""

        spreadsheet = FakeSpreadsheet(
            {SAVED_DATA_SHEET: saved_data_values(["id-a", "A", "2024-01-01 00:00:00"])}
        )
        storage = SheetStorage(spreadsheet, clock=fixed_clock())

        save_id, name = storage.save(
            "新しい名前", [make_product()], dict(SETTING_DEFAULTS), overwrite_save_id="id-a"
        )

        assert save_id == "id-a"
        assert name == "新しい名前"

        rows = parse_saved_data(spreadsheet.sheets[SAVED_DATA_SHEET].get_all_values())
        assert len(rows) == 1
        assert rows[0]["save_id"] == "id-a"
        assert rows[0]["name"] == "新しい名前"

    def test_保存名が空文字だとValueErrorになりupdateが呼ばれない(self):
        """境界値: 空文字（空白のみ含む）の保存名はValueErrorになり、書き込みは一切行われない。"""

        spreadsheet = FakeSpreadsheet({})
        storage = SheetStorage(spreadsheet, clock=fixed_clock())

        with pytest.raises(ValueError):
            storage.save("   ", [make_product()], dict(SETTING_DEFAULTS))

        assert spreadsheet.call_log == []

    def test_保存名が51文字だとValueErrorになる(self):
        """境界値: MAX_SAVE_NAME_LENGTH(50)を1文字超えるとValueError。"""

        spreadsheet = FakeSpreadsheet({})
        storage = SheetStorage(spreadsheet, clock=fixed_clock())

        with pytest.raises(ValueError):
            storage.save(
                "あ" * (MAX_SAVE_NAME_LENGTH + 1), [make_product()], dict(SETTING_DEFAULTS)
            )

        assert spreadsheet.call_log == []

    def test_保存名がちょうど50文字ならエラーにならない(self):
        """境界値: MAX_SAVE_NAME_LENGTHちょうどの長さはOK。"""

        spreadsheet = FakeSpreadsheet({})
        storage = SheetStorage(spreadsheet, clock=fixed_clock())

        save_id, name = storage.save(
            "あ" * MAX_SAVE_NAME_LENGTH, [make_product()], dict(SETTING_DEFAULTS)
        )

        assert name == "あ" * MAX_SAVE_NAME_LENGTH
        assert len(save_id) == 32  # uuid4().hex

    def test_saved_atはclockの時刻文字列になる(self):
        """saved_atはclock().strftime("%Y-%m-%d %H:%M:%S")の形式になる。"""

        clock_dt = datetime.datetime(2030, 12, 31, 23, 59, 59)
        spreadsheet = FakeSpreadsheet({})
        storage = SheetStorage(spreadsheet, clock=lambda: clock_dt)

        storage.save("保存1", [make_product()], dict(SETTING_DEFAULTS))

        rows = parse_saved_data(spreadsheet.sheets[SAVED_DATA_SHEET].get_all_values())
        assert rows[0]["saved_at"] == "2030-12-31 23:59:59"

    def test_シートが無いときはadd_worksheetで作られる(self):
        """3シートいずれも存在しない状態から保存すると、全てadd_worksheetで作られる。"""

        spreadsheet = FakeSpreadsheet({})
        storage = SheetStorage(spreadsheet, clock=fixed_clock())

        storage.save("保存1", [make_product()], dict(SETTING_DEFAULTS))

        for sheet_name in (PRODUCTS_SHEET, SETTINGS_SHEET, SAVED_DATA_SHEET):
            assert sheet_name in spreadsheet.add_worksheet_calls

    def test_productsの行の内容と並び順が仕様通り(self):
        """products行が [save_id, name, ap, apt, baby, rp, rpt, rurl] の順で書かれる。"""

        spreadsheet = FakeSpreadsheet({})
        storage = SheetStorage(spreadsheet, clock=fixed_clock())
        product = make_product(
            name="商品A", ap=1234, apt=3, baby=True, rp=5678, rpt=2, rurl="https://a.example.com"
        )

        save_id, _ = storage.save("保存1", [product], dict(SETTING_DEFAULTS))

        row = spreadsheet.sheets[PRODUCTS_SHEET].get_all_values()[1]
        assert row == [save_id, "商品A", 1234, 3, True, 5678, 2, "https://a.example.com"]

    def test_settingsの行はSETTING_DEFAULTSのキー順に書かれる(self):
        """渡すsettings dictの順序に関わらず、書き込み順はSETTING_DEFAULTSのキー順になる。"""

        spreadsheet = FakeSpreadsheet({})
        storage = SheetStorage(spreadsheet, clock=fixed_clock())
        settings = {"spu_multiplier": 5, "max_shops": 8, "bonus_cap": 3000, "min_shop_price": 500}

        storage.save("保存1", [make_product()], settings)

        rows = spreadsheet.sheets[SETTINGS_SHEET].get_all_values()[1:]
        assert [row[1] for row in rows] == list(SETTING_DEFAULTS.keys())

        values_by_key = {row[1]: row[2] for row in rows}
        assert values_by_key["max_shops"] == 8
        assert values_by_key["spu_multiplier"] == 5

    def test_settingsに無いキーがあってもデフォルト値が使われる(self):
        """settings引数が空dictでも、SETTING_DEFAULTSの値で全キーが書き込まれる。"""

        spreadsheet = FakeSpreadsheet({})
        storage = SheetStorage(spreadsheet, clock=fixed_clock())

        storage.save("保存1", [make_product()], {})

        rows = spreadsheet.sheets[SETTINGS_SHEET].get_all_values()[1:]
        values_by_key = {row[1]: row[2] for row in rows}
        for key, default in SETTING_DEFAULTS.items():
            assert values_by_key[key] == default


# ===========================================================================
# SheetStorage.load
# ===========================================================================


class TestSheetStorageLoad:
    """SheetStorage.load のテスト。"""

    def test_商品と設定が復元される(self):
        """一覧record・商品リスト・設定dictがそれぞれ正しく復元される。"""

        spreadsheet = FakeSpreadsheet(
            {
                SAVED_DATA_SHEET: saved_data_values(["id1", "保存1", "2024-01-01 00:00:00"]),
                PRODUCTS_SHEET: products_values(
                    ["id1", "商品1", "1000", "1", "False", "1000", "1", "https://a"],
                    ["id1", "商品2", "2000", "2", "True", "3000", "3", "https://b"],
                ),
                SETTINGS_SHEET: settings_values(["id1", "max_shops", "5"]),
            }
        )
        storage = SheetStorage(spreadsheet, clock=fixed_clock())

        record, products, settings = storage.load("id1")

        assert record == {"save_id": "id1", "name": "保存1", "saved_at": "2024-01-01 00:00:00"}
        assert len(products) == 2
        assert products[0]["name"] == "商品1"
        assert products[1]["baby"] is True
        assert settings["max_shops"] == 5
        assert settings["bonus_cap"] == SETTING_DEFAULTS["bonus_cap"]

    def test_商品が16件だとValueErrorになる(self):
        """境界値: MAX_PRODUCTS(15)を1件超える16件でValueErrorになる。"""

        rows = [
            ["id1", f"商品{i}", "1000", "1", "False", "1000", "1", ""]
            for i in range(MAX_PRODUCTS + 1)
        ]
        spreadsheet = FakeSpreadsheet(
            {
                SAVED_DATA_SHEET: saved_data_values(["id1", "保存1", "2024-01-01 00:00:00"]),
                PRODUCTS_SHEET: products_values(*rows),
                SETTINGS_SHEET: settings_values(),
            }
        )
        storage = SheetStorage(spreadsheet, clock=fixed_clock())

        with pytest.raises(ValueError):
            storage.load("id1")

    def test_商品がちょうど15件なら読み込める(self):
        """境界値: MAX_PRODUCTSちょうどの15件は正常に読み込める。"""

        rows = [
            ["id1", f"商品{i}", "1000", "1", "False", "1000", "1", ""] for i in range(MAX_PRODUCTS)
        ]
        spreadsheet = FakeSpreadsheet(
            {
                SAVED_DATA_SHEET: saved_data_values(["id1", "保存1", "2024-01-01 00:00:00"]),
                PRODUCTS_SHEET: products_values(*rows),
                SETTINGS_SHEET: settings_values(),
            }
        )
        storage = SheetStorage(spreadsheet, clock=fixed_clock())

        _, products, _ = storage.load("id1")
        assert len(products) == MAX_PRODUCTS

    def test_商品が0件ならデフォルト商品が1件返る(self):
        """境界値: 商品が1件も無い場合、make_default_product()を1件だけ含むリストになる。"""

        spreadsheet = FakeSpreadsheet(
            {
                SAVED_DATA_SHEET: saved_data_values(["id1", "保存1", "2024-01-01 00:00:00"]),
                PRODUCTS_SHEET: products_values(),
                SETTINGS_SHEET: settings_values(),
            }
        )
        storage = SheetStorage(spreadsheet, clock=fixed_clock())

        _, products, _ = storage.load("id1")
        assert products == [make_default_product()]

    def test_存在しないIDはValueErrorになる(self):
        """一覧に存在しないsave_idを指定するとValueError。"""

        spreadsheet = FakeSpreadsheet(
            {SAVED_DATA_SHEET: saved_data_values(["id1", "保存1", "2024-01-01 00:00:00"])}
        )
        storage = SheetStorage(spreadsheet, clock=fixed_clock())

        with pytest.raises(ValueError):
            storage.load("not-exist")

    def test_空文字のIDはValueErrorになる(self):
        """境界値: save_idが空文字の場合はValueError。"""

        spreadsheet = FakeSpreadsheet(
            {SAVED_DATA_SHEET: saved_data_values(["id1", "保存1", "2024-01-01 00:00:00"])}
        )
        storage = SheetStorage(spreadsheet, clock=fixed_clock())

        with pytest.raises(ValueError):
            storage.load("")


# ===========================================================================
# SheetStorage.delete
# ===========================================================================


class TestSheetStorageDelete:
    """SheetStorage.delete のテスト。"""

    def test_対象だけが3シートから消えて他は残る(self):
        """指定したsave_idの行だけが3シート全てから消え、他のsave_idは残る。"""

        spreadsheet = FakeSpreadsheet(
            {
                SAVED_DATA_SHEET: saved_data_values(
                    ["id1", "保存1", "2024-01-01 00:00:00"], ["id2", "保存2", "2024-01-02 00:00:00"]
                ),
                PRODUCTS_SHEET: products_values(
                    ["id1", "商品1", "1000", "1", "False", "1000", "1", ""],
                    ["id2", "商品2", "2000", "1", "False", "2000", "1", ""],
                ),
                SETTINGS_SHEET: settings_values(
                    *settings_rows_for("id1"), *settings_rows_for("id2")
                ),
            }
        )
        storage = SheetStorage(spreadsheet, clock=fixed_clock())

        remaining = storage.delete("id1")

        assert remaining == [{"save_id": "id2", "name": "保存2", "saved_at": "2024-01-02 00:00:00"}]

        products_values_after = spreadsheet.sheets[PRODUCTS_SHEET].get_all_values()
        assert parse_products(products_values_after, "id1") == []
        assert len(parse_products(products_values_after, "id2")) == 1

        settings_values_after = spreadsheet.sheets[SETTINGS_SHEET].get_all_values()
        assert (
            parse_settings(settings_values_after, "id2")["max_shops"]
            == SETTING_DEFAULTS["max_shops"]
        )

    def test_削除の書き込み順序はsaved_data_products_settings(self):
        """一覧を先に消すため、updateの順序はsaved_data -> products -> settingsになる。"""

        spreadsheet = FakeSpreadsheet(
            {
                SAVED_DATA_SHEET: saved_data_values(["id1", "保存1", "2024-01-01 00:00:00"]),
                PRODUCTS_SHEET: products_values(
                    ["id1", "商品1", "1000", "1", "False", "1000", "1", ""]
                ),
                SETTINGS_SHEET: settings_values(*settings_rows_for("id1")),
            }
        )
        storage = SheetStorage(spreadsheet, clock=fixed_clock())

        storage.delete("id1")

        assert spreadsheet.call_log == [SAVED_DATA_SHEET, PRODUCTS_SHEET, SETTINGS_SHEET]

    def test_存在しないIDはValueErrorになりどのシートも更新されない(self):
        """一覧に無いsave_idを削除しようとするとValueErrorになり、書き込みは行われない。"""

        spreadsheet = FakeSpreadsheet(
            {SAVED_DATA_SHEET: saved_data_values(["id1", "保存1", "2024-01-01 00:00:00"])}
        )
        storage = SheetStorage(spreadsheet, clock=fixed_clock())

        with pytest.raises(ValueError):
            storage.delete("not-exist")

        assert spreadsheet.call_log == []

    def test_空文字のIDはValueErrorになる(self):
        """境界値: save_idが空文字の場合はValueError。"""

        spreadsheet = FakeSpreadsheet(
            {SAVED_DATA_SHEET: saved_data_values(["id1", "保存1", "2024-01-01 00:00:00"])}
        )
        storage = SheetStorage(spreadsheet, clock=fixed_clock())

        with pytest.raises(ValueError):
            storage.delete("")

    def test_productsの見出しが想定と違うとValueError(self):
        """productsシートの見出しがPRODUCT_HEADERSと一致しない場合はValueError。"""

        spreadsheet = FakeSpreadsheet(
            {
                SAVED_DATA_SHEET: saved_data_values(["id1", "保存1", "2024-01-01 00:00:00"]),
                PRODUCTS_SHEET: [["a", "b", "c"], ["id1", "x", "y"]],
                SETTINGS_SHEET: settings_values(*settings_rows_for("id1")),
            }
        )
        storage = SheetStorage(spreadsheet, clock=fixed_clock())

        with pytest.raises(ValueError):
            storage.delete("id1")

    def test_settingsの見出しが想定と違うとValueError(self):
        """settingsシートの見出しがSETTING_HEADERSと一致しない場合はValueError。"""

        spreadsheet = FakeSpreadsheet(
            {
                SAVED_DATA_SHEET: saved_data_values(["id1", "保存1", "2024-01-01 00:00:00"]),
                PRODUCTS_SHEET: products_values(
                    ["id1", "商品1", "1000", "1", "False", "1000", "1", ""]
                ),
                SETTINGS_SHEET: [["a", "b", "c"], ["id1", "x", "y"]],
            }
        )
        storage = SheetStorage(spreadsheet, clock=fixed_clock())

        with pytest.raises(ValueError):
            storage.delete("id1")
