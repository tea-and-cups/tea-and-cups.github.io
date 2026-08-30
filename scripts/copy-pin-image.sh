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

# 配置する前にコピー元の寸法を検査する（D-0174）
# 判定ロジック・閾値はこのファイルに書き写さず、check-pin-image-dimensions.py を正本とする。
# コピーしてから消す方式は取らない（中途半端なファイルを output/Pin-images/ に残さないため。
# 残るとファイル名規則チェックや今後のPin投稿を巻き込む）。
CHECK_SCRIPT="C:/Claude/Tea_TeaCut/site/scripts/check-pin-image-dimensions.py"
if ! python "$CHECK_SCRIPT" "$HOME/Downloads/$SRC"; then
  echo "配置を中止しました: 寸法チェックに失敗したためコピーしていません。" >&2
  echo "  この画像は作り直しが必要です。ChatGPTへ縦長（高さが幅の1.4倍以上）での" >&2
  echo "  生成し直しを依頼してから、あらためてこのスクリプトを実行してください。" >&2
  exit 1
fi

mkdir -p "$DEST_DIR"
cp "$HOME/Downloads/$SRC" "$DEST_DIR/$DEST"
ls -la "$DEST_DIR/$DEST"
