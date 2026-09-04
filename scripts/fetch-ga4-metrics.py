# -*- coding: utf-8 -*-
r"""GA4 Data APIからPV数（screenPageViews）と流入内訳を取得するスクリプト
（2026-08-09・週次レポートへの組み込みに伴い期間引数対応版
　／2026-09-04・日別レポートと参照元別レポートを追加・D-0197）。

--start/--end で対象期間を指定して取得する。省略時は直近7日間（従来の疎通確認動作）。
出力は3ブロック構成:
  1) 対象期間のPV数（従来どおり・書式・順序とも不変）
  2) 日別レポート（date × sessions/totalUsers/screenPageViews・APIコールは1回）
  3) 参照元別レポート（sessionSourceMedium × sessions・降順・上位20行＋「その他」に合算）
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

# 参照元別レポートの表示上限。これを超えた分は1行の「その他」へ合算する
# （参照元が増えても出力量が比例して増えないようにするため・D-0197）
SOURCE_ROW_LIMIT = 20


def run_report(svc, body):
    """runReportを1回呼び、失敗時はメッセージを出して終了する。"""
    from googleapiclient.errors import HttpError

    try:
        return svc.properties().runReport(
            property="properties/%s" % PROPERTY_ID, body=body
        ).execute()
    except HttpError as exc:
        print("エラー: GA4 Data APIの呼び出しに失敗しました。")
        print(str(exc))
        sys.exit(1)


def format_date(value):
    """GA4のdateディメンション（YYYYMMDD）をYYYY-MM-DD表記にする。"""
    if len(value) == 8 and value.isdigit():
        return "%s-%s-%s" % (value[:4], value[4:6], value[6:])
    return value


def print_daily_report(svc, start_date, end_date):
    """日別レポート。日数によらずAPIコールは常に1回。"""
    body = {
        "dateRanges": [{"startDate": start_date, "endDate": end_date}],
        "dimensions": [{"name": "date"}],
        "metrics": [
            {"name": "sessions"},
            {"name": "totalUsers"},
            {"name": "screenPageViews"},
        ],
        "orderBys": [{"dimension": {"dimensionName": "date"}}],
    }
    resp = run_report(svc, body)
    rows = resp.get("rows", [])

    print("")
    print("[日別]（%s〜%s）" % (start_date, end_date))
    if not rows:
        print("  データなし")
        return

    print("  %-12s %8s %8s %8s" % ("日付", "セッション", "ユーザー", "PV"))
    total = [0, 0, 0]
    for row in rows:
        date_value = format_date(row["dimensionValues"][0]["value"])
        values = [int(m["value"]) for m in row["metricValues"]]
        total = [a + b for a, b in zip(total, values)]
        print("  %-12s %8d %8d %8d" % (date_value, values[0], values[1], values[2]))
    print("  %-12s %8d %8d %8d" % ("合計", total[0], total[1], total[2]))


def print_source_report(svc, start_date, end_date):
    """参照元別レポート。セッション数の降順・上位SOURCE_ROW_LIMIT行＋「その他」。"""
    body = {
        "dateRanges": [{"startDate": start_date, "endDate": end_date}],
        "dimensions": [{"name": "sessionSourceMedium"}],
        "metrics": [{"name": "sessions"}],
        "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
    }
    resp = run_report(svc, body)
    rows = resp.get("rows", [])

    print("")
    print("[参照元/メディア別セッション]（%s〜%s）" % (start_date, end_date))
    if not rows:
        print("  データなし")
        return

    pairs = [
        (row["dimensionValues"][0]["value"], int(row["metricValues"][0]["value"]))
        for row in rows
    ]
    pairs.sort(key=lambda item: item[1], reverse=True)

    head = pairs[:SOURCE_ROW_LIMIT]
    rest = pairs[SOURCE_ROW_LIMIT:]
    for name, sessions in head:
        print("  %-40s %6d" % (name, sessions))
    if rest:
        print("  %-40s %6d" % ("その他（%d件）" % len(rest), sum(s for _, s in rest)))
    print("  %-40s %6d" % ("合計", sum(s for _, s in pairs)))


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

    resp = run_report(svc, body)

    rows = resp.get("rows", [])
    if not rows:
        print("対象期間（%s〜%s）のPV: 0件（データなし）" % (start_date, end_date))
    else:
        pv = rows[0]["metricValues"][0]["value"]
        print("対象期間（%s〜%s）のPV数: %s" % (start_date, end_date, pv))

    # 以下は既存出力の後ろへの追記（既存行の書式・順序・文言は変更しない・D-0197）
    print_daily_report(svc, start_date, end_date)
    print_source_report(svc, start_date, end_date)


if __name__ == "__main__":
    main()
