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

節構成（hero・Pin共通・D-0172）:
  依頼文は【比率】【用途】【構図】【画像に描く文字】（Pinの CTAあり群のみ【誘導の帯】）
  【描かない要素】【仕上げ】の順で組み立てる。比率は冒頭と末尾の2箇所に置く（生成AIが
  長い依頼文の途中の指示を取りこぼしやすいため）。否定形の指示は【描かない要素】へ集約し、
  他の節では肯定形のホワイトリスト（描いてよい文字はこれだけ）で書く。

寸法・比率の根拠（実測・reports/2026-08-15-5.md／D-0172）:
  hero: 横縦比およそ一・八倍を指示する。site/scripts/hero-to-webp.py の TARGET=(1400, 735)
        は「WebP変換後」の正規サイズ（D-0020）であり、ChatGPTが生成時に出せる寸法ではない
        （生成側の最も横に広い形は約1.75倍）。達成不可能な実寸を指示すると他の指示への追従が
        弱まるため、実寸ではなく比率で指示する。1.8倍あれば hero-to-webp.py の縦長ガード
        下限（横縦比1.4・D-0148）を確実に上回る。あわせて中央クロップで上下が削られるため、
        見出し文言を上下の端へ寄せない指示を【画像に描く文字】節に置く。
  pin : output/Pin-images/ 配下の直近実測で、pin108〜119の12枚は 1024x1536（比率2:3）で
        一貫していた。pin120〜122（2026-08-15）はプロンプトで異なる比率（四対五等）を
        指定したためズレていた（1122x1402／1003x1568）。本スクリプトは実測で最も長く
        安定していた 2:3 を正規値として毎回のプロンプトに固定する。縦長という指示と整合する
        よう「横二に対して縦三」の語順で書く（D-0172以前は「三対二」と書いており、縦長指示と
        矛盾して横長Pinが生成される原因になっていた）。

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

hero画像に焼き込む見出し文言の必須指定（D-0173）:
  hero用の【画像に描く文字】節は、以前はプレースホルダー《…》を出力し、AIが手で置き換える
  前提だった。置き換えを忘れると説明文がそのまま画像へ焼き込まれるため、pin側（D-0148）と
  同じく --hero-text で受け取る必須引数にした。受け取り方・検査は --pinN-text と同一で、
  上限件数だけが異なる（見出しは一行または二行のため1〜2件・1件あたり30文字以内）。
  未指定・件数超過・文字数超過・半角英数字混入のいずれでも、hero用もpin用もプロンプトを
  一切出力せず exit 1 で終わる。

使い方:
  python site/scripts/make-image-prompt.py <slug> --hero-text "見出し文言"
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


# --- 節構成（hero・Pin共通・D-0172） ---
# 依頼文は【比率】【用途】【構図】【画像に描く文字】（【誘導の帯】）【描かない要素】【仕上げ】の
# 順に組み立てる。節の区切りは全角の【】のみを使う（ASCII検査に通す必要があるため・D-0149）。
SEC_RATIO = "比率"
SEC_PURPOSE = "用途"
SEC_COMPOSITION = "構図"
SEC_TEXT = "画像に描く文字"
SEC_CTA = "誘導の帯"
SEC_EXCLUDE = "描かない要素"
SEC_FINISH = "仕上げ"


def section(title, bodies):
    """【見出し】＋本文行 の1節を組み立てる。空の行は落とす。"""
    return "\n".join(["【%s】" % title] + [b for b in bodies if b])


# --- 比率（D-0172） ---
# hero: 生成側（ChatGPT）が直接出せる最も横に広い形は約一・七五倍で、hero-to-webp.py の
#       出力寸法（1400x735・約1.90）は生成時には達成できない。達成不可能な実寸を指示すると
#       他の指示への追従も弱まるため、比率表記（およそ一・八倍）で指示する。一・八倍あれば
#       hero-to-webp.py の縦長ガード下限（横縦比1.4）を確実に上回る。
HERO_RATIO_APPROX = "一・八"

# pin: 実測（pin108〜119・12枚で一貫）した1024x1536＝2:3。縦長であることが要件のため、
#      横（PIN_RATIO_W）を先に、縦（PIN_RATIO_H）を後に置いて「二に対して三」と読ませる。
PIN_RATIO_W, PIN_RATIO_H = 2, 3


def hero_ratio_head():
    return (
        "この画像は横長で作る。横の長さが縦の長さのおよそ{r}倍になる、横に広い形にする。"
    ).format(r=HERO_RATIO_APPROX)


def hero_ratio_tail():
    return "横長で、横の長さが縦の長さのおよそ{r}倍になる形で出力する。".format(r=HERO_RATIO_APPROX)


def pin_ratio_head():
    return (
        "この画像は縦長で作る。横の長さ{w}に対して縦の長さ{h}の比率にする。"
    ).format(w=to_kanji(PIN_RATIO_W), h=to_kanji(PIN_RATIO_H))


def pin_ratio_tail():
    return (
        "縦長で、横の長さ{w}に対して縦の長さ{h}の比率で出力する。"
    ).format(w=to_kanji(PIN_RATIO_W), h=to_kanji(PIN_RATIO_H))


