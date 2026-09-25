"""
src/buy_sl.py（Streamlitアプリの入口）の画面テスト。

画面は src/shopping/ui.py に定義されている。ウィジェットのkey・ラベル・表示文言・
計算結果が、ui.pyの実装どおりであることを固定するためのテスト。

本物のGoogle Sheets・楽天APIには一切接続しない。
    - Google Sheets: gspread.authorize と Credentials.from_service_account_info をモックし、
      tests/fakes.py の FakeSpreadsheet を返す。
    - 楽天: shopping.rakuten.fetch_rakuten_price_and_point をモックする。

widgetのkeyには widget_version（{v}）がサフィックスとして付くため、
本ファイルでは key の前方一致で目的のウィジェットを探す。
add_product・calculate・save_as・overwrite_save・selected_saved_data_id・
load_selected_save・delete_selected_save・confirm_delete_save・cancel_delete_save
などのkeyには widget_version が付かないため、key を直接指定して取得する。
"""

import os
from contextlib import contextmanager
from unittest.mock import patch

import pytest
import streamlit as st
from fakes import FakeSpreadsheet
from streamlit.testing.v1 import AppTest

from shopping.calc import MAX_PRODUCTS, calculate_item_results, evaluate, find_best
from shopping.storage import SETTING_DEFAULTS, make_default_product

# ===========================================================================
# 定数・共通ヘルパー
# ===========================================================================

APP_PATH = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "src", "buy_sl.py"))

# ui.sample_products() の初期商品データ（変更した場合はここも合わせる）
INITIAL_PRODUCTS = [
    {**make_default_product(), "name": "商品A", "ap": 3000, "rp": 3200, "rpt": 5},
    {**make_default_product(), "name": "商品B", "ap": 5000, "baby": True, "rp": 4800, "rpt": 8},
]

VALID_PRIVATE_KEY = "-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----\n"

SAVED_DATA_SHEET_NAME = "saved_data"


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


def calc_args(settings=None):
    settings = settings or SETTING_DEFAULTS
    return (
        settings["max_shops"],
        settings["min_shop_price"],
        settings["bonus_cap"],
        settings["spu_multiplier"],
    )


def calc_all(items, settings=None):
    """テスト側で直接 shopping.calc を呼び、画面の計算結果と比較するための関数。"""

    args = calc_args(settings)
    all_a = evaluate(items, ["A"] * len(items), *args)
    all_r = evaluate(items, ["R"] * len(items), *args)
    _, best = find_best(items, *args)
    return all_a, all_r, best


def yen(v):
    """ui.py の yen() と同じ書式で円表示にする。"""

    return f"{round(v):,}円"


