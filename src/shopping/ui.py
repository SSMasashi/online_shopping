"""
画面（UI）の組み立て。

import しただけでは何も表示しない。src/buy_sl.py から main() を呼ぶ。
楽天の取得関数はテストで差し替えられるよう、モジュール経由（rakuten.xxx）で呼ぶ。
"""

import streamlit as st

from shopping import rakuten
from shopping.calc import (
    MAX_PRODUCTS,
    calculate_item_results,
    evaluate,
    find_best,
    rakuten_rate_from_api,
)
from shopping.gsheets_app import (
    delete_named_data_from_google_sheets,
    get_saved_data_options,
    get_secret_or_env,
    load_named_data_from_google_sheets,
    save_named_data_to_google_sheets,
)
from shopping.storage import SETTING_DEFAULTS, make_default_product

# ===========================================================================
# 表示用関数
# ===========================================================================


def yen(v):
    """
    円表示。
    """

    return f"{round(v):,}円"


def point(v):
    """
    ポイント表示。
    """

    return f"{round(v):,}pt"


# ===========================================================================
# 状態の準備
# ===========================================================================


def apply_pending_actions():
    """ボタンで予約された読み込み・削除を、ウィジェットを作る前に反映する。"""

    # 読み込み・削除は、ボタンを押した直後にrerunし、次の実行の先頭で
    # session_stateへ反映する。これによりStreamlitのウィジェットキーと
    # 読み込んだ値が衝突しない。

    if st.session_state.pop("pending_load_save_id", ""):
        pending_id = st.session_state.pop("_pending_load_save_id_value", "")

        try:
            load_named_data_from_google_sheets(pending_id)
            st.session_state["google_sheet_message"] = (
                "success",
                "Google Sheetsから設定を読み込みました。",
            )
        except Exception as e:
            st.session_state["google_sheet_message"] = (
                "error",
                f"Google Sheetsからの読み込みに失敗しました：{e}",
            )

    if st.session_state.get("pending_delete_save_id", False) and st.session_state.pop(
        "pending_delete_confirmed", False
    ):
        pending_id = st.session_state.pop("_pending_delete_save_id_value", "")
        st.session_state.pop("pending_delete_save_id", None)

        try:
            delete_named_data_from_google_sheets(pending_id)
            st.session_state["google_sheet_message"] = ("success", "保存データを削除しました。")
        except Exception as e:
            st.session_state["google_sheet_message"] = (
                "error",
                f"保存データの削除に失敗しました：{e}",
            )


def init_session_state():
    """session_state の初期値を入れる。"""

    if "products" not in st.session_state:
        st.session_state.products = [
            {
                "name": "商品A",
                "ap": 3000,
                "apt": 1,
                "baby": False,
                "rp": 3200,
                "rpt": 5,
                "rurl": "",
            },
            {"name": "商品B", "ap": 5000, "apt": 1, "baby": True, "rp": 4800, "rpt": 8, "rurl": ""},
        ]

    if "widget_version" not in st.session_state:
        st.session_state.widget_version = 0

    if "current_save_id" not in st.session_state:
        st.session_state.current_save_id = ""

    if "current_save_name" not in st.session_state:
        st.session_state.current_save_name = ""

    if "saved_data_records" not in st.session_state:
        st.session_state.saved_data_records = []

    if "selected_saved_data_id" not in st.session_state:
        st.session_state.selected_saved_data_id = ""

    for _key, _default in SETTING_DEFAULTS.items():
        if _key not in st.session_state:
            st.session_state[_key] = _default


# ===========================================================================
# 画面の各部分
# ===========================================================================


def render_header():
    """タイトルと説明。"""

    st.title("🛒 Amazon × 楽天 最安振り分け計算")

    st.caption(
        "各商品をAmazonと楽天市場のどちらで購入すると、"
        "ポイントを含めた実質負担額が安くなるかを計算します。"
    )


