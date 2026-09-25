"""
楽天市場APIから商品の価格とポイント倍率を取得する処理。

Streamlit に依存しない。認証情報は呼び出し側から引数で受け取る。
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request

RAKUTEN_API_URL = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701"

RAKUTEN_ITEM_HOST = "item.rakuten.co.jp"

# itemCode で見つからなかったときに、検索し直しへ進むHTTPステータス。
NOT_FOUND_STATUSES = (400, 404)

FALLBACK_HITS = 30


class RakutenApiError(RuntimeError):
    """楽天APIの呼び出しに失敗したときの例外。status は HTTP ステータス（接続エラーなどは None）。"""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


# ===========================================================================
# URL・レスポンスの解析
# ===========================================================================


def extract_shop_and_slug(url):
    """楽天の商品URLから (ショップコード, 商品コード部分) を取得する。"""

    parsed = urllib.parse.urlparse(str(url).strip())

    if parsed.scheme not in ("http", "https") or parsed.hostname != RAKUTEN_ITEM_HOST:
        raise ValueError("楽天の商品URL（https://item.rakuten.co.jp/...）を入力してください")

    parts = [p for p in parsed.path.split("/") if p]

    if len(parts) < 2:
        raise ValueError("楽天の商品URLとして認識できません")

    return parts[0], parts[1]


def parse_item(item):
    """APIレスポンスの Item から (税込価格, pointRate) を取り出す。"""

    try:
        price = float(item["itemPrice"])
        point_rate = int(float(item.get("pointRate", 1)))
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError("楽天APIの応答から価格を読み取れませんでした") from e

    return price, point_rate


def _is_same_item(item, shop, slug):
    """検索結果の Item が、URLで指定された商品と同じかどうか。"""

    item_code = f"{shop}:{slug}".lower()

    if str(item.get("itemCode", "")).lower() == item_code:
        return True

    try:
        item_shop, item_slug = extract_shop_and_slug(item.get("itemUrl", ""))
    except ValueError:
        return False

    return (item_shop.lower(), item_slug.lower()) == (shop.lower(), slug.lower())


# ===========================================================================
# API呼び出し
# ===========================================================================


def call_rakuten_api(params, app_id, access_key, referer):
    """楽天APIを呼び出し、JSONを dict で返す。"""

    query = {**params, "format": "json", "applicationId": app_id, "accessKey": access_key}

    req = urllib.request.Request(
        f"{RAKUTEN_API_URL}?{urllib.parse.urlencode(query)}", headers={"Origin": referer}
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return json.loads(res.read().decode("utf-8"))

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")

        try:
            err = json.loads(body)
            errs = err.get("errors", err)
            msg = (
                errs.get("errorMessage")
                or errs.get("error_description")
                or errs.get("error")
                or body
            )
        except (json.JSONDecodeError, AttributeError):
            msg = body

        raise RakutenApiError(str(msg), status=e.code) from None

    except (urllib.error.URLError, TimeoutError) as e:
        raise RakutenApiError(f"楽天APIに接続できませんでした（{e}）") from None

    except json.JSONDecodeError:
        raise RakutenApiError("楽天APIの応答を読み取れませんでした") from None


def fetch_rakuten_price_and_point(url, app_id, access_key, referer, call_api=call_rakuten_api):
    """
    楽天の商品URLから (税込価格, pointRate) を取得する。

    pointRate は API の生の値（通常の1%を含む）。
    itemCode で見つからない場合はショップ内をキーワード検索し、
    URLと同じ商品が見つかったときだけ採用する。
    """

    app_id = (app_id or "").strip()
    access_key = (access_key or "").strip()
    referer = (referer or "").strip()

    if not app_id or not access_key:
        raise RakutenApiError("楽天APIの認証情報がStreamlit Secretsに設定されていません。")

    if not referer:
        raise RakutenApiError("楽天APIのRAKUTEN_REFERERがStreamlit Secretsに設定されていません。")

    shop, slug = extract_shop_and_slug(url)
    item_code = f"{shop}:{slug}"

    # -----------------------------------------------------------------------
    # itemCode で直接取得
    # -----------------------------------------------------------------------

    try:
        data = call_api({"itemCode": item_code}, app_id, access_key, referer)
        items = data.get("Items", [])

        if items:
            return parse_item(items[0]["Item"])

    except RakutenApiError as e:
        if e.status not in NOT_FOUND_STATUSES:
            raise

    # -----------------------------------------------------------------------
    # ショップ内をキーワード検索し、同じ商品だけを採用する
    # -----------------------------------------------------------------------

    words = re.sub(r"[^0-9A-Za-z]+", " ", slug).split()
    keyword = words[0] if words else ""

    if len(keyword) < 2:
        raise ValueError(f"商品が見つかりませんでした（itemCode: {item_code}）")

    data = call_api(
        {"shopCode": shop, "keyword": keyword, "hits": FALLBACK_HITS}, app_id, access_key, referer
    )

    for entry in data.get("Items", []):
        item = entry.get("Item", {})

        if _is_same_item(item, shop, slug):
            return parse_item(item)

    raise ValueError(f"URLの商品と一致する商品が見つかりませんでした（itemCode: {item_code}）")
