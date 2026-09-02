# -*- coding: utf-8 -*-
r"""GET /v5/boards で実ボード一覧を取得する（読み取り専用・D-0017）。

ボード名・board_id・ピン数を一覧表示する。bookmarkによるページングがあれば
全ページ取得する。ファイル化は行わない（親チャットで対応表を決めてから次
フェーズで行う）。

Pinterest APIへのリクエストは pinterest_api.py の単一入口経由で行う（D-0017）。

使い方:
  python site/scripts/pinterest-list-boards.py
"""

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
from env_loader import require_env  # noqa: E402
from pinterest_api import fetch_all_pages, PinterestApiError  # noqa: E402


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    access_token = require_env("PINTEREST_ACCESS_TOKEN")

    try:
        all_boards = fetch_all_pages("/boards", access_token)
    except PinterestApiError as e:
        print("エラー: GET /v5/boards がHTTP %d を返しました: %s" % (e.status_code, e.body))
        sys.exit(1)

    print("=== ボード一覧（全%d件） ===" % len(all_boards))
    print("%-30s %-20s %s" % ("ボード名", "board_id", "pin_count"))
    for b in all_boards:
        name = b.get("name", "")
        board_id = b.get("id", "")
        pin_count = b.get("pin_count", "")
        print("%-30s %-20s %s" % (name, board_id, pin_count))


if __name__ == "__main__":
    main()
