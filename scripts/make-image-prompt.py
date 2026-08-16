# -*- coding: utf-8 -*-
"""hero・Pin画像（pin1〜3）のChatGPT用依頼文を組み立てる（D-0126）。

背景:
  依頼文をその場で毎回組み立てると、寸法・比率・アラビア数字指定・ブランドロゴ禁止等の
  固定要素の指定漏れが起き、ChatGPT側の生成物がやり直しになり、Chrome連携ツールの
  往復（トークン消費の主因）が増えていた（reports/2026-08-15-5.md の実測調査）。
  このスクリプトは「そのまま貼れる依頼文」を機械的に組み立てることで、指定漏れそのものを
  無くす。構図4軸（アングル/フレーミング/テキスト配置/背景小物）とPin1〜3の「型」の選定は
  従来どおり pick-image-variation.py（および --set-style での記録）で行う。本スクリプトは
  それを読み取って依頼文に反映するだけで、選定ロジックは持たない。

型の正本:
  data/image-variation.tsv（pick-image-variation.py が読み書きする台帳）の image_style列。
  このスクリプトは新しい管理ファイルを作らず、read_ledger() 経由でこの台帳のみを読む。

寸法・比率の根拠（実測・reports/2026-08-15-5.md）:
  hero: site/scripts/hero-to-webp.py の TARGET=(1400, 735) がWebP変換後の正規サイズ
        （D-0020で確定済みの値。ChatGPT生成直後の実寸ではなく変換後の最終値）。
  pin : output/Pin-images/ 配下の直近実測で、pin108〜119の12枚は 1024x1536（比率2:3）で
        一貫していた。pin120〜122（2026-08-15）はプロンプトで異なる比率（四対五等）を
        指定したためズレていた（1122x1402／1003x1568）。本スクリプトは実測で最も長く
        安定していた 2:3 を正規値として毎回のプロンプトに固定する。

ChatGPTへのプロンプトはASCII文字を含めない規約（rules/image-generation-flow.md 2節3）が
あるため、寸法・比率の数値は漢数字で表記する（本スクリプト内でアラビア数字→漢数字に変換する。
「画像内の数字はアラビア数字で」という指示文自体は日本語の指示文であり、プロンプトに含める
文言としてASCII規約に抵触しない）。

型ごとの指示方針（TYPE_GUIDANCE）は rules/image-generation-flow.md 1-3節の表と重複させず、
このスクリプトを正本とする（rules側は表の型名一覧のみ残し、指示文言はここを参照する形にした。
D-0126）。型の候補プール自体（型名の一覧）は pick-image-variation.py の IMAGE_STYLES を正本と
し、ここでは複製しない。

ランキング型の順位ラベル（D-0144）:
  「ランキング」型は順位の枠だけを描かせると、ChatGPT側が空欄・破線の記入欄や
  架空のブランド名を描き足す生成物になりやすかった。そのため pin1〜3のいずれかが
  ランキング型のときは --ranking-labels で1位〜3位に焼き込む文言（3件・各10文字以内）を
  必須にし、プロンプトへそのまま埋め込む。ラベルを用意できない場合は
  pick-image-variation.py --set-style で別の型に選び直す。

使い方:
  python site/scripts/make-image-prompt.py <slug>
  python site/scripts/make-image-prompt.py <slug> --ranking-labels "香り重視,毎日飲む用,ミルクティー向き"
"""

import importlib.util
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

_spec = importlib.util.spec_from_file_location(
    "pick_image_variation", os.path.join(SCRIPT_DIR, "pick-image-variation.py")
)
piv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(piv)


# --- 漢数字変換（プロンプト内でASCII数字を使わないための表記。D-0126） ---
_KANJI_DIGITS = "〇一二三四五六七八九"


