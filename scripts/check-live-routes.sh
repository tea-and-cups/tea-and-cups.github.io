#!/bin/bash
# 公開中サイトの主要URLがすべて200を返すか確認する（記事URLは全記事を自動列挙）。
# 使い方: check-live-routes.sh [追加で確認したいパス ...]
#   例: bash "C:/Claude/Tea_TeaCut/site/scripts/check-live-routes.sh" /2/
set -uo pipefail

BASE="https://tea-and-cups.github.io"
POSTS_DIR="C:/Claude/Tea_TeaCut/site/src/content/posts"

PATHS=("/" "/category/" "/about/" "/privacy-policy/" "/sitemap-index.xml")
for SLUG in $(grep -h '^slug:' "$POSTS_DIR"/*.md | sed 's/^slug:[[:space:]]*//'); do
  PATHS+=("/posts/$SLUG/")
done
for C in how-to tea-leaves teaware gift; do
  PATHS+=("/category/$C/")
done
PATHS+=("$@")

NG=0
for P in "${PATHS[@]}"; do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' "$BASE$P")
  if [ "$CODE" = "200" ]; then
    printf 'OK   %s  %s\n' "$CODE" "$P"
  else
    printf 'NG   %s  %s\n' "$CODE" "$P"
    NG=$((NG + 1))
  fi
done

echo "---"
if [ "$NG" -eq 0 ]; then
  echo "すべて200（${#PATHS[@]}件）"
else
  echo "200以外が ${NG}件あります"
  exit 2
fi
