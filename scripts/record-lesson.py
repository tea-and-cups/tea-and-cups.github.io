# -*- coding: utf-8 -*-
r"""教訓リスト機構（D-0163）。日次セッションで得られた教訓を data/lessons.tsv へ
機械的に蓄積し、3回再発したものだけを週次レポートへ浮上させる。

【目的】
オーナーが日次レポートを読まなくても、繰り返し起きている問題だけが週次で目に入る
状態を作る。単発の失敗は自動的に古びて消え、3回再発したものだけが残る。

【日次セッションの判別＝マーカー方式】
「今日は日次セッションか」をAIの自己申告に頼らず、日次フローでしか実行されない
スクリプト（check-topic-duplicate.py＝題材選定・publish-article.py＝公開処理）の
冒頭から `mark` を呼ぶことで判定する。改善・修正セッションではこの2本が動かないため
マーカーが作られず、`check` は何も要求しない（＝誤爆しない）。

マーカーの同一セッション判定には環境変数 CLAUDE_CODE_SESSION_ID を使う。
通常のスクリプト実行時とStopフック実行時の両方で同じ値が得られることを実測で
確認済み（2026-08-25・詳細は reports/2026-08-25-3.md 参照）。

【data/lessons.tsv の列】
  id / category / summary / count / status / first_seen / last_seen / resolved_at /
  details
  status: active（未処遇）／pending（週次で浮上済み・処遇待ち）／fixed（対策済み）／
          accepted（許容）
  resolved_at: status が最後に変わった日。active は空文字。
  details: 再発の具体症状。`YYYY-MM-DD:詳細|YYYY-MM-DD:詳細` 形式で直近3件のみ保持
           （4件目の追加時に最古を捨てる）。summary が抽象的なままだと週次に浮上しても
           対策を設計できないため、bump 時に必ず1件記録する。

【data/lessons-session.txt】
  1行目: そのセッションの CLAUDE_CODE_SESSION_ID
  2行目以降: そのセッションで実行した記録（ADD/BUMP/NONE）。件数の上限判定に使う。

使い方:
  python site/scripts/record-lesson.py mark
  python site/scripts/record-lesson.py list [--category <カテゴリ>]
  python site/scripts/record-lesson.py add --category <カテゴリ> --summary "<40字以内>" [--detail "<20字以内>"]
  python site/scripts/record-lesson.py bump --id L001 --detail "<20字以内>"
  python site/scripts/record-lesson.py none
  python site/scripts/record-lesson.py check
  python site/scripts/record-lesson.py weekly
  python site/scripts/record-lesson.py resolve --id L001 --status fixed

終了コード: 0=正常 / 1=入力エラー（不正カテゴリ・40字超・summaryのタブ/改行混入・
  存在しないID・処遇済み項目へのresolve・セッション上限超過・bumpの--detail未指定・
  detailの20字超・detailのタブ/改行/パイプ記号混入）
"""

import argparse
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LESSONS_FILE = os.path.join(ROOT, "data", "lessons.tsv")
SESSION_FILE = os.path.join(ROOT, "data", "lessons-session.txt")

# カテゴリはこの9種類に固定する。増減はここでのみ行い、スクリプト側で弾く。
CATEGORIES = (
    "article-writing",
    "product-research",
    "image-generation",
    "image-quality",
    "pin-posting",
    "publish",
    "script-bug",
    "external-service",
    "other",
)
STATUSES = ("active", "pending", "fixed", "accepted")
RESOLVED_STATUSES = ("fixed", "accepted")
# resolve を受け付ける status（＝まだ処遇されていないもの）
RESOLVABLE_STATUSES = ("active", "pending")
COLUMNS = (
    "id", "category", "summary", "count", "status",
    "first_seen", "last_seen", "resolved_at", "details",
)

