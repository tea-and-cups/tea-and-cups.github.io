# -*- coding: utf-8 -*-
r"""記事slugのピン投稿文が「X向けの文字数」を満たしているかを検査する。

  python site/scripts/check-x-post-length.py <slug>

なぜ専用の説明文が要るか:
  Xの投稿は2つの別々の上限に同時に収まらないと通らない。
    (a) X側の数え方 … 日本語の全角文字を1文字あたり2として数え、URLは実際の
        長さに関わらず 23 として数える（X_URL_WEIGHT）。
    (b) Buffer の createPost の入力検証 … 全角・半角を区別せず、URLも実際の
        長さのまま数えて 280 と比べる（2026-08-30実測。D-0176）。
  Pinterest・Instagram・Threads 向けの説明文（200字前後）は (a) の数え方だと
  400前後になり、どうやってもXには載らない。かといって共通の説明文を短くすると
  他の3媒体の情報量が落ちる。そのため **Xだけ専用の短い本文を持たせる**。

ピン投稿文ファイルの書式（rules/pinterest-api.md「X向けの説明文」節が正本）:
  行頭「- X用説明文: 」の1行。1ファイルにつき0行または1行。

検査するもの（1ファイルでも満たさなければ終了コード1）:
  a) 「- X用説明文: 」行が存在し、内容が空でないこと
  b) 実際にXへ送る本文（X用説明文 ＋ 改行 ＋ utm_source=x に置換した誘導先URL）の
     実文字数が X_CHAR_LIMIT 以下であること
  c) 同じ本文のX重みが X_CHAR_LIMIT 以下であること

NG時は「あと何文字削れば両方を満たすか」まで出す。超過文字数だけを出すと、
全角を削るのか半角を削るのかで必要量が倍違うため、書き直しが何度も往復する。

このファイルが X 関連の判定の正本であり、post-pins-to-buffer.py はここから
import して使う（同じ数え方を二重実装すると片方だけ直って食い違うため）。
"""

import glob
import importlib.util
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
PINS_DIR = os.path.join(ROOT, "output", "pins")

# --- 判定に使う定数（マジックナンバーを判定式へ直接書かない） --------------------

# X（無料枠）の上限。実文字数・X重みの両方をこの1つの値と比べる。
X_CHAR_LIMIT = 280

# Xの数え方でのURLの重み。URLの実際の長さに関わらずこの値で数える。
X_URL_WEIGHT = 23

# X重みが1になる符号位置の範囲（これ以外は2として数える）。
# 半角（ASCII・ラテン文字・一般句読点）が1、全角・絵文字が2になる。
# 改行 U+000A は最初の範囲に入るので1として数えられる。
X_LIGHT_WEIGHT_RANGES = (
    (0x0000, 0x10FF),
    (0x2000, 0x200D),
    (0x2010, 0x201F),
    (0x2032, 0x2037),
)

# 目安の上限（rules/pinterest-api.md と揃える）。この値自体では弾かない
# （実際に通るかどうかを決めるのは上の2つの判定であり、目安で二重に弾くと
#  「90字以内なのにNG」「91字だがOK」といった食い違いが起きるため）。
X_DESC_TARGET_CHARS = 90

# ピン投稿文ファイル内の項目名。
X_DESC_LABEL = "- X用説明文: "


_PPB_CACHE = []


