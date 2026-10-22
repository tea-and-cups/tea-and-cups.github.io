# -*- coding: utf-8 -*-
r"""ピンの審査行（quality-reviewer の公開可）の判定を1か所にまとめた内部ライブラリ。

単体では実行しない。post-pins-to-pinterest.py・post-pins-to-buffer.py・
check-pin-posting-status.py・check-buffer-posting-status.py・
.claude/hooks/check-pin-board.py がimportして使う（正規表現を各所へ写さないため）。

規則:
  - REVIEW_START_PIN 未満のピンは審査行の有無を問わず審査済みとみなす
    （363以前は全件投稿済みのため対象外）。
  - REVIEW_START_PIN 以上のピンは、ピンmdに行頭「- 審査: 公開可 YYYY-MM-DD」の行が
    あるときだけ審査済みとする。「要修正」「公開不可」などは審査済みにしない。
  - 審査行は、quality-reviewer がそのピン番号に公開可を返した直後に本体AIが Edit で足す
    （rules/pinterest-api.md）。「- [ ] quality-reviewer依頼」のチェックボックス行は判定に使わない。
"""

import os
import re

REVIEW_START_PIN = 364

REVIEW_LINE_RE = re.compile(r"^-\s*審査:\s*公開可\s+\d{4}-\d{2}-\d{2}(?!\d)", re.M)


def is_reviewed(pin_no, md_text):
    """ピン番号 pin_no のmd本文 md_text が投稿してよい状態（審査済み）なら True。"""
    if pin_no < REVIEW_START_PIN:
        return True
    return bool(REVIEW_LINE_RE.search(md_text or ""))


def is_reviewed_file(pin_no, path):
    """ピンmdのパスから is_reviewed() を判定する。読めなければ未審査（False）とする。"""
    if pin_no < REVIEW_START_PIN:
        return True
    try:
        with open(path, encoding="utf-8") as f:
            return is_reviewed(pin_no, f.read())
    except OSError:
        return False


def held_unreviewed(created_map, pins_dir):
    """{ピン番号: [ファイル名, ...]}（extract_created_pins() の戻り値）のうち、
    未審査で保留するピン番号の集合を返す。同じ番号のファイルが複数ある場合は、
    投稿スクリプトが代表に使う1件目で判定する。"""
    held = set()
    for pin_no, files in created_map.items():
        if pin_no < REVIEW_START_PIN or not files:
            continue
        if not is_reviewed_file(pin_no, os.path.join(pins_dir, files[0])):
            held.add(pin_no)
    return held


# 状態チェックが未審査の保留を出したとき、続けて出す「次に何をするか」の1行。
HELD_NEXT_ACTION = "quality-reviewer にかけ、公開可ならピンmdへ審査行を足してから %s を実行する"


def held_line(prefix, nums):
    """「<prefix>: 364, 365」形式の1行を返す。"""
    return "%s: %s" % (prefix, ", ".join(str(n) for n in sorted(nums)))
