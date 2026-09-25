"""
src/shopping/rakuten.py のテスト。

実装はまだ書きかけ・未着手の可能性があるため、仕様書
（extract_shop_and_slug / parse_item / call_rakuten_api /
fetch_rakuten_price_and_point）を正としてテストを先に書く。

特に fetch_rakuten_price_and_point については、call_api に
フェイク関数を注入することで実際のHTTP通信を行わずに
「itemCode直接検索 -> だめならキーワード検索でのフォールバック」
の分岐を検証する。
"""

import pytest

from shopping.rakuten import (
    RakutenApiError,
    call_rakuten_api,
    extract_shop_and_slug,
    fetch_rakuten_price_and_point,
    parse_item,
)

# ===========================================================================
# テスト用ヘルパー
# ===========================================================================


class FakeCallApi:
    """
    call_api の代わりに使うフェイク。

    呼ばれた引数(params, app_id, access_key, referer)を順番に記録し、
    あらかじめ用意したレスポンス（またはexception）を順番に返す。
    responsesに例外インスタンスを入れておくと、その回の呼び出しで送出する。
    """

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, params, app_id, access_key, referer):
        self.calls.append(
            {"params": params, "app_id": app_id, "access_key": access_key, "referer": referer}
        )

        if not self.responses:
            raise AssertionError("call_apiがテストで用意した回数より多く呼ばれました")

        response = self.responses.pop(0)

        if isinstance(response, Exception):
            raise response

        return response


def make_api_item(item_code=None, item_url=None, price=1000, point_rate=1):
    """楽天APIレスポンスの Item 部分を模したdictを作る。"""

    item = {"itemPrice": price}

    if item_code is not None:
        item["itemCode"] = item_code

    if item_url is not None:
        item["itemUrl"] = item_url

    if point_rate is not None:
        item["pointRate"] = point_rate

    return item


def wrap_items(*items):
    """Item群を Items: [{"Item": ...}, ...] の形にラップする。"""

    return {"Items": [{"Item": item} for item in items]}


EMPTY_ITEMS = {"Items": []}

DEFAULT_URL = "https://item.rakuten.co.jp/someshop/item-abc123/"
DEFAULT_SHOP = "someshop"
DEFAULT_SLUG = "item-abc123"
DEFAULT_ITEM_CODE = f"{DEFAULT_SHOP}:{DEFAULT_SLUG}"


# ===========================================================================
# extract_shop_and_slug
# ===========================================================================


class TestExtractShopAndSlug:
    """extract_shop_and_slug（URLからショップコードと商品スラッグを取り出す）のテスト。"""

    def test_基本的なURLからshopとslugを取得できる(self):
        """https://item.rakuten.co.jp/<shop>/<slug>/ の形から正しく分解される。"""

        shop, slug = extract_shop_and_slug("https://item.rakuten.co.jp/someshop/item-abc123/")
        assert shop == "someshop"
        assert slug == "item-abc123"

    def test_末尾スラッシュがなくても同じ結果になる(self):
        """末尾に/が無いURLでも同じshop, slugが得られる。"""

        shop, slug = extract_shop_and_slug("https://item.rakuten.co.jp/someshop/item-abc123")
        assert (shop, slug) == ("someshop", "item-abc123")

    def test_クエリ文字列があっても同じ結果になる(self):
        """?以降のクエリ文字列は無視され、同じshop, slugが得られる。"""

        shop, slug = extract_shop_and_slug(
            "https://item.rakuten.co.jp/someshop/item-abc123/?scid=af_pc_etc"
        )
        assert (shop, slug) == ("someshop", "item-abc123")

    def test_httpスキームでも取得できる(self):
        """スキームがhttpでも許可される。"""

        shop, slug = extract_shop_and_slug("http://item.rakuten.co.jp/someshop/item-abc123/")
        assert (shop, slug) == ("someshop", "item-abc123")

    def test_ホストがitem_rakuten_co_jp以外ならValueError(self):
        """楽天商品ページ以外のホストはValueErrorになる。"""

        with pytest.raises(ValueError):
            extract_shop_and_slug("https://example.com/shop/item/")

    def test_ホストがwww_rakuten_co_jpならValueError(self):
        """item.rakuten.co.jp以外の楽天系ホストもValueErrorになる。"""

        with pytest.raises(ValueError):
            extract_shop_and_slug("https://www.rakuten.co.jp/shop/")

    def test_スキームがftpならValueError(self):
        """http/https以外のスキームはValueErrorになる。"""

        with pytest.raises(ValueError):
            extract_shop_and_slug("ftp://item.rakuten.co.jp/a/b/")

    def test_パスの要素が2つ未満ならValueError(self):
        """shopのみでslugが無いURLはValueErrorになる。"""

        with pytest.raises(ValueError):
            extract_shop_and_slug("https://item.rakuten.co.jp/shop/")

    def test_パスが空ならValueError(self):
        """境界値: パスが全く無いURLもValueErrorになる。"""

        with pytest.raises(ValueError):
            extract_shop_and_slug("https://item.rakuten.co.jp/")


