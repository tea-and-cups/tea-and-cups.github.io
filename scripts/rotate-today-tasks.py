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
    マーカーを基準日へ更新し、削除件数と削除した行の全文を出力する。
    未完了行が1つも残らないときも「## 今日」の見出しは消さず、見出しと基準日の日付マーカー
    だけを残す（節が消えると日付マーカーが無くなり、Stopフックの日次判定
    ［stop-hook-check.py の daily_done_on］と check-doc-governance.py の MARKER 警告が働かないため）
  - マーカーが存在しない → 削除は一切行わず、基準日のマーカーを新規挿入するだけに
    とどめ、その旨を出力する（日付が不明な状態で消すのは危険なため）。
    見出し直下が `<!-- date:` で始まるのに日付として読めない場合は、触れずにその旨を出力する
  - 「## 今日」節が存在しない → 「## 今週」の直前（無ければ最初の「## 」見出しの直前、
    それも無ければ末尾）に、見出しと基準日の日付マーカーだけの節を作り直し、
    「作り直しました」と1行出力する

安全策:
  - 未完了行（- [ ]）は年月日にかかわらず絶対に削除しない
  - 「## 今日」「## 今月」以外の節（## 今週・## バックログ等）には一切触れない
    （「## 今日」節が無いときに今週の直前へ空の今日節を足す処理だけが唯一の例外）

「## 今月」節（D-0269）:
  - 見出し直下付近の `<!-- month: YYYY-MM -->` を月マーカーとして読む
  - 今日節から削除する完了行に `[M-nn]` があれば、今月節の同じIDの未完了行を [x] にする
  - 月マーカーが基準日の月より古ければ、今月節の完了行を退避先へ移し（未完了行は残す）、
    マーカーを基準日の月へ更新する。退避先の日付見出しはマーカー月の末日とする
    （退避先の見出し形式 `## YYYY-MM-DD` と14日保持の仕組みをそのまま使うため）
  - 処理の最後に必ず1行、`MONTHLY_NEXT: <最初の選べる未完了行>` か `MONTHLY_NONE` を出す
    （D-0273: 上限に数える改修［タグ [改修]/[改修+画像]・行のどこにも「（上限外）」が無い］の完了が
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
    --posts-dir <パス>     週3本の判定で数える記事の置き場（既定 site/src/content/posts）

10〜12月の週3本（GD-0007・GD-0043）:
  最後に MONTHLY_NEXT / MONTHLY_NONE の前で、週3本の判定行を出す。対象は 10/1〜12/31 の日本時間の基準日
  （対象期間外は何も出さない）。その週（月〜日）に frontmatter の date がある status: published の
  gift・seasons 記事を数える（改修は数えない）。足りない本数（3−数えた本数）が今日を含む週の残り日数
  以上なら `CATEGORY_QUOTA_REQUIRED 今週 n/3・残りm日`（報告対象）と題材の探し方の1行を出し、
  MONTHLY_NEXT は改修の行（[改修]・[改修+画像]）を選ばず gift・seasons の [新規記事執筆] の行だけを選ぶ
  （無ければ MONTHLY_NONE）。届く見込みの日は `CATEGORY_QUOTA_OK 今週 n/3`（報告対象外）だけを出す。
  同じ判定を publish-article.py が使う（必要な日は gift・seasons 以外の新規公開を止め、
  今日 gift・seasons の新規公開が無ければ --revise も止める）。
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
WEEK_HEADING = "## 今週"
DATE_MARKER_PREFIX_RE = re.compile(r"^<!--\s*date:")
DATE_MARKER_RE = re.compile(r"^<!--\s*date:\s*(\d{4}-\d{2}-\d{2})\s*-->\s*$")

MONTH_HEADING = "## 今月"
MONTH_MARKER_RE = re.compile(r"^<!--\s*month:\s*(\d{4}-\d{2})\s*-->\s*$")
MONTHLY_ID_RE = re.compile(r"\[(M-\d+)\]")

