# -*- coding: utf-8 -*-
r"""週次レポート用のPinterest実績数値を、対象期間の算出ごと自動取得する（D-0155）。

背景: 週次ルーチンの対象期間は「直近の weekly-*.md の終了日を読む」方式で、AIが
ファイルを読んで手で日付を決めていた。さらにPinterestの数値はオーナーへのCSV依頼に
依存していた。対象期間の決定・Pinterest数値の取得・GA4へ渡すコマンド行の3つを
このスクリプト1本の出力に集約し、AIが手で計算する余地を無くす。

動作:
  1. 基準日（既定は今日・検証用に --date YYYY-MM-DD で差し替え可）から
     「直近に終わった週の月曜〜日曜」を求める。曜日で分岐せず単一式で求める。
     基準日が日曜なら、その日を含む週ではなく前週の月〜日になる
     （例: 基準日2026-08-23(日) → 2026-08-10〜2026-08-16）。
     この期間算出は check-routine-due.py の last_complete_week() をimportして呼ぶ
     （D-0156・同じ計算をこちらで再実装しない）。
  2. 週次レポートの書き込み先ファイル名は check-routine-due.py の weekly_filename() を
     importして呼ぶ（週番号の決め方をこちらで再実装しない・二重実装を作らない）。
  3. GET /v5/user_account/analytics を1回だけ呼ぶ（GET系のみ。POST/PATCH/DELETEは
     呼ばない。ピン単位のループも実装しない）。認証・リクエストは pinterest_token.py /
     pinterest_api.py をそのまま再利用し、その2本には一切変更を加えない。
  4. 各日の data_status が READY の日だけを合計に採用する。固定日数のオフセットは
     使わない（Pinterest側の確定タイミングは日によって動くため）。READYでない日は
     値を採用せず、日付と状態を明示する。

出力（AIが手で計算する余地を残さないため、次の4つを必ず出す）:
  1) 対象期間（開始日・終了日）
  2) 週次レポートの書き込み先ファイル名 weekly-YYYY-WW.md
  3) fetch-ga4-metrics.py に渡すべきコマンド行（--start/--end を埋めた完全な形）
  4) 4指標の期間合計と日次内訳（data_status 付き）

月次など任意の期間（--since / --until・D-0267）:
  --since YYYY-MM-DD --until YYYY-MM-DD を必ず2つ一緒に指定すると、その期間（両端を含む）
  の合計を出す。この場合、基準日・週次レポート書き込み先・GA4取得コマンドは出さない
  （週次専用の情報のため）。両方とも省いた場合の動作・出力は変更前と同じ。
  口座単位の合計であり、ピン単位の日次実績（data/pin-daily-metrics.tsv）の合計とは
  定義が異なるため混ぜない。

終了コード:
  0 = 対象期間のすべての日が READY
  1 = READYでない日がある（値は出力したうえで警告する）
  2 = 取得・認証・import等に失敗した（数値を作らずそのまま止める）

使い方:
  python site/scripts/fetch-pinterest-analytics.py
  python site/scripts/fetch-pinterest-analytics.py --date 2026-08-23   # 検証用
  python site/scripts/fetch-pinterest-analytics.py --since 2026-09-01 --until 2026-09-30   # 月次
"""

import argparse
import datetime
import importlib.util
import os
import re
import sys
import urllib.error
import urllib.parse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import pinterest_api  # noqa: E402
import pinterest_token  # noqa: E402

ROUTINE_DUE_PATH = os.path.join(SCRIPT_DIR, "check-routine-due.py")

# 取得する指標。順序はそのまま出力順になる。
METRIC_TYPES = ["IMPRESSION", "SAVE", "OUTBOUND_CLICK", "PIN_CLICK"]

