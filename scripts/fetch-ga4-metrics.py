# -*- coding: utf-8 -*-
r"""GA4 Data APIからPV数（screenPageViews）を取得するスクリプト
（2026-08-09・週次レポートへの組み込みに伴い期間引数対応版）。

--start/--end で対象期間を指定して取得する。省略時は直近7日間（従来の疎通確認動作）。
ファイルへの保存・docs/kpi.mdへの反映は行わない（週次レポート本文への転記はAIが手動で行う）。

認証情報: data/google-credentials.json（OAuthクライアントシークレット）
トークンキャッシュ: data/google-token.json
  documents・drive.file・analytics.readonly の3スコープが必要
  （sync-to-gdrive.py と共有。スコープ定義はそちら側が正本）
対象プロパティ: 547119508（「琥珀時間」・GA管理画面で確認済み・2026-08-09）

使い方:
  python site/scripts/fetch-ga4-metrics.py
  python site/scripts/fetch-ga4-metrics.py --start 2026-08-03 --end 2026-08-09

対象期間の決め方（週次レポート用）: 直近のreports/weekly-*.mdの期間表記の終了日の翌日を
開始日、当日を終了日とする（rules/weekly-report.md参照）。この決定自体はAIが
reports/配下を読んで行い、本スクリプトへは確定済みの日付をそのまま渡す。
"""

import argparse
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")

TOKEN_PATH = os.path.join(DATA_DIR, "google-token.json")
PROPERTY_ID = "547119508"

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_args():
    parser = argparse.ArgumentParser(description="GA4 PV数取得（期間指定可）")
    parser.add_argument("--start", help="開始日 YYYY-MM-DD（省略時は7daysAgo）")
    parser.add_argument("--end", help="終了日 YYYY-MM-DD（省略時はtoday）")
    args = parser.parse_args()

    if (args.start and not args.end) or (args.end and not args.start):
        parser.error("--start と --end は両方指定するか、両方省略してください。")
    for label, value in (("--start", args.start), ("--end", args.end)):
        if value and not DATE_RE.match(value):
            parser.error("%s は YYYY-MM-DD 形式で指定してください（例: 2026-08-03）: %s" % (label, value))
    return args


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = parse_args()
    start_date = args.start or "7daysAgo"
    end_date = args.end or "today"

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    if not os.path.exists(TOKEN_PATH):
        print("エラー: %s が見つかりません。先にsync-to-gdrive.pyで認証を済ませてください。" % TOKEN_PATH)
        sys.exit(1)

    creds = Credentials.from_authorized_user_file(TOKEN_PATH)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_PATH, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    svc = build("analyticsdata", "v1beta", credentials=creds)
    body = {
        "dateRanges": [{"startDate": start_date, "endDate": end_date}],
        "metrics": [{"name": "screenPageViews"}],
    }

    try:
        resp = svc.properties().runReport(
            property="properties/%s" % PROPERTY_ID, body=body
        ).execute()
    except HttpError as exc:
        print("エラー: GA4 Data APIの呼び出しに失敗しました。")
        print(str(exc))
        sys.exit(1)

    rows = resp.get("rows", [])
    if not rows:
        print("対象期間（%s〜%s）のPV: 0件（データなし）" % (start_date, end_date))
        return

    pv = rows[0]["metricValues"][0]["value"]
    print("対象期間（%s〜%s）のPV数: %s" % (start_date, end_date, pv))


if __name__ == "__main__":
    main()
