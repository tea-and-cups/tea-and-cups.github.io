"""記事への商品リンク必須化原則（rules/product-linking.md 0節・D-0061）を機械的にチェックする。

対象は output/articles/{slug}.md（下書き段階。無ければ site/src/content/posts/{slug}.md）。

判定単位は「リンク件数」ではなく「商品点数」である。1商品につき画像リンクとテキストリンクの
2本が並ぶ書式（rules/product-linking.md 3節）のため、本文中の商品リンクのURL
（楽天アフィリエイトの hb.afl.rakuten.co.jp・もしもアフィリエイトの af.moshimo.com）を
重複排除して数え、その件数を商品点数とみなす。画像取得に失敗してテキストリンクのみに
なった商品も、URLが1つ残るため1点として数えられる。

チェック内容:
  00. PR表記（「※当サイトはアフィリエイト広告（…）を利用しています。」）が、本文の商品リンクの
     URLホストから決まる期待文言と一致すること（GD-0026・D-0263）。楽天アフィリエイト
     （hb.afl.rakuten.co.jp）→もしもアフィリエイト（af.moshimo.com）の順に「・」でつなぎ、
     商品リンクが無ければ「楽天アフィリエイト」。1行だけあり、一致しなければNG（期待文言を1行出す）。
     新規公開・--revise・週次のいずれでも常に検査する
  0. --new（新規公開の公開前チェック。publish-article.py が初回公開のときだけ付ける）の場合、
     本文に af.moshimo.com のリンクが1件でもあればNG（新規記事は楽天アフィリエイトのみ・D-0260）。
     --new なし（--revise・週次）では、もしものリンクも従来どおり商品リンクとして数える
     （第2段の一括移行・D-0261で、商品ページが削除されてリンクを作り直せなかった商品だけ
       もしものリンクが残っているため、それらが週次で差し替わるまではもしものリンクを許す）
  1. 商品点数が要求点数N（--min・省略時は1）以上であればOK
  2. N未満の場合、data/product-link-exceptions.md にそのslugが登録されているか確認する
     - 登録されていればOK（「例外登録済み（区分: 恒久/一時/候補不足）」の旨を出力）
     - 登録されていなければNG（商品を追加するか、例外登録するよう促す）

使い方:
  python site/scripts/check-product-link-presence.py <slug>                  （N=1・週次の健全性チェック用）
  python site/scripts/check-product-link-presence.py <slug> --min 3          （下書き段階の単独確認）
  python site/scripts/check-product-link-presence.py <slug> --min 3 --new    （新規記事の公開前チェック用）
  python site/scripts/check-product-link-presence.py <slug> --pr-line-only   （PR表記だけ検査。--revise で公開中の商品が0点のとき）
  python site/scripts/check-product-link-presence.py --all-posts             （公開済み全記事のPR表記だけ検査）

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
# 楽天アフィリエイト（hb.afl.rakuten.co.jp・D-0260）ともしもアフィリエイト（af.moshimo.com）を同等に数える。
AFFILIATE_URL_RE = re.compile(
    r"https?://[^\s\)\"'\]<>]*(?:af\.moshimo\.com|hb\.afl\.rakuten\.co\.jp)[^\s\)\"'\]<>]*"
)
MOSHIMO_URL_RE = re.compile(r"https?://[^\s\)\"'\]<>]*af\.moshimo\.com[^\s\)\"'\]<>]*")

# PR表記は商品リンクのURLホストから決める（GD-0026・D-0263）。順序は表記に並べる順でもある。
# 商品リンクが無い記事は先頭（楽天アフィリエイト）とする。
PROGRAM_BY_HOST = (
    ("hb.afl.rakuten.co.jp", "楽天アフィリエイト"),
    ("af.moshimo.com", "もしもアフィリエイト"),
)
RE_PR_LINE = re.compile(r"^※当サイトはアフィリエイト広告[^\r\n]*", re.M)


def program_names(text):
    """本文の商品リンクのホストから、アフィリエイトプログラム名を返す（無ければ楽天のみ）。"""
    names = [name for host, name in PROGRAM_BY_HOST
             if re.search(r"https?://" + re.escape(host) + r"/", text)]
    return names or [PROGRAM_BY_HOST[0][1]]


def expected_pr_line(text):
    return "※当サイトはアフィリエイト広告（%s）を利用しています。" % "・".join(program_names(text))


def pr_line_problem(text):
    """PR表記が期待どおりなら None。違えば (期待する行, 実際の行のリスト) を返す。"""
    expected = expected_pr_line(text)
    found = RE_PR_LINE.findall(text)
    return None if found == [expected] else (expected, found)


def check_all_posts():
    """全記事（site/src/content/posts）のPR表記を検査し、終了コードを返す。"""
    posts_dir = os.path.join(ROOT, "site", "src", "content", "posts")
    names = sorted(n for n in os.listdir(posts_dir) if n.endswith(".md"))
    ng = 0
    for name in names:
        problem = pr_line_problem(io_read(os.path.join(posts_dir, name)))
        if problem:
            ng += 1
            print(f"NG {name[:-3]}")
            print(f"  期待: {problem[0]}")
            print(f"  実際: {' / '.join(problem[1]) if problem[1] else '（PR表記の行なし）'}")
    print(f"PR表記: 全{len(names)}記事・不一致{ng}件")
    return 1 if ng else 0


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
    """(slug, min_products, エラーメッセージ) を返す。エラー時は先の2つがNone。
    --new は main() が先に取り除くため、ここには来ない。"""
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

    argv = sys.argv[1:]
    if argv == ["--all-posts"]:
        sys.exit(check_all_posts())
    new_article = "--new" in argv
    pr_only = "--pr-line-only" in argv
    slug, min_products, err = parse_args([a for a in argv if a not in ("--new", "--pr-line-only")])
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

    problem = pr_line_problem(text)
    if problem:
        print("PR表記: 記事の広告表示が商品リンクのURLホストと一致しません（GD-0026）")
        print(f"  期待: {problem[0]}")
        print(f"  実際: {' / '.join(problem[1]) if problem[1] else '（PR表記の行なし）'}")
        print("総合: NG")
        sys.exit(1)
    print(f"PR表記: OK（{'・'.join(program_names(text))}）")
    if pr_only:
        print("総合: OK")
        sys.exit(0)

    if new_article:
        moshimo = sorted(set(MOSHIMO_URL_RE.findall(body)))
        if moshimo:
            print(f"商品リンク: もしもアフィリエイトのリンク（af.moshimo.com）が{len(moshimo)}件あります。"
                  "新規記事の商品リンクは楽天アフィリエイトのリンク作成ページのリンクだけを使います（D-0260）")
            print("  rules/product-linking.md 3節の手順（rakuten-freelink-extract.js → "
                  "build-rakuten-affiliate-products.py）でリンクを作り直してください")
            print("総合: NG")
            sys.exit(1)

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
