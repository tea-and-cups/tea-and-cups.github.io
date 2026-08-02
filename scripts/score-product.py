"""商品リンク候補をスコアリングして順位づけする（D-0024）。

背景:
  旧基準（★4.0以上「かつ」レビュー20件以上の固定しきい値）は、条件を1つでも
  外すと「候補なし」になり、そこから先へ進めなくなる。実際 glass-cup-hikaku の
  2件（★4.63/8件・評価表示なし）で2週続けて代替探索が空振りし、Web検索・取得を
  10回近く回して成果ゼロという状態が起きた。探索が止まらないこと自体が
  トークンコストの主因なので、「常に順位はつく／ただし紹介に値するかは別に守る」
  スコアリング＋絶対フロア方式へ移行する。

  数値の判断はこのスクリプトに閉じ込め、LLM側では行わない。基準を思い出して
  比較する分の文脈消費が消え、判定も毎回同じ結果になる。

判定の作り:
  1. ベイズ加重平均 WR で「★5.0/3件」が「★4.3/300件」に勝つ不合理を消す
       WR = v/(v+m) * R + m/(v+m) * C     （m=20, C=3.8）
  2. レビュー件数は対数で頭打ちにする（件数稼ぎを効かせない）
  3. 価格は「カテゴリ内の中庸さ」を見る。候補が2件以上あれば中央値を自動算出し、
     1件しか渡していない/価格未記入なら価格の重みを他へ再配分する
  4. 絶対フロア（生の★が3.0未満／評価データが一切ない）は何点でも不採用
  5. スコア帯に応じて紹介文のトーンを指定する。基準を緩めた事実を隠さないため
     （CLAUDE.md 判断原則1・読者への誠実さ）

  出力の「表示用」R（実評価）・件数は、記事本文のスコアバッジ「★R（v件）」に
  そのまま使ってよい数値（試行運用・新規記事限定・D-0047）。「順位用」の
  加重評価WRは順位づけのための内部指標であり、実際の評価と食い違うことが
  あるため記事には書かない。

使い方:
  data/scoring-input.tsv に候補を書いてから、引数なしで実行する。

      python site/scripts/score-product.py

  引数に動的な値（商品名・評価値）を載せるとそのたびに一発限りの権限エントリが
  増えるため、入力はファイル経由に固定している（rules/command-execution.md 3）。

入力ファイルの書式（タブ区切り・`#` で始まる行はコメント）:
  商品名<TAB>評価<TAB>レビュー件数<TAB>販売元<TAB>ブランド<TAB>価格
    評価・レビュー件数: ページに表示がなければ空欄にする（0ではなく空欄）
    販売元: rakuten / amazon / asp
    ブランド: major（大手・公式）/ mid（中堅）/ unknown（無名・記載なし）
    価格: 円。空欄可
"""

import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INPUT_PATH = os.path.join(ROOT, "data", "scoring-input.tsv")

# --- パラメータ（strategy.md「商品選定基準」と対で管理する。変更時は両方を直す） ---

M_PRIOR = 20.0   # ベイズ加重の事前件数。旧基準のレビュー20件をここに移した
C_PRIOR = 3.8    # ベースライン評価。実データが溜まったら実測平均に置き換える
V_REF = 100.0    # レビュー件数がこの件数で満点。以降は加点しない

WEIGHTS = {"rating": 0.50, "volume": 0.20, "price": 0.15, "brand": 0.15}

# 販売元ごとの評価の甘辛補正。楽天は星が甘めに出やすいとされるが、
# 当メディアには実測データがないため初期値は0.0とする（根拠のない補正で
# 紹介トーンの判定が変わるのを避ける）。Amazon承認後、両モールに同一商品が
# 並んだ時点で実測して設定する。
SOURCE_ADJUST = {"rakuten": 0.0, "amazon": 0.0, "asp": 0.0}

BRAND_SCORE = {"major": 100.0, "mid": 50.0, "unknown": 0.0}

FLOOR_RATING = 3.0  # 生の評価がこれ未満なら何点でも不採用

TONE_BANDS = [
    (75.0, "積極", "「イチ押し」「高評価」等の積極表現を使ってよい"),
    (50.0, "中立", "中立表現にとどめる（「バランスの取れた選択肢」「この価格帯では手堅い」等）"),
    (0.0, "留保", "留保付き表現が必須（「まだレビュー件数は少ないですが」等）。誇張表現は禁止"),
]


def bayesian_rating(rating, reviews, source):
    """レビューの少なさを割り引いた評価値を返す。"""
    adjusted = rating - SOURCE_ADJUST.get(source, 0.0)
    return (reviews / (reviews + M_PRIOR)) * adjusted + (M_PRIOR / (reviews + M_PRIOR)) * C_PRIOR


