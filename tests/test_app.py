"""
src/buy_sl.py（Streamlitアプリの入口）の画面テスト。

これからUIコードを関数に分けるリファクタリングを行うため、
リファクタリング前の画面の動き（ウィジェットのkey・ラベル・表示文言・計算結果）を
固定し、リファクタリング後も同じテストが通ることで挙動が変わっていないことを
確認するためのテスト。

本物のGoogle Sheets・楽天APIには一切接続しない。
    - Google Sheets: gspread.authorize と Credentials.from_service_account_info をモックし、
      tests/fakes.py の FakeSpreadsheet を返す。
    - 楽天: shopping.rakuten.fetch_rakuten_price_and_point をモックする。

widgetのkeyには widget_version（{v}）がサフィックスとして付くため、
本ファイルでは key の前方一致で目的のウィジェットを探す。
"""

import os
from contextlib import contextmanager
from unittest.mock import patch

import pytest
import streamlit as st
from fakes import FakeSpreadsheet
from streamlit.testing.v1 import AppTest

from shopping.calc import MAX_PRODUCTS, evaluate, find_best
from shopping.storage import SETTING_DEFAULTS

# ===========================================================================
# 定数・共通ヘルパー
# ===========================================================================

APP_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "src", "buy_sl.py")
)

# buy_sl.py の初期商品データ（変更した場合はここも合わせる）
INITIAL_PRODUCTS = [
    {"name": "商品A", "ap": 3000, "apt": 1, "baby": False, "rp": 3200, "rpt": 5, "rurl": ""},
    {"name": "商品B", "ap": 5000, "apt": 1, "baby": True, "rp": 4800, "rpt": 8, "rurl": ""},
]

VALID_PRIVATE_KEY = "-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----\n"


@pytest.fixture(autouse=True)
def clear_streamlit_cache():
    """各テストの前後で st.cache_resource / st.cache_data をクリアし、テスト間の干渉を防ぐ。"""

    st.cache_resource.clear()
    st.cache_data.clear()
    yield
    st.cache_resource.clear()
    st.cache_data.clear()


def set_valid_secrets(at, sheet_id="test-sheet-id"):
    """有効なGoogle Sheets関連のSecretsをAppTestに設定する。"""

    at.secrets["GOOGLE_SHEET_ID"] = sheet_id
    at.secrets["gcp_service_account"] = {
        "type": "service_account",
        "project_id": "test-project",
        "private_key_id": "test-key-id",
        "private_key": VALID_PRIVATE_KEY,
        "client_email": "test@example.com",
        "client_id": "1234567890",
        "token_uri": "https://oauth2.googleapis.com/token",
    }


@contextmanager
def patched_google_sheets(fake_spreadsheet):
    """
    gspread.authorize とGoogle認証をモックし、常に fake_spreadsheet を返すようにする。

    このwithブロックの中でだけ at.run() を呼ぶこと（buy_sl.pyはスクリプトの
    たびにimportし直されるため、モックはそのつど有効にする必要がある）。
    """

    with (
        patch(
            "google.oauth2.service_account.Credentials.from_service_account_info",
            return_value=object(),
        ),
        patch("gspread.authorize") as mock_authorize,
    ):
        mock_authorize.return_value.open_by_key.return_value = fake_spreadsheet
        yield


def make_app():
    """AppTestを作成し、有効なSecretsを設定して返す（まだrunはしない）。"""

    at = AppTest.from_file(APP_PATH, default_timeout=30)
    set_valid_secrets(at)
    return at


def widget_by_key_prefix(widgets, prefix):
    """key が prefix で前方一致する唯一のウィジェットを返す（widget_version違い吸収用）。"""

    matches = [w for w in widgets if str(w.key).startswith(prefix)]
    assert len(matches) == 1, (
        f"'{prefix}'で始まるキーのウィジェットが{len(matches)}件見つかりました："
        f"{[w.key for w in matches]}"
    )
    return matches[0]


