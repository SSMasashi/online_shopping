"""
src/shopping/calc.py のテスト。

リファクタリングで計算結果が変わらないよう、現在の仕様を固定する。
既知の仕様（買いまわりを商品単位で数える、楽天還元率は通常の1%を含まない）も
テストとして明示している。
"""

import pytest

from shopping.calc import (
    MAX_PRODUCTS,
    amazon_cost,
    calculate_item_results,
    calculate_rakuten_bonus,
    calculate_rakuten_shop_count,
    evaluate,
    find_best,
    rakuten_rate_from_api,
    tax_excluded_price,
)


def make_item(name="商品", ap=1000, apt=1, baby=False, rp=1000, rpt=1, rurl="https://example.com"):
    """テスト用の商品dictを作るヘルパー。"""

    return {"name": name, "ap": ap, "apt": apt, "baby": baby, "rp": rp, "rpt": rpt, "rurl": rurl}


# ===========================================================================
# tax_excluded_price
# ===========================================================================


class TestTaxExcludedPrice:
    """tax_excluded_price（税抜価格計算）のテスト。"""

    def test_デフォルト税率10パーセントで税抜価格を計算できる(self):
        """税込1100円はデフォルト税率10%で税抜1000円になる。"""

        assert tax_excluded_price(1100) == pytest.approx(1000.0)

    def test_税率を明示的に指定できる(self):
        """税率8%を指定した場合、税込1080円は税抜1000円になる。"""

        assert tax_excluded_price(1080, tax_rate=0.08) == pytest.approx(1000.0)

    def test_価格が0の場合は0を返す(self):
        """境界値: 価格0円のとき税抜価格も0円。"""

        assert tax_excluded_price(0) == pytest.approx(0.0)

    def test_割り切れない価格でも近似値で一致する(self):
        """1000円 / 1.1 は割り切れないため、pytest.approxで比較する。"""

        assert tax_excluded_price(1000) == pytest.approx(1000 / 1.1)


# ===========================================================================
# amazon_cost
# ===========================================================================


class TestAmazonCost:
    """amazon_cost（Amazon実質価格・ポイント計算）のテスト。"""

    def test_らくベビ割対象外の通常価格とポイント(self):
        """baby=Falseの場合、価格は定価のまま、ポイントは定価×還元率。"""

        item = make_item(ap=1000, apt=5, baby=False)
        price, points = amazon_cost(item)
        assert price == pytest.approx(1000.0)
        assert points == pytest.approx(50.0)

    def test_らくベビ割対象は価格が0_9倍になりポイントも割引後価格基準(self):
        """baby=Trueの場合、価格は10%OFFになり、ポイントも割引後価格から計算される。"""

        item = make_item(ap=1000, apt=5, baby=True)
        price, points = amazon_cost(item)
        assert price == pytest.approx(900.0)
        assert points == pytest.approx(45.0)

    def test_還元率0パーセントならポイントは0(self):
        """境界値: apt=0のときポイントは0円。"""

        item = make_item(ap=1000, apt=0, baby=False)
        price, points = amazon_cost(item)
        assert price == pytest.approx(1000.0)
        assert points == pytest.approx(0.0)

    def test_価格0円なら価格ポイントともに0(self):
        """境界値: ap=0のとき価格・ポイントともに0円。"""

        item = make_item(ap=0, apt=10, baby=False)
        price, points = amazon_cost(item)
        assert price == pytest.approx(0.0)
        assert points == pytest.approx(0.0)


# ===========================================================================
# calculate_rakuten_shop_count
# ===========================================================================


