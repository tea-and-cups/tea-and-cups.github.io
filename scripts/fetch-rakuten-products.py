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

  affiliateId を渡し、APIが返す affiliateUrl（hb.afl.rakuten.co.jp の
  アフィリエイトリンク）を別セクションで出力する（D-0260）。Chromeが使えず
  リンク作成ページ（rakuten-freelink-extract.js）を使えない日に、画像なしの
  テキストリンクとして記事に使うためのもの。
  APIの商品画像（mediumImageUrls）は出力しない。楽天ウェブサービス規約 第10条(9)
  によりAPIから取った画像は保存できないため（旧 D-0047 の経路は D-0260 で廃止）。

使い方:
  python site/scripts/fetch-rakuten-products.py <検索キーワード> [取得件数(既定5・最大30)]

前提:
  data/.rakuten-credentials（KEY=VALUE形式、RAKUTEN_APP_ID・RAKUTEN_ACCESS_KEY・
  RAKUTEN_AFFILIATE_ID）に楽天ウェブサービスのアプリケーションID・アクセスキー・
  楽天アフィリエイトのアフィリエイトIDを保存しておく。data/ はGit管理外
  （decision_no_root_gitify）のため、キーをファイルに直接置いてよい。ファイルが無い場合は
  環境変数 RAKUTEN_APP_ID / RAKUTEN_ACCESS_KEY / RAKUTEN_AFFILIATE_ID にフォールバックする。
  RAKUTEN_AFFILIATE_ID が無い場合は affiliateUrl を出さず、その旨を表示する（他の出力は変わらない）。
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
APP_REFERER = "https://kohaku-jikan.com/"  # 楽天アプリ登録画面の「アプリケーションURL」と一致させる

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
    affiliate_id = creds.get("RAKUTEN_AFFILIATE_ID") or os.environ.get("RAKUTEN_AFFILIATE_ID")
    return app_id, access_key, affiliate_id


def fetch(keyword, hits):
    app_id, access_key, affiliate_id = load_credentials()
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
    if affiliate_id:
        params["affiliateId"] = affiliate_id
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


def plain_item_url(d):
    """商品ページのURL（アフィリエイトでない素のURL）を返す。

    affiliateId を渡すと、APIの itemUrl もアフィリエイトリンク（hb.afl.rakuten.co.jp）になる
    （2026-10-03実測）。実在・在庫確認やリンク作成ページへ渡すのは素の商品URLのため、
    pc パラメータから取り出す。
    """
    url = d.get("itemUrl", "")
    parsed = urllib.parse.urlparse(url)
    if parsed.hostname == "hb.afl.rakuten.co.jp":
        pc = urllib.parse.parse_qs(parsed.query).get("pc")
        if pc:
            return pc[0]
    return url


def to_tsv_row(item):
    d = item["Item"]
    name = d["itemName"].replace("\t", " ")
    rating = d.get("reviewAverage") or ""
    reviews = d.get("reviewCount") or ""
    price = d.get("itemPrice") or ""
    shop = d.get("shopName", "")
    url = d.get("itemUrl", "")
    return name, rating, reviews, price, shop, url


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
        print(f"- {d['itemName']}｜{d.get('shopName','')}｜{plain_item_url(d)}")
    print()
    print("--- affiliateUrl（Chromeが使えない日の文字リンク用・画像なし・D-0260。リンク作成ページが使える日は rakuten-freelink-extract.js を使う） ---")
    if not any(item["Item"].get("affiliateUrl") for item in items):
        print("（affiliateUrl なし。data/.rakuten-credentials に RAKUTEN_AFFILIATE_ID があるか確認する）")
    for item in items:
        d = item["Item"]
        if d.get("affiliateUrl"):
            print(f"- {d['itemName']}｜{d['affiliateUrl']}")
    print()
    print("※APIの商品画像（mediumImageUrls）は記事に使わないため出力しない（楽天ウェブサービス規約 第10条(9)・D-0260）")


if __name__ == "__main__":
    main()