# 改修の月次上限（D-0273。strategy.md「日次ノルマ」の「改修は月4本まで」を機械で守らせる）。
# 上限に数えるのは、今月節の完了行のうちタグが [改修] / [改修+画像] で、行のどこにも
# 「（上限外）」が無い行（後ろに「| …再公開完了…」が続いていても対象外）。
# 「（上限外）」の行（安全・保存の助言の修正など）は数えず、飛ばしもしない。
REVISE_MONTHLY_CAP = 4
REVISE_EXEMPT_SUFFIX = "（上限外）"
REVISE_TAG_RE = re.compile(r"^- \[[ xX]\] (?:\[M-\d+\] )?\[(?:改修|改修\+画像)\]")

# 10〜12月の週3本（GD-0007・GD-0043）。数えるのは、その週（日本時間の月〜日）に frontmatter の date が
# ある status: published の gift・seasons 記事（改修は数えない）。足りない本数が今日を含む週の残り日数
# 以上の日は「今日 gift・seasons の新規記事が必要」とし、MONTHLY_NEXT・publish-article.py に反映する。
QUOTA_CATEGORIES = ("gift", "seasons")
QUOTA_WEEKLY_MIN = 3
QUOTA_FIRST_DAY = "2026-10-01"
QUOTA_LAST_DAY = "2026-12-31"
POSTS_DIR = os.path.join(ROOT, "site", "src", "content", "posts")
FRONT_RE = re.compile(r"\A---\r?\n(.*?\r?\n)---\r?\n", re.S)
NEW_ARTICLE_TAG_RE = re.compile(r"^- \[[ xX]\] (?:\[M-\d+\] )?\[新規記事執筆\]")
QUOTA_ROW_CATEGORY_RE = re.compile(r"（[a-z0-9]+(?:-[a-z0-9]+)*・(?:category:\s*)?([a-z0-9-]+)）")

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
    """上限に数える改修の行か（タグが [改修] / [改修+画像] で、行のどこにも「（上限外）」が無い）。"""
    return bool(REVISE_TAG_RE.match(stripped)) and REVISE_EXEMPT_SUFFIX not in stripped


def _front_value(front, key):
    m = re.search(r"^%s:[ \t]*(\S+)[ \t]*$" % key, front, re.M)
    return m.group(1).strip("\"'") if m else None


def read_published_articles(posts_dir=POSTS_DIR):
    """posts_dir 直下の status: published の記事を [(date, category), ...] で返す。
    date・category が読めない記事は含めない。
    """
    articles = []
    if not os.path.isdir(posts_dir):
        return articles
    for name in sorted(os.listdir(posts_dir)):
        if not name.endswith(".md"):
            continue
        try:
            text = read_text(os.path.join(posts_dir, name))
        except OSError:
            continue
        m = FRONT_RE.match(text)
        if not m:
            continue
        front = m.group(1)
        if _front_value(front, "status") != "published":
            continue
        date, category = _front_value(front, "date"), _front_value(front, "category")
        if date and category:
            articles.append((date[:10], category))
    return articles


def jst_today():
    """今日の日付（日本時間）を YYYY-MM-DD で返す。"""
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date().isoformat()


def category_quota_status(today, posts_dir=POSTS_DIR):
    """GD-0007（10〜12月は gift・seasons が週3本以上）の、today（YYYY-MM-DD・日本時間）時点の状態を返す（GD-0043）。
    対象期間外（10/1〜12/31 以外）は None。
    数えるのは、その週（月〜日）に date がある status: published の gift・seasons 記事。改修は数えない。
    足りない本数が今日を含む週の残り日数以上なら required（今日 gift・seasons の新規記事を出さないと届かない）。
    戻り値: dict(count, remaining_days, required, published_today, week_start, week_end)。
    """
    if not (QUOTA_FIRST_DAY <= today <= QUOTA_LAST_DAY):
        return None
    day = datetime.date.fromisoformat(today)
    week_start = day - datetime.timedelta(days=day.weekday())
    week_end = week_start + datetime.timedelta(days=6)
    start_s, end_s = week_start.isoformat(), week_end.isoformat()
    count = 0
    published_today = 0
    for date, category in read_published_articles(posts_dir):
        if category in QUOTA_CATEGORIES:
            if start_s <= date <= end_s:
                count += 1
            if date == today:
                published_today += 1
    remaining_days = (week_end - day).days + 1
    return {
        "count": count,
        "remaining_days": remaining_days,
        "required": (QUOTA_WEEKLY_MIN - count) >= remaining_days,
        "published_today": published_today,
        "week_start": start_s,
        "week_end": end_s,
    }