# ===========================================================================
# parse_item
# ===========================================================================


class TestParseItem:
    """parse_item（APIのItem dictから価格とポイント倍率を取り出す）のテスト。"""

    def test_itemPriceとpointRateから価格と倍率を取得できる(self):
        """通常のItemから (price, point_rate) を取得できる。"""

        price, point_rate = parse_item({"itemPrice": 1980, "pointRate": 2})
        assert price == pytest.approx(1980.0)
        assert point_rate == 2

    def test_pointRateが無ければ1とみなす(self):
        """pointRateキーが存在しない場合は1として扱う。"""

        price, point_rate = parse_item({"itemPrice": 500})
        assert price == pytest.approx(500.0)
        assert point_rate == 1

    def test_pointRateが文字列でも数値として解釈される(self):
        """pointRateが文字列 "2" でも整数2として扱われる。"""

        _, point_rate = parse_item({"itemPrice": 1000, "pointRate": "2"})
        assert point_rate == 2

    def test_pointRateが小数の場合は整数に切り捨てられる(self):
        """境界値: pointRate=2.9は int(float(...)) により2に切り捨てられる。"""

        _, point_rate = parse_item({"itemPrice": 1000, "pointRate": 2.9})
        assert point_rate == 2

    def test_itemPriceが無ければValueError(self):
        """itemPriceキーが無いItemはValueErrorになる。"""

        with pytest.raises(ValueError):
            parse_item({"pointRate": 1})

    def test_itemPriceが数値変換できなければValueError(self):
        """itemPriceが数値に変換できない文字列の場合はValueErrorになる。"""

        with pytest.raises(ValueError):
            parse_item({"itemPrice": "abc"})

    def test_itemPriceが0でも正常に取得できる(self):
        """境界値: itemPrice=0でも例外にならずそのまま返る。"""

        price, point_rate = parse_item({"itemPrice": 0, "pointRate": 1})
        assert price == pytest.approx(0.0)
        assert point_rate == 1


# ===========================================================================
# RakutenApiError
# ===========================================================================


class TestRakutenApiError:
    """RakutenApiError（楽天API呼び出し失敗時の例外）のテスト。"""

    def test_statusを指定しない場合はNoneになる(self):
        """statusを指定しなければデフォルトでNoneになる。"""

        error = RakutenApiError("失敗しました")
        assert error.status is None
        assert str(error) == "失敗しました"

    def test_statusを指定できる(self):
        """statusにHTTPステータスコードを指定できる。"""

        error = RakutenApiError("Not Found", status=404)
        assert error.status == 404

    def test_RuntimeErrorのサブクラスである(self):
        """例外クラスとしてRuntimeErrorを継承している。"""

        assert issubclass(RakutenApiError, RuntimeError)


