"""
画面（UI）の組み立て。

import しただけでは何も表示しない。src/buy_sl.py から main() を呼ぶ。
楽天の取得関数はテストで差し替えられるよう、モジュール経由（rakuten.xxx）で呼ぶ。

画面の構成:
    サイドバー : 設定（楽天の買いまわり・SPU）、保存・読み込み
    メイン     : 商品リスト（1商品1カード）→ 計算ボタン → 計算結果（買い物リスト）
"""

import streamlit as st

from shopping import rakuten
from shopping.calc import (
    MAX_PRODUCTS,
    available_stores,
    calculate_item_results,
    evaluate,
    find_best,
    quantity,
    rakuten_rate_from_api,
)
from shopping.gsheets_app import (
    delete_named_data_from_google_sheets,
    get_saved_data_options,
    get_secret_or_env,
    load_named_data_from_google_sheets,
    save_named_data_to_google_sheets,
)
from shopping.storage import MAX_SAVE_NAME_LENGTH, SETTING_DEFAULTS, make_default_product

PRICE_HELP = "0のままにすると、その店では「扱いなし」として計算します。"

RAKUTEN_RATE_HELP = "通常ポイント1%を除いた倍率を入力します（例: 楽天で5倍なら4）。"


def sample_products():
    """起動時に表示するサンプルの商品。"""

    return [
        {**make_default_product(), "name": "商品A", "ap": 3000, "rp": 3200, "rpt": 5},
        {**make_default_product(), "name": "商品B", "ap": 5000, "baby": True, "rp": 4800, "rpt": 8},
    ]


# ===========================================================================
# 表示用関数
# ===========================================================================


def yen(v):
    """円表示。"""

    return f"{round(v):,}円"


def point(v):
    """ポイント表示。"""

    return f"{round(v):,}pt"


def show_message(message):
    """(種類, 文章) の形のメッセージを表示する。"""

    kind, text = message
    {"error": st.error, "warning": st.warning}.get(kind, st.success)(text)


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
            st.session_state["google_sheet_message"] = ("success", "保存データを読み込みました。")
        except Exception as e:
            st.session_state["google_sheet_message"] = ("error", f"読み込みに失敗しました：{e}")

    if st.session_state.get("pending_delete_save_id", False) and st.session_state.pop(
        "pending_delete_confirmed", False
    ):
        pending_id = st.session_state.pop("_pending_delete_save_id_value", "")
        st.session_state.pop("pending_delete_save_id", None)

        try:
            delete_named_data_from_google_sheets(pending_id)
            st.session_state["google_sheet_message"] = ("success", "保存データを削除しました。")
        except Exception as e:
            st.session_state["google_sheet_message"] = ("error", f"削除に失敗しました：{e}")


def init_session_state():
    """session_state の初期値を入れる。"""

    defaults = {
        "widget_version": 0,
        "save_as_version": 0,
        "current_save_id": "",
        "current_save_name": "",
        "saved_data_records": [],
        "selected_saved_data_id": "",
        **SETTING_DEFAULTS,
    }

    if "products" not in st.session_state:
        st.session_state.products = sample_products()

    for key, default in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default


# ===========================================================================
# サイドバー（設定・保存）
# ===========================================================================


def render_settings():
    """楽天の買いまわり・SPUの設定。"""

    v = st.session_state.widget_version

    st.subheader("⚙️ 設定")

    st.session_state.max_shops = st.number_input(
        "買いまわり最大ショップ数",
        min_value=1,
        max_value=10,
        value=int(st.session_state.max_shops),
        step=1,
        format="%d",
        key=f"max_shops_widget_{v}",
        help="買いまわりでポイント倍率が上がるショップ数の上限です。",
    )

    st.session_state.min_shop_price = st.number_input(
        "買いまわり対象の最低金額（税込）",
        min_value=0,
        value=int(st.session_state.min_shop_price),
        step=100,
        format="%d",
        key=f"min_shop_price_widget_{v}",
        help="1商品（個数分の合計）がこの金額以上なら、買いまわりの1ショップとして数えます。",
    )

    st.session_state.bonus_cap = st.number_input(
        "買いまわり特典ポイント上限",
        min_value=0,
        value=int(st.session_state.bonus_cap),
        step=100,
        format="%d",
        key=f"bonus_cap_widget_{v}",
    )

    st.session_state.spu_multiplier = st.number_input(
        "楽天SPUポイント倍率",
        min_value=0,
        max_value=100,
        value=int(st.session_state.spu_multiplier),
        step=1,
        format="%d",
        key=f"spu_multiplier_widget_{v}",
        help="楽天の商品ごとの還元率に、計算時だけ加算します。例：3と設定すると+3倍。",
    )


