# -*- coding: utf-8 -*-
r"""週次・月次ルーチンの実施要否を、日付とファイルの有無だけで機械判定して通知する
（読み取り専用・他ファイルへの書き込みは一切行わない）。

背景: 週次レポート（CLAUDE.md 6節）・月次レポート・前月実績の催促（D-0036）は
すべて文章での指示だけに頼っており、AIがその日に思い出せるかどうかに依存していた。
check-image-gen-needed-today.py（D-0078）と同じ方針で、あいまいな推測ロジックを持たせず
「日付」と「ファイルの有無」だけで判定する。文脈からの推測・自由記述文の解釈は行わない。

判定項目:
  1. 週次レポート（日曜のみ）
     基準日が日曜で、かつ今週分の reports/weekly-YYYY-WW.md が存在しなければ通知する。
     日曜以外の曜日では週次に関する出力を一切行わない（取りこぼしは次の日曜に自然に
     検知される。毎日通知すると通知そのものが形骸化するため）。
     WW の決め方: 既存ファイル（weekly-2026-31/32/33.md）の実運用に合わせ、
     「対象日曜の翌日（月曜）のISO週番号」を使う。実測での対応:
       2026-07-26(日)→翌日07-27のISO週31 → weekly-2026-31.md（実在）
       2026-08-02(日)→翌日08-03のISO週32 → weekly-2026-32.md（実在）
       2026-08-09(日)→翌日08-10のISO週33 → weekly-2026-33.md（実在）
  2. 月次レポート
     基準日が当月1日以降（=常に真）で、前月分の reports/monthly-YYYY-MM.md が
     存在しなければ通知する。
  3. 月次実績の催促（D-0036をこのスクリプトへ移管）
     基準日が当月4日以降で、docs/kpi.md の表に前月（YYYY-MM形式）の行が
     存在しなければ通知する。

出力:
  該当項目があればその通知行を1行以上、1件も無ければ "ROUTINE_NONE" の1行のみ。
  終了コードは常に0（情報提供のみ。ブロックや強制終了は行わない）。

該当項目があってもAIは週次・月次の作業そのものに着手しない。オーナーへ
「今日は◯◯が必要な日です。実施しますか」と報告し、明示的な指示を待つ。

使い方:
  python site/scripts/check-routine-due.py
  python site/scripts/check-routine-due.py --date 2026-08-16   # 検証用（省略時は今日）
"""

import datetime
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORTS_DIR = os.path.join(ROOT, "reports")
KPI_MD = os.path.join(ROOT, "docs", "kpi.md")

# 月次実績の催促を始める日（当月のこの日以降）
KPI_REMINDER_DAY = 4


def read_text(path):
    if not os.path.isfile(path):
        return ""
    with io.open(path, "r", encoding="utf-8") as f:
        return f.read()


def parse_args(argv):
    """--date YYYY-MM-DD を受け取る（省略時は今日）。曜日判定の検証を、スクリプト本体を
    書き換えずに行えるようにするため（--date 2026-08-16 で日曜の挙動を実測できる）。"""
    base = datetime.date.today()
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--date":
            if i + 1 >= len(argv):
                raise SystemExit("--date には YYYY-MM-DD を指定してください")
            base = datetime.date.fromisoformat(argv[i + 1])
            i += 2
            continue
        if arg.startswith("--date="):
            base = datetime.date.fromisoformat(arg.split("=", 1)[1])
            i += 1
            continue
        raise SystemExit("不明な引数: %s（使えるのは --date YYYY-MM-DD のみ）" % arg)
    return base


def weekly_filename(sunday):
    """対象日曜に対応する週次レポートのファイル名を返す（docstring 1 の対応表を参照）。"""
    iso_year, iso_week, _ = (sunday + datetime.timedelta(days=1)).isocalendar()
    return "weekly-%04d-%02d.md" % (iso_year, iso_week)


def previous_month(base):
    """基準日の前月を (year, month) で返す。1月なら前年12月。"""
    if base.month == 1:
        return base.year - 1, 12
    return base.year, base.month - 1


def has_kpi_row(month_key):
    """docs/kpi.md の表に month_key（YYYY-MM）の行があるか。表の行（|始まり）だけを見る。"""
    for raw in read_text(KPI_MD).split("\n"):
        line = raw.strip()
        if line.startswith("|") and month_key in line:
            return True
    return False


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    base = parse_args(sys.argv[1:])
    messages = []

    # 1. 週次レポート（日曜のみ・月曜=0 ... 日曜=6）
    if base.weekday() == 6:
        name = weekly_filename(base)
        if not os.path.isfile(os.path.join(REPORTS_DIR, name)):
            messages.append(
                "週次レポート未生成（%s は日曜・reports/%s がありません）" % (base.isoformat(), name)
            )

    # 2. 月次レポート（当月1日以降=常に真）
    prev_year, prev_month_num = previous_month(base)
    month_key = "%04d-%02d" % (prev_year, prev_month_num)
    monthly_name = "monthly-%s.md" % month_key
    if not os.path.isfile(os.path.join(REPORTS_DIR, monthly_name)):
        messages.append("前月分の月次レポート未生成（reports/%s がありません）" % monthly_name)

    # 3. 月次実績の催促（当月4日以降・D-0036）
    if base.day >= KPI_REMINDER_DAY and not has_kpi_row(month_key):
        messages.append(
            "前月分（%s）の実績（GA4月間PV・ASP月間成果・Pinterest Analytics月間CSV）が"
            "未提供です。オーナーへ提出を依頼してください" % month_key
        )

    if messages:
        for message in messages:
            print(message)
    else:
        print("ROUTINE_NONE")

    sys.exit(0)


if __name__ == "__main__":
    main()
