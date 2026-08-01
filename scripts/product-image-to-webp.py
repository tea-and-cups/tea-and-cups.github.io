"""商品画像URL（楽天商品検索APIのmediumImageUrls）をダウンロードし、記事用の正方形WebPに変換する。

背景（試行運用・新規記事限定・D-0047）:
  fetch-rakuten-products.pyで取得したmediumImageUrlsは、もしもアフィリエイトの
  「かんたんリンク作成」が生成する画像URLと同一CDN（thumbnail.image.rakuten.co.jp・
  R-Cabinet）・同一URL体系であることを確認済み（reports/2026-08-02.md参照）。

  商品ごとに縦横比がバラバラなため、そのまま並べるとレイアウトが崩れる。
  hero-to-webp.pyと同じ考え方で固定サイズ・固定比率のWebPに統一する。
  ただしhero画像と異なり、商品写真は中央基準クロップ（ImageOps.fit）を使わない。
  楽天ガイドラインの画像加工禁止事項（部分切り取り・文字追加の禁止）に対応するため、
  画像全体を保持したまま余白を足す方式（ImageOps.pad）で正方形化する。

使い方:
  python site/scripts/product-image-to-webp.py <画像URL> <slug> <連番>
      画像をダウンロードして output/product-images/ に原本を残し、
      site/public/images/<slug>/products/<連番>.webp（600x600）を書き出す。
      連番は記事内の商品掲載順（1, 2, 3...）。

python本体はPATH上の `python`（Windows版Python 3.12系）を想定している。
CLAUDE.md 11節のとおり、呼び出しは常にプロジェクトルートからの相対パスで行う。

失敗時の挙動:
  ダウンロード失敗（404・タイムアウト等）や画像デコード失敗（壊れたレスポンス等）は
  トレースバックを出さず、明確な日本語メッセージで終了コード1を返す。この1商品の
  画像だけをスキップし、本文はテキストリンクのみ（画像なし）で続行してよい
  （試行運用・D-0047。記事作成セッション全体を止める必要はない。CLAUDE.md 5節参照）。
"""

import os
import re
import sys
import urllib.error
import urllib.request

from PIL import Image, ImageOps, UnidentifiedImageError

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(ROOT, "output", "product-images")
OUT_DIR = os.path.join(ROOT, "site", "public", "images")

TARGET = (600, 600)  # 正方形固定。CLSを防ぐため商品ごとに統一する
QUALITY = 85
PAD_COLOR = (255, 255, 255)  # 楽天の商品画像は白背景が大半のため、余白も白に揃える

USER_AGENT = "Mozilla/5.0 (compatible; kohaku-jikan-product-image-fetch/1.0)"


SKIP_HINT = "この商品の画像はスキップし、本文はテキストリンクのみ（画像なし）で続行してください（試行運用・D-0047）。"


def download(url, dst_path):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as res, open(dst_path, "wb") as f:
            f.write(res.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"画像ダウンロード失敗（HTTPエラー {e.code}）: {url}\n{SKIP_HINT}")
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        sys.exit(f"画像ダウンロード失敗（通信エラー: {e}）: {url}\n{SKIP_HINT}")


def convert(url, slug, seq):
    os.makedirs(SRC_DIR, exist_ok=True)
    ext = os.path.splitext(url.split("?")[0])[1] or ".jpg"
    src_path = os.path.join(SRC_DIR, f"{slug}-{seq}{ext}")
    download(url, src_path)

    dst_dir = os.path.join(OUT_DIR, slug, "products")
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, f"{seq}.webp")

    before = os.path.getsize(src_path)
    try:
        src_im = Image.open(src_path).convert("RGB")
        ow, oh = src_im.size
        # 部分切り取りをしないため、fit（クロップ）ではなくpad（余白追加）で正方形化する
        im = ImageOps.pad(src_im, TARGET, method=Image.LANCZOS, color=PAD_COLOR, centering=(0.5, 0.5))
        im.save(dst, "WEBP", quality=QUALITY, method=6)
    except (UnidentifiedImageError, OSError) as e:
        os.remove(src_path)  # 壊れた原本を残さない
        sys.exit(f"画像デコード失敗（{e}）。ダウンロードした内容が画像として不正です: {url}\n{SKIP_HINT}")
    after = os.path.getsize(dst)

    print(
        f"{slug}-{seq:<4} {ow}x{oh} {before/1024:6.1f}KB "
        f"-> {TARGET[0]}x{TARGET[1]} {after/1024:6.1f}KB"
    )
    print(f"  原本: {src_path}")
    print(f"  配置先: {dst}")
    print(f"  本文参照パス: /images/{slug}/products/{seq}.webp")
    return dst


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    args = sys.argv[1:]
    if len(args) != 3:
        print(__doc__)
        sys.exit(1)

    url, slug, seq = args
    if not re.fullmatch(r"[a-z0-9-]+", slug):
        sys.exit(f"slugは英小文字・数字・ハイフンのみ: {slug}")
    if not re.fullmatch(r"[0-9]+", seq):
        sys.exit(f"連番は数字のみ: {seq}")
    if not url.startswith("https://"):
        sys.exit(f"画像URLが空欄またはhttps://で始まっていません: {url!r}\n{SKIP_HINT}")

    convert(url, slug, seq)


if __name__ == "__main__":
    main()