class TestCalculateRakutenShopCount:
    """calculate_rakuten_shop_count（買いまわり対象ショップ数）のテスト。"""

    def test_楽天かつ対象金額以上の商品だけ数える(self):
        """Amazon選択の商品や金額未満の商品はカウントされない。"""

        items = [
            make_item(rp=2000),  # A -> 対象外
            make_item(rp=1500),  # R かつ min以上 -> 対象
            make_item(rp=1000),  # R だが min未満 -> 対象外
        ]
        choices = ("A", "R", "R")
        count = calculate_rakuten_shop_count(items, choices, min_shop_price=1500)
        assert count == 1

    def test_境界値_rpがmin_shop_priceと等しい場合は対象に含む(self):
        """境界値: rp == min_shop_price のとき、以上判定でカウント対象になる。"""

        items = [make_item(rp=1500)]
        choices = ("R",)
        count = calculate_rakuten_shop_count(items, choices, min_shop_price=1500)
        assert count == 1

    def test_境界値_rpがmin_shop_priceより1円少ない場合は対象外(self):
        """境界値: rp が min_shop_price をわずかに下回るとカウントされない。"""

        items = [make_item(rp=1499)]
        choices = ("R",)
        count = calculate_rakuten_shop_count(items, choices, min_shop_price=1500)
        assert count == 0

    def test_商品が0件の場合は0を返す(self):
        """境界値: 商品リストが空のとき0を返す。"""

        assert calculate_rakuten_shop_count([], (), min_shop_price=1500) == 0

    def test_全てAmazon選択なら0を返す(self):
        """楽天で購入する商品が1つもなければ0になる。"""

        items = [make_item(rp=5000), make_item(rp=5000)]
        choices = ("A", "A")
        assert calculate_rakuten_shop_count(items, choices, min_shop_price=100) == 0

    def test_同じショップの商品でも商品ごとに個別にカウントする(self):
        """
        仕様固定: rurl（ショップ）が同一でも、商品単位で買いまわり件数を数える。
        これは実際のショップ数と一致しない可能性がある既知の仕様だが、
        現状の振る舞いとして明示的に固定する。
        """

        items = [
            make_item(rp=2000, rurl="https://same-shop.example.com"),
            make_item(rp=2000, rurl="https://same-shop.example.com"),
        ]
        choices = ("R", "R")
        count = calculate_rakuten_shop_count(items, choices, min_shop_price=1000)
        # 同一ショップ(rurl)でも2件としてカウントされる
        assert count == 2


# ===========================================================================
# calculate_rakuten_bonus
# ===========================================================================


class TestCalculateRakutenBonus:
    """calculate_rakuten_bonus（楽天買いまわり特典ポイント）のテスト。"""

    def test_通常のボーナス計算(self):
        """税込11000円・3ショップ・上限5・上限額1000円のとき、期待通りのボーナスになる。"""

        result = calculate_rakuten_bonus(
            rakuten_tax_included_total=11000, eligible_shops=3, max_shops=5, bonus_cap=1000
        )
        # shop_count=3, multiplier=2, tax_excluded=10000, bonus=10000*2/100=200
        assert result["shop_count"] == 3
        assert result["bonus_multiplier"] == 2
        assert result["tax_excluded_total"] == pytest.approx(10000.0)
        assert result["bonus"] == pytest.approx(200.0)

    def test_境界値_対象ショップ数が0なら倍率も0でボーナスも0(self):
        """境界値: eligible_shops=0のとき、倍率が負にならず0に丸められボーナスも0。"""

        result = calculate_rakuten_bonus(
            rakuten_tax_included_total=5000, eligible_shops=0, max_shops=5, bonus_cap=1000
        )
        assert result["shop_count"] == 0
        assert result["bonus_multiplier"] == 0
        assert result["bonus"] == pytest.approx(0.0)

    def test_境界値_対象ショップ数がmax_shopsを超える場合はmax_shopsで頭打ち(self):
        """境界値: eligible_shopsがmax_shopsより多くても、倍率計算はmax_shops基準。"""

        result = calculate_rakuten_bonus(
            rakuten_tax_included_total=11000, eligible_shops=10, max_shops=3, bonus_cap=10000
        )
        assert result["shop_count"] == 3
        assert result["bonus_multiplier"] == 2

    def test_境界値_ボーナスがちょうど上限と一致する場合は上限額そのまま(self):
        """境界値: 計算結果がbonus_capと完全一致する場合でもそのままの値になる。"""

        # tax_excluded_total=10000, multiplier=4 -> bonus=400 = bonus_cap
        result = calculate_rakuten_bonus(
            rakuten_tax_included_total=11000, eligible_shops=5, max_shops=5, bonus_cap=400
        )
        assert result["bonus_multiplier"] == 4
        assert result["bonus"] == pytest.approx(400.0)

    def test_境界値_ボーナスが上限を超える場合は上限額に丸められる(self):
        """境界値: 計算結果がbonus_capを超える場合はbonus_capで頭打ちになる。"""

        # 上と同条件でbonus_capだけ100に下げると400ではなく100になる
        result = calculate_rakuten_bonus(
            rakuten_tax_included_total=11000, eligible_shops=5, max_shops=5, bonus_cap=100
        )
        assert result["bonus_multiplier"] == 4
        assert result["bonus"] == pytest.approx(100.0)

    def test_楽天税込合計が0円ならボーナスも0(self):
        """境界値: 楽天での購入が0円（購入なし）のときボーナスも0円。"""

        result = calculate_rakuten_bonus(
            rakuten_tax_included_total=0, eligible_shops=0, max_shops=5, bonus_cap=1000
        )
        assert result["bonus"] == pytest.approx(0.0)


