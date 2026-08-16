# -*- coding: utf-8 -*-
r"""運営ドキュメント（CLAUDE.md・docs/・.claude/settings系・rules/配下）を
Googleドキュメントへ同期する（D-0064）。対象一覧は TARGET_FILES が正本。

外部チャット窓口（Claude.aiのProject）が毎回ファイルを手動添付されなくても
最新版を読めるようにするための対応。

対応表: data/gdrive-sync-map.json（プロジェクトルート直下・Git管理外）
  {"local_path": "google_doc_id", ...}
認証情報: data/google-credentials.json（OAuthクライアントシークレット）
トークンキャッシュ: data/google-token.json（初回認証後は自動更新）

プロジェクトルートはD-0043によりGit管理外のため、これらの認証ファイルが
site/リポジトリへ混入することは構造的に起こらない。

使い方:
  python site/scripts/sync-to-gdrive.py --init   セットアップ（追記型・再実行可）
    1. ブラウザでのGoogle認証フローを起動（オーナーがブラウザで許可操作）
    2. 既存の data/gdrive-sync-map.json を読み込む（あれば）
    3. 対応表に無いファイルだけ新規Googleドキュメントを作成して追記する。
       既に対応表にあるファイルは新規作成せず既存IDを維持する。
       対応表にあるがTARGET_FILESに無いエントリも削除せず残す。
    4. 今回新規作成したドキュメントのURL一覧を標準出力に表示

  python site/scripts/sync-to-gdrive.py          通常同期
    対応表を読み、各ローカルファイルの現在の中身でGoogleドキュメント本文を
    全置換する。1件の同期失敗は他ファイルの同期を止めない。
    成功件数・失敗件数を標準出力に出す。

終了コード: 通常同期時、1件でも失敗があれば1、全件成功または対象0件なら0。
  --init時は成功すれば0、認証・作成に失敗すれば1。
"""

import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")

CREDENTIALS_PATH = os.path.join(DATA_DIR, "google-credentials.json")
TOKEN_PATH = os.path.join(DATA_DIR, "google-token.json")
SYNC_MAP_PATH = os.path.join(DATA_DIR, "gdrive-sync-map.json")

# Docs本文の読み書きに必要な最小スコープ。ドキュメント新規作成にはDrive側の
# file スコープ（このアプリが作成したファイルのみ操作可）を使う。
# analytics.readonly はGA4データ自動取得の疎通確認用（2026-08-09追加・
# site/scripts/fetch-ga4-metrics.py参照）。このファイルが同一クレデンシャル・
# トークンキャッシュのスコープ定義を兼ねているため、GA4関連スコープもここに追加する。
# webmasters.readonly はSearch Console APIでのインデックス状態調査用
# （2026-08-09追加・D-0075）。sitemaps.list / urlInspection.index.inspect
# 両方をこの1スコープでカバーできる。
SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/webmasters.readonly",
]

# 同期対象: (ローカルパス, ドキュメントタイトル)
# rules/配下は窓口（Claude.ai相談プロジェクト）が内容を推測で補って誤指示を出す
# 事故を防ぐために追加した（2026-08-16）。
TARGET_FILES = [
    (os.path.join(PROJECT_ROOT, "CLAUDE.md"), "Tea_TeaCut CLAUDE.md"),
    (os.path.join(PROJECT_ROOT, "docs", "decisions.md"), "Tea_TeaCut decisions.md"),
    (os.path.join(PROJECT_ROOT, "docs", "status.md"), "Tea_TeaCut status.md"),
    (os.path.join(PROJECT_ROOT, ".claude", "settings.json"), "Tea_TeaCut settings.json"),
    (os.path.join(PROJECT_ROOT, ".claude", "settings.local.json"), "Tea_TeaCut settings.local.json"),
    (os.path.join(PROJECT_ROOT, "docs", "tasks.md"), "Tea_TeaCut tasks.md"),
    (os.path.join(PROJECT_ROOT, "rules", "portability.md"), "Tea_TeaCut rules/portability.md"),
    (os.path.join(PROJECT_ROOT, "rules", "weekly-report.md"), "Tea_TeaCut rules/weekly-report.md"),
    (os.path.join(PROJECT_ROOT, "rules", "image-generation-flow.md"), "Tea_TeaCut rules/image-generation-flow.md"),
    (os.path.join(PROJECT_ROOT, "rules", "pinterest-api.md"), "Tea_TeaCut rules/pinterest-api.md"),
    (os.path.join(PROJECT_ROOT, "rules", "product-linking.md"), "Tea_TeaCut rules/product-linking.md"),
    (os.path.join(PROJECT_ROOT, "rules", "command-execution.md"), "Tea_TeaCut rules/command-execution.md"),
    (os.path.join(PROJECT_ROOT, "docs", "script-index.md"), "Tea_TeaCut script-index.md"),
]