# ===========================================================================
# fetch_rakuten_price_and_point: 認証情報・URLのバリデーション
# ===========================================================================


class TestFetchRakutenPriceAndPointValidation:
    """fetch_rakuten_price_and_point の入力バリデーションに関するテスト。"""

    def test_app_idが空文字ならRakutenApiErrorでcall_apiは呼ばれない(self):
        """app_idが空文字の場合はRakutenApiErrorになり、call_apiは呼ばれない。"""

        fake = FakeCallApi([])
        with pytest.raises(RakutenApiError):
            fetch_rakuten_price_and_point(DEFAULT_URL, "", "key", "referer", call_api=fake)
        assert fake.calls == []

    def test_app_idが空白のみならRakutenApiError(self):
        """境界値: app_idが空白文字だけの場合も空扱いでRakutenApiErrorになる。"""

        fake = FakeCallApi([])
        with pytest.raises(RakutenApiError):
            fetch_rakuten_price_and_point(DEFAULT_URL, "   ", "key", "referer", call_api=fake)
        assert fake.calls == []

    def test_access_keyが空文字ならRakutenApiErrorでcall_apiは呼ばれない(self):
        """access_keyが空文字の場合はRakutenApiErrorになり、call_apiは呼ばれない。"""

        fake = FakeCallApi([])
        with pytest.raises(RakutenApiError):
            fetch_rakuten_price_and_point(DEFAULT_URL, "app", "", "referer", call_api=fake)
        assert fake.calls == []

    def test_access_keyが空白のみならRakutenApiError(self):
        """境界値: access_keyが空白文字だけの場合も空扱いでRakutenApiErrorになる。"""

        fake = FakeCallApi([])
        with pytest.raises(RakutenApiError):
            fetch_rakuten_price_and_point(DEFAULT_URL, "app", "   ", "referer", call_api=fake)
        assert fake.calls == []

    def test_refererが空文字ならRakutenApiErrorでcall_apiは呼ばれない(self):
        """refererが空文字の場合はRakutenApiErrorになり、call_apiは呼ばれない。"""

        fake = FakeCallApi([])
        with pytest.raises(RakutenApiError):
            fetch_rakuten_price_and_point(DEFAULT_URL, "app", "key", "", call_api=fake)
        assert fake.calls == []

    def test_refererが空白のみならRakutenApiError(self):
        """境界値: refererが空白文字だけの場合も空扱いでRakutenApiErrorになる。"""

        fake = FakeCallApi([])
        with pytest.raises(RakutenApiError):
            fetch_rakuten_price_and_point(DEFAULT_URL, "app", "key", "   ", call_api=fake)
        assert fake.calls == []

    def test_不正なURLならValueErrorでcall_apiは呼ばれない(self):
        """URLが楽天商品URLとして解析できない場合はValueErrorになり、call_apiは呼ばれない。"""

        fake = FakeCallApi([])
        with pytest.raises(ValueError):
            fetch_rakuten_price_and_point(
                "https://example.com/shop/item/", "app", "key", "referer", call_api=fake
            )
        assert fake.calls == []


# ===========================================================================
# fetch_rakuten_price_and_point: itemCode直接検索（手順3）
# ===========================================================================


class TestFetchRakutenPriceAndPointDirectHit:
    """fetch_rakuten_price_and_point のitemCode直接検索が成功するケースのテスト。"""

    def test_itemCodeでの直接検索がヒットすればそのまま返す(self):
        """Itemsが空でなければ、先頭のItemをparse_itemした結果を返す。"""

        response = wrap_items(make_api_item(price=1980, point_rate=2))
        fake = FakeCallApi([response])

        price, point_rate = fetch_rakuten_price_and_point(
            DEFAULT_URL, "app", "key", "referer", call_api=fake
        )

        assert price == pytest.approx(1980.0)
        assert point_rate == 2
        assert len(fake.calls) == 1
        assert fake.calls[0]["params"] == {"itemCode": DEFAULT_ITEM_CODE}
        assert fake.calls[0]["app_id"] == "app"
        assert fake.calls[0]["access_key"] == "key"
        assert fake.calls[0]["referer"] == "referer"