# ===========================================================================
# evaluate
# ===========================================================================


class TestEvaluate:
    """evaluate（組み合わせごとの実質負担額計算）のテスト。"""

    def test_Amazonが得な例では選択Aの方がRより実質負担が小さい(self):
        """
        手計算:
        Amazon: 価格1100円, 還元1% -> 実質1045円
        楽天  : 税込1200円, ポイント1%, 買いまわり対象外 -> 実質1189.0909...円
        """

        item = make_item(ap=1100, apt=5, baby=False, rp=1200, rpt=1)

        result_a = evaluate(
            items=[item],
            choices=("A",),
            max_shops=5,
            min_shop_price=1500,
            bonus_cap=1000,
            spu_multiplier=0,
        )
        result_r = evaluate(
            items=[item],
            choices=("R",),
            max_shops=5,
            min_shop_price=1500,
            bonus_cap=1000,
            spu_multiplier=0,
        )

        assert result_a["net"] == pytest.approx(1045.0)
        assert result_r["net"] == pytest.approx(1189.090909090909)
        assert result_a["net"] < result_r["net"]

    def test_楽天が得な例では選択Rの方がAより実質負担が小さい(self):
        """
        手計算:
        Amazon: 価格1200円, 還元1% -> 実質1188円
        楽天  : 税込1000円, ポイント10%, 買いまわり対象外 -> 実質909.0909...円
        """

        item = make_item(ap=1200, apt=1, baby=False, rp=1000, rpt=10)

        result_a = evaluate(
            items=[item],
            choices=("A",),
            max_shops=5,
            min_shop_price=1500,
            bonus_cap=1000,
            spu_multiplier=0,
        )
        result_r = evaluate(
            items=[item],
            choices=("R",),
            max_shops=5,
            min_shop_price=1500,
            bonus_cap=1000,
            spu_multiplier=0,
        )

        assert result_a["net"] == pytest.approx(1188.0)
        assert result_r["net"] == pytest.approx(909.0909090909091)
        assert result_r["net"] < result_a["net"]

    def test_買いまわりで楽天にまとめた方が得になる例(self):
        """
        手計算(いずれもspu_multiplier=0, min_shop_price=1000, max_shops=2, bonus_cap=10000):
        item1=item2: ap=2200(還元0%), rp=2000(還元1%)

        両方Amazon: 4400円
        片方だけ楽天(買いまわり不成立): 4181.818181...円
        両方楽天(買いまわり成立、倍率1): 3927.272727...円 <- 最安
        """

        item = make_item(ap=2200, apt=0, baby=False, rp=2000, rpt=1)
        items = [item, item]

        result_aa = evaluate(
            items, ("A", "A"), max_shops=2, min_shop_price=1000, bonus_cap=10000, spu_multiplier=0
        )
        result_ar = evaluate(
            items, ("A", "R"), max_shops=2, min_shop_price=1000, bonus_cap=10000, spu_multiplier=0
        )
        result_rr = evaluate(
            items, ("R", "R"), max_shops=2, min_shop_price=1000, bonus_cap=10000, spu_multiplier=0
        )

        assert result_aa["net"] == pytest.approx(4400.0)
        assert result_ar["net"] == pytest.approx(4181.818181818182)
        assert result_rr["net"] == pytest.approx(3927.2727272727275)
        assert result_rr["bonus_multiplier"] == 1
        assert result_rr["net"] < result_ar["net"] < result_aa["net"]

    def test_商品が0件の場合は支払いもポイントも0(self):
        """境界値: 商品が1件もない場合、支払額・ポイント・netすべて0になる。"""

        result = evaluate(
            [], (), max_shops=5, min_shop_price=1000, bonus_cap=1000, spu_multiplier=0
        )
        assert result["net"] == pytest.approx(0.0)
        assert result["total_points"] == pytest.approx(0.0)
        assert result["amazon_paid"] == pytest.approx(0.0)
        assert result["rakuten_paid"] == pytest.approx(0.0)

    def test_spu_multiplierが加算されて楽天ポイントが増える(self):
        """spu_multiplierを指定すると、楽天商品ポイント倍率にそのまま加算される。"""

        item = make_item(rp=1100, rpt=1)
        result_without_spu = evaluate(
            [item], ("R",), max_shops=5, min_shop_price=999999, bonus_cap=1000, spu_multiplier=0
        )
        result_with_spu = evaluate(
            [item], ("R",), max_shops=5, min_shop_price=999999, bonus_cap=1000, spu_multiplier=9
        )

        # 税抜1000円 * (1+9)/100 = 100円
        assert result_with_spu["rakuten_base_points"] == pytest.approx(100.0)
        assert result_with_spu["rakuten_base_points"] > result_without_spu["rakuten_base_points"]

    def test_babyがTrueだとAmazon実質負担がより小さくなる(self):
        """らくベビ割対象の商品はAmazon選択時の実質負担が対象外より小さくなる。"""

        item_baby = make_item(ap=1000, apt=5, baby=True)
        item_normal = make_item(ap=1000, apt=5, baby=False)

        result_baby = evaluate(
            [item_baby], ("A",), max_shops=5, min_shop_price=1000, bonus_cap=1000, spu_multiplier=0
        )
        result_normal = evaluate(
            [item_normal],
            ("A",),
            max_shops=5,
            min_shop_price=1000,
            bonus_cap=1000,
            spu_multiplier=0,
        )

        assert result_baby["net"] == pytest.approx(855.0)  # 900 - 45
        assert result_normal["net"] == pytest.approx(950.0)  # 1000 - 50
        assert result_baby["net"] < result_normal["net"]


