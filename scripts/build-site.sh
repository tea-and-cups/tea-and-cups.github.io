#!/usr/bin/env bash
# サイトをローカルでビルドする（astro build）。
#
# 使い方: bash "C:/Claude/Tea_TeaCut/site/scripts/build-site.sh"
set -eu

SITE_DIR="/c/Claude/Tea_TeaCut/site"

if ! command -v node >/dev/null 2>&1; then
  echo "Node.jsが見つかりません。Claude Codeを再起動するか、Node.js LTSを導入してください。" >&2
  exit 1
fi

echo "node: $(command -v node) ($(node --version))"
cd "$SITE_DIR"
node "$SITE_DIR/node_modules/astro/astro.js" build "$@"