def get_credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_PATH, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        return creds

    if not os.path.exists(CREDENTIALS_PATH):
        print("エラー: %s が見つかりません。オーナーによる配置が必要です。" % CREDENTIALS_PATH)
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
    creds = flow.run_local_server(port=0)
    with open(TOKEN_PATH, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    return creds


def read_file_text(path):
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def cmd_init():
    from googleapiclient.discovery import build

    creds = get_credentials()
    docs_service = build("docs", "v1", credentials=creds)

    # 既存の対応表があれば読み込み、追記型で更新する。
    # 既にIDを持つファイルは新規作成せず既存IDを維持し、TARGET_FILESから
    # 外れたエントリも削除しない（既存の共有リンクを失う事故を防ぐため）。
    sync_map = {}
    if os.path.exists(SYNC_MAP_PATH):
        with open(SYNC_MAP_PATH, "r", encoding="utf-8") as f:
            sync_map = json.load(f)

    created = []
    kept = []

    for local_path, title in TARGET_FILES:
        if local_path in sync_map:
            kept.append((title, sync_map[local_path]))
            print("既存維持: %s -> %s" % (title, sync_map[local_path]))
            continue

        if not os.path.exists(local_path):
            print("警告: %s が存在しないためスキップします。" % local_path)
            continue

        doc = docs_service.documents().create(body={"title": title}).execute()
        doc_id = doc.get("documentId")

        body_text = read_file_text(local_path)
        if body_text:
            docs_service.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": [{
                    "insertText": {
                        "location": {"index": 1},
                        "text": body_text,
                    }
                }]},
            ).execute()

        sync_map[local_path] = doc_id
        url = "https://docs.google.com/document/d/%s/edit" % doc_id
        created.append((title, url))
        print("作成完了: %s -> %s" % (title, url))

    with open(SYNC_MAP_PATH, "w", encoding="utf-8") as f:
        json.dump(sync_map, f, ensure_ascii=False, indent=2)

    print("\n--- 今回新規作成したGoogleドキュメント一覧 ---")
    if created:
        for title, url in created:
            print("%s: %s" % (title, url))
    else:
        print("（新規作成なし・すべて既存の対応表にありました）")

    print("対応表の総件数: %d件（今回新規 %d件 / 既存維持 %d件）"
          % (len(sync_map), len(created), len(kept)))

    # 新規作成も既存維持も0件＝対応表が空のままなら異常。
    if not created and not kept:
        print("エラー: 1件も対応表に登録できませんでした。")
        sys.exit(1)


def sync_one(docs_service, local_path, doc_id):
    body_text = read_file_text(local_path)

    doc = docs_service.documents().get(documentId=doc_id).execute()
    end_index = doc.get("body", {}).get("content", [])[-1].get("endIndex", 1)

    requests = []
    # 既存本文が1文字でもあれば全削除してから挿入する。
    # (endIndexは末尾の暗黙改行の次を指すため、削除範囲は end_index - 1 まで)
    if end_index > 1:
        requests.append({
            "deleteContentRange": {
                "range": {"startIndex": 1, "endIndex": end_index - 1}
            }
        })
    if body_text:
        requests.append({
            "insertText": {"location": {"index": 1}, "text": body_text}
        })

    if requests:
        docs_service.documents().batchUpdate(
            documentId=doc_id, body={"requests": requests}
        ).execute()


def cmd_sync():
    from googleapiclient.discovery import build

    if not os.path.exists(SYNC_MAP_PATH):
        print("エラー: %s がありません。先に --init を実行してください。" % SYNC_MAP_PATH)
        sys.exit(1)

    with open(SYNC_MAP_PATH, "r", encoding="utf-8") as f:
        sync_map = json.load(f)

    if not sync_map:
        print("同期対象0件。")
        sys.exit(0)

    creds = get_credentials()
    docs_service = build("docs", "v1", credentials=creds)

    ok_count = 0
    failures = []

    for local_path, doc_id in sync_map.items():
        try:
            if not os.path.exists(local_path):
                raise FileNotFoundError(local_path)
            sync_one(docs_service, local_path, doc_id)
            ok_count += 1
        except Exception as exc:
            failures.append((local_path, str(exc)))

    print("同期完了: 成功 %d件 / 失敗 %d件" % (ok_count, len(failures)))
    if failures:
        print("--- 失敗一覧 ---")
        for local_path, err in failures:
            print("%s: %s" % (local_path, err))
        sys.exit(1)

    sys.exit(0)


KNOWN_ARGS = {"--init"}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    unknown_args = [a for a in sys.argv[1:] if a not in KNOWN_ARGS]
    if unknown_args:
        print(
            "エラー: 未知の引数を検出しました: %s（既知の引数は %s のみ、または引数なしの通常同期）"
            % (" ".join(unknown_args), ", ".join(sorted(KNOWN_ARGS)))
        )
        sys.exit(1)

    if "--init" in sys.argv:
        cmd_init()
    else:
        cmd_sync()


if __name__ == "__main__":
    main()
