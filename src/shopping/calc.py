"""
Amazon / 楽天の振り分け計算ロジック。

Streamlit に依存しない純粋な計算関数だけを置く。
"""

from itertools import product

# 組み合わせ探索は 2^n 通りになるため、商品数に上限を設ける。
MAX_PRODUCTS = 15

# 消費税率。楽天のポイントは税抜価格にかかる。
TAX_RATE = 0.10

# らくベビ割（Amazon）の対象商品は10%OFF。
BABY_DISCOUNT_RATE = 0.9


# ===========================================================================
# 楽天還元率
# ===========================================================================


def rakuten_rate_from_api(point_rate):
    """
    楽天APIの pointRate（通常ポイント1%を含む倍率）を、
    アプリで扱う還元率（通常の1%を含まない）に変換する。
    """

    return max(int(point_rate) - 1, 0)


# ===========================================================================
# 金額計算
# ===========================================================================


def tax_excluded_price(price, tax_rate=TAX_RATE):
    """
    税込価格から税抜価格を計算する。
    """

    return price / (1 + tax_rate)


def amazon_cost(item):
    """
    Amazonの実質価格を計算。

    らくベビ割対象の場合は10%OFF。

    Amazon還元ポイントは、
    10%OFF後の価格を基準に計算。
    """

    price = item["ap"] * BABY_DISCOUNT_RATE if item["baby"] else item["ap"]

    points = price * (item["apt"] / 100)

    return price, points


# ===========================================================================
# 楽天買いまわり
# ===========================================================================


def calculate_rakuten_shop_count(items, choices, min_shop_price):
    """
    楽天で購入する商品のうち、
    買いまわり対象金額以上の商品数を返す。
    """

    eligible = 0

    for item, choice in zip(items, choices):
        if choice != "R":
            continue

        if item["rp"] >= min_shop_price:
            eligible += 1

    return eligible


def calculate_rakuten_bonus(rakuten_tax_included_total, eligible_shops, max_shops, bonus_cap):
    """
    楽天買いまわり特典ポイントを計算。
    """

    shop_count = min(eligible_shops, max_shops)

    bonus_multiplier = max(shop_count - 1, 0)

    rakuten_tax_excluded_total = tax_excluded_price(rakuten_tax_included_total)

    bonus = rakuten_tax_excluded_total * bonus_multiplier / 100

    bonus = min(bonus, bonus_cap)

    return {
        "shop_count": shop_count,
        "bonus_multiplier": bonus_multiplier,
        "tax_excluded_total": rakuten_tax_excluded_total,
        "bonus": bonus,
    }


# ===========================================================================
# 総合計算
# ===========================================================================


def evaluate(items, choices, max_shops, min_shop_price, bonus_cap, spu_multiplier):
    """
    指定された購入先の組み合わせについて
    実質負担額を計算する。
    """

    amazon_paid = 0.0
    amazon_points = 0.0

    rakuten_paid = 0.0
    rakuten_base_points = 0.0

    for item, choice in zip(items, choices):
        # -------------------------------------------------------------------
        # Amazon
        # -------------------------------------------------------------------

        if choice == "A":
            paid, points = amazon_cost(item)

            amazon_paid += paid
            amazon_points += points

        # -------------------------------------------------------------------
        # 楽天
        # -------------------------------------------------------------------

        else:
            rakuten_paid += item["rp"]

            tax_excluded = tax_excluded_price(item["rp"])

            effective_rakuten_rate = item["rpt"] + spu_multiplier

            rakuten_base_points += tax_excluded * (effective_rakuten_rate / 100)

    # -----------------------------------------------------------------------
    # 楽天買いまわり
    # -----------------------------------------------------------------------

    eligible_shops = calculate_rakuten_shop_count(items, choices, min_shop_price)

    rakuten_info = calculate_rakuten_bonus(
        rakuten_tax_included_total=rakuten_paid,
        eligible_shops=eligible_shops,
        max_shops=max_shops,
        bonus_cap=bonus_cap,
    )

    # -----------------------------------------------------------------------
    # 合計
    # -----------------------------------------------------------------------

    total_paid = amazon_paid + rakuten_paid

    total_points = amazon_points + rakuten_base_points + rakuten_info["bonus"]

    net = total_paid - total_points

    return {
        "net": net,
        "shop_count": rakuten_info["shop_count"],
        "bonus_multiplier": rakuten_info["bonus_multiplier"],
        "bonus": rakuten_info["bonus"],
        "total_points": total_points,
        "amazon_points": amazon_points,
        "rakuten_base_points": rakuten_base_points,
        "amazon_paid": amazon_paid,
        "rakuten_paid": rakuten_paid,
        "rakuten_tax_excluded_total": rakuten_info["tax_excluded_total"],
        "spu_multiplier": spu_multiplier,
    }


