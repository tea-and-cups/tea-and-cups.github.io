"""記事の「裏取りが要る事実」に出典URLが併記されているかを機械的に検査する。

記事の種類ではなく「記述の種類」で出典要否を判定する。
判定単位は本文（frontmatter・コードブロック除外）を空行で区切ったブロック。
見出し行（#始まり）は直後のブロックと結合して1単位として扱う。
画像行（![ 始まり）は判定対象から除外する。

裏取りが要る記述のカテゴリ:
  A 発売時期 / B 価格 / C 限定性 / D 受賞・認定 / E 初・首位・シェア
  F 沿革・規模 / G 数値主張

出典とみなすもの（カテゴリA・C〜Gのみ）:
  同一判定単位内の Markdownリンク [表示文字](http〜) または素のhttp(s) URL。
  ただしホストが af.moshimo.com のものは出典に数えない
  （アフィリエイトリンクを出典に数えるとチェックが実質無効化されるため）。

カテゴリB（価格）の特則:
  記事本文に価格を書かない。出典URLを併記しても許可しない
  （価格は変動するため、出典を付けてもその出典ごと古くなるため）。
  例外は次の2つのみで、いずれも機械的に確定できるものに限る:
    例外1 その記事自身の frontmatter の title に含まれる価格表現と同一の文字列
    例外2 Markdownリンクのリンクテキスト（[ ] の内側）にある価格表現

違反: 判定単位がA〜Gのいずれかに該当し、かつ
      ・Bに該当する（例外1・例外2を除いた上で）場合は出典の有無を問わず違反
      ・A・C〜Gに該当する場合は有効な出典を1つも含まないとき違反
      件数は「判定単位1つ＝1件」で数える（複数カテゴリ該当でも1件）。
      カテゴリ別件数は該当カテゴリごとの延べ数のため、合計は違反総数を超えうる。

使い方:
  python site/scripts/check-fact-source.py <slug>      通常モード
  python site/scripts/check-fact-source.py --calibrate 較正モード（公開済み全件）

終了コード: 通常モード OK=0 / 違反あり=1、較正モードは常に0
"""

import glob
import os
import re
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POSTS_DIR = os.path.join(ROOT, "site", "src", "content", "posts")
DRAFTS_DIR = os.path.join(ROOT, "output", "articles")
CALIBRATION_OUT = os.path.join(ROOT, "output", "fact-source-calibration.md")

EXCERPT_LIMIT = 30
EXCERPT_CHARS = 40
TOP_ARTICLES = 5

# --- 裏取りが要る記述の検知条件 -------------------------------------------------

RE_DATE = re.compile(r"\d{4}年|\d{1,2}月\d{1,2}日|\d{1,2}月")
RE_RELEASE_WORD = re.compile(r"発売|販売開始|登場|リリース")

CATEGORIES = [
    ("B", "価格", re.compile(r"\d[\d,]*円|税込|税抜|希望小売価格")),
    ("C", "限定性", re.compile(r"数量限定|期間限定|限定販売|限定\d|先着|完売")),
    ("D", "受賞・認定", re.compile(r"受賞|金賞|大賞|グランプリ|モンドセレクション|認定")),
    (
        "E",
        "初・首位・シェア",
        re.compile(r"日本初|世界初|業界初|国内初|初の|No\.1|ナンバーワン|第1位|1位|シェア"),
    ),
    (
        "F",
        "沿革・規模",
        re.compile(r"創業\d{4}|創立\d{4}|設立\d{4}|\d{4}年創業|\d+か国|\d+ヶ国|\d+店舗"),
    ),
    ("G", "数値主張", re.compile(r"\d+(?:\.\d+)?%|約\d+倍")),
]

RE_PRICE_B = CATEGORIES[0][2]  # カテゴリB（価格）の検知パターン

# 例外1: titleから抜き出す価格表現（数字＋円を含む連続した表現）
RE_TITLE_LINE = re.compile(r"^title:\s*(.+?)\s*$", re.M)
RE_PRICE_EXPR = re.compile(r"\d[\d,]*円(?:以下|以上|未満|前後|程度|台|超|以内)?")

# 例外2: Markdownリンクの表示文字部分 [表示文字](
RE_MD_LINK_TEXT = re.compile(r"\[([^\]\n]*)\]\(")

CATEGORY_LABELS = {"A": "発売時期"}
CATEGORY_LABELS.update({key: label for key, label, _ in CATEGORIES})
CATEGORY_ORDER = ["A", "B", "C", "D", "E", "F", "G"]

# --- 出典判定 ------------------------------------------------------------------

RE_URL = re.compile(r"https?://[^\s\)\]\>\"'　]+")
RE_AFFILIATE = re.compile(r"^https?://(?:[\w.-]+\.)?af\.moshimo\.com", re.IGNORECASE)


