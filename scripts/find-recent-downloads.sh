#!/bin/bash
# Downloads 内の最近の生成画像を新しい順に表示する（hero画像・Pin画像の取り込み元確認用）
# 日時はハードコードせず「今から何分以内か」の相対時間で指定する
# 使い方: find-recent-downloads.sh [分数] [名前フィルタ]
#   例: find-recent-downloads.sh              → 直近60分の画像すべて
#       find-recent-downloads.sh 15           → 直近15分の画像
#       find-recent-downloads.sh 120 ChatGPT  → 直近120分の「ChatGPT」を含む画像
set -euo pipefail

MINUTES="${1:-60}"
FILTER="${2:-}"

case "$MINUTES" in
  ''|*[!0-9]*)
    echo "usage: find-recent-downloads.sh [minutes] [name-filter]" >&2
    exit 1
    ;;
esac

DIR="$HOME/Downloads"

if [ -n "$FILTER" ]; then
  NAME_PATTERN="*${FILTER}*"
else
  NAME_PATTERN="*"
fi

FOUND=$(find "$DIR" -maxdepth 1 -type f -mmin "-${MINUTES}" -iname "$NAME_PATTERN" \
  \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.webp' \) \
  -printf '%T@\t%TY-%Tm-%Td %TH:%TM\t%s\t%p\n' 2>/dev/null | sort -rn || true)

if [ -z "$FOUND" ]; then
  echo "直近${MINUTES}分以内に該当する画像はありません（$DIR）"
  exit 0
fi

echo "直近${MINUTES}分以内の画像（新しい順）:"
echo "$FOUND" | while IFS=$'\t' read -r _epoch mtime size path; do
  printf '  %s  %8sKB  %s\n' "$mtime" "$((size / 1024))" "$(basename "$path")"
done
