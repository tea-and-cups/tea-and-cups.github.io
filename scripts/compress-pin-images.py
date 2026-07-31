"""output/Pin-images/ 配下のPin画像をJPEG quality88に変換し、_compressed/ へ出力する。

背景: ChatGPT生成のPin画像（PNG・1枚2〜2.6MB）を複数枚そのままArtifactへ埋め込むと
16MB上限を超える（2026-07-31実測・3枚で19MB）。JPEG quality88に変換すると
1枚あたり230〜300KB程度まで縮み、画質もArtifact上のプレビュー・保存用途としては
十分保たれることを確認済み。

使い方:
  python site/scripts/compress-pin-images.py <ファイル名> [<ファイル名> ...]
    ファイル名は output/Pin-images/ からの相対名（例: pin-48-xxx-01.png）
    出力先: output/Pin-images/_compressed/<同名の拡張子違い>.jpg
"""

import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(ROOT, "output", "Pin-images")
OUT_DIR = os.path.join(SRC_DIR, "_compressed")
QUALITY = 88


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    os.makedirs(OUT_DIR, exist_ok=True)

    for name in args:
        src = os.path.join(SRC_DIR, name)
        if not os.path.isfile(src):
            print(f"見つかりません: {src}")
            continue
        base, _ext = os.path.splitext(name)
        dst = os.path.join(OUT_DIR, base + ".jpg")

        before = os.path.getsize(src)
        im = Image.open(src).convert("RGB")
        im.save(dst, "JPEG", quality=QUALITY, optimize=True)
        after = os.path.getsize(dst)

        print(f"{name:48} {before/1024:7.1f}KB -> {after/1024:7.1f}KB  ({100*(1-after/before):4.1f}%減)")
        print(f"  出力先: {dst}")


if __name__ == "__main__":
    main()
