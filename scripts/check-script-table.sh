#!/bin/bash
# CLAUDE.md 11節の補助スクリプト一覧表と、site/scripts/ の実ファイルを突き合わせる。
# 表にあるのに実在しない行・実在するのに表に無いスクリプトを検出する（CLAUDE.md 11-3の比較処理）。
# 使い方: check-script-table.sh
set -uo pipefail

CLAUDE_MD="C:/Claude/Tea_TeaCut/CLAUDE.md"
SCRIPTS_DIR="C:/Claude/Tea_TeaCut/site/scripts"

TMP_TABLE="$(mktemp)"
TMP_FILES="$(mktemp)"
trap 'rm -f "$TMP_TABLE" "$TMP_FILES"' EXIT

# 表の1列目（| xxx.sh | ... | の xxx.sh）だけを取り出す
grep -o '^| [A-Za-z0-9._-]\+\.\(sh\|py\|ps1\) ' "$CLAUDE_MD" \
  | sed 's/^| //; s/ $//' | sort -u > "$TMP_TABLE"

ls "$SCRIPTS_DIR" | grep -E '\.(sh|py|ps1)$' | sort -u > "$TMP_FILES"

MISSING=$(comm -23 "$TMP_TABLE" "$TMP_FILES")   # 表にあるが実在しない
UNLISTED=$(comm -13 "$TMP_TABLE" "$TMP_FILES")  # 実在するが表に無い

echo "表の記載: $(wc -l < "$TMP_TABLE")件 / 実ファイル: $(wc -l < "$TMP_FILES")件"
echo "---"

NG=0
if [ -n "$MISSING" ]; then
  echo "表にあるのに実在しない（行を削除する）:"
  echo "$MISSING" | sed 's/^/  /'
  NG=1
fi
if [ -n "$UNLISTED" ]; then
  echo "実在するのに表に無い（行を追記する）:"
  echo "$UNLISTED" | sed 's/^/  /'
  NG=1
fi

if [ "$NG" -eq 0 ]; then
  echo "一致（過不足なし）"
else
  exit 2
fi
