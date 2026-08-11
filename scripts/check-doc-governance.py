# -*- coding: utf-8 -*-
r"""運営文書（CLAUDE.md・decisions.md・rules/配下）の変更管理チェック（引数なしで実行）。

CLAUDE.md 3節1「rules/配下のファイルの新設・削除はオーナー承認＋decisions.md記録が必要」の
実施漏れを機械的に検出する。人の記憶に頼っていたために記録漏れが起きたため（D-0051）。

検出項目:
  1. rules/配下のファイルの新設・削除 → 【警告】（3節1の対象）
     内容のみの更新（ハッシュ変化）→ 【通知】（3節1の対象外なので警告にしない）
  2. decisions.md 最新エントリの日付が今日か → 1の警告に添える判断材料として使う
  3. decisions.md 直近5件の3行ルール逸脱（本体の文字数で判定）→ 【警告】
  4. CLAUDE.md本体の文字数が閾値超過 → 【警告】
  5. フックスクリプト自身の検証用デバッグ残留物（D-0069・D-0070） → 【警告】
     対象は .claude/settings.json・.claude/settings.local.json の hooks 項に登録された
     全スクリプトを動的に洗い出す（固定リストにしない。フックが増えても追従できるように）。
     「TEMP DEBUG」「一時デバッグ」「完了後に削除」等の削除予定コメント、または
     ファイル名・変数名に debug を含むデバッグ専用ログ書き込みが残っていないかを検出する。
  6. docs/status.md の文字数が閾値超過（CLAUDE.md 10節「常に1画面以内」の機械チェック・D-0099） → 【警告】
  7. docs/tasks.md「## 今日」節直下の日付マーカー（<!-- date: YYYY-MM-DD -->）が今日の日付か
     （rotate-today-tasks.py の実行漏れ検知・D-0102） → 【警告】

状態は data/doc-state.tsv に保存する。プロジェクトルートはD-0043によりGit管理外のため、
この状態ファイルがsite/リポジトリへ混入することは構造的に起こらない。

初回実行（状態ファイルが無い）:
  エラーにせず現状を記録して終了コード0で終わる。状態を必要としない検出（3・4）は初回でも行う。

警告の持ち越し:
  rules/の新設・削除を検出し、かつ decisions.md の本日付エントリ（全件）の本文に
  該当ファイル名の言及が無い場合は、rules/の状態を保存せず持ち越す。次のセッションでも
  同じ警告が出続け、該当ファイル名を含む形で記録した日に自動で解消される。単に
  「本日付のエントリが存在するか」だけで判定すると、rules/変更と無関係な決定が同日に
  記録されただけで誤って「記録済み」とみなしてしまうため（2026-08-02の動作検証で発覚・
  D-0053）。また、本日付エントリのうち先頭（entries[0]）1件だけを見ると、記録直後に
  一度も実行しないうちに無関係な決定が同日に先へ積まれた場合に誤って「未記録」と
  判定されるため、本日付エントリ全件を対象にする（2026-08-02の追加検証で発覚・D-0054）。

行数・文字数の数え方は site/scripts/count-doc-chars.py と同一（テキストモードで読み、
"\n" を数える）。ハッシュも改行変換後のテキストに対して取るため、CRLF/LFの差では変化しない。

使い方:
  python site/scripts/check-doc-governance.py

終了コード: 【警告】が1件でもあれば1、それ以外（【通知】のみ・異常なし・初回実行）は0
"""

import datetime
import glob
import hashlib
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from decisions_lib import (
    read_text,
    count_chars_lines,
    heading_date,
    parse_decisions,
    body_char_count,
)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RULES_DIR = os.path.join(ROOT, "rules")
CLAUDE_MD = os.path.join(ROOT, "CLAUDE.md")
DECISIONS_MD = os.path.join(ROOT, "docs", "decisions.md")
STATUS_MD = os.path.join(ROOT, "docs", "status.md")
TASKS_MD = os.path.join(ROOT, "docs", "tasks.md")
IDEAS_MD = os.path.join(ROOT, "docs", "ideas.md")
POSTS_DIR = os.path.join(ROOT, "site", "src", "content", "posts")
STATE_TSV = os.path.join(ROOT, "data", "doc-state.tsv")

