# -*- coding: utf-8 -*-
r"""GET /v5/boards で実ボード一覧を取得する（読み取り専用・T5）。

ボード名・board_id・ピン数を一覧表示する。bookmarkによるページングがあれば
全ページ取得する。ファイル化は行わない（親チャットで対応表を決めてから次
フェーズで行う）。

使い方:
  python site/scripts/pinterest-list-boards.py
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
from env_loader import require_env  # noqa: E402

BOARDS_URL = "https://api.pinterest.com/v5/boards"
TIMEOUT_SECONDS = 15


def fetch_page(access_token, bookmark=None):
    url = BOARDS_URL + "?page_size=100"
    if bookmark:
        url += "&bookmark=" + urllib.parse.quote(bookmark)
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", "Bearer %s" % access_token)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print("エラー: GET /v5/boards がHTTP %d を返しました: %s" % (e.code, body))
        sys.exit(1)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    access_token = require_env("PINTEREST_ACCESS_TOKEN")

    all_boards = []
    bookmark = None
    page = 0
    while True:
        page += 1
        data = fetch_page(access_token, bookmark)
        items = data.get("items", [])
        all_boards.extend(items)
        bookmark = data.get("bookmark")
        print("[page %d] %d件取得（累計 %d件）" % (page, len(items), len(all_boards)), file=sys.stderr)
        if not bookmark:
            break

    print("=== ボード一覧（全%d件） ===" % len(all_boards))
    print("%-30s %-20s %s" % ("ボード名", "board_id", "pin_count"))
    for b in all_boards:
        name = b.get("name", "")
        board_id = b.get("id", "")
        pin_count = b.get("pin_count", "")
        print("%-30s %-20s %s" % (name, board_id, pin_count))


if __name__ == "__main__":
    main()
