"""output/Pin-images/ 配下のPin画像の寸法・カラーモードを表示する。

Pinterest推奨比率（縦長2:3）通りに生成されているかの確認用。

使い方:
  python site/scripts/check-pin-image-dimensions.py <ファイル名> [<ファイル名> ...]
    ファイル名は output/Pin-images/ からの相対名（例: pin-48-xxx-01.png）
"""

import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(ROOT, "output", "Pin-images")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    for name in args:
        path = os.path.join(SRC_DIR, name)
        if not os.path.isfile(path):
            print(f"見つかりません: {path}")
            continue
        im = Image.open(path)
        w, h = im.size
        ratio = w / h
        note = "○ 縦長2:3に近い" if abs(ratio - 2 / 3) < 0.03 else "△ 2:3から外れている"
        print(f"{name:48} {w}x{h} mode={im.mode}  比率={ratio:.3f}  {note}")


if __name__ == "__main__":
    main()