SUMMARY_MAX_CHARS = 40
DETAIL_MAX_CHARS = 20          # --detail 1件あたりの上限
DETAILS_KEEP = 3               # details に保持する件数（超過分は最古から捨てる）
DETAIL_SEPARATOR = "|"         # details 内の区切り。detail 本文への混入は弾く
ADD_LIMIT = 3                  # 1セッションで実行できる add の件数
BUMP_LIMIT = 5                 # 1セッションで実行できる bump の件数（addとは別枠）
ACTIVE_STALE_DAYS = 30         # active かつ count=1 をこの日数で自動削除する
FIXED_KEEP_DAYS = 50           # fixed をこの日数で自動削除する
ACCEPTED_KEEP_DAYS = 180       # accepted を last_seen からこの日数で自動削除する
ACTIVE_MAX = 40                # active の保持上限（超過分は count=1 の古い順に削除）
RESOLVED_WARN = 40             # fixed+accepted がこの件数を超えたら stderr で通知
OTHER_CATEGORY_WARN = 5        # category=other の active がこの件数を超えたら通知
WEEKLY_THRESHOLD = 3           # 週次へ浮上させる count の閾値

FAILED_PREFIX = "[対策失敗]"   # fixed を bump したときに summary の先頭へ付ける
NOT_RECORDED_MARKER = "LESSON_NOT_RECORDED"

SESSION_RECORD_KINDS = ("ADD", "BUMP", "NONE")
# 種別ごとの1セッション上限（add と bump は合算しない）
SESSION_LIMITS = {"ADD": ADD_LIMIT, "BUMP": BUMP_LIMIT}


# --------------------------------------------------------------------------
# lessons.tsv の入出力
# --------------------------------------------------------------------------

def load_rows():
    """lessons.tsv を辞書のリストとして読む。ファイルが無ければ空リストを返す。"""
    if not os.path.exists(LESSONS_FILE):
        return []
    rows = []
    with open(LESSONS_FILE, "r", encoding="utf-8") as f:
        lines = [line.rstrip("\n") for line in f if line.strip()]
    for line in lines:
        fields = line.split("\t")
        if fields[0] == COLUMNS[0]:
            continue  # ヘッダー行
        fields = (fields + [""] * len(COLUMNS))[:len(COLUMNS)]
        rows.append(dict(zip(COLUMNS, fields)))
    return rows


def save_rows(rows):
    directory = os.path.dirname(LESSONS_FILE)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(LESSONS_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(COLUMNS) + "\n")
        for row in rows:
            f.write("\t".join(str(row.get(col, "")) for col in COLUMNS) + "\n")


def to_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def parse_date(value):
    try:
        return date(*[int(part) for part in str(value).strip().split("-")])
    except (TypeError, ValueError):
        return None


def today_str():
    return date.today().isoformat()


# --------------------------------------------------------------------------
# 自動メンテナンス（list / add / bump / weekly の実行時に毎回走る）
# --------------------------------------------------------------------------

def elapsed_days(value):
    """日付文字列から今日までの経過日数を返す。読めなければ None。"""
    parsed = parse_date(value)
    if parsed is None:
        return None
    return (date.today() - parsed).days


def run_maintenance(rows):
    """古びた項目を自動的に整理する。count>=2 の active は絶対に削除しない。
    pending（処遇待ち）はどの削除対象にもしない（処遇されるまで消えない）。
    accepted は180日再発していなければ削除する（事象が消滅しているため）。
    """
    today = date.today()
    kept = []
    for row in rows:
        status = row.get("status", "")
        if status == "active" and to_int(row.get("count")) == 1:
            last_seen = parse_date(row.get("last_seen"))
            if last_seen and (today - last_seen).days >= ACTIVE_STALE_DAYS:
                continue
        if status == "fixed":
            resolved_at = parse_date(row.get("resolved_at"))
            if resolved_at and (today - resolved_at).days >= FIXED_KEEP_DAYS:
                continue
        if status == "accepted":
            last_seen = parse_date(row.get("last_seen"))
            if last_seen and (today - last_seen).days >= ACCEPTED_KEEP_DAYS:
                continue
        kept.append(row)

    actives = [r for r in kept if r.get("status") == "active"]
    if len(actives) > ACTIVE_MAX:
        excess = len(actives) - ACTIVE_MAX
        removable = [r for r in actives if to_int(r.get("count")) == 1]
        removable.sort(key=lambda r: (r.get("last_seen", ""), r.get("id", "")))
        drop_ids = set(r.get("id") for r in removable[:excess])
        if drop_ids:
            kept = [r for r in kept if r.get("id") not in drop_ids]
        remaining = len([r for r in kept if r.get("status") == "active"])
        if remaining > ACTIVE_MAX:
            print(
                "警告: activeが%d件あり上限%d件に収まりません（count>=2は削除しないため）。"
                "処遇（resolve）を検討してください。" % (remaining, ACTIVE_MAX),
                file=sys.stderr,
            )

    resolved = [r for r in kept if r.get("status") in RESOLVED_STATUSES]
    if len(resolved) > RESOLVED_WARN:
        print("処遇済みが40件を超過。棚卸しを検討", file=sys.stderr)

    # other がゴミ箱化すると同カテゴリ照合が機能しなくなるため、件数だけ通知する
    others = [r for r in kept
              if r.get("status") == "active" and r.get("category") == "other"]
    if len(others) > OTHER_CATEGORY_WARN:
        print("カテゴリ other が5件超過。カテゴリ分割の検討が必要", file=sys.stderr)

    return kept