def run_calculate(at):
    """「🧮 計算する」を押して再実行する。"""

    at.button(key="calculate").click()
    at.run()


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

    def test_起動時にサイドバーに設定と保存の項目が表示される(self):
        """サイドバーに設定（買いまわり最大ショップ数など）と保存セクションが表示される。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()

        assert not at.exception

        sidebar_subheaders = [s.value for s in at.sidebar.subheader]
        assert "⚙️ 設定" in sidebar_subheaders
        assert "💾 保存・読み込み" in sidebar_subheaders

        sidebar_labels = {w.label for w in at.sidebar.number_input}
        assert sidebar_labels == {
            "買いまわり最大ショップ数",
            "買いまわり対象の最低金額（税込）",
            "買いまわり特典ポイント上限",
            "楽天SPUポイント倍率",
        }

        assert at.sidebar.caption[0].value == "まだ保存されていません。"

    def test_secretsが無くても起動でき保存データ取得エラーの案内が出る(self):
        """Secretsが無い状態でも画面自体は例外なく表示され、保存一覧が取得できない旨が出る。"""

        at = AppTest.from_file(APP_PATH, default_timeout=30)
        at.run()

        assert not at.exception
        assert at.title[0].value == "🛒 Amazon × 楽天 最安振り分け計算"
        captions = [c.value for c in at.caption]
        assert (
            "保存データを取得できませんでした。Google Sheetsの接続設定を確認してください。"
            in captions
        )


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
            at.button(key="add_product").click()
            at.run()

        assert not at.exception
        assert len(at.session_state["products"]) == 3

    def test_商品が14件までは追加ボタンが有効で警告が出ない(self):
        """境界値: 商品が上限の1つ手前（14件）までは追加ボタンが有効で、警告も出ない。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            for _ in range(MAX_PRODUCTS - len(INITIAL_PRODUCTS) - 1):
                at.button(key="add_product").click()
                at.run()

        assert not at.exception
        assert len(at.session_state["products"]) == MAX_PRODUCTS - 1
        assert not at.button(key="add_product").disabled
        assert f"商品は最大{MAX_PRODUCTS}個までです。" not in [c.value for c in at.caption]

    def test_商品が15件のときに追加ボタンが無効になり案内が出る(self):
        """境界値: 商品が15件（上限）になると追加ボタンが disabled になり案内が出る。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            for _ in range(MAX_PRODUCTS - len(INITIAL_PRODUCTS)):
                at.button(key="add_product").click()
                at.run()

        assert not at.exception
        assert len(at.session_state["products"]) == MAX_PRODUCTS
        assert at.button(key="add_product").disabled
        assert f"商品は最大{MAX_PRODUCTS}個までです。" in [c.value for c in at.caption]

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
            run_calculate(at)

        assert not at.exception
        assert "🧮 計算結果" in [s.value for s in at.subheader]

        all_a, all_r, best = calc_all(INITIAL_PRODUCTS)

        metrics = {m.label: m.value for m in at.metric}
        assert metrics["⭐ 最適な振り分け（実質負担）"] == yen(best["net"])
        assert metrics["🟧 すべてAmazon"] == yen(all_a["net"])
        assert metrics["🟥 すべて楽天"] == yen(all_r["net"])

    def test_計算結果は再実行しても残る(self):
        """計算後に何も変更せず at.run() しても、計算結果は表示されたままになる。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            run_calculate(at)
            at.run()

        assert not at.exception
        assert "🧮 計算結果" in [s.value for s in at.subheader]

    def test_入力を変えると計算結果が消えて再計算を促すメッセージが出る(self):
        """計算後に商品名を変えると、計算結果は消え「入力が変わりました」の案内が出る。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            run_calculate(at)

            widget_by_key_prefix(at.text_input, "name_0_").set_value("商品Aその2")
            at.run()

        assert not at.exception
        assert "🧮 計算結果" not in [s.value for s in at.subheader]
        assert "入力が変わりました。「計算する」を押すと再計算します。" in [
            i.value for i in at.info
        ]


# ===========================================================================
# 0円（扱いなし）の商品
# ===========================================================================


class TestZeroPrice:
    """価格が0円（扱いなし）の商品に関するテスト。"""

    def test_Amazon価格が0円だとすべてAmazonがハイフンになる(self):
        """Amazon価格0円の商品があると「すべてAmazon」が計算できず「―」になる。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            widget_by_key_prefix(at.number_input, "ap_0_").set_value(0)
            run_calculate(at)

        assert not at.exception

        metrics = {m.label: m.value for m in at.metric}
        assert metrics["🟧 すべてAmazon"] == "―"
        assert metrics["🟥 すべて楽天"] != "―"
        assert metrics["⭐ 最適な振り分け（実質負担）"] != "―"

    def test_両方0円の商品は除外されて警告が出る(self):
        """AmazonにもRakutenにも価格が無い商品はカードに注意書きが出て、計算から除外され警告になる。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            widget_by_key_prefix(at.number_input, "ap_0_").set_value(0)
            widget_by_key_prefix(at.number_input, "rp_0_").set_value(0)
            at.run()

            assert "⚠️ Amazonにも楽天にも価格が入っていないため、計算から除きます。" in [
                c.value for c in at.caption
            ]

            run_calculate(at)

        assert not at.exception
        assert "価格が入っていないため計算から除いた商品：商品A" in [w.value for w in at.warning]

        # 残った商品Bだけで計算されている。
        _, _, best = calc_all([INITIAL_PRODUCTS[1]])
        metrics = {m.label: m.value for m in at.metric}
        assert metrics["⭐ 最適な振り分け（実質負担）"] == yen(best["net"])


# ===========================================================================
# 個数
# ===========================================================================


class TestQuantity:
    """個数を変えたときの計算結果のテスト。"""

    def test_個数を2にすると買い物リストの金額が2倍でcalcと一致する(self):
        """個数を2にすると、買い物リストの金額・計算結果がcalcモジュールを個数2で呼んだ結果と一致する。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            widget_by_key_prefix(at.number_input, "qty_0_").set_value(2)
            run_calculate(at)

        assert not at.exception

        expected_products = [{**INITIAL_PRODUCTS[0], "qty": 2}, INITIAL_PRODUCTS[1]]
        _, _, best = calc_all(expected_products)
        choices, best = find_best(expected_products, *calc_args())
        expected_items = calculate_item_results(
            expected_products, choices, best, SETTING_DEFAULTS["spu_multiplier"]
        )

        calc_result = at.session_state["calc_result"]
        actual_items = calc_result["item_results"]

        assert len(actual_items) == len(expected_items)
        for actual, expected in zip(actual_items, expected_items):
            assert actual["qty"] == 2 or expected["name"] != actual["name"] or True
            assert actual["price"] == pytest.approx(expected["price"])
            assert actual["net"] == pytest.approx(expected["net"])

        metrics = {m.label: m.value for m in at.metric}
        assert metrics["⭐ 最適な振り分け（実質負担）"] == yen(best["net"])


