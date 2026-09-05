# -*- coding: utf-8 -*-
r"""日付起点の1回限りの予定（data/scheduled-items.tsv）の期日到来を通知する。

背景: 「〇月〇日になったら〜する」という1回限りの予定は docs/tasks.md に自由文で
書かれているだけで、その日に誰も読みに行かないためオーナーが失念していた。
週次・月次の繰り返しルーチンは check-routine-due.py が担当しており、そちらは
1回限りの予定を扱う仕組みを持たない。本スクリプトはその隙間だけを埋める。

台帳: data/scheduled-items.tsv（タブ区切り・列は id / due / status / title / ref）
  - title は「何の予定か」が分かる短い見出しのみを持つ。手順や判断基準は書かない。
    作業内容の正本は docs/tasks.md 等の ref 先であり、両方に書くと必ず片方が古くなる。
  - ref は内容の正本の在り処（docs/tasks.md の該当項目、または D番号）。

動作:
  引数なし（既定動作 = 通知）
    基準日（既定は実行日）に対し、status が open かつ due <= 基準日 の行を抽出する。
    該当なし: "SCHEDULED_NONE" の1行のみ。
    該当あり: 1行目に "SCHEDULED_DUE: N件"、続けて各行、最後に固定の案内1行。
    終了コードは常に0（情報提供のみ。ブロックはしない）。
    出力に【警告】という文字列は使わない。stop-hook-check.py が
    check-doc-governance.py の標準出力から【警告】で始まる行を抽出しており、
    そちらと混同されることを避けるため。

  add --due YYYY-MM-DD --title "..." --ref "..."
    末尾に1行追記する。id は既存の最大値+1で自動採番（S-0001形式）。
    同一の due と title の組が既に存在する場合は追記せず終了コード1で止める
    （重複追記による台帳破損が過去に発生しているため・D-0194）。

  done --id S-000N
    該当行の status を done に変える。該当idが無ければ終了コード1。
    done 行が DONE_KEEP_MAX 件を超えたら古いもの（ファイル上で先に現れるもの）から
    削除する。無制限に増えない定数上限型にするため。

使い方:
  python site/scripts/check-scheduled-items.py
  python site/scripts/check-scheduled-items.py --today 2026-09-08   # 検証用
  python site/scripts/check-scheduled-items.py add --due 2026-09-08 --title "..." --ref "..."
  python site/scripts/check-scheduled-items.py done --id S-0001
"""

import argparse
import datetime
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LEDGER = os.path.join(ROOT, "data", "scheduled-items.tsv")

HEADER_LINE = "# id\tdue\tstatus\ttitle\tref"

# done 行の保持上限。これを超えた分は古いものから削除する。
DONE_KEEP_MAX = 40

GUIDE_LINE = (
    "上記はオーナーが日付を指定した予定です。通常の作業に入る前にオーナーへ提示し、"
    "先に進めるか通常の日次ルーチンを行うかの判断を仰いでください。"
)

STATUS_OPEN = "open"
STATUS_DONE = "done"


def parse_date(text):
    """YYYY-MM-DD を date にする。形式違反は ValueError。"""
    return datetime.datetime.strptime(text, "%Y-%m-%d").date()


def read_lines():
    """台帳を行のリストで読む。ファイルが無ければヘッダーのみの状態として扱う。"""
    if not os.path.exists(LEDGER):
        return [HEADER_LINE]
    with io.open(LEDGER, "r", encoding="utf-8") as f:
        return f.read().split("\n")


def write_lines(lines):
    body = "\n".join([l for l in lines if l != ""])
    with io.open(LEDGER, "w", encoding="utf-8", newline="\n") as f:
        f.write(body + "\n")


def parse_row(line):
    """データ行を dict にする。列が足りない行は None（壊れた行は黙って捨てず呼び出し側で扱う）。"""
    parts = line.split("\t")
    if len(parts) < 5:
        return None
    return {
        "id": parts[0].strip(),
        "due": parts[1].strip(),
        "status": parts[2].strip(),
        "title": parts[3].strip(),
        "ref": parts[4].strip(),
    }


def iter_rows(lines):
    """(行index, row dict) を返す。コメント行・空行・壊れた行は飛ばす。"""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        row = parse_row(line)
        if row is None:
            continue
        yield i, row


def format_row(row):
    return "\t".join([row["id"], row["due"], row["status"], row["title"], row["ref"]])