def render_save_section():
    """保存・読み込み・削除。"""

    st.subheader("💾 保存・読み込み")

    # 保存一覧が取れなくても、商品の入力や計算はできるようにする。
    try:
        saved_records = get_saved_data_options()
        st.session_state.saved_data_records = saved_records
        saved_data_error = ""
    except Exception as e:
        saved_records = st.session_state.get("saved_data_records", [])
        saved_data_error = str(e)

    current_save_name = st.session_state.get("current_save_name", "")

    if current_save_name:
        st.caption(f"編集中のデータ：**{current_save_name}**")
    else:
        st.caption("まだ保存されていません。")

    render_save_buttons(saved_records)
    render_saved_list(saved_records, saved_data_error)
    render_sheet_message()


def _save_and_rerun(save_name, overwrite_save_id, success_text):
    try:
        save_named_data_to_google_sheets(save_name, overwrite_save_id=overwrite_save_id)
        st.session_state["google_sheet_message"] = ("success", success_text)
        st.session_state.save_as_version += 1
    except Exception as e:
        st.session_state["google_sheet_message"] = ("error", f"保存に失敗しました：{e}")

    st.rerun()


def render_save_buttons(saved_records):
    """「上書き保存」と「別名で保存」。"""

    current_id = st.session_state.get("current_save_id", "")
    current_name = st.session_state.get("current_save_name", "")

    if st.button(
        "💾 上書き保存",
        key="overwrite_save",
        use_container_width=True,
        disabled=not current_id,
        help="読み込み中（または保存したばかり）のデータを、今の内容で上書きします。",
    ):
        _save_and_rerun(current_name, current_id, f"「{current_name}」を上書き保存しました。")

    new_name = st.text_input(
        "別名で保存する名前",
        placeholder="例：日用品まとめ買い",
        max_chars=MAX_SAVE_NAME_LENGTH,
        key=f"save_as_name_{st.session_state.save_as_version}",
    )

    if st.button("📝 別名で保存", key="save_as", use_container_width=True):
        new_name = new_name.strip()

        if not new_name:
            st.session_state["google_sheet_message"] = (
                "warning",
                "保存する名前を入力してください。",
            )
            st.rerun()

        if any(record["name"] == new_name for record in saved_records):
            st.session_state["google_sheet_message"] = (
                "warning",
                f"「{new_name}」は既にあります。別の名前にするか、読み込んでから上書き保存してください。",
            )
            st.rerun()

        _save_and_rerun(new_name, None, f"「{new_name}」として保存しました。")


def render_saved_list(saved_records, saved_data_error):
    """保存データの一覧と、読み込み・削除。"""

    if not saved_records:
        if saved_data_error:
            st.caption(
                "保存データを取得できませんでした。Google Sheetsの接続設定を確認してください。"
            )
        else:
            st.caption("保存データはまだありません。")
        return

    option_ids = [record["save_id"] for record in saved_records]
    records_by_id = {record["save_id"]: record for record in saved_records}
    current_id = st.session_state.get("current_save_id", "")

    # selectbox は行番号ではなく save_id を状態として持つ。
    # 削除で一覧の行数が変わっても、古い位置が残ってエラーにならない。
    if st.session_state.get("selected_saved_data_id", "") not in option_ids:
        st.session_state.selected_saved_data_id = (
            current_id if current_id in option_ids else option_ids[0]
        )

    def label(save_id):
        record = records_by_id[save_id]
        return f"{record['name']}（{record['saved_at']}）" if record["saved_at"] else record["name"]

    selected_save_id = st.selectbox(
        "保存済みデータ", options=option_ids, format_func=label, key="selected_saved_data_id"
    )

    load_col, delete_col = st.columns(2)

    with load_col:
        if st.button("📂 読み込む", use_container_width=True, key="load_selected_save"):
            st.session_state["_pending_load_save_id_value"] = selected_save_id
            st.session_state["pending_load_save_id"] = True
            st.rerun()

    with delete_col:
        if st.button("🗑️ 削除", use_container_width=True, key="delete_selected_save"):
            st.session_state["pending_delete_save_id"] = True
            st.session_state["pending_delete_confirmed"] = False
            st.session_state["_pending_delete_save_id_value"] = selected_save_id
            st.rerun()

    render_delete_confirm(records_by_id)


