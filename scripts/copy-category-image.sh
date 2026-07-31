#!/bin/bash
# ~/Downloads の画像を output/category-images/ へ配置する（テーマ一覧のカテゴリ画像の原本置き場）
# 使い方: copy-category-image.sh <Downloads内のファイル名> <カテゴリslug>
# 置いたあと python site/scripts/hero-to-webp.py --category <配置先パス> <カテゴリslug> でWebP化する
set -euo pipefail

if [ $# -ne 2 ]; then
  echo "usage: copy-category-image.sh <source-filename-in-downloads> <category-slug>" >&2
  exit 1
fi

SRC="$1"
SLUG="$2"
DEST_DIR="C:/Claude/Tea_TeaCut/output/category-images"

case "$SLUG" in
  *[!a-z0-9-]*)
    echo "カテゴリslugは英小文字・数字・ハイフンのみ: $SLUG" >&2
    exit 1
    ;;
esac

SRC_EXT="${SRC##*.}"
mkdir -p "$DEST_DIR"
cp "$HOME/Downloads/$SRC" "$DEST_DIR/$SLUG.$SRC_EXT"
ls -la "$DEST_DIR/$SLUG.$SRC_EXT"
