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
      output/hero-images/*.png をすべて再変換する（ファイル名の「（」より前をslugとみなす）。
      画質設定を見直したときの一括やり直し用。

python本体のパス（この環境）:
  C:\\Users\\shash\\AppData\\Local\\Programs\\Python\\Python312\\python.exe
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


def convert(src_path, slug):
    dst_dir = os.path.join(OUT_DIR, slug)
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, "hero.webp")
    dst_thumb = os.path.join(dst_dir, "thumb.webp")

    before = os.path.getsize(src_path)
    src_im = Image.open(src_path).convert("RGB")
    ow, oh = src_im.size
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


def main():
    args = sys.argv[1:]

    if args[:1] == ["--all"]:
        total = 0
        for fn in sorted(os.listdir(SRC_DIR)):
            if not fn.endswith(".png"):
                continue
            slug = re.split(r"[（(]", fn)[0].strip()
            if not os.path.isdir(os.path.join(OUT_DIR, slug)):
                continue  # 記事heroでないPNGは飛ばす
            total += convert(os.path.join(SRC_DIR, fn), slug)
        print(f"\n合計 {total/1024:.1f}KB")
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
    convert(src, slug)


if __name__ == "__main__":
    main()