def render_settings():
    """楽天買いまわりの設定欄。楽天APIの認証情報はここには表示しない。"""

    #
    # 楽天APIの認証情報はここには表示しない。
    #
    # ===========================================================================

    with st.expander("⚙️ 設定（楽天買いまわり）", expanded=False):
        v = st.session_state.widget_version

        c1, c2, c3, c4 = st.columns(4)

        with c1:
            st.session_state.max_shops = st.number_input(
                "買いまわり最大ショップ数",
                min_value=1,
                max_value=10,
                value=int(st.session_state.max_shops),
                step=1,
                format="%d",
                key=f"max_shops_widget_{v}",
            )

        with c2:
            st.session_state.min_shop_price = st.number_input(
                "買いまわり対象最低金額（税込）",
                min_value=0,
                value=int(st.session_state.min_shop_price),
                step=100,
                format="%d",
                key=f"min_shop_price_widget_{v}",
            )

        with c3:
            st.session_state.bonus_cap = st.number_input(
                "買いまわり特典ポイント上限",
                min_value=0,
                value=int(st.session_state.bonus_cap),
                step=100,
                format="%d",
                key=f"bonus_cap_widget_{v}",
            )

        with c4:
            st.session_state.spu_multiplier = st.number_input(
                "楽天SPUポイント倍率",
                min_value=0,
                max_value=100,
                value=int(st.session_state.spu_multiplier),
                step=1,
                format="%d",
                key=f"spu_multiplier_widget_{v}",
                help=("楽天の商品ごとの還元率に加算します。例：3と設定すると+3倍。"),
            )

        st.caption(
            "※SPUは計算時のみ楽天還元率に加算されます。商品リストの楽天還元%には表示されません。"
        )

        st.caption("※楽天APIから取得した還元率は1倍引いて表示します。")

        st.caption(
            "※楽天APIの認証情報はアプリ画面には表示されません。Streamlit Cloud Secretsから取得します。"
        )


def render_product_list(rakuten_credentials):
    """商品リスト。"""

    st.subheader("商品リスト")

    items = st.session_state.products

    for i, item in enumerate(items):
        render_product_row(i, item, rakuten_credentials)


def render_product_row(i, item, rakuten_credentials):
    """商品1件分の入力欄（商品名・Amazon・楽天・取得ボタン・メッセージ）。"""

    v = st.session_state.widget_version

    # =======================================================================
    # 商品名・削除
    # =======================================================================

    name_col, delete_col = st.columns([9, 1])

    with name_col:
        current_name = item["name"]

        item["name"] = st.text_input(
            "",
            value=current_name,
            placeholder="商品名",
            key=f"name_{i}_{v}",
            label_visibility="collapsed",
        )

    with delete_col:
        if st.button("🗑️", key=f"delete_{i}_{v}"):
            st.session_state.products.pop(i)

            st.session_state.widget_version += 1

            st.rerun()

    # =======================================================================
    # Amazon
    # =======================================================================

    (
        amazon_label,
        amazon_price_label,
        amazon_price,
        amazon_return_label,
        amazon_return,
        baby_col,
        amazon_empty,
    ) = st.columns([1.4, 0.7, 1.5, 0.7, 1.5, 4.2, 1.6])

    with amazon_label:
        st.markdown("**🟧 Amazon**")

    with amazon_price_label:
        st.markdown("価格")

    with amazon_price:
        item["ap"] = st.number_input(
            "",
            min_value=0,
            value=int(item.get("ap", 0)),
            step=100,
            key=f"ap_{i}_{v}",
            label_visibility="collapsed",
        )

    with amazon_return_label:
        st.markdown("還元%")

    with amazon_return:
        item["apt"] = st.number_input(
            "",
            min_value=0,
            max_value=100,
            value=int(item.get("apt", 1)),
            step=1,
            format="%d",
            key=f"apt_{i}_{v}",
            label_visibility="collapsed",
        )

    with baby_col:
        item["baby"] = st.checkbox(
            "らくベビ割（10%OFF）", value=item.get("baby", False), key=f"baby_{i}_{v}"
        )

    # =======================================================================
    # 楽天
    # =======================================================================

    (
        rakuten_label,
        rakuten_price_label,
        rakuten_price,
        rakuten_return_label,
        rakuten_return,
        rakuten_url_input,
        rakuten_url_button,
    ) = st.columns([1.4, 0.7, 1.5, 0.7, 1.5, 4.2, 1.6])

    with rakuten_label:
        st.markdown("**🟥 楽天**")

    with rakuten_price_label:
        st.markdown("価格")

    with rakuten_price:
        item["rp"] = st.number_input(
            "",
            min_value=0,
            value=int(item.get("rp", 0)),
            step=100,
            key=f"rp_{i}_{v}",
            label_visibility="collapsed",
        )

    with rakuten_return_label:
        st.markdown("還元%")

    with rakuten_return:
        item["rpt"] = st.number_input(
            "",
            min_value=0,
            max_value=100,
            value=int(item.get("rpt", 0)),
            step=1,
            format="%d",
            key=f"rpt_{i}_{v}",
            help="通常ポイント1%を除いた倍率を入力します（例: 楽天で5倍なら4）。",
            label_visibility="collapsed",
        )

    with rakuten_url_input:
        item["rurl"] = st.text_input(
            "",
            value=item.get("rurl", ""),
            placeholder="URL",
            key=f"rurl_{i}_{v}",
            label_visibility="collapsed",
        )

    with rakuten_url_button:
        if st.button("取得", key=f"get_rakuten_{i}_{v}", use_container_width=True):
            url = st.session_state.get(f"rurl_{i}_{v}", "").strip()

            if not url:
                item["_message"] = ("warning", "楽天商品URLを入力してください")

            else:
                try:
                    price, point_rate = rakuten.fetch_rakuten_price_and_point(
                        url, *rakuten_credentials
                    )

                    # -------------------------------------------------------
                    # 楽天価格
                    # -------------------------------------------------------

                    display_price = round(price)

                    # -------------------------------------------------------
                    # 楽天還元率（通常の1%を含まない値に変換）
                    # -------------------------------------------------------

                    display_point_rate = rakuten_rate_from_api(point_rate)

                    # -------------------------------------------------------
                    # 商品データを更新
                    # -------------------------------------------------------

                    item["rp"] = display_price

                    item["rpt"] = display_point_rate

                    item["rurl"] = url

                    item["_message"] = ("success", "楽天の商品情報を取得しました")

                    st.session_state.widget_version += 1

                    st.rerun()

                except Exception as e:
                    item["_message"] = ("error", f"取得エラー：{e}")

    # -----------------------------------------------------------------------
    # URL取得メッセージ
    #
    # 行番号ではなく商品自体に持たせるので、商品を削除してもずれない。
    # 一度表示したら消す。
    # -----------------------------------------------------------------------

    message = item.pop("_message", None)

    if message:
        kind, text = message
        {"error": st.error, "warning": st.warning}.get(kind, st.success)(text)

    st.divider()


