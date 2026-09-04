# -*- coding: utf-8 -*-
r"""Pin画像を「SNS送信用の公開JPEG」へ変換して site/public/pin-images/ へ置く。

`python site/scripts/publish-pin-images.py 196 197 198`（ピン番号を1つ以上）

背景:
  Buffer経由でX・Instagram・Threadsへ画像を送るには、公開URLで到達できる画像が要る
  （https://developers.buffer.com/guides/hosting-media.html：認証なしで到達できる
  URLであること）。Pin画像の正本はPinterest向けの2:3のままにしておきたいので、
  正本には一切触れず、送信用の複製をここで作る。

変換仕様:
  - 比率が2:3（許容±2%）でなければ変換せず終了コード1で止める
    （想定外の比率の画像が公開へ混ざるのを機械的に防ぐため）
  - 高さは変えず、幅を「高さ×0.75」まで左右均等に拡張して3:4にする。
    拡張部分は単色 #F7F1E8 で塗る。**切り取りは一切行わない**
    （上下に焼き込まれた見出し文言とCTA帯を欠けさせないため）
  - その後 1080×1440 へ LANCZOS でリサンプルし、JPEG quality=88 / optimize=True

保持件数:
  公開先に残すのは番号の降順で KEEP_LIMIT 件まで。超過分は削除する。
  各SNSは投稿時に画像を自社側へ取り込むため、URLは投稿の瞬間だけ生きていればよい。
  全件を永久保持するとリポジトリが記事数に比例して肥大するため上限を設ける。
  **KEEP_LIMIT はスクリプト内の定数であり、引数では変えられない。**

正本（output/Pin-images/ のPNG）は読むだけで、一切変更しない。
"""

import os
import re
import sys

from PIL import Image

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
SOURCE_DIR = os.path.join(PROJECT_ROOT, "output", "Pin-images")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "site", "public", "pin-images")
PUBLIC_URL_BASE = "https://kohaku-jikan.com/pin-images"

# 正本に期待する比率（幅÷高さ）と許容誤差。
SOURCE_ASPECT = 2.0 / 3.0
ASPECT_TOLERANCE = 0.02

# 出力仕様。
TARGET_ASPECT = 3.0 / 4.0
OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1440
PAD_COLOR = (0xF7, 0xF1, 0xE8)
JPEG_QUALITY = 88

# 公開先に残す件数の上限（定数・引数で変えない）。
KEEP_LIMIT = 60

OUTPUT_NAME_RE = re.compile(r"^pin(\d+)\.jpg$")


def find_source(number):
    """`ピン{番号} ` で始まるPNGを1件特定する。0件・2件以上は None を返す。"""
    prefix = "ピン%d " % number
    matches = sorted(
        name for name in os.listdir(SOURCE_DIR)
        if name.startswith(prefix) and name.lower().endswith(".png")
    )
    if len(matches) != 1:
        return None, matches
    return os.path.join(SOURCE_DIR, matches[0]), matches


def convert(source_path, dest_path):
    """2:3のPNGを 3:4・1080×1440 のJPEGへ変換する。戻り値は (元寸法, 出力寸法, バイト数)。"""
    with Image.open(source_path) as image:
        source_size = image.size
        width, height = source_size
        aspect = float(width) / float(height)
        if abs(aspect / SOURCE_ASPECT - 1.0) > ASPECT_TOLERANCE:
            raise ValueError(
                "比率が2:3（許容±%.0f%%）ではありません: %dx%d（幅÷高さ=%.4f・期待%.4f）"
                % (ASPECT_TOLERANCE * 100, width, height, aspect, SOURCE_ASPECT)
            )

        rgb = image.convert("RGB")
        # 高さは変えず、幅だけ左右均等に広げる（切り取りは行わない）。
        padded_width = int(round(height * TARGET_ASPECT))
        canvas = Image.new("RGB", (padded_width, height), PAD_COLOR)
        canvas.paste(rgb, ((padded_width - width) // 2, 0))
        resized = canvas.resize((OUTPUT_WIDTH, OUTPUT_HEIGHT), Image.LANCZOS)
        resized.save(dest_path, "JPEG", quality=JPEG_QUALITY, optimize=True)

    return source_size, (OUTPUT_WIDTH, OUTPUT_HEIGHT), os.path.getsize(dest_path)


def select_files_to_delete(names, limit=KEEP_LIMIT):
    """pin{番号}.jpg の名前一覧から、番号降順で上位limit件を残した残りを返す。

    ファイルシステムに触らない純粋関数。命名規則に合わない名前は対象外
    （このスクリプトが作っていないファイルを消さないため）。
    """
    numbered = []
    for name in names:
        match = OUTPUT_NAME_RE.match(name)
        if match:
            numbered.append((int(match.group(1)), name))
    numbered.sort(key=lambda item: item[0], reverse=True)
    return [name for _, name in numbered[limit:]]


def prune():
    """公開先を KEEP_LIMIT 件まで刈り込む。削除したファイル名の一覧を返す。"""
    doomed = select_files_to_delete(os.listdir(OUTPUT_DIR))
    for name in doomed:
        os.remove(os.path.join(OUTPUT_DIR, name))
    return doomed


def main(argv):
    if not argv:
        sys.stderr.write(
            "使い方: python site/scripts/publish-pin-images.py <ピン番号> [ピン番号...]\n"
        )
        return 1

    numbers = []
    for arg in argv:
        if not arg.isdigit():
            sys.stderr.write("ピン番号は正の整数で指定してください: %s\n" % arg)
            return 1
        numbers.append(int(arg))

    if not os.path.isdir(SOURCE_DIR):
        sys.stderr.write("正本ディレクトリがありません: %s\n" % SOURCE_DIR)
        return 1
    if not os.path.isdir(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print("作成: %s" % OUTPUT_DIR)

    skipped = []
    converted = 0
    for number in numbers:
        source_path, matches = find_source(number)
        if source_path is None:
            reason = "0件" if not matches else "%d件（%s）" % (len(matches), " / ".join(matches))
            print("スキップ: ピン%d — 正本PNGが%s。1件に特定できません。" % (number, reason))
            skipped.append(number)
            continue

        dest_path = os.path.join(OUTPUT_DIR, "pin%d.jpg" % number)
        try:
            source_size, out_size, size_bytes = convert(source_path, dest_path)
        except ValueError as exc:
            sys.stderr.write("エラー: ピン%d — %s\n" % (number, exc))
            sys.stderr.write("変換を行わず終了します（正本は変更していません）。\n")
            return 1

        print(
            "変換: ピン%d  %dx%d → %dx%d  %d bytes  %s/pin%d.jpg"
            % (
                number,
                source_size[0], source_size[1],
                out_size[0], out_size[1],
                size_bytes,
                PUBLIC_URL_BASE, number,
            )
        )
        print("      正本: %s" % os.path.basename(source_path))
        converted += 1

    deleted = prune()
    print()
    print("=== 保持件数の整理（上限 %d 件・番号降順） ===" % KEEP_LIMIT)
    if deleted:
        for name in deleted:
            print("  削除: %s" % name)
    else:
        print("  削除なし（現在 %d 件）" % len(
            [n for n in os.listdir(OUTPUT_DIR) if OUTPUT_NAME_RE.match(n)]
        ))

    print()
    print("変換 %d 件 / スキップ %d 件 / 削除 %d 件" % (converted, len(skipped), len(deleted)))
    return 1 if skipped else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
