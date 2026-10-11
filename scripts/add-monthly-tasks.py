# -*- coding: utf-8 -*-
r"""月次監査の「## 来月の作業キュー案」を読み、採用されたQ番号だけを docs/tasks.md「## 今月」節へ書き込む（D-0276）。

背景: 月次の Growth Agent 監査（growth/outputs/monthly-<対象月>/audit.md）が出す日次向けの
作業候補を、AIが文章から読み取って tasks.md へ手で写すと、行の形・M番号・重複・上限外の
位置がその都度ぶれる。監査には機械で読める表を出させ、窓口が採用したQ番号だけをこの
スクリプトが決まった形で書き込む。採否を決めるのは窓口であり、AIが自分の判断で --adopt を
実行しない。

読み取る表（growth/prompts/monthly-audit.md が出力の形を指示する）:
  「## 来月の作業キュー案」節に、タブ区切りの表を1つ。1行目は列名の行。
    Q番号 ／ タグ ／ slug ／ category ／ GD番号 ／ 内容 ／ 根拠
  - Q番号: Q-1 の形・重複なし
  - タグ: 新規記事執筆・改修・改修+画像 のどれか
  - slug・category: 半角英小文字・数字・ハイフン
  - GD番号: GD-NNNN か、無ければ -
  - 内容・根拠: 空でない1行（内容に「（上限外）」「[M-nn]」を書かない）
  コードブロックの囲み（```）と空行は読み飛ばす。それ以外の行はすべて表の行として検査する。

書き込む行の形（rotate-today-tasks.py の解析に合わせる）:
  - [ ] [M-連番] [タグ] 内容（GD番号）（slug・category）
  GD番号が - の行、内容に同じGD番号が既に書かれている行には（GD番号）を足さない。

--adopt の動作:
  - M番号: 今月節にある [M-nn] の最大の番号＋1から、--adopt に書いた順に通しで付ける。
  - 重複: 今月節の未完了行と slug×GD番号 が同じ候補は飛ばす（GD番号が - の候補は、GD番号の
    無い未完了行と照合する）。タグが 新規記事執筆 の候補は slug だけで照合する。
  - 上限外: GD番号が UNCAPPED_GD にある行にだけ、末尾へ「（上限外）」を付ける（改修の月4本の
    上限に数えない行・D-0273）。上限外かどうかは監査に書かせず、この定数だけで決める。
  - 挿入位置: rotate-today-tasks.py の MONTHLY_NEXT は、今月節の未完了行をファイルの上から
    順に選ぶ（「（上限外）」の印は、上限に数えない・上限到達後も飛ばさない、の2点にだけ効く）。
    そのため上限外の行は、今月節で最初の「上限外でない未完了行」の直前へ入れる（既にある
    上限外の行の後ろ・それ以外の未完了行より前）。それ以外の行は今月節の末尾へ入れる。
  - 月マーカー（<!-- month: YYYY-MM -->）が実行月と違えば、何も書かずに終了コード1。
    （月の繰越しは rotate-today-tasks.py が開始時に行う。繰越し前の節へ書かないため）
  - 改修の月4本の上限はここでは制御しない（rotate-today-tasks.py が担う・D-0273）。

出力:
  --list  : 候補を、書き込まれる行の形（M番号を除く）と根拠で1件1行に表示する。
  --adopt : 書き込んだ行（行番号つき）と、飛ばした候補（理由と既存の行）をすべて表示する。
  終了コード: 0=正常／1=形式違反・月マーカーの不一致・表に無いQ番号・ファイルが無い。
  形式違反は「行N: 理由」（Nは監査出力の行番号）で全件を示し、1件でもあれば何も書かない。

使い方:
  python site/scripts/add-monthly-tasks.py --list <監査出力のパス>
  python site/scripts/add-monthly-tasks.py --adopt Q-1,Q-3 --from <監査出力のパス>
  検証用（省略時は docs/tasks.md・実行日）:
    --tasks <パス>      書き込み先を差し替える
    --date YYYY-MM-DD   実行日を差し替える（月マーカーとの照合に使う）
"""

import argparse
import datetime
import importlib.util
import io
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
TASKS_MD = os.path.join(ROOT, "docs", "tasks.md")

# 今月節の見出し・月マーカー・完了行の判定・「（上限外）」の印は rotate-today-tasks.py を
# 唯一の定義元とする（ファイル名にハイフンを含むため importlib で読み込む）。
_spec = importlib.util.spec_from_file_location(
    "rotate_today_tasks", os.path.join(SCRIPT_DIR, "rotate-today-tasks.py")
)
rotate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rotate)

