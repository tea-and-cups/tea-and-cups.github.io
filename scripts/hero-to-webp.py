"""hero画像を記事用のWebP（本文用のhero＋一覧用のthumb）に変換して配置する。

背景（D-0020 / reports/2026-07-26-ui-ux-review.md）:
  ChatGPTが出力する画像は1.8〜2.5MBのPNGで、そのまま置くとモバイルのLCPを大きく損なう。
  また [slug].astro が width="1200" height="630" を固定出力するため、
  比率がずれるとCLS（表示中のレイアウトずれ）が発生する。
  よってhero画像は「1400x735（1200x630と同比率）のWebP」に統一する。

  一覧・関連記事のサムネイルにheroをそのまま使うと、1覧ページで85KB×記事数を読むことになる。
  同比率の縮小版 thumb.webp（480x252・20KB前後）を必ずセットで書き出し、一覧側はこちらを使う。
  サムネのパスはslugから導出する（frontmatterのキーは9項目のまま増やさない・CLAUDE.md 9-2規約1）。

使い方:
  python site/scripts/hero-to-webp.py <入力画像> <slug>
      1枚を変換して site/public/images/<slug>/ に hero.webp と thumb.webp を配置する。
      入力画像は output/hero-images/ にも原本として残しておくこと。

  python site/scripts/hero-to-webp.py --all
      output/hero-images/*.png をすべて再変換する（拡張子を除いたファイル名の「（」より前をslugとみなす）。
      画質設定を見直したときの一括やり直し用。
      既存原本の一括再生成が目的のため、縦長ガード（下記）は適用せず、
      該当した原本のファイル名を実行末尾に一覧表示するだけにする（D-0148）。

  python site/scripts/hero-to-webp.py --category <入力画像> <カテゴリslug>
      テーマ一覧（/category/）のカード画像を作る。
      site/public/images/categories/<カテゴリslug>.webp に 1200x675（16:9・中央基準）で配置する。
      入力画像は output/category-images/ に原本として残しておくこと。

  python site/scripts/hero-to-webp.py --stamp-pin <入力PNG> <出力PNG>
      Pin画像の右下に「琥珀時間」を合成し、合成済みの目印（tEXtチャンク）を入れたPNGを書き出す。
      起動元は copy-pin-image.sh のみ（ピン352以降の配置時）。単体で手打ちする必要はない。

ブランド表記「琥珀時間」の後処理合成（D-0274・GD-0036後半）:
  右下の「琥珀時間」は画像生成に描かせず（描かせると入ったり入らなかったりする）、ここで必ず合成する。
  hero: hero.webp にだけ入れる。thumb.webp とカテゴリ画像には入れない（一覧の縮小画像では読めないため）。
        合成するのは、原本の更新日時が BRAND_STAMP_START 以降のものだけ（単一変換も --all も同じ判定）。
        それより前の原本には生成側で描いた印が既に入っている可能性があり、重ねると二重になる。
        印の右端は画像の幅の83%以内に置く（モバイルの記事ページは中央4:3で表示し左右約15%が切れる）。
  Pin : --stamp-pin で合成する。目印の有無は check-pin-image-style.py が公開前に検査する。
  フォント（BRAND_FONT_PATH）が無い場合は合成を飛ばさず exit 1 で止める。

縦長ガード（D-0148・単一記事の変換時のみ）:
  ChatGPTが縦長画像を出すと ImageOps.fit の中央クロップで上部の見出し文言が切れ、
  気づいた時点で作り直しになる（2026-08-20に908x1732で実際に発生）。
  幅<=高さ、または横縦比が1.4未満の入力は変換せず exit 1 で止める。

python本体はPATH上の `python`（Windows版Python 3.12系）を想定している。
rules/command-execution.md のとおり、呼び出しは常にプロジェクトルートからの相対パスで行う。
"""

