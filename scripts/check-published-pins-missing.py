# -*- coding: utf-8 -*-
r"""公開済み（status: published）記事のうち、ピンが1枚も作られていないものを
機械検知する（読み取り専用・D-0120／2段構え化・D-0121）。

判定方式（2段構え）:
  - site/src/content/posts/ の各記事は、先頭20行程度のみを読み frontmatterの
    `status: published` の有無を判定する（本文全体は読まない。記事数が増えても
    処理量が膨らまないようにするため）。
  - 第1段（安い処理・毎回実行）: output/pins/ のファイル名一覧のみを使い、
    ファイル内容は読まない。ファイル名からslugを抽出する規則（実在する
    ファイル名から導出・check-pin-posting-status.pyのPIN_NUM_REと同型の
    アプローチ）:
      "YYYY-MM-DD-pin-<番号>(-<番号>)?-<slug>-<2桁の連番>.md" の形に一致する
      ファイルのみ <slug> 部分を抽出する。この形に一致しないファイル名
      （末尾に2桁の連番が無い等）は「抽出不能」として別途報告する。
    ここで全公開済み記事にピンが見つかれば、第2段は実行せず終了する。
  - 第2段（高い処理・第1段で取りこぼしがあったときだけ実行）: 第1段で
    ピンが見つからなかった記事が1本でもある場合に限り、対象を絞って
    output/pins/ の各ピンファイルの先頭80行を読み、"https://tea-and-cups.
    github.io/posts/<slug>/" 形式の誘導先URLからslugを抽出する（パス
    /posts/ の直後から1階層）。ここで見つかったslugは「ピンあり」として
    扱い、取りこぼした記事と再照合する。
    対象の絞り込み（D-0122）: 第1段でファイル名から抽出したslugが
    published記事のslugのいずれかと一致したファイルは、そのピンが
    どの記事のものかすでに確定しているため本文を読まない。一致しな
    かったファイル（抽出不能を含む）だけを本文読み取りの対象とする。
    判定の正本は本文の誘導先URLであり、ファイル名は処理を軽くするための
    下調べに過ぎない。最近のピンはファイル名に正式slugをそのまま使って
    いるため、通常のセッションでは第2段の対象は過去の非準拠ファイルの
    みに固定され、記事数が増えても読み取り量は増えない。
  - 第2段まで実行してもファイル名・本文URLのどちらからもslugを判別
    できなかったピンファイルは「判定不能」として【警告】で別途報告する
    （沈黙で握りつぶさないため）。

出力:
  - 検知0件: "PUBLISHED_PINS_OK" の1行のみ。
  - 検知あり: 行頭に【警告】を付けた行。対象は最大10件まで＋残件数を表示する。
  - slug判定不能なピンファイルがあった場合も【警告】として別途報告する
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
PIN_BODY_HEAD_LINES = 80

STATUS_RE = re.compile(r"^status:\s*(\S+)\s*$")
PIN_FILENAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-pin-\d+(?:-\d+)?-(.+)-\d{2}\.md$")
PIN_BODY_URL_RE = re.compile(r"https://tea-and-cups\.github\.io/posts/([^/\s]+)/")


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


def list_pin_filenames():
    if not os.path.isdir(PINS_DIR):
        return []
    return [f for f in sorted(os.listdir(PINS_DIR)) if f.endswith(".md")]


def extract_pin_slugs_from_filenames(pin_filenames):
    """(ファイル名から抽出できたslugの集合, 抽出不能だったファイル名のリスト,
    {ファイル名: 抽出できたslug} の辞書) を返す。"""
    slugs = set()
    unrecognized = []
    filename_slug = {}
    for fname in pin_filenames:
        m = PIN_FILENAME_RE.match(fname)
        if m:
            slugs.add(m.group(1))
            filename_slug[fname] = m.group(1)
        else:
            unrecognized.append(fname)
    return slugs, unrecognized, filename_slug


def extract_slug_from_body(fname):
    """ピンファイル先頭PIN_BODY_HEAD_LINES行の誘導先URLからslugを抽出する。
    見つからなければ None。"""
    path = os.path.join(PINS_DIR, fname)
    try:
        with open(path, "r", encoding="utf-8") as f:
            head_lines = [next(f, "") for _ in range(PIN_BODY_HEAD_LINES)]
    except OSError:
        return None
    for line in head_lines:
        m = PIN_BODY_URL_RE.search(line)
        if m:
            return m.group(1)
    return None


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if not os.path.isdir(POSTS_DIR):
        print("【エラー】site/src/content/posts/ が見つかりません（%s）" % POSTS_DIR)
        sys.exit(1)

    published = get_published_slugs()
    pin_filenames = list_pin_filenames()

    # 第1段（安い処理）: ファイル名のみからslugを抽出する。
    stage1_slugs, filename_unrecognized, filename_slug = extract_pin_slugs_from_filenames(pin_filenames)
    missing = sorted(slug for slug in published if slug not in stage1_slugs)

    unresolved_files = []

    if missing:
        # 第2段（高い処理・D-0122で対象を絞り込み）:
        # ファイル名から抽出したslugがpublished記事のいずれかと一致した
        # ファイルは、そのピンの帰属がすでに確定しているため対象から除く。
        # 一致しなかったファイル（抽出不能を含む）だけを本文読み取りの対象とする。
        stage2_targets = [
            fname for fname in pin_filenames
            if filename_slug.get(fname) not in published
        ]

        body_slugs = set()
        for fname in stage2_targets:
            body_slug = extract_slug_from_body(fname)
            if body_slug:
                body_slugs.add(body_slug)
            elif fname in filename_unrecognized:
                unresolved_files.append(fname)

        combined_slugs = stage1_slugs | body_slugs
        missing = sorted(slug for slug in published if slug not in combined_slugs)

    output_lines = []

    if missing:
        shown = missing[:MAX_REPORT_ITEMS]
        for slug in shown:
            output_lines.append("【警告】公開済み記事にピンが1枚も見つかりません: %s（%s）" % (
                slug, published[slug]))
        rest = len(missing) - len(shown)
        if rest > 0:
            output_lines.append("【警告】ほか%d件、ピン未作成の可能性がある公開済み記事があります" % rest)

    if unresolved_files:
        shown_u = unresolved_files[:MAX_REPORT_ITEMS]
        for fname in shown_u:
            output_lines.append(
                "【警告】output/pins/のファイル名・本文URLのいずれからもslugを判別できませんでした: %s" % fname)
        rest_u = len(unresolved_files) - len(shown_u)
        if rest_u > 0:
            output_lines.append("【警告】ほか%d件、slug判定不能なピンファイルがあります" % rest_u)

    if not output_lines:
        print("PUBLISHED_PINS_OK")
        sys.exit(0)

    for line in output_lines:
        print(line)
    sys.exit(0)


if __name__ == "__main__":
    main()
