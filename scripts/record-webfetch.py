# -*- coding: utf-8 -*-
"""WebFetch で実際に取得できたURLを data/webfetch-log.md へ記録する（D-0133）。

PostToolUse フック（matcher: WebFetch）から標準入力でフック入力JSONを受け取る。
記事の出典URLが「実際にWebFetchした記録」に存在するかを
check-source-fetched.py が照合できるようにするための台帳を作るのが目的。

【記録するもの / しないもの】
  tool_response.code が 2xx のときだけ記録する。404等の失敗は記録しない。
  （PostToolUse は取得後に発火し、HTTPステータスを受け取れることを実測済み。
    reports/2026-08-15-16.md 参照）

【1行の書式】
  - YYYY-MM-DD | <URL> | <session_id>
  同じ日・同じURLの行は重複させない（1日1URL1行）。

【固定上限】
  直近 RETAIN_DAYS 日分のみを保持し、それより古い行は追記時に削除する。
  記事数・セッション数に比例して増えない。

【ヘッダの記録開始日】
  台帳を最初に作った日を「記録開始日」としてヘッダに書き、以後書き換えない。
  check-source-fetched.py はこの日より前に公開された記事を照合対象から外す。

【何があっても終了コード0】
  記録の失敗が WebFetch 自体を止めてはならないため、例外は握りつぶす。
"""

import json
import os
import re
import sys
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG_PATH = os.path.join(ROOT, "data", "webfetch-log.md")

RETAIN_DAYS = 14

RE_ENTRY = re.compile(r"^- (\d{4}-\d{2}-\d{2}) \| (\S+) \| (\S*)\s*$")

HEADER_TEMPLATE = """# WebFetch記録台帳（自動生成・site/scripts/record-webfetch.py）

記録開始日: %s
保持期間: 直近{retain}日分（これより古い行は追記時に自動削除される）
記録対象: WebFetchが成功（HTTPステータス2xx）した取得のみ。失敗した取得は記録しない。
書式: `- 日付 | URL | session_id`（同じ日の同じURLは1行にまとめる）

このファイルは手で編集しない。記録開始日の行は書き換えない
（check-source-fetched.py がこの日付を基準に照合対象を絞るため）。

""".replace("{retain}", str(RETAIN_DAYS))


def read_input():
    """フック入力JSONを読む。sys.stdin.read() は空文字を返すことがあるためバイトで読む。"""
    raw = sys.stdin.buffer.read()
    return json.loads(raw.decode("utf-8", "replace"))


def is_success(payload):
    response = payload.get("tool_response")
    if not isinstance(response, dict):
        return False
    code = response.get("code")
    return isinstance(code, int) and 200 <= code < 300


def ensure_header(today_str):
    """台帳が無ければ、今日を記録開始日としてヘッダだけ作る。"""
    if os.path.isfile(LOG_PATH):
        return
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(HEADER_TEMPLATE % today_str)


def prune_if_needed(cutoff_str):
    """cutoff より古い行があれば、その行だけを落として書き直す。

    古い行が1つも無い通常時はファイルを書き換えない（追記だけで済ませる）。
    """
    with open(LOG_PATH, encoding="utf-8") as f:
        lines = f.read().splitlines()

    kept = []
    dropped = False
    for line in lines:
        m = RE_ENTRY.match(line)
        if m and m.group(1) < cutoff_str:
            dropped = True
            continue
        kept.append(line)

    if not dropped:
        return

    tmp = LOG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(kept).rstrip("\n") + "\n")
    os.replace(tmp, LOG_PATH)


def already_recorded(today_str, url):
    with open(LOG_PATH, encoding="utf-8") as f:
        for line in f:
            m = RE_ENTRY.match(line)
            if m and m.group(1) == today_str and m.group(2) == url:
                return True
    return False


def append_entry(today_str, url, session_id):
    with open(LOG_PATH, "a", encoding="utf-8", newline="\n") as f:
        f.write("- %s | %s | %s\n" % (today_str, url, session_id))


def run():
    payload = read_input()
    if payload.get("tool_name") != "WebFetch":
        return
    if not is_success(payload):
        return

    url = (payload.get("tool_input") or {}).get("url")
    if not url or "|" in url or "\n" in url:
        return
    session_id = payload.get("session_id") or "-"

    today = date.today()
    today_str = today.isoformat()
    cutoff_str = (today - timedelta(days=RETAIN_DAYS - 1)).isoformat()

    ensure_header(today_str)
    prune_if_needed(cutoff_str)
    if not already_recorded(today_str, url):
        append_entry(today_str, url, session_id)


def main():
    try:
        run()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
