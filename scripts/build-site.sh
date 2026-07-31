#!/usr/bin/env bash
# サイトをローカルでビルドする（astro build）。
#
# この環境には Node.js が単体でインストールされておらず、PATH に node / npm が無い。
# そのため PATH → 既知の同梱ランタイム の順に node を探し、astro を直接起動する。
# 使い方: bash "C:/Claude/Tea_TeaCut/site/scripts/build-site.sh"
set -eu

SITE_DIR="/c/Claude/Tea_TeaCut/site"

# ユーザープロファイル配下の絶対パスは直書きしない（siteリポジトリは公開されているため）。
# 環境変数から組み立てる。LOCALAPPDATA等はバックスラッシュ区切りで来るのでスラッシュへ直す。
local_app_dirs() {
  [ -n "${LOCALAPPDATA:-}" ] && echo "${LOCALAPPDATA//\\//}"
  [ -n "${HOME:-}" ] && echo "$HOME/AppData/Local"
  [ -n "${USERPROFILE:-}" ] && echo "${USERPROFILE//\\//}/AppData/Local"
  return 0
}

find_node() {
  if command -v node >/dev/null 2>&1; then
    command -v node
    return
  fi
  local base c
  # 同梱ランタイム（他アプリ付属）。恒久的な足場ではないため、Node.js導入までの暫定措置。
  for base in $(local_app_dirs); do
    for c in "$base"/OpenAI/Codex/runtimes/cua_node/*/bin/node.exe; do
      if [ -x "$c" ]; then
        echo "$c"
        return
      fi
    done
  done
  return 1
}

NODE="$(find_node)" || {
  echo "node が見つかりません。Node.js を導入するか、このスクリプトの探索先を追加してください。" >&2
  exit 1
}

echo "node: $NODE ($("$NODE" --version))"
cd "$SITE_DIR"
"$NODE" "$SITE_DIR/node_modules/astro/astro.js" build "$@"