def widget_by_label(widgets, label):
    """label が完全一致する唯一のウィジェットを返す。"""

    matches = [w for w in widgets if w.label == label]
    assert len(matches) == 1, f"label={label!r}のウィジェットが{len(matches)}件見つかりました。"
    return matches[0]


def calc_all(items, settings=None):
    """テスト側で直接 shopping.calc を呼び、画面の計算結果と比較するための関数。"""

    settings = settings or SETTING_DEFAULTS
    args = (
        settings["max_shops"],
        settings["min_shop_price"],
        settings["bonus_cap"],
        settings["spu_multiplier"],
    )
    all_a = evaluate(items, ["A"] * len(items), *args)
    all_r = evaluate(items, ["R"] * len(items), *args)
    _, best = find_best(items, *args)
    return all_a, all_r, best


def yen(v):
    """buy_sl.py の yen() と同じ書式で円表示にする。"""

    return f"{round(v):,}円"


# ===========================================================================
# 起動
# ===========================================================================


class TestLaunch:
    """アプリ起動時の画面のテスト。"""

    def test_起動時に例外が発生せずタイトルと初期商品2件が表示される(self):
        """起動しても例外が出ず、タイトルと初期商品2件（商品A・商品B）が表示される。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()

        assert not at.exception
        assert at.title[0].value == "🛒 Amazon × 楽天 最安振り分け計算"

        name_inputs = [w for w in at.text_input if str(w.key).startswith("name_")]
        assert len(name_inputs) == 2
        assert {w.value for w in name_inputs} == {"商品A", "商品B"}

    def test_secretsが無くても起動でき保存済みデータ取得エラーの案内が出る(self):
        """Secretsが無い状態でも画面自体は例外なく表示され、保存一覧が取得できない旨が出る。"""

        at = AppTest.from_file(APP_PATH, default_timeout=30)
        at.run()

        assert not at.exception
        assert at.title[0].value == "🛒 Amazon × 楽天 最安振り分け計算"
        captions = [c.value for c in at.caption]
        assert "保存済みデータを取得できませんでした。Google Sheetsの接続設定を確認してください。" in captions


# ===========================================================================
# 商品の追加・削除
# ===========================================================================


class TestAddDeleteProduct:
    """商品の追加・削除のテスト。"""

    def test_商品を追加ボタンで1件増える(self):
        """「＋ 商品を追加」を押すと商品が1件増える。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            widget_by_label(at.button, "＋ 商品を追加").click()
            at.run()

        assert not at.exception
        assert len(at.session_state["products"]) == 3

    def test_商品がちょうど15件のときは追加できて警告が出ない(self):
        """境界値: 商品が14件から15件になる追加は警告なしで成功する。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            for _ in range(MAX_PRODUCTS - len(INITIAL_PRODUCTS)):
                widget_by_label(at.button, "＋ 商品を追加").click()
                at.run()

        assert not at.exception
        assert len(at.session_state["products"]) == MAX_PRODUCTS
        assert not at.warning

    def test_商品が15件のときに追加すると増えずに警告が出る(self):
        """境界値: 商品が15件（上限）の状態で追加すると件数は増えず、警告が表示される。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            for _ in range(MAX_PRODUCTS - len(INITIAL_PRODUCTS)):
                widget_by_label(at.button, "＋ 商品を追加").click()
                at.run()

            widget_by_label(at.button, "＋ 商品を追加").click()
            at.run()

        assert not at.exception
        assert len(at.session_state["products"]) == MAX_PRODUCTS
        assert [w.value for w in at.warning] == [f"商品は最大{MAX_PRODUCTS}個までです。"]

    def test_削除ボタンで商品が1件減る(self):
        """商品行の🗑️（削除）ボタンを押すと、その商品が削除され1件減る。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            widget_by_key_prefix(at.button, "delete_0_").click()
            at.run()

        assert not at.exception
        products = at.session_state["products"]
        assert len(products) == 1
        assert products[0]["name"] == "商品B"


# ===========================================================================
# 計算
# ===========================================================================


class TestCalculation:
    """「🧮 計算する」ボタンによる計算結果表示のテスト。"""

    def test_計算するボタンで計算結果が表示され最適な振り分けの金額が直接計算した結果と一致する(
        self,
    ):
        """計算結果セクションが表示され、⭐最適な振り分けの金額がcalcモジュールの計算結果と一致する。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            widget_by_label(at.button, "🧮 計算する").click()
            at.run()

        assert not at.exception
        assert "🧮 計算結果" in [s.value for s in at.subheader]

        all_a, all_r, best = calc_all(INITIAL_PRODUCTS)

        metrics = {m.label: m.value for m in at.metric}
        assert metrics["⭐ 最適な振り分け"] == yen(best["net"])
        assert metrics["🟧 すべてAmazon"] == yen(all_a["net"])
        assert metrics["🟥 すべて楽天"] == yen(all_r["net"])

    def test_計算結果は再実行しても残る(self):
        """計算後に何も変更せず at.run() しても、計算結果は表示されたままになる。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            widget_by_label(at.button, "🧮 計算する").click()
            at.run()
            at.run()

        assert not at.exception
        assert "🧮 計算結果" in [s.value for s in at.subheader]

    def test_入力を変えると計算結果が消えて再計算を促すメッセージが出る(self):
        """計算後に商品名を変えると、計算結果は消え「入力が変わりました」の案内が出る。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            widget_by_label(at.button, "🧮 計算する").click()
            at.run()

            widget_by_key_prefix(at.text_input, "name_0_").set_value("商品Aその2")
            at.run()

        assert not at.exception
        assert "🧮 計算結果" not in [s.value for s in at.subheader]
        assert "入力が変わりました。「計算する」を押すと再計算します。" in [
            i.value for i in at.info
        ]


