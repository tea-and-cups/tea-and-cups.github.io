# -*- coding: utf-8 -*-
"""公開記事の楽天商品リンクを楽天APIで全件照会し、data/product-link-status.tsv を生成する（引数なしで全件）。

背景:
  従来の商品リンク健全性チェックは、AIが data/link-health.md から週10件ずつ WebFetch で
  巡回する方式だった。件数が追いつかず（一巡224日）3週連続で実施されず、台帳も記事本文と
  ずれていた。停止検知（D-0242）も、記事公開のたびに台帳の日付が更新されるため働かなかった。
  そこで、記事本文を正本として商品URLを集め、楽天APIで全件を機械的に照会する。
  AIは「OK」以外の行だけを確認する（rules/product-linking.md 4節）。

対象リンク（status: published の記事のみ）:
  hb.afl.rakuten.co.jp（pc= を復号）／af.moshimo.com（url= を復号）／item.rakuten.co.jp

照会の手順:
  台帳に内部の商品コード（itemCode）が保存されている商品は itemCode で照会する。
  保存されていない商品は shopCode＋URL末尾のID → shopCode＋商品名 の順で検索し、
  返ってきた itemUrl が元の商品URLと一致したものだけを採って itemCode を保存する。
  商品名は記事のリンク文言（出現順にすべて）から取り、その後に data/link-health.md の商品名を試す
  （名前検索は1商品あたり最大 MAX_NAME_SEARCHES 回）。

状態:
  OK（1件見つかり availability=1）／在庫なし（見つかったが availability≠1）／
  消失疑い（保存した itemCode で0件）／未特定（itemUrl が一致する商品が無い）／
  照会失敗（通信エラー・429以外のエラー）

台帳 data/product-link-status.tsv はこのスクリプトだけが書く（手で編集しない）。
全件の照会を終えたときだけ書き換える。--limit N のときは表示のみで台帳を書かない
（一部だけ照会したのに最終照会日が新しくなり、全件照会済みに見えるのを防ぐため）。
最終照会日の鮮度は check-doc-governance.py が監視する（8日以上前で【警告】）。

認証情報は fetch-rakuten-products.py の load_credentials() を読み込んで使う（値は出力しない）。

使い方:
  python site/scripts/check-product-links.py            # 全件照会して台帳を更新（約5〜8分）
  python site/scripts/check-product-links.py --limit 5  # 先頭5件だけ照会して表示（台帳は書かない）
  python site/scripts/check-product-links.py --targets-only  # 照会せず、既存台帳から「確認対象」だけを表示（書き込みなし）
  python site/scripts/check-product-links.py --item <itemCode または商品URL>  # 1商品の仕様・在庫・内訳を確かめる（下記）

1商品の照会（--item・D-0334・L102）:
  楽天の商品ページ（item.rakuten.co.jp）は EUC-JP で返るため、WebFetch では日本語を判読できない
  （PreToolUse フック block-rakuten-item-webfetch.py が取得を止める）。代わりにこのモードで楽天APIに照会し、
  itemName・availability・評価・件数・商品URL・itemCaption（商品説明文の全文）を UTF-8 で出す。
  引数は itemCode（例: nenrin:10000862）か商品URL（item.rakuten.co.jp・hb.afl.rakuten.co.jp・af.moshimo.com）。
  URLのときは、台帳に保存した itemCode → 「店舗ID:URL末尾のID」の itemCode → 店舗ID＋URL末尾のIDの検索の順に試し、
  返った itemUrl が元のURLと一致したものだけを採る。
  照会に成功したら、素の商品URLを data/webfetch-log.md に識別子 rakuten-api で記録する
  （record-webfetch.py の record_url を共用。記事の出典として check-source-fetched.py の照合を通すため）。
  0件・エラーのときは記録しない（終了コード1）。data/product-link-status.tsv は書かない。

確認対象（D-0331）:
  OK以外の行のうち、使用記事の直近7日のPVが REVIEW_MIN_PV（20）以上のものだけを「確認対象」として出す
  （上限なし。複数の記事で使われている商品は最大のPVで判定する）。
  PVは growth/inputs/ にある最新の週（YYYY-Www）の ga4-page-traffic.json から読む。ファイルが無い場合や、
  記事が上位100行に無い場合は対象外とし、その旨を1行出す。対象が0件なら「確認対象 0件」と出す。

終了コード: 0=正常終了（OK以外の行があっても0）／1=準備段階の失敗（認証情報・記事を読めない等）
"""

