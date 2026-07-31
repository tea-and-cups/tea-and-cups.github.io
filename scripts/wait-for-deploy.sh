#!/bin/bash
# 記事ページがデプロイされ200を返すまで待機する
#
# 使い方: wait-for-deploy.sh <slug>
#   引数は記事のslugのみ（例: zansho-mimai-koucha-gift）。
#   URLはこのスクリプト内部で https://tea-and-cups.github.io/posts/<slug>/ として
#   組み立てるため、URL全体を渡すと二重URLになり200が返らず無限に待ち続ける。
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "usage: wait-for-deploy.sh <slug>" >&2
  exit 1
fi

case "$1" in
  http://*|https://*)
    echo "エラー: slugを渡してください。URLではありません（例: wait-for-deploy.sh zansho-mimai-koucha-gift）" >&2
    exit 1
    ;;
esac

SLUG="$1"
URL="https://tea-and-cups.github.io/posts/${SLUG}/"

until curl -s -o /dev/null -w "%{http_code}" "$URL" | grep -q 200; do
  sleep 15
done
echo "deployed"