API_TIMEOUT_SECONDS = 20
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_routine_due_functions():
    """check-routine-due.py の last_complete_week() と weekly_filename() を
    importして (last_complete_week, weekly_filename) で返す（D-0156）。

    対象期間の算出も週番号の決め方も、こちら側では実装しない（同じ計算を2箇所に
    持たないため）。ファイル名にハイフンを含み通常のimport文が使えないため、
    他スクリプトと同じくimportlibで読み込む（check-routine-due.py 側の main() は
    __name__ == "__main__" ガードの内側にあるため、importしても実行されない）。
    """
    spec = importlib.util.spec_from_file_location("check_routine_due", ROUTINE_DUE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError("check-routine-due.py を読み込めません（%s）" % ROUTINE_DUE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ("last_complete_week", "weekly_filename"):
        if not hasattr(module, name):
            raise ImportError("check-routine-due.py に %s() が見つかりません" % name)
    return module.last_complete_week, module.weekly_filename


def parse_args():
    parser = argparse.ArgumentParser(description="週次レポート用Pinterest実績の取得（対象期間も算出）")
    parser.add_argument("--date", help="基準日 YYYY-MM-DD（省略時は今日・検証用）")
    parser.add_argument("--since", help="期間の開始日 YYYY-MM-DD（--until と一緒に指定・月次用）")
    parser.add_argument("--until", help="期間の終了日 YYYY-MM-DD（--since と一緒に指定・月次用）")
    args = parser.parse_args()
    if args.date and not DATE_RE.match(args.date):
        parser.error("--date は YYYY-MM-DD 形式で指定してください: %s" % args.date)
    if bool(args.since) != bool(args.until):
        parser.error("--since と --until は必ず2つ一緒に指定してください")
    if args.since:
        for name in ("since", "until"):
            value = getattr(args, name)
            if not DATE_RE.match(value):
                parser.error("--%s は YYYY-MM-DD 形式で指定してください: %s" % (name, value))
        if args.date:
            parser.error("--date と --since/--until は同時に指定できません")
        try:
            since = datetime.date.fromisoformat(args.since)
            until = datetime.date.fromisoformat(args.until)
        except ValueError as e:
            parser.error("日付として解釈できません: %s" % e)
        if since > until:
            parser.error("--since は --until 以前の日付にしてください")
    return args


def fetch_analytics(access_token, start_date, end_date):
    """GET /v5/user_account/analytics を1回だけ呼ぶ。"""
    query = urllib.parse.urlencode({
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "metric_types": ",".join(METRIC_TYPES),
    })
    return pinterest_api.request(
        "GET", "/user_account/analytics?" + query, access_token, timeout=API_TIMEOUT_SECONDS,
    )


def extract_daily_metrics(payload):
    """応答から daily_metrics のリストを取り出す。

    v5の応答は分割指定なしの場合、"all" キーの下に daily_metrics と summary_metrics を
    持つ形になる。将来の形式差に備えてトップレベル直下も見るが、見つからない場合は
    推測で空リストを返さず例外にする（沈黙する失敗を作らないため）。
    """
    if isinstance(payload, dict):
        if isinstance(payload.get("daily_metrics"), list):
            return payload["daily_metrics"]
        for value in payload.values():
            if isinstance(value, dict) and isinstance(value.get("daily_metrics"), list):
                return value["daily_metrics"]
    raise ValueError("応答に daily_metrics が見つかりません: %r" % (payload,))


def build_day_map(daily_metrics):
    """日付文字列 → (data_status, 指標の辞書) の対応表を作る。"""
    day_map = {}
    for entry in daily_metrics:
        if not isinstance(entry, dict):
            continue
        date_key = entry.get("date")
        if not date_key:
            continue
        metrics = entry.get("metrics") or entry.get("metric") or {}
        day_map[date_key] = (entry.get("data_status", "UNKNOWN"), metrics)
    return day_map


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = parse_args()

    if args.since:
        # 任意期間（月次用・D-0267）。週次専用の出力（基準日・書き込み先・GA4コマンド）は出さない。
        start_monday = datetime.date.fromisoformat(args.since)
        end_sunday = datetime.date.fromisoformat(args.until)
        print("対象期間: %s 〜 %s（--since/--until 指定・口座単位）" % (
            start_monday.isoformat(), end_sunday.isoformat()))
        print("")
    else:
        base = datetime.date.fromisoformat(args.date) if args.date else datetime.date.today()

        try:
            last_complete_week, weekly_filename = load_routine_due_functions()
        except Exception as e:
            print("【エラー】check-routine-due.py の関数を読み込めませんでした: %s" % e)
            return 2

        start_monday, end_sunday = last_complete_week(base)
        report_name = weekly_filename(end_sunday)
        ga4_command = "python site/scripts/fetch-ga4-metrics.py --start %s --end %s" % (
            start_monday.isoformat(), end_sunday.isoformat(),
        )

        print("基準日: %s" % base.isoformat())
        print("対象期間: %s 〜 %s（直近に終わった週の月〜日）" % (
            start_monday.isoformat(), end_sunday.isoformat()))
        print("週次レポート書き込み先: reports/%s" % report_name)
        print("GA4取得コマンド: %s" % ga4_command)
        print("")
    period_days = (end_sunday - start_monday).days + 1

    try:
        status = pinterest_token.ensure_fresh()
        access_token = status["access_token"]
    except Exception as e:
        print("【エラー】Pinterestアクセストークンの準備に失敗しました: %s" % e)
        return 2

    try:
        payload = fetch_analytics(access_token, start_monday, end_sunday)
        daily_metrics = extract_daily_metrics(payload)
    except pinterest_api.PinterestApiError as e:
        print("【エラー】Pinterest Analytics APIがエラーを返しました: %s" % e)
        return 2
    except urllib.error.URLError as e:
        print("【エラー】Pinterest Analytics APIへの通信に失敗しました: %s" % e)
        return 2
    except ValueError as e:
        print("【エラー】Pinterest Analytics APIの応答を解釈できませんでした: %s" % e)
        return 2

    day_map = build_day_map(daily_metrics)

    totals = dict((m, 0) for m in METRIC_TYPES)
    not_ready = []
    rows = []
    for i in range(period_days):
        day = start_monday + datetime.timedelta(days=i)
        key = day.isoformat()
        if key not in day_map:
            not_ready.append((key, "NO_DATA"))
            rows.append((key, "NO_DATA", None))
            continue
        data_status, metrics = day_map[key]
        if data_status != "READY":
            not_ready.append((key, data_status))
            rows.append((key, data_status, None))
            continue
        values = {}
        for m in METRIC_TYPES:
            v = metrics.get(m, 0)
            values[m] = int(v) if isinstance(v, (int, float)) else 0
            totals[m] += values[m]
        rows.append((key, data_status, values))

    print("【期間合計】（data_status が READY の日のみ集計）")
    for m in METRIC_TYPES:
        print("  %-15s %s" % (m, totals[m]))
    print("  集計採用日数: %d / %d 日" % (period_days - len(not_ready), period_days))
    print("")

    print("【日次内訳】")
    print("  %-12s %-10s " % ("日付", "状態") + " ".join("%-15s" % m for m in METRIC_TYPES))
    for key, data_status, values in rows:
        if values is not None:
            cells = " ".join("%-15s" % values[m] for m in METRIC_TYPES)
        else:
            cells = " ".join("%-15s" % "(不採用)" for _ in METRIC_TYPES)
        print("  %-12s %-10s " % (key, data_status) + cells)
    print("")

    if not_ready:
        print("【警告】data_status が READY でない日があります（値は合計に採用していません）:")
        for key, data_status in not_ready:
            print("  %s: %s" % (key, data_status))
        return 1

    print("対象期間の%d日すべてが READY です。" % period_days)
    return 0


if __name__ == "__main__":
    sys.exit(main())
