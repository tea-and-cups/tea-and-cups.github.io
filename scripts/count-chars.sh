#!/bin/bash
# 記事の文字数を数える（frontmatter・アフィリエイト表記を除いた本文の文字数）
# strategy.md「記事ポリシー」の文字数目安（2,000〜3,500字）の確認用
# 使い方: count-chars.sh <記事ファイルパス> [<記事ファイルパス> ...]
#
# 注: Git Bash の wc -m はロケール依存で日本語を1文字=3バイトと数えてしまうため、
#     文字数のカウントは python 側で行う（D-0023で実測・修正）
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: count-chars.sh <article-path> [<article-path> ...]" >&2
  exit 1
fi

# Windows版pythonの標準出力は既定でcp932になり日本語が文字化けするため明示する
export PYTHONIOENCODING=utf-8

python - "$@" <<'PYEOF'
import io
import os
import re
import sys

for path in sys.argv[1:]:
    if not os.path.isfile(path):
        sys.stderr.write("not found: %s\n" % path)
        continue

    text = io.open(path, encoding="utf-8").read()

    # frontmatter（先頭の --- から2つ目の --- まで）を除去
    body = re.sub(r"\A---\r?\n.*?\r?\n---\r?\n", "", text, count=1, flags=re.S)

    # アフィリエイト表記の定型行を除去（記事本文の量として数えない）
    body = re.sub(r"^※当サイトはアフィリエイト広告.*$", "", body, flags=re.M)

    # 空白・改行を除いた実質的な文字数
    stripped = re.sub(r"\s", "", body)

    total_chars = len(text)
    body_chars = len(stripped)

    if body_chars < 2000:
        judge = "△ 目安2,000字を下回っています"
    elif body_chars > 3500:
        judge = "△ 目安3,500字を超えています（比較記事なら可）"
    else:
        judge = "○ 目安（2,000〜3,500字）の範囲内"

    print("%s" % os.path.basename(path))
    print("  全体: %d字 / 本文（frontmatter・空白除く）: %d字  %s" % (total_chars, body_chars, judge))
PYEOF
