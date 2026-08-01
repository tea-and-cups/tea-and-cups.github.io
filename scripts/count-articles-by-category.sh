#!/bin/bash
# site/src/content/posts/ 配下の公開済み・下書き記事をcategory別に集計する
# 使い方: count-articles-by-category.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
POSTS_DIR="$ROOT/site/src/content/posts"

grep -l "" "$POSTS_DIR"/*.md | xargs grep -h "^category:" | sort | uniq -c