CLAUDE_MD_CHAR_LIMIT = 10000
# decisions.md本体の容量閾値。超過した場合はarchive-decisions.pyでの退避対象になる
# （検出のみ・自動実行はしない。実行可否の判断はCLAUDE.md 10節参照）
DECISIONS_MD_CHAR_LIMIT = 15000
# status.md本体の容量閾値。CLAUDE.md 10節「status.mdは常に1画面以内」の機械チェック（D-0099）
STATUS_MD_CHAR_LIMIT = 3500
# 「3行程度」の目安は文字数で判定する。物理行数だと、短文を折り返した決定が警告になる一方で
# 1行にまとめた長い決定がすり抜けるという逆転が起きるため（実測でD-0051とD-0050が逆転した）。
DECISION_BODY_CHAR_LIMIT = 400
RECENT_DECISIONS = 5

# docs/tasks.md「## 今日」節直下の日付マーカー（rotate-today-tasks.pyが更新する・D-0097）が
# 今日の日付と一致するかの検知に使う（rotate-today-tasks.py実行漏れの機械検知・D-0102）。
TASKS_TODAY_HEADING = "## 今日"
TASKS_DATE_MARKER_RE = re.compile(r"^<!--\s*date:\s*(\d{4}-\d{2}-\d{2})\s*-->$")

# docs/ideas.md「## ストック」節に進捗情報が書き込まれていないかの検知に使う
# （ideas.mdを「未着手の題材在庫リスト」に純化する運用の機械チェック・D-0105）。
IDEAS_STOCK_HEADING = "## ストック"
IDEAS_FORBIDDEN_WORDS = [
    "記事化",
    "公開済み",
    "下書き",
    "quality-reviewer",
    "hero画像",
    "pin画像",
    "投稿待ち",
    "生成待ち",
    "判定済み",
    "push完了",
    "次回セッション",
]

# フックスクリプト自身の残留デバッグ検知（D-0069の再発防止・D-0070）。
# 対象スクリプトは .claude/settings.json・.claude/settings.local.json の hooks 項から
# 動的に洗い出す（固定リストにしない）。
SETTINGS_FILES = ["settings.json", "settings.local.json"]

# 削除予定を示唆したまま残っているコメント（部分一致・大小文字区別なし）
DEBUG_COMMENT_MARKERS = [
    "TEMP DEBUG",
    "一時デバッグ",
    "完了後に削除",
]

# デバッグ専用ログファイルへの書き込みを示唆するパターン。
# 正規の成果物（reports/YYYY-MM-DD.md等）を誤検知しないよう、ファイル名・変数名に
# 「debug」を含む場合、または一時ディレクトリ（tmp/temp）への書き込みに限定する。
DEBUG_LOG_PATTERNS = [
    re.compile(r"(?i)\bdebug_log\b"),
    re.compile(r"(?i)\bDEBUG_LOG_PATH\b"),
    re.compile(r"(?i)[\"'][^\"']*debug[^\"']*\.(log|txt)[\"']"),
    re.compile(r"(?i)[\"'][^\"']*[\\/](tmp|temp)[\\/][^\"']*[\"']"),
]

STATE_HEADER = [
    "# doc-state.tsv — 運営文書（CLAUDE.md・decisions.md・rules/）の変更検出用の状態台帳",
    "#",
    "# このファイルは自動生成。手で編集しない。",
    "# site/scripts/check-doc-governance.py が読み書きする。",
    "# 形式: <種別> <キー> <値> のタブ区切り3列",
]