def io_read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def split_frontmatter(text):
    m = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n(.*)\Z", text, re.S)
    if not m:
        return "", text
    return m.group(1), m.group(2)


def strip_code_blocks(lines):
    """コードブロック内の行を空行に置換する（行番号を保つため削除はしない）。"""
    out = []
    in_code = False
    for line in lines:
        if line.lstrip().startswith("```"):
            in_code = not in_code
            out.append("")
            continue
        out.append("" if in_code else line)
    return out


def build_units(body, body_start_line):
    """本文を判定単位（(開始行番号, [行...]) のリスト）に分割する。"""
    raw_lines = body.splitlines()
    lines = strip_code_blocks(raw_lines)

    blocks = []
    current = []
    for idx, line in enumerate(lines):
        lineno = body_start_line + idx
        if line.strip() == "":
            if current:
                blocks.append(current)
                current = []
            continue
        if line.lstrip().startswith("!["):
            continue  # 画像行は判定対象外
        current.append((lineno, line))
    if current:
        blocks.append(current)

    def is_heading_only(block):
        return all(line.lstrip().startswith("#") for _, line in block)

    units = []
    pending = []
    for block in blocks:
        if is_heading_only(block):
            pending.extend(block)
            continue
        units.append(pending + block)
        pending = []
    if pending:
        units.append(pending)
    return units


def unit_text(unit):
    return "\n".join(line for _, line in unit)


def has_valid_source(text):
    for url in RE_URL.findall(text):
        if not RE_AFFILIATE.match(url):
            return True
    return False


def has_affiliate(text):
    return any(RE_AFFILIATE.match(url) for url in RE_URL.findall(text))


def match_categories(text):
    # URL文字列自体は主張ではない。URLエンコード（%2F 等）や商品IDの数字が
    # 数値主張として誤検知されるため、判定前にURLを除去する。
    text = RE_URL.sub(" ", text)
    hits = []
    if RE_RELEASE_WORD.search(text) and RE_DATE.search(text):
        hits.append("A")
    for key, _label, pattern in CATEGORIES:
        if pattern.search(text):
            hits.append(key)
    return hits


def title_price_expressions(front):
    """frontmatterのtitleに含まれる価格表現を返す（例外1の材料）。"""
    m = RE_TITLE_LINE.search(front or "")
    if not m:
        return []
    return sorted(set(RE_PRICE_EXPR.findall(m.group(1))), key=len, reverse=True)


def price_survives_exceptions(text, title_prices):
    """例外1・例外2を除いてもなお価格表現が残るかを返す。"""
    # 例外2: Markdownリンクの表示文字部分を除去
    masked = RE_MD_LINK_TEXT.sub(lambda m: "[](", text)
    # 例外1: titleに含まれる価格表現と同一の文字列を除去
    for expr in title_prices:
        masked = masked.replace(expr, " ")
    return bool(RE_PRICE_B.search(RE_URL.sub(" ", masked)))


def excerpt(text):
    flat = re.sub(r"\s+", " ", text).strip()
    return flat[:EXCERPT_CHARS]


def check_article(path, slug):
    """1記事を検査し、(違反リスト, 例外適用前のB該当単位数) を返す。"""
    text = io_read(path)
    front, body = split_frontmatter(text)
    body_start_line = len(front.splitlines()) + 3 if front else 1
    title_prices = title_price_expressions(front)

    violations = []
    b_before = 0
    for unit in build_units(body, body_start_line):
        text_u = unit_text(unit)
        cats = match_categories(text_u)
        if not cats:
            continue
        if "B" in cats:
            b_before += 1
            if not price_survives_exceptions(text_u, title_prices):
                cats = [c for c in cats if c != "B"]
        # Bは出典併記による免除を認めない。A・C〜Gは従来どおり出典があれば通す。
        if has_valid_source(text_u):
            cats = [c for c in cats if c == "B"]
        if not cats:
            continue
        violations.append(
            {
                "slug": slug,
                "line": unit[0][0],
                "categories": cats,
                "excerpt": excerpt(text_u),
                "in_product_block": has_affiliate(text_u),
            }
        )
    return violations, b_before


def resolve_path(slug):
    draft = os.path.join(DRAFTS_DIR, f"{slug}.md")
    if os.path.isfile(draft):
        return draft
    published = os.path.join(POSTS_DIR, f"{slug}.md")
    if os.path.isfile(published):
        return published
    return None


def is_published(path):
    head = io_read(path).splitlines()[:20]
    return any(re.match(r"\s*status:\s*published\s*$", line) for line in head)


# --- 出力 ----------------------------------------------------------------------


