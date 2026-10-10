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
  - 「## 今日」「## 今月」以外の節（## 今週・## バックログ等）には一切触れない
  - 「## 今日」節そのものが見つからない場合は今日節に何も書き込まない（今月節の処理は行う）

「## 今月」節（D-0269）:
  - 見出し直下付近の `<!-- month: YYYY-MM -->` を月マーカーとして読む
  - 今日節から削除する完了行に `[M-nn]` があれば、今月節の同じIDの未完了行を [x] にする
  - 月マーカーが基準日の月より古ければ、今月節の完了行を退避先へ移し（未完了行は残す）、
    マーカーを基準日の月へ更新する。退避先の日付見出しはマーカー月の末日とする
    （退避先の見出し形式 `## YYYY-MM-DD` と14日保持の仕組みをそのまま使うため）
  - 処理の最後に必ず1行、`MONTHLY_NEXT: <最初の選べる未完了行>` か `MONTHLY_NONE` を出す
    （D-0273: 上限に数える改修［タグ [改修]/[改修+画像]・末尾が「（上限外）」でない］の完了が
    REVISE_MONTHLY_CAP 件に達したら、その種類の未完了行を飛ばして残りの先頭を選び、
    行末に「（改修上限 n/4・保留n行）」を添える。「（上限外）」の行と [新規記事執筆] の行は飛ばさない）
    （どの位置で終わっても出す。日次の題材選びに使う）

出力:
  終了コードは0。退避先への書き込みに失敗した場合のみ1（tasks.md は書き換えない）。

使い方:
  python site/scripts/rotate-today-tasks.py               # docs/tasks.md に対して実行
  python site/scripts/rotate-today-tasks.py --dry-run      # 書き込みなしの事前確認
  python site/scripts/rotate-today-tasks.py --file <パス>  # 対象ファイルを差し替え
  検証用（省略時は従来どおり）:
    --tasks-file <パス>    対象ファイル（--file と同じ。両方あれば --tasks-file を優先）
    --archive-file <パス>  退避先（既定 docs/tasks-archive.md）
    --date YYYY-MM-DD      基準日（既定 実行日）
