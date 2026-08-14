# -*- coding: utf-8 -*-
r"""公開済み（status: published）記事のうち、ピンが1枚も作られていないものを
機械検知する（読み取り専用・フェーズD・T4・D-0120）。

判定方式:
  - site/src/content/posts/ の各記事は、先頭20行程度のみを読み frontmatterの
    `status: published` の有無を判定する（本文全体は読まない。記事数が増えても
    処理量が膨らまないようにするため）。
  - output/pins/ はファイル名の一覧のみを使い、ファイル内容は読まない。
    ファイル名からslugを抽出する規則（実在するファイル名から導出・
    check-pin-posting-status.pyのPIN_NUM_REと同型のアプローチ）:
      "YYYY-MM-DD-pin-<番号>(-<番号>)?-<slug>-<2桁の連番>.md" の形に一致する
      ファイルのみ <slug> 部分を抽出する。この形に一致しないファイル名
      （末尾に2桁の連番が無い等）は「抽出不能」として【警告】で報告する
      （2026-07-20頃の初期のピンファイルの一部がこれに該当する。抽出できた
      slugのみで判定するため、これらは判定対象から漏れる可能性があり、
      その分は過剰報告の方向へ倒す設計とする）。
  - 抽出できたslugの集合と、公開済み記事のslugを突き合わせ、集合に無い記事を
    「ピン未作成」として検知する。

出力:
  - 検知0件: "PUBLISHED_PINS_OK" の1行のみ。
  - 検知あり: 行頭に【警告】を付けた行。対象は最大10件まで＋残件数を表示する。
  - slug抽出不能なピンファイルがあった場合も【警告】として別途報告する
    （最大10件まで＋残件数）。

終了コード:
  0: 正常に判定できた場合（検知の有無を問わない）
  1: site/src/content/posts/ が存在しない等、前提が不成立の場合

session-start-check.py の子スクリプトとして登録する（正常とみなす終了コード: {0}）。

使い方:
  python site/scripts/check-published-pins-missing.py
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POSTS_DIR = os.path.join(ROOT, "site", "src", "content", "posts")
PINS_DIR = os.path.join(ROOT, "output", "pins")

FRONTMATTER_HEAD_LINES = 20
MAX_REPORT_ITEMS = 10

STATUS_RE = re.compile(r"^status:\s*(\S+)\s*$")
PIN_FILENAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-pin-\d+(?:-\d+)?-(.+)-\d{2}\.md$")


def get_published_slugs():
    """{slug: filename} を返す。status: published の記事のみ。"""
    published = {}
    for fname in sorted(os.listdir(POSTS_DIR)):
        if not fname.endswith(".md"):
            continue
        path = os.path.join(POSTS_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                head_lines = [next(f, "") for _ in range(FRONTMATTER_HEAD_LINES)]
        except OSError:
            continue
        is_published = any(
            STATUS_RE.match(line.strip()) and STATUS_RE.match(line.strip()).group(1) == "published"
            for line in head_lines
        )
        if is_published:
            slug = fname[:-3]  # 拡張子.mdを除いたものをslugとみなす（rules/portability.md規約）
            published[slug] = fname
    return published


def extract_pin_slugs():
    """(抽出できたslugの集合, 抽出不能だったファイル名のリスト) を返す。"""
    slugs = set()
    unrecognized = []
    if not os.path.isdir(PINS_DIR):
        return slugs, unrecognized
    for fname in sorted(os.listdir(PINS_DIR)):
        if not fname.endswith(".md"):
            continue
        m = PIN_FILENAME_RE.match(fname)
        if m:
            slugs.add(m.group(1))
        else:
            unrecognized.append(fname)
    return slugs, unrecognized


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if not os.path.isdir(POSTS_DIR):
        print("【エラー】site/src/content/posts/ が見つかりません（%s）" % POSTS_DIR)
        sys.exit(1)

    published = get_published_slugs()
    pin_slugs, unrecognized = extract_pin_slugs()

    missing = sorted(slug for slug in published if slug not in pin_slugs)

    output_lines = []

    if missing:
        shown = missing[:MAX_REPORT_ITEMS]
        for slug in shown:
            output_lines.append("【警告】公開済み記事にピンが1枚も見つかりません: %s（%s）" % (
                slug, published[slug]))
        rest = len(missing) - len(shown)
        if rest > 0:
            output_lines.append("【警告】ほか%d件、ピン未作成の可能性がある公開済み記事があります" % rest)

    if unrecognized:
        shown_u = unrecognized[:MAX_REPORT_ITEMS]
        for fname in shown_u:
            output_lines.append("【警告】output/pins/のファイル名からslugを抽出できませんでした: %s" % fname)
        rest_u = len(unrecognized) - len(shown_u)
        if rest_u > 0:
            output_lines.append("【警告】ほか%d件、slug抽出不能なピンファイルがあります" % rest_u)

    if not output_lines:
        print("PUBLISHED_PINS_OK")
        sys.exit(0)

    for line in output_lines:
        print(line)
    sys.exit(0)


if __name__ == "__main__":
    main()
