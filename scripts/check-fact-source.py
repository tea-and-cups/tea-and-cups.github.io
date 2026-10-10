"""記事の「裏取りが要る事実」に出典URLが併記されているかを機械的に検査する。

記事の種類ではなく「記述の種類」で出典要否を判定する。
判定単位は本文（frontmatter・コードブロック除外）を空行で区切ったブロック。
見出し行（#始まり）は直後のブロックと結合して1単位として扱う。
画像行（![ 始まり）は判定対象から除外する。

裏取りが要る記述のカテゴリ:
  A 発売時期 / B 価格 / C 限定性 / D 受賞・認定 / E 初・首位・シェア
  F 沿革・規模 / G 数値主張 / H 実物を使った行為・観察・「編集部」の記述

カテゴリH（行為・観察・編集部）の特則（D-0245）:
  琥珀時間はAIが下調べ・執筆する媒体のため、淹れた・飲んだ・使った・見比べたといった
  実物を使った行為・観察の記述と、人の存在をうかがわせる「編集部」等の主語は書かない。
  出典URLを併記しても免除しない（出典の有無と無関係に違反）。検知は EXPERIENCE_PATTERNS。
  読者への呼びかけ（「試してみてください」等）と、AIが実際に行った調査の記述
  （「読み比べて整理した」等）は検知しない。

判定X・Y（D-0270・GD-0002/GD-0015の機械化。新規公開・--revise の両方で効く）:
  X 調査の材料: 調査方法を述べる行（「なお、この記事は」で始まる行、または「読み比べて」
    「突き合わせ」を含む行）に、他サイトの記事・解説・ブログ・まとめ・比較サイト・紹介記事等を
    調査の材料として挙げる語（RESEARCH_MATERIAL_WORDS）があればNG。許容する材料は
    楽天データの集計・メーカー/公的資料の突き合わせ（D-0245）。メーカー・官公庁の「解説」は
    RESEARCH_ALLOWED_PREFIXES で除いてから判定する。
  Y 安全・保存の断定: 次の型のどれかに当たる文があり、かつ同じブロック（箇条書きは1項目ずつ）に
    出典URL（アフィリエイト除く）も適用条件の語（SAFETY_CONDITION_WORDS）も無ければNG。
    型1 安全の保証（鉛・カドミウム等＋気にせず・安心等） 型2 使用可否の断定（電子レンジ・食洗機等
    ＋使える・OK等。「対応」は可の語に含めない） 型3 期間の断定（保存・賞味期限等＋期間）。
    語の単独出現では止めない。割れ・やけど・カビは対象にしない。
  --survey-xy: 公開済み全記事にX・Yだけをかける読み取り専用モード。

出典とみなすもの（カテゴリA・C〜Gのみ）:
  同一判定単位内の Markdownリンク [表示文字](http〜) または素のhttp(s) URL。
  ただしホストが af.moshimo.com・hb.afl.rakuten.co.jp のものは出典に数えない
  （アフィリエイトリンクを出典に数えるとチェックが実質無効化されるため）。

カテゴリB（価格）の特則:
  記事本文に価格を書かない。出典URLを併記しても許可しない
  （価格は変動するため、出典を付けてもその出典ごと古くなるため）。
  例外は次の2つのみで、いずれも機械的に確定できるものに限る:
    例外1 その記事自身の frontmatter の title に含まれる価格表現と同一の文字列
    例外2 Markdownリンクのリンクテキスト（[ ] の内側）にある価格表現
    例外3 category: gift の記事に限り、贈答の相場・予算帯の区分名（「3,000円台」
          「5,000円以下」「3,000〜5,000円」等）。同じ判定単位に「相場」または「予算」と
          執筆年月（「2026年10月執筆」「2026年10月時点」）があり、アフィリエイトリンクを
          含まない場合のみ。区分名の形をしていない価格（「1,280円」等）は個別商品の価格として
          違反のまま（rules/product-linking.md 5節・D-0249）

違反: 判定単位がA〜Gのいずれかに該当し、かつ
      ・Bに該当する（例外1〜3を除いた上で）場合は出典の有無を問わず違反
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

# 例外3（D-0249）: 贈答の相場・予算帯の区分名。category: gift の記事に限る。
# 区分名の形（「〜円台」「〜円以下/以上/未満/以内/超」「A〜B円」「〜B円」）だけを免除し、
# 「1,280円」のような単独の価格は個別商品の価格として違反のまま残す。
RE_CATEGORY_LINE = re.compile(r"^category:\s*(\S+)\s*$", re.M)
RE_BUDGET_BAND = re.compile(
    r"\d[\d,]*円(?:台|以下|以上|未満|以内|超)"
    r"|\d[\d,]*(?:円)?\s*[〜～~]\s*\d[\d,]*円"
    r"|[〜～~]\s*\d[\d,]*円"
)
RE_BUDGET_WORD = re.compile(r"相場|予算")
RE_WRITTEN_YM = re.compile(r"\d{4}年\d{1,2}月(?:執筆|時点)")

# カテゴリH（D-0245）: 実物を使った行為・観察の記述と「編集部」等の主語。
# 過去形の行為（〜たところ）・行為を前提にした条件文（実際に淹れ比べると）・感想の断定・
# 人の存在をうかがわせる主語だけを拾う。「試してみてください」等の読者への呼びかけや、
# 「読み比べて整理した」等のAIが実際に行った調査の記述は拾わない。
RE_EXPERIENCE_ACT = "|".join(
    [
        r"編集部|当編集|私たち|筆者",
        r"比べ(?:て(?:み)?)?たところ",
        r"(?:試し|使っ|飲ん|淹れ|いれ|入れ|作っ|食べ|測っ|量っ|計っ|触っ|並べ)(?:て)?(?:み)?たところ",
        r"実際に[^。、]{0,25}(?:淹れ比べ|見比べ|飲み比べ|食べ比べ|使い比べ|持ち比べ)(?:る)?と",
        r"実際に[^。、]{0,30}(?:て|で)みる?と",
        r"魅力に感じ(?:ます|ています)|(?:実感|痛感)(?:します|しました|しています)",
        r"感じました|驚きました|気づきました",
    ]
)
RE_EXPERIENCE = re.compile(RE_EXPERIENCE_ACT)

# 判定X（調査の材料・D-0270）。調査方法を述べる行に、他サイトの記事等を材料として挙げる語。
RESEARCH_LINE_START = "なお、この記事は"
RESEARCH_LINE_WORDS = ["読み比べて", "突き合わせ"]
RESEARCH_MATERIAL_WORDS = [
    "解説", "検証記事", "紹介記事", "記事", "ブログ", "まとめ", "比較サイト", "レシピサイト",
    "個人サイト", "口コミ", "レビュー記事", "レビューサイト", "ウェブ上", "ネット上", "サイト", "メディア",
]
# 材料語の前に付いていれば許容する出どころ（メーカー・公的資料・楽天データ）
RESEARCH_ALLOWED_PREFIXES = [
    "農林水産省", "厚生労働省", "消費者庁", "経済産業省", "国民生活センター", "公式",
    "メーカー", "各社", "製造元", "楽天",
]
# 判定Y（安全・保存の助言・D-0270。D-0270の調整で「語の出現」から「断定の型」へ変更）
# 同じ文に「対象語」と「断定語」が揃う文だけを拾う（語の単独出現では止めない）。
# 割れ・やけど・カビは語単独では対象にしない。「対応」は可の語に含めない（食洗機対応等の仕様表記を止めない）。
SAFETY_TYPE1_SUBJECT = ["鉛", "カドミウム", "有害", "溶出"]
SAFETY_TYPE1_GUARANTEE = [
    "気にせず", "心配ない", "心配なく", "安心", "問題ない", "問題なく", "大丈夫", "安全",
]
SAFETY_TYPE2_SUBJECT = ["電子レンジ", "食洗機", "オーブン", "直火", "煮沸", "漂白", "熱湯"]
SAFETY_TYPE2_OK = ["使える", "使用できる", "OK", "問題ない", "問題なく", "大丈夫"]
SAFETY_TYPE3_SUBJECT = ["保存", "日持ち", "賞味期限", "もつ", "持つ", "風味が落ちる"]
SAFETY_TYPE3_PERIOD = r"(?:[0-9０-９一二三四五六七八九十百]+\s*(?:日|週間|か月|ヶ月|カ月|年)|半年)"
RE_SAFETY_PERIOD = re.compile(SAFETY_TYPE3_PERIOD)
RE_SENTENCE_SPLIT = re.compile(r"[。！？!?\n]")
SAFETY_ADVICE_WORDS = (
    SAFETY_TYPE1_SUBJECT + SAFETY_TYPE1_GUARANTEE + SAFETY_TYPE2_SUBJECT + SAFETY_TYPE2_OK
    + SAFETY_TYPE3_SUBJECT + ["半年", "数字＋日・週間・か月・ヶ月・カ月・年"]
)
SAFETY_CONDITION_WORDS = [
    "未開封", "開封後", "表示に従", "表示を確認", "記載に従", "記載を確認", "取扱説明書",
    "取扱表示", "メーカーの指示", "メーカーの案内", "商品ページの表示", "商品ページの記載",
    "パッケージの表示", "パッケージの記載", "製品の表示",
]
RE_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")

CATEGORY_LABELS = {"A": "発売時期", "H": "行為・観察・編集部の記述"}
CATEGORY_LABELS.update({key: label for key, label, _ in CATEGORIES})
CATEGORY_ORDER = ["A", "B", "C", "D", "E", "F", "G", "H"]

# --- 出典判定 ------------------------------------------------------------------

RE_URL = re.compile(r"https?://[^\s\)\]\>\"'　]+")
# アフィリエイトリンク（出典に数えない・例外3を使えない）。楽天アフィリエイト（hb.afl.rakuten.co.jp・
# D-0260）ともしもアフィリエイト（af.moshimo.com）を同等に扱う。
RE_AFFILIATE = re.compile(
    r"^https?://(?:[\w.-]+\.)?(?:af\.moshimo\.com|hb\.afl\.rakuten\.co\.jp)", re.IGNORECASE
)
RE_AFFILIATE_ANY = re.compile(r"af\.moshimo\.com|hb\.afl\.rakuten\.co\.jp", re.IGNORECASE)


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


def is_gift_article(front):
    """frontmatterの category が gift か（例外3の適用条件）。"""
    m = RE_CATEGORY_LINE.search(front or "")
    return bool(m) and m.group(1) == "gift"


def budget_bands_exempt(text, is_gift):
    """例外3: 相場・予算帯の書式なら、区分名を除いた本文を返す。書式でなければNone。

    条件は全部満たすこと: gift記事／「相場」か「予算」を含む／執筆年月を含む／
    アフィリエイトURLを含まない（商品紹介ブロックで個別商品の価格を書けないようにする）。
    """
    if not is_gift:
        return None
    if not (RE_BUDGET_WORD.search(text) and RE_WRITTEN_YM.search(text)):
        return None
    if RE_AFFILIATE_ANY.search(text):
        return None
    return RE_BUDGET_BAND.sub(" ", text)


def price_survives_exceptions(text, title_prices, is_gift=False):
    """例外1〜3を除いてもなお価格表現が残るかを返す。"""
    # 例外2: Markdownリンクの表示文字部分を除去
    masked = RE_MD_LINK_TEXT.sub(lambda m: "[](", text)
    # 例外1: titleに含まれる価格表現と同一の文字列を除去
    for expr in title_prices:
        masked = masked.replace(expr, " ")
    # 例外3: gift記事の相場・予算帯の区分名（執筆年月つき）
    banded = budget_bands_exempt(text, is_gift)
    if banded is not None:
        masked = RE_BUDGET_BAND.sub(" ", masked)
    return bool(RE_PRICE_B.search(RE_URL.sub(" ", masked)))


def research_material_hits(line):
    """調査方法を述べる行なら、他サイトを材料として挙げる語を返す（該当しなければ空）。"""
    is_research = line.startswith(RESEARCH_LINE_START) or any(
        w in line for w in RESEARCH_LINE_WORDS
    )
    if not is_research:
        return []
    masked = RE_URL.sub(" ", line).replace("この記事", " ").replace("記事のヒーロー画像", " ")
    for prefix in RESEARCH_ALLOWED_PREFIXES:
        for w in RESEARCH_MATERIAL_WORDS:
            masked = masked.replace(prefix + "の" + w, " ").replace(prefix + w, " ")
    return [w for w in RESEARCH_MATERIAL_WORDS if w in masked]


def safety_sentence_types(sentence):
    """1文が当たる断定の型 [(型, 語...)] を返す。"""
    out = []
    t1 = [w for w in SAFETY_TYPE1_SUBJECT if w in sentence]
    g1 = [w for w in SAFETY_TYPE1_GUARANTEE if w in sentence]
    if t1 and g1:
        out.append(("型1", t1 + g1))
    t2 = [w for w in SAFETY_TYPE2_SUBJECT if w in sentence]
    g2 = [w for w in SAFETY_TYPE2_OK if w in sentence]
    if t2 and g2:
        out.append(("型2", t2 + g2))
    t3 = [w for w in SAFETY_TYPE3_SUBJECT if w in sentence]
    m3 = RE_SAFETY_PERIOD.search(sentence)
    if t3 and m3:
        out.append(("型3", t3 + [m3.group(0)]))
    return out


def safety_advice_hits(text):
    """出典も適用条件も無いブロックの断定文を [(型, 語リスト, 文)] で返す（問題なければ空）。"""
    plain = RE_URL.sub(" ", text)
    if has_valid_source(text) or any(w in plain for w in SAFETY_CONDITION_WORDS):
        return []
    hits = []
    for sentence in RE_SENTENCE_SPLIT.split(plain):
        sentence = sentence.strip()
        if not sentence:
            continue
        for typ, words in safety_sentence_types(sentence):
            hits.append((typ, words, sentence))
    return hits


def safety_sub_units(unit):
    """判定Y用に、箇条書きは1項目ずつ・それ以外はブロック全体を単位にする。"""
    if not any(RE_LIST_ITEM.match(line) for _, line in unit):
        return [unit]
    out, current = [], []
    for item in unit:
        if RE_LIST_ITEM.match(item[1]) and current:
            out.append(current)
            current = []
        current.append(item)
    if current:
        out.append(current)
    return out


def check_xy(path, slug):
    """判定X・Yの違反を返す（既存カテゴリの判定とは独立）。"""
    front, body = split_frontmatter(io_read(path))
    body_start_line = len(front.splitlines()) + 3 if front else 1
    out = []
    for unit in build_units(body, body_start_line):
        for lineno, line in unit:
            hits = research_material_hits(line)
            if hits:
                out.append({"slug": slug, "line": lineno, "categories": ["X"],
                            "excerpt": excerpt(line), "hit": "・".join(hits),
                            "sentence": line, "in_product_block": False})
        for sub in safety_sub_units(unit):
            for typ, words, sentence in safety_advice_hits(unit_text(sub)):
                out.append({"slug": slug, "line": sub[0][0], "categories": ["Y"],
                            "excerpt": excerpt(sentence), "hit": typ + ":" + "・".join(words),
                            "sentence": sentence, "in_product_block": False})
    return out


def excerpt(text):
    flat = re.sub(r"\s+", " ", text).strip()
    return flat[:EXCERPT_CHARS]


def check_article(path, slug, with_xy=False):
    """1記事を検査し、(違反リスト, 例外適用前のB該当単位数) を返す。"""
    text = io_read(path)
    front, body = split_frontmatter(text)
    body_start_line = len(front.splitlines()) + 3 if front else 1
    title_prices = title_price_expressions(front)
    is_gift = is_gift_article(front)

    violations = []
    b_before = 0
    for unit in build_units(body, body_start_line):
        text_u = unit_text(unit)
        cats = match_categories(text_u)
        experience = RE_EXPERIENCE.search(RE_URL.sub(" ", text_u))
        if not cats and not experience:
            continue
        if "B" in cats:
            b_before += 1
            if not price_survives_exceptions(text_u, title_prices, is_gift):
                cats = [c for c in cats if c != "B"]
        # Bは出典併記による免除を認めない。A・C〜Gは従来どおり出典があれば通す。
        if has_valid_source(text_u):
            cats = [c for c in cats if c == "B"]
        # Hも出典併記による免除を認めない（D-0245）。
        if experience:
            cats = cats + ["H"]
        if not cats:
            continue
        violations.append(
            {
                "slug": slug,
                "line": unit[0][0],
                "categories": cats,
                "excerpt": excerpt(text_u),
                "hit": experience.group(0) if experience else "",
                "in_product_block": has_affiliate(text_u),
            }
        )
    if with_xy:
        violations.extend(check_xy(path, slug))
        violations.sort(key=lambda v: v["line"])
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

    violations, _ = check_article(path, slug, with_xy=True)
    if not violations:
        print("FACT_SOURCE_OK")
        return 0

    print(f"出典が併記されていない要裏取り記述・行為観察の記述: {len(violations)}件")
    for v in violations:
        cats = "".join(v["categories"])
        hit = f" 〔検知語: {v['hit']}〕" if v.get("hit") else ""
        print(f"  L{v['line']} [{cats}] {v['excerpt']}{hit}")
    print("該当箇所に一次情報のURLを併記するか、断定を避けた表現へ書き換えてください")
    if any("H" in v["categories"] for v in violations):
        print("[H] 実物を使った行為・観察・「編集部」の記述は出典を付けても通りません。"
              "資料に基づく表現（〜が目安とされています／出典の記述）に書き換えるか削除してください")
    if any("X" in v["categories"] for v in violations):
        print("[X] 調査方法の行に他サイトの記事・解説等を材料として挙げています。実際の調査"
              "（楽天データの集計・メーカー/公的資料の突き合わせ）どおりに書き直してください。"
              "検知語一覧: " + "・".join(RESEARCH_MATERIAL_WORDS)
              + "（許容する出どころ: " + "・".join(RESEARCH_ALLOWED_PREFIXES) + "）")
    if any("Y" in v["categories"] for v in violations):
        print("[Y] 安全・保存の助言に出典URLも適用条件もありません。出典を付けるか、適用条件"
              "（未開封の場合・製品の表示に従う等）を付けるか、断定を削除してください。"
              "検知語一覧: " + "・".join(SAFETY_ADVICE_WORDS)
              + " ／ 条件語一覧: " + "・".join(SAFETY_CONDITION_WORDS))
    return 1


def run_survey_xy():
    """公開済み全記事に判定X・Yだけをかける（読み取りのみ）。型別件数と該当文（60字まで）を出す。"""
    found = []
    for path in sorted(glob.glob(os.path.join(POSTS_DIR, "*.md"))):
        if not is_published(path):
            continue
        slug = os.path.splitext(os.path.basename(path))[0]
        found.extend(check_xy(path, slug))
    counts = {}
    for v in found:
        key = "X" if v["categories"] == ["X"] else v["hit"].split(":")[0]
        counts[key] = counts.get(key, 0) + 1
    for key in ["X", "型1", "型2", "型3"]:
        print("XY_SURVEY_" + key + ": " + str(counts.get(key, 0)) + "件")
    shown = found[:50]
    for v in shown:
        label = "X" if v["categories"] == ["X"] else v["hit"].split(":")[0]
        sentence = re.sub(r"\s+", " ", v["sentence"]).strip()[:60]
        print(v["slug"] + " [" + label + "] " + sentence)
    if len(found) > 50:
        print("（先頭50件のみ表示。総数 " + str(len(found)) + "件）")
    print("XY_SURVEY_TOTAL: " + str(len(found)) + "件")
    return 0


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
    if args[0] == "--survey-xy":
        return run_survey_xy()
    return run_single(args[0])


if __name__ == "__main__":
    sys.exit(main())