def render_delete_confirm(records_by_id):
    if not st.session_state.get("pending_delete_save_id"):
        return

    record = records_by_id.get(st.session_state.get("_pending_delete_save_id_value", ""))

    if record is None:
        for key in (
            "pending_delete_save_id",
            "pending_delete_confirmed",
            "_pending_delete_save_id_value",
        ):
            st.session_state.pop(key, None)
        return

    st.warning(f"「{record['name']}」を削除しますか？この操作は元に戻せません。")

    confirm_col, cancel_col = st.columns(2)

    with confirm_col:
        if st.button(
            "削除する", type="primary", use_container_width=True, key="confirm_delete_save"
        ):
            st.session_state["pending_delete_confirmed"] = True
            st.rerun()

    with cancel_col:
        if st.button("キャンセル", use_container_width=True, key="cancel_delete_save"):
            for key in (
                "pending_delete_save_id",
                "pending_delete_confirmed",
                "_pending_delete_save_id_value",
            ):
                st.session_state.pop(key, None)
            st.rerun()


def render_sheet_message():
    message = st.session_state.pop("google_sheet_message", None)

    if message:
        show_message(message)


# ===========================================================================
# 商品リスト
# ===========================================================================


def render_header():
    st.title("🛒 Amazon × 楽天 最安振り分け計算")

    st.caption(
        "商品ごとに、Amazonと楽天市場のどちらで買うとポイント込みの実質負担が安くなるかを計算します。"
        "設定と保存は左のサイドバーにあります。"
    )


def render_product_list(rakuten_credentials):
    st.subheader("🛍️ 商品リスト")

    for i, item in enumerate(st.session_state.products):
        render_product_card(i, item, rakuten_credentials)

    render_add_button()


def render_product_card(i, item, rakuten_credentials):
    """商品1件分のカード（商品名・個数・Amazon・楽天）。"""

    v = st.session_state.widget_version

    with st.container(border=True):
        name_col, qty_col, delete_col = st.columns([6, 1.5, 0.7], vertical_alignment="bottom")

        with name_col:
            item["name"] = st.text_input(
                "商品名", value=item["name"], placeholder="例：おむつ Lサイズ", key=f"name_{i}_{v}"
            )

        with qty_col:
            item["qty"] = st.number_input(
                "個数", min_value=1, max_value=99, value=quantity(item), step=1, key=f"qty_{i}_{v}"
            )

        with delete_col:
            if st.button("🗑️", key=f"delete_{i}_{v}", help="この商品を削除"):
                st.session_state.products.pop(i)
                st.session_state.widget_version += 1
                st.rerun()

        amazon_col, rakuten_col = st.columns(2, gap="medium")

        with amazon_col:
            render_amazon_inputs(i, item, v)

        with rakuten_col:
            render_rakuten_inputs(i, item, v, rakuten_credentials)

        if not available_stores(item):
            st.caption("⚠️ Amazonにも楽天にも価格が入っていないため、計算から除きます。")

        # 楽天の取得メッセージは商品自体に持たせる（行番号だとずれるため）。一度表示したら消す。
        message = item.pop("_message", None)

        if message:
            show_message(message)


def render_amazon_inputs(i, item, v):
    st.markdown("**🟧 Amazon**")

    price_col, rate_col = st.columns([3, 2])

    with price_col:
        item["ap"] = st.number_input(
            "価格（円）",
            min_value=0,
            value=int(item.get("ap", 0)),
            step=100,
            key=f"ap_{i}_{v}",
            help=PRICE_HELP,
        )

    with rate_col:
        item["apt"] = st.number_input(
            "還元%",
            min_value=0,
            max_value=100,
            value=int(item.get("apt", 1)),
            step=1,
            format="%d",
            key=f"apt_{i}_{v}",
        )

    item["baby"] = st.checkbox(
        "らくベビ割（10%OFF）", value=item.get("baby", False), key=f"baby_{i}_{v}"
    )

    item["aurl"] = st.text_input(
        "商品URL（メモ）",
        value=item.get("aurl", ""),
        placeholder="https://www.amazon.co.jp/...",
        key=f"aurl_{i}_{v}",
    )


