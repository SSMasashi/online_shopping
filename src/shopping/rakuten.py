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

PAGE_USER_AGENT = "Mozilla/5.0 (compatible; buy-sl/1.0)"

# 商品ページは最初の応答まで10秒ほどかかることがあるため、長めに待つ。
PAGE_TIMEOUT_SECONDS = 25

# 商品ページは大きくても数百KBなので、それ以上は読まない。
MAX_PAGE_BYTES = 3 * 1024 * 1024


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


def extract_item_id(html, slug):
    """
    商品ページのHTMLから、楽天の内部番号（itemId）を取り出す。見つからなければ None。

    URLの商品管理番号（slug）は itemCode に使えないことがあるため、
    ページ内の商品情報から itemCode 用の内部番号を探す。
    """

    slug = slug.lower()
    has_sku_info = False

    # manageNumber（URLの商品管理番号）と itemId が同じオブジェクトにあるものを優先する。
    for obj in re.finditer(r"\{[^{}]*\}", html):
        text = obj.group(0)
        manage = re.search(r'"manageNumber"\s*:\s*"([^"]*)"', text)
        item_id = re.search(r'"itemId"\s*:\s*"?(\d+)', text)

        if manage and item_id:
            has_sku_info = True

            if manage.group(1).lower() == slug:
                return item_id.group(1)

    # 商品情報はあるが URL と一致しないなら、別の商品の番号を使わないよう諦める。
    if has_sku_info:
        return None

    ids = set(re.findall(r'"itemId"\s*:\s*"?(\d+)', html)) | set(
        re.findall(r"\bitem_id=(\d+)", html)
    )

    return ids.pop() if len(ids) == 1 else None


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


def fetch_item_page(url):
    """楽天の商品ページのHTMLを取得する。"""

    req = urllib.request.Request(
        url, headers={"User-Agent": PAGE_USER_AGENT, "Accept-Language": "ja"}
    )

    try:
        with urllib.request.urlopen(req, timeout=PAGE_TIMEOUT_SECONDS) as res:
            raw = res.read(MAX_PAGE_BYTES)
            charset = res.headers.get_content_charset()

    except (urllib.error.URLError, TimeoutError) as e:
        raise RakutenApiError(f"商品ページを取得できませんでした（{e}）") from None

    if not charset:
        meta = re.search(rb"charset=[\"']?([A-Za-z0-9_-]+)", raw[:4096])
        charset = meta.group(1).decode("ascii") if meta else "utf-8"

    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _describe_page(html):
    """原因調査のため、取得した商品ページの概要を文字列にする。"""

    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    title_text = re.sub(r"\s+", " ", title.group(1)).strip()[:60] if title else "(なし)"
    markers = ", ".join(
        f"{name}:{'あり' if name in html else 'なし'}"
        for name in ("manageNumber", "itemId", "item_id=")
    )

    return f"（{len(html)}文字 / タイトル: {title_text} / {markers}）"


def _fetch_via_item_page(shop, slug, app_id, access_key, referer, call_api, fetch_page):
    """
    商品ページから内部番号を読み取り、その itemCode で API から取得する。

    戻り値は (取得結果 or None, 調査用の説明)。
    """

    try:
        html = fetch_page(f"https://{RAKUTEN_ITEM_HOST}/{shop}/{slug}/")
        item_id = extract_item_id(html, slug)

        if item_id is None:
            return None, "内部番号が見つかりませんでした" + _describe_page(html)

        data = call_api({"itemCode": f"{shop}:{item_id}"}, app_id, access_key, referer)

    except RakutenApiError as e:
        return None, f"失敗（{e}）"

    for entry in data.get("Items", []):
        item = entry.get("Item", {})

        if _is_same_item(item, shop, slug):
            return parse_item(item), f"内部番号 {item_id} で取得"

    return None, f"内部番号 {item_id} の商品がURLと一致しませんでした"


def fetch_rakuten_price_and_point(
    url, app_id, access_key, referer, call_api=call_rakuten_api, fetch_page=None
):
    """
    楽天の商品URLから (税込価格, pointRate) を取得する。

    pointRate は API の生の値（通常の1%を含む）。
    URLの itemCode で見つからない場合は、
        1. 商品ページから内部番号を読み取って itemCode を作り直す
        2. ショップ内をキーワード検索する
    の順に試し、URLと同じ商品が見つかったときだけ採用する。
    """

    fetch_page = fetch_page or fetch_item_page

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

        first_result = "0件"

    except RakutenApiError as e:
        if e.status not in NOT_FOUND_STATUSES:
            raise

        first_result = f"HTTP {e.status}: {e}"

    # -----------------------------------------------------------------------
    # 商品ページの内部番号で itemCode を作り直す
    # -----------------------------------------------------------------------

    result, page_result = _fetch_via_item_page(
        shop, slug, app_id, access_key, referer, call_api, fetch_page
    )

    if result is not None:
        return result

    # -----------------------------------------------------------------------
    # ショップ内をキーワード検索し、同じ商品だけを採用する
    # -----------------------------------------------------------------------

    words = re.sub(r"[^0-9A-Za-z]+", " ", slug).split()
    keyword = words[0] if words else ""

    if len(keyword) < 2:
        raise ValueError(
            f"商品が見つかりませんでした（itemCode: {item_code}）\n"
            f"・itemCodeでの取得: {first_result}\n"
            f"・商品ページからの取得: {page_result}"
        )

    data = call_api(
        {"shopCode": shop, "keyword": keyword, "hits": FALLBACK_HITS}, app_id, access_key, referer
    )

    candidates = [entry.get("Item", {}) for entry in data.get("Items", [])]

    for item in candidates:
        if _is_same_item(item, shop, slug):
            return parse_item(item)

    raise ValueError(
        f"URLの商品と一致する商品が見つかりませんでした（itemCode: {item_code}）\n"
        f"・itemCodeでの取得: {first_result}\n"
        f"・商品ページからの取得: {page_result}\n"
        f"・キーワード「{keyword}」での検索: {len(candidates)}件" + _describe_candidates(candidates)
    )


def _describe_candidates(candidates, limit=3):
    """原因調査のため、検索結果の上位候補を文字列にする。"""

    lines = [
        f"\n  - {str(item.get('itemName', ''))[:40]} / {item.get('itemCode', '')} / {item.get('itemUrl', '')}"
        for item in candidates[:limit]
    ]

    return "".join(lines)
