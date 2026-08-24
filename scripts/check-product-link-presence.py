"""記事への商品リンク必須化原則（rules/product-linking.md 0節・D-0061）を機械的にチェックする。

対象は output/articles/{slug}.md（下書き段階。無ければ site/src/content/posts/{slug}.md）。

判定単位は「リンク件数」ではなく「商品点数」である。1商品につき画像リンクとテキストリンクの
2本が並ぶ書式（rules/product-linking.md 3節）のため、本文中の af.moshimo.com を含むURLを
重複排除して数え、その件数を商品点数とみなす。画像取得に失敗してテキストリンクのみに
なった商品も、URLが1つ残るため1点として数えられる。

チェック内容:
  1. 商品点数が要求点数N（--min・省略時は1）以上であればOK
  2. N未満の場合、data/product-link-exceptions.md にそのslugが登録されているか確認する
     - 登録されていればOK（「例外登録済み（区分: 恒久/一時/候補不足）」の旨を出力）
     - 登録されていなければNG（商品を追加するか、例外登録するよう促す）

使い方:
  python site/scripts/check-product-link-presence.py <slug>            （N=1・週次の健全性チェック用）
  python site/scripts/check-product-link-presence.py <slug> --min 3    （新規記事の公開前チェック用）

終了コード: OKなら0、NGなら1
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXCEPTIONS_PATH = os.path.join(ROOT, "data", "product-link-exceptions.md")
EXCEPTIONS_REL = "data/product-link-exceptions.md"

DEFAULT_MIN_PRODUCTS = 1

# 本文中のアフィリエイトURL全体を拾う（末尾の ) や引用符・空白で切る）。
AFFILIATE_URL_RE = re.compile(r"https?://[^\s\)\"'\]<>]*af\.moshimo\.com[^\s\)\"'\]<>]*")


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


def count_products(body):
    """本文中のアフィリエイトURLを重複排除して数え、商品点数として返す。

    同一商品の画像リンクとテキストリンクは同一URLを指すため（全記事122件で実測・D-0162）、
    重複排除後の件数がそのまま商品点数になる。
    """
    return len(set(AFFILIATE_URL_RE.findall(body)))


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


def parse_args(argv):
    """(slug, min_products, エラーメッセージ) を返す。エラー時は先の2つがNone。"""
    slug = None
    min_products = DEFAULT_MIN_PRODUCTS
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--min":
            if i + 1 >= len(argv):
                return None, None, "--min には整数（1以上）を指定してください（値がありません）"
            raw = argv[i + 1]
            try:
                value = int(raw)
            except ValueError:
                return None, None, "--min には整数（1以上）を指定してください（受け取った値: %s）" % raw
            if value < 1:
                return None, None, "--min には1以上の整数を指定してください（受け取った値: %s）" % raw
            min_products = value
            i += 2
            continue
        if arg.startswith("-"):
            return None, None, "不明なオプションです: %s" % arg
        if slug is not None:
            return None, None, "slugは1つだけ指定してください（余分な引数: %s）" % arg
        slug = arg
        i += 1
    if slug is None:
        return None, None, "slugを指定してください"
    return slug, min_products, None


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    slug, min_products, err = parse_args(sys.argv[1:])
    if err is not None:
        print(err)
        sys.exit(1)

    path = resolve_path(slug)
    if path is None:
        print(f"見つかりません: output/articles/{slug}.md / site/src/content/posts/{slug}.md")
        sys.exit(1)

    text = io_read(path)
    _, body = split_frontmatter(text)
    if body is None:
        body = text

    products = count_products(body)

    if products >= min_products:
        print(f"商品リンク: OK（商品{products}点 / 要求{min_products}点以上）")
        print("総合: OK")
        sys.exit(0)

    kubun = find_exception(slug)
    if kubun is not None:
        print(f"商品リンク: 商品{products}点で要求{min_products}点に届きませんが、"
              f"例外登録済み（区分: {kubun}）")
        print("総合: OK")
        sys.exit(0)

    print(f"商品リンク: 商品{products}点で要求{min_products}点に届きません")
    print(f"商品を追加するか、絶対フロアを通過した候補が足りない等の理由がある場合は"
          f" {EXCEPTIONS_REL} に登録してください")
    print("注意: このチェックを通すためだけに関連性の薄い商品を挿入しないこと。"
          "自然に繋げられる商材が無ければ例外登録を選んでください")
    print("総合: NG")
    sys.exit(1)


if __name__ == "__main__":
    main()