def render_rakuten_inputs(i, item, v, rakuten_credentials):
    st.markdown("**🟥 楽天**")

    price_col, rate_col = st.columns([3, 2])

    with price_col:
        item["rp"] = st.number_input(
            "価格（円）",
            min_value=0,
            value=int(item.get("rp", 0)),
            step=100,
            key=f"rp_{i}_{v}",
            help=PRICE_HELP,
        )

    with rate_col:
        item["rpt"] = st.number_input(
            "還元%",
            min_value=0,
            max_value=100,
            value=int(item.get("rpt", 0)),
            step=1,
            format="%d",
            key=f"rpt_{i}_{v}",
            help=RAKUTEN_RATE_HELP,
        )

    url_key = f"rurl_{i}_{v}"

    item["rurl"] = st.text_input(
        "商品URL",
        value=item.get("rurl", ""),
        placeholder="貼り付けると価格と還元%を自動取得",
        key=url_key,
        on_change=fetch_rakuten_on_url_change,
        args=(i, url_key, rakuten_credentials),
        help="楽天の商品ページのURLを貼り付けると、楽天APIから価格と還元%を取得します。",
    )


def fetch_rakuten_on_url_change(i, url_key, rakuten_credentials):
    """楽天のURL欄が変わったら、価格と還元%を取得する（画面の再実行の前に呼ばれる）。"""

    item = st.session_state.products[i]
    url = str(st.session_state.get(url_key, "")).strip()
    item["rurl"] = url

    if not url:
        return

    try:
        price, point_rate = rakuten.fetch_rakuten_price_and_point(url, *rakuten_credentials)
    except Exception as e:
        item["_message"] = ("error", f"取得エラー：{e}")
        return

    item["rp"] = round(price)
    item["rpt"] = rakuten_rate_from_api(point_rate)
    item["_message"] = ("success", "楽天の価格と還元%を取得しました")

    # 入力欄の key を付け替えて、取得した値を表示させる。
    st.session_state.widget_version += 1


def render_add_button():
    is_full = len(st.session_state.products) >= MAX_PRODUCTS

    if st.button("＋ 商品を追加", key="add_product", use_container_width=True, disabled=is_full):
        st.session_state.products.append(make_default_product())
        st.session_state.widget_version += 1
        st.rerun()

    if is_full:
        st.caption(f"商品は最大{MAX_PRODUCTS}個までです。")


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


def calculate_all(products, settings):
    """最適な振り分けと、すべてAmazon・すべて楽天の場合を計算する。"""

    included = [item for item in products if available_stores(item)]
    excluded = [item["name"] or "(無題)" for item in products if not available_stores(item)]

    args = (
        settings["max_shops"],
        settings["min_shop_price"],
        settings["bonus_cap"],
        settings["spu_multiplier"],
    )

    # 片方の店で扱いのない商品があるときは「すべて〇〇」は成り立たない。
    all_a = None
    all_r = None

    if all("A" in available_stores(item) for item in included):
        all_a = evaluate(included, ["A"] * len(included), *args)

    if all("R" in available_stores(item) for item in included):
        all_r = evaluate(included, ["R"] * len(included), *args)

    best_choices, best = find_best(included, *args)
    item_results = calculate_item_results(included, best_choices, best, settings["spu_multiplier"])

    return {
        "all_a": all_a,
        "all_r": all_r,
        "best": best,
        "item_results": item_results,
        "excluded": excluded,
    }


def render_calc():
    # 計算結果は session_state に残し、ほかの入力を触っても消えないようにする。
    # ただし計算後に入力が変わった場合は、古い結果を出さずに再計算を促す。
    if st.button("🧮 計算する", type="primary", use_container_width=True, key="calculate"):
        inputs = current_calc_inputs()

        try:
            st.session_state.calc_result = {"inputs": inputs, **calculate_all(*inputs)}
        except ValueError as e:
            st.session_state.pop("calc_result", None)
            st.error(str(e))

    calc_result = st.session_state.get("calc_result")

    if not calc_result:
        return

    if calc_result["inputs"] != current_calc_inputs():
        st.info("入力が変わりました。「計算する」を押すと再計算します。")
        return

    render_results(calc_result)


def render_results(result):
    best = result["best"]
    item_results = result["item_results"]

    st.subheader("🧮 計算結果")

    if result["excluded"]:
        st.warning("価格が入っていないため計算から除いた商品：" + "、".join(result["excluded"]))

    if not item_results:
        st.info("価格が入力された商品がありません。")
        return

    render_summary(best, result["all_a"], result["all_r"])
    render_shopping_list(item_results)

    with st.expander("📋 商品ごとの内訳"):
        render_item_table(item_results, best)

    with st.expander("📊 詳細な計算内訳"):
        render_calc_details(best)


