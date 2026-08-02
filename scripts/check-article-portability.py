"""記事の可搬性規約（CLAUDE.md 9-2 / D-0005）を機械的にチェックする。

対象は output/articles/{slug}.md（下書き段階。無ければ site/src/content/posts/{slug}.md）。

チェック項目:
  1. frontmatterのキーが必須9項目と完全一致しているか（欠落・余分キーの両方を検出）
  2. categoryが site/src/data/categories.ts 定義の4択のいずれかに収まっているか
  3. 本文（frontmatter除く）が純Markdownのみか（生HTMLタグの疑いを検出。コードブロック内は除外）
  4. 商品リンク（af.moshimo.com）がMarkdownリンク構文 [text](url) で直書きされているか

使い方:
  python site/scripts/check-article-portability.py <slug>

終了コード: 全項目OKなら0、1件でもNGがあれば1
"""

import os
import re
import sys

REQUIRED_KEYS = [
    "title",
    "slug",
    "date",
    "updated",
    "description",
    "tags",
    "hero",
    "status",
    "category",
]

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CATEGORIES_TS = os.path.join(ROOT, "site", "src", "data", "categories.ts")


def resolve_path(slug):
    draft = os.path.join(ROOT, "output", "articles", f"{slug}.md")
    if os.path.isfile(draft):
        return draft
    published = os.path.join(ROOT, "site", "src", "content", "posts", f"{slug}.md")
    if os.path.isfile(published):
        return published
    return None


def load_category_slugs():
    text = io_read(CATEGORIES_TS)
    m = re.search(r"CATEGORY_SLUGS\s*=\s*\[(.*?)\]", text, re.S)
    if not m:
        return []
    return re.findall(r"'([^']+)'", m.group(1))


def io_read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def split_frontmatter(text):
    m = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n(.*)\Z", text, re.S)
    if not m:
        return None, text
    return m.group(1), m.group(2)


def parse_frontmatter_keys(fm_text):
    keys = []
    values = {}
    for line in fm_text.splitlines():
        m = re.match(r"^([a-zA-Z_]+):\s*(.*)$", line)
        if m:
            key = m.group(1)
            keys.append(key)
            values[key] = m.group(2).strip()
    return keys, values


def strip_code_blocks(body):
    # フェンスコードブロック内は誤検知対象から除外する
    return re.sub(r"```.*?```", "", body, flags=re.S)


def check_frontmatter_keys(keys):
    missing = [k for k in REQUIRED_KEYS if k not in keys]
    extra = [k for k in keys if k not in REQUIRED_KEYS]
    ok = not missing and not extra
    detail = []
    if missing:
        detail.append(f"欠落: {', '.join(missing)}")
    if extra:
        detail.append(f"余分: {', '.join(extra)}")
    return ok, "; ".join(detail)


def check_category(values, allowed_slugs):
    category = values.get("category", "")
    if not allowed_slugs:
        return False, "categories.tsからCATEGORY_SLUGSを読み取れませんでした"
    if category in allowed_slugs:
        return True, ""
    return False, f"category='{category}' は許可された4択（{', '.join(allowed_slugs)}）に含まれません"


def check_html_free(body):
    clean = strip_code_blocks(body)
    violations = []
    for i, line in enumerate(clean.splitlines(), start=1):
        for m in re.finditer(r"</?[a-zA-Z][a-zA-Z0-9-]*(?:\s[^<>]*)?>", line):
            violations.append(f"{i}行目: {m.group(0)}")
    ok = not violations
    detail = "; ".join(violations[:5])
    if len(violations) > 5:
        detail += f" 他{len(violations) - 5}件"
    return ok, detail


def check_affiliate_links_plain(body):
    total = len(re.findall(r"af\.moshimo\.com", body))
    if total == 0:
        return True, "該当リンクなし"
    # リンクテキストが画像Markdown `![alt](img)` の場合（CLAUDE.md 5節の商品画像埋め込み形式
    # `[![商品名](画像)](URL)`）にも対応する。画像部分の `]` で閉じ括弧と誤認しないようにする。
    in_link = 0
    for m in re.finditer(r"\[(?:!\[[^\]]*\]\([^)]*\)|[^\[\]])+\]\([^)]*af\.moshimo\.com[^)]*\)", body):
        in_link += len(re.findall(r"af\.moshimo\.com", m.group(0)))
    ok = in_link == total
    detail = "" if ok else f"Markdownリンク構文外の出現あり（全{total}件中{total - in_link}件）"
    return ok, detail


def check_article(path, allowed_slugs):
    """1記事分の4項目チェックを実行し、[(項目名, ok, detail), ...] を返す。

    check-all-articles-portability.py から共通利用するために、
    main() の判定ロジック本体をここへ切り出したもの（判定ロジックの二重管理を避けるため）。
    """
    text = io_read(path)
    fm_text, body = split_frontmatter(text)
    if fm_text is None:
        return [("frontmatter", False, "frontmatterが見つかりません（--- で始まっていません）")]

    keys, values = parse_frontmatter_keys(fm_text)

    results = []
    results.append(("frontmatter必須9項目", *check_frontmatter_keys(keys)))
    results.append(("category(4択)", *check_category(values, allowed_slugs)))
    results.append(("本文の純Markdown性", *check_html_free(body)))
    results.append(("商品リンクのURL直書き", *check_affiliate_links_plain(body)))
    return results


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    slug = sys.argv[1]
    path = resolve_path(slug)
    if path is None:
        print(f"見つかりません: output/articles/{slug}.md / site/src/content/posts/{slug}.md")
        sys.exit(1)

    allowed_slugs = load_category_slugs()
    results = check_article(path, allowed_slugs)

    ng_count = 0
    for name, ok, detail in results:
        if ok:
            print(f"{name}: OK")
        else:
            ng_count += 1
            print(f"{name}: NG - {detail}")

    print(f"総合: {'OK' if ng_count == 0 else f'NG（{ng_count}件）'}")
    sys.exit(0 if ng_count == 0 else 1)


if __name__ == "__main__":
    main()