import datetime
import glob
import importlib.util
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POSTS_DIR = os.path.join(ROOT, "site", "src", "content", "posts")
STATUS_PATH = os.path.join(ROOT, "data", "product-link-status.tsv")
GROWTH_INPUTS_DIR = os.path.join(ROOT, "growth", "inputs")
LINK_HEALTH_PATH = os.path.join(ROOT, "data", "link-health.md")

# 認証情報の読み方・エンドポイントの正本は fetch-rakuten-products.py（ファイル名にハイフンを含むため importlib で読み込む）
_spec = importlib.util.spec_from_file_location(
    "fetch_rakuten_products", os.path.join(os.path.dirname(os.path.abspath(__file__)), "fetch-rakuten-products.py")
)
frp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(frp)

CALL_INTERVAL_SECONDS = 1.1
SEARCH_HITS = 30
MAX_NAME_SEARCHES = 3  # 1商品あたりの名前検索の上限（未特定の商品で呼び出しが膨らまないように）

HEADER = ["商品URL", "店舗ID", "URL末尾のID", "内部の商品コード", "状態", "availability",
          "評価", "件数", "使用記事", "最終照会日", "特定方法"]

STATUS_ORDER = ["OK", "在庫なし", "消失疑い", "未特定", "照会失敗"]

REVIEW_MIN_PV = 20  # 確認対象にする記事の直近7日PVの下限（D-0331）
WEEK_DIR_RE = re.compile(r"^\d{4}-W\d{2}$")
POST_PATH_RE = re.compile(r"^/posts/([^/]+)/?$")

PUBLISHED_RE = re.compile(r"^status:\s*published\s*$", re.MULTILINE)
# [![alt](img)](url) と [テキスト](url) の両方を拾う
LINK_RE = re.compile(r"\[(!\[([^\]]*)\]\([^)]*\)|[^\]]*)\]\((https?://[^)\s]+)\)")
URL_RE = re.compile(r"https?://[^\s)\]\"'<>]+")
ITEM_URL_RE = re.compile(r"^https?://item\.rakuten\.co\.jp/([^/?#]+)/([^/?#]+)/?", re.IGNORECASE)
LINK_TEXT_SUFFIX_RE = re.compile(r"(はこちら|をチェック|を見る).*$")
LINK_HEALTH_ID_RE_TEMPLATE = r"{shop}\s*[／/・]\s*{item}(?![\w-])"


class ApiError(Exception):
    pass


def item_url_parts(url):
    """任意の商品リンクから (正規化した商品URL, 店舗ID, URL末尾のID) を返す。対象外なら None。"""
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    query = urllib.parse.parse_qs(parsed.query)
    if host == "hb.afl.rakuten.co.jp":
        url = (query.get("pc") or [""])[0]
    elif host == "af.moshimo.com":
        url = (query.get("url") or [""])[0]
    elif host != "item.rakuten.co.jp":
        return None
    m = ITEM_URL_RE.match(url)
    if not m:
        return None
    shop, item = m.group(1).lower(), m.group(2)
    return "https://item.rakuten.co.jp/%s/%s/" % (shop, item), shop, item


def normalize_item_url(url):
    m = ITEM_URL_RE.match(url or "")
    if not m:
        return ""
    return "https://item.rakuten.co.jp/%s/%s/" % (m.group(1).lower(), m.group(2))


def clean_name(text):
    text = LINK_TEXT_SUFFIX_RE.sub("", text.strip())
    return text.strip()


def collect_products():
    """公開記事から商品URLを集め、{商品URL: {shop, item, slugs, names}} を返す。"""
    paths = sorted(glob.glob(os.path.join(POSTS_DIR, "*.md")))
    if not paths:
        raise RuntimeError("記事が見つからない: %s" % POSTS_DIR)
    products = {}
    for path in paths:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if not PUBLISHED_RE.search(text):
            continue
        slug = os.path.splitext(os.path.basename(path))[0]
        names_by_url = {}
        for m in LINK_RE.finditer(text):
            parts = item_url_parts(m.group(3))
            if not parts:
                continue
            name = clean_name(m.group(2) if m.group(2) is not None else m.group(1))
            if name:
                names_by_url.setdefault(parts[0], []).append(name)
        for m in URL_RE.finditer(text):
            parts = item_url_parts(m.group(0))
            if not parts:
                continue
            url, shop, item = parts
            entry = products.setdefault(url, {"shop": shop, "item": item, "slugs": [], "names": []})
            if slug not in entry["slugs"]:
                entry["slugs"].append(slug)
            for name in names_by_url.get(url, []):
                if name not in entry["names"]:
                    entry["names"].append(name)
    return products


