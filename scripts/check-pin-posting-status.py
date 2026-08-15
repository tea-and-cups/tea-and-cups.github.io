# -*- coding: utf-8 -*-
r"""output/pins/ のファイル名から作成済みPin番号を抽出し、data/pin-posted.md の
投稿済み台帳と突き合わせて未投稿のPinを検知する（読み取り専用・D-0111）。

背景: docs/status.md の「Pin未着手の公開済み記事」欄は更新責任者・更新契機の規定が
なく、実態と乖離しても検知できなかった。調査の結果、Pinファイル名中のslug断片は
記事slugと不一致が多く、Pinファイル内の「ステータス」欄・残タスクチェックボックスも
相互に同期していないことが確認された。信頼できるのはファイル名から機械抽出できる
Pin番号のみであるため、本スクリプトは番号の差分のみで判定する。

抽出規則:
  ファイル名中の `pin-` の直後に続く半角数字を開始番号とする。
  その直後が `-` + 半角数字 の形で続き、かつその数字の直後が `-` または `.md`
  （文字列末尾）で区切られており、かつ後者の数字が前者より大きい場合のみ、
  開始番号から後者までの連番（inclusive）を1ファイルの担当範囲とみなす。
  それ以外（数字がスラッグの一部に紛れ込んでいる場合等）は開始番号1件のみとする。
  例: pin-78-80-twg-tea-gift.md -> 78,79,80（範囲）
      pin-02-4chaba-hikaku.md -> 2のみ（"4chaba"は数字が区切られていないため対象外）
      pin-54-5000en-ika-...md -> 54のみ（"5000en"も同様）

台帳の書式（data/pin-posted.md）:
  「投稿済み:」で始まる行に、半角数字の番号または範囲（N-M）をカンマ区切りで書く。
  それ以外の行はすべて無視する。

自己検査:
  作成済み番号の集合が 1 から最大値までの連番になっているかを確認する。
  欠番・重複があれば【警告】として出力する（抽出ロジックが壊れた場合に沈黙させないため）。

出力:
  - 未投稿0件・自己検査も正常: "PIN_POSTING_OK （作成済みN件・すべて投稿済み）" の1行のみ。
  - 未投稿がある場合: "PIN_UNPOSTED: " に続けて未投稿番号を昇順で列挙し、
    番号ごとに該当ファイル名を1行ずつ添える。
  - 台帳にあるが作成済み一覧に存在しない番号があれば【警告】として列挙する。

終了コード: 異常終了（台帳ファイル不在等）のみ非ゼロ。それ以外は常に0。

使い方:
  python site/scripts/check-pin-posting-status.py
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PINS_DIR = os.path.join(ROOT, "output", "pins")
LEDGER_PATH = os.path.join(ROOT, "data", "pin-posted.md")

PIN_NUM_RE = re.compile(r"pin-(\d+)(?:-(\d+)(?=-|\.md$))?")
LEDGER_LINE_RE = re.compile(r"^投稿済み:\s*(.*)$")
RANGE_RE = re.compile(r"^(\d+)-(\d+)$")
SINGLE_RE = re.compile(r"^(\d+)$")


# 範囲表記（pin-78-80-...）とみなす2数字の許容差の上限。1ファイルが担当する
# 実際のPin数（数個程度）を大きく超える差は、slugが数字始まり（例:
# 2026-natsu-...）であることによる誤検出とみなして単一番号扱いにする
# （2026-08-15発見・D-0124。pin-120-2026-natsu-...という記事slugでこの誤検出が発生した）。
RANGE_MAX_SPAN = 20


def extract_created_pins():
    """{pin番号: [該当ファイル名, ...]} を返す"""
    nums_map = {}
    if not os.path.isdir(PINS_DIR):
        return nums_map
    for fname in sorted(os.listdir(PINS_DIR)):
        if not fname.endswith(".md"):
            continue
        m = PIN_NUM_RE.search(fname)
        if not m:
            continue
        start = int(m.group(1))
        end = start
        if m.group(2):
            second = int(m.group(2))
            if second > start and (second - start) <= RANGE_MAX_SPAN:
                end = second
        for n in range(start, end + 1):
            nums_map.setdefault(n, []).append(fname)
    return nums_map


def load_ledger():
    """data/pin-posted.md から投稿済み番号の集合を返す。ファイル不在時は None"""
    if not os.path.isfile(LEDGER_PATH):
        return None
    with open(LEDGER_PATH, encoding="utf-8") as f:
        text = f.read()

    posted = set()
    for line in text.splitlines():
        m = LEDGER_LINE_RE.match(line.strip())
        if not m:
            continue
        body = m.group(1)
        for token in body.split(","):
            token = token.strip()
            if not token:
                continue
            rm = RANGE_RE.match(token)
            if rm:
                lo, hi = int(rm.group(1)), int(rm.group(2))
                if lo <= hi:
                    for n in range(lo, hi + 1):
                        posted.add(n)
                continue
            sm = SINGLE_RE.match(token)
            if sm:
                posted.add(int(sm.group(1)))
    return posted


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    posted = load_ledger()
    if posted is None:
        print("【エラー】data/pin-posted.md が見つかりません")
        sys.exit(1)

    nums_map = extract_created_pins()
    created = sorted(nums_map.keys())

    warnings = []

    # 自己検査: 1〜最大値の連番になっているか
    if created:
        max_num = created[-1]
        expected = set(range(1, max_num + 1))
        actual_set = set(created)
        missing = sorted(expected - actual_set)
        if missing:
            warnings.append(
                "【警告】作成済みPin番号に欠番があります: " + ", ".join(str(n) for n in missing)
            )
        dup_nums = sorted(n for n, files in nums_map.items() if len(files) > 1)
        if dup_nums:
            for n in dup_nums:
                warnings.append(
                    "【警告】Pin番号 %d が複数ファイルに重複しています: %s"
                    % (n, ", ".join(nums_map[n]))
                )

    # 台帳にあるが作成済み一覧に存在しない番号
    ghost = sorted(posted - set(created))
    if ghost:
        warnings.append(
            "【警告】data/pin-posted.mdに記載があるが作成済み一覧に存在しない番号: "
            + ", ".join(str(n) for n in ghost)
        )

    unposted = sorted(set(created) - posted)

    for w in warnings:
        print(w)

    if not unposted and not warnings:
        print("PIN_POSTING_OK （作成済み%d件・すべて投稿済み）" % len(created))
        sys.exit(0)

    if unposted:
        print("PIN_UNPOSTED: " + ", ".join(str(n) for n in unposted))
        for n in unposted:
            for fname in nums_map[n]:
                print("  pin-%d: %s" % (n, fname))
    else:
        print("PIN_POSTING_OK （作成済み%d件・すべて投稿済み）" % len(created))

    sys.exit(0)


if __name__ == "__main__":
    main()