# ===========================================================================
# find_best
# ===========================================================================


class TestFindBest:
    """find_best（全組み合わせからの最安探索）のテスト。"""

    def test_Amazonが得な商品ではA選択が選ばれる(self):
        """1商品でAmazonが得な場合、選択肢はAになる。"""

        item = make_item(ap=1100, apt=5, baby=False, rp=1200, rpt=1)
        choices, best = find_best(
            [item], max_shops=5, min_shop_price=1500, bonus_cap=1000, spu_multiplier=0
        )
        assert choices == ("A",)
        assert best["net"] == pytest.approx(1045.0)

    def test_楽天が得な商品ではR選択が選ばれる(self):
        """1商品で楽天が得な場合、選択肢はRになる。"""

        item = make_item(ap=1200, apt=1, baby=False, rp=1000, rpt=10)
        choices, best = find_best(
            [item], max_shops=5, min_shop_price=1500, bonus_cap=1000, spu_multiplier=0
        )
        assert choices == ("R",)
        assert best["net"] == pytest.approx(909.0909090909091)

    def test_買いまわりで両方楽天にまとめる組み合わせが選ばれる(self):
        """2商品とも楽天にまとめた方が買いまわり特典で得になる場合、RRが選ばれる。"""

        item = make_item(ap=2200, apt=0, baby=False, rp=2000, rpt=1)
        choices, best = find_best(
            [item, item], max_shops=2, min_shop_price=1000, bonus_cap=10000, spu_multiplier=0
        )
        assert choices == ("R", "R")
        assert best["net"] == pytest.approx(3927.2727272727275)

    def test_netが同値の場合は先に見つかった組み合わせが選ばれる(self):
        """
        仕様固定: 全ての組み合わせのnetが同額になる場合、
        itertools.product("AR", repeat=n)の並び順で最初に見つかった組み合わせ
        （すべてAmazon選択）が採用される。
        """

        # ap == rp かつ apt == rpt == 0 なので、どの組み合わせでもnetは同じになる
        item = make_item(ap=1500, apt=0, baby=False, rp=1500, rpt=0)
        items = [item, item]

        choices, best = find_best(
            items, max_shops=1, min_shop_price=999999, bonus_cap=0, spu_multiplier=0
        )

        # product("AR", repeat=2) の並び: AA, AR, RA, RR のうち最初のAAが採用される
        assert choices == ("A", "A")
        assert best["net"] == pytest.approx(3000.0)

    def test_商品が0件の場合は空の組み合わせが返る(self):
        """境界値: 商品が0件の場合、選択肢は空タプルでnetは0になる。"""

        choices, best = find_best(
            [], max_shops=5, min_shop_price=1000, bonus_cap=1000, spu_multiplier=0
        )
        assert choices == ()
        assert best["net"] == pytest.approx(0.0)