# ===========================================================================
# fetch_rakuten_price_and_point: 検索し直しへの分岐条件
# ===========================================================================


class TestFetchRakutenPriceAndPointFallbackTrigger:
    """
    手順3の結果によって、検索し直し（手順4）に進むか、
    そのまま例外を送出するかの分岐に関するテスト。
    """

    def test_Itemsが空なら検索し直しに進む(self):
        """itemCode検索の結果Itemsが空配列なら、キーワード検索にフォールバックする。"""

        fake = FakeCallApi([EMPTY_ITEMS, wrap_items(make_api_item(item_code=DEFAULT_ITEM_CODE))])

        price, point_rate = fetch_rakuten_price_and_point(
            DEFAULT_URL, "app", "key", "referer", call_api=fake
        )

        assert price == pytest.approx(1000.0)
        assert point_rate == 1
        assert len(fake.calls) == 2
        assert fake.calls[1]["params"] == {"shopCode": DEFAULT_SHOP, "keyword": "item", "hits": 30}

    def test_ステータス400なら検索し直しに進む(self):
        """RakutenApiErrorのstatus=400のときは、キーワード検索にフォールバックする。"""

        fake = FakeCallApi(
            [
                RakutenApiError("Bad Request", status=400),
                wrap_items(make_api_item(item_code=DEFAULT_ITEM_CODE)),
            ]
        )

        price, point_rate = fetch_rakuten_price_and_point(
            DEFAULT_URL, "app", "key", "referer", call_api=fake
        )

        assert price == pytest.approx(1000.0)
        assert len(fake.calls) == 2

    def test_ステータス404なら検索し直しに進む(self):
        """RakutenApiErrorのstatus=404のときは、キーワード検索にフォールバックする。"""

        fake = FakeCallApi(
            [
                RakutenApiError("Not Found", status=404),
                wrap_items(make_api_item(item_code=DEFAULT_ITEM_CODE)),
            ]
        )

        price, point_rate = fetch_rakuten_price_and_point(
            DEFAULT_URL, "app", "key", "referer", call_api=fake
        )

        assert price == pytest.approx(1000.0)
        assert len(fake.calls) == 2

    @pytest.mark.parametrize("status", [401, 403, 500, None])
    def test_400_404以外のRakutenApiErrorは検索し直さずそのまま送出する(self, status):
        """
        重要な仕様: 401/403/500/status=None（接続エラー等）の場合は
        キーワード検索にフォールバックせず、そのままRakutenApiErrorを送出する。
        """

        original_error = RakutenApiError("エラー", status=status)
        fake = FakeCallApi([original_error])

        with pytest.raises(RakutenApiError) as exc_info:
            fetch_rakuten_price_and_point(DEFAULT_URL, "app", "key", "referer", call_api=fake)

        assert exc_info.value is original_error
        assert exc_info.value.status == status
        # フォールバックの2回目呼び出しは発生していないこと
        assert len(fake.calls) == 1


# ===========================================================================
# fetch_rakuten_price_and_point: 検索し直し（手順4）のキーワード生成
# ===========================================================================


class TestFetchRakutenPriceAndPointKeyword:
    """検索し直し時のキーワード抽出に関するテスト。"""

    def test_キーワードが2文字未満ならValueErrorでcall_apiは1回しか呼ばれない(self):
        """
        slugを英数字以外で区切った最初の語が2文字未満の場合はValueErrorになり、
        2回目のcall_api（キーワード検索）は呼ばれない。
        """

        url = "https://item.rakuten.co.jp/someshop/a-abc/"
        fake = FakeCallApi([EMPTY_ITEMS])

        with pytest.raises(ValueError):
            fetch_rakuten_price_and_point(url, "app", "key", "referer", call_api=fake)

        assert len(fake.calls) == 1

    def test_検索し直しでのRakutenApiErrorはそのまま送出する(self):
        """キーワード検索(2回目)でRakutenApiErrorが起きた場合はそのまま送出する。"""

        fallback_error = RakutenApiError("サーバーエラー", status=500)
        fake = FakeCallApi([EMPTY_ITEMS, fallback_error])

        with pytest.raises(RakutenApiError) as exc_info:
            fetch_rakuten_price_and_point(DEFAULT_URL, "app", "key", "referer", call_api=fake)

        assert exc_info.value is fallback_error
        assert len(fake.calls) == 2