# ===========================================================================
# 最適解探索
# ===========================================================================


def find_best(items, max_shops, min_shop_price, bonus_cap, spu_multiplier):
    """
    Amazon / 楽天の全組み合わせを調べ、
    実質負担額が最も安い組み合わせを探す。
    """

    if len(items) > MAX_PRODUCTS:
        raise ValueError(f"商品は最大{MAX_PRODUCTS}個までです（現在{len(items)}個）。")

    best = None
    best_choices = None

    for choices in product("AR", repeat=len(items)):
        result = evaluate(items, choices, max_shops, min_shop_price, bonus_cap, spu_multiplier)

        if best is None or result["net"] < best["net"]:
            best = result
            best_choices = choices

    return (best_choices, best)


# ===========================================================================
# 商品ごとのポイント計算
# ===========================================================================


def _format_rate(rate):
    """倍率を小数第1位までの文字列にする（整数なら小数点なし）。"""

    return f"{round(rate, 1):g}"


def calculate_item_results(items, choices, best, spu_multiplier):
    """
    商品ごとの

        支払価格
        還元ポイント
        実質負担額
        還元倍率

    を計算する。

    楽天買いまわりポイントは、
    全楽天商品の税抜価格に応じて比例配分する。

    これにより、

        商品ごとの還元ポイント合計
        =
        全体のポイント合計

    となる。
    """

    results = []

    # -----------------------------------------------------------------------
    # 楽天商品の税抜価格合計
    # -----------------------------------------------------------------------

    rakuten_tax_excluded_total = 0.0

    for item, choice in zip(items, choices):
        if choice == "R":
            rakuten_tax_excluded_total += tax_excluded_price(item["rp"])

    # -----------------------------------------------------------------------
    # 買いまわりポイント
    # -----------------------------------------------------------------------

    total_rakuten_bonus = float(best["bonus"])

    # 配分した買いまわりポイントを税抜価格あたりの倍率に直したもの。
    # 上限で頭打ちになると bonus_multiplier より小さくなる。
    buyaround_rate = 0.0

    if rakuten_tax_excluded_total > 0:
        buyaround_rate = total_rakuten_bonus / rakuten_tax_excluded_total * 100

    # -----------------------------------------------------------------------
    # 商品ごとの計算
    # -----------------------------------------------------------------------

    for item, choice in zip(items, choices):
        name = item["name"] or "(無題)"

        # ===================================================================
        # Amazon
        # ===================================================================

        if choice == "A":
            paid, base_points = amazon_cost(item)

            total_points = base_points

            net = paid - total_points

            multiplier = int(item["apt"])

            results.append(
                {
                    "name": name,
                    "store": "🟧 Amazon",
                    "price": paid,
                    "multiplier": f"{multiplier}倍",
                    "points": total_points,
                    "net": net,
                }
            )

        # ===================================================================
        # 楽天
        # ===================================================================

        else:
            paid = float(item["rp"])

            tax_excluded = tax_excluded_price(paid)

            # ---------------------------------------------------------------
            # 商品ポイント + SPU
            # ---------------------------------------------------------------

            product_rate = float(item["rpt"])

            spu_rate = float(spu_multiplier)

            base_points = tax_excluded * (product_rate + spu_rate) / 100

            # ---------------------------------------------------------------
            # 買いまわりポイント
            #
            # 現在の全体計算ロジックでは、
            # 楽天購入商品の税抜合計を基準にしているため、
            # 各楽天商品の税抜価格に比例して配分する。
            # ---------------------------------------------------------------

            buyaround_points = 0.0

            if rakuten_tax_excluded_total > 0 and total_rakuten_bonus > 0:
                buyaround_points = total_rakuten_bonus * tax_excluded / rakuten_tax_excluded_total

            total_points = base_points + buyaround_points

            net = paid - total_points

            total_multiplier = product_rate + spu_rate + buyaround_rate

            detail = (
                f"{_format_rate(total_multiplier)}倍"
                f"({_format_rate(product_rate)}"
                f"+{_format_rate(spu_rate)}"
                f"+{_format_rate(buyaround_rate)})"
            )

            results.append(
                {
                    "name": name,
                    "store": "🟥 楽天",
                    "price": paid,
                    "multiplier": detail,
                    "points": total_points,
                    "net": net,
                }
            )

    return results
