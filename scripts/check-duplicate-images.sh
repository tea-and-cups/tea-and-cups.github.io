#!/bin/bash
# 画像ファイルの重複（内容が同一かどうか）を判定する
# ChatGPTからのダウンロードで同じ画像を二重取得していないかの確認用
# 使い方: check-duplicate-images.sh <画像パス> <画像パス> [<画像パス> ...]
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "usage: check-duplicate-images.sh <image-path> <image-path> [<image-path> ...]" >&2
  exit 1
fi

TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT

for FILE in "$@"; do
  if [ ! -f "$FILE" ]; then
    echo "not found: $FILE" >&2
    continue
  fi
  HASH=$(md5sum "$FILE" | awk '{print $1}')
  SIZE=$(wc -c < "$FILE" | tr -d ' ')
  printf '%s\t%s\t%s\n' "$HASH" "$SIZE" "$FILE" >> "$TMP"
  echo "$HASH  ${SIZE}bytes  $(basename "$FILE")"
done

echo "---"

DUP=$(cut -f1 "$TMP" | sort | uniq -d)
if [ -z "$DUP" ]; then
  echo "重複なし（すべて異なる画像です）"
else
  echo "重複あり:"
  for HASH in $DUP; do
    echo "  同一内容のファイル群 (md5: $HASH)"
    awk -F'\t' -v h="$HASH" '$1==h {print "    " $3}' "$TMP"
  done
  exit 2
fi
