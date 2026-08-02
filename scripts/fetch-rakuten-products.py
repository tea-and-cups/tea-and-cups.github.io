"""楽天商品検索APIで商品候補の評価・レビュー件数・価格・在庫を取得する。

背景:
  従来はWebFetch/WebSearchで1商品ずつページを取得しており、トークンコストが
  大きかった（[[project-rakuten-api]]参照）。APIなら評価・レビュー件数・価格・
  在庫がJSONで一括取得できる。取得結果は score-product.py の入力形式
  （data/scoring-input.tsv）でそのまま出力する。取得元を差し替えただけで
  スコアリング式は変更しない（CLAUDE.md 9節の「入口と出口を差し替える」方針）。

  ブランド区分（major/mid/unknown）はAPIから機械的に判定できないため、
  出力では暫定的に unknown を入れる。score-product.py を実行する前に
  実際のブランドを確認して手動で直すこと。同様に、APIの在庫フラグは
  参考情報であり、CLAUDE.md 2-2の実在・在庫確認（実売ページ確認）を
  省略してよいわけではない。

  商品画像URL（mediumImageUrls）も別セクションで出力する（試行運用・
  新規記事限定・D-0047）。既存のscoring-input.tsv用の出力形式は変更
  していない。取得したURLは site/scripts/product-image-to-webp.py に
  そのまま渡せる。

使い方:
  python site/scripts/fetch-rakuten-products.py <検索キーワード> [取得件数(既定5・最大30)]

前提:
  data/.rakuten-credentials（KEY=VALUE形式、1行目 RAKUTEN_APP_ID・2行目 RAKUTEN_ACCESS_KEY）
  に楽天ウェブサービスのアプリケーションID・アクセスキーを保存しておく。data/ はGit管理外
  （decision_no_root_gitify）のため、キーをファイルに直接置いてよい。ファイルが無い場合は
  環境変数 RAKUTEN_APP_ID / RAKUTEN_ACCESS_KEY にフォールバックする。
  2026年2〜5月の楽天API新方式移行により、旧エンドポイント（app.rakuten.co.jp）は廃止済み。
  新エンドポイント（openapi.rakuten.co.jp）は applicationId に加え accessKey が必須。
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CREDENTIALS_PATH = os.path.join(ROOT, "data", ".rakuten-credentials")

ENDPOINT = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701"
APP_REFERER = "https://tea-and-cups.github.io/"  # 楽天アプリ登録画面の「アプリケーションURL」と一致させる

MAX_RETRIES = 4
BACKOFF_BASE_SECONDS = 2


def load_credentials():
    """data/.rakuten-credentials を優先し、無ければ環境変数にフォールバックする。"""
    creds = {}
    if os.path.exists(CREDENTIALS_PATH):
        with open(CREDENTIALS_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                creds[key.strip()] = value.strip()
    app_id = creds.get("RAKUTEN_APP_ID") or os.environ.get("RAKUTEN_APP_ID")
    access_key = creds.get("RAKUTEN_ACCESS_KEY") or os.environ.get("RAKUTEN_ACCESS_KEY")
    return app_id, access_key


def fetch(keyword, hits):
    app_id, access_key = load_credentials()
    if not app_id or not access_key:
        sys.exit(f"{CREDENTIALS_PATH} または環境変数に RAKUTEN_APP_ID / RAKUTEN_ACCESS_KEY が見つかりません")

    params = {
        "applicationId": app_id,
        "accessKey": access_key,
        "keyword": keyword,
        "hits": hits,
        "sort": "-reviewCount",
        "availability": 1,  # 在庫ありのみ
        "format": "json",
    }
    url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Referer": APP_REFERER, "Origin": APP_REFERER.rstrip("/")})

    body = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req) as res:
                body = json.loads(res.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < MAX_RETRIES:
                wait = BACKOFF_BASE_SECONDS * (2 ** attempt)
                print(f"429（レート制限）応答。{wait}秒待って再試行します（{attempt + 1}/{MAX_RETRIES}）", file=sys.stderr)
                time.sleep(wait)
                continue
            detail = e.read().decode("utf-8", errors="replace")
            sys.exit(f"HTTPエラー {e.code}: {detail}")

    if "error" in body:
        sys.exit(f"APIエラー: {body.get('error')} - {body.get('error_description', '')}")

    return body.get("Items", [])


def to_tsv_row(item):
    d = item["Item"]
    name = d["itemName"].replace("\t", " ")
    rating = d.get("reviewAverage") or ""
    reviews = d.get("reviewCount") or ""
    price = d.get("itemPrice") or ""
    shop = d.get("shopName", "")
    url = d.get("itemUrl", "")
    return name, rating, reviews, price, shop, url


def image_url(item):
    """product-image-to-webp.pyへ渡す画像URL（mediumImageUrls優先）を1件返す。

    APIが返すmediumImageUrlsはデフォルトで `?_ex=128x128` というクエリ付きで、
    実体は128x128の極小画像（5KB前後）。これをそのまま600x600へ拡大すると
    ぼやける（実測確認済み・reports/2026-08-02.md）。クエリを外して原寸画像の
    URLを返し、拡大縮小はproduct-image-to-webp.py側のPillow処理に任せる。
    """
    d = item["Item"]
    medium = d.get("mediumImageUrls") or []
    small = d.get("smallImageUrls") or []
    urls = medium or small
    if not urls:
        return ""
    return urls[0].get("imageUrl", "").split("?")[0]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) < 2:
        sys.exit("usage: python site/scripts/fetch-rakuten-products.py <検索キーワード> [取得件数]")

    keyword = sys.argv[1]
    hits = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    hits = max(1, min(hits, 30))

    items = fetch(keyword, hits)
    if not items:
        print("該当商品なし（在庫ありに絞っているため0件の場合は availability=1 の条件を外す必要がある）")
        return

    print(f"検索キーワード: {keyword} / 取得件数: {len(items)}")
    print()
    print("--- scoring-input.tsv 用（ブランド区分は unknown 仮置き・要手動確認） ---")
    for item in items:
        name, rating, reviews, price, shop, url = to_tsv_row(item)
        print(f"{name}\t{rating}\t{reviews}\trakuten\tunknown\t{price}")
    print()
    print("--- 商品URL・販売元（実在・在庫確認の参考。CLAUDE.md 2-2の実売ページ確認は別途必要） ---")
    for item in items:
        d = item["Item"]
        print(f"- {d['itemName']}｜{d.get('shopName','')}｜{d.get('itemUrl','')}")
    print()
    print("--- 商品画像URL（試行運用・新規記事限定・D-0047。product-image-to-webp.pyへそのまま渡す） ---")
    for item in items:
        d = item["Item"]
        print(f"- {d['itemName']}｜{image_url(item)}")


if __name__ == "__main__":
    main()
