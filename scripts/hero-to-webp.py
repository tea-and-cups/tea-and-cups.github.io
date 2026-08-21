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

from PIL import Image, ImageOps

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
    im.save(dst, "WEBP", quality=QUALITY, method=6)
    after = os.path.getsize(dst)

    # サムネは原本から直接縮小する（hero.webpの再エンコードを避けるため）
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
