# -*- coding: utf-8 -*-
r"""ボード名が data/pinterest-boards.md の「選定可」ボードと一致するか判定する（T4）。

CLIから単体実行できる判定ロジック本体。.claude/hooks/check-pin-board.py（PreToolUse
フック用の薄いラッパ）から呼ばれる想定だが、判定ロジックはこちら側に置く（フックを
介さずコマンドラインから単体検証できるようにするため・D-0104と同じ2段構成）。

使い方:
  python site/scripts/check-pin-board-name.py "<ボード名>"
  python site/scripts/check-pin-board-name.py "<ボード名>" --boards-file <パス>

終了コード:
  0: OK（「選定可」のボード名と完全一致）
  1: NG（不一致・正本ファイルが存在しない/空/表が読めない、いずれも含む＝fail-closed）

標準出力: 先頭行に "OK" または "NG"（後続にあれば理由）。
"""

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
DEFAULT_BOARDS_FILE = os.path.join(PROJECT_ROOT, "data", "pinterest-boards.md")


def load_selectable_board_names(boards_file):
    """正本ファイルを読み、「状態=選定可」のボード名の集合を返す。

    読めない・表が無い等はいずれも空集合を返す（呼び出し側でNG判定させる＝fail-closed）。
    """
    if not os.path.isfile(boards_file):
        return None  # ファイル不在
    try:
        with open(boards_file, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return None

    if not content.strip():
        return None  # 空ファイル

    names = set()
    found_table = False
    for line in content.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        # ヘッダ行・区切り行をスキップ
        if cells[0] in ("ボード名",) or set(cells[0]) <= {"-"}:
            continue
        found_table = True
        name, status = cells[0], cells[3]
        if status == "選定可":
            names.add(name)

    if not found_table:
        return None  # 表が読めない
    return names


def check(board_name, boards_file=None):
    boards_file = boards_file or DEFAULT_BOARDS_FILE
    names = load_selectable_board_names(boards_file)
    if names is None:
        return False, "正本ファイルが存在しない・空・表が読めません（%s）" % boards_file
    if board_name in names:
        return True, None
    return False, "「%s」は「選定可」のボード名と一致しません" % board_name


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = sys.argv[1:]
    if not args:
        print("NG: ボード名を引数で指定してください")
        sys.exit(1)

    board_name = args[0]
    boards_file = None
    if "--boards-file" in args:
        idx = args.index("--boards-file")
        if idx + 1 >= len(args):
            print("NG: --boards-file の後にパスを指定してください")
            sys.exit(1)
        boards_file = args[idx + 1]

    ok, reason = check(board_name, boards_file)
    if ok:
        print("OK")
        sys.exit(0)
    else:
        print("NG: %s" % reason)
        sys.exit(1)


if __name__ == "__main__":
    main()
