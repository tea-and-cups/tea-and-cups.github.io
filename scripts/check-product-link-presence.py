"""記事への商品リンク必須化原則（rules/product-linking.md 0節・D-0061）を機械的にチェックする。

対象は output/articles/{slug}.md（下書き段階。無ければ site/src/content/posts/{slug}.md）。

チェック内容:
  1. 本文中に商品アフィリエイトリンク（af.moshimo.com、もしもアフィリエイト経由の楽天市場リンク）が
     1件以上あればOK
  2. 無い場合、data/product-link-exceptions.md にそのslugが登録されているか確認する
     - 登録されていればOK（「例外登録済み（区分: 恒久/一時）」の旨を出力）
     - 登録されていなければNG（商品リンクを追加するか、例外登録するよう促す）

使い方:
  python site/scripts/check-product-link-presence.py <slug>

終了コード: OKなら0、NGなら1
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXCEPTIONS_PATH = os.path.join(ROOT, "data", "product-link-exceptions.md")

AFFILIATE_LINK_RE = re.compile(r"af\.moshimo\.com")


def resolve_path(slug):
    draft = os.path.join(ROOT, "output", "articles", f"{slug}.md")
    if os.path.isfile(draft):
        return draft
    published = os.path.join(ROOT, "site", "src", "content", "posts", f"{slug}.md")
    if os.path.isfile(published):
        return published
    return None


def io_read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def split_frontmatter(text):
    m = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n(.*)\Z", text, re.S)
    if not m:
        return None, text
    return m.group(1), m.group(2)


def count_product_links(body):
    return len(AFFILIATE_LINK_RE.findall(body))


def find_exception(slug):
    """data/product-link-exceptions.md の台帳からslugを検索し、区分を返す（無ければNone）。"""
    if not os.path.isfile(EXCEPTIONS_PATH):
        return None
    text = io_read(EXCEPTIONS_PATH)
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cols = [c.strip() for c in line.strip("|").split("|")]
        if len(cols) < 3:
            continue
        if cols[0] == slug:
            # | 記事slug | 登録日 | 区分 | 理由 |
            kubun = cols[2] if len(cols) > 2 else "不明"
            return kubun
    return None


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

    text = io_read(path)
    _, body = split_frontmatter(text)
    if body is None:
        body = text

    link_count = count_product_links(body)

    if link_count > 0:
        print(f"商品リンク: OK（{link_count}件検出）")
        print("総合: OK")
        sys.exit(0)

    kubun = find_exception(slug)
    if kubun is not None:
        print(f"商品リンク: 0件ですが例外登録済み（区分: {kubun}）")
        print("総合: OK")
        sys.exit(0)

    print("商品リンクが未検出です。商品リンクを追加するか、構造上の理由がある場合は"
          "data/product-link-exceptions.mdに登録してください")
    print("注意: このチェックを通すためだけに関連性の薄い商品を挿入しないこと。"
          "自然に繋げられる商材が無ければ例外登録を選んでください")
    print("総合: NG")
    sys.exit(1)


if __name__ == "__main__":
    main()
