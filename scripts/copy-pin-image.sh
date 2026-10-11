#!/bin/bash
# ~/Downloads のPin画像を output/Pin-images/ へ配置する
# 使い方: copy-pin-image.sh <Downloads内のファイル名> <配置後のファイル名>
#
# ピン352以降は、右下に「琥珀時間」を合成したものを output/Pin-images/ に置き、
# 無加工の原本を output/Pin-images-original/ に同じ名前で残す（D-0274・GD-0036後半）。
# 合成に失敗した場合は output/Pin-images/ に何も置かずに終了コード1で終える
# （原本の控えは output/Pin-images-original/ に残る。どのスクリプトも読まないため残っても害はなく、
# 次に配置が成功したとき上書きされる）。ピン351以前は従来どおり無加工でコピーする。
set -euo pipefail

if [ $# -ne 2 ]; then
  echo "usage: copy-pin-image.sh <source-filename-in-downloads> <dest-filename>" >&2
  exit 1
fi

SRC="$1"
DEST="$2"
# 配置先は環境変数で差し替えられる（検証用。通常の運用では指定しない）
DEST_DIR="${PIN_IMAGE_DEST_DIR:-C:/Claude/Tea_TeaCut/output/Pin-images}"
ORIGINAL_DIR="${PIN_IMAGE_ORIGINAL_DIR:-C:/Claude/Tea_TeaCut/output/Pin-images-original}"

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

# 配置後のファイル名からピン番号を取る（新形式「ピン{番号} …」・旧形式「pin-{番号}-…」）
case "$DEST" in
  ピン[0-9]*) PIN_REST="${DEST#ピン}" ;;
  pin-[0-9]*) PIN_REST="${DEST#pin-}" ;;
  *) PIN_REST="" ;;
esac
PIN_NUM="${PIN_REST%%[!0-9]*}"

# 「琥珀時間」を合成する境界。check-pin-image-style.py の HEAD_QUESTION_FROM_PIN と同じ値にする
# （あちらはこの番号以降のPin画像に合成済みの目印が無いとNGにする）。
BRAND_STAMP_FROM_PIN=352
STAMP_SCRIPT="C:/Claude/Tea_TeaCut/site/scripts/hero-to-webp.py"

mkdir -p "$DEST_DIR"
if [ -n "$PIN_NUM" ] && [ "$((10#$PIN_NUM))" -ge "$BRAND_STAMP_FROM_PIN" ]; then
  mkdir -p "$ORIGINAL_DIR"
  cp "$HOME/Downloads/$SRC" "$ORIGINAL_DIR/$DEST"
  if ! python "$STAMP_SCRIPT" --stamp-pin "$HOME/Downloads/$SRC" "$DEST_DIR/$DEST"; then
    echo "配置を中止しました: 「琥珀時間」の合成に失敗したため output/Pin-images/ には置いていません。" >&2
    echo "  上のエラーを解消してから、あらためてこのスクリプトを実行してください。" >&2
    exit 1
  fi
  ls -la "$ORIGINAL_DIR/$DEST"
else
  cp "$HOME/Downloads/$SRC" "$DEST_DIR/$DEST"
fi
ls -la "$DEST_DIR/$DEST"