def _load_post_pins_to_buffer():
    """post-pins-to-buffer.py をモジュールとして読み込む（1プロセスにつき1回だけ）。
    （ファイル名がハイフンを含み、そのままではimportできないため）。

    誘導先URLの読み取りと utm_source の差し替えはあちらが正本で、ここでは
    書き写さない。あちらの module 直下は定数と関数定義だけで副作用が無いため、
    読み込んでも通信・ファイル書き込みは起きない。"""
    if _PPB_CACHE:
        return _PPB_CACHE[0]
    path = os.path.join(SCRIPT_DIR, "post-pins-to-buffer.py")
    spec = importlib.util.spec_from_file_location("post_pins_to_buffer", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _PPB_CACHE.append(mod)
    return mod


# --- 数え方 ---------------------------------------------------------------------


def x_weight(text):
    """Xの数え方での重みを返す（全角=2 / 半角=1 / 改行=1）。URLの置換は呼び出し元で行う。"""
    total = 0
    for ch in text:
        code = ord(ch)
        light = any(low <= code <= high for low, high in X_LIGHT_WEIGHT_RANGES)
        total += 1 if light else 2
    return total


def x_weighted_length(text, url):
    """本文のX重み。URLは長さに関わらず X_URL_WEIGHT として数える。"""
    occurrences = text.count(url)
    return x_weight(text.replace(url, "")) + X_URL_WEIGHT * occurrences


def raw_length(text):
    """Bufferの入力検証が見る実文字数（UTF-16コード単位）。

    サロゲートペアの絵文字を2として数える側に倒してある。Buffer側がどちらで
    数えているかは公開されていないため、少ないほうに寄せて弾かれるより、
    多いほうで見積もって手前で止めるほうが安全（D-0176の実測と同じ扱い）。
    """
    return len(text.encode("utf-16-le")) // 2


def build_x_text(x_description, url):
    """X向けの本文を組み立てる。誘導文は付けない（280に収めるため）。"""
    return "%s\n%s" % (x_description, url)


def verdict(x_description, url):
    """X向け本文の判定。戻り値: (送ってよいか, 本文, 実文字数, X重み)"""
    text = build_x_text(x_description, url)
    raw = raw_length(text)
    weighted = x_weighted_length(text, url)
    return (raw <= X_CHAR_LIMIT and weighted <= X_CHAR_LIMIT), text, raw, weighted


def shortfall(raw, weighted):
    """あと何文字削れば両方を満たすかを返す。

    戻り値: (実文字数の超過, X重みの超過, 全角だけ削る場合の必要文字数,
             半角だけ削る場合の必要文字数)

    全角を1文字削ると実文字数は1・X重みは2減る。半角を1文字削るとどちらも1減る。
    どちらを削るかで必要量が倍違うため、両方を出す。
    """
    raw_over = max(0, raw - X_CHAR_LIMIT)
    weight_over = max(0, weighted - X_CHAR_LIMIT)
    need_fullwidth = max(raw_over, -(-weight_over // 2))  # 切り上げ除算
    need_halfwidth = max(raw_over, weight_over)
    return raw_over, weight_over, need_fullwidth, need_halfwidth


# --- ピンファイルの読み取り -----------------------------------------------------


def find_pin_files(slug):
    """slugに対応するピン投稿文ファイル名の一覧（昇順）。

    照合の仕方は check-pin-image-style.py の find_pin_files と揃える。
    """
    pattern = os.path.join(PINS_DIR, "*-%s-*.md" % slug)
    return sorted(os.path.basename(p) for p in glob.glob(pattern))


def extract_x_description(lines):
    """「- X用説明文: 」行を1本だけ取り出す。戻り値: (説明文 または None, 理由)"""
    ppb = _load_post_pins_to_buffer()
    found = []
    for line in lines:
        stripped = line.strip()
        m = ppb.X_DESC_RE.match(stripped)
        if m:
            found.append(m.group(1).strip())
    if not found:
        return None, "「%s」行がありません" % X_DESC_LABEL.strip()
    if len(found) > 1:
        return None, "「%s」行が%d本あります（1ファイルにつき0行または1行）" % (
            X_DESC_LABEL.strip(), len(found))
    if not found[0]:
        return None, "「%s」行が空です" % X_DESC_LABEL.strip()
    return found[0], None


def check_file(file_name, out):
    """1ファイルを検査する。戻り値: 満たしていれば True。"""
    ppb = _load_post_pins_to_buffer()
    path = os.path.join(PINS_DIR, file_name)
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError as e:
        out("  [NG] %s" % file_name)
        out("       ファイル読み込み失敗: %s" % e)
        return False

    guide_url = None
    for line in lines:
        m = ppb.GUIDE_URL_RE.match(line.strip())
        if m:
            guide_url = m.group(1).strip()
            break
    if not guide_url:
        out("  [NG] %s" % file_name)
        out("       「- 誘導先URL:」行がありません（X向け本文を組み立てられません）")
        return False

    x_description, reason = extract_x_description(lines)
    if x_description is None:
        out("  [NG] %s" % file_name)
        out("       %s" % reason)
        out("       書式: 「%s<90字以内の本文>」（rules/pinterest-api.md）" % X_DESC_LABEL)
        return False

    url = ppb.rewrite_utm_source(guide_url, "twitter")
    ok, _text, raw, weighted = verdict(x_description, url)
    if ok:
        out("  [OK] %s  実文字数 %d / X重み %d（上限 %d）"
            % (file_name, raw, weighted, X_CHAR_LIMIT))
        return True

    raw_over, weight_over, need_fw, need_hw = shortfall(raw, weighted)
    out("  [NG] %s" % file_name)
    out("       実文字数 %d / 上限 %d → %d文字超過" % (raw, X_CHAR_LIMIT, raw_over))
    out("       X重み   %d / 上限 %d → %d文字超過" % (weighted, X_CHAR_LIMIT, weight_over))
    out("       あと何文字削れば両方を満たすか: 全角だけを削るなら %d文字 / "
        "半角だけを削るなら %d文字" % (need_fw, need_hw))
    out("       ※自動切り詰めは行いません。X用説明文を書き直してください。")
    return False


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if len(argv) != 1:
        sys.stderr.write("使い方: python site/scripts/check-x-post-length.py <slug>\n")
        return 2
    slug = argv[0]

    def out(msg=""):
        print(msg)

    files = find_pin_files(slug)
    out("対象記事: %s（X向け本文の文字数・上限 %d）" % (slug, X_CHAR_LIMIT))
    if not files:
        out("  [NG] output/pins/ に %s のピン投稿文ファイルがありません。" % slug)
        return 1

    ng = 0
    for file_name in files:
        if not check_file(file_name, out):
            ng += 1

    out()
    if ng:
        out("NG %d件 / 全%d件" % (ng, len(files)))
        return 1
    out("X_LENGTH_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
