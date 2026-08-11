# -*- coding: utf-8 -*-
r"""SessionStartフックから呼ばれる呼び出し役スクリプト（D-0106）。

背景: CLAUDE.md 10節はセッション開始時に4本のスクリプト
（rotate-today-tasks.py / check-doc-governance.py / check-routine-due.py /
check-image-gen-needed-today.py）をAIが順に手動実行する運用だったが、
5節の起動フレーズ（「昨日までの実績を教えて」）と異なる言い回しでセッションが
始まった場合、AIがこの文章ルールを読み落として1本も実行しないことがあった。
本スクリプトはこの担保を文章ルールからSessionStartフック（ツール層）へ移し、
起動フレーズに依存せず必ず4本が実行される状態にする。

動作:
  - 下記4本を必ずこの順序で実行し、各スクリプトの標準出力をそのまま中継する
    （D-0102の順序規定を維持）。
      1. rotate-today-tasks.py
      2. check-doc-governance.py
      3. check-routine-due.py
      4. check-image-gen-needed-today.py
  - 各子スクリプトは cwd をプロジェクトルートに固定して起動する（D-0084と同型の予防）。
  - 子スクリプトが例外・非ゼロ終了・タイムアウト（1本30秒）した場合も無言で飛ばさず、
    「【エラー】<スクリプト名> が失敗しました（終了コード: N）」を出力し、残りの
    スクリプトは実行を続ける（silent failureを作らないため）。
  - 冒頭・末尾に固定文を印字する（AIの文脈に投入され、二重実行防止の指示として機能する）。

このスクリプト自体は既存4本のロジックを一切変更しない。呼び出し位置を移すのみ。

使い方:
  python site/scripts/session-start-check.py
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS_DIR = os.path.join(ROOT, "site", "scripts")

# 各子スクリプト名と「正常とみなす終了コードの集合」をセットで持つ。
# 子スクリプトが増えたときもここだけ見れば済むようにするための一覧。
# check-doc-governance.py のみ 0/1 の両方を正常とする: このスクリプトは
# 警告を検出した場合に終了コード1を返す仕様（0=検出なし/1=警告検出）であり、
# 1は異常終了ではなく「警告あり」を表す正常な状態のため（2026-08-11実測・D-0107）。
# 他の3本は非ゼロ終了コードを異常とみなす通常の仕様のため 0 のみを正常とする。
CHILD_SCRIPTS = [
    ("rotate-today-tasks.py", {0}),
    ("check-doc-governance.py", {0, 1}),
    ("check-routine-due.py", {0}),
    ("check-image-gen-needed-today.py", {0}),
]

TIMEOUT_SECONDS = 30

HEADER = (
    "=== セッション開始時チェック（SessionStartフック・自動実行） ===\n"
    "以下は自動実行された開始時チェックの結果です。CLAUDE.md 10節の4本はここで実行済みのため、"
    "AIが同じ4本を改めて手動実行しないでください（二重報告防止）。\n"
    "【警告】【エラー】ROUTINE_NONE以外の出力・NEEDED判定のいずれかが含まれる場合は、"
    "その内容を通常の作業に入る前に最初にオーナーへ報告してください。"
    "NEEDEDの場合の対応はCLAUDE.md 10節の記載に従ってください。"
)

FOOTER = "=== セッション開始時チェック ここまで ==="


def run_child(script_name, ok_codes):
    script_path = os.path.join(SCRIPTS_DIR, script_name)
    print("--- %s ---" % script_name)
    try:
        result = subprocess.run(
            [sys.executable, script_path],
            cwd=ROOT,
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        print("【エラー】%s が失敗しました（終了コード: タイムアウト %d秒）" % (script_name, TIMEOUT_SECONDS))
        return
    except Exception as e:
        print("【エラー】%s が失敗しました（終了コード: 例外 %s）" % (script_name, e))
        return

    stdout_text = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
    stderr_text = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""

    if stdout_text:
        print(stdout_text.rstrip("\n"))

    if result.returncode not in ok_codes:
        print("【エラー】%s が失敗しました（終了コード: %d）" % (script_name, result.returncode))
        if stderr_text:
            print(stderr_text.rstrip("\n"))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print(HEADER)
    print("")

    for script_name, ok_codes in CHILD_SCRIPTS:
        run_child(script_name, ok_codes)
        print("")

    print(FOOTER)
    sys.exit(0)


if __name__ == "__main__":
    main()
