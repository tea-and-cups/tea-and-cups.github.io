# -*- coding: utf-8 -*-
r"""週次・月次ルーチンの実施要否を、日付とファイルの有無だけで機械判定して通知する
（読み取り専用・他ファイルへの書き込みは一切行わない）。

背景: 週次レポート（CLAUDE.md 6節）・月次レポート・前月実績の催促（D-0036）は
すべて文章での指示だけに頼っており、AIがその日に思い出せるかどうかに依存していた。
check-image-gen-needed-today.py（D-0078）と同じ方針で、あいまいな推測ロジックを持たせず
「日付」と「ファイルの有無」だけで判定する。文脈からの推測・自由記述文の解釈は行わない。

判定項目:
  1. 週次レポート（直近4週の未生成週を検知・D-0095）
     「直近に終わった週の日曜」（last_complete_week()・D-0156）を起点に、そこから
     遡る4回分の日曜それぞれについて、対応する reports/weekly-YYYY-WW.md の有無を
     確認する。基準日が日曜でも、その日を含む週はまだ終わっていないため対象にしない
     （期間定義を fetch-pinterest-analytics.py と揃えるため。D-0156）。存在しない週があれば、
     その週ごとに通知する。上限は4週（約1か月）固定とし、それより古い週次の
     欠落は遡って検知しない（古すぎる週次レポートは遡って作る意味がないため。
     窓口の運用方針）。
     通知文では、今回の対象週（起点の日曜）なのか、それより前の日曜
     （過去の週が未生成のまま残っている）なのかを区別する。
     （旧実装は「日曜のみ判定・取りこぼしは次の日曜に自然に検知される」として
     いたが誤りだった。weekly_filename() は基準日ベースで週番号を算出するため、
     日曜のセッションを1回でも飛ばすとその週は永久に検知されないまま欠落して
     いた。D-0095でこの前提を修正した）。
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

# 週次レポートの未生成チェックを遡る上限週数（D-0095・古すぎる週は遡って作る意味がないため固定）
WEEKLY_LOOKBACK_WEEKS = 4


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


def last_complete_week(base):
    """基準日から「直近に終わった週の月曜・日曜」を (monday, sunday) で返す。

    曜日ごとの場合分けはしない。(weekday+1) % 7 は「直近の日曜からの経過日数」
    （日曜なら0）。そこから -1 して再度 mod 7 し +1 することで、0 を 7 に写しつつ
    他の値はそのまま残す。結果は常に「基準日より前にある直近の日曜」になる。
      基準日2026-08-23(日) → 7日前の 2026-08-16(日) → 週は 2026-08-10〜08-16
      基準日2026-08-19(水) → 3日前の 2026-08-16(日) → 週は 2026-08-10〜08-16

    fetch-pinterest-analytics.py もこの関数をimportして使う（同じ期間算出を
    2箇所に持たないため）。
    """
    days_since_sunday = (base.weekday() + 1) % 7
    days_back = (days_since_sunday - 1) % 7 + 1
    sunday = base - datetime.timedelta(days=days_back)
    monday = sunday - datetime.timedelta(days=6)
    return monday, sunday


def weekly_filename(sunday):
    """対象日曜に対応する週次レポートのファイル名を返す（docstring 1 の対応表を参照）。"""
    iso_year, iso_week, _ = (sunday + datetime.timedelta(days=1)).isocalendar()
    return "weekly-%04d-%02d.md" % (iso_year, iso_week)


def previous_month(base):
    """基準日の前月を (year, month) で返す。1月なら前年12月。"""
    if base.month == 1:
        return base.year - 1, 12
    return base.year, base.month - 1


EMPTY_CELL_VALUES = ("", "-", "ー", "—", "未入力")


def has_kpi_row(month_key):
    """docs/kpi.md の表に month_key（YYYY-MM）の行があり、かつPV列に実数値が
    入っているか。行の絞り込みは「月列（cells[1]）をstripした値がmonth_keyと
    完全一致するか」で行う（特記事項欄等、月列以外のセルにmonth_key文字列が
    含まれるだけの行を誤ってヒットさせないため。D-0094）。行の存在だけでなく、
    PV列の中身が空文字・「-」等の未記載を表す値でないことまで見る
    （空値行を先に作った場合の silent failure を防ぐため。D-0091）。"""
    for raw in read_text(KPI_MD).split("\n"):
        line = raw.strip()
        if not line.startswith("|"):
            continue
        cells = line.split("|")
        # cells[0] は "|" の前の空文字。cells[1] が月列、cells[2] がPV列。
        if len(cells) < 3:
            continue
        if cells[1].strip() != month_key:
            continue
        pv_cell = cells[2].strip()
        if pv_cell in EMPTY_CELL_VALUES:
            continue
        return True
    return False


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    base = parse_args(sys.argv[1:])
    messages = []

    # 1. 週次レポート（直近4週の未生成週を検知・D-0095）
    # 起点は「直近に終わった週の日曜」（D-0156）。基準日が日曜でもその日を含む週は
    # まだ終わっていないため対象にしない。4週ルックバックはD-0095のまま維持する。
    _, target_sunday = last_complete_week(base)
    for i in range(WEEKLY_LOOKBACK_WEEKS):
        sunday = target_sunday - datetime.timedelta(weeks=i)
        name = weekly_filename(sunday)
        if os.path.isfile(os.path.join(REPORTS_DIR, name)):
            continue
        if sunday == target_sunday:
            messages.append(
                "週次レポート未生成（%s は日曜・今週分の reports/%s がありません）"
                % (sunday.isoformat(), name)
            )
        else:
            messages.append(
                "週次レポート未生成（過去の週が未生成のまま残っています。%s（日曜）分の"
                " reports/%s がありません）" % (sunday.isoformat(), name)
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