def to_kanji(n):
    """0〜9999の整数を漢数字表記に変換する（十/百/千の頭の「一」は省略する標準表記）。"""
    if n < 0 or n > 9999:
        raise ValueError("to_kanjiは0〜9999のみ対応: %r" % (n,))
    if n == 0:
        return _KANJI_DIGITS[0]
    s = ""
    for unit_name, unit_val in (("千", 1000), ("百", 100), ("十", 10)):
        d, n = divmod(n, unit_val)
        if d > 0:
            s += unit_name if d == 1 else (_KANJI_DIGITS[d] + unit_name)
    if n > 0:
        s += _KANJI_DIGITS[n]
    return s


# --- 実測にもとづく正規寸法・比率（作業前の確認3・reports/2026-08-15-5.md） ---
HERO_TARGET_W, HERO_TARGET_H = 1400, 735  # hero-to-webp.py TARGET（D-0020）
HERO_RATIO_W, HERO_RATIO_H = 40, 21  # 1400:735を約分（gcd=35）

PIN_TARGET_W, PIN_TARGET_H = 1024, 1536  # 実測（pin108〜119・12枚で一貫）
PIN_RATIO_W, PIN_RATIO_H = 2, 3  # 1024:1536を約分（gcd=512）


def hero_dimension_text():
    return (
        "画像の比率は縦横{rw}対{rh}にする（配置前に縦{h}・横{w}ピクセルのWebPへ変換するため、"
        "その比率に合わせる）。"
    ).format(
        rw=to_kanji(HERO_RATIO_H), rh=to_kanji(HERO_RATIO_W),
        h=to_kanji(HERO_TARGET_H), w=to_kanji(HERO_TARGET_W),
    )


def pin_dimension_text():
    return (
        "画像は縦長の比率{rh}対{rw}にする（目安は縦{h}・横{w}ピクセル程度）。"
    ).format(
        rh=to_kanji(PIN_RATIO_H), rw=to_kanji(PIN_RATIO_W),
        h=to_kanji(PIN_TARGET_H), w=to_kanji(PIN_TARGET_W),
    )


# --- rules/image-generation-flow.md にある既存の固定要素（正本はこのファイル・D-0126） ---
BRAND_LOGO_BAN = (
    "実在のブランドを想起させるロゴや文字は絶対に描かない。無地でロゴや文字を一切入れない。"
)

DIGIT_RULE = "画像内の数字はすべてアラビア数字で表記し、漢数字は使わない。"

TEXT_POSITION_LABEL = {"上部帯": "画像上部", "下部帯": "画像下部", "中央": "画像中央"}


def text_overlay_instruction(text_position):
    pos = TEXT_POSITION_LABEL.get(text_position, text_position)
    return (
        "{pos}に、実際の見出し文言（記事タイトルまたはピン投稿文の要点から作った短い日本語の"
        "コピー）を白抜き等の読みやすい文字で焼き込む。文字を入れない構図のみの仕上げは不可。"
        "見出し文言: 《ここに見出し文言を入れる》"
    ).format(pos=pos)


def background_phrase(value):
    """背景小物の軸の値を、曖昧語回避（rules/image-generation-flow.md 1節）を適用した表現に変換する。"""
    if "布ナプキン" in value:
        note = "（「布ナプキン」は多義語のため、食器用のふきん・ディッシュクロス等キッチン用途と一意にわかる語で指示する）"
        return value.replace("布ナプキン", "食器用のふきん") + note
    return value


AXIS_LABEL = {"angle": "アングル", "framing": "フレーミング", "text_position": "テキスト配置", "background": "背景小物"}


def axis_summary(row):
    return "アングル={angle}／フレーミング={framing}／背景小物={background}".format(
        angle=row["angle"], framing=row["framing"], background=background_phrase(row["background"]),
    )


# --- ランキング型の順位ラベル（D-0144） ---
RANKING_KEY = "ランキング"
RANKING_LABEL_COUNT = 3
RANKING_LABEL_MAX_LEN = 10
RANKING_LABELS_OPT = "--ranking-labels"
RANKING_LABELS_EXAMPLE = '%s "香り重視,毎日飲む用,ミルクティー向き"' % RANKING_LABELS_OPT


