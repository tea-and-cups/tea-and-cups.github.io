"""Pin画像のファイル名規則（rules/image-generation-flow.md 1-2・D-0058）を機械確認する。

確認内容:
  1. output/Pin-images/ 配下のうち「ピン{数字}」で始まるファイル名が、
     新命名規則の正規表現パターンに完全に合致しているか
     （形式: ピン{番号} {説明}（誘導先 {誘導先名}）.拡張子）
  2. output/pins/ 配下の投稿文ファイルが持つPin番号と、
     output/Pin-images/ 配下の新形式ファイルが持つPin番号が一致しているか
     （投稿文はあるのに対応する画像が見つからない番号を検出する）

D-0058より前に作成された旧形式ファイル（pin-連番-slug-枝番.png 等、「ピン」で
始まらないもの）はリネーム対象外のため、本スクリプトでは「legacy（スキップ）」
として件数のみ表示し、NG扱いにしない。同様に、投稿文とのPin番号突き合わせも
D-0058適用開始（ピン75〜）以降の番号のみを対象とし、それより前の番号は
チェック対象外とする（PIN_NUMBER_CUTOVER定数）。

使い方:
  python site/scripts/check-pin-image-naming.py
  （引数なし。output/Pin-images/ と output/pins/ を全件走査する）
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PIN_IMAGES_DIR = os.path.join(ROOT, "output", "Pin-images")
PINS_DIR = os.path.join(ROOT, "output", "pins")

NEW_FORMAT_RE = re.compile(
    r"^ピン(?P<num>\d+)\s+(?P<desc>.+?)"
    r"（誘導先\s+(?P<dest>.+?)）"
    r"\.(?P<ext>png|jpg|jpeg|webp)$"
)
STARTS_LIKE_NEW_RE = re.compile(r"^ピン\d+")
PIN_MD_NUM_RE = re.compile(r"-pin-(\d+)-")

# D-0058（2026-08-04）で新命名規則を適用したのはピン75以降。
# それより前の番号は既存ファイルのリネーム対象外（rules/image-generation-flow.md 1-2）のため
# 番号突き合わせチェックの対象からも除外する。
PIN_NUMBER_CUTOVER = 75


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if not os.path.isdir(PIN_IMAGES_DIR):
        print(f"見つかりません: {PIN_IMAGES_DIR}")
        sys.exit(1)

    ng = []
    ok_count = 0
    legacy_count = 0
    image_nums = {}

    for name in sorted(os.listdir(PIN_IMAGES_DIR)):
        path = os.path.join(PIN_IMAGES_DIR, name)
        if not os.path.isfile(path):
            continue
        if not STARTS_LIKE_NEW_RE.match(name):
            legacy_count += 1
            continue
        m = NEW_FORMAT_RE.match(name)
        if not m:
            ng.append((name, "「ピン{数字}」で始まるが命名規則の形式に一致しない"))
            continue
        num = int(m.group("num"))
        ok_count += 1
        image_nums.setdefault(num, []).append(name)

    print("=== 1. ファイル名規則チェック ===")
    print(f"新形式に合致: {ok_count}件 / legacy（スキップ対象・チェック対象外）: {legacy_count}件")
    if ng:
        print(f"NG: {len(ng)}件")
        for name, reason in ng:
            print(f"  [NG] {name}\n       理由: {reason}")
    else:
        print("NG: 0件")

    print()
    print("=== 2. 投稿文とのPin番号突き合わせ ===")
    if not os.path.isdir(PINS_DIR):
        print(f"見つかりません: {PINS_DIR}")
        sys.exit(1)

    expected_nums = {}
    skipped_legacy_pins = 0
    for name in sorted(os.listdir(PINS_DIR)):
        if not name.endswith(".md"):
            continue
        m = PIN_MD_NUM_RE.search(name)
        if not m:
            continue
        num = int(m.group(1))
        if num < PIN_NUMBER_CUTOVER:
            skipped_legacy_pins += 1
            continue
        expected_nums.setdefault(num, name)

    print(f"チェック対象: ピン{PIN_NUMBER_CUTOVER}以降（それより前は対象外・{skipped_legacy_pins}件スキップ）")

    missing = sorted(n for n in expected_nums if n not in image_nums)
    extra = sorted(n for n in image_nums if n not in expected_nums)

    if missing:
        print(f"投稿文はあるが対応する画像が見つからない番号: {len(missing)}件")
        for n in missing:
            print(f"  [NG] ピン{n}（{expected_nums[n]}）に対応する新形式の画像ファイルがありません")
    else:
        print("投稿文と画像の番号は一致（不足なし）")

    if extra:
        print(f"画像はあるが対応する投稿文が見つからない番号（参考・NG扱いしない）: {extra}")

    print()
    total_ng = len(ng) + len(missing)
    if total_ng:
        print(f"総合: NG（{total_ng}件）")
        sys.exit(1)
    else:
        print("総合: OK")


if __name__ == "__main__":
    main()