# --------------------------------------------------------------------------
# セッションマーカー
# --------------------------------------------------------------------------

def current_session_id():
    return os.environ.get("CLAUDE_CODE_SESSION_ID") or ""


def read_session():
    """(セッションID, 記録行のリスト) を返す。ファイルが無ければ (None, [])。"""
    if not os.path.exists(SESSION_FILE):
        return None, []
    with open(SESSION_FILE, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    if not lines:
        return None, []
    return lines[0], lines[1:]


def write_session(session_id, records):
    directory = os.path.dirname(SESSION_FILE)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(SESSION_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write(session_id + "\n")
        for record in records:
            f.write(record + "\n")


def append_session_record(record):
    """記録行を1行追記する。マーカーが未作成・別セッションのものだった場合は
    現在のセッションIDで作り直してから追記する（記録そのものは落とさない）。
    """
    session_id, records = read_session()
    sid = current_session_id() or "UNKNOWN"
    if session_id != sid:
        session_id, records = sid, []
    records.append(record)
    write_session(session_id, records)


def counted_records(records, kind):
    return [r for r in records if r.split("\t")[0] == kind]


def ensure_session_capacity(kind):
    """同一セッションでの kind（ADD / BUMP）の件数が上限を超えていないか確かめる。
    add と bump は別枠で数える（bumpはリストを増やさずカウントを+1するだけのため、
    同じ枠で絞るとカウント精度が落ちる）。超過時は終了コード1で止める。
    """
    session_id, records = read_session()
    if session_id != (current_session_id() or "UNKNOWN"):
        return  # 別セッション（または未作成）なら数え直しになるので上限には掛からない
    limit = SESSION_LIMITS[kind]
    used = len(counted_records(records, kind))
    if used >= limit:
        print(
            "エラー: このセッションでは既に %s を%d件記録済みです。"
            "1セッションの %s 上限は%d件です。" % (kind.lower(), used, kind.lower(), limit),
            file=sys.stderr,
        )
        sys.exit(1)


# --------------------------------------------------------------------------
# サブコマンド
# --------------------------------------------------------------------------

def cmd_mark(_args):
    sid = current_session_id()
    if not sid:
        print(
            "環境変数 CLAUDE_CODE_SESSION_ID が取得できないため、"
            "教訓リストのセッションマーカーを作成しません（処理は続行します）。",
            file=sys.stderr,
        )
        return 0
    session_id, _records = read_session()
    if session_id == sid:
        return 0  # 既に同じIDが書かれている（冪等）
    write_session(sid, [])  # 異なるIDなら上書き（＝新しいセッションの開始）
    return 0


def format_row(row):
    return "%s  [%s]  %s  (count=%s, %s〜%s)" % (
        row.get("id", ""),
        row.get("category", ""),
        row.get("summary", ""),
        row.get("count", ""),
        row.get("first_seen", ""),
        row.get("last_seen", ""),
    )


def pending_line(row):
    days = elapsed_days(row.get("resolved_at"))
    suffix = "経過日数不明" if days is None else "浮上から%d日経過" % days
    return "%s  resolved_at=%s（%s）" % (format_row(row), row.get("resolved_at", ""), suffix)


def cmd_list(args):
    rows = run_maintenance(load_rows())
    save_rows(rows)

    category = getattr(args, "category", None)
    if category:
        if category not in CATEGORIES:
            print(
                "エラー: カテゴリ '%s' は定義されていません。使えるのは次の9種類です:\n  %s"
                % (category, " / ".join(CATEGORIES)),
                file=sys.stderr,
            )
            return 1
        rows = [r for r in rows if r.get("category") == category]
        print("=== カテゴリ: %s ===" % category)

    # details は照合が要る --category 指定時のみ出す（全件表示で毎回出すとトークンを食う）
    show_details = bool(category)

    def print_detail_lines(row):
        if show_details:
            for line in detail_lines(row):
                print(line)

    actives = [r for r in rows if r.get("status") == "active"]
    actives.sort(key=lambda r: (r.get("category", ""), -to_int(r.get("count")), r.get("id", "")))
    print("=== active（未処遇・%d件） ===" % len(actives))
    if actives:
        for row in actives:
            print(format_row(row))
            print_detail_lines(row)
    else:
        print("（なし）")

    pendings = [r for r in rows if r.get("status") == "pending"]
    pendings.sort(key=lambda r: (r.get("resolved_at", ""), r.get("id", "")))
    print("")
    print("=== pending（処遇待ち・%d件） ===" % len(pendings))
    if pendings:
        for row in pendings:
            print(pending_line(row))
            print_detail_lines(row)
    else:
        print("（なし）")

    resolved = [r for r in rows if r.get("status") in RESOLVED_STATUSES]
    resolved.sort(key=lambda r: (r.get("status", ""), r.get("category", ""), r.get("id", "")))
    print("")
    print("=== 処遇済み（fixed / accepted・%d件） ===" % len(resolved))
    if resolved:
        for row in resolved:
            print("%s  status=%s  resolved_at=%s" % (
                format_row(row), row.get("status", ""), row.get("resolved_at", "")))
    else:
        print("（なし）")
    return 0


def check_summary_safe(summary):
    """summary にタブ・改行が含まれていないか確かめる。TSVが壊れると機構全体が
    止まるため、混入していればここで弾く。
    """
    for char, label in (("\t", "タブ文字"), ("\n", "改行"), ("\r", "改行")):
        if char in summary:
            print(
                "エラー: summaryに%sが含まれています。TSVが破損するため記録できません。" % label,
                file=sys.stderr,
            )
            return False
    return True


def check_detail(detail, required):
    """--detail の内容を検査する。不正なら None を返す（呼び出し側が終了コード1）。
    パイプ記号は details 列の区切りに使うため、本文への混入を弾く。
    """
    if detail is None or not str(detail).strip():
        if required:
            print(
                "エラー: bump には --detail \"<20字以内>\" が必須です。"
                "何が起きたかを具体的に記録してください。",
                file=sys.stderr,
            )
            return None
        return ""
    detail = str(detail).strip()
    for char, label in (("\t", "タブ文字"), ("\n", "改行"), ("\r", "改行"),
                        (DETAIL_SEPARATOR, "パイプ記号(|)")):
        if char in detail:
            print(
                "エラー: detailに%sが含まれています。TSVが破損するため記録できません。" % label,
                file=sys.stderr,
            )
            return None
    if len(detail) > DETAIL_MAX_CHARS:
        print(
            "エラー: detailが%d字です。%d字以内にしてください。"
            % (len(detail), DETAIL_MAX_CHARS),
            file=sys.stderr,
        )
        return None
    return detail


def parse_details(value):
    """details 列を ["YYYY-MM-DD:詳細", ...] のリストにする。空なら空リスト。"""
    raw = str(value or "").strip()
    if not raw:
        return []
    return [part for part in raw.split(DETAIL_SEPARATOR) if part.strip()]


def append_detail(value, detail):
    """details 列へ1件追記し、直近 DETAILS_KEEP 件だけを残した文字列を返す。"""
    entries = parse_details(value)
    entries.append("%s:%s" % (today_str(), detail))
    return DETAIL_SEPARATOR.join(entries[-DETAILS_KEEP:])


def detail_lines(row, indent="    "):
    """details を日付付きの箇条書き行のリストにする。空なら空リスト。"""
    lines = []
    for entry in parse_details(row.get("details")):
        head, sep, body = entry.partition(":")
        lines.append("%s- %s" % (indent, ("%s %s" % (head, body)) if sep else entry))
    return lines


def next_id(rows):
    numbers = []
    for row in rows:
        raw = str(row.get("id", "")).strip()
        if raw.upper().startswith("L") and raw[1:].isdigit():
            numbers.append(int(raw[1:]))
    return "L%03d" % ((max(numbers) + 1) if numbers else 1)


def cmd_add(args):
    if args.category not in CATEGORIES:
        print(
            "エラー: カテゴリ '%s' は定義されていません。使えるのは次の9種類です:\n  %s"
            % (args.category, " / ".join(CATEGORIES)),
            file=sys.stderr,
        )
        return 1
    if not check_summary_safe(args.summary):
        return 1
    summary = args.summary.strip()
    if len(summary) > SUMMARY_MAX_CHARS:
        print(
            "エラー: summaryが%d字です。%d字以内にしてください。"
            % (len(summary), SUMMARY_MAX_CHARS),
            file=sys.stderr,
        )
        return 1

    detail = check_detail(getattr(args, "detail", None), required=False)
    if detail is None:
        return 1

    ensure_session_capacity("ADD")

    rows = load_rows()
    today = today_str()
    new_row = {
        "id": next_id(rows),
        "category": args.category,
        "summary": summary,
        "count": "1",
        "status": "active",
        "first_seen": today,
        "last_seen": today,
        "resolved_at": "",
        "details": append_detail("", detail) if detail else "",
    }
    rows.append(new_row)
    save_rows(run_maintenance(rows))
    append_session_record("ADD\t%s" % new_row["id"])
    print("追加: %s" % format_row(new_row))
    return 0


def cmd_bump(args):
    rows = load_rows()
    target = None
    for row in rows:
        if row.get("id", "").strip().upper() == args.id.strip().upper():
            target = row
            break
    if target is None:
        print("エラー: ID '%s' は lessons.tsv に存在しません。" % args.id, file=sys.stderr)
        return 1

    if not check_summary_safe(target.get("summary", "")):
        return 1

    detail = check_detail(getattr(args, "detail", None), required=True)
    if detail is None:
        return 1

    ensure_session_capacity("BUMP")

    target["count"] = str(to_int(target.get("count")) + 1)
    target["last_seen"] = today_str()
    target["details"] = append_detail(target.get("details"), detail)

    note = ""
    if target.get("status") == "fixed":
        # 対策したはずのものが再発した＝対策失敗。countに関わらず週次へ浮上させる。
        target["status"] = "active"
        target["resolved_at"] = ""
        if not target.get("summary", "").startswith(FAILED_PREFIX):
            target["summary"] = FAILED_PREFIX + target.get("summary", "")
        note = "（対策失敗としてactiveへ戻し、週次の浮上対象にしました）"
    # pending は処遇待ちのまま count だけ加算する（statusは変えない）。
    # accepted も count を加算するだけで status を変えない。

    save_rows(run_maintenance(rows))
    append_session_record("BUMP\t%s" % target["id"])
    print("更新: %s%s" % (format_row(target), note))
    for line in detail_lines(target):
        print(line)
    return 0


def cmd_none(_args):
    append_session_record("NONE")
    print("このセッションは教訓ゼロとして記録しました。")
    return 0


def cmd_check(_args):
    """Stopフックから呼ばれる。exit 1 は使わない（停止の判断は stop-hook-check.py 側）。"""
    session_id, records = read_session()
    sid = current_session_id()
    if session_id is None or not sid or session_id != sid:
        return 0  # 日次セッションではない（＝改善・修正セッション）ので何も要求しない
    if not [r for r in records if r.split("\t")[0] in SESSION_RECORD_KINDS]:
        print(NOT_RECORDED_MARKER)
    return 0


def cmd_weekly(_args):
    rows = run_maintenance(load_rows())

    # (c) 先に「処遇待ち」を拾う。今回浮上した分は含めない（初出は新規浮上側に出す）。
    waiting = [r for r in rows if r.get("status") == "pending"]
    waiting.sort(key=lambda r: (r.get("resolved_at", ""), r.get("id", "")))

    # (a) 今回浮上する分
    targets = [
        r for r in rows
        if r.get("status") == "active"
        and (to_int(r.get("count")) >= WEEKLY_THRESHOLD
             or r.get("summary", "").startswith(FAILED_PREFIX))
    ]
    targets.sort(key=lambda r: (-to_int(r.get("count")), r.get("category", ""), r.get("id", "")))

    if not targets and not waiting:
        save_rows(rows)
        print("今週の浮上項目なし／処遇待ちなし")
        return 0

    if targets:
        print("今週浮上した教訓（%d件・処遇待ちとしてリストに残ります）" % len(targets))
        for row in targets:
            print("- %s [%s] %s（%d回・%s〜%s）" % (
                row.get("id", ""),
                row.get("category", ""),
                row.get("summary", ""),
                to_int(row.get("count")),
                row.get("first_seen", ""),
                row.get("last_seen", ""),
            ))
            for line in detail_lines(row):
                print(line)
    else:
        print("今週の浮上項目なし")

    print("")
    if waiting:
        print("処遇待ち（過去に浮上・未処遇・%d件）" % len(waiting))
        for row in waiting:
            days = elapsed_days(row.get("resolved_at"))
            elapsed = "経過日数不明" if days is None else "浮上から%d日経過" % days
            print("- %s [%s] %s（%d回・%s）" % (
                row.get("id", ""),
                row.get("category", ""),
                row.get("summary", ""),
                to_int(row.get("count")),
                elapsed,
            ))
            for line in detail_lines(row):
                print(line)
    else:
        print("処遇待ちなし")

    # (b) 出力した項目は削除せず pending にして残す
    today = today_str()
    for row in targets:
        row["status"] = "pending"
        row["resolved_at"] = today
    save_rows(rows)
    return 0


def cmd_resolve(args):
    rows = load_rows()
    target = None
    for row in rows:
        if row.get("id", "").strip().upper() == args.id.strip().upper():
            target = row
            break
    if target is None:
        print("エラー: ID '%s' は lessons.tsv に存在しません。" % args.id, file=sys.stderr)
        return 1
    if target.get("status") in RESOLVED_STATUSES:
        print(
            "エラー: %s は既に status=%s で処遇済みです。再度の resolve はできません。"
            % (target.get("id", ""), target.get("status", "")),
            file=sys.stderr,
        )
        return 1
    target["status"] = args.status
    target["resolved_at"] = today_str()
    save_rows(rows)
    print("処遇: %s  status=%s  resolved_at=%s" % (
        format_row(target), target["status"], target["resolved_at"]))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description="教訓リストの記録・照会（D-0163）")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("mark", help="日次セッションのマーカーを作る（日次フローのスクリプトから呼ばれる）")
    p_list = sub.add_parser("list", help="既存の教訓を一覧表示する（照合用）")
    p_list.add_argument("--category", default=None,
                        help="指定したカテゴリの項目だけを表示する")

    p_add = sub.add_parser("add", help="新しい教訓を追加する")
    p_add.add_argument("--category", required=True)
    p_add.add_argument("--summary", required=True)
    p_add.add_argument("--detail", default=None,
                       help="具体的な症状（20字以内・任意。指定時はdetailsの1件目になる）")

    p_bump = sub.add_parser("bump", help="既存の教訓の再発を記録する")
    p_bump.add_argument("--id", required=True)
    # argparse の required=True は終了コード2になるため、必須判定は check_detail 側で行う
    p_bump.add_argument("--detail", default=None,
                        help="具体的な症状（20字以内・必須）")

    sub.add_parser("none", help="そのセッションで教訓ゼロだったことを記録する")
    sub.add_parser("check", help="Stopフック用: 記録漏れを検知する")
    sub.add_parser("weekly", help="週次: count>=3 の項目と処遇待ちを出力する")

    p_resolve = sub.add_parser("resolve", help="窓口での処遇判断を反映する")
    p_resolve.add_argument("--id", required=True)
    p_resolve.add_argument("--status", required=True, choices=list(RESOLVED_STATUSES))

    return parser


COMMANDS = {
    "mark": cmd_mark,
    "list": cmd_list,
    "add": cmd_add,
    "bump": cmd_bump,
    "none": cmd_none,
    "check": cmd_check,
    "weekly": cmd_weekly,
    "resolve": cmd_resolve,
}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