def run_single(slug):
    path = resolve_path(slug)
    if path is None:
        print(f"見つかりません: output/articles/{slug}.md / site/src/content/posts/{slug}.md")
        return 1

    violations, _ = check_article(path, slug)
    if not violations:
        print("FACT_SOURCE_OK")
        return 0

    print(f"出典が併記されていない要裏取り記述: {len(violations)}件")
    for v in violations:
        cats = "".join(v["categories"])
        print(f"  L{v['line']} [{cats}] {v['excerpt']}")
    print("該当箇所に一次情報のURLを併記するか、断定を避けた表現へ書き換えてください")
    return 1


def run_calibrate():
    paths = sorted(glob.glob(os.path.join(POSTS_DIR, "*.md")))
    targets = [p for p in paths if is_published(p)]

    per_article = []
    all_violations = []
    b_before_total = 0
    for path in targets:
        slug = os.path.splitext(os.path.basename(path))[0]
        v, b_before = check_article(path, slug)
        per_article.append((slug, len(v)))
        all_violations.extend(v)
        b_before_total += b_before

    total = len(all_violations)
    counts = [n for _, n in per_article]
    mean = (total / len(counts)) if counts else 0.0
    median = statistics.median(counts) if counts else 0.0
    zero = sum(1 for n in counts if n == 0)

    print("=== check-fact-source.py 較正結果 ===")
    print(f"対象記事数（status: published）: {len(targets)}")
    print(f"違反総数: {total}")
    print(f"1記事あたり平均: {mean:.2f}")
    print(f"中央値: {median}")
    print(f"違反0件の記事数: {zero}")
    print("")
    print("--- カテゴリ別（延べ数・1単位が複数カテゴリに該当しうる） ---")
    for key in CATEGORY_ORDER:
        hits = [v for v in all_violations if key in v["categories"]]
        articles = len({v["slug"] for v in hits})
        print(f"{key} {CATEGORY_LABELS[key]}: {len(hits)}件 / {articles}記事")

    b_hits = [v for v in all_violations if "B" in v["categories"]]
    b_in = sum(1 for v in b_hits if v["in_product_block"])
    print(
        f"  └ B例外: 例外適用前 {b_before_total}件 / 例外適用後 {len(b_hits)}件"
        f"（例外1・2で除外 {b_before_total - len(b_hits)}件）"
    )
    print(
        f"  └ B内訳: 商品リンクブロック内 {b_in}件 / 本文中 {len(b_hits) - b_in}件"
    )
    print("")
    print("--- 違反件数上位5本 ---")
    for slug, n in sorted(per_article, key=lambda x: -x[1])[:TOP_ARTICLES]:
        print(f"{n}件  {slug}")
    print("")
    print(f"--- 違反箇所の抜粋（最大{EXCERPT_LIMIT}件） ---")
    for v in all_violations[:EXCERPT_LIMIT]:
        print(f"{v['slug']} L{v['line']} [{''.join(v['categories'])}] {v['excerpt']}")
    if total > EXCERPT_LIMIT:
        print(f"他{total - EXCERPT_LIMIT}件")

    write_calibration_detail(targets, per_article, all_violations, mean, median, zero)
    print("")
    print(f"全件明細: output/fact-source-calibration.md（上書き保存）")
    return 0


def write_calibration_detail(targets, per_article, all_violations, mean, median, zero):
    lines = []
    lines.append("# check-fact-source.py 較正明細（自動生成・毎回上書き）")
    lines.append("")
    lines.append(f"- 対象記事数: {len(targets)}")
    lines.append(f"- 違反総数: {len(all_violations)}")
    lines.append(f"- 1記事あたり平均: {mean:.2f}")
    lines.append(f"- 中央値: {median}")
    lines.append(f"- 違反0件の記事数: {zero}")
    lines.append("")
    lines.append("## 記事別違反件数")
    lines.append("")
    lines.append("| 記事slug | 違反件数 |")
    lines.append("|---|---|")
    for slug, n in sorted(per_article, key=lambda x: (-x[1], x[0])):
        lines.append(f"| {slug} | {n} |")
    lines.append("")
    lines.append("## 違反箇所 全件明細")
    lines.append("")
    lines.append("| 記事slug | 行 | カテゴリ | 商品リンクブロック内 | 本文先頭40字 |")
    lines.append("|---|---|---|---|---|")
    for v in all_violations:
        mark = "○" if v["in_product_block"] else ""
        text = v["excerpt"].replace("|", "\\|")
        lines.append(
            f"| {v['slug']} | {v['line']} | {''.join(v['categories'])} | {mark} | {text} |"
        )
    with open(CALIBRATION_OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = sys.argv[1:]
    if len(args) != 1:
        print(__doc__)
        return 1
    if args[0] == "--calibrate":
        return run_calibrate()
    return run_single(args[0])


if __name__ == "__main__":
    sys.exit(main())