def render_add_button():
    """商品追加ボタン。"""

    col_a, col_b = st.columns(2)

    with col_a:
        if st.button("＋ 商品を追加"):
            if len(st.session_state.products) < MAX_PRODUCTS:
                st.session_state.products.append(make_default_product())

                st.session_state.widget_version += 1

                st.rerun()

            else:
                st.warning(f"商品は最大{MAX_PRODUCTS}個までです。")


def render_save_section():
    """保存・読み込み・削除のエリア。"""

    st.subheader("💾 保存・読み込み")

    # 保存一覧の取得は、画面表示時に行う。
    # APIエラーが起きても商品入力画面そのものは使えるようにする。
    try:
        saved_records = get_saved_data_options()
        st.session_state.saved_data_records = saved_records
        saved_data_error = ""
    except Exception as e:
        saved_records = st.session_state.get("saved_data_records", [])
        saved_data_error = str(e)

    current_save_name = st.session_state.get("current_save_name", "")

    if current_save_name:
        st.caption(f"現在の保存データ：**{current_save_name}**")
    else:
        st.caption("現在の画面の設定は、まだ保存されていません。")

    render_save_form(saved_records, current_save_name)
    render_overwrite_confirm()
    render_saved_list(saved_records, saved_data_error)
    render_sheet_message()