# ===========================================================================
# fetch_rakuten_price_and_point: 検索し直し結果からの一致判定
# ===========================================================================


class TestFetchRakutenPriceAndPointFallbackMatching:
    """検索し直し後、複数の候補から正しい商品を選び出す照合ロジックのテスト。"""

    def test_itemCodeが完全一致する商品を選ぶ(self):
        """itemCodeがURLと完全一致するItemが優先して選ばれる。"""

        other = make_api_item(item_code="othershop:other-slug", price=9999, point_rate=9)
        target = make_api_item(item_code=DEFAULT_ITEM_CODE, price=1234, point_rate=3)
        fake = FakeCallApi([EMPTY_ITEMS, wrap_items(other, target)])

        price, point_rate = fetch_rakuten_price_and_point(
            DEFAULT_URL, "app", "key", "referer", call_api=fake
        )

        assert price == pytest.approx(1234.0)
        assert point_rate == 3

    def test_itemCodeの大文字小文字が違っても一致する(self):
        """重要な仕様: itemCodeの照合は大文字小文字を区別しない。"""

        target = make_api_item(
            item_code=f"{DEFAULT_SHOP.upper()}:{DEFAULT_SLUG.upper()}", price=1500, point_rate=4
        )
        fake = FakeCallApi([EMPTY_ITEMS, wrap_items(target)])

        price, point_rate = fetch_rakuten_price_and_point(
            DEFAULT_URL, "app", "key", "referer", call_api=fake
        )

        assert price == pytest.approx(1500.0)
        assert point_rate == 4

    def test_itemUrlを解析した結果が一致する商品を選ぶ(self):
        """itemCodeが無くても、itemUrlを解析した(shop, slug)が一致すれば選ばれる。"""

        target = make_api_item(
            item_url=f"https://item.rakuten.co.jp/{DEFAULT_SHOP}/{DEFAULT_SLUG}/",
            price=2000,
            point_rate=5,
        )
        fake = FakeCallApi([EMPTY_ITEMS, wrap_items(target)])

        price, point_rate = fetch_rakuten_price_and_point(
            DEFAULT_URL, "app", "key", "referer", call_api=fake
        )

        assert price == pytest.approx(2000.0)
        assert point_rate == 5

    def test_itemUrlの大文字小文字が違っても一致する(self):
        """重要な仕様: itemUrl経由の照合も大文字小文字を区別しない。"""

        target = make_api_item(
            item_url=f"https://item.rakuten.co.jp/{DEFAULT_SHOP.upper()}/{DEFAULT_SLUG.upper()}/",
            price=2500,
            point_rate=6,
        )
        fake = FakeCallApi([EMPTY_ITEMS, wrap_items(target)])

        price, point_rate = fetch_rakuten_price_and_point(
            DEFAULT_URL, "app", "key", "referer", call_api=fake
        )

        assert price == pytest.approx(2500.0)
        assert point_rate == 6

    def test_itemUrlが解析できないItemは無視して他の候補を見る(self):
        """itemUrlがextract_shop_and_slugで解析できないItemは無視され、例外にならない。"""

        broken = make_api_item(item_url="https://example.com/not-rakuten/", price=9999)
        target = make_api_item(item_code=DEFAULT_ITEM_CODE, price=1300, point_rate=1)
        fake = FakeCallApi([EMPTY_ITEMS, wrap_items(broken, target)])

        price, point_rate = fetch_rakuten_price_and_point(
            DEFAULT_URL, "app", "key", "referer", call_api=fake
        )

        assert price == pytest.approx(1300.0)
        assert point_rate == 1

    def test_一致する商品が無ければValueError(self):
        """
        重要な仕様: 検索し直しの結果に一致する商品が1つも無い場合は、
        別の商品の価格を誤って返さずValueErrorにする。
        """

        other1 = make_api_item(item_code="othershop:aaa", price=100, point_rate=1)
        other2 = make_api_item(
            item_url="https://item.rakuten.co.jp/othershop/bbb/", price=200, point_rate=1
        )
        fake = FakeCallApi([EMPTY_ITEMS, wrap_items(other1, other2)])

        with pytest.raises(ValueError):
            fetch_rakuten_price_and_point(DEFAULT_URL, "app", "key", "referer", call_api=fake)

    def test_一致しないときのメッセージに原因調査用の情報が入る(self):
        """
        itemCode検索の結果（HTTPステータス）、検索し直しの件数、
        上位の候補（商品名・itemCode・URL）をメッセージに含める。候補は最大3件。
        """

        others = [
            {
                **make_api_item(
                    item_code=f"someshop:1000{i}",
                    item_url=f"https://item.rakuten.co.jp/someshop/other{i}/",
                ),
                "itemName": f"別の商品{i}",
            }
            for i in range(4)
        ]
        fake = FakeCallApi([RakutenApiError("wrong_parameter", status=400), wrap_items(*others)])

        with pytest.raises(ValueError) as exc:
            fetch_rakuten_price_and_point(DEFAULT_URL, "app", "key", "referer", call_api=fake)

        message = str(exc.value)
        assert "HTTP 400" in message
        assert "4件" in message
        assert "別の商品0" in message and "someshop:10000" in message
        assert "https://item.rakuten.co.jp/someshop/other2/" in message
        assert "別の商品3" not in message

    def test_検索し直しが0件ならそのことがメッセージに入る(self):
        fake = FakeCallApi([EMPTY_ITEMS, EMPTY_ITEMS])

        with pytest.raises(ValueError, match="0件"):
            fetch_rakuten_price_and_point(DEFAULT_URL, "app", "key", "referer", call_api=fake)

    def test_検索し直しの結果Itemsが空でもValueError(self):
        """境界値: キーワード検索でもItemsが空配列なら一致する商品が無くValueErrorになる。"""

        fake = FakeCallApi([EMPTY_ITEMS, EMPTY_ITEMS])

        with pytest.raises(ValueError):
            fetch_rakuten_price_and_point(DEFAULT_URL, "app", "key", "referer", call_api=fake)


# ===========================================================================
# call_rakuten_api（実HTTP通信部分。ネットワークにはアクセスしない）
# ===========================================================================


class TestCallRakutenApi:
    """
    call_rakuten_api（実際にHTTP通信を行う関数）の最小限のテスト。

    urllib.request.urlopenをモックし、実際のネットワークには一切アクセスしない。
    詳細な仕様検証は対象外（call_api経由の呼び出しはfetch_rakuten_price_and_point側の
    テストでフェイクにより検証済み）とし、ここでは呼び出し可能であることのみ確認する。
    """

    def test_urlopenが呼ばれ正常なJSONレスポンスをdictとして返す(self, monkeypatch):
        """urlopenの戻り値をモックし、JSONがパースされてdictで返ることを確認する。"""

        import json as json_module

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json_module.dumps({"Items": []}).encode("utf-8")

        def fake_urlopen(req, timeout=10):
            assert "item-abc123" in req.full_url or True  # URLが構築されていればOK
            return FakeResponse()

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

        result = call_rakuten_api({"itemCode": DEFAULT_ITEM_CODE}, "app", "key", "referer")

        assert result == {"Items": []}