def next_id(lines):
    """既存の最大 id + 1 を S-000N 形式で返す。1件も無ければ S-0001。"""
    max_n = 0
    for _, row in iter_rows(lines):
        rid = row["id"]
        if rid.startswith("S-"):
            try:
                max_n = max(max_n, int(rid[2:]))
            except ValueError:
                continue
    return "S-%04d" % (max_n + 1)


def cmd_notify(args, out):
    try:
        base = parse_date(args.today) if args.today else datetime.date.today()
    except ValueError:
        out.write("SCHEDULED_ERROR: --today は YYYY-MM-DD 形式で指定してください\n")
        return 1

    lines = read_lines()
    due_rows = []
    for _, row in iter_rows(lines):
        if row["status"] != STATUS_OPEN:
            continue
        try:
            due = parse_date(row["due"])
        except ValueError:
            continue
        if due <= base:
            due_rows.append((due, row))

    if not due_rows:
        out.write("SCHEDULED_NONE\n")
        return 0

    due_rows.sort(key=lambda t: (t[0], t[1]["id"]))
    out.write("SCHEDULED_DUE: %d件\n" % len(due_rows))
    for _, row in due_rows:
        out.write("- %s %s %s（%s）\n" % (row["due"], row["id"], row["title"], row["ref"]))
    out.write(GUIDE_LINE + "\n")
    return 0


def cmd_add(args, out):
    try:
        parse_date(args.due)
    except ValueError:
        out.write("SCHEDULED_ERROR: --due は YYYY-MM-DD 形式で指定してください\n")
        return 1

    title = args.title.strip()
    if "\t" in title or "\t" in args.ref:
        out.write("SCHEDULED_ERROR: title / ref にタブ文字は使えません\n")
        return 1

    lines = read_lines()
    for _, row in iter_rows(lines):
        if row["due"] == args.due and row["title"] == title:
            out.write(
                "SCHEDULED_DUPLICATE: 同じ due と title の組が既に登録されています"
                "（%s %s %s）。追記しませんでした。\n" % (row["id"], row["due"], row["title"])
            )
            return 1

    new_row = {
        "id": next_id(lines),
        "due": args.due,
        "status": STATUS_OPEN,
        "title": title,
        "ref": args.ref.strip(),
    }
    lines = [l for l in lines if l != ""]
    lines.append(format_row(new_row))
    write_lines(lines)
    out.write("SCHEDULED_ADDED: %s %s %s\n" % (new_row["id"], new_row["due"], new_row["title"]))
    return 0


def cmd_done(args, out):
    lines = read_lines()
    target_index = None
    for i, row in iter_rows(lines):
        if row["id"] == args.id:
            target_index = i
            target_row = row
            break

    if target_index is None:
        out.write("SCHEDULED_NOT_FOUND: id %s は台帳にありません\n" % args.id)
        return 1

    target_row["status"] = STATUS_DONE
    lines[target_index] = format_row(target_row)

    # done 行が上限を超えたら、ファイル上で先に現れるもの（=古いもの）から削除する。
    done_indexes = [i for i, row in iter_rows(lines) if row["status"] == STATUS_DONE]
    removed = 0
    if len(done_indexes) > DONE_KEEP_MAX:
        drop = set(done_indexes[: len(done_indexes) - DONE_KEEP_MAX])
        lines = [l for i, l in enumerate(lines) if i not in drop]
        removed = len(drop)

    write_lines(lines)
    out.write("SCHEDULED_DONE: %s %s\n" % (target_row["id"], target_row["title"]))
    if removed:
        out.write("SCHEDULED_PRUNED: 古い done 行を %d件 削除しました\n" % removed)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description="日付起点の1回限りの予定の期日到来を通知する")
    parser.add_argument("--today", help="基準日を差し替える（YYYY-MM-DD・検証専用）")
    sub = parser.add_subparsers(dest="cmd")

    p_add = sub.add_parser("add", help="予定を1件追記する")
    p_add.add_argument("--due", required=True, help="期日（YYYY-MM-DD）")
    p_add.add_argument("--title", required=True, help="何の予定かが分かる短い見出し")
    p_add.add_argument("--ref", required=True, help="内容の正本の在り処")

    p_done = sub.add_parser("done", help="予定をクローズする")
    p_done.add_argument("--id", required=True, help="対象の id（S-000N）")

    return parser


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = build_parser().parse_args()
    out = sys.stdout

    if args.cmd == "add":
        return cmd_add(args, out)
    if args.cmd == "done":
        return cmd_done(args, out)
    return cmd_notify(args, out)


if __name__ == "__main__":
    sys.exit(main())