QUEUE_HEADING = "## 来月の作業キュー案"
COLUMNS = ["Q番号", "タグ", "slug", "category", "GD番号", "内容", "根拠"]
NEW_ARTICLE_TAG = "新規記事執筆"
TAGS = (NEW_ARTICLE_TAG, "改修", "改修+画像")
NO_GD = "-"

# 改修の月4本の上限に数えない行（D-0273）を決める GD番号。該当する行にだけ「（上限外）」を付ける。
UNCAPPED_GD = {"GD-0033"}

Q_RE = re.compile(r"^Q-\d+$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
GD_RE = re.compile(r"GD-\d{4}")
GD_CELL_RE = re.compile(r"^GD-\d{4}$")
M_NUMBER_RE = re.compile(r"\[M-(\d+)\]")
# 今月節の行の「（slug・category）」（今日節の「（slug・category: xxx）」の書き方も読む）。
ROW_SLUG_RE = re.compile(r"（([a-z0-9]+(?:-[a-z0-9]+)*)・(?:category:\s*)?[a-z0-9-]+）")


def display_path(path):
    """プロジェクトルート配下ならルートからの相対パス（スラッシュ区切り）にする。"""
    absolute = os.path.abspath(path)
    try:
        relative = os.path.relpath(absolute, ROOT)
    except ValueError:
        return absolute.replace("\\", "/")
    if relative.startswith(".."):
        return absolute.replace("\\", "/")
    return relative.replace("\\", "/")


def parse_queue(text):
    """監査出力から候補表を読む。戻り値は (候補のリスト, 形式違反のリスト)。

    形式違反は「行N: 理由」の文字列（Nは監査出力の行番号）。1件でもあれば呼び出し側は
    何も書き込まない。
    """
    lines = text.split("\n")
    start = None
    for i, line in enumerate(lines):
        if line.strip() == QUEUE_HEADING:
            start = i
            break
    if start is None:
        return [], ["「%s」節がありません" % QUEUE_HEADING]

    rows = []
    for i in range(start + 1, len(lines)):
        raw = lines[i].rstrip("\r")
        if raw.startswith("## "):
            break
        if not raw.strip() or raw.strip().startswith("```"):
            continue
        rows.append((i + 1, raw))
    if not rows:
        return [], ["行%d: 「%s」節に表がありません（列名の行が必要）" % (start + 1, QUEUE_HEADING)]

    header_no, header = rows[0]
    if [cell.strip() for cell in header.split("\t")] != COLUMNS:
        return [], ["行%d: 列名の行が違います（タブ区切りで「%s」の7列）"
                    % (header_no, "／".join(COLUMNS))]

    candidates = []
    errors = []
    seen = {}
    for line_no, raw in rows[1:]:
        cells = [cell.strip() for cell in raw.split("\t")]
        if len(cells) != len(COLUMNS):
            errors.append("行%d: 列数が%d（タブ区切りで%d列）" % (line_no, len(cells), len(COLUMNS)))
            continue
        q, tag, slug, category, gd, content, basis = cells
        problems = []
        if not Q_RE.match(q):
            problems.append("Q番号「%s」が Q-1 の形でない" % q)
        elif q in seen:
            problems.append("Q番号 %s が行%dと重複" % (q, seen[q]))
        if tag not in TAGS:
            problems.append("タグ「%s」が %s のどれでもない" % (tag, "・".join(TAGS)))
        if not SLUG_RE.match(slug):
            problems.append("slug「%s」が半角英小文字・数字・ハイフンでない" % slug)
        if not SLUG_RE.match(category):
            problems.append("category「%s」が半角英小文字・数字・ハイフンでない" % category)
        if gd != NO_GD and not GD_CELL_RE.match(gd):
            problems.append("GD番号「%s」が GD-NNNN でも %s でもない" % (gd, NO_GD))
        if not content:
            problems.append("内容が空")
        elif rotate.REVISE_EXEMPT_SUFFIX in content or M_NUMBER_RE.search(content):
            problems.append("内容に「%s」または [M-nn] が書かれている" % rotate.REVISE_EXEMPT_SUFFIX)
        if not basis:
            problems.append("根拠が空")
        if problems:
            errors.append("行%d: %s" % (line_no, "／".join(problems)))
            continue
        seen[q] = line_no
        candidates.append({"q": q, "tag": tag, "slug": slug, "category": category, "gd": gd,
                           "content": content, "basis": basis, "line_no": line_no})
    return candidates, errors


def task_body(candidate):
    """今月節へ書く行の、[M-連番] より後ろの部分を返す。"""
    gd = candidate["gd"]
    gd_part = "" if gd == NO_GD or gd in candidate["content"] else "（%s）" % gd
    body = "[%s] %s%s（%s・%s）" % (candidate["tag"], candidate["content"], gd_part,
                                 candidate["slug"], candidate["category"])
    if gd in UNCAPPED_GD:
        body += rotate.REVISE_EXEMPT_SUFFIX
    return body


def load_queue(path):
    """監査出力を読んで (候補, 形式違反) を返す。読めなければ (None, [理由])。"""
    if not os.path.isfile(path):
        return None, ["監査出力が見つかりません: %s" % display_path(path)]
    with io.open(path, "r", encoding="utf-8-sig") as f:
        return parse_queue(f.read())


def print_errors(path, errors):
    print("形式違反 %d件（%s）。何も書き込みません。" % (len(errors), display_path(path)))
    for error in errors:
        print("  %s" % error)


def run_list(path):
    candidates, errors = load_queue(path)
    if errors:
        print_errors(path, errors)
        return 1
    print("来月の作業キュー案 %d件（%s）" % (len(candidates), display_path(path)))
    for candidate in candidates:
        print("%s %s ｜根拠: %s" % (candidate["q"], task_body(candidate), candidate["basis"]))
    return 0


def month_rows(lines, start, end):
    """今月節のタスク行（未完了・完了）を、照合に使う項目つきで返す。"""
    rows = []
    for i in range(start + 1, end):
        stripped = lines[i].strip()
        is_open = stripped.startswith("- [ ]")
        if not is_open and not rotate.is_checked_line(stripped):
            continue
        slugs = ROW_SLUG_RE.findall(stripped)
        rows.append({"index": i, "text": stripped, "open": is_open,
                     "slug": slugs[-1] if slugs else None,
                     "gds": set(GD_RE.findall(stripped)),
                     "exempt": stripped.endswith(rotate.REVISE_EXEMPT_SUFFIX)})
    return rows


def find_duplicate(candidate, open_rows):
    """候補と重複する未完了行を返す（無ければ None）。新規記事は slug だけで照合する。"""
    for row in open_rows:
        if row["slug"] != candidate["slug"]:
            continue
        if candidate["tag"] == NEW_ARTICLE_TAG:
            return row
        if candidate["gd"] == NO_GD:
            if not row["gds"]:
                return row
        elif candidate["gd"] in row["gds"]:
            return row
    return None


def run_adopt(q_text, queue_path, tasks_path, run_date):
    candidates, errors = load_queue(queue_path)
    if errors:
        print_errors(queue_path, errors)
        return 1

    wanted = [q.strip() for q in q_text.split(",") if q.strip()]
    by_q = {candidate["q"]: candidate for candidate in candidates}
    bad = [q for q in wanted if q not in by_q]
    repeated = sorted({q for q in wanted if wanted.count(q) > 1})
    if not wanted or bad or repeated:
        if not wanted:
            print("--adopt にQ番号がありません（例: --adopt Q-1,Q-3）。何も書き込みません。")
        if bad:
            print("表に無いQ番号です: %s（表にあるのは %s）。何も書き込みません。"
                  % ("、".join(bad), "、".join(c["q"] for c in candidates) or "なし"))
        if repeated:
            print("--adopt に同じQ番号が2回あります: %s。何も書き込みません。" % "、".join(repeated))
        return 1

    if not os.path.isfile(tasks_path):
        print("書き込み先が見つかりません: %s" % display_path(tasks_path))
        return 1
    lines = rotate.read_text(tasks_path).split("\n")
    section = rotate.find_month_section(lines)
    if section is None:
        print("「%s」節がありません: %s。何も書き込みません。"
              % (rotate.MONTH_HEADING, display_path(tasks_path)))
        return 1
    start, end = section

    marker_month = None
    for i in range(start + 1, end):
        m = rotate.MONTH_MARKER_RE.match(lines[i].strip())
        if m:
            marker_month = m.group(1)
            break
    run_month = run_date[:7]
    if marker_month != run_month:
        print("今月節の月マーカー（%s）が実行月（%s）と違うため、何も書き込みません。"
              % (marker_month or "読み取れない", run_month))
        print("月の繰越しは rotate-today-tasks.py が行います。繰越しの後に実行してください。")
        return 1

    rows = month_rows(lines, start, end)
    open_rows = [row for row in rows if row["open"]]
    for row in open_rows:
        if row["slug"] is None:
            print("【注意】slug を読めない未完了行があります（重複の照合に使いません）: %s" % row["text"])

    numbers = [int(n) for i in range(start + 1, end)
               for n in M_NUMBER_RE.findall(lines[i]) if lines[i].strip().startswith("- [")]
    next_number = max(numbers) + 1 if numbers else 1

    uncapped_new, normal_new, skipped = [], [], []
    for q in wanted:
        candidate = by_q[q]
        duplicate = find_duplicate(candidate, open_rows)
        if duplicate is not None:
            skipped.append((candidate, duplicate))
            continue
        line = "- [ ] [M-%d] %s" % (next_number, task_body(candidate))
        next_number += 1
        exempt = line.endswith(rotate.REVISE_EXEMPT_SUFFIX)
        (uncapped_new if exempt else normal_new).append((candidate, line))
        # 同じ --adopt の中の後続の候補とも照合できるよう、書く予定の行を未完了行に加える。
        open_rows.append({"index": None, "text": line, "open": True, "slug": candidate["slug"],
                          "gds": set(GD_RE.findall(line)), "exempt": exempt})

    print("書き込み先: %s（月マーカー %s）" % (display_path(tasks_path), marker_month))
    if uncapped_new or normal_new:
        # 今月節の末尾（最後の空でない行の次）。上限外の行は、最初の「上限外でない未完了行」の直前。
        tail = start + 1
        for i in range(start + 1, end):
            if lines[i].strip():
                tail = i + 1
        first_capped = next((row["index"] for row in rows if row["open"] and not row["exempt"]), None)
        head = first_capped if first_capped is not None else tail
        # 後ろ（末尾）から先に入れる。先頭側の挿入位置がずれないようにするため。
        lines[tail:tail] = [line for _candidate, line in normal_new]
        lines[head:head] = [line for _candidate, line in uncapped_new]
        rotate.write_text(tasks_path, "\n".join(lines))

        for candidate, line in uncapped_new + normal_new:
            where = "上限外の並びの末尾" if line.endswith(rotate.REVISE_EXEMPT_SUFFIX) else "今月節の末尾"
            print("追加 行%d（%s）← %s: %s" % (lines.index(line) + 1, where, candidate["q"], line))
    for candidate, duplicate in skipped:
        key = ("slug %s" % candidate["slug"] if candidate["tag"] == NEW_ARTICLE_TAG
               else "slug %s × GD番号 %s" % (candidate["slug"], candidate["gd"]))
        print("重複のため飛ばしました ← %s（%s）／既存の未完了行: %s"
              % (candidate["q"], key, duplicate["text"]))
    print("ADD_MONTHLY_DONE 追加%d件・重複で飛ばした%d件"
          % (len(uncapped_new) + len(normal_new), len(skipped)))
    return 0


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="月次監査の作業キュー案を tasks.md「## 今月」へ書き込む（D-0276）")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", dest="list_path", metavar="AUDIT_MD",
                      help="監査出力の候補表を解析して表示する")
    mode.add_argument("--adopt", dest="adopt", metavar="Q-1,Q-3",
                      help="採用するQ番号（カンマ区切り）。--from と一緒に指定する")
    parser.add_argument("--from", dest="from_path", metavar="AUDIT_MD", help="--adopt の読み取り元の監査出力")
    parser.add_argument("--tasks", dest="tasks_path", default=TASKS_MD, metavar="TASKS_MD",
                        help="書き込み先（検証用・省略時は docs/tasks.md）")
    parser.add_argument("--date", dest="run_date", default=None, metavar="YYYY-MM-DD",
                        help="実行日（検証用・省略時は今日）")
    args = parser.parse_args(argv)

    if args.list_path:
        return run_list(args.list_path)
    if not args.from_path:
        print("--adopt には --from <監査出力のパス> が必要です。何も書き込みません。")
        return 1
    run_date = args.run_date or datetime.date.today().isoformat()
    datetime.date.fromisoformat(run_date)  # 形式が不正なら例外で止める
    return run_adopt(args.adopt, args.from_path, args.tasks_path, run_date)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
