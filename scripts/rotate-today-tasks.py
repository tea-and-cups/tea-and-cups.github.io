# -*- coding: utf-8 -*-
r"""docs/tasks.md「## 今日」節の完了[x]行を、日付マーカーとの比較だけで機械的に掃除する
（書き込み系・--dry-run で事前確認できる）。

背景: CLAUDE.md 5節ステップ6は「今日」欄から前日以前の完了[x]タスクを削除するよう
指示していたが、タスク行に日付が一切書かれておらず、どの行が前日以前かを機械的にも
目視でも判定する手段が無かった（ルールが物理的に実行不可能だった）。
check-image-gen-needed-today.py（D-0078）・check-routine-due.py（D-0087）と同じ方針で、
自由記述文からの推測は行わず、「書く側が固定タグを機械的に書く」「読む側はそのタグの
比較だけを見る」設計にする（D-0097）。

日付マーカー:
  docs/tasks.md の「## 今日」見出し直下に置く HTMLコメント行 `<!-- date: YYYY-MM-DD -->`。
  Markdown表示に現れず、`## ` で始まらないため check-image-gen-needed-today.py の
  節抽出（次の「## 」見出しの直前まで）を壊さない。

動作:
  - 「## 今日」節の直後にある日付マーカーを読む
  - マーカーの日付が基準日と一致 → 何も書き込まず NO_ROTATE の1行だけを出力
    （同日2回目以降のセッションでその日の完了タスクが消えるのを防ぐため）
  - マーカーの日付が基準日と異なる → 「## 今日」節の完了行（- [x] / - [X]）を削除し、
    マーカーを基準日へ更新し、削除件数と削除した行の全文を出力する
  - マーカーが存在しない → 削除は一切行わず、基準日のマーカーを新規挿入するだけに
    とどめ、その旨を出力する（日付が不明な状態で消すのは危険なため）

安全策:
  - 未完了行（- [ ]）は年月日にかかわらず絶対に削除しない
  - 「## 今日」以外の節（## 今週・## バックログ等）には一切触れない
  - 「## 今日」節そのものが見つからない場合は何も書き込まず終了する

出力:
  終了コードは常に0（情報提供のみ・ブロックしない）。

使い方:
  python site/scripts/rotate-today-tasks.py               # docs/tasks.md に対して実行
  python site/scripts/rotate-today-tasks.py --dry-run      # 書き込みなしの事前確認
  python site/scripts/rotate-today-tasks.py --file <パス>  # 対象ファイルを差し替え
"""

import datetime
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TASKS_MD = os.path.join(ROOT, "docs", "tasks.md")
ARCHIVE_MD = os.path.join(ROOT, "docs", "tasks-archive.md")

TODAY_HEADING = "## 今日"
DATE_MARKER_RE = re.compile(r"^<!--\s*date:\s*(\d{4}-\d{2}-\d{2})\s*-->\s*$")

ARCHIVE_HEADER = (
    "# tasks-archive.md — tasks.md「今日」欄の削除行アーカイブ（自動生成・参照専用）\n"
    "\n"
    "1. このファイルは rotate-today-tasks.py が自動で追記する。人間・AIが手で編集しない\n"
    "2. 用途は過去の「今日」欄の内容を後から確認することのみ。"
    "**タスクや記事の進捗状態の根拠として参照してはならない**。"
    "進捗の正本は記事frontmatterのstatus（D-0105）、Pin投稿状況は data/pin-posted.md（D-0111）である\n"
    "3. 保持は直近14日分のみ。古い日付のブロックは自動削除される\n"
    "\n"
    "---\n"
)

ARCHIVE_DATE_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2})\s*$")
ARCHIVE_MAX_BLOCKS = 14


def parse_archive(text):
    """アーカイブ本文を (preamble_lines, [[date, [line, ...]], ...]) に分解する。"""
    lines = text.split("\n")
    preamble = []
    i = 0
    while i < len(lines) and not ARCHIVE_DATE_RE.match(lines[i]):
        preamble.append(lines[i])
        i += 1

    blocks = []
    while i < len(lines):
        m = ARCHIVE_DATE_RE.match(lines[i])
        if not m:
            i += 1
            continue
        date = m.group(1)
        i += 1
        block_lines = []
        while i < len(lines) and not ARCHIVE_DATE_RE.match(lines[i]):
            block_lines.append(lines[i])
            i += 1
        while block_lines and block_lines[-1] == "":
            block_lines.pop()
        blocks.append([date, block_lines])
    return preamble, blocks