import os
import re
import sys
from datetime import datetime, timedelta, timezone

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, PngImagePlugin

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(ROOT, "output", "hero-images")
OUT_DIR = os.path.join(ROOT, "site", "public", "images")

TARGET = (1400, 735)  # OGP推奨1200x630と同比率。変更する場合は[slug].astroのwidth/heightも合わせる
QUALITY = 82
# 一覧・関連記事用サムネイル。TARGETと同比率（40:21）を保つこと。
# 表示上の最大幅は約200px想定で、Retina(2x)でも足りるサイズにしている。
THUMB = (480, 252)
THUMB_QUALITY = 80
# テーマ一覧のカード画像。CategoryCard.astro の width/height（1200x675・16:9）と揃えること。
CATEGORY_DIR = os.path.join(OUT_DIR, "categories")
CATEGORY_TARGET = (1200, 675)
CATEGORY_QUALITY = 82


# --- 縦長ガード（D-0148） ---
# TARGET比率は40:21（約1.90）。これより横縦比が小さいほど中央クロップで上下が大きく削られる。
# 1.4未満は上下の帯文字が切れる実測域のため、単一記事の変換では止める。
MIN_ASPECT = 1.4


def aspect_ng(w, h):
    """変換すると上下が大きく切れる寸法か（縦長／横縦比1.4未満）を返す。"""
    return w <= h or (w / h) < MIN_ASPECT


def check_aspect_or_exit(src_path, w, h):
    """単一記事の変換時のみ呼ぶ。該当したら1枚も書き出さずに exit 1 する（D-0148）。"""
    if not aspect_ng(w, h):
        return
    shape = "縦長" if w <= h else "横長だが横縦比が%.2f（%.1f未満）" % (w / h, MIN_ASPECT)
    print(f"変換を中止しました: 入力画像が{shape}です（実寸 {w}x{h}・横縦比 {w/h:.2f}）")
    print(f"  入力: {src_path}")
    print(
        f"  heroは{TARGET[0]}x{TARGET[1]}（比率{TARGET[0]/TARGET[1]:.2f}）へ中央クロップするため、"
        "このまま変換すると上部の見出し文言が切れます。"
        "ChatGPTへ横長（横の辺が縦の辺より長い形）での作り直しを依頼してください。"
    )
    sys.exit(1)


# --- ブランド表記「琥珀時間」の後処理合成（D-0274・GD-0036後半） ---
BRAND_TEXT = "琥珀時間"
BRAND_FONT_PATH = r"C:\Windows\Fonts\yumindb.ttf"  # 游明朝 Demibold（Windows標準）
# 色は make-image-prompt.py:199-202（BRAND_FINISH_RULES）の3色基調「琥珀色・生成り・深い茶色」から、
# 文字に生成り、影に深い茶色を使う。RGB値は site/src/styles/global.css:2-3 の
# --color-ivory（#f5efe4）と --color-brown（#3a2a1f）を写した。
BRAND_FILL = (0xF5, 0xEF, 0xE4)
BRAND_SHADOW = (0x3A, 0x2A, 0x1F)
# 明るい背景でも暗い背景でも読めるよう、文字の後ろに深い茶色の淡い影（ぼかし）を敷く。
BRAND_SHADOW_ALPHA = 215
BRAND_SHADOW_BLUR_RATIO = 0.13    # ぼかし半径（文字サイズ比）
BRAND_SHADOW_SPREAD_RATIO = 0.07  # 影を文字より太らせる幅（文字サイズ比）
BRAND_TRACKING_RATIO = 0.10       # 字間（文字サイズ比）

# hero: 原本の更新日時がこの時刻以降のものにだけ合成する（copy-hero-image.sh は cp に -p を
# 付けないため、原本の更新日時＝配置した時刻）。それより前の原本は生成側の印が入っている可能性がある。
JST = timezone(timedelta(hours=9))
BRAND_STAMP_START = datetime(2026, 10, 12, 0, 0, tzinfo=JST)

