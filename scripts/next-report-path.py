# -*- coding: utf-8 -*-
r"""日次レポートのファイル名（枝番）を採番する（引数なし・読み取り専用・D-0108）。

背景: 日次レポートのファイル名をAIが自分で考えて決めると、既存ファイルの上書きや
番号飛びが起きうる。採番を本スクリプトに固定し、AIは出力されたパスにしか書かない
形にする。

動作:
  - 基準日はスクリプト実行時のローカル日付。
  - reports/ 配下から、基準日に一致する `YYYY-MM-DD.md` および
    `YYYY-MM-DD-N.md`（Nは2以上の整数）を走査する。
  - 1本も無ければ `reports/YYYY-MM-DD.md` を、既にあれば既存の最大N
    （枝番なしのファイルはN=1とみなす）に1を足した `reports/YYYY-MM-DD-N.md` を、
    ROOTからの相対パス1行だけで標準出力に出す。
  - weekly-*.md / monthly-*.md / アンダースコア始まりのファイルは対象外
    （ファイル名の日付部分の一致のみで判定するため、この命名規則上そもそも
    マッチしない）。

使い方:
  python site/scripts/next-report-path.py
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


def max_branch_for_date(today):
    """基準日に一致する既存レポートの最大枝番を返す。1本も無ければ0。
    枝番なしのファイルはN=1とみなす。
    """
    if not os.path.isdir(REPORTS_DIR):
        return 0
    max_n = 0
    for name in os.listdir(REPORTS_DIR):
        match = REPORT_RE.match(name)
        if not match:
            continue
        if match.group(1) != today:
            continue
        n = int(match.group(2)) if match.group(2) else 1
        max_n = max(max_n, n)
    return max_n


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    today = datetime.date.today().isoformat()
    max_n = max_branch_for_date(today)

    if max_n == 0:
        rel_path = "reports/%s.md" % today
    else:
        rel_path = "reports/%s-%d.md" % (today, max_n + 1)

    print(rel_path)
    sys.exit(0)


if __name__ == "__main__":
    main()