def render_save_form(saved_records, current_save_name):
    """保存名の入力と保存ボタン。"""

    save_name_col, save_button_col = st.columns([4, 1])

    with save_name_col:
        save_name = st.text_input(
            "保存名", value=current_save_name, placeholder="例：日用品まとめ買い", max_chars=50
        )

    with save_button_col:
        st.write("")
        save_clicked = st.button("💾 保存", use_container_width=True)

    if save_clicked:
        save_name = save_name.strip()

        if not save_name:
            st.session_state["google_sheet_message"] = ("warning", "保存名を入力してください。")
            st.rerun()

        try:
            # 同名保存データの確認。
            matching_record = next(
                (record for record in saved_records if record["name"] == save_name), None
            )

            current_id = st.session_state.get("current_save_id", "")

            # 現在読み込んでいる保存データ自身なら、そのまま上書きする。
            if matching_record and matching_record["save_id"] == current_id:
                try:
                    save_named_data_to_google_sheets(save_name, overwrite_save_id=current_id)
                    st.session_state["google_sheet_message"] = (
                        "success",
                        f"Google Sheetsの「{save_name}」を上書き保存しました。",
                    )
                    st.rerun()
                except Exception as e:
                    st.session_state["google_sheet_message"] = (
                        "error",
                        f"Google Sheetsへの保存に失敗しました：{e}",
                    )
                    st.rerun()

            # 別のデータと同名なら確認を表示する。
            if matching_record:
                st.session_state["pending_save"] = {
                    "name": save_name,
                    "save_id": matching_record["save_id"],
                }
                st.session_state["pending_save_confirmed"] = False
                st.rerun()

            # 新規保存
            save_named_data_to_google_sheets(save_name, overwrite_save_id=None)

            st.session_state["google_sheet_message"] = (
                "success",
                f"Google Sheetsへ「{save_name}」を保存しました。",
            )

            st.rerun()

        except Exception as e:
            st.session_state["google_sheet_message"] = (
                "error",
                f"Google Sheetsへの保存に失敗しました：{e}",
            )
            st.rerun()


def render_overwrite_confirm():
    """同名の保存データがあるときの上書き確認。"""

    pending_save = st.session_state.get("pending_save")

    if pending_save and not st.session_state.get("pending_save_confirmed", False):
        st.warning(
            f"「{pending_save['name']}」は既に保存されています。この保存データを上書きしますか？"
        )

        overwrite_col, cancel_col = st.columns(2)

        with overwrite_col:
            if st.button(
                "上書きする", type="primary", use_container_width=True, key="confirm_overwrite_save"
            ):
                try:
                    save_named_data_to_google_sheets(
                        pending_save["name"], overwrite_save_id=pending_save["save_id"]
                    )

                    st.session_state.pop("pending_save", None)
                    st.session_state.pop("pending_save_confirmed", None)

                    st.session_state["google_sheet_message"] = (
                        "success",
                        f"Google Sheetsの「{pending_save['name']}」を上書き保存しました。",
                    )
                    st.rerun()

                except Exception as e:
                    st.session_state["google_sheet_message"] = (
                        "error",
                        f"Google Sheetsへの保存に失敗しました：{e}",
                    )
                    st.rerun()

        with cancel_col:
            if st.button("キャンセル", use_container_width=True, key="cancel_overwrite_save"):
                st.session_state.pop("pending_save", None)
                st.session_state.pop("pending_save_confirmed", None)
                st.rerun()


def render_saved_list(saved_records, saved_data_error):
    """保存データ一覧と、読み込み・削除のボタン。"""

    if saved_records:
        option_ids = [record["save_id"] for record in saved_records]

        current_id = st.session_state.get("current_save_id", "")

        # selectboxは行番号ではなくsave_idを状態として持たせる。
        # 削除後に一覧の行数が変わっても、古いindexが残ってエラーにならない。
        selected_state = st.session_state.get("selected_saved_data_id", "")

        if selected_state not in option_ids:
            selected_state = current_id if current_id in option_ids else option_ids[0]
            st.session_state.selected_saved_data_id = selected_state

        def saved_option_label(save_id):
            record = next(record for record in saved_records if record["save_id"] == save_id)
            if record.get("saved_at"):
                return f"{record['name']}（{record['saved_at']}）"
            return record["name"]

        selected_save_id = st.selectbox(
            "保存済みデータ",
            options=option_ids,
            format_func=saved_option_label,
            key="selected_saved_data_id",
        )

        load_col, delete_col = st.columns(2)

        with load_col:
            if st.button(
                "📂 選択したデータを読み込む", use_container_width=True, key="load_selected_save"
            ):
                st.session_state["_pending_load_save_id_value"] = selected_save_id
                st.session_state["pending_load_save_id"] = True
                st.rerun()

        with delete_col:
            if st.button(
                "🗑️ 選択したデータを削除", use_container_width=True, key="delete_selected_save"
            ):
                st.session_state["pending_delete_save_id"] = True
                st.session_state["pending_delete_confirmed"] = False
                st.session_state["_pending_delete_save_id_value"] = selected_save_id
                st.rerun()

        # -----------------------------------------------------------------------
        # 削除確認
        # -----------------------------------------------------------------------

        if st.session_state.get("pending_delete_save_id"):
            pending_delete_id = st.session_state.get("_pending_delete_save_id_value", "")

            pending_delete_record = next(
                (record for record in saved_records if record["save_id"] == pending_delete_id), None
            )

            if pending_delete_record:
                st.warning(
                    f"「{pending_delete_record['name']}」を削除しますか？この操作は元に戻せません。"
                )

                confirm_delete_col, cancel_delete_col = st.columns(2)

                with confirm_delete_col:
                    if st.button(
                        "削除する",
                        type="primary",
                        use_container_width=True,
                        key="confirm_delete_save",
                    ):
                        st.session_state["pending_delete_confirmed"] = True
                        st.rerun()

                with cancel_delete_col:
                    if st.button("キャンセル", use_container_width=True, key="cancel_delete_save"):
                        st.session_state.pop("pending_delete_save_id", None)
                        st.session_state.pop("pending_delete_confirmed", None)
                        st.session_state.pop("_pending_delete_save_id_value", None)
                        st.rerun()
            else:
                st.session_state.pop("pending_delete_save_id", None)
                st.session_state.pop("pending_delete_confirmed", None)
                st.session_state.pop("_pending_delete_save_id_value", None)

    else:
        if saved_data_error:
            st.caption(
                "保存済みデータを取得できませんでした。Google Sheetsの接続設定を確認してください。"
            )
        else:
            st.info("保存済みデータはありません。保存名を入力して「💾 保存」を押してください。")


