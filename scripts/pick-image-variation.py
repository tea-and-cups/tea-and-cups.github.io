"""hero画像・Pin画像3枚（計4枚）の構図バリエーションを機械的に選ぶ（D-0034）。
Pin画像（pin1〜3）については「型」の候補リスト提示も担う（D-0062）。

背景:
  ChatGPT用の画像生成プロンプトを毎回AIが記事内容だけを見て組み立てると、
  「安全に通った過去の表現」を無意識に使い回してしまい、俯瞰・木製テーブル・
  生成りリネン・明朝体下部帯といった構図がほぼ全記事で固定化していた
  （経緯は reports/2026-08-01.md 参照）。
  数値の判断をscore-product.pyに閉じ込めているのと同じ考え方で、構図の選定も
  このスクリプトに閉じ込め、AIが頭の中で「そろそろ違うのを選ぼう」と判断しない
  ようにする。

判定の作り（4軸・hero/pin共通）:
  各軸（アングル/フレーミング/テキスト配置/背景小物）ごとに、記事1本を処理する
  たびに1ずつ進む連番（article_seq）を開始位置として、軸の選択肢リストを
  ラウンドロビンで4枚（hero→pin1→pin2→pin3の順）に割り当てる。
    - 選択肢が4つの軸（アングル/背景小物）: 1記事内で4枚とも別の値になる
      （重複なし）。
    - 選択肢が2つの軸（フレーミング）・3つの軸（テキスト配置）: 1記事内で
      重複ゼロにはできないため、偏りなく交互・順送りに割り当てる。
  article_seqは記事ごとに1ずつ進むため、次の記事では開始位置がずれ、
  どの画像がどの値になるかも一緒にローテーションする（同じ組み合わせが
  毎回同じ位置に固定されない）。乱数は使わない＝同じ台帳状態からは常に
  同じ結果になる。

  テキスト配置は上部帯／下部帯／中央の3択のみで「テキストなし」は廃止済み
  （D-0049）。hero・Pin画像は文字オーバーレイを必須とし、返ってきた位置に
  必ず見出し文言を焼き込む指示をChatGPTへのプロンプトに含めること。

型（image_style）の扱い（D-0062・pin1〜3のみ）:
  上記4軸は「1枚の物撮り写真」の内部パラメータでしかなく、写真か図解かという
  「型」を選ぶ軸が無かったため、pin1〜3が3枚とも同じ物撮り型に収束していた
  （pin78〜80の調査結果）。そこでIMAGE_STYLES（12種）を型候補プールとして持ち、
  直近2記事のpin1〜3で使われた型を除外した「今回選べる候補リスト」を提示する。
    - どの型をpin1/pin2/pin3に割り当てるかはこのスクリプトでは決めない。
      記事内容を理解しているAIが候補リストの中から異なる3つを選ぶ。
    - 除外後の候補が3個未満になる場合は、直近1記事のみの除外に緩め、
      それでも3個未満ならプール全体を候補として出す（選定が詰まるのを防ぐ）。
      緩和が起きた場合は出力にその旨を注記する。
    - heroは型プールの対象外。従来どおり4軸のみで選定する（写真型を維持）。

条件の振り分け（D-0152・情報量×CTAの4群・pin1〜3のみ）:
  「1枚に載る情報量の多少」と「CTA帯（続きはタップ等）の有無」を掛け合わせた4群を、
  記事単位で同時並行に走らせて比較する。対象記事の article_seq を4で割った余りで機械的に
  判定し（conditions_for_seq()）、出力の先頭に両方の条件名を明示する。
    余り1 → 情報多め（現行条件）・CTAなし
    余り2 → 情報少なめ（低情報量条件）・CTAなし
    余り3 → 情報多め（現行条件）・CTAあり
    余り0 → 情報少なめ（低情報量条件）・CTAあり
    - 低情報量条件: 候補を低密度4種（IMAGE_STYLESで DENSITY_LOW を持つ型）だけに絞る。
      このとき「直近2記事で使った型を除外」の規則は適用しない（候補が4種しかなく、
      除外すると枯れるため）。守るのは「同一記事内でpin1〜3が重複しないこと」だけ。
      1枚あたりの文言件数（1〜2件）と型の低密度チェックは make-image-prompt.py が強制する。
    - 現行条件: 型・文言件数の扱いは従来のまま（型は12種・文言は1〜6件）。
    - CTAあり: pin1〜3の3枚すべてにCTA帯を焼き込む（1枚だけに入れる方式は取らない。
      同一記事内でCTAあり・なしが混在すると、ボードとスロットの違いが条件差に混ざるため）。
      焼き込む文言は CTA_TEXTS（件数はコード側で定義）から article_seq で機械的に選ぶ（cta_text_for_seq()）。
      CTA文言は --pinN-text の件数制限の対象外（見出しとCTAは役割が異なるため）。
      帯の意匠指示と実際の焼き込み指示は make-image-prompt.py が組み立てる。
    - CTAなし: 依頼文は従来どおりでCTAの記述を一切含めない。

使い方:
  python site/scripts/pick-image-variation.py <slug>
      台帳（data/image-variation.tsv）に4行（hero/pin1/pin2/pin3）を追記し、
      選んだ組み合わせと、pin1〜3で選択可能な型の候補リストを標準出力に表示する。
      この時点では image_style 列は空欄のまま追記される（AIが記事内容を見て
      選ぶのはこの後のため）。
      同じslugを続けて実行した場合（同一セッション内の再実行等）は、台帳の
      末尾4行がそのslugのものであればそれをそのまま再表示するだけで、
      二重に消費しない。

  python site/scripts/pick-image-variation.py --set-style <slug> "pin1=手順図解" "pin2=チェックリスト" "pin3=Q&A形式"
      AIが選定した型を台帳の image_style 列に記録する（画像生成後に必ず実行する）。
      型名は IMAGE_STYLES の値そのまま、または一覧の番号（1〜12）で指定できる。
      PowerShellでは `&` 等が解釈されるため、各引数は必ず引用符で囲むこと
      （例: "pin3=Q&A形式" もしくは番号指定の pin3=6）。
      記録漏れは site/scripts/check-pin-image-style.py がエラーとして検知する。
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LEDGER_PATH = os.path.join(ROOT, "data", "image-variation.tsv")

HEADER_COMMENT = """# image-variation.tsv — hero/Pin画像の構図バリエーション台帳
#
# site/scripts/pick-image-variation.py が読み書きする。手で編集しない。
# 1行 = 画像1枚。列: article_seq(連番) / slug / image_type(hero|pin1|pin2|pin3) / date / angle / framing / text_position / background / image_style
# image_style は Pin画像の「型」（D-0062）。pin1〜3のみ値が入り、heroは常に空欄。
#   pick-image-variation.py <slug> の時点では空欄で追記され、AIが型を選定した後に
#   pick-image-variation.py --set-style <slug> pin1=... pin2=... pin3=... で埋める。
# 保持件数の上限は8記事分（32行）。超えた分は同スクリプトが古い記事から自動で削除する（CLAUDE.md 10節・D-0031の肥大化防止原則）。
#
"""

COLUMNS = ["article_seq", "slug", "image_type", "date", "angle", "framing", "text_position", "background", "image_style"]

IMAGE_SLOTS = ["hero", "pin1", "pin2", "pin3"]
PIN_SLOTS = ["pin1", "pin2", "pin3"]

AXES = {
    "angle": ["俯瞰", "斜め45度", "正面", "手元アップ"],
    "framing": ["引き", "寄り"],
    "text_position": ["上部帯", "下部帯", "中央"],  # 「テキストなし」は廃止（D-0049・hero/Pin画像は文字オーバーレイ必須）
    "background": ["木目テーブル＋リネン", "大理石", "窓辺の自然光", "布ナプキン＋陶器小物"],
}

# Pin画像（pin1〜3）の型候補プール（D-0062）と、型ごとの情報密度（D-0152）。
# 増減・密度の変更はこの辞書だけを直す（他のロジックはすべてここを参照する。
# make-image-prompt.py 側にも複製しない）。
# 情報密度は「1枚に載る文言の多さ」の分類で、低情報量条件（後述）の候補プールを決めるのに使う。
DENSITY_LOW = "低"
DENSITY_HIGH = "高"

IMAGE_STYLES = {
    "写真ヒーロー": DENSITY_LOW,           # 物撮り・情景写真
    "比較グリッド": DENSITY_HIGH,          # 2〜4項目を並列表示
    "手順図解": DENSITY_HIGH,              # ステップ形式
    "チェックリスト": DENSITY_HIGH,
    "ビフォーアフター": DENSITY_LOW,       # 対比構造
    "Q&A形式": DENSITY_LOW,
    "ポイント整理": DENSITY_HIGH,          # 要点まとめ
    "ランキング": DENSITY_HIGH,            # 番付形式
    "数字訴求型": DENSITY_LOW,             # 統計・数字を大きく見せる
    "用語解説型": DENSITY_HIGH,            # 辞書・用語集ふう
    "シーン別ガイド": DENSITY_HIGH,        # 用途・シチュエーション別に分岐
    "相関図フローチャート": DENSITY_HIGH,  # 要素同士の関係性を線・矢印で示す
}

# 番号指定（--set-style pin1=6 等）と一覧表示に使う型名リスト。IMAGE_STYLESの定義順をそのまま使う。
STYLE_NAMES = list(IMAGE_STYLES)
LOW_INFO_STYLES = [s for s, d in IMAGE_STYLES.items() if d == DENSITY_LOW]

STYLE_LOOKBACK = 2   # 型の重複除外に使う直近記事数
MIN_CANDIDATES = 3   # pin1〜3に別々の型を割り当てるために最低限必要な候補数

# --- 条件の振り分け（D-0152・情報量×CTAの4群） -------------------------------
# Pin画像の「情報量の多少」と「CTA帯の有無」を掛け合わせた4群を、記事単位で同時並行に
# 走らせて比較する。振り分けは article_seq を4で割った余りで機械的に決め、AIの判断に委ねない。
#   余り1 → 情報多め（現行条件）・CTAなし
#   余り2 → 情報少なめ（低情報量条件）・CTAなし
#   余り3 → 情報多め（現行条件）・CTAあり
#   余り0 → 情報少なめ（低情報量条件）・CTAあり
# 情報量条件だけを見ると「偶数=低情報量／奇数=現行」であり、D-0152導入時（2群）の判定と
# 完全に一致する（余り2と余り0が偶数、余り1と余り3が奇数）。
# 判定は conditions_for_seq() の1箇所だけに置く。make-image-prompt.py / check-pin-image-style.py /
# analyze-pin-metrics.py はこの関数（またはそこから導く薄いラッパー）を呼び、余りの計算を複製しない。
CONDITION_LOW = "低情報量条件"
CONDITION_CURRENT = "現行条件"
CTA_YES = "CTAあり"
CTA_NONE = "CTAなし"
LOW_INFO_TEXT_MIN = 1  # 低情報量条件で1枚に指定できる文言の下限（make-image-prompt.pyが参照する）
LOW_INFO_TEXT_MAX = 2  # 同・上限

# 4群の振り分け表（キー = article_seq % 4）。群を増減するときはこの辞書だけを直す。
CONDITION_BY_REMAINDER = {
    1: (CONDITION_CURRENT, CTA_NONE),
    2: (CONDITION_LOW, CTA_NONE),
    3: (CONDITION_CURRENT, CTA_YES),
    0: (CONDITION_LOW, CTA_YES),
}

# CTA帯に焼き込む文言の固定候補（D-0152）。自由入力は受け付けない（表記ゆれを防ぐため）。
# 半角英数字・半角記号を含めないこと（make-image-prompt.py の出力直前ASCII検査に抵触するため・D-0149）。
# analyze-pin-metrics.py はこのリストをそのまま検索語として使い、CTAの有無を判定する。
CTA_TEXTS = [
    "続きはタップ",
    "タップして読む",
    "詳しくはこちら",
    "タップで続きを読む",
    "続きを見る",
    "続きはこちら",
    "もっと詳しく",
    "タップで詳しく",
    "記事を読む",
    "さらに詳しく",
]

MAX_ARTICLES = 8  # 台帳の保持上限（記事数）。CLAUDE.md 10節の肥大化防止原則に合わせる
MAX_ROWS = MAX_ARTICLES * len(IMAGE_SLOTS)


def read_ledger():
    if not os.path.exists(LEDGER_PATH):
        return []
    rows = []
    with open(LEDGER_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            cols = line.split("\t")
            if cols == COLUMNS or cols == COLUMNS[:-1]:
                continue  # ヘッダー行（image_style列の有無を問わない）
            # image_style列を持たない過去データ（D-0062以前の行）は空欄扱いで読む
            if len(cols) == len(COLUMNS) - 1:
                cols.append("")
            if len(cols) != len(COLUMNS):
                continue
            rows.append(dict(zip(COLUMNS, cols)))
    return rows


def write_ledger(rows):
    with open(LEDGER_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(HEADER_COMMENT)
        f.write("\t".join(COLUMNS) + "\n")
        for r in rows:
            f.write("\t".join(r.get(c, "") for c in COLUMNS) + "\n")


def group_by_article(rows, exclude_slug=None):
    """台帳の行を記事単位（article_seq+slug）にまとめ、出現順のリストで返す。"""
    groups = []
    for r in rows:
        if exclude_slug is not None and r["slug"] == exclude_slug:
            continue
        key = (r["article_seq"], r["slug"])
        if not groups or groups[-1][0] != key:
            groups.append((key, []))
        groups[-1][1].append(r)
    return groups


def recent_style_usage(rows, exclude_slug=None, lookback=STYLE_LOOKBACK):
    """直近lookback記事のpin1〜3で使われた型の集合を返す。

    image_style列が空欄の行は「データなし」として無視する（記録漏れの行が
    除外リストを不当に狭めないようにするため）。
    """
    if lookback <= 0:
        return set()
    used = set()
    for _key, group in group_by_article(rows, exclude_slug)[-lookback:]:
        for r in group:
            style = r.get("image_style", "").strip()
            if r["image_type"] in PIN_SLOTS and style:
                used.add(style)
    return used


def conditions_for_seq(article_seq):
    """article_seq から (情報量条件, CTA条件) を返す（4群の唯一の判定元・D-0152）。

    余りの計算をここ以外に書かない。情報量条件だけが要るときは condition_for_seq()、
    CTA条件だけが要るときは cta_for_seq() を通す（どちらもこの関数の薄いラッパー）。
    """
    return CONDITION_BY_REMAINDER[int(article_seq) % 4]


def condition_for_seq(article_seq):
    """article_seqから情報量条件名だけを返す（低情報量条件／現行条件・D-0152）。"""
    return conditions_for_seq(article_seq)[0]


def cta_for_seq(article_seq):
    """article_seqからCTA条件名だけを返す（CTAあり／CTAなし・D-0152）。"""
    return conditions_for_seq(article_seq)[1]


# CTA文言を記事内で1枚ずつずらす歩幅。CTA_TEXTS が10件・歩幅3のため、
# 同一記事の pin1〜3 は必ず連続した別の添字になり、文言が重複しない。
CTA_TEXT_STRIDE = 3


def cta_text_for_seq(article_seq, pin_no=1):
    """CTA帯に焼き込む文言を CTA_TEXTS から機械的に選ぶ（D-0152・D-0157）。

    記事単位ではなくピン単位で選ぶ。同一記事の pin1〜3 は連続した添字になるため
    3枚とも別の文言になる。どの文言を使うかはAIが選ばず、
    article_seq と pin_no から決める（表記ゆれ防止・乱数は使わない）。

    pin_no を省略した場合は pin1 の文言を返す（引数を渡さない呼び出しの互換のため）。
    添字の計算はこの関数だけに置く。make-image-prompt.py 側で余りの計算や
    CTA_TEXTS への添字アクセスを複製しない。
    """
    index = (int(article_seq) * CTA_TEXT_STRIDE + (int(pin_no) - 1)) % len(CTA_TEXTS)
    return CTA_TEXTS[index]


def seq_for_slug(slug, rows=None):
    """台帳から slug の article_seq を引く。見つからない／数値でなければ None。"""
    if rows is None:
        rows = read_ledger()
    for r in rows:
        if r["slug"] == slug:
            try:
                return int(r["article_seq"])
            except (TypeError, ValueError):
                return None
    return None


def conditions_for_slug(slug, rows=None):
    """台帳から slug の (情報量条件, CTA条件) を返す。台帳に無ければ None。"""
    seq = seq_for_slug(slug, rows)
    return None if seq is None else conditions_for_seq(seq)


def condition_for_slug(slug, rows=None):
    """台帳から slug の情報量条件名を返す。台帳に無ければ None。"""
    conds = conditions_for_slug(slug, rows)
    return None if conds is None else conds[0]


def is_low_density(style):
    """型が低密度プールに含まれるか（D-0152）。未知の型は高密度扱いにしない＝Falseを返す。"""
    return IMAGE_STYLES.get(style) == DENSITY_LOW


def available_styles(rows, exclude_slug=None, condition=CONDITION_CURRENT):
    """今回選べる型の候補リストを返す。

    戻り値: (候補リスト, 除外に使った型の集合, 実際に適用したlookback)
      lookbackが STYLE_LOOKBACK より小さい場合は緩和が発生したことを意味する
      （0はプール全体を候補にしたケース）。

    低情報量条件（D-0152）では低密度4種のみを候補とし、「直近2記事で使った型を除外」の
    規則は適用しない（低密度プールが4種しかなく、直近2記事を除外すると候補が枯れて
    pin1〜3に別々の型を割り当てられなくなるため）。この場合のlookbackは None を返し、
    「除外規則そのものを適用していない」ことを緩和（0）と区別できるようにする。
    同一記事内でpin1〜3が重複しないことだけが条件になる。
    """
    if condition == CONDITION_LOW:
        return list(LOW_INFO_STYLES), set(), None
    for lookback in range(STYLE_LOOKBACK, 0, -1):
        used = recent_style_usage(rows, exclude_slug, lookback)
        candidates = [s for s in IMAGE_STYLES if s not in used]
        if len(candidates) >= MIN_CANDIDATES:
            return candidates, used, lookback
    return list(IMAGE_STYLES), set(), 0


def resolve_style(value):
    """型名（そのまま）または一覧番号（1〜12）を型名に解決する。"""
    value = value.strip()
    if value in IMAGE_STYLES:
        return value
    if value.isdigit() and 1 <= int(value) <= len(STYLE_NAMES):
        return STYLE_NAMES[int(value) - 1]
    listing = "\n".join(f"  {i + 1}. {s}" for i, s in enumerate(STYLE_NAMES))
    sys.exit(f"型名が候補プールにありません: {value}\n指定できる型（番号でも可）:\n{listing}")


def pick_combinations(article_seq):
    """article_seqを開始位置として、4枚(hero/pin1/pin2/pin3)分の軸の値を決める。"""
    combos = []
    for i, slot in enumerate(IMAGE_SLOTS):
        combo = {"image_type": slot}
        for axis, values in AXES.items():
            start = article_seq % len(values)
            combo[axis] = values[(start + i) % len(values)]
        combos.append(combo)
    return combos


def cmd_set_style(argv):
    """--set-style <slug> pin1=型名 pin2=型名 pin3=型名"""
    if len(argv) < 2:
        sys.exit('usage: pick-image-variation.py --set-style <slug> "pin1=<型名>" "pin2=<型名>" "pin3=<型名>"')
    slug = argv[0]

    assignments = {}
    for token in argv[1:]:
        if "=" not in token:
            sys.exit(f"指定の形式が不正です（pin1=型名 の形で書く）: {token}")
        slot, value = token.split("=", 1)
        slot = slot.strip()
        if slot not in PIN_SLOTS:
            sys.exit(f"型を記録できるのは pin1〜pin3 のみです（heroは対象外・D-0062）: {slot}")
        assignments[slot] = resolve_style(value)

    rows = read_ledger()
    targets = [r for r in rows if r["slug"] == slug and r["image_type"] in assignments]
    if not targets:
        sys.exit(f"台帳に {slug} のpin行が見つかりません（先に pick-image-variation.py {slug} を実行する）")

    for r in targets:
        r["image_style"] = assignments[r["image_type"]]
    write_ledger(rows)

    print(f"記事: {slug} の型を台帳に記録しました")
    for slot in PIN_SLOTS:
        if slot in assignments:
            print(f"  {slot}: {assignments[slot]}")
    recorded = {r["image_type"]: r["image_style"].strip() for r in rows if r["slug"] == slug and r["image_type"] in PIN_SLOTS}
    blanks = [s for s in PIN_SLOTS if not recorded.get(s)]
    if blanks:
        print(f"  ※未記録のスロットが残っています: {'・'.join(blanks)}")
    values = [v for v in recorded.values() if v]
    if len(values) != len(set(values)):
        print("  ※記事内で型が重複しています（check-pin-image-style.py でエラーになります）")
    print()
    print(f"確認: python site/scripts/check-pin-image-style.py {slug}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) >= 2 and sys.argv[1] == "--set-style":
        cmd_set_style(sys.argv[2:])
        return

    if len(sys.argv) != 2:
        sys.exit(
            "usage: pick-image-variation.py <slug>\n"
            '       pick-image-variation.py --set-style <slug> "pin1=<型名>" "pin2=<型名>" "pin3=<型名>"'
        )
    slug = sys.argv[1]

    rows = read_ledger()

    # 直前の実行が同じslugの4行であれば、再消費せずそのまま再表示する
    last4 = rows[-4:]
    if len(last4) == 4 and all(r["slug"] == slug for r in last4) and {r["image_type"] for r in last4} == set(IMAGE_SLOTS):
        print(f"（台帳の末尾が既に {slug} の4行のため、再消費せず再表示します）")
        condition, cta = conditions_for_seq(last4[0]["article_seq"])
        print_result(slug, last4, *available_styles(rows, exclude_slug=slug, condition=condition),
                     condition=condition, cta=cta)
        return

    prev_seq = int(rows[-1]["article_seq"]) if rows else -1
    article_seq = prev_seq + 1
    condition, cta = conditions_for_seq(article_seq)

    from datetime import date
    today = date.today().isoformat()

    # 型の候補は「今回の記事を除いた直近2記事」から計算する（追記より前に確定させる）。
    # 低情報量条件のときは直近記事による除外を行わず、低密度4種をそのまま候補にする（D-0152）。
    styles_info = available_styles(rows, exclude_slug=slug, condition=condition)

    combos = pick_combinations(article_seq)
    new_rows = []
    for combo in combos:
        new_rows.append({
            "article_seq": str(article_seq),
            "slug": slug,
            "image_type": combo["image_type"],
            "date": today,
            "angle": combo["angle"],
            "framing": combo["framing"],
            "text_position": combo["text_position"],
            "background": combo["background"],
            "image_style": "",  # AIが型を選定した後に --set-style で埋める（D-0062）
        })

    rows.extend(new_rows)
    # 保持上限を超えた分は古い記事から削除（4行単位＝記事単位で揃える）
    while len(rows) > MAX_ROWS:
        del rows[0:4]

    write_ledger(rows)
    print_result(slug, new_rows, *styles_info, condition=condition, cta=cta)


def print_result(slug, rows, candidates, used, lookback, condition=CONDITION_CURRENT, cta=CTA_NONE):
    candidate_text = "／".join(candidates)
    article_seq = rows[0]["article_seq"]
    remainder = int(article_seq) % 4
    print(f"■ 条件: {condition}／{cta}（article_seq={article_seq} を4で割った余り={remainder}・D-0152）")
    if cta == CTA_YES:
        cta_list = "／".join(
            "pin%d=「%s」" % (i, cta_text_for_seq(article_seq, i)) for i in (1, 2, 3)
        )
        print("  CTA帯をpin1〜3の3枚すべてに焼き込む。文言はピンごとに異なる（%s）"
              "（AIが選ばない・make-image-prompt.py が依頼文に自動で入れる）。" % cta_list)
        print("  CTA文言は --pinN-text の件数制限の対象外。見出し文言の件数は下記の条件どおりに渡す。")
    else:
        print("  CTA帯は入れない（依頼文にCTAの記述は一切入らない）。")
    if condition == CONDITION_LOW:
        print(f"  型は低密度{len(LOW_INFO_STYLES)}種のみから選ぶ。"
              f"1枚あたりの文言は{LOW_INFO_TEXT_MIN}〜{LOW_INFO_TEXT_MAX}件"
              "（make-image-prompt.py が強制する）。")
        print("  この条件では「直近2記事で使った型を除外」の規則は適用しない"
              "（候補が4種しかないため）。同一記事内でpin1〜3が重複しないことだけを守る。")
    else:
        print("  従来どおり。型は12種から直近2記事使用分を除外した候補を使い、"
              "1枚あたりの文言件数は make-image-prompt.py の既定（PIN_TEXT_MIN_COUNT〜PIN_TEXT_MAX_COUNT）のまま。")
    print()
    print(f"記事: {slug}（article_seq={article_seq}）")
    print()
    print("画像種別  アングル      フレーミング  テキスト配置  背景小物                  選択可能な型（pin1〜3のみ・この中から異なる3つを選ぶ）")
    print("-" * 120)
    for r in rows:
        style_col = candidate_text if r["image_type"] in PIN_SLOTS else "－（heroは型プール対象外・写真型を維持）"
        print(f"{r['image_type']:<8}  {r['angle']:<10}  {r['framing']:<10}  {r['text_position']:<10}  {r['background']:<22}  {style_col}")
    print()

    if lookback is None:
        print("直近記事による除外: 適用していません（低情報量条件のため・D-0152）")
        print("※低密度プールは4種しかないため、直近2記事を除外すると候補が枯れて選定が詰まります。"
              "同一記事内でpin1〜3が重複しないことだけを守ってください。")
    elif lookback == 0:
        print("直近記事で使用済みの型（参考）: 候補が足りないためプール全体を候補にしています")
        print("※緩和発生: 直近2記事・直近1記事のどちらで除外しても候補が3個未満になるため、除外なし（プール全体）で出しています")
    else:
        print(f"直近{lookback}記事で使用済みの型（除外済み・参考）: {'／'.join(sorted(used)) if used else '（記録なし）'}")
        if lookback < STYLE_LOOKBACK:
            print("※緩和発生: 直近2記事の除外では候補が3個未満になるため、直近1記事のみで除外しています")

    recorded = [(r["image_type"], r["image_style"].strip()) for r in rows if r["image_type"] in PIN_SLOTS and r["image_style"].strip()]
    if recorded:
        print("既に台帳へ記録済みの型: " + "、".join(f"{slot}={style}" for slot, style in recorded))

    print()
    print("次の手順（D-0062）:")
    print("  1. 記事内容に合わせて、上の候補からpin1・pin2・pin3に異なる型を1つずつ選ぶ")
    print("  2. 選んだ型に応じてChatGPTへの指示文を作り分ける（rules/image-generation-flow.md 1-3参照）")
    print("  3. 生成後に必ず次を実行して台帳へ記録する（記録漏れはcheck-pin-image-style.pyがエラー検知する）")
    print(f'     python site/scripts/pick-image-variation.py --set-style {slug} "pin1=<型名>" "pin2=<型名>" "pin3=<型名>"')


if __name__ == "__main__":
    main()