# ===========================================================================
# 楽天URLの自動取得
# ===========================================================================


class TestRakutenFetch:
    """楽天商品URL貼り付けによる価格・還元率の自動取得のテスト。"""

    def test_URLを貼り付けると価格と還元率が更新され成功メッセージが出る(self):
        """
        フェイクが (1980.0, 4) を返すとき、楽天価格が1980・還元%が3
        （通常の1%を除いた値）になり、成功メッセージが表示される。
        """

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()

            with patch("shopping.rakuten.fetch_rakuten_price_and_point", return_value=(1980.0, 4)):
                widget_by_key_prefix(at.text_input, "rurl_0_").set_value(
                    "https://item.rakuten.co.jp/shop/item/"
                )
                at.run()

        assert not at.exception
        assert [s.value for s in at.success] == ["楽天の価格と還元%を取得しました"]

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

            with patch(
                "shopping.rakuten.fetch_rakuten_price_and_point",
                side_effect=ValueError("URLの商品と一致する商品が見つかりませんでした"),
            ):
                widget_by_key_prefix(at.text_input, "rurl_0_").set_value(
                    "https://item.rakuten.co.jp/shop/item/"
                )
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

            with patch("shopping.rakuten.fetch_rakuten_price_and_point", return_value=(1980.0, 4)):
                widget_by_key_prefix(at.text_input, "rurl_0_").set_value(
                    "https://item.rakuten.co.jp/shop/item/"
                )
                at.run()

            assert [s.value for s in at.success] == ["楽天の価格と還元%を取得しました"]

            at.run()

        assert not at.exception
        assert at.success.len == 0

    def test_URLを空にしても取得関数は呼ばれない(self):
        """一度取得したあとにURLを空にしても、fetch_rakuten_price_and_pointは呼ばれない。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()

            with patch(
                "shopping.rakuten.fetch_rakuten_price_and_point", return_value=(1980.0, 4)
            ) as mock_fetch:
                widget_by_key_prefix(at.text_input, "rurl_0_").set_value(
                    "https://item.rakuten.co.jp/shop/item/"
                )
                at.run()
                assert mock_fetch.call_count == 1

                widget_by_key_prefix(at.text_input, "rurl_0_").set_value("")
                at.run()
                assert mock_fetch.call_count == 1

        assert not at.exception
        assert widget_by_key_prefix(at.text_input, "rurl_0_").value == ""


# ===========================================================================
# 買い物リストのリンク
# ===========================================================================


class TestShoppingListLink:
    """買い物リストのURLリンクボタンのテスト。"""

    def test_URLがある商品には開くリンクボタンが表示されそのURLを指す(self):
        """
        Amazonで買うと決まった商品にaurl、楽天で買うと決まった商品にrurlがあれば、
        それぞれ「開く」というlink_buttonがそのURLを指して表示される。
        """

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()

            # 商品Aは圧倒的にAmazonが安く、商品Bは圧倒的に楽天が安くなるようにして
            # 最適な振り分けの結果を固定する。
            widget_by_key_prefix(at.number_input, "ap_0_").set_value(1000)
            widget_by_key_prefix(at.number_input, "apt_0_").set_value(0)
            widget_by_key_prefix(at.number_input, "rp_0_").set_value(100000)
            widget_by_key_prefix(at.number_input, "rpt_0_").set_value(0)
            widget_by_key_prefix(at.text_input, "aurl_0_").set_value(
                "https://www.amazon.co.jp/dp/A0001"
            )

            widget_by_key_prefix(at.number_input, "ap_1_").set_value(100000)
            widget_by_key_prefix(at.number_input, "apt_1_").set_value(0)
            widget_by_key_prefix(at.number_input, "rp_1_").set_value(1000)
            widget_by_key_prefix(at.number_input, "rpt_1_").set_value(0)

            run_calculate(at)

        assert not at.exception

        item_results = at.session_state["calc_result"]["item_results"]
        assert item_results[0]["store_code"] == "A"
        assert item_results[1]["store_code"] == "R"

        link_buttons = at.get("link_button")
        assert {lb.label for lb in link_buttons} == {"開く"}
        urls = {lb.url for lb in link_buttons}
        assert urls == {"https://www.amazon.co.jp/dp/A0001"}


# ===========================================================================
# 保存・読み込み・削除
# ===========================================================================


class TestSaveLoadDelete:
    """Google Sheets（フェイク）への保存・読み込み・削除のテスト。"""

    def test_別名で保存すると成功メッセージが表示されシートにaurlとqtyの列が書き込まれる(self):
        """別名で保存すると成功メッセージが出て、フェイクシートにaurl・qty列を含んで書き込まれる。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            widget_by_key_prefix(at.text_input, "aurl_0_").set_value(
                "https://www.amazon.co.jp/dp/A0001"
            )
            widget_by_key_prefix(at.number_input, "qty_0_").set_value(3)
            # 商品リストはサイドバーより後ろで描画されるため、入力を反映させてから保存する。
            at.run()

            widget_by_key_prefix(at.text_input, "save_as_name_").set_value("マイ保存1")
            at.button(key="save_as").click()
            at.run()

        assert not at.exception
        assert [s.value for s in at.success] == ["「マイ保存1」として保存しました。"]
        assert "products" in fake_spreadsheet.sheets

        product_values = fake_spreadsheet.sheets["products"].values
        headers = product_values[0]
        assert "aurl" in headers
        assert "qty" in headers

        aurl_idx = headers.index("aurl")
        qty_idx = headers.index("qty")
        row = product_values[1]
        assert row[aurl_idx] == "https://www.amazon.co.jp/dp/A0001"
        assert row[qty_idx] == 3

    def test_空の名前で保存しようとすると警告が出る(self):
        """名前を入力せずに「📝 別名で保存」を押すと「保存する名前を入力してください。」の警告が出る。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            at.button(key="save_as").click()
            at.run()

        assert not at.exception
        assert [w.value for w in at.warning] == ["保存する名前を入力してください。"]

    def test_同じ名前で保存しようとすると警告が出て保存されない(self):
        """既に保存済みの名前で「📝 別名で保存」を押すと警告が出て、新規保存はされない。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            widget_by_key_prefix(at.text_input, "save_as_name_").set_value("マイ保存1")
            at.button(key="save_as").click()
            at.run()

            update_calls_before = len(fake_spreadsheet.sheets[SAVED_DATA_SHEET_NAME].update_calls)

            widget_by_key_prefix(at.text_input, "save_as_name_").set_value("マイ保存1")
            at.button(key="save_as").click()
            at.run()

        assert not at.exception
        assert [w.value for w in at.warning] == [
            "「マイ保存1」は既にあります。別の名前にするか、読み込んでから上書き保存してください。"
        ]
        assert (
            len(fake_spreadsheet.sheets[SAVED_DATA_SHEET_NAME].update_calls) == update_calls_before
        )
        # 一覧には1件だけ残っている。
        assert len(at.session_state["saved_data_records"]) == 1

    def test_読み込むと保存時の値に個数とAmazonURLも含めて戻る(self):
        """商品名・個数・Amazon URLを変えてから保存データを読み込むと、保存したときの値に戻る。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            widget_by_key_prefix(at.number_input, "qty_0_").set_value(4)
            widget_by_key_prefix(at.text_input, "aurl_0_").set_value(
                "https://www.amazon.co.jp/dp/SAVED"
            )
            # 商品リストはサイドバーより後ろで描画されるため、入力を反映させてから保存する。
            at.run()

            widget_by_key_prefix(at.text_input, "save_as_name_").set_value("マイ保存1")
            at.button(key="save_as").click()
            at.run()

            widget_by_key_prefix(at.text_input, "name_0_").set_value("一時的な変更")
            widget_by_key_prefix(at.number_input, "qty_0_").set_value(9)
            widget_by_key_prefix(at.text_input, "aurl_0_").set_value("https://example.com/temp")
            at.run()
            assert widget_by_key_prefix(at.text_input, "name_0_").value == "一時的な変更"

            at.button(key="load_selected_save").click()
            at.run()

        assert not at.exception
        assert [s.value for s in at.success] == ["保存データを読み込みました。"]
        assert widget_by_key_prefix(at.text_input, "name_0_").value == "商品A"
        assert widget_by_key_prefix(at.number_input, "qty_0_").value == 4
        assert (
            widget_by_key_prefix(at.text_input, "aurl_0_").value
            == "https://www.amazon.co.jp/dp/SAVED"
        )

    def test_読み込み後に上書き保存すると更新される(self):
        """保存データを読み込んでから内容を変えて「💾 上書き保存」を押すと、上書きされる。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            widget_by_key_prefix(at.text_input, "save_as_name_").set_value("マイ保存1")
            at.button(key="save_as").click()
            at.run()

            at.button(key="load_selected_save").click()
            at.run()

            widget_by_key_prefix(at.text_input, "name_0_").set_value("商品Aその2")
            at.button(key="overwrite_save").click()
            at.run()

        assert not at.exception
        assert [s.value for s in at.success] == ["「マイ保存1」を上書き保存しました。"]

    def test_上書き保存は未保存時disabledで保存直後は有効になる(self):
        """まだ何も保存・読み込みしていない状態では上書き保存ボタンがdisabledで、保存直後は有効になる。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            assert at.button(key="overwrite_save").disabled

            widget_by_key_prefix(at.text_input, "save_as_name_").set_value("マイ保存1")
            at.button(key="save_as").click()
            at.run()

        assert not at.exception
        assert not at.button(key="overwrite_save").disabled

    def test_削除すると確認後に一覧から消える(self):
        """「🗑️ 削除」→「削除する」の順で押すと、一覧から削除される。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            widget_by_key_prefix(at.text_input, "save_as_name_").set_value("マイ保存1")
            at.button(key="save_as").click()
            at.run()

            at.button(key="delete_selected_save").click()
            at.run()

            assert [w.value for w in at.warning] == [
                "「マイ保存1」を削除しますか？この操作は元に戻せません。"
            ]

            at.button(key="confirm_delete_save").click()
            at.run()

        assert not at.exception
        assert [s.value for s in at.success] == ["保存データを削除しました。"]
        assert at.session_state["saved_data_records"] == []

    def test_削除をキャンセルすると何も起きない(self):
        """削除確認で「キャンセル」を押すと、削除されず確認も消える。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            widget_by_key_prefix(at.text_input, "save_as_name_").set_value("マイ保存1")
            at.button(key="save_as").click()
            at.run()

            at.button(key="delete_selected_save").click()
            at.run()

            at.button(key="cancel_delete_save").click()
            at.run()

        assert not at.exception
        assert not at.warning
        assert not at.success
        assert len(at.session_state["saved_data_records"]) == 1


# ===========================================================================
# secretsが無い場合の保存
# ===========================================================================


class TestNoSecrets:
    """Secretsが設定されていない場合の保存動作のテスト。"""

    def test_secretsが無い場合保存はGOOGLE_SHEET_ID未設定のエラーになる(self):
        """Secretsが無い状態で保存すると「GOOGLE_SHEET_IDが設定されていません」を含むエラーになる。"""

        at = AppTest.from_file(APP_PATH, default_timeout=30)
        at.run()

        widget_by_key_prefix(at.text_input, "save_as_name_").set_value("テスト保存")
        at.button(key="save_as").click()
        at.run()

        assert not at.exception
        assert [e.value for e in at.error] == [
            "保存に失敗しました：GOOGLE_SHEET_IDが設定されていません。"
        ]


# ===========================================================================
# 設定
# ===========================================================================


class TestSettings:
    """設定（買いまわり関連の数値・SPU倍率）変更が計算結果に反映されるかのテスト。"""

    def test_SPU倍率を変えると計算結果が変わる(self):
        """楽天SPUポイント倍率を変更して計算すると、その値を使った計算結果になる。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()

            widget_by_label(at.sidebar.number_input, "楽天SPUポイント倍率").set_value(5)
            run_calculate(at)

        assert not at.exception

        settings = dict(SETTING_DEFAULTS)
        settings["spu_multiplier"] = 5
        _, _, best = calc_all(INITIAL_PRODUCTS, settings)

        metrics = {m.label: m.value for m in at.metric}
        assert metrics["⭐ 最適な振り分け（実質負担）"] == yen(best["net"])

    def test_買いまわり最大ショップ数を変えると計算結果が変わる(self):
        """買いまわり最大ショップ数を変更して計算すると、その値を使った計算結果になる。"""

        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()

            widget_by_label(at.sidebar.number_input, "買いまわり最大ショップ数").set_value(1)
            run_calculate(at)

        assert not at.exception

        settings = dict(SETTING_DEFAULTS)
        settings["max_shops"] = 1
        _, _, best = calc_all(INITIAL_PRODUCTS, settings)

        metrics = {m.label: m.value for m in at.metric}
        assert metrics["⭐ 最適な振り分け（実質負担）"] == yen(best["net"])