# ===========================================================================
# calculate_item_results
# ===========================================================================


class TestCalculateItemResults:
    """calculate_item_results（商品ごとのポイント配分・表示）のテスト。"""

    def test_商品ごとのポイント合計がevaluateのtotal_pointsと一致する(self):
        """
        買いまわりボーナスは楽天商品の税抜価格に比例配分されるため、
        商品ごとのpointsを合計するとevaluateのtotal_pointsと一致するはず。
        """

        item1 = make_item(name="商品1", rp=2000, rpt=1)
        item2 = make_item(name="商品2", rp=2000, rpt=1)
        item3 = make_item(name="商品3", rp=1000, rpt=1)
        items = [item1, item2, item3]
        choices = ("R", "R", "R")

        best = evaluate(
            items, choices, max_shops=3, min_shop_price=1500, bonus_cap=10000, spu_multiplier=0
        )
        results = calculate_item_results(items, choices, best, spu_multiplier=0)

        total_points_from_items = sum(r["points"] for r in results)
        assert total_points_from_items == pytest.approx(best["total_points"])
        # 手計算: base=18.1818+18.1818+9.0909, bonus=45.4545 -> 合計90.9090909...
        assert best["total_points"] == pytest.approx(90.9090909090909)

    def test_買いまわり対象外の商品も配分された買いまわり倍率が表示に反映される(self):
        """
        買いまわりボーナスは全楽天商品の税抜価格比で配分されるので、
        min_shop_price未満の商品も、配分を受けた分の倍率を表示する。
        """

        item1 = make_item(name="商品1", rp=2000, rpt=1)
        item2 = make_item(name="商品2", rp=2000, rpt=1)
        item3 = make_item(name="商品3", rp=1000, rpt=1)  # min_shop_price未満
        items = [item1, item2, item3]
        choices = ("R", "R", "R")

        best = evaluate(
            items, choices, max_shops=3, min_shop_price=1500, bonus_cap=10000, spu_multiplier=0
        )
        results = calculate_item_results(items, choices, best, spu_multiplier=0)

        # 対象外の商品も配分(約9.0909pt)を受け取り、表示にも+1倍が出る
        assert results[2]["multiplier"] == "2倍(1+0+1)"
        assert results[2]["points"] == pytest.approx(18.18181818181818)

        assert results[0]["multiplier"] == "2倍(1+0+1)"
        assert results[0]["points"] == pytest.approx(36.36363636363636)

    def test_ボーナスが上限で頭打ちのときは実際の配分倍率を小数で表示する(self):
        """
        2商品(税抜各2000円)で倍率1、本来のボーナス40ptが上限20ptで頭打ち。
        実際の買いまわり倍率は 20 / 4000 * 100 = 0.5倍 になる。
        """

        items = [make_item(name="商品1", rp=2200, rpt=1), make_item(name="商品2", rp=2200, rpt=1)]
        choices = ("R", "R")

        best = evaluate(
            items, choices, max_shops=10, min_shop_price=1000, bonus_cap=20, spu_multiplier=0
        )
        results = calculate_item_results(items, choices, best, spu_multiplier=0)

        assert best["bonus"] == pytest.approx(20.0)
        for r in results:
            # 税抜2000円 * 1% = 20pt + 配分10pt
            assert r["points"] == pytest.approx(30.0)
            assert r["multiplier"] == "1.5倍(1+0+0.5)"

    def test_Amazon商品の倍率表示は還元率をそのまま整数化した文字列になる(self):
        """Amazon商品の倍率表示は int(apt) を使った "n倍" 形式になる。"""

        item = make_item(name="Amazon商品", ap=1000, apt=5, baby=False)
        items = [item]
        choices = ("A",)

        best = evaluate(
            items, choices, max_shops=5, min_shop_price=1000, bonus_cap=1000, spu_multiplier=0
        )
        results = calculate_item_results(items, choices, best, spu_multiplier=0)

        assert results[0]["multiplier"] == "5倍"
        assert results[0]["store"] == "🟧 Amazon"
        assert results[0]["price"] == pytest.approx(1000.0)
        assert results[0]["points"] == pytest.approx(50.0)
        assert results[0]["net"] == pytest.approx(950.0)

    def test_商品名が空の場合は無題と表示される(self):
        """境界値: item["name"]が空文字の場合、表示名は "(無題)" になる。"""

        item = make_item(name="", ap=1000, apt=5, baby=False)
        items = [item]
        choices = ("A",)

        best = evaluate(
            items, choices, max_shops=5, min_shop_price=1000, bonus_cap=1000, spu_multiplier=0
        )
        results = calculate_item_results(items, choices, best, spu_multiplier=0)

        assert results[0]["name"] == "(無題)"

    def test_楽天でボーナスが0円のときは買いまわりポイントが加算されない(self):
        """境界値: 買いまわりボーナスが発生しない場合、pointsは商品ポイントのみになる。"""

        item = make_item(name="単品", rp=1100, rpt=1)
        items = [item]
        choices = ("R",)

        best = evaluate(
            items, choices, max_shops=5, min_shop_price=999999, bonus_cap=1000, spu_multiplier=0
        )
        results = calculate_item_results(items, choices, best, spu_multiplier=0)

        assert best["bonus"] == pytest.approx(0.0)
        # 税抜1000円 * 1% = 10円
        assert results[0]["points"] == pytest.approx(10.0)
        assert results[0]["multiplier"] == "1倍(1+0+0)"

    def test_商品が0件の場合は空リストが返る(self):
        """境界値: 商品が0件の場合、結果リストも空になる。"""

        best = evaluate([], (), max_shops=5, min_shop_price=1000, bonus_cap=1000, spu_multiplier=0)
        results = calculate_item_results([], (), best, spu_multiplier=0)
        assert results == []