def category_quota_lines(status):
    """セッション開始時に出す行を返す。対象期間外（status が None）は何も出さない。"""
    if status is None:
        return []
    if status["required"]:
        return [
            "CATEGORY_QUOTA_REQUIRED 今週 %d/%d・残り%d日" % (status["count"], QUOTA_WEEKLY_MIN, status["remaining_days"]),
            "新規記事を gift・seasons で書く。題材は ideas.md、無ければ data/advance-pin-calendar.tsv の近い山から選ぶ",
        ]
    return ["CATEGORY_QUOTA_OK 今週 %d/%d" % (status["count"], QUOTA_WEEKLY_MIN)]


def category_quota_gate(category, status, revise):
    """公開（新規・--revise）が週3本の要件に反しないかを判定する。(通すか, 理由) を返す。
    required でなければ常に通す。required の日は、新規公開は gift・seasons のみ、
    --revise は今日 gift・seasons の新規公開が既に1本以上あるときだけ通す。
    """
    if status is None or not status["required"]:
        return True, None
    head = "gift・seasons が今週 %d/%d 本（残り%d日）で、今日 gift・seasons の新規記事を出さないと週3本に届かない日です" % (
        status["count"], QUOTA_WEEKLY_MIN, status["remaining_days"])
    if revise:
        if status["published_today"] >= 1:
            return True, None
        return False, head + "。今日 gift・seasons の新規公開がまだ無いため、--revise は後回しにしてください"
    if category in QUOTA_CATEGORIES:
        return True, None
    return False, head + "。category: %s の新規公開は後回しにして、gift・seasons の新規記事を公開してください" % category


def quota_row_category(stripped):
    """今月節の行末「（slug・category）」「（slug・category: x）」の category を返す。読めなければ None。"""
    found = QUOTA_ROW_CATEGORY_RE.findall(stripped)
    return found[-1] if found else None


def monthly_next_line(lines, quota_required=False):
    """今月節から MONTHLY_NEXT（最初の選べる未完了行）か MONTHLY_NONE を返す（D-0273）。
    上限に数える改修の完了が REVISE_MONTHLY_CAP 件に達したら、上限に数える改修の未完了行を
    飛ばし、残りの先頭を返す。その場合は行末に「（改修上限 n/4・保留n行）」を添える。
    quota_required（今日 gift・seasons の新規記事を出さないと週3本に届かない日・GD-0043）のときは、
    改修の行（[改修]・[改修+画像]）を上限外も含めてすべて選ばず、gift・seasons の
    [新規記事執筆] の行だけを選ぶ（無ければ MONTHLY_NONE）。行末に「（週3本のため改修保留n行）」を添える。
    """
    if quota_required:
        return _monthly_next_quota_line(lines)
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


def _monthly_next_quota_line(lines):
    section = find_month_section(lines) if lines else None
    chosen = None
    held = 0
    if section:
        start, end = section
        for i in range(start + 1, end):
            stripped = lines[i].strip()
            if not stripped.startswith("- [ ]"):
                continue
            if REVISE_TAG_RE.match(stripped):
                held += 1
            elif (chosen is None and NEW_ARTICLE_TAG_RE.match(stripped)
                  and quota_row_category(stripped) in QUOTA_CATEGORIES):
                chosen = stripped
    note = "（週3本のため改修保留%d行）" % held
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
        quota_required = print_category_quota()
        print(monthly_next_line(state["lines"], quota_required))
    sys.exit(code)