def load_recent_pageviews(growth_dir=None):
    """最新の週の ga4-page-traffic.json から {slug: 直近7日のPV} を返す。

    戻り値: (PVのdict or None, 出典の説明)。週のファイルが無い・読めないときは (None, 理由)。
    """
    growth_dir = growth_dir or GROWTH_INPUTS_DIR
    weeks = []
    if os.path.isdir(growth_dir):
        weeks = sorted(d for d in os.listdir(growth_dir)
                       if WEEK_DIR_RE.match(d) and os.path.isfile(os.path.join(growth_dir, d, "ga4-page-traffic.json")))
    if not weeks:
        return None, "growth/inputs/ に週（YYYY-Www）の ga4-page-traffic.json が無い"
    week = weeks[-1]
    path = os.path.join(growth_dir, week, "ga4-page-traffic.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        series = data["data"]["series"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        return None, "growth/inputs/%s/ga4-page-traffic.json を読めない（%s）" % (week, e)
    period = (data.get("params") or {}).get("period") or {}
    views = {}
    for entry in series:
        m = POST_PATH_RE.match(str(entry.get("page_path", "")))
        if m:
            views[m.group(1)] = views.get(m.group(1), 0) + int(entry.get("screenPageViews") or 0)
    source = "growth/inputs/%s/ga4-page-traffic.json（%s〜%s）" % (
        week, period.get("start_date", "?"), period.get("end_date", "?"))
    return views, source


def select_review_targets(not_ok, views):
    """OK以外の行から、使用記事の最大PVが REVIEW_MIN_PV 以上のものを返す。

    戻り値: ([(行, 最大PV, 最大PVの記事), ...] をPVの大きい順, PVを引けず対象外にした行数)。
    """
    targets = []
    unknown = 0
    for row in not_ok:
        slugs = [s for s in row.get("使用記事", "").split(",") if s]
        known = [(views[s], s) for s in slugs if s in views]
        if not known:
            unknown += 1
            continue
        pv, slug = max(known)
        if pv >= REVIEW_MIN_PV:
            targets.append((row, pv, slug))
    targets.sort(key=lambda x: -x[1])
    return targets, unknown


def print_review_targets(not_ok, growth_dir=None):
    """「確認対象」（OK以外かつ直近7日PVが REVIEW_MIN_PV 以上の記事）を表示する（D-0331）。件数を返す。"""
    views, source = load_recent_pageviews(growth_dir)
    if views is None:
        print("確認対象 0件（PVを読めないため全件対象外: %s）" % source)
        return 0
    targets, unknown = select_review_targets(not_ok, views)
    print("確認対象 %d件（OK以外 %d件のうち、使用記事の直近7日PVが%d以上。PV出典: %s）" % (
        len(targets), len(not_ok), REVIEW_MIN_PV, source))
    for row, pv, slug in targets:
        print("  %s	%s	%s（PV %d）" % (row["状態"], row["商品URL"], slug, pv))
    if unknown:
        print("対象外 %d件: 使用記事が上位100行に無い（PV不明）" % unknown)
    return len(targets)


def link_health_name(shop, item, lines):
    """link-health.md の商品名列から、店舗ID・URL末尾のIDを含む行の商品名（括弧書きを除く）を返す。"""
    pattern = re.compile(
        LINK_HEALTH_ID_RE_TEMPLATE.format(shop=re.escape(shop), item=re.escape(item)), re.IGNORECASE
    )
    for line in lines:
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or not pattern.search(cells[2]):
            continue
        return re.sub(r"[（(][^（(]*$", "", cells[2]).strip()
    return ""


def load_status():
    """既存台帳を {商品URL: 行dict} で返す。無ければ空。"""
    if not os.path.isfile(STATUS_PATH):
        return {}
    rows = {}
    with open(STATUS_PATH, encoding="utf-8") as f:
        lines = f.read().splitlines()
    if not lines:
        return {}
    header = lines[0].split("\t")
    for line in lines[1:]:
        if not line.strip():
            continue
        cells = line.split("\t")
        row = dict(zip(header, cells))
        rows[row.get("商品URL", "")] = row
    return rows


class Client:
    def __init__(self):
        self.app_id, self.access_key, _ = frp.load_credentials()
        if not self.app_id or not self.access_key:
            raise RuntimeError("data/.rakuten-credentials または環境変数に RAKUTEN_APP_ID / RAKUTEN_ACCESS_KEY が見つからない")
        self.last_call = 0.0
        self.calls = {"itemCode": 0, "id検索": 0, "名前検索": 0}

    def search(self, kind, **params):
        """IchibaItem/Search を呼んで Items（Itemの中身のリスト）を返す。0件の 404 も空リストとして返す。"""
        self.calls[kind] += 1
        query = {
            "applicationId": self.app_id,
            "accessKey": self.access_key,
            "availability": 0,  # 在庫切れも含めて返させる（在庫なしを判定するため）
            "format": "json",
        }
        query.update(params)
        req = urllib.request.Request(
            "%s?%s" % (frp.ENDPOINT, urllib.parse.urlencode(query)),
            headers={"Referer": frp.APP_REFERER, "Origin": frp.APP_REFERER.rstrip("/")},
        )
        for attempt in range(frp.MAX_RETRIES + 1):
            wait = self.last_call + CALL_INTERVAL_SECONDS - time.time()
            if wait > 0:
                time.sleep(wait)
            self.last_call = time.time()
            try:
                with urllib.request.urlopen(req, timeout=30) as res:
                    body = json.loads(res.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", errors="replace")
                if e.code == 429 and attempt < frp.MAX_RETRIES:
                    backoff = frp.BACKOFF_BASE_SECONDS * (2 ** attempt)
                    print("  429（レート制限）応答。%d秒待って再試行（%d/%d）" % (backoff, attempt + 1, frp.MAX_RETRIES))
                    time.sleep(backoff)
                    continue
                if e.code == 404 and "not_found" in detail:
                    return []
                raise ApiError("HTTP %d %s" % (e.code, detail[:120]))
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                raise ApiError("通信エラー %s" % e)
        else:
            raise ApiError("HTTP 429 再試行上限")
        if "error" in body:
            if body.get("error") == "not_found":
                return []
            raise ApiError("APIエラー %s %s" % (body.get("error"), body.get("error_description", "")))
        return [it.get("Item", it) for it in body.get("Items", [])]


def name_keyword(name):
    """商品名を検索キーワードに整える（かっこ書きを除き、記号を空白へ、1文字の語を除き、長すぎれば語単位で切る）。

    楽天のキーワード検索はAND一致のため、リンク文言に添えた店名（かっこ書き）が
    商品名に無いだけで0件になる（2026-10-26実測・aarti/10002001）。
    """
    text = re.sub(r"[（(][^）)]*[）)]", " ", name)
    text = re.sub(r"[()（）\[\]［］【】「」『』<>＜＞&＆/／・,、。!！?？★☆|｜:：~〜+＋\"'#＃%％]", " ", name)
    words = [w for w in text.split() if len(w) >= 2]
    kept = []
    for w in words:
        if len(" ".join(kept + [w])) > 60:
            break
        kept.append(w)
    return " ".join(kept)


def check_product(client, url, product, saved, lh_lines):
    """1商品を照会して台帳の行dictを返す。"""
    row = {
        "商品URL": url, "店舗ID": product["shop"], "URL末尾のID": product["item"],
        "内部の商品コード": "", "状態": "", "availability": "", "評価": "", "件数": "",
        "使用記事": ",".join(product["slugs"]), "最終照会日": datetime.date.today().isoformat(),
        "特定方法": "なし",
    }

    def fill(item):
        row["内部の商品コード"] = item.get("itemCode", "")
        avail = item.get("availability")
        row["availability"] = "" if avail is None else str(avail)
        row["状態"] = "OK" if str(avail) == "1" else "在庫なし"
        row["評価"] = str(item.get("reviewAverage", ""))
        row["件数"] = str(item.get("reviewCount", ""))

    code = (saved or {}).get("内部の商品コード", "")
    if code:
        row["内部の商品コード"] = code
        row["特定方法"] = "code"
        try:
            items = client.search("itemCode", itemCode=code)
        except ApiError as e:
            row["状態"] = "照会失敗"
            return row, str(e)
        if not items:
            row["状態"] = "消失疑い"
            return row, ""
        fill(items[0])
        return row, ""

    # 記事のリンク文言（画像のalt・テキストリンク）を出現順にすべて候補にし、
    # 最後に link-health.md の商品名を足す（記事の文言が検索語として外れる場合の予備）
    names = product["names"] + [link_health_name(product["shop"], product["item"], lh_lines)]
    keywords = []
    for name in names:
        keyword = name_keyword(name) if name else ""
        if keyword and keyword not in keywords:
            keywords.append(keyword)
    attempts = [("id検索", product["item"])] + [("名前検索", kw) for kw in keywords[:MAX_NAME_SEARCHES]]
    errors = []
    for kind, kw in attempts:
        try:
            items = client.search(kind, shopCode=product["shop"], keyword=kw, hits=SEARCH_HITS)
        except ApiError as e:
            errors.append("%s: %s" % (kind, e))
            continue
        for item in items:
            if normalize_item_url(item.get("itemUrl", "")) == url:
                fill(item)
                row["特定方法"] = kind
                return row, ""
    row["状態"] = "照会失敗" if errors else "未特定"
    note = " / ".join(errors) if errors else ("商品名なし" if not keywords else "")
    return row, note


def load_record_webfetch():
    """record-webfetch.py（台帳 data/webfetch-log.md の書き込みの正本）を読み込む。"""
    spec = importlib.util.spec_from_file_location(
        "record_webfetch", os.path.join(os.path.dirname(os.path.abspath(__file__)), "record-webfetch.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lookup_item(client, arg):
    """itemCode か商品URLから1商品を照会し、(Itemの中身, 素の商品URL) を返す。見つからなければ (None, 理由)。"""
    if "://" not in arg:
        items = client.search("itemCode", itemCode=arg)
        if not items:
            return None, "itemCode %s は楽天APIで0件" % arg
        item = items[0]
        return item, normalize_item_url(frp.plain_item_url(item))

    parts = item_url_parts(arg)
    if not parts:
        return None, "楽天の商品URL（item.rakuten.co.jp/<店舗>/<ID>/ またはそのアフィリエイトリンク）として読めない: %s" % arg
    url, shop, item_id = parts
    codes = []
    saved_code = (load_status().get(url) or {}).get("内部の商品コード", "")
    if saved_code:
        codes.append(saved_code)
    if "%s:%s" % (shop, item_id) not in codes:
        codes.append("%s:%s" % (shop, item_id))
    for code in codes:
        for item in client.search("itemCode", itemCode=code):
            if normalize_item_url(frp.plain_item_url(item)) == url:
                return item, url
    for item in client.search("id検索", shopCode=shop, keyword=item_id, hits=SEARCH_HITS):
        if normalize_item_url(frp.plain_item_url(item)) == url:
            return item, url
    return None, "%s は楽天APIで見つからない（itemCode %s・店舗ID＋IDの検索で一致なし）" % (url, " / ".join(codes))


def run_item_mode(arg):
    """--item: 1商品の仕様・在庫・内訳を UTF-8 で出し、成功したら素の商品URLを data/webfetch-log.md に記録する。"""
    try:
        client = Client()
        item, info = lookup_item(client, arg)
    except (RuntimeError, ApiError) as e:
        print("【エラー】照会に失敗: %s（台帳には記録していない）" % e)
        return 1
    if item is None:
        print("見つからない: %s（台帳には記録していない）" % info)
        return 1
    avail = item.get("availability")
    print("itemName: %s" % item.get("itemName", ""))
    print("itemCode: %s" % item.get("itemCode", ""))
    print("availability: %s（%s）" % (avail, "在庫あり" if str(avail) == "1" else "在庫なし"))
    print("評価: %s／件数: %s" % (item.get("reviewAverage", ""), item.get("reviewCount", "")))
    print("店舗: %s" % item.get("shopName", ""))
    print("商品URL: %s" % info)
    print("--- itemCaption ---")
    print(item.get("itemCaption", "") or "（itemCaption なし）")
    print("--- ここまで ---")
    if not info:
        print("商品URLを特定できないため台帳には記録していない")
        return 0
    try:
        recorded = load_record_webfetch().record_url(info, "rakuten-api")
    except Exception as e:  # 記録の失敗は照会結果の表示を妨げない
        print("【警告】data/webfetch-log.md への記録に失敗: %s" % e)
        return 0
    print("data/webfetch-log.md: %s" % ("記録した（rakuten-api）" if recorded else "今日の記録が既にある"))
    return 0


def write_status(rows):
    tmp = STATUS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(HEADER) + "\n")
        for row in rows:
            f.write("\t".join(str(row.get(h, "")).replace("\t", " ") for h in HEADER) + "\n")
    os.replace(tmp, STATUS_PATH)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    limit = None
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "--item":
        sys.exit(run_item_mode(args[1].strip()))
    if args == ["--targets-only"]:
        # 照会も台帳の書き込みもせず、既存台帳から確認対象だけを表示する（D-0331）
        saved = load_status()
        if not saved:
            print("【エラー】台帳 data/product-link-status.tsv が無い。先に引数なしで実行する")
            sys.exit(1)
        not_ok = [r for r in saved.values() if r.get("状態") != "OK"]
        print("台帳の最終照会日: %s／OK以外 %d件" % (
            max((r.get("最終照会日", "") for r in saved.values()), default="?"), len(not_ok)))
        print_review_targets(not_ok)
        sys.exit(0)
    if args:
        if len(args) == 2 and args[0] == "--limit" and args[1].isdigit():
            limit = int(args[1])
        else:
            print("使い方: python site/scripts/check-product-links.py [--limit N | --targets-only | --item <itemCode または商品URL>]")
            sys.exit(1)

    try:
        client = Client()
        products = collect_products()
    except (RuntimeError, OSError) as e:
        print("【エラー】準備に失敗: %s" % e)
        sys.exit(1)

    saved_rows = load_status()
    lh_lines = []
    if os.path.isfile(LINK_HEALTH_PATH):
        with open(LINK_HEALTH_PATH, encoding="utf-8") as f:
            lh_lines = f.read().splitlines()

    urls = sorted(products)
    if limit is not None:
        urls = urls[:limit]
    print("商品URL %d件（公開記事から重複を除いて集計）%s" % (
        len(products), "／--limit %d：台帳は書かない" % limit if limit is not None else ""))

    started = time.time()
    rows = []
    for i, url in enumerate(urls, 1):
        row, note = check_product(client, url, products[url], saved_rows.get(url), lh_lines)
        rows.append(row)
        print("%d/%d [%s] %s/%s → %s%s" % (
            i, len(urls), row["特定方法"], row["店舗ID"], row["URL末尾のID"], row["状態"],
            "（%s）" % note if note else ""))

    elapsed = time.time() - started
    if limit is None:
        write_status(rows)
        print("台帳を更新: data/product-link-status.tsv（%d行）" % len(rows))
    else:
        print("--limit 指定のため台帳は更新していない")

    print("所要 %d分%02d秒 / API呼び出し itemCode照会 %d回・id検索 %d回・名前検索 %d回" % (
        elapsed // 60, elapsed % 60, client.calls["itemCode"], client.calls["id検索"], client.calls["名前検索"]))
    methods = {}
    for row in rows:
        methods[row["特定方法"]] = methods.get(row["特定方法"], 0) + 1
    print("特定方法: " + " / ".join("%s %d件" % (k, v) for k, v in sorted(methods.items())))
    counts = {s: 0 for s in STATUS_ORDER}
    for row in rows:
        counts[row["状態"]] = counts.get(row["状態"], 0) + 1
    print("状態: " + " / ".join("%s %d件" % (s, counts[s]) for s in STATUS_ORDER))
    not_ok = [r for r in rows if r["状態"] != "OK"]
    if not_ok:
        print("OK以外 %d件（先頭20件）:" % len(not_ok))
        for r in not_ok[:20]:
            print("  %s\t%s\t%s" % (r["状態"], r["商品URL"], r["使用記事"]))
    print_review_targets(not_ok)
    sys.exit(0)


if __name__ == "__main__":
    main()