# --- rules/image-generation-flow.md にある既存の固定要素（正本はこのファイル・D-0126） ---
# 【用途】節。
HERO_PURPOSE = "紅茶と器の暮らしを紹介するブログの、記事の見出しに使う横長画像を一枚作る。"
PIN_PURPOSE = "紅茶と器の暮らしを紹介するブログの、写真共有サイト向けの縦長画像を一枚作る。"

# 【描かない要素】節（D-0172）。否定形の指示はこの1節に集約し、他の節では繰り返さない
# （同じ趣旨の否定文を各所に散らすと他の指示への追従が弱まるため）。
# 2文目は実在ブランドの模造禁止（D-0059）であり、削除しない。
EXCLUDE_RULES = [
    "上に挙げた文言以外の文字・数字・記号・説明文・英字・記入欄は描かない。",
    "実在の商標を思わせるロゴや文字は描かず、缶や箱の面は無地にする。",
]

DIGIT_RULE = "数字はアラビア数字で描く。"

# heroは後工程の hero-to-webp.py が 1400x735 へ中央クロップするため上下が削られる。
# 端に寄った見出し文言は切れて作り直しになる（D-0148）。
HERO_MARGIN_RULE = (
    "見出しの文字と主要な被写体は、画像の上下の端から十分に内側へ入れて配置する。"
    "上部帯または下部帯の指定であっても、端に接するほど寄せない。"
)

# CTA帯の意匠・文言指示（D-0152）。CTAありの群のPin依頼文にだけ足す。
# 生成AIが制御できない微細指定（余白の割合・外周の枠線の太さ）は置かない（D-0172）。
# 全角のみで組み立てる（出力直前のASCII検査に通す必要があるため・D-0149）。
CTA_BAND_RULES = [
    "画像の下部に、角丸の帯を一つだけ置く。",
    "帯の地の色は濃い茶色系にし、帯の中の文字の色は白にする。",
    "帯の中に描く文字は「{text}」の一つだけとする。",
    "帯の下側に少しの余白を空ける。",
    "帯は見出しの文言と重ならない位置に置き、見出しの文言と帯の文言がどちらも読める大きさにする。",
]


def cta_instruction(cta_text):
    return [line.format(text=cta_text) for line in CTA_BAND_RULES]


TEXT_POSITION_LABEL = {"上部帯": "画像上部", "下部帯": "画像下部", "中央": "画像中央"}


def text_position_line(text_position, ranking):
    if ranking:
        return "各順位の枠内に、白抜き等の読みやすい文字で配置する。"
    pos = kanjify_digits(TEXT_POSITION_LABEL.get(text_position, text_position))
    return "{pos}に、白抜き等の読みやすい文字で配置する。".format(pos=pos)


def text_whitelist_head(count, has_cta):
    """【画像に描く文字】節の冒頭。肯定形のホワイトリストとして書く（D-0172）。

    「文字を入れない仕上げは不可」という否定文は「必ず描き込む」が同じ役割を果たすため置かない。
    """
    n = to_kanji(count)
    only = "この{n}件".format(n=n)
    if has_cta:
        only += "と、後述の【%s】に指定する文言" % SEC_CTA
    return (
        "次の{n}件の文言を必ず画像に描き込む。一字一句そのまま描く。"
        "画像に描いてよい文字は{only}だけとする。{digit}"
    ).format(n=n, only=only, digit=DIGIT_RULE)


def hero_text_section(text_position, texts):
    """渡された見出し文言をそのまま列挙する（プレースホルダーは出さない・D-0173）。

    冒頭文・列挙の書式は pin側（pin_text_section）と同一にする（覚える規則を増やさないため）。
    """
    lines = [
        text_whitelist_head(len(texts), False),
        text_position_line(text_position, False),
    ]
    for i, t in enumerate(texts, 1):
        lines.append("文言その{n}：「{t}」".format(n=to_kanji(i), t=t))
    lines.append(HERO_MARGIN_RULE)
    return section(SEC_TEXT, lines)


def pin_text_section(text_position, texts, ranking, has_cta):
    """渡された文言をそのまま列挙する焼き込み指示を作る（数字は漢数字・ASCII規約。D-0148）。"""
    lines = [
        text_whitelist_head(len(texts), has_cta),
        text_position_line(text_position, ranking),
    ]
    for i, t in enumerate(texts, 1):
        lines.append("文言その{n}：「{t}」".format(n=to_kanji(i), t=t))
    return section(SEC_TEXT, lines)


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
    '--hero-text "雨の日の紅茶時間" '
    '--pin1-text "雨の日の一杯｜香りで気分転換" --pin2-text "淹れる前と後" '
    '--pin3-text "茶葉｜湯温｜蒸らし時間"'
)