def print_category_quota():
    """週3本の判定行を出し、「今日 gift・seasons の新規記事が必要」なら True を返す（GD-0043）。
    判定に失敗しても開始時チェックを止めず、エラーの1行を出す（黙って飛ばさない）。
    """
    try:
        status = category_quota_status(get_arg("--date") or jst_today(), get_arg("--posts-dir") or POSTS_DIR)
    except Exception as e:  # noqa: BLE001
        print("【エラー】週3本の判定に失敗しました: %s" % e)
        return False
    for line in category_quota_lines(status):
        print(line)
    return bool(status and status["required"])


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
    new_marker_line = "<!-- date: %s -->" % today

    recreated = False
    if not sections:
        insert_at = None
        for i, line in enumerate(lines):
            if line.startswith(WEEK_HEADING):
                insert_at = i
                break
        if insert_at is None:
            for i, line in enumerate(lines):
                if line.startswith("## "):
                    insert_at = i
                    break
        new_section = [TODAY_HEADING, new_marker_line, ""]
        if insert_at is None:
            if lines and lines[-1].strip() != "":
                lines.append("")
            insert_at = len(lines)
            new_section = [TODAY_HEADING, new_marker_line]
        lines[insert_at:insert_at] = new_section
        recreated = True
        print("「## 今日」節が無かったため、日付マーカー（%s）付きで作り直しました。" % today)

    # 節ごとに独立して判定する。lines への削除・置換は、後ろの節から適用すれば
    # 前の節のindexに影響しないため、開始indexの降順で処理する。
    unreadable_headings = []
    touched_reports = []  # (heading_text, 状態の説明, removed_count, removed_lines)
    pending_archives = []  # (marker_date, removed_lines) を書き込み前に集めておく

    for start, end in sorted(sections, key=lambda s: s[0], reverse=True):
        heading_text = lines[start].strip()
        marker_idx = start + 1
        has_marker = marker_idx < end and DATE_MARKER_RE.match(lines[marker_idx])
        marker_date = DATE_MARKER_RE.match(lines[marker_idx]).group(1) if has_marker else None

        if not has_marker:
            if marker_idx < end and DATE_MARKER_PREFIX_RE.match(lines[marker_idx].strip()):
                unreadable_headings.append(heading_text)
                continue
            lines.insert(marker_idx, new_marker_line)
            touched_reports.append((heading_text, "日付マーカーが無かったため挿入: %s" % today, 0, []))
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
            touched_reports.append((heading_text, "マーカー更新: %s -> %s" % (marker_date, today),
                                    len(removed), removed))
        else:
            # 未完了行が1つも残らない → 見出しは残し、基準日の日付マーカーだけにする
            lines[start:end] = [lines[start], new_marker_line, ""]
            touched_reports.append((heading_text, "マーカー更新（未完了行なし・見出しと日付マーカーのみ残す）: %s -> %s"
                                    % (marker_date, today), len(removed), removed))

    if unreadable_headings:
        for h in unreadable_headings:
            print("日付マーカーが読み取れないため触れません: %s" % h)

    if sections and not touched_reports:
        print("NO_ROTATE")

    # 表示は元の並び順（ファイル上から下）にしたいので開始indexの降順で積んだ
    # touched_reports を反転する。
    for heading_text, status, removed_count, removed_lines in reversed(touched_reports):
        print("見出し: %s / %s / 削除件数: %d件" % (heading_text, status, removed_count))
        for line in removed_lines:
            print(line)

    # 今月節: 今日節から消した完了行の [M-nn] を、今月節の同じIDの行へ反映する
    done_ids_input = []
    for report in reversed(touched_reports):
        for line in report[3]:
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

    if not touched_reports and not done_ids and not rolled and not recreated:
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
