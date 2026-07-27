#!/bin/bash
# 記事ページがデプロイされ200を返すまで待機する
# 使い方: wait-for-deploy.sh <slug>
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "usage: wait-for-deploy.sh <slug>" >&2
  exit 1
fi

SLUG="$1"
URL="https://tea-and-cups.github.io/posts/${SLUG}/"

until curl -s -o /dev/null -w "%{http_code}" "$URL" | grep -q 200; do
  sleep 15
done
echo "deployed"