# hero の位置。[slug].astro のモバイル表示（global.css の .hero-image{aspect-ratio:4/3}）は
# 1400x735 の中央980pxだけを見せ、左右それぞれ15%が切れる。印の右端は幅の83%以内に置く。
HERO_STAMP = {"size_ratio": 0.024, "right_ratio": 0.83, "bottom_margin_ratio": 0.045}
# Pin の位置。右の余白は幅の4%、下の余白は高さの3%。印の左端は幅の約84%で、
# make-image-prompt.py が空けさせる右下の角（幅・高さとも約15%）にほぼ収まる。
PIN_STAMP = {"size_ratio": 0.028, "right_ratio": 0.96, "bottom_margin_ratio": 0.03}

# Pin画像（PNG）に入れる合成済みの目印（tEXtチャンク）。check-pin-image-style.py が読む。
PIN_STAMP_KEY = "kohaku-brand-stamp"
PIN_STAMP_VALUE = "1"


def load_brand_font(size):
    """ブランド表記用のフォントを読み込む。無ければ合成を飛ばさず exit 1 で止める。"""
    try:
        return ImageFont.truetype(BRAND_FONT_PATH, size)
    except OSError as exc:
        print(f"ブランド表記のフォントを読み込めません: {BRAND_FONT_PATH}（{exc}）")
        print("  「琥珀時間」を合成できないため、画像を書き出さずに中止しました。")
        sys.exit(1)


def stamp_brand(im, size_ratio, right_ratio, bottom_margin_ratio):
    """画像の右下に「琥珀時間」を合成した新しい画像を返す（元の画像は変更しない）。

    size_ratio は文字サイズ、right_ratio は印の右端の位置（どちらも画像の幅に対する割合）、
    bottom_margin_ratio は印の下の余白（画像の高さに対する割合）。
    """
    w, h = im.size
    size = max(12, round(w * size_ratio))
    font = load_brand_font(size)
    tracking = round(size * BRAND_TRACKING_RATIO)

    # 字間を空けるため1文字ずつ置く。右端・下端はインクの外形で合わせる。
    advances = [font.getlength(ch) for ch in BRAND_TEXT]
    total = round(sum(advances)) + tracking * (len(BRAND_TEXT) - 1)
    _, _, _, ink_bottom = font.getbbox(BRAND_TEXT)
    x0 = round(w * right_ratio) - total
    y0 = round(h * (1 - bottom_margin_ratio)) - ink_bottom

    def draw_text(layer, fill, stroke_width=0):
        d = ImageDraw.Draw(layer)
        x = x0
        for ch, adv in zip(BRAND_TEXT, advances):
            d.text((x, y0), ch, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=fill)
            x += adv + tracking

    shadow = Image.new("RGBA", im.size, BRAND_SHADOW + (0,))
    draw_text(shadow, BRAND_SHADOW + (BRAND_SHADOW_ALPHA,),
              stroke_width=max(1, round(size * BRAND_SHADOW_SPREAD_RATIO)))
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(1, size * BRAND_SHADOW_BLUR_RATIO)))
    text = Image.new("RGBA", im.size, BRAND_FILL + (0,))
    draw_text(text, BRAND_FILL + (255,))

    mode = im.mode if im.mode in ("RGB", "RGBA") else "RGB"
    out = Image.alpha_composite(im.convert("RGBA"), shadow)
    out = Image.alpha_composite(out, text)
    return out.convert(mode)


def hero_needs_stamp(src_path):
    """hero原本に合成するか（原本の更新日時が BRAND_STAMP_START 以降か）を返す。"""
    return os.path.getmtime(src_path) >= BRAND_STAMP_START.timestamp()


def pin_has_brand_stamp(path):
    """Pin画像（PNG）に合成済みの目印が入っているかを返す。開けない・PNGでない場合は False。"""
    try:
        with Image.open(path) as im:
            return im.format == "PNG" and im.text.get(PIN_STAMP_KEY) == PIN_STAMP_VALUE
    except OSError:
        return False