def render_sheet_message():
    """Google Sheets関連のメッセージ。保存・読み込みエリアの直下にだけ表示する。"""

    # 保存・読み込みエリアの直下にだけ表示する。

    google_sheet_message = st.session_state.pop("google_sheet_message", None)

    if google_sheet_message:
        message_type, message_text = google_sheet_message

        if message_type == "success":
            st.success(message_text)
        elif message_type == "warning":
            st.warning(message_text)
        else:
            st.error(message_text)

    st.caption("保存先：Google Sheets")
    st.caption("楽天APIの認証情報はGoogle Sheetsには保存されません。")


# ===========================================================================
# 計算
# ===========================================================================


def current_calc_inputs():
    """計算結果が今の入力に対するものかを判定するための値（表示用の一時データは除く）。"""

    products = [
        {key: value for key, value in item.items() if not key.startswith("_")}
        for item in st.session_state.products
    ]
    settings = {key: st.session_state[key] for key in SETTING_DEFAULTS}

    return products, settings


def calculate_all(items, settings):
    """すべてAmazon・すべて楽天・最適な振り分けを計算する。"""

    args = (
        settings["max_shops"],
        settings["min_shop_price"],
        settings["bonus_cap"],
        settings["spu_multiplier"],
    )

    all_a = evaluate(items, ["A"] * len(items), *args)
    all_r = evaluate(items, ["R"] * len(items), *args)
    best_choices, best = find_best(items, *args)
    item_results = calculate_item_results(items, best_choices, best, settings["spu_multiplier"])

    return {"all_a": all_a, "all_r": all_r, "best": best, "item_results": item_results}


