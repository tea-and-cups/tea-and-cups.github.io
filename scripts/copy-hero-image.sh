#!/bin/bash
# ~/Downloads の画像を output/hero-images/ へ配置する
# 使い方: copy-hero-image.sh <Downloads内のファイル名> <配置後のファイル名>
set -euo pipefail

if [ $# -ne 2 ]; then
  echo "usage: copy-hero-image.sh <source-filename-in-downloads> <dest-filename>" >&2
  exit 1
fi

SRC="$1"
DEST="$2"
DEST_DIR="C:/Claude/Tea_TeaCut/output/hero-images"

mkdir -p "$DEST_DIR"
cp "$HOME/Downloads/$SRC" "$DEST_DIR/$DEST"
ls -la "$DEST_DIR/$DEST"