def stamp_pin(src_path, dst_path):
    """Pin画像に「琥珀時間」を合成し、目印つきのPNGを dst_path へ書き出す。

    失敗時は dst_path に何も残さず exit 1 する（書きかけは一時ファイルに出し、成功時だけ置き換える）。
    """
    if not os.path.isfile(src_path):
        print(f"入力画像が見つかりません: {src_path}")
        sys.exit(1)
    if os.path.splitext(dst_path)[1].lower() != ".png":
        print(f"出力先はPNGにしてください（目印をPNGのtEXtチャンクへ入れるため）: {dst_path}")
        sys.exit(1)
    if pin_has_brand_stamp(src_path):
        print(f"入力画像は既に「{BRAND_TEXT}」を合成済みです（二重に合成しません）: {src_path}")
        print("  合成前の原本（~/Downloads または output/Pin-images-original/）を入力にしてください。")
        sys.exit(1)

    with Image.open(src_path) as src:
        icc = src.info.get("icc_profile")
        im = src.convert("RGBA" if src.mode == "RGBA" else "RGB")
    out = stamp_brand(im, **PIN_STAMP)

    meta = PngImagePlugin.PngInfo()
    meta.add_text(PIN_STAMP_KEY, PIN_STAMP_VALUE)
    tmp = dst_path + ".tmp"
    try:
        out.save(tmp, "PNG", pnginfo=meta, icc_profile=icc)
        if not pin_has_brand_stamp(tmp):
            raise OSError("書き出したPNGから目印を読み戻せませんでした")
        os.replace(tmp, dst_path)
    except OSError as exc:
        if os.path.exists(tmp):
            os.remove(tmp)
        print(f"「{BRAND_TEXT}」の合成に失敗しました: {exc}")
        sys.exit(1)
    print(f"「{BRAND_TEXT}」を合成しました（{out.size[0]}x{out.size[1]}・目印 {PIN_STAMP_KEY}）: {dst_path}")


def convert(src_path, slug, guard_aspect=False):
    dst_dir = os.path.join(OUT_DIR, slug)
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, "hero.webp")
    dst_thumb = os.path.join(dst_dir, "thumb.webp")

    before = os.path.getsize(src_path)
    src_im = Image.open(src_path).convert("RGB")
    ow, oh = src_im.size
    if guard_aspect:
        check_aspect_or_exit(src_path, ow, oh)
    # 中央基準でクロップしつつ縮小（元画像は周囲に余白があるため中央固定で問題ない）
    im = ImageOps.fit(src_im, TARGET, method=Image.LANCZOS, centering=(0.5, 0.5))
    # 「琥珀時間」は切り抜き・縮小の後に合成する（位置と大きさを出力寸法の基準で揃えるため・D-0274）
    stamped = hero_needs_stamp(src_path)
    if stamped:
        im = stamp_brand(im, **HERO_STAMP)
    im.save(dst, "WEBP", quality=QUALITY, method=6)
    after = os.path.getsize(dst)

    # サムネは原本から直接縮小する（hero.webpの再エンコードを避けるため。「琥珀時間」は入れない）
    thumb = ImageOps.fit(src_im, THUMB, method=Image.LANCZOS, centering=(0.5, 0.5))
    thumb.save(dst_thumb, "WEBP", quality=THUMB_QUALITY, method=6)
    after_thumb = os.path.getsize(dst_thumb)

    print(
        f"{slug:32} {ow}x{oh} {before/1048576:5.2f}MB "
        f"-> hero {TARGET[0]}x{TARGET[1]} {after/1024:6.1f}KB "
        f"/ thumb {THUMB[0]}x{THUMB[1]} {after_thumb/1024:5.1f}KB  "
        f"{100*(1-after/before):5.1f}%減"
    )
    print(f"  配置先: {dst}")
    print(f"        : {dst_thumb}")
    print(
        f"  「{BRAND_TEXT}」: "
        + ("heroに合成した" if stamped else
           f"合成なし（原本の更新日時が {BRAND_STAMP_START:%Y-%m-%d %H:%M} より前）")
    )
    print(f"  frontmatter: hero: /images/{slug}/hero.webp")
    return after + after_thumb


