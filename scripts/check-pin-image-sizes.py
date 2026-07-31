"""output/Pin-images/ 配下のPin画像のファイルサイズを表示する。

Artifact公開前にファイルサイズを把握する用途（Artifactは1公開あたり16MB上限のため、
複数枚を埋め込む前にサイズの見当をつける）。

使い方:
  python site/scripts/check-pin-image-sizes.py <ファイル名> [<ファイル名> ...]
    ファイル名は output/Pin-images/ からの相対名（例: pin-48-xxx-01.png）
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(ROOT, "output", "Pin-images")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    total = 0
    for name in args:
        path = os.path.join(SRC_DIR, name)
        if not os.path.isfile(path):
            print(f"見つかりません: {path}")
            continue
        size = os.path.getsize(path)
        total += size
        print(f"{name:48} {size/1024:8.1f}KB")

    print(f"合計 {total/1024/1024:.2f}MB")


if __name__ == "__main__":
    main()