def render_results(all_a, all_r, best, item_results):
    """計算結果を表示する。"""

    st.subheader("🧮 計算結果")

    result_col1, result_col2, result_col3 = st.columns(3)

    with result_col1:
        st.metric("⭐ 最適な振り分け", yen(best["net"]))

    with result_col2:
        st.metric("🟧 すべてAmazon", yen(all_a["net"]))

    with result_col3:
        st.metric("🟥 すべて楽天", yen(all_r["net"]))

    # =========================================================================
    # 商品ごとの購入先
    # =========================================================================

    st.markdown("### 📦 商品ごとの購入先")

    # -------------------------------------------------------------------------
    # ヘッダー
    #
    # 左から:
    #   商品名
    #   購入先
    #   価格
    #   還元倍率
    #   還元ポイント
    #   実質負担額
    # -------------------------------------------------------------------------

    (h_name, h_store, h_price, h_multiplier, h_points, h_net) = st.columns(
        [2.4, 1.4, 1.5, 2.1, 1.6, 1.7]
    )

    with h_name:
        st.markdown("**商品名**")

    with h_store:
        st.markdown("**購入先**")

    with h_price:
        st.markdown("**価格**")

    with h_multiplier:
        st.markdown("**還元倍率**")

    with h_points:
        st.markdown("**還元ポイント**")

    with h_net:
        st.markdown("**実質負担額**")

    # -------------------------------------------------------------------------
    # 商品ごとの結果
    # -------------------------------------------------------------------------

    for result in item_results:
        (row_name, row_store, row_price, row_multiplier, row_points, row_net) = st.columns(
            [2.4, 1.4, 1.5, 2.1, 1.6, 1.7]
        )

        with row_name:
            st.write(result["name"])

        with row_store:
            st.write(result["store"])

        with row_price:
            st.write(yen(result["price"]))

        with row_multiplier:
            st.write(result["multiplier"])

        with row_points:
            st.write(point(result["points"]))

        with row_net:
            st.write(yen(result["net"]))

    # =========================================================================
    # 合計
    # =========================================================================

    st.divider()

    (total_name, total_store, total_price, total_multiplier, total_points_col, total_net) = (
        st.columns([2.4, 1.4, 1.5, 2.1, 1.6, 1.7])
    )

    with total_name:
        st.markdown("**合計**")

    with total_store:
        st.markdown("**購入額**")

    with total_price:
        st.markdown(f"**{yen(best['amazon_paid'] + best['rakuten_paid'])}**")

    with total_multiplier:
        st.markdown("**―**")

    with total_points_col:
        st.markdown(f"**{point(best['total_points'])}**")

    with total_net:
        st.markdown(f"**{yen(best['net'])}**")

    # =========================================================================
    # 詳細計算
    # =========================================================================

    with st.expander("📊 詳細な計算内訳"):
        # ---------------------------------------------------------------------
        # Amazon
        # ---------------------------------------------------------------------

        st.markdown("#### 🟧 Amazon")

        st.write(f"支払額：{yen(best['amazon_paid'])}")

        st.write(f"Amazonポイント：{point(best['amazon_points'])}")

        st.divider()

        # ---------------------------------------------------------------------
        # 楽天
        # ---------------------------------------------------------------------

        st.markdown("#### 🟥 楽天市場")

        st.write(f"税込支払額：{yen(best['rakuten_paid'])}")

        st.write(f"税抜購入額：{yen(best['rakuten_tax_excluded_total'])}")

        st.write(f"楽天通常ポイント：{point(best['rakuten_base_points'])}")

        st.write(f"楽天SPU：+{best['spu_multiplier']}倍")

        st.write(f"買いまわり対象ショップ数：{best['shop_count']}")

        st.write(f"買いまわり特典：+{best['bonus_multiplier']}倍")

        st.write(f"買いまわりポイント：{point(best['bonus'])}")

        st.divider()

        # ---------------------------------------------------------------------
        # 最終結果
        # ---------------------------------------------------------------------

        st.markdown("#### 💰 最終結果")

        st.write(f"支払額合計：{yen(best['amazon_paid'] + best['rakuten_paid'])}")

        st.write(f"ポイント合計：{point(best['total_points'])}")

        st.write(f"**実質負担額：{yen(best['net'])}**")


def render_calc():
    """計算ボタンと計算結果。"""

    # 計算結果は session_state に残し、ほかの入力を触っても消えないようにする。
    # ただし計算後に入力が変わった場合は、古い結果を出さずに再計算を促す。
    if st.button("🧮 計算する", type="primary", use_container_width=True):
        inputs = current_calc_inputs()

        try:
            st.session_state.calc_result = {"inputs": inputs, **calculate_all(*inputs)}
        except ValueError as e:
            st.session_state.pop("calc_result", None)
            st.error(str(e))

    calc_result = st.session_state.get("calc_result")

    if calc_result:
        if calc_result["inputs"] != current_calc_inputs():
            st.info("入力が変わりました。「計算する」を押すと再計算します。")
        else:
            render_results(
                calc_result["all_a"],
                calc_result["all_r"],
                calc_result["best"],
                calc_result["item_results"],
            )


def main():
    """画面全体を組み立てる。"""

    # Secrets は実行のたびに読む（import 時に1回だけ読むと、設定の変更やテストの差し替えが効かない）。
    rakuten_credentials = tuple(
        get_secret_or_env(name)
        for name in ("RAKUTEN_APP_ID", "RAKUTEN_ACCESS_KEY", "RAKUTEN_REFERER")
    )

    # 予約された読み込み・削除と初期化は、ウィジェットを作る前に行う。
    apply_pending_actions()
    init_session_state()

    render_header()
    render_settings()
    render_product_list(rakuten_credentials)
    render_add_button()
    render_save_section()
    render_calc()