# --- hero画像に焼き込む見出し文言（--hero-text・D-0173） ---
# 受け取り方・検査は --pinN-text と同一に揃える（上限件数だけが異なる。見出しは一行または二行）。
HERO_TEXT_OPT = "--hero-text"
HERO_TEXT_MIN_COUNT = 1
HERO_TEXT_MAX_COUNT = 2
HERO_TEXT_MAX_LEN = 30
HERO_TEXT_EXAMPLE = (
    'python site/scripts/make-image-prompt.py <slug> '
    '--hero-text "雨の日の紅茶時間" '
    '--pin1-text "雨の日の一杯｜香りで気分転換" --pin2-text "淹れる前と後" '
    '--pin3-text "茶葉｜湯温｜蒸らし時間"'
)


def hero_text_error(detail):
    """--hero-text 関連のエラーを標準エラーへ出して exit 1 する（D-0173）。

    hero用・pin用のどちらの依頼文も出力しない（--pinN-text と同じ挙動）。
    """
    lines = [
        "【エラー】%s" % detail,
        "hero画像に焼き込む見出し文言は %s での指定が必須です"
        "（%d〜%d件・1件あたり%d文字以内。区切りは全角の縦棒「%s」）。"
        % (HERO_TEXT_OPT, HERO_TEXT_MIN_COUNT, HERO_TEXT_MAX_COUNT,
           HERO_TEXT_MAX_LEN, PIN_TEXT_SEP_FULL),
        "見出しは一行または二行のため上限は%d件です（Pinの上限%d件とは異なります）。"
        % (HERO_TEXT_MAX_COUNT, PIN_TEXT_MAX_COUNT),
        "記述例: %s" % HERO_TEXT_EXAMPLE,
        "文言は実在のブランド名ではなく、記事本文と一致する語にしてください。",
    ]
    sys.stderr.write("\n".join(lines) + "\n")
    sys.exit(1)


def parse_hero_texts(raw):
    """--hero-text の値を検証して文言リストにする。違反時は exit 1（プロンプトは出力しない）。"""
    if raw is None:
        hero_text_error("%s が指定されていません。" % HERO_TEXT_OPT)
    normalized = raw.replace(PIN_TEXT_SEP_HALF, PIN_TEXT_SEP_FULL)
    texts = [v.strip() for v in normalized.split(PIN_TEXT_SEP_FULL)]
    texts = [v for v in texts if v]
    if len(texts) < HERO_TEXT_MIN_COUNT:
        hero_text_error("%s に文言が1件も含まれていません（空文字）。" % HERO_TEXT_OPT)
    if len(texts) > HERO_TEXT_MAX_COUNT:
        hero_text_error(
            "%s が%d件を超えています（受け取った件数: %d件）: %s"
            % (HERO_TEXT_OPT, HERO_TEXT_MAX_COUNT, len(texts), "／".join(texts))
        )
    too_long = [v for v in texts if len(v) > HERO_TEXT_MAX_LEN]
    if too_long:
        hero_text_error(
            "%s に%d文字を超える文言があります: %s"
            % (HERO_TEXT_OPT, HERO_TEXT_MAX_LEN,
               "／".join("%s（%d文字）" % (v, len(v)) for v in too_long))
        )
    return texts


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


def build_hero_prompt(row, texts):
    """hero用の依頼文を6節構成で組み立てる（D-0172・heroに【誘導の帯】は無い）。"""
    return "\n".join([
        section(SEC_RATIO, [hero_ratio_head()]),
        section(SEC_PURPOSE, [HERO_PURPOSE]),
        section(SEC_COMPOSITION, [
            axis_summary(row) + "の構図で、物撮りまたは情景写真として仕上げる。",
        ]),
        hero_text_section(row["text_position"], texts),
        section(SEC_EXCLUDE, EXCLUDE_RULES),
        section(SEC_FINISH, [hero_ratio_tail()]),
    ])


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
    parts = [
        section(SEC_RATIO, [pin_ratio_head()]),
        section(SEC_PURPOSE, [PIN_PURPOSE]),
        section(SEC_COMPOSITION, [
            "型は「%s」。" % display_style(style),
            guidance,
            axis_summary(row) + "を反映する。",
        ]),
        pin_text_section(row["text_position"], texts, ranking, bool(cta_text)),
    ]
    if cta_text:
        parts.append(section(SEC_CTA, cta_instruction(cta_text)))
    parts.extend([
        section(SEC_EXCLUDE, EXCLUDE_RULES),
        section(SEC_FINISH, [pin_ratio_tail()]),
    ])
    return "\n".join(parts)


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
    raw_hero_text = None
    if HERO_TEXT_OPT in argv:
        i = argv.index(HERO_TEXT_OPT)
        if i + 1 >= len(argv):
            hero_text_error("%s の値が指定されていません。" % HERO_TEXT_OPT)
        reject_hankaku_pin_text(HERO_TEXT_OPT, argv[i + 1])
        raw_hero_text = argv[i + 1]
        del argv[i:i + 2]

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
            'usage: make-image-prompt.py <slug> %s "見出し文言" ' % HERO_TEXT_OPT
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
    hero_texts = parse_hero_texts(raw_hero_text)
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

    blocks = [("hero", build_hero_prompt(by_type["hero"], hero_texts))]
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
