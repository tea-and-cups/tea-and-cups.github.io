"""hero画像・Pin画像3枚（計4枚）の構図バリエーションを機械的に選ぶ（D-0034）。

背景:
  ChatGPT用の画像生成プロンプトを毎回AIが記事内容だけを見て組み立てると、
  「安全に通った過去の表現」を無意識に使い回してしまい、俯瞰・木製テーブル・
  生成りリネン・明朝体下部帯といった構図がほぼ全記事で固定化していた
  （経緯は reports/2026-08-01.md 参照）。
  数値の判断をscore-product.pyに閉じ込めているのと同じ考え方で、構図の選定も
  このスクリプトに閉じ込め、AIが頭の中で「そろそろ違うのを選ぼう」と判断しない
  ようにする。

判定の作り:
  各軸（アングル/フレーミング/テキスト配置/背景小物）ごとに、記事1本を処理する
  たびに1ずつ進む連番（article_seq）を開始位置として、軸の選択肢リストを
  ラウンドロビンで4枚（hero→pin1→pin2→pin3の順）に割り当てる。
    - 選択肢が4つの軸（アングル/テキスト配置/背景小物）: 1記事内で4枚とも
      別の値になる（重複なし）。
    - 選択肢が2つの軸（フレーミング）: 1記事内は2枚ずつになる（重複はゼロに
      できないため、偏りなく交互に割り当てる）。
  article_seqは記事ごとに1ずつ進むため、次の記事では開始位置がずれ、
  どの画像がどの値になるかも一緒にローテーションする（同じ組み合わせが
  毎回同じ位置に固定されない）。乱数は使わない＝同じ台帳状態からは常に
  同じ結果になる。

使い方:
  python site/scripts/pick-image-variation.py <slug>
      台帳（data/image-variation.tsv）に4行（hero/pin1/pin2/pin3）を追記し、
      選んだ組み合わせを標準出力に表示する。
      同じslugを続けて実行した場合（同一セッション内の再実行等）は、台帳の
      末尾4行がそのslugのものであればそれをそのまま再表示するだけで、
      二重に消費しない。
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LEDGER_PATH = os.path.join(ROOT, "data", "image-variation.tsv")

HEADER_COMMENT = """# image-variation.tsv — hero/Pin画像の構図バリエーション台帳
#
# site/scripts/pick-image-variation.py が読み書きする。手で編集しない。
# 1行 = 画像1枚。列: article_seq(連番) / slug / image_type(hero|pin1|pin2|pin3) / date / angle / framing / text_position / background
# 保持件数の上限は8記事分（32行）。超えた分は同スクリプトが古い記事から自動で削除する（CLAUDE.md 10節・D-0031の肥大化防止原則）。
#
"""

COLUMNS = ["article_seq", "slug", "image_type", "date", "angle", "framing", "text_position", "background"]

IMAGE_SLOTS = ["hero", "pin1", "pin2", "pin3"]

AXES = {
    "angle": ["俯瞰", "斜め45度", "正面", "手元アップ"],
    "framing": ["引き", "寄り"],
    "text_position": ["上部帯", "下部帯", "中央", "テキストなし"],
    "background": ["木目テーブル＋リネン", "大理石", "窓辺の自然光", "布ナプキン＋陶器小物"],
}

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
            if cols == COLUMNS:
                continue  # ヘッダー行
            if len(cols) != len(COLUMNS):
                continue
            rows.append(dict(zip(COLUMNS, cols)))
    return rows


def write_ledger(rows):
    with open(LEDGER_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(HEADER_COMMENT)
        f.write("\t".join(COLUMNS) + "\n")
        for r in rows:
            f.write("\t".join(r[c] for c in COLUMNS) + "\n")


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


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) != 2:
        sys.exit("usage: pick-image-variation.py <slug>")
    slug = sys.argv[1]

    rows = read_ledger()

    # 直前の実行が同じslugの4行であれば、再消費せずそのまま再表示する
    last4 = rows[-4:]
    if len(last4) == 4 and all(r["slug"] == slug for r in last4) and {r["image_type"] for r in last4} == set(IMAGE_SLOTS):
        print(f"（台帳の末尾が既に {slug} の4行のため、再消費せず再表示します）")
        print_result(slug, last4)
        return

    prev_seq = int(rows[-1]["article_seq"]) if rows else -1
    article_seq = prev_seq + 1

    from datetime import date
    today = date.today().isoformat()

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
        })

    rows.extend(new_rows)
    # 保持上限を超えた分は古い記事から削除（4行単位＝記事単位で揃える）
    while len(rows) > MAX_ROWS:
        del rows[0:4]

    write_ledger(rows)
    print_result(slug, new_rows)


def print_result(slug, rows):
    print(f"記事: {slug}（article_seq={rows[0]['article_seq']}）")
    print()
    print("画像種別  アングル      フレーミング  テキスト配置  背景小物")
    print("-" * 70)
    for r in rows:
        print(f"{r['image_type']:<8}  {r['angle']:<10}  {r['framing']:<10}  {r['text_position']:<10}  {r['background']}")


if __name__ == "__main__":
    main()
