#!/bin/bash
# 公開サイト（GitHub Pages）の疎通確認。デプロイ待機と全URL点検を1本で行う。
#
# 使い方:
#   wait-for-deploy.sh <slug>
#       記事ページ /posts/<slug>/ が200を返すまで待機する（従来どおりの使い方）。
#       引数は記事のslugのみ（例: zansho-mimai-koucha-gift）。URL全体を渡すと
#       二重URLになり200が返らないため、エラーで弾く。
#
#   wait-for-deploy.sh --path <パス>
#       任意のパスが200を返すまで待機する（例: --path /2/）。
#       記事以外を追加・変更したとき（ページ送り・カテゴリ等）はこちらを使う。
#
#   wait-for-deploy.sh --routes [追加パス ...]
#       待機せず、主要URL（トップ・カテゴリ・全記事・sitemap＋引数の追加パス）が
#       200を返すか一括で確認する。1件でも200以外なら終了コード2。
#
#   wait-for-deploy.sh --file <ローカルファイルパス> <公開URLパス>
#       画像等、既存パスへの上書き更新（差し替え）を確認する専用モード。
#       公開URL側のファイルが、指定したローカルファイルとバイト数一致するまで待機する。
#       例: wait-for-deploy.sh --file site/public/images/foo/hero.webp /images/foo/hero.webp
#       （<slug>やhttp code 200のチェックでは、上書き前の古いファイルでも200を返すため
#         差し替えの完了を判定できない。中身の一致を見るのはこのモードのみ）
#
# 注意: 既に存在していたURLは「デプロイ前でも200」を返す。構成を変えたときは
#       まず新しく増えたパスを --path で待ってから --routes を実行すること。
#       同じ理由で、既存ファイルの中身だけを差し替えたとき（hero画像の再生成等）も
#       <slug>やHTTP 200チェックでは検知できないため --file を使うこと。
set -uo pipefail

BASE="https://tea-and-cups.github.io"
POSTS_DIR="C:/Claude/Tea_TeaCut/site/src/content/posts"
MAX_WAIT_SEC=900   # 待機モードの上限（15分）。超えたら異常としてエラー終了する
INTERVAL_SEC=15

status_of() {
  curl -s -o /dev/null -w '%{http_code}' "$BASE$1"
}

wait_for() {
  local PATH_="$1"
  local WAITED=0
  while [ "$(status_of "$PATH_")" != "200" ]; do
    if [ "$WAITED" -ge "$MAX_WAIT_SEC" ]; then
      echo "タイムアウト: ${MAX_WAIT_SEC}秒待っても200になりません（$BASE$PATH_）" >&2
      exit 1
    fi
    sleep "$INTERVAL_SEC"
    WAITED=$((WAITED + INTERVAL_SEC))
  done
  echo "deployed"
}

remote_size_of() {
  curl -s -o /dev/null -w '%{size_download}' "$BASE$1?t=$(date +%s)"
}

wait_for_file() {
  local LOCAL_PATH="$1"
  local PATH_="$2"

  if [ ! -f "$LOCAL_PATH" ]; then
    echo "エラー: ローカルファイルが見つかりません（$LOCAL_PATH）" >&2
    exit 1
  fi

  local LOCAL_SIZE
  LOCAL_SIZE=$(wc -c < "$LOCAL_PATH" | tr -d ' ')

  local WAITED=0
  while [ "$(remote_size_of "$PATH_")" != "$LOCAL_SIZE" ]; do
    if [ "$WAITED" -ge "$MAX_WAIT_SEC" ]; then
      echo "タイムアウト: ${MAX_WAIT_SEC}秒待っても公開URL側のバイト数がローカル（${LOCAL_SIZE}バイト）と一致しません（$BASE$PATH_）" >&2
      exit 1
    fi
    sleep "$INTERVAL_SEC"
    WAITED=$((WAITED + INTERVAL_SEC))
  done
  echo "deployed（${LOCAL_SIZE}バイトで一致）"
}

check_routes() {
  local PATHS=("/" "/category/" "/about/" "/privacy-policy/" "/sitemap-index.xml")
  local SLUG
  for SLUG in $(grep -h '^slug:' "$POSTS_DIR"/*.md | sed 's/^slug:[[:space:]]*//'); do
    PATHS+=("/posts/$SLUG/")
  done
  local C
  for C in how-to tea-leaves teaware gift; do
    PATHS+=("/category/$C/")
  done
  PATHS+=("$@")

  local NG=0 P CODE
  for P in "${PATHS[@]}"; do
    CODE=$(status_of "$P")
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
}

if [ $# -lt 1 ]; then
  echo "usage: wait-for-deploy.sh <slug> | --path <パス> | --routes [追加パス ...] | --file <ローカルパス> <公開URLパス>" >&2
  exit 1
fi

case "$1" in
  --routes)
    shift
    check_routes "$@"
    ;;
  --path)
    if [ $# -ne 2 ]; then
      echo "usage: wait-for-deploy.sh --path <パス>" >&2
      exit 1
    fi
    wait_for "$2"
    ;;
  --file)
    if [ $# -ne 3 ]; then
      echo "usage: wait-for-deploy.sh --file <ローカルファイルパス> <公開URLパス>" >&2
      exit 1
    fi
    wait_for_file "$2" "$3"
    ;;
  http://*|https://*)
    echo "エラー: slugを渡してください。URLではありません（例: wait-for-deploy.sh zansho-mimai-koucha-gift）" >&2
    exit 1
    ;;
  *)
    if [ $# -ne 1 ]; then
      echo "usage: wait-for-deploy.sh <slug>" >&2
      exit 1
    fi
    wait_for "/posts/$1/"
    ;;
esac