def render_summary(best, all_a, all_r):
    """お得額と、最適・すべてAmazon・すべて楽天の実質負担。"""

    comparisons = [
        (label, other["net"] - best["net"])
        for label, other in (("すべて楽天", all_r), ("すべてAmazon", all_a))
        if other is not None
    ]
    savings = [f"{label}より **{yen(diff)}**" for label, diff in comparisons if diff >= 0.5]

    if savings:
        st.success("最適な振り分けなら、" + "、".join(savings) + " お得です。")

    best_col, amazon_col, rakuten_col = st.columns(3)

    with best_col:
        st.metric("⭐ 最適な振り分け（実質負担）", yen(best["net"]))

    for col, label, other, store in (
        (amazon_col, "🟧 すべてAmazon", all_a, "Amazon"),
        (rakuten_col, "🟥 すべて楽天", all_r, "楽天"),
    ):
        with col:
            if other is None:
                st.metric(label, "―", help=f"{store}で扱いのない商品があるため計算できません。")
            else:
                st.metric(
                    label,
                    yen(other["net"]),
                    delta=f"最適より +{yen(other['net'] - best['net'])}",
                    delta_color="off",
                )


def render_shopping_list(item_results):
    """店ごとの買い物リスト。URLがあれば商品ページへのリンクボタンを付ける。"""

    st.markdown("#### 🛒 買い物リスト")

    amazon_col, rakuten_col = st.columns(2, gap="medium")

    for col, store_code, title in (
        (amazon_col, "A", "🟧 Amazonで買うもの"),
        (rakuten_col, "R", "🟥 楽天で買うもの"),
    ):
        rows = [r for r in item_results if r["store_code"] == store_code]

        with col, st.container(border=True):
            subtotal = sum(r["price"] for r in rows)
            st.markdown(f"**{title}**（{len(rows)}点・{yen(subtotal)}）")

            if not rows:
                st.caption("なし")

            for r in rows:
                text_col, link_col = st.columns([3, 1], vertical_alignment="center")

                with text_col:
                    st.markdown(
                        f"{r['name']} × {r['qty']}  \n"
                        f"{yen(r['price'])}・{point(r['points'])}（{r['multiplier']}）"
                    )

                with link_col:
                    if r["url"].startswith(("https://", "http://")):
                        st.link_button("開く", r["url"], use_container_width=True)


def render_item_table(item_results, best):
    rows = [
        {
            "商品名": r["name"],
            "購入先": r["store"],
            "個数": r["qty"],
            "価格": yen(r["price"]),
            "還元倍率": r["multiplier"],
            "還元ポイント": point(r["points"]),
            "実質負担額": yen(r["net"]),
        }
        for r in item_results
    ]
    rows.append(
        {
            "商品名": "合計",
            "購入先": "",
            "個数": sum(r["qty"] for r in item_results),
            "価格": yen(best["amazon_paid"] + best["rakuten_paid"]),
            "還元倍率": "",
            "還元ポイント": point(best["total_points"]),
            "実質負担額": yen(best["net"]),
        }
    )

    st.dataframe(rows, hide_index=True, use_container_width=True)


def render_calc_details(best):
    st.markdown("#### 🟧 Amazon")
    st.write(f"支払額：{yen(best['amazon_paid'])}")
    st.write(f"Amazonポイント：{point(best['amazon_points'])}")

    st.divider()

    st.markdown("#### 🟥 楽天市場")
    st.write(f"税込支払額：{yen(best['rakuten_paid'])}")
    st.write(f"税抜購入額：{yen(best['rakuten_tax_excluded_total'])}")
    st.write(f"楽天通常ポイント：{point(best['rakuten_base_points'])}")
    st.write(f"楽天SPU：+{best['spu_multiplier']}倍")
    st.write(f"買いまわり対象ショップ数：{best['shop_count']}")
    st.write(f"買いまわり特典：+{best['bonus_multiplier']}倍")
    st.write(f"買いまわりポイント：{point(best['bonus'])}")

    st.divider()

    st.markdown("#### 💰 最終結果")
    st.write(f"支払額合計：{yen(best['amazon_paid'] + best['rakuten_paid'])}")
    st.write(f"ポイント合計：{point(best['total_points'])}")
    st.write(f"**実質負担額：{yen(best['net'])}**")


# ===========================================================================
# 画面全体
# ===========================================================================


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

    # 設定は計算より先に反映させる必要があるので先に処理する。
    with st.sidebar:
        render_settings()

    render_header()
    render_product_list(rakuten_credentials)
    render_calc()

    # 保存は商品カードの処理より後に行う。入力欄の変更と保存ボタンのクリックが
    # 同じ再実行で届いたときも、変更後の値で保存するため。
    # サイドバーは処理の順番に関係なく左側に表示される。
    with st.sidebar:
        st.divider()
        render_save_section()
