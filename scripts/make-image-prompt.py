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

Pin画像に焼き込む文言の必須指定（D-0148）:
  画像内テキストをChatGPTの自律生成に任せると本文と食い違い、quality-reviewerの2回目往復と
  Pin画像の作り直しを招いていた（対象期間8記事中5記事で発生）。そのため pin1〜3それぞれに
  --pin1-text / --pin2-text / --pin3-text で「その1枚に描く文言のすべて」を渡すことを必須に
  する。1つでも未指定・制約違反があればプロンプトを一切出力せず exit 1 で終わる。
  文言は全角の縦棒「｜」で区切る（PowerShell対策として半角の縦棒も受け付ける）。
  制約は1枚あたり1〜6件・1件あたり30文字以内（低情報量条件の記事は1〜2件・後述）。
  ランキング型のPinに限り、渡された文言を
  順位ラベルとして扱い、追加でちょうど3件・各10文字以内を課す（旧 --ranking-labels の
  役割はここへ統合した。同じ「画像内文言」を2系統の引数で管理すると片方が腐るため・
  D-0126と同じ理由）。

条件による分岐の強制（D-0152・情報量×CTAの4群）:
  対象記事が属する群は article_seq を4で割った余りで決まる。判定そのものは
  pick-image-variation.py が正本で、ここでは piv.conditions_for_slug() /
  piv.cta_text_for_seq() / piv.is_low_density() / piv.LOW_INFO_STYLES を呼ぶだけにする
  （余りの計算を2箇所に持たせない）。

  情報量が「少なめ」の群（低情報量条件）は、次を満たさない限りプロンプトを一切出力せず
  exit 1 で終わる。
    - --pin1-text / --pin2-text / --pin3-text が各1〜2件であること
    - pin1〜3に選ばれた型が3つとも低密度プールに含まれること

  CTAありの群は、pin1〜3の3枚すべての依頼文にCTA帯の指示（CTA_BAND_RULES）を足す。
  1枚だけに入れる方式は取らない（同一記事内でCTAあり・なしが混在すると、ボードと
  スロットの違いが条件差に混ざるため）。CTA文言は piv.CTA_TEXTS（件数は同定数側で定義）から article_seq で
  機械的に選び、自由入力は受け付けない（表記ゆれ防止）。
  **CTA文言は --pinN-text の件数制限の対象外**（見出しとCTAは役割が異なり、件数に含めると
  見出しが入らなくなるため）。CTAなしの群の依頼文にはCTAの記述が一切入らない。

使い方:
  python site/scripts/make-image-prompt.py <slug>
    --pin1-text "文言A｜文言B" --pin2-text "文言C" --pin3-text "文言D｜文言E｜文言F"
