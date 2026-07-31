#!/bin/bash
# ~/Downloads のPin画像を output/Pin-images/ へ配置する
# 使い方: copy-pin-image.sh <Downloads内のファイル名> <配置後のファイル名>
set -euo pipefail

if [ $# -ne 2 ]; then
  echo "usage: copy-pin-image.sh <source-filename-in-downloads> <dest-filename>" >&2
  exit 1
fi

SRC="$1"
DEST="$2"
DEST_DIR="C:/Claude/Tea_TeaCut/output/Pin-images"

# 保存先ファイル名が保存元と同じ拡張子で終わっていなければ自動で付け足す
# （呼び出し側が拡張子を付け忘れても拡張子なしファイルができないようにするため）
SRC_EXT="${SRC##*.}"
case "$DEST" in
  *.[Pp][Nn][Gg]|*.[Jj][Pp][Gg]|*.[Jj][Pp][Ee][Gg]|*.[Ww][Ee][Bb][Pp])
    ;;
  *)
    DEST="${DEST}.${SRC_EXT}"
    ;;
esac

mkdir -p "$DEST_DIR"
cp "$HOME/Downloads/$SRC" "$DEST_DIR/$DEST"
ls -la "$DEST_DIR/$DEST"