def convert_category(src_path, slug):
    """テーマ一覧のカード画像（1200x675・16:9）を書き出す。hero/thumbとは別系統。"""
    os.makedirs(CATEGORY_DIR, exist_ok=True)
    dst = os.path.join(CATEGORY_DIR, f"{slug}.webp")

    before = os.path.getsize(src_path)
    src_im = Image.open(src_path).convert("RGB")
    ow, oh = src_im.size
    im = ImageOps.fit(src_im, CATEGORY_TARGET, method=Image.LANCZOS, centering=(0.5, 0.5))
    im.save(dst, "WEBP", quality=CATEGORY_QUALITY, method=6)
    after = os.path.getsize(dst)

    print(
        f"{slug:32} {ow}x{oh} {before/1048576:5.2f}MB "
        f"-> category {CATEGORY_TARGET[0]}x{CATEGORY_TARGET[1]} {after/1024:6.1f}KB  "
        f"{100*(1-after/before):5.1f}%減"
    )
    print(f"  配置先: {dst}")
    print(f"  参照パス: /images/categories/{slug}.webp")
    return after


def main():
    args = sys.argv[1:]

    if args[:1] == ["--stamp-pin"]:
        # Pinのファイル名はcp932に無い文字を含みうるため、この経路だけ出力をUTF-8に寄せる
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        if len(args) != 3:
            print(__doc__)
            sys.exit(1)
        stamp_pin(args[1], args[2])
        return

    if args[:1] == ["--category"]:
        if len(args) != 3:
            print(__doc__)
            sys.exit(1)
        src, slug = args[1], args[2]
        if not os.path.isfile(src):
            print(f"入力画像が見つかりません: {src}")
            sys.exit(1)
        if not re.fullmatch(r"[a-z0-9-]+", slug):
            print(f"カテゴリslugは英小文字・数字・ハイフンのみ: {slug}")
            sys.exit(1)
        convert_category(src, slug)
        return

    if args[:1] == ["--all"]:
        total = 0
        flagged = []  # 縦長ガード該当（変換はする・表示のみ。D-0148）
        for fn in sorted(os.listdir(SRC_DIR)):
            if not fn.endswith(".png"):
                continue
            # 拡張子を先に落としてから分割する（カッコを含まないファイル名の原本にも対応）
            slug = re.split(r"[（(]", os.path.splitext(fn)[0])[0].strip()
            if not os.path.isdir(os.path.join(OUT_DIR, slug)):
                continue  # 記事heroでないPNGは飛ばす
            src_path = os.path.join(SRC_DIR, fn)
            with Image.open(src_path) as probe:
                pw, ph = probe.size
            if aspect_ng(pw, ph):
                flagged.append((fn, pw, ph))
            total += convert(src_path, slug)
        print(f"\n合計 {total/1024:.1f}KB")
        if flagged:
            print(
                f"\n【注意】縦長または横縦比{MIN_ASPECT}未満の原本が{len(flagged)}件あります"
                "（一括再生成のため変換は実施済み。中央クロップで上下が切れている可能性）:"
            )
            for fn, pw, ph in flagged:
                print(f"  {fn}  {pw}x{ph}（横縦比 {pw/ph:.2f}）")
        return

    if len(args) != 2:
        print(__doc__)
        sys.exit(1)

    src, slug = args
    if not os.path.isfile(src):
        print(f"入力画像が見つかりません: {src}")
        sys.exit(1)
    if not re.fullmatch(r"[a-z0-9-]+", slug):
        print(f"slugは英小文字・数字・ハイフンのみ: {slug}")
        sys.exit(1)
    convert(src, slug, guard_aspect=True)


if __name__ == "__main__":
    main()
