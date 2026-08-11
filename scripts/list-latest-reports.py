# -*- coding: utf-8 -*-
r"""最新レポート日の枝番ファイル一覧を出す（引数なし・読み取り専用・D-0108）。

背景: CLAUDE.md 5節ステップ1「前日の reports/ を読み」は日次ルーチンでしか走らず、
また枝番のどこまでを読むのかが不明確で、持ち越し情報の読み落としリスクがあった。
読むべきファイルの列挙をセッション開始時のフック側へ移し、起動の仕方に依存させない。

動作:
  - reports/ 配下の `YYYY-MM-DD.md` / `YYYY-MM-DD-N.md` 形式のファイルのうち、
    基準日（実行時のローカル日付）以前で最も新しい日付を1日ぶん特定する。
    今日ぶんのファイルが既にあれば今日を対象にする（同日2回目以降のセッションで、
    同じ日の先行セッションの持ち越しを拾うため）。
  - その日のファイルを枝番順（枝番なし→2→3…）に、ROOTからの相対パスで1行ずつ出力する。
    先頭に `REPORTS_LATEST: YYYY-MM-DD` の1行を付ける。
  - 該当ファイルが1本も無い場合は `REPORTS_NONE` の1行だけを出力する。
  - weekly-*.md / monthly-*.md / アンダースコア始まりのファイルは対象外
    （ファイル名の日付部分の一致のみで判定するため、この命名規則上そもそも
    マッチしない）。
  - 出力するのはパスの一覧までとし、ファイルの中身は読まない・出力しない
    （毎セッションのトークン消費を一定に保つため）。

使い方:
  python site/scripts/list-latest-reports.py
"""

import datetime
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORTS_DIR = os.path.join(ROOT, "reports")

# YYYY-MM-DD.md または YYYY-MM-DD-N.md（Nは2以上の整数）にのみマッチする。
# weekly-YYYY-WW.md・monthly-YYYY-MM.md・アンダースコア始まりのファイルはマッチしない。
REPORT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:-(\d+))?\.md$")


def collect_dates():
    """reports/配下の対象ファイルから {日付文字列: [(枝番, ファイル名), ...]} を返す。"""
    by_date = {}
    if not os.path.isdir(REPORTS_DIR):
        return by_date
    for name in os.listdir(REPORTS_DIR):
        match = REPORT_RE.match(name)
        if not match:
            continue
        date_str = match.group(1)
        n = int(match.group(2)) if match.group(2) else 1
        by_date.setdefault(date_str, []).append((n, name))
    return by_date


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    today = datetime.date.today().isoformat()
    by_date = collect_dates()

    if today in by_date:
        target_date = today
    else:
        past_dates = [d for d in by_date if d <= today]
        target_date = max(past_dates) if past_dates else None

    if target_date is None:
        print("REPORTS_NONE")
        sys.exit(0)

    print("REPORTS_LATEST: %s" % target_date)
    for n, name in sorted(by_date[target_date]):
        rel_path = "reports/%s" % name
        print(rel_path)
    sys.exit(0)


if __name__ == "__main__":
    main()