def sha256_of(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def collect_rules():
    """rules/配下の *.md について {ファイル名: ハッシュ} を返す。"""
    result = {}
    if not os.path.isdir(RULES_DIR):
        return result
    for name in sorted(os.listdir(RULES_DIR)):
        if name.endswith(".md"):
            result[name] = sha256_of(read_text(os.path.join(RULES_DIR, name)))
    return result


def load_state():
    """状態ファイルを {種別: {キー: 値}} で返す。存在しなければ None。"""
    if not os.path.isfile(STATE_TSV):
        return None
    state = {}
    for raw in read_text(STATE_TSV).split("\n"):
        line = raw.rstrip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        kind, key, value = parts
        state.setdefault(kind, {})[key] = value
    return state


def save_state(rules, max_d, claude_chars):
    lines = list(STATE_HEADER)
    for name in sorted(rules):
        lines.append("rules\t%s\t%s" % (name, rules[name]))
    lines.append("decisions\tmax-d\t%d" % max_d)
    lines.append("claude-md\tchars\t%d" % claude_chars)
    with io.open(STATE_TSV, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def collect_hook_scripts():
    """.claude/settings.json・settings.local.json のhooks項から、登録されている
    スクリプトの絶対パス一覧を動的に洗い出して返す（固定リストにしない）。
    JSON解析に失敗したファイル・hooks項が無いファイルはスキップする。
    """
    paths = set()
    for name in SETTINGS_FILES:
        settings_path = os.path.join(ROOT, ".claude", name)
        if not os.path.isfile(settings_path):
            continue
        try:
            data = json.loads(read_text(settings_path))
        except Exception:
            continue
        hooks = data.get("hooks", {})
        if not isinstance(hooks, dict):
            continue
        for groups in hooks.values():
            if not isinstance(groups, list):
                continue
            for group in groups:
                if not isinstance(group, dict):
                    continue
                for hook in group.get("hooks", []) or []:
                    if not isinstance(hook, dict):
                        continue
                    candidates = [hook.get("command")]
                    candidates.extend(hook.get("args", []) or [])
                    for c in candidates:
                        if isinstance(c, str) and c.endswith(".py"):
                            resolved = c.replace("${CLAUDE_PROJECT_DIR}", ROOT)
                            paths.add(os.path.normpath(resolved))
    return sorted(paths)


def check_hook_residue():
    """フックスクリプト自身に検証用デバッグの残留物がないかを検出する（D-0070）。"""
    warnings = []
    for path in collect_hook_scripts():
        if not os.path.isfile(path):
            continue
        text = read_text(path)
        reasons = []
        for marker in DEBUG_COMMENT_MARKERS:
            if marker.lower() in text.lower():
                reasons.append("削除予定を示唆するコメント「%s」" % marker)
        for pattern in DEBUG_LOG_PATTERNS:
            if pattern.search(text):
                reasons.append("デバッグ専用ログ書き込みの疑いのある記述（%s）" % pattern.pattern)
        if reasons:
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            warnings.append(
                "【警告】フックスクリプト %s に検証用デバッグの残留物の疑いがあります（%s）。"
                "削除するか正式な実装に統合してください。" % (rel, " / ".join(reasons))
            )
    return warnings


def check_tasks_marker(today):
    """docs/tasks.md「## 今日」節直下の日付マーカーが今日の日付と一致するかを検知する
    （rotate-today-tasks.py の実行漏れの機械検知・D-0102）。
    「## 今日」節が無い、直下の最初の非空行がマーカー形式でない、日付が今日と異なる、
    のいずれの場合も警告文字列を返す。問題なければNoneを返す。
    """
    if not os.path.isfile(TASKS_MD):
        return None
    lines = read_text(TASKS_MD).split("\n")
    in_today_section = False
    marker_date = None
    found_heading = False
    for line in lines:
        if line.strip() == TASKS_TODAY_HEADING:
            in_today_section = True
            found_heading = True
            continue
        if in_today_section:
            stripped = line.strip()
            if not stripped:
                continue
            match = TASKS_DATE_MARKER_RE.match(stripped)
            if match:
                marker_date = match.group(1)
            break
    if not found_heading or marker_date is None:
        return (
            "【警告】docs/tasks.md「## 今日」節直下に日付マーカー（<!-- date: YYYY-MM-DD -->）が"
            "見つかりません。rotate-today-tasks.py が実行されていない可能性があります。"
        )
    if marker_date != today:
        return (
            "【警告】docs/tasks.md の日付マーカーが%s で本日（%s）と一致しません。"
            "rotate-today-tasks.py が実行されていない可能性があります。" % (marker_date, today)
        )
    return None


def check_ideas_forbidden_words():
    """docs/ideas.md の「## ストック」節に進捗情報の禁止語が残っていないかを検知する
    （D-0105・ideas.mdを未着手の題材在庫リストに純化する運用の機械チェック）。
    禁止語を含む行がある場合、行番号と該当語を含む警告文字列のリストを返す。
    """
    if not os.path.isfile(IDEAS_MD):
        return []
    lines = read_text(IDEAS_MD).split("\n")
    warnings = []
    in_stock = False
    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped == IDEAS_STOCK_HEADING:
            in_stock = True
            continue
        if in_stock and stripped.startswith("## "):
            in_stock = False
        if not in_stock:
            continue
        hits = [w for w in IDEAS_FORBIDDEN_WORDS if w in line]
        if hits:
            warnings.append(
                "【警告】docs/ideas.md %d行目に進捗情報の禁止語が含まれています（%s）。"
                "ideas.mdのストック節に進捗情報を書かないこと。"
                "進捗の正本は記事frontmatterのstatusである（D-0105）。" % (i, "、".join(hits))
            )
    return warnings


def collect_post_slugs():
    """site/src/content/posts/ 配下の実在slug一覧を返す
    （prune-used-ideas.pyのcollect_slugs()と同じ定義）。"""
    slugs = []
    for path in glob.glob(os.path.join(POSTS_DIR, "*.md")):
        slugs.append(os.path.splitext(os.path.basename(path))[0])
    return slugs


def check_ideas_unchecked_published_slugs():
    """docs/ideas.md「## ストック」節の各行のうち、実在する記事slugを含みながら
    [ ]（未チェック）のままの行を検知する（D-0105補足）。

    [x] は「記事を公開した」ことのみを意味する運用に確定したため、公開済みの
    slugへ言及した行が未チェックのまま残っているのは、[x]の付け忘れの可能性が
    ある。ただし、差別化目的で既存記事のslugへ言及しているだけの正当な未着手行
    （例:「既存の◯◯記事(slug)とは別に」）もこの条件に該当するため、機械的に
    誤りと断定できない。よってこの関数の結果は常に【警告】として扱い、エラー
    （exit 1の直接要因）にはしない値としては返さず、他の警告と同様の重み付けで
    main()側に渡す（現状の実装では他の警告と同じくexit code 1になるが、内容が
    「要確認」であって「要修正」ではないことをメッセージ文で明示する）。
    """
    if not os.path.isfile(IDEAS_MD):
        return []
    slugs = collect_post_slugs()
    lines = read_text(IDEAS_MD).split("\n")
    warnings = []
    in_stock = False
    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped == IDEAS_STOCK_HEADING:
            in_stock = True
            continue
        if in_stock and stripped.startswith("## "):
            in_stock = False
        if not in_stock:
            continue
        if not stripped.startswith("- [ ]"):
            continue
        hits = [s for s in slugs if s in line]
        if hits:
            warnings.append(
                "【警告・要確認】docs/ideas.md %d行目、公開済み記事のslug（%s）が"
                "未チェックのままストック節に残っています。これが差別化目的の言及で"
                "あれば問題ありませんが、記事化済みの題材であれば [x] を付けて"
                "prune-used-ideas.py を実行してください（D-0105補足）。"
                % (i, "、".join(hits))
            )
    return warnings


def check_recent_decisions(entries):
    """直近RECENT_DECISIONS件の3行ルール逸脱を警告文のリストで返す。"""
    messages = []
    for entry in entries[:RECENT_DECISIONS]:
        chars = body_char_count(entry["body"])
        if chars > DECISION_BODY_CHAR_LIMIT:
            messages.append(
                "【警告】D-%04d の本体が%d字。decisions.md冒頭の3行ルール"
                "（目安上限%d字）を超えています。経緯は reports/ へ移してください。"
                % (entry["num"], chars, DECISION_BODY_CHAR_LIMIT)
            )
    return messages


def check_rules_diff(rules_now, prev_rules, max_d, prev_max_d, latest_date, today, today_entries_text):
    """rules/の差分から (警告, 通知, 増減あり, 本日付エントリ(全件)に言及あり) を返す。"""
    warnings = []
    notices = []

    added = sorted(set(rules_now) - set(prev_rules))
    removed = sorted(set(prev_rules) - set(rules_now))
    changed = sorted(n for n in set(rules_now) & set(prev_rules) if rules_now[n] != prev_rules[n])

    # 本日付エントリが複数あっても、entries[0]（先頭=最新）1件だけでなく全件を
    # 対象に言及有無を判定する（today_entries_textは呼び出し側で本日付エントリ
    # 全件を連結済み）。
    mentioned_today = latest_date == today and any(
        name in today_entries_text for name in added + removed
    )

    if added or removed:
        parts = []
        if added:
            parts.append("新設: " + ", ".join(added))
        if removed:
            parts.append("削除: " + ", ".join(removed))
        message = (
            "【警告】rules/配下のファイルが増減しています（%s）。"
            "CLAUDE.md 3節1によりオーナー承認とdecisions.mdへの記録が必要です。"
            % " / ".join(parts)
        )
        if mentioned_today:
            message += " decisions.mdの本日付エントリ（D-%04d）に該当ファイル名の言及あり。記録済みとみなします。" % max_d
        elif latest_date == today:
            message += (
                " decisions.mdに本日付の記録あり（D-%04d）ですが、該当ファイル名への言及が"
                "本文に見当たりません。この増減の記録か確認してください。" % max_d
            )
        else:
            message += " decisions.mdの最新エントリは%s（D-%04d）で、本日付の記録がありません。" % (
                latest_date or "日付なし",
                max_d,
            )
        if max_d <= prev_max_d:
            message += " 前回実行時から決定件数も増えていません。"
        warnings.append(message)

    if changed:
        notices.append(
            "【通知】rules/配下の内容が更新されています（%s）。3節1の対象外のため記録は不要です。"
            % ", ".join(changed)
        )

    return warnings, notices, bool(added or removed), mentioned_today


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    today = datetime.date.today().isoformat()

    rules_now = collect_rules()
    claude_chars, _ = count_chars_lines(read_text(CLAUDE_MD))
    decisions_text = read_text(DECISIONS_MD)
    decisions_chars, _ = count_chars_lines(decisions_text)
    entries = parse_decisions(decisions_text)
    max_d = max(e["num"] for e in entries) if entries else 0
    latest_date = heading_date(entries[0]["heading"]) if entries else None

    warnings = check_recent_decisions(entries)
    warnings += check_hook_residue()
    notices = []

    if claude_chars > CLAUDE_MD_CHAR_LIMIT:
        warnings.append(
            "【警告】CLAUDE.md が%d字で閾値%d字を超えています。"
            "フェーズ限定の規約は rules/ へ分割してください。" % (claude_chars, CLAUDE_MD_CHAR_LIMIT)
        )

    if decisions_chars > DECISIONS_MD_CHAR_LIMIT:
        warnings.append(
            "【警告】decisions.md が%d字で閾値%d字を超えています。"
            "archive-decisions.py で古い決定を docs/decisions-archive.md へ退避してください。"
            % (decisions_chars, DECISIONS_MD_CHAR_LIMIT)
        )

    status_chars, _ = count_chars_lines(read_text(STATUS_MD))
    if status_chars > STATUS_MD_CHAR_LIMIT:
        warnings.append(
            "【警告】status.md が%d字で閾値%d字を超えています。"
            "古い情報を消すか、詳細を reports/ への参照へ置き換えてください。"
            % (status_chars, STATUS_MD_CHAR_LIMIT)
        )

    tasks_warning = check_tasks_marker(today)
    if tasks_warning:
        warnings.append(tasks_warning)

    warnings += check_ideas_forbidden_words()
    warnings += check_ideas_unchecked_published_slugs()

    state = load_state()

    if state is None:
        save_state(rules_now, max_d, claude_chars)
        print(
            "初回実行: data/doc-state.tsv を作成しました（rules/ %d件・最大D番号 D-%04d・CLAUDE.md %d字）。"
            % (len(rules_now), max_d, claude_chars)
        )
        for message in warnings + notices:
            print(message)
        sys.exit(0)

    prev_rules = state.get("rules", {})
    prev_max_d = int(state.get("decisions", {}).get("max-d", "0") or 0)
    # 本日付エントリを「先頭(entries[0])の1件」だけでなく全件対象に連結する。
    # 記録直後にまだ一度も本スクリプトを実行しないうちに、無関係な決定が同日に
    # 先へ積まれると、entries[0]だけを見た場合は誤って「未記録」と判定される
    # ため（2026-08-02の追加検証で発覚・D-0054）。
    today_entries_text = "\n".join(
        entry["heading"] + "\n" + "\n".join(entry["body"])
        for entry in entries
        if heading_date(entry["heading"]) == today
    )

    rules_warnings, rules_notices, has_add_remove, mentioned_today = check_rules_diff(
        rules_now, prev_rules, max_d, prev_max_d, latest_date, today, today_entries_text
    )
    warnings = rules_warnings + warnings
    notices += rules_notices

    hold_rules = has_add_remove and not mentioned_today
    if hold_rules:
        notices.append("（rules/の状態は保存せず持ち越します。decisions.mdへ記録した日に解消されます）")
    save_state(prev_rules if hold_rules else rules_now, max_d, claude_chars)

    if not warnings and not notices:
        print("異常なし")
        sys.exit(0)

    for message in warnings + notices:
        print(message)
    sys.exit(1 if warnings else 0)


if __name__ == "__main__":
    main()