def volume_score(reviews):
    return min(100.0, math.log10(reviews + 1) / math.log10(V_REF + 1) * 100.0)


def price_score(price, median):
    """中央値からの乖離を減点する。極端に高い/安い商品を上位に出さないため。"""
    if not median:
        return None
    return max(0.0, 100.0 - abs(price - median) / median * 100.0)


def score(product, median):
    """1商品を評価して {finalScore, breakdown, ...} を返す。純粋関数。"""
    rating = product["rating"]
    reviews = product["reviews"]

    # --- 絶対フロア ---
    if rating is None or reviews is None:
        return {"ok": False, "reason": "評価データなし（フロア割れ・不採用）", "final": None, "breakdown": {}}
    if rating < FLOOR_RATING:
        return {"ok": False, "reason": f"生の評価 {rating} が下限 {FLOOR_RATING} 未満（不採用）", "final": None, "breakdown": {}}

    wr = bayesian_rating(rating, reviews, product["source"])
    parts = {
        "rating": (wr - 1.0) / 4.0 * 100.0,
        "volume": volume_score(reviews),
        "brand": BRAND_SCORE[product["brand"]],
    }
    ps = price_score(product["price"], median) if product["price"] else None
    if ps is not None:
        parts["price"] = ps

    # 使える項目の重みだけで正規化する（価格が取れない場合に不利にならないように）
    total_weight = sum(WEIGHTS[k] for k in parts)
    final = sum(parts[k] * WEIGHTS[k] for k in parts) / total_weight

    for threshold, label, guidance in TONE_BANDS:
        if final >= threshold:
            tone, tone_note = label, guidance
            break

    return {"ok": True, "reason": "", "final": final, "wr": wr, "breakdown": parts, "tone": tone, "tone_note": tone_note}


def parse(path):
    products = []
    with open(path, encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            cols = [c.strip() for c in line.split("\t")]
            if len(cols) < 5:
                sys.exit(f"{lineno}行目: 列が足りません（商品名/評価/件数/販売元/ブランド[/価格]）: {line}")
            name, rating, reviews, source, brand = cols[:5]
            price = cols[5] if len(cols) > 5 else ""
            if brand not in BRAND_SCORE:
                sys.exit(f"{lineno}行目: ブランドは major/mid/unknown のいずれか: {brand}")
            products.append({
                "name": name,
                "rating": float(rating) if rating else None,
                "reviews": float(reviews.replace(",", "")) if reviews else None,
                "source": source,
                "brand": brand,
                "price": float(price.replace(",", "")) if price else None,
            })
    return products


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if not os.path.exists(INPUT_PATH):
        sys.exit(f"入力ファイルがありません: {INPUT_PATH}")

    products = parse(INPUT_PATH)
    if not products:
        sys.exit("候補が1件も書かれていません")

    prices = sorted(p["price"] for p in products if p["price"])
    median = None
    if len(prices) >= 2:
        mid = len(prices) // 2
        median = prices[mid] if len(prices) % 2 else (prices[mid - 1] + prices[mid]) / 2

    results = [(p, score(p, median)) for p in products]
    adopted = sorted([r for r in results if r[1]["ok"]], key=lambda r: r[1]["final"], reverse=True)
    rejected = [r for r in results if not r[1]["ok"]]

    print(f"候補 {len(products)} 件 / 価格中央値: {f'{median:,.0f}円' if median else '算出せず（価格2件未満）'}")
    print()
    print("順位  スコア  トーン  商品名")
    print("-" * 78)
    for i, (p, r) in enumerate(adopted, 1):
        print(f"{i:>3}   {r['final']:>5.1f}   {r['tone']:<4}   {p['name']}")
        b = r["breakdown"]
        detail = "  ".join(f"{k}={b[k]:.1f}" for k in ("rating", "volume", "price", "brand") if k in b)
        print(f"      └ 表示用（記事・スコアバッジに書いてよい数値）R={p['rating']:.2f}（{int(p['reviews'])}件）")
        print(f"      └ 順位用（内部のみ・記事に書かない）加重評価WR={r['wr']:.2f}  {detail}")
    if rejected:
        print()
        print("【不採用（絶対フロア割れ）】")
        for p, r in rejected:
            print(f"  × {p['name']}: {r['reason']}")
    if adopted:
        print()
        print(f"採用候補: {adopted[0][0]['name']}")
        print(f"紹介トーン: {adopted[0][1]['tone_note']}")


if __name__ == "__main__":
    main()