def render_archive(preamble, blocks):
    out = list(preamble)
    for date, block_lines in blocks:
        if out and out[-1] != "":
            out.append("")
        out.append("## %s" % date)
        out.extend(block_lines)
    text = "\n".join(out)
    if not text.endswith("\n"):
        text += "\n"
    return text


def archive_removed_lines(marker_date, removed_lines):
    """削除された行（マーカーの日付に属していた行）を docs/tasks-archive.md へ追記する。
    追記後、日付見出しブロックが上限を超えていれば古い日付から削除する。
    成功したら追記件数を返す。失敗したら例外を送出する（呼び出し側で tasks.md への書き込みを止めるため）。
    """
    if os.path.isfile(ARCHIVE_MD):
        existing = read_text(ARCHIVE_MD)
    else:
        existing = ARCHIVE_HEADER

    preamble, blocks = parse_archive(existing)

    target_block = None
    for block in blocks:
        if block[0] == marker_date:
            target_block = block
            break

    if target_block is None:
        blocks.append([marker_date, list(removed_lines)])
    else:
        target_block[1].extend(removed_lines)

    if len(blocks) > ARCHIVE_MAX_BLOCKS:
        blocks.sort(key=lambda b: b[0])
        blocks = blocks[-ARCHIVE_MAX_BLOCKS:]

    new_text = render_archive(preamble, blocks)
    write_text(ARCHIVE_MD, new_text)
    return len(removed_lines)


def read_text(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_text(path, text):
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def is_checked_line(line):
    """チェックボックスが済み（- [x] / - [X]）の行かどうかを判定する（大文字小文字両対応）。"""
    stripped = line.strip()
    return stripped.startswith("- [x]") or stripped.startswith("- [X]")


def find_today_section(lines):
    """「## 今日」見出しの開始行indexと、次の「## 」見出し直前までの終了indexを返す。
    見出しが見つからなければ (None, None)。
    """
    start = None
    for i, line in enumerate(lines):
        if line.strip() == TODAY_HEADING:
            start = i
            break
    if start is None:
        return None, None
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    return start, end


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    dry_run = "--dry-run" in sys.argv
    target = TASKS_MD
    if "--file" in sys.argv:
        idx = sys.argv.index("--file")
        if idx + 1 < len(sys.argv):
            target = sys.argv[idx + 1]

    today = datetime.date.today().isoformat()

    if not os.path.isfile(target):
        print("対象ファイルが見つかりません: %s" % target)
        sys.exit(0)

    text = read_text(target)
    lines = text.split("\n")

    heading_idx, section_end = find_today_section(lines)
    if heading_idx is None:
        print("「## 今日」節が見つかりません。何も書き込みません。")
        sys.exit(0)

    # 「## 今日」見出しの直後の行が日付マーカーかどうかを見る
    marker_idx = heading_idx + 1
    marker_date = None
    has_marker = marker_idx < section_end and DATE_MARKER_RE.match(lines[marker_idx])
    if has_marker:
        marker_date = DATE_MARKER_RE.match(lines[marker_idx]).group(1)

    if has_marker and marker_date == today:
        print("NO_ROTATE")
        sys.exit(0)

    new_marker_line = "<!-- date: %s -->" % today

    if not has_marker:
        # マーカーが存在しない → 削除は一切行わず、マーカーを新規挿入するだけ
        new_lines = lines[: heading_idx + 1] + [new_marker_line] + lines[heading_idx + 1 :]
        print("日付マーカーが見つからないため削除は行わず、マーカーのみ新規挿入します（%s）。" % new_marker_line)
        if not dry_run:
            write_text(target, "\n".join(new_lines))
        sys.exit(0)

    # マーカーが過去日 → 「## 今日」節の完了行を削除し、マーカーを更新する
    section_lines = lines[marker_idx + 1 : section_end]
    kept = []
    removed = []
    for line in section_lines:
        if is_checked_line(line):
            removed.append(line)
        else:
            kept.append(line)

    new_lines = (
        lines[:heading_idx]
        + [lines[heading_idx], new_marker_line]
        + kept
        + lines[section_end:]
    )

    print("マーカー更新: %s -> %s" % (marker_date, today))
    print("削除件数: %d件" % len(removed))
    for line in removed:
        print(line)

    if not dry_run:
        if removed:
            try:
                archived_count = archive_removed_lines(marker_date, removed)
            except Exception as e:
                print("退避に失敗したため tasks.md への書き込みを中止します: %s" % e)
                sys.exit(1)
            print("退避先: %s（%d件）" % (ARCHIVE_MD, archived_count))
        write_text(target, "\n".join(new_lines))

    sys.exit(0)


if __name__ == "__main__":
    main()
