#!/bin/bash
# usage: diff-draft-published.sh <slug> [lines]
set -euo pipefail

SLUG="${1:?usage: diff-draft-published.sh <slug> [lines]}"
LINES="${2:-12}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DRAFT="$ROOT/output/articles/$SLUG.md"
PUBLISHED="$ROOT/site/src/content/posts/$SLUG.md"

for f in "$DRAFT" "$PUBLISHED"; do
  if [ ! -f "$f" ]; then
    echo "file not found: $f" >&2
    exit 1
  fi
done

TMP_DRAFT="$(mktemp)"
TMP_PUBLISHED="$(mktemp)"
trap 'rm -f "$TMP_DRAFT" "$TMP_PUBLISHED"' EXIT

head -n "$LINES" "$DRAFT" > "$TMP_DRAFT"
head -n "$LINES" "$PUBLISHED" > "$TMP_PUBLISHED"

if diff -u "$TMP_DRAFT" "$TMP_PUBLISHED"; then
  echo "差分なし（frontmatter先頭${LINES}行が一致）"
fi