# ===========================================================================
# 楽天の取得
# ===========================================================================


class TestRakutenFetch:
    """楽天商品URLからの価格・還元率取得のテスト。"""

    def test_URLが空で取得ボタンを押すと警告が出る(self):
        """楽天URLが空のまま「取得」を押すと「楽天商品URLを入力してください」の警告が出る。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            widget_by_key_prefix(at.button, "get_rakuten_0_").click()
            at.run()

        assert not at.exception
        assert [w.value for w in at.warning] == ["楽天商品URLを入力してください"]

    def test_取得に成功すると価格と還元率が更新され成功メッセージが出る(self):
        """
        フェイクが (1980.0, 4) を返すとき、楽天価格が1980・還元%が3
        （通常の1%を除いた値）になり、成功メッセージが表示される。
        """

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            widget_by_key_prefix(at.text_input, "rurl_0_").set_value(
                "https://item.rakuten.co.jp/shop/item/"
            )

            with patch(
                "shopping.rakuten.fetch_rakuten_price_and_point", return_value=(1980.0, 4)
            ):
                widget_by_key_prefix(at.button, "get_rakuten_0_").click()
                at.run()

        assert not at.exception
        assert [s.value for s in at.success] == ["楽天の商品情報を取得しました"]

        rp = widget_by_key_prefix(at.number_input, "rp_0_")
        rpt = widget_by_key_prefix(at.number_input, "rpt_0_")
        assert rp.value == 1980
        assert rpt.value == 3

    def test_取得に失敗すると簡潔な1行のエラーが表示される(self):
        """フェイクがValueErrorを出すと「取得エラー：<メッセージ>」が1行で表示される。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            widget_by_key_prefix(at.text_input, "rurl_0_").set_value(
                "https://item.rakuten.co.jp/shop/item/"
            )

            with patch(
                "shopping.rakuten.fetch_rakuten_price_and_point",
                side_effect=ValueError("URLの商品と一致する商品が見つかりませんでした"),
            ):
                widget_by_key_prefix(at.button, "get_rakuten_0_").click()
                at.run()

        assert not at.exception
        assert [e.value for e in at.error] == [
            "取得エラー：URLの商品と一致する商品が見つかりませんでした"
        ]

    def test_取得メッセージは次の再実行で消える(self):
        """URL取得の成功メッセージは一度表示されると、次の再実行では消える。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            widget_by_key_prefix(at.text_input, "rurl_0_").set_value(
                "https://item.rakuten.co.jp/shop/item/"
            )

            with patch(
                "shopping.rakuten.fetch_rakuten_price_and_point", return_value=(1980.0, 4)
            ):
                widget_by_key_prefix(at.button, "get_rakuten_0_").click()
                at.run()

            assert [s.value for s in at.success] == ["楽天の商品情報を取得しました"]

            at.run()

        assert not at.exception
        assert at.success.len == 0


# ===========================================================================
# 保存・読み込み・削除
# ===========================================================================


class TestSaveLoadDelete:
    """Google Sheets（フェイク）への保存・読み込み・削除のテスト。"""

    def test_保存すると成功メッセージが表示されシートに書き込まれる(self):
        """保存名を入力して「💾 保存」を押すと成功メッセージが出て、フェイクシートに書き込まれる。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            widget_by_label(at.text_input, "保存名").set_value("マイ保存1")
            widget_by_label(at.button, "💾 保存").click()
            at.run()

        assert not at.exception
        assert [s.value for s in at.success] == [
            "Google Sheetsへ「マイ保存1」を保存しました。"
        ]
        assert "products" in fake_spreadsheet.sheets
        assert "saved_data" in fake_spreadsheet.sheets

    def test_保存名が空だと警告が出る(self):
        """保存名を入力せずに「💾 保存」を押すと「保存名を入力してください。」の警告が出る。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            widget_by_label(at.button, "💾 保存").click()
            at.run()

        assert not at.exception
        assert [w.value for w in at.warning] == ["保存名を入力してください。"]

    def test_読み込むと保存時の値に戻る(self):
        """商品名を変えてから保存データを読み込むと、保存したときの値に戻る。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            widget_by_label(at.text_input, "保存名").set_value("マイ保存1")
            widget_by_label(at.button, "💾 保存").click()
            at.run()

            widget_by_key_prefix(at.text_input, "name_0_").set_value("一時的な変更")
            at.run()
            assert widget_by_key_prefix(at.text_input, "name_0_").value == "一時的な変更"

            at.button("load_selected_save").click()
            at.run()

        assert not at.exception
        assert [s.value for s in at.success] == [
            "Google Sheetsから設定を読み込みました。"
        ]
        assert widget_by_key_prefix(at.text_input, "name_0_").value == "商品A"

    def test_同名で保存すると上書き確認が出て上書きすると更新される(self):
        """既存と同名で保存すると上書き確認が出て、「上書きする」を押すと上書きされる。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            widget_by_label(at.text_input, "保存名").set_value("マイ保存1")
            widget_by_label(at.button, "💾 保存").click()
            at.run()

            # 別の保存データを作る
            widget_by_key_prefix(at.text_input, "name_0_").set_value("商品X")
            widget_by_label(at.text_input, "保存名").set_value("マイ保存2")
            widget_by_label(at.button, "💾 保存").click()
            at.run()

            # 「マイ保存1」と同名で保存しようとすると上書き確認が出る
            widget_by_label(at.text_input, "保存名").set_value("マイ保存1")
            widget_by_label(at.button, "💾 保存").click()
            at.run()

            assert [w.value for w in at.warning] == [
                "「マイ保存1」は既に保存されています。この保存データを上書きしますか？"
            ]

            at.button("confirm_overwrite_save").click()
            at.run()

        assert not at.exception
        assert [s.value for s in at.success] == [
            "Google Sheetsの「マイ保存1」を上書き保存しました。"
        ]

    def test_上書きをキャンセルすると保存されない(self):
        """上書き確認で「キャンセル」を押すと、上書きされず確認も消える。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            widget_by_label(at.text_input, "保存名").set_value("マイ保存1")
            widget_by_label(at.button, "💾 保存").click()
            at.run()

            widget_by_key_prefix(at.text_input, "name_0_").set_value("商品X")
            widget_by_label(at.text_input, "保存名").set_value("マイ保存2")
            widget_by_label(at.button, "💾 保存").click()
            at.run()

            widget_by_label(at.text_input, "保存名").set_value("マイ保存1")
            widget_by_label(at.button, "💾 保存").click()
            at.run()

            at.button("cancel_overwrite_save").click()
            at.run()

        assert not at.exception
        assert not at.warning
        assert not at.success

    def test_削除すると確認後に一覧から消える(self):
        """「🗑️ 選択したデータを削除」→「削除する」の順で押すと、一覧から削除される。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            widget_by_label(at.text_input, "保存名").set_value("マイ保存1")
            widget_by_label(at.button, "💾 保存").click()
            at.run()

            at.button("delete_selected_save").click()
            at.run()

            assert [w.value for w in at.warning] == [
                "「マイ保存1」を削除しますか？この操作は元に戻せません。"
            ]

            at.button("confirm_delete_save").click()
            at.run()

        assert not at.exception
        assert [s.value for s in at.success] == ["保存データを削除しました。"]
        assert at.session_state["saved_data_records"] == []


# ===========================================================================
# secretsが無い場合の保存
# ===========================================================================


class TestNoSecrets:
    """Secretsが設定されていない場合の保存動作のテスト。"""

    def test_secretsが無い場合保存はGOOGLE_SHEET_ID未設定のエラーになる(self):
        """Secretsが無い状態で保存すると「GOOGLE_SHEET_IDが設定されていません」を含むエラーになる。"""

        at = AppTest.from_file(APP_PATH, default_timeout=30)
        at.run()

        widget_by_label(at.text_input, "保存名").set_value("テスト保存")
        widget_by_label(at.button, "💾 保存").click()
        at.run()

        assert not at.exception
        assert [e.value for e in at.error] == [
            "Google Sheetsへの保存に失敗しました：GOOGLE_SHEET_IDが設定されていません。"
        ]


# ===========================================================================
# 設定
# ===========================================================================


class TestSettings:
    """設定（買いまわり関連の数値）変更が計算結果に反映されるかのテスト。"""

    def test_SPU倍率を変えると計算結果が変わる(self):
        """楽天SPUポイント倍率を変更して計算すると、その値を使った計算結果になる。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()

            widget_by_label(at.number_input, "楽天SPUポイント倍率").set_value(5)
            widget_by_label(at.button, "🧮 計算する").click()
            at.run()

        assert not at.exception

        settings = dict(SETTING_DEFAULTS)
        settings["spu_multiplier"] = 5
        _, _, best = calc_all(INITIAL_PRODUCTS, settings)

        metrics = {m.label: m.value for m in at.metric}
        assert metrics["⭐ 最適な振り分け"] == yen(best["net"])

    def test_買いまわり最大ショップ数を変えると計算結果が変わる(self):
        """買いまわり最大ショップ数を変更して計算すると、その値を使った計算結果になる。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()

            widget_by_label(at.number_input, "買いまわり最大ショップ数").set_value(1)
            widget_by_label(at.button, "🧮 計算する").click()
            at.run()

        assert not at.exception

        settings = dict(SETTING_DEFAULTS)
        settings["max_shops"] = 1
        _, _, best = calc_all(INITIAL_PRODUCTS, settings)

        metrics = {m.label: m.value for m in at.metric}
        assert metrics["⭐ 最適な振り分け"] == yen(best["net"])