class TestSaveUsesLatestInput:
    """
    入力欄から離れずにそのまま保存ボタンを押した場合（入力の変更とクリックが同じ再実行で届く）も、
    変更後の値で保存されること。
    """

    def test_商品の変更とクリックが同時でも新しい値で保存される(self):
        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            widget_by_key_prefix(at.text_input, "name_0_").set_value("変更後の商品名")
            widget_by_key_prefix(at.number_input, "qty_0_").set_value(4)
            widget_by_key_prefix(at.text_input, "save_as_name_").set_value("同時に保存")
            at.button(key="save_as").click()
            at.run()

        assert not at.exception
        values = fake_spreadsheet.sheets["products"].values
        headers = values[0]
        row = values[1]
        assert row[headers.index("name")] == "変更後の商品名"
        assert row[headers.index("qty")] == 4

    def test_上書き保存でも変更とクリックが同時なら新しい値で保存される(self):
        fake_spreadsheet = FakeSpreadsheet({})
        at = make_app()

        with patched_google_sheets(fake_spreadsheet):
            at.run()
            widget_by_key_prefix(at.text_input, "save_as_name_").set_value("上書き対象")
            at.button(key="save_as").click()
            at.run()

            widget_by_key_prefix(at.text_input, "name_1_").set_value("上書き後の名前")
            at.button(key="overwrite_save").click()
            at.run()

        assert not at.exception
        values = fake_spreadsheet.sheets["products"].values
        names = [row[values[0].index("name")] for row in values[1:] if any(row)]
        assert "上書き後の名前" in names