"""

import calendar
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

MONTH_HEADING = "## 今月"
MONTH_MARKER_RE = re.compile(r"^<!--\s*month:\s*(\d{4}-\d{2})\s*-->\s*$")
MONTHLY_ID_RE = re.compile(r"\[(M-\d+)\]")

# 改修の月次上限（D-0273。strategy.md「日次ノルマ」の「改修は月4本まで」を機械で守らせる）。
# 上限に数えるのは、今月節の完了行のうちタグが [改修] / [改修+画像] で、本文の末尾が
# 「（上限外）」でない行。「（上限外）」の行（安全・保存の助言の修正など）は数えず、飛ばしもしない。
REVISE_MONTHLY_CAP = 4
REVISE_EXEMPT_SUFFIX = "（上限外）"
REVISE_TAG_RE = re.compile(r"^- \[[ xX]\] (?:\[M-\d+\] )?\[(?:改修|改修\+画像)\]")

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


def archive_removed_lines(archive_path, entries):
    """削除された行を退避先（既定 docs/tasks-archive.md）へ追記する。
    entries は [(見出しの日付, [行, ...]), ...]。全件を1回の書き込みで反映する
    （途中で失敗して一部だけ退避された状態を作らないため）。
    追記後、日付見出しブロックが上限を超えていれば古い日付から削除する。
    失敗したら例外を送出する（呼び出し側で tasks.md への書き込みを止めるため）。
    """
    if os.path.isfile(archive_path):
        existing = read_text(archive_path)
    else:
        existing = ARCHIVE_HEADER

    preamble, blocks = parse_archive(existing)

    for marker_date, removed_lines in entries:
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
    write_text(archive_path, new_text)


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


def find_today_sections(lines):
    """「## 今日」で始まる（前方一致・サフィックス付き見出しを含む）節をすべて返す。
    各要素は (start, end)。start は見出し行のindex、end は次の「## 」見出し直前
    （無ければファイル末尾）のindex。見出しが1つも無ければ空リスト。
    """
    starts = [i for i, line in enumerate(lines) if line.strip().startswith(TODAY_HEADING)]
    sections = []
    for start in starts:
        end = len(lines)
        for i in range(start + 1, len(lines)):
            if lines[i].startswith("## "):
                end = i
                break
        sections.append((start, end))
    return sections


def find_month_section(lines):
    """「## 今月」で始まる最初の節を (start, end) で返す。無ければ None。
    end は次の「## 」見出し直前（無ければファイル末尾）のindex。
    """
    for start, line in enumerate(lines):
        if line.strip().startswith(MONTH_HEADING):
            end = len(lines)
            for i in range(start + 1, len(lines)):
                if lines[i].startswith("## "):
                    end = i
                    break
            return start, end
    return None


def complete_monthly_ids(lines, ids):
    """今月節の、ids に含まれるIDを持つ未完了行を [x] にする（lines をその場で書き換える）。
    戻り値は (完了にしたID, 今月節に未完了行として見つからなかったID)。
    """
    section = find_month_section(lines)
    done, missing = [], []
    for mid in ids:
        hit = False
        if section:
            start, end = section
            for i in range(start + 1, end):
                stripped = lines[i].strip()
                if stripped.startswith("- [ ]") and mid in MONTHLY_ID_RE.findall(stripped):
                    lines[i] = lines[i].replace("- [ ]", "- [x]", 1)
                    hit = True
                    break
        (done if hit else missing).append(mid)
    return done, missing


def roll_month(lines, run_date):
    """月マーカーが基準日の月より古ければ、今月節の完了行を取り除きマーカーを更新する
    （lines をその場で書き換える）。
    戻り値は None（何もしない）か (旧月, 新月, 退避先の見出し日付, 取り除いた行のリスト)。
    マーカーが読めない場合は文字列（表示用メッセージ）を返し、何もしない。
    """
    section = find_month_section(lines)
    if section is None:
        return None
    start, end = section
    marker_idx = None
    for i in range(start + 1, end):
        if MONTH_MARKER_RE.match(lines[i].strip()):
            marker_idx = i
            break
    if marker_idx is None:
        return "今月節の月マーカー（<!-- month: YYYY-MM -->）が読み取れないため繰越しません"
    old_month = MONTH_MARKER_RE.match(lines[marker_idx].strip()).group(1)
    new_month = run_date[:7]
    if old_month >= new_month:
        return None

    year, month = int(old_month[:4]), int(old_month[5:7])
    archive_date = "%s-%02d" % (old_month, calendar.monthrange(year, month)[1])

    kept, removed = [], []
    for i in range(start + 1, end):
        if i == marker_idx:
            kept.append("<!-- month: %s -->" % new_month)
        elif is_checked_line(lines[i]):
            removed.append(lines[i])
        else:
            kept.append(lines[i])
    lines[start + 1 : end] = kept
    return old_month, new_month, archive_date, removed


def is_capped_revise(stripped):
    """上限に数える改修の行か（タグが [改修] / [改修+画像] で、末尾が「（上限外）」でない）。"""
    return bool(REVISE_TAG_RE.match(stripped)) and not stripped.endswith(REVISE_EXEMPT_SUFFIX)


def monthly_next_line(lines):
    """今月節から MONTHLY_NEXT（最初の選べる未完了行）か MONTHLY_NONE を返す（D-0273）。
    上限に数える改修の完了が REVISE_MONTHLY_CAP 件に達したら、上限に数える改修の未完了行を
    飛ばし、残りの先頭を返す。その場合は行末に「（改修上限 n/4・保留n行）」を添える。
    """
    section = find_month_section(lines) if lines else None
    candidates = []
    done_count = 0
    if section:
        start, end = section
        for i in range(start + 1, end):
            stripped = lines[i].strip()
            if is_checked_line(stripped):
                if is_capped_revise(stripped):
                    done_count += 1
            elif stripped.startswith("- [ ]"):
                candidates.append(stripped)

    capped = done_count >= REVISE_MONTHLY_CAP
    held = 0
    chosen = None
    for stripped in candidates:
        if capped and is_capped_revise(stripped):
            held += 1
        elif chosen is None:
            chosen = stripped
    note = "（改修上限 %d/%d・保留%d行）" % (done_count, REVISE_MONTHLY_CAP, held) if capped else ""
    if chosen is not None:
        return "MONTHLY_NEXT: %s%s" % (chosen, note)
    return "MONTHLY_NONE%s" % note


def get_arg(name):
    if name in sys.argv:
        idx = sys.argv.index(name)
        if idx + 1 < len(sys.argv):
            return sys.argv[idx + 1]
    return None


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    # どの位置で終わっても、最後に MONTHLY_NEXT / MONTHLY_NONE を1行だけ出す。
    # state["lines"] は「最後にファイルへ反映された（dry-runなら反映されるはずの）内容」。
    state = {"lines": None}
    code = 0
    try:
        code = run(state)
    finally:
        print(monthly_next_line(state["lines"]))
    sys.exit(code)


def run(state):
    dry_run = "--dry-run" in sys.argv
    target = get_arg("--tasks-file") or get_arg("--file") or TASKS_MD
    archive_path = get_arg("--archive-file") or ARCHIVE_MD
    date_arg = get_arg("--date")
    today = date_arg if date_arg else datetime.date.today().isoformat()
    datetime.date.fromisoformat(today)  # 形式が不正なら例外で止める

    if not os.path.isfile(target):
        print("対象ファイルが見つかりません: %s" % target)
        return 0

    text = read_text(target)
    lines = text.split("\n")
    state["lines"] = list(lines)

    sections = find_today_sections(lines)
    if not sections:
        print("「## 今日」節が見つかりません。今日節には何も書き込みません。")

    new_marker_line = "<!-- date: %s -->" % today

    # 節ごとに独立して判定する。lines への削除・置換は、後ろの節から適用すれば
    # 前の節のindexに影響しないため、開始indexの降順で処理する。
    unreadable_headings = []
    touched_reports = []  # (heading_text, old_date, new_today_or_None, removed_count, deleted_section)
    pending_archives = []  # (marker_date, removed_lines) を書き込み前に集めておく

    for start, end in sorted(sections, key=lambda s: s[0], reverse=True):
        heading_text = lines[start].strip()
        marker_idx = start + 1
        has_marker = marker_idx < end and DATE_MARKER_RE.match(lines[marker_idx])
        marker_date = DATE_MARKER_RE.match(lines[marker_idx]).group(1) if has_marker else None

        if not has_marker:
            unreadable_headings.append(heading_text)
            continue

        if marker_date == today:
            continue

        section_content = lines[marker_idx + 1 : end]
        kept = []
        removed = []
        for line in section_content:
            if is_checked_line(line):
                removed.append(line)
            else:
                kept.append(line)

        if removed:
            pending_archives.append((marker_date, list(removed)))

        remains = any(l.strip().startswith("- [") for l in kept)

        if remains:
            new_section = [lines[start], new_marker_line] + kept
            lines[start:end] = new_section
            touched_reports.append((heading_text, marker_date, today, len(removed), False, removed))
        else:
            # 未完了行が1つも残らない → 見出しごと節を削除する
            lines[start:end] = []
            touched_reports.append((heading_text, marker_date, today, len(removed), True, removed))

    if unreadable_headings:
        for h in unreadable_headings:
            print("日付マーカーが読み取れないため触れません: %s" % h)

    if sections and not touched_reports:
        print("NO_ROTATE")

    # 表示は元の並び順（ファイル上から下）にしたいので開始indexの降順で積んだ
    # touched_reports を反転する。
    for heading_text, old_date, new_date, removed_count, deleted, removed_lines in reversed(touched_reports):
        status = "節ごと削除" if deleted else "マーカー更新: %s -> %s" % (old_date, new_date)
        print("見出し: %s / %s / 削除件数: %d件" % (heading_text, status, removed_count))
        for line in removed_lines:
            print(line)

    # 今月節: 今日節から消した完了行の [M-nn] を、今月節の同じIDの行へ反映する
    done_ids_input = []
    for report in reversed(touched_reports):
        for line in report[5]:
            for mid in MONTHLY_ID_RE.findall(line):
                if mid not in done_ids_input:
                    done_ids_input.append(mid)
    done_ids, missing_ids = complete_monthly_ids(lines, done_ids_input)
    for mid in done_ids:
        print("今月節: [%s] を完了にしました" % mid)
    for mid in missing_ids:
        print("今月節: [%s] は未完了行として見つからないため変更しません" % mid)

    # 今月節: 月が替わっていれば完了行を退避し、月マーカーを更新する
    rolled = roll_month(lines, today)
    month_archive = None
    if isinstance(rolled, str):
        print(rolled)
        rolled = None
    elif rolled:
        old_month, new_month, archive_date, month_removed = rolled
        print("見出し: %s / 月マーカー更新: %s -> %s / 退避件数: %d件"
              % (MONTH_HEADING, old_month, new_month, len(month_removed)))
        for line in month_removed:
            print(line)
        if month_removed:
            month_archive = (archive_date, list(month_removed))

    if not touched_reports and not done_ids and not rolled:
        return 0

    if not dry_run:
        entries = list(pending_archives)
        if month_archive:
            entries.append(month_archive)
        if entries:
            try:
                archive_removed_lines(archive_path, entries)
            except Exception as e:
                print("退避に失敗したため tasks.md への書き込みを中止します: %s" % e)
                return 1
        for marker_date, removed_lines in pending_archives:
            print("退避先: %s（%s・%d件）" % (archive_path, marker_date, len(removed_lines)))
        if month_archive:
            print("退避先: %s（%s・%d件・今月節）" % (archive_path, month_archive[0], len(month_archive[1])))
        write_text(target, "\n".join(lines))

    state["lines"] = lines
    return 0


if __name__ == "__main__":
    main()
