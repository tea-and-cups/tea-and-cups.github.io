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

# Pin画像（pin1〜3）の型候補プール（D-0062）。
# 増減する場合はこのリストだけを直す（他のロジックはすべてここを参照する）。
IMAGE_STYLES = [
    "写真ヒーロー",          # 物撮り・情景写真
    "比較グリッド",          # 2〜4項目を並列表示
    "手順図解",              # ステップ形式
    "チェックリスト",
    "ビフォーアフター",      # 対比構造
    "Q&A形式",
    "ポイント整理",          # 要点まとめ
    "ランキング",            # 番付形式
    "数字訴求型",            # 統計・数字を大きく見せる
    "用語解説型",            # 辞書・用語集ふう
    "シーン別ガイド",        # 用途・シチュエーション別に分岐
    "相関図フローチャート",  # 要素同士の関係性を線・矢印で示す
]

STYLE_LOOKBACK = 2   # 型の重複除外に使う直近記事数
MIN_CANDIDATES = 3   # pin1〜3に別々の型を割り当てるために最低限必要な候補数

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


def available_styles(rows, exclude_slug=None):
    """今回選べる型の候補リストを返す。

    戻り値: (候補リスト, 除外に使った型の集合, 実際に適用したlookback)
      lookbackが STYLE_LOOKBACK より小さい場合は緩和が発生したことを意味する
      （0はプール全体を候補にしたケース）。
    """
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
    if value.isdigit() and 1 <= int(value) <= len(IMAGE_STYLES):
        return IMAGE_STYLES[int(value) - 1]
    listing = "\n".join(f"  {i + 1}. {s}" for i, s in enumerate(IMAGE_STYLES))
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
        print_result(slug, last4, *available_styles(rows, exclude_slug=slug))
        return

    prev_seq = int(rows[-1]["article_seq"]) if rows else -1
    article_seq = prev_seq + 1

    from datetime import date
    today = date.today().isoformat()

    # 型の候補は「今回の記事を除いた直近2記事」から計算する（追記より前に確定させる）
    styles_info = available_styles(rows, exclude_slug=slug)

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
    print_result(slug, new_rows, *styles_info)


def print_result(slug, rows, candidates, used, lookback):
    candidate_text = "／".join(candidates)
    print(f"記事: {slug}（article_seq={rows[0]['article_seq']}）")
    print()
    print("画像種別  アングル      フレーミング  テキスト配置  背景小物                  選択可能な型（pin1〜3のみ・この中から異なる3つを選ぶ）")
    print("-" * 120)
    for r in rows:
        style_col = candidate_text if r["image_type"] in PIN_SLOTS else "－（heroは型プール対象外・写真型を維持）"
        print(f"{r['image_type']:<8}  {r['angle']:<10}  {r['framing']:<10}  {r['text_position']:<10}  {r['background']:<22}  {style_col}")
    print()

    if lookback == 0:
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