# ===========================================================================
# rakuten_rate_from_api
# ===========================================================================


class TestRakutenRateFromApi:
    """楽天APIのpointRateを、通常の1%を除いた還元率に変換するテスト。"""

    @pytest.mark.parametrize("point_rate, expected", [(1, 0), (2, 1), (4, 3), (10, 9)])
    def test_通常の1パーセント分を差し引く(self, point_rate, expected):
        assert rakuten_rate_from_api(point_rate) == expected

    def test_1未満の値は0にする(self):
        assert rakuten_rate_from_api(0) == 0


# ===========================================================================
# 商品数の上限
# ===========================================================================


class TestMaxProducts:
    """組み合わせ探索が 2^n で増えるのを防ぐ商品数の上限のテスト。"""

    def test_上限は15件(self):
        assert MAX_PRODUCTS == 15

    def test_上限ちょうどの商品数なら探索できる(self):
        items = [make_item(name=f"商品{i}", ap=1000, rp=1100) for i in range(MAX_PRODUCTS)]
        choices, best = find_best(
            items, max_shops=10, min_shop_price=1000, bonus_cap=7000, spu_multiplier=0
        )
        assert len(choices) == MAX_PRODUCTS

    def test_上限を超える商品数ではValueErrorになる(self):
        items = [make_item(name=f"商品{i}") for i in range(MAX_PRODUCTS + 1)]
        with pytest.raises(ValueError, match="15"):
            find_best(items, max_shops=10, min_shop_price=1000, bonus_cap=7000, spu_multiplier=0)