def ranking_labels_error(detail):
    """順位ラベル関連のエラーを標準エラー出力へ出して exit 1 する（D-0144）。"""
    lines = [
        "【エラー】%s" % detail,
        "ランキング型のPin画像には、一位〜三位に焼き込む順位ラベルが%d件必要です"
        "（各%d文字以内・画像内に収まらない長さを避けるため）。" % (RANKING_LABEL_COUNT, RANKING_LABEL_MAX_LEN),
        "記述例: python site/scripts/make-image-prompt.py <slug> %s" % RANKING_LABELS_EXAMPLE,
        "ラベルは実在のブランド名ではなく、特徴を表す語（例: 香り重視／毎日飲む用）にしてください。",
        "ラベルを用意できない場合は、次を打ち直してランキング以外の型へ変更してかまいません:",
        '  python site/scripts/pick-image-variation.py --set-style <slug> "pin1=<型名>" "pin2=<型名>" "pin3=<型名>"',
    ]
    sys.stderr.write("\n".join(lines) + "\n")
    sys.exit(1)


# --- 型ごとの指示方針（rules/image-generation-flow.md 1-3節の表を正本としてここへ一本化。D-0126） ---
TYPE_GUIDANCE = {
    "写真ヒーロー": "物撮り・情景写真として、heroと同様の方向性で仕上げる。",
    "比較グリッド": "二〜四項目を並べたグリッド／表形式にする。各項目にラベルと短い説明を付ける。",
    "手順図解": "三〜五ステップを段組みで示す。各段に番号とキャプションを付ける。",
    "チェックリスト": "三〜六項目のチェックボックス風レイアウトにする。",
    "ビフォーアフター": "左右または上下で対比構造にする。",
    "Q&A形式": "質問と回答を吹き出し等で対比させる。",
    "ポイント整理": "記事の要点を三〜四個の箇条書き風レイアウトで見せる。",
    # ランキング型は渡された順位ラベル（--ranking-labels）を埋め込む形にする（D-0144）。
    # 他の型と違い、この値は format() 用のテンプレートであり、そのままは使わない
    # （埋め込みは ranking_guidance() が行う）。
    "ランキング": (
        "一位〜三位の順位構造（番付形式）にする。"
        "一位には「{label1}」、二位には「{label2}」、三位には「{label3}」という文言を、"
        "それぞれの順位の枠内に読みやすい文字で焼き込む。"
        "空欄・破線・点線など「記入欄が空のまま」に見える表現は作らない。"
        "指定した三つの文言以外の説明文や商品名・ブランド名を勝手に描き足さない。"
    ),
    "数字訴求型": "統計・数字を大きく見せるインフォグラフィック風にする。",
    "用語解説型": "辞書・用語集ふうのレイアウトにする。",
    "シーン別ガイド": "用途・シチュエーション別に分岐したレイアウトにする。",
    "相関図フローチャート": "要素同士の関係性を線・矢印で示す図にする。",
}


def build_hero_prompt(row):
    lines = [
        "紅茶ブログのhero画像を一枚作成してください。",
        axis_summary(row) + "の構図で、物撮りまたは情景写真として仕上げてください。",
        text_overlay_instruction(row["text_position"]),
        BRAND_LOGO_BAN,
        DIGIT_RULE,
        hero_dimension_text(),
    ]
    return "\n".join(lines)


def is_ranking(style):
    """型名にランキングが含まれるか（D-0144）。"""
    return RANKING_KEY in style


def ranking_guidance(labels):
    return TYPE_GUIDANCE[RANKING_KEY].format(label1=labels[0], label2=labels[1], label3=labels[2])


