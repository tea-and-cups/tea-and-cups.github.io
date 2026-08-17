# -*- coding: utf-8 -*-
"""Search Console API の状態を読み取り専用で取得する（D-0146）。

GSCインデックス問題（docs/gsc-log.md が正本）の再測定用。
GET系のみを呼び、サイトマップの送信・削除・インデックス登録リクエスト等の
書き込み系APIは一切呼ばない。

認証は sync-to-gdrive.py と同じ data/google-credentials.json ／
data/google-token.json をそのまま使う（スコープに
webmasters.readonly が含まれている前提。再認可・スコープ変更はしない）。

使い方:
  python site/scripts/check-gsc-status.py    引数なし

出力:
  1. sitemaps.list: 送信済みサイトマップごとの lastDownloaded / isPending /
     warnings / errors / contents 件数
  2. urlInspection.index.inspect: トップページ・最古記事・直近記事の
     coverageState / lastCrawlTime / robotsTxtState / indexingState /
     pageFetchState / userCanonical / googleCanonical

終了コード: 取得できれば0、認証・API呼び出しに失敗すれば1。
"""

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
POSTS_DIR = os.path.join(PROJECT_ROOT, "site", "src", "content", "posts")

CREDENTIALS_PATH = os.path.join(DATA_DIR, "google-credentials.json")
TOKEN_PATH = os.path.join(DATA_DIR, "google-token.json")

# GSCプロパティの登録文字列（URLプレフィックス型・末尾スラッシュあり）
SITE_URL = "https://tea-and-cups.github.io/"

# 読み取り専用スコープのみ。sync-to-gdrive.py の SCOPES と同一の集合を渡さないと
# 既存トークンの再利用時にスコープ不一致で弾かれるため、同じ並びを使う。
SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/webmasters.readonly",
]

INSPECT_FIELDS = (
    "coverageState",
    "lastCrawlTime",
    "robotsTxtState",
    "indexingState",
    "pageFetchState",
    "userCanonical",
    "googleCanonical",
)


def get_credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not os.path.exists(TOKEN_PATH):
        print("エラー: %s が見つかりません。sync-to-gdrive.py --init が未実行です。" % TOKEN_PATH)
        sys.exit(1)

    creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_PATH, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        return creds

    # 再認可はこのスクリプトでは行わない（オーナー判断事項）。
    print("エラー: 既存トークンが無効です。再認可はこのスクリプトでは行いません。")
    sys.exit(1)


def read_frontmatter_date(path):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("date:"):
                return line.split(":", 1)[1].strip().strip('"').strip("'")
    return None


def oldest_and_newest_post_urls():
    entries = []
    for name in os.listdir(POSTS_DIR):
        if not name.endswith(".md"):
            continue
        date = read_frontmatter_date(os.path.join(POSTS_DIR, name))
        if date:
            entries.append((date, name[:-3]))
    entries.sort()
    if not entries:
        return []
    oldest = entries[0]
    newest = entries[-1]
    return [
        ("最古の記事 %s" % oldest[0], "%sposts/%s/" % (SITE_URL, oldest[1])),
        ("直近の記事 %s" % newest[0], "%sposts/%s/" % (SITE_URL, newest[1])),
    ]


def show_sitemaps(service):
    print("=== sitemaps.list（%s） ===" % SITE_URL)
    res = service.sitemaps().list(siteUrl=SITE_URL).execute()
    sitemaps = res.get("sitemap", [])
    if not sitemaps:
        print("送信済みサイトマップが0件です。")
        return
    for sm in sitemaps:
        print("- path: %s" % sm.get("path"))
        print("  lastDownloaded: %s" % sm.get("lastDownloaded", "(フィールドなし)"))
        print("  lastSubmitted:  %s" % sm.get("lastSubmitted", "(フィールドなし)"))
        print("  isPending: %s / isSitemapsIndex: %s / type: %s"
              % (sm.get("isPending"), sm.get("isSitemapsIndex"), sm.get("type")))
        print("  warnings: %s / errors: %s" % (sm.get("warnings"), sm.get("errors")))
        contents = sm.get("contents", [])
        if contents:
            for c in contents:
                print("  contents: type=%s submitted=%s indexed=%s"
                      % (c.get("type"), c.get("submitted"), c.get("indexed")))
        else:
            print("  contents: 0件（フィールドなし）")


def show_inspections(service, targets):
    print()
    print("=== urlInspection.index.inspect ===")
    for label, url in targets:
        print("- %s: %s" % (label, url))
        body = {"inspectionUrl": url, "siteUrl": SITE_URL}
        res = service.urlInspection().index().inspect(body=body).execute()
        result = res.get("inspectionResult", {}).get("indexStatusResult", {})
        for field in INSPECT_FIELDS:
            print("  %s: %s" % (field, result.get(field, "(フィールドなし)")))


def main():
    try:
        from googleapiclient.discovery import build
    except ImportError:
        print("エラー: google-api-python-client が見つかりません。")
        sys.exit(1)

    creds = get_credentials()
    service = build("searchconsole", "v1", credentials=creds, cache_discovery=False)

    targets = [("トップページ", SITE_URL)] + oldest_and_newest_post_urls()
    try:
        show_sitemaps(service)
        show_inspections(service, targets)
    except Exception as e:
        print("エラー: API呼び出しに失敗しました: %s" % e)
        sys.exit(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