"""

import importlib.util
import os
import re
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


_ASCII_DIGITS = "0123456789"


def _digits_to_kanji(digits):
    n = int(digits)
    if n <= 9999:
        return to_kanji(n)
    return "".join(_KANJI_DIGITS[int(d)] for d in digits)


def kanjify_digits(text):
    """文字列中の半角アラビア数字の並びを漢数字へ変換する（台帳由来の値の全角化・D-0149）。

    台帳ファイル自体は書き換えず、依頼文へ埋め込む直前にのみ適用する。
    例:「斜め45度」→「斜め四十五度」。
    """
    out = []
    buf = ""
    for ch in text:
        if ch in _ASCII_DIGITS:
            buf += ch
        else:
            if buf:
                out.append(_digits_to_kanji(buf))
                buf = ""
            out.append(ch)
    if buf:
        out.append(_digits_to_kanji(buf))
    return "".join(out)


# --- 実測にもとづく正規寸法・比率（作業前の確認3・reports/2026-08-15-5.md） ---
HERO_TARGET_W, HERO_TARGET_H = 1400, 735  # hero-to-webp.py TARGET（D-0020）
HERO_RATIO_W, HERO_RATIO_H = 40, 21  # 1400:735を約分（gcd=35）

PIN_TARGET_W, PIN_TARGET_H = 1024, 1536  # 実測（pin108〜119・12枚で一貫）
PIN_RATIO_W, PIN_RATIO_H = 2, 3  # 1024:1536を約分（gcd=512）


def hero_dimension_text():
    return (
        "画像の比率は縦横{rw}対{rh}にする（配置前に縦{h}・横{w}ピクセルへ変換するため、"
        "その比率に合わせる）。"
    ).format(
        rw=to_kanji(HERO_RATIO_H), rh=to_kanji(HERO_RATIO_W),
        h=to_kanji(HERO_TARGET_H), w=to_kanji(HERO_TARGET_W),
    )


def pin_dimension_text():
    return (
        "必ず縦長で作る（縦の辺が横の辺より長い）。横長や正方形は不可。"
        "比率は{rh}対{rw}にする（目安は縦{h}・横{w}ピクセル程度）。"
    ).format(
        rh=to_kanji(PIN_RATIO_H), rw=to_kanji(PIN_RATIO_W),
        h=to_kanji(PIN_TARGET_H), w=to_kanji(PIN_TARGET_W),
    )


# --- rules/image-generation-flow.md にある既存の固定要素（正本はこのファイル・D-0126） ---
BRAND_LOGO_BAN = (
    "実在のブランドを想起させるロゴや文字は絶対に描かない。無地でロゴや文字を一切入れない。"
)

DIGIT_RULE = "画像内の数字はすべてアラビア数字で表記し、漢数字は使わない。"

# 指定文言以外を描き足させないための固定文（Pin用依頼文に必ず入れる・D-0148）。全角のみで組み立てる
# （rules/image-generation-flow.md 規約3・ChatGPT入力欄でASCIIが脱落するため）。
TEXT_STRICT_RULES = [
    "画像内に描く文字は、ここで指定した文言のみとする。",
    "指定した文言以外の文字・数字・記号を描き足さない"
    "（説明文・商品名・ブランド名・空欄や破線の記入欄・飾りの英字も含む）。",
    "文言は一字一句そのまま使い、言い換え・要約・語尾の変更をしない。",
]

# CTAありの群で使う版。CTA帯の文言も画像内に描くため、1行目だけを差し替える（D-0152）。
TEXT_STRICT_RULES_WITH_CTA = [
    "画像内に描く文字は、ここで指定した見出しの文言と、あとで指定する誘導の帯の文言のみとする。",
] + TEXT_STRICT_RULES[1:]


def text_strict_rules(has_cta):
    return TEXT_STRICT_RULES_WITH_CTA if has_cta else TEXT_STRICT_RULES


# CTA帯の意匠・文言指示（D-0152）。CTAありの群のPin依頼文にだけ足す。
# 全角のみで組み立てる（出力直前のASCII検査に通す必要があるため・D-0149）。
CTA_BAND_RULES = [
    "画像の下部に、読者を記事へ誘導するための帯を一つだけ配置する。",
    "帯の中に焼き込む文言は「{text}」のみとする。一字一句そのまま使い、言い換え・要約・語尾の変更をしない。",
    "帯の地の色は、濃い茶色（＃４Ａ３４２Ａ）の一色で塗りつぶす。"
    "背景がどんな色であってもこの色を変えない。透過・半透明にしない。",
    "帯の中の文字の色は白（＃ＦＦＦＦＦＦ）にする。",
    "帯の外周すべてに、クリーム色（＃Ｆ５ＥＦＥ６）の太さ二ピクセルの枠線を入れる。"
    "背景が茶系でも帯の輪郭が消えないようにするための枠線であり、省略しない。",
    "帯は角丸の帯またはボタン状の形にし、周囲の余白と区別がつくようにする。",
    "帯の下端と画像の下辺のあいだに、画像の高さの四パーセントぶんの余白を必ず空ける。"
    "帯を画像の最も下の辺に接触させない。",
    "帯の中には、指定した文言以外の文字・数字・記号を描き足さない（矢印・指の形・飾りの英字も含む）。",
    "帯は見出しの文言と重ならない位置に置き、見出しの文言と帯の文言がどちらも読める大きさにする。",
]


def cta_instruction(cta_text):
    return "\n".join(line.format(text=cta_text) for line in CTA_BAND_RULES)


# heroは横長でないと配置時の中央クロップで上部の見出し文言が切れる（hero-to-webp.pyのガード・D-0148）。
HERO_LANDSCAPE_RULE = "必ず横長で作る（横の辺が縦の辺より長い）。縦長や正方形は不可。"

TEXT_POSITION_LABEL = {"上部帯": "画像上部", "下部帯": "画像下部", "中央": "画像中央"}


def text_overlay_instruction(text_position):
    pos = kanjify_digits(TEXT_POSITION_LABEL.get(text_position, text_position))
    return (
        "{pos}に、実際の見出し文言（記事タイトルまたはピン投稿文の要点から作った短い日本語の"
        "コピー）を白抜き等の読みやすい文字で焼き込む。文字を入れない構図のみの仕上げは不可。"
        "見出し文言：《ここに見出し文言を入れる》"
    ).format(pos=pos)


def pin_text_instruction(text_position, texts, ranking, has_cta=False):
    """渡された文言をそのまま列挙する焼き込み指示を作る（数字は漢数字・ASCII規約。D-0148）。"""
    if ranking:
        head = "各順位の枠内に、次の文言を白抜き等の読みやすい文字で焼き込む。"
    else:
        pos = kanjify_digits(TEXT_POSITION_LABEL.get(text_position, text_position))
        head = "{pos}に、次の文言を白抜き等の読みやすい文字で焼き込む。".format(pos=pos)
    lines = [head + "文字を入れない構図のみの仕上げは不可。"]
    for i, t in enumerate(texts, 1):
        lines.append("文言その{n}：「{t}」".format(n=to_kanji(i), t=t))
    lines.extend(text_strict_rules(has_cta))
    return "\n".join(lines)


def background_phrase(value):
    """背景小物の軸の値を、曖昧語回避（rules/image-generation-flow.md 1節）を適用した表現に変換する。"""
    if "布ナプキン" in value:
        note = "（「布ナプキン」は多義語のため、食器用のふきん・ディッシュクロス等キッチン用途と一意にわかる語で指示する）"
        return value.replace("布ナプキン", "食器用のふきん") + note
    return value


AXIS_LABEL = {"angle": "アングル", "framing": "フレーミング", "text_position": "テキスト配置", "background": "背景小物"}


def axis_summary(row):
    return "アングル＝{angle}／フレーミング＝{framing}／背景小物＝{background}".format(
        angle=kanjify_digits(row["angle"]),
        framing=kanjify_digits(row["framing"]),
        background=kanjify_digits(background_phrase(row["background"])),
    )


# --- Pin画像に焼き込む文言（--pinN-text・旧 --ranking-labels の統合先・D-0148） ---
RANKING_KEY = "ランキング"
RANKING_LABEL_COUNT = 3
RANKING_LABEL_MAX_LEN = 10

PIN_TEXT_SEP_FULL = "｜"  # 正規の区切り（全角）
PIN_TEXT_SEP_HALF = "|"   # PowerShell対策で受け付ける半角
PIN_TEXT_MAX_COUNT = 6
PIN_TEXT_MIN_COUNT = 1
PIN_TEXT_MAX_LEN = 30
PIN_TEXT_EXAMPLE = (
    'python site/scripts/make-image-prompt.py <slug> '
    '--pin1-text "雨の日の一杯｜香りで気分転換" --pin2-text "淹れる前と後" '
    '--pin3-text "茶葉｜湯温｜蒸らし時間"'
)


def pin_text_opt(slot):
    """スロット名（pin1等）に対応するオプション名を返す。"""
    return "--%s-text" % slot


def pin_text_error(detail):
    """画像内文言（--pinN-text）関連のエラーを標準エラーへ出して exit 1 する（D-0148）。"""
    lines = [
        "【エラー】%s" % detail,
        "Pin画像に焼き込む文言は pin1〜pin3 のすべてで指定が必須です"
        "（1枚あたり%d〜%d件・1件あたり%d文字以内。区切りは全角の縦棒「%s」）。"
        % (PIN_TEXT_MIN_COUNT, PIN_TEXT_MAX_COUNT, PIN_TEXT_MAX_LEN, PIN_TEXT_SEP_FULL),
        "ランキング型のPinに限り、順位ラベルとして扱うためちょうど%d件・各%d文字以内が必要です。"
        % (RANKING_LABEL_COUNT, RANKING_LABEL_MAX_LEN),
        "記述例: %s" % PIN_TEXT_EXAMPLE,
        "文言は実在のブランド名ではなく、記事本文と一致する語にしてください。",
        "ランキング型の文言を用意できない場合は、次を打ち直して別の型へ変更してかまいません:",
        '  python site/scripts/pick-image-variation.py --set-style <slug> "pin1=<型名>" "pin2=<型名>" "pin3=<型名>"',
    ]
    sys.stderr.write("\n".join(lines) + "\n")
    sys.exit(1)


HANKAKU_RE = re.compile(r"[0-9A-Za-z]")


def reject_hankaku_pin_text(opt, raw):
    """--pinN-text に半角英数字が1文字でもあればプロンプトを出力せず exit 1（D-0149）。"""
    hits = sorted(set(HANKAKU_RE.findall(raw)))
    if not hits:
        return
    lines = [
        "【エラー】%s の値に半角英数字が含まれています: %s" % (opt, "・".join(hits)),
        "半角英数字はChatGPTの入力欄へ送信する時点で脱落するため、依頼文には使えません。",
        "数字は漢数字で書いてください（例:「二種類用意する」）。",
        "画像内にはアラビア数字で描かれるため（依頼文に数字の表記ルールを含めています）、"
        "漢数字で渡して問題ありません。",
        "受け取った値: %s" % raw,
    ]
    sys.stderr.write("\n".join(lines) + "\n")
    sys.exit(1)


def low_info_error(problems, slug):
    """低情報量条件（D-0152）の違反をまとめて出し、プロンプトを一切出力せず exit 1。

    どのPinが何件だったか・どの型が高密度だったかを具体的に並べる（1件ずつ止めない）。
    """
    lines = [
        "【エラー】記事「%s」は%s（article_seqを4で割った余りが2または0・D-0152）のため、"
        "次の条件を満たさない限り依頼文を出力しません。" % (slug, piv.CONDITION_LOW),
        "  条件1: --pinN-text が各%d〜%d件であること"
        % (piv.LOW_INFO_TEXT_MIN, piv.LOW_INFO_TEXT_MAX),
        "  条件2: pin1〜3の型が3つとも低密度プールに含まれること（%s）"
        % "／".join(piv.LOW_INFO_STYLES),
        "",
        "違反の内訳:",
    ]
    lines.extend("  - %s" % p for p in problems)
    lines.extend([
        "",
        "型を入れ替える場合:",
        '  python site/scripts/pick-image-variation.py --set-style %s "pin1=<型名>" "pin2=<型名>" "pin3=<型名>"'
        % slug,
        "（現行条件＝余りが1または3の記事は従来どおり%d〜%d件・型は12種すべて使えます。"
        "CTA帯の有無はこの件数制限に影響しません）"
        % (PIN_TEXT_MIN_COUNT, PIN_TEXT_MAX_COUNT),
    ])
    sys.stderr.write("\n".join(lines) + "\n")
    sys.exit(1)


def check_low_info_condition(slug, styles, texts):
    """低情報量条件の記事について、文言件数と型の密度をまとめて検証する（D-0152）。

    現行条件の記事では何もしない（挙動を一切変えない）。
    """
    problems = []
    for slot in piv.PIN_SLOTS:
        n = len(texts[slot])
        if not (piv.LOW_INFO_TEXT_MIN <= n <= piv.LOW_INFO_TEXT_MAX):
            problems.append(
                "%s の %s が%d件です（%d〜%d件にしてください）: %s"
                % (slot, pin_text_opt(slot), n,
                   piv.LOW_INFO_TEXT_MIN, piv.LOW_INFO_TEXT_MAX,
                   "／".join(texts[slot])))
    for slot in piv.PIN_SLOTS:
        style = styles[slot]
        if not piv.is_low_density(style):
            problems.append(
                "%s の型「%s」は高密度です（低密度プールに含まれていません）" % (slot, style))
    if problems:
        low_info_error(problems, slug)


def parse_pin_texts(slot, raw, style):
    """--pinN-text の値を検証して文言リストにする。違反時は exit 1（プロンプトは出力しない）。"""
    opt = pin_text_opt(slot)
    if raw is None:
        pin_text_error("%s（型「%s」）の %s が指定されていません。" % (slot, style, opt))
    normalized = raw.replace(PIN_TEXT_SEP_HALF, PIN_TEXT_SEP_FULL)
    texts = [v.strip() for v in normalized.split(PIN_TEXT_SEP_FULL)]
    texts = [v for v in texts if v]
    if len(texts) < PIN_TEXT_MIN_COUNT:
        pin_text_error("%s の %s に文言が1件も含まれていません（空文字）。" % (slot, opt))
    if len(texts) > PIN_TEXT_MAX_COUNT:
        pin_text_error(
            "%s の %s が%d件を超えています（受け取った件数: %d件）。"
            % (slot, opt, PIN_TEXT_MAX_COUNT, len(texts))
        )
    too_long = [v for v in texts if len(v) > PIN_TEXT_MAX_LEN]
    if too_long:
        pin_text_error(
            "%s の %s に%d文字を超える文言があります: %s"
            % (slot, opt, PIN_TEXT_MAX_LEN, "／".join("%s（%d文字）" % (v, len(v)) for v in too_long))
        )
    if is_ranking(style):
        if len(texts) != RANKING_LABEL_COUNT:
            pin_text_error(
                "%s はランキング型（%s）のため順位ラベルがちょうど%d件必要ですが、%d件でした。"
                % (slot, style, RANKING_LABEL_COUNT, len(texts))
            )
        over = [v for v in texts if len(v) > RANKING_LABEL_MAX_LEN]
        if over:
            pin_text_error(
                "%s はランキング型のため各順位ラベルは%d文字以内が必要です: %s"
                % (slot, RANKING_LABEL_MAX_LEN, "／".join("%s（%d文字）" % (v, len(v)) for v in over))
            )
    return texts


# --- 型ごとの指示方針（rules/image-generation-flow.md 1-3節の表を正本としてここへ一本化。D-0126） ---
TYPE_GUIDANCE = {
    "写真ヒーロー": "物撮り・情景写真として、メイン画像と同様の方向性で仕上げる。",
    "比較グリッド": "二〜四項目を並べたグリッド／表形式にする。各項目にラベルと短い説明を付ける。",
    "手順図解": "三〜五ステップを段組みで示す。各段に番号とキャプションを付ける。",
    "チェックリスト": "三〜六項目のチェックボックス風レイアウトにする。",
    "ビフォーアフター": "左右または上下で対比構造にする。",
    "Q&A形式": "質問と回答を吹き出し等で対比させる。",
    "ポイント整理": "記事の要点を三〜四個の箇条書き風レイアウトで見せる。",
    # ランキング型は渡された順位ラベル（--pinN-text）を埋め込む形にする（D-0144・D-0148）。
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


# 台帳・pick-image-variation.py 側の型名は変更せず、依頼文へ埋め込む時だけ表記を差し替える
# （型名を変えると check-pin-image-style.py の重複判定と台帳の既存値が壊れるため・D-0149）。
STYLE_DISPLAY_NAME = {"Q&A形式": "一問一答形式"}


def display_style(style):
    return kanjify_digits(STYLE_DISPLAY_NAME.get(style, style))


def build_hero_prompt(row):
    lines = [
        "紅茶ブログのメイン画像を一枚作成してください。",
        axis_summary(row) + "の構図で、物撮りまたは情景写真として仕上げてください。",
        text_overlay_instruction(row["text_position"]),
        BRAND_LOGO_BAN,
        DIGIT_RULE,
        hero_dimension_text(),
        HERO_LANDSCAPE_RULE,
    ]
    return "\n".join(lines)


def is_ranking(style):
    """型名にランキングが含まれるか（D-0144）。"""
    return RANKING_KEY in style


def ranking_guidance(labels):
    return TYPE_GUIDANCE[RANKING_KEY].format(label1=labels[0], label2=labels[1], label3=labels[2])


def build_pin_prompt(row, style, texts, cta_text=None):
    """Pin一枚分の依頼文を組み立てる。cta_textがあればCTA帯の指示を足す（D-0152）。"""
    ranking = is_ranking(style)
    if ranking:
        guidance = ranking_guidance(texts)
    else:
        guidance = TYPE_GUIDANCE.get(style)
    if guidance is None:
        print("型ごとの指示方針が未定義です（TYPE_GUIDANCEにない型）: %s" % style)
        sys.exit(1)
    lines = [
        "紅茶ブログのピン画像を一枚作成してください。型は「%s」です。" % display_style(style),
        guidance,
        axis_summary(row) + "を反映してください。",
        pin_text_instruction(row["text_position"], texts, ranking, has_cta=bool(cta_text)),
    ]
    if cta_text:
        lines.append(cta_instruction(cta_text))
    lines.extend([
        BRAND_LOGO_BAN,
        DIGIT_RULE,
        pin_dimension_text(),
    ])
    return "\n".join(lines)


# --- 実装D: 依頼文本文に半角ASCIIが混入していないかの自己チェック（D-0149） ---
# 区切り行（--- hero --- 等）は main() 側で組み立てて出力するため、この検査の対象外。
ASCII_RE = re.compile(r"[\x20-\x7e]")


def assert_no_ascii(blocks):
    """ChatGPTへ貼り付ける本文に半角ASCIIが1文字でもあれば、何も出力せず exit 1。"""
    bad = []
    for name, body in blocks:
        for i, line in enumerate(body.split("\n"), 1):
            hits = ASCII_RE.findall(line)
            if hits:
                bad.append((name, i, line, sorted(set(hits))))
    if not bad:
        return
    lines = [
        "【エラー】依頼文の本文に半角ASCII文字が含まれています"
        "（ChatGPTの入力欄へ送信する時点で脱落するため出力を中止しました）。",
    ]
    for name, i, line, hits in bad:
        lines.append(
            "%s の%d行目: 混入文字 %s ／ 該当行: %s"
            % (name, i, "・".join("「%s」" % c for c in hits), line)
        )
    lines.append("固定文・型ガイダンス・台帳由来の値のいずれかに半角文字が入っています。"
                 "全角または日本語へ置き換えてください。")
    sys.stderr.write("\n".join(lines) + "\n")
    sys.exit(1)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    # エラーはすべて標準エラーへ出すため、こちらも同じくUTF-8へ寄せる（既定のcp932だと文字化けする）
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    argv = sys.argv[1:]
    raw_texts = {}
    for slot in piv.PIN_SLOTS:
        opt = pin_text_opt(slot)
        if opt in argv:
            i = argv.index(opt)
            if i + 1 >= len(argv):
                pin_text_error("%s の値が指定されていません。" % opt)
            reject_hankaku_pin_text(opt, argv[i + 1])
            raw_texts[slot] = argv[i + 1]
            del argv[i:i + 2]

    if len(argv) != 1:
        print(
            'usage: make-image-prompt.py <slug> '
            + " ".join('%s "文言1｜文言2"' % pin_text_opt(s_) for s_ in piv.PIN_SLOTS)
        )
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

    # --- 画像内文言の検証（D-0148・プロンプトを1行も出力する前に全スロットを判定する） ---
    texts = {}
    for slot in piv.PIN_SLOTS:
        texts[slot] = parse_pin_texts(slot, raw_texts.get(slot), styles[slot])

    # --- 条件による分岐（D-0152・余りの判定は piv 側の1関数に集約） ---
    conditions = piv.conditions_for_slug(slug, rows)
    info_condition = conditions[0] if conditions else None
    cta_condition = conditions[1] if conditions else None

    if info_condition == piv.CONDITION_LOW:
        check_low_info_condition(slug, styles, texts)

    # CTA文言は --pinN-text の件数制限の対象外のため、件数検証の後にここで足す（D-0152）。
    # 文言はピン単位で変える（D-0157）。添字の計算は piv 側の1関数に集約し、ここでは複製しない。
    cta_texts = {slot: None for slot in piv.PIN_SLOTS}
    if cta_condition == piv.CTA_YES:
        article_seq = piv.seq_for_slug(slug, rows)
        for pin_no, slot in enumerate(piv.PIN_SLOTS, start=1):
            cta_texts[slot] = piv.cta_text_for_seq(article_seq, pin_no)

    blocks = [("hero", build_hero_prompt(by_type["hero"]))]
    for slot in piv.PIN_SLOTS:
        blocks.append((slot, build_pin_prompt(by_type[slot], styles[slot], texts[slot], cta_texts[slot])))

    assert_no_ascii(blocks)

    if conditions:
        print("■ 条件: %s／%s（D-0152・この行はChatGPTへ貼らない）" % (info_condition, cta_condition))
        if cta_condition == piv.CTA_YES:
            listed = "／".join(
                "%s=「%s」" % (slot, cta_texts[slot]) for slot in piv.PIN_SLOTS
            )
            print("■ CTA文言: %s（3枚とも別の文言・この行も貼らない）" % listed)
        print()

    for name, body in blocks:
        print("--- %s ---" % name)
        print(body)
        print()


if __name__ == "__main__":
    main()