def build_pin_prompt(row, style, ranking_labels=None):
    if is_ranking(style):
        guidance = ranking_guidance(ranking_labels)
    else:
        guidance = TYPE_GUIDANCE.get(style)
    if guidance is None:
        print("型ごとの指示方針が未定義です（TYPE_GUIDANCEにない型）: %s" % style)
        sys.exit(1)
    lines = [
        "紅茶ブログのPin画像を一枚作成してください。型は「%s」です。" % style,
        guidance,
        axis_summary(row) + "を反映してください。",
        text_overlay_instruction(row["text_position"]),
        BRAND_LOGO_BAN,
        DIGIT_RULE,
        pin_dimension_text(),
    ]
    return "\n".join(lines)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    argv = sys.argv[1:]
    raw_labels = None
    if RANKING_LABELS_OPT in argv:
        i = argv.index(RANKING_LABELS_OPT)
        if i + 1 >= len(argv):
            ranking_labels_error("%s の値が指定されていません。" % RANKING_LABELS_OPT)
        raw_labels = argv[i + 1]
        del argv[i:i + 2]

    if len(argv) != 1:
        print('usage: make-image-prompt.py <slug> [%s "ラベル1,ラベル2,ラベル3"]' % RANKING_LABELS_OPT)
        sys.exit(1)
    slug = argv[0]

    rows = piv.read_ledger()
    by_type = {r["image_type"]: r for r in rows if r["slug"] == slug and r["image_type"] in piv.IMAGE_SLOTS}

    missing = [s for s in piv.IMAGE_SLOTS if s not in by_type]
    if missing:
        print("台帳（data/image-variation.tsv）に %s の行がありません: %s" % (slug, "・".join(missing)))
        print("先に python site/scripts/pick-image-variation.py %s を実行してください。" % slug)
        sys.exit(1)

    styles = {s: by_type[s]["image_style"].strip() for s in piv.PIN_SLOTS}
    blanks = [s for s in piv.PIN_SLOTS if not styles[s]]
    if blanks:
        print("型（image_style）が未記録です: %s" % "・".join(blanks))
        print("先に型を選定し、次を実行してから再実行してください:")
        print('  python site/scripts/pick-image-variation.py --set-style %s "pin1=<型名>" "pin2=<型名>" "pin3=<型名>"' % slug)
        sys.exit(1)

    values = [styles[s] for s in piv.PIN_SLOTS]
    if len(set(values)) != len(values):
        dupes = sorted({v for v in values if values.count(v) > 1})
        print("pin1〜3の型が重複しています（重複した型: %s）。" % "／".join(dupes))
        print("台帳の型選定をやり直してから再実行してください（同一記事内で異なる3つの型が必要）。")
        sys.exit(1)

    # --- ランキング型の順位ラベル検証（D-0144・プロンプトを1行も出力する前に判定する） ---
    ranking_slots = [s for s in piv.PIN_SLOTS if is_ranking(styles[s])]
    ranking_labels = None
    if ranking_slots:
        if raw_labels is None:
            ranking_labels_error(
                "%s がランキング型（%s）ですが、%s が指定されていません。"
                % ("・".join(ranking_slots), "／".join(styles[s] for s in ranking_slots), RANKING_LABELS_OPT)
            )
        ranking_labels = [v.strip() for v in raw_labels.split(",")]
        if len(ranking_labels) != RANKING_LABEL_COUNT or any(not v for v in ranking_labels):
            ranking_labels_error(
                "%s の値が%d件ちょうどではありません（受け取った値: %d件）。"
                % (RANKING_LABELS_OPT, RANKING_LABEL_COUNT, len(ranking_labels))
            )
        too_long = [v for v in ranking_labels if len(v) > RANKING_LABEL_MAX_LEN]
        if too_long:
            ranking_labels_error(
                "%d文字を超えるラベルがあります: %s"
                % (RANKING_LABEL_MAX_LEN, "／".join("%s（%d文字）" % (v, len(v)) for v in too_long))
            )
    # ランキング型が無い場合、--ranking-labels は指定されていても無視する（D-0144(4)）

    print("--- hero ---")
    print(build_hero_prompt(by_type["hero"]))
    print()
    for slot in piv.PIN_SLOTS:
        print("--- %s ---" % slot)
        print(build_pin_prompt(by_type[slot], styles[slot], ranking_labels))
        print()


if __name__ == "__main__":
    main()
