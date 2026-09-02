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
  8. docs/decisions.md 本文中の reports/ 参照が実在するか、および「本日のreports/」等の
     具体的なファイル名を伴わない曖昧参照になっていないか（D-0109） → 【警告】
     対象は decisions.md のみ、decisions-archive.md は対象外（3行ルールの対象外と同じ扱い）。
  9. docs/decisions.md 冒頭の境界行（D-0112）が decisions-archive.md の実データと整合しているか
     （境界行の存在・境界行の番号・archive側最大D番号+1とdecisions.md側最小D番号の一致） → 【警告】
     decisions-archive.md が存在しない場合は検査自体をスキップする。
 10. CLAUDE.md・rules/配下・docs/配下（decisions-archive.md除く）・.claude/agents/配下の
     本文中のD番号参照が、decisions.md または decisions-archive.md に見出しとして実在するか
     （D-0113） → 【警告】。site/scripts/配下・.claude/hooks/配下は対象外。
 11. docs/status.md 全文に、Pin投稿の未完了状態を示す禁止語（固定リスト）が含まれていないか
     （D-0114） → 【警告】。Pinの投稿状況の正本は data/pin-posted.md と
     check-pin-posting-status.py であり、status.md はその写しにしない。
 12. site/scripts/ の実ファイルについて、用途未記載とGit未追跡の2つを検出する → 【警告】
     PURPOSE（docstringも冒頭#コメントも無く用途が読み取れない）／
     UNTRACKED（実在するのにGit未追跡）の2判定。用途の抽出規則の正本は
     generate-script-index.py の extract_purpose() であり、ここへ書き写さず import して使う。
     UNTRACKEDは `git -C site ls-files scripts/` の出力と照合する。gitの実行または
     extract_purpose() の読み込みに失敗した場合は、黙って成功扱いにせず【警告】として出す
     （判定が消えたことに気づけないため）。

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
import importlib.util
import io
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from decisions_lib import (
    read_text,
    count_chars_lines,
    heading_date,
    parse_decisions,
    body_char_count,
    max_heading_num,
    build_boundary_line,
    BOUNDARY_LINE_RE,
)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RULES_DIR = os.path.join(ROOT, "rules")
CLAUDE_MD = os.path.join(ROOT, "CLAUDE.md")
DECISIONS_MD = os.path.join(ROOT, "docs", "decisions.md")
ARCHIVE_MD = os.path.join(ROOT, "docs", "decisions-archive.md")
STATUS_MD = os.path.join(ROOT, "docs", "status.md")
TASKS_MD = os.path.join(ROOT, "docs", "tasks.md")
IDEAS_MD = os.path.join(ROOT, "docs", "ideas.md")
DOCS_DIR = os.path.join(ROOT, "docs")
AGENTS_DIR = os.path.join(ROOT, ".claude", "agents")
POSTS_DIR = os.path.join(ROOT, "site", "src", "content", "posts")
STATE_TSV = os.path.join(ROOT, "data", "doc-state.tsv")
# site/scripts/ の健全性チェック（検出項目12）
SITE_DIR = os.path.join(ROOT, "site")
SCRIPTS_DIR = os.path.join(SITE_DIR, "scripts")
SCRIPTS_REL = "site/scripts"
# 用途1行の抽出規則の正本。ここでは再実装せず、このファイルから import して使う。
SCRIPT_INDEX_SCRIPT = os.path.join(SCRIPTS_DIR, "generate-script-index.py")
SCRIPT_EXTENSIONS = (".sh", ".py", ".ps1")
GIT_TIMEOUT_SECONDS = 30

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

# docs/decisions.md 本文中の reports/ 参照の検査に使う（D-0109・D-0110で対象を絞り込み）。
# この運用では reports/ への実参照は必ず「詳細は reports/… 参照」という決まった形で
# 書かれる。この形以外（書式の例示・決定記録本文中の引用等）は参照ではないため、
# 検査対象をこの表記の内側に限定する（D-0110）。
DECISIONS_DETAIL_REF_RE = re.compile(r"詳細は.*?参照")
# 実在性検査: reports/で始まり.mdで終わるパス表記を抽出する。
DECISIONS_REPORTS_PATH_RE = re.compile(r"reports/[A-Za-z0-9_\-]+\.md")
# パス中に YYYY・MM・DD のいずれかを含むものは書式のテンプレート表記とみなし、
# 実在性検査から除外する（D-0110）。
DECISIONS_REPORTS_TEMPLATE_RE = re.compile(r"YYYY|MM|DD")
# 曖昧参照検査: 「本日のreports/」等のあとに具体的な日付ファイル名
# （YYYY-MM-DD始まり）が続かない場合を曖昧参照とみなす。
DECISIONS_REPORTS_VAGUE_RE = re.compile(
    r"(本日|当日|その日|同日|今日)のreports/(?!\d{4}-\d{2}-\d{2})"
)

# D番号参照の実在性検査（D-0113）に使う。「D-」＋半角数字4桁で、直後が半角数字でも
# "-"でもないもののみを対象とする。これにより .claude/hooks/check-bash-command-style.py の
# D-2026-08-08-Downloads-check のような日付由来の識別子や、decisions.md末尾のテンプレート行
# 「D-XXXX」は、除外リストなしで自然に対象外になる。
D_NUMBER_REF_RE = re.compile(r"D-(\d{4})(?![\d\-])")

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

# docs/status.md にPin投稿の未完了状態を示す語が残っていないかの検知に使う
# （Pinの投稿状況の正本はdata/pin-posted.mdとcheck-pin-posting-status.pyであり、
# status.mdを第三の台帳として機能させないための機械チェック・D-0114）。
# 語を増やす場合はdecisions.mdへの記録を伴う変更とする（固定リスト）。
STATUS_FORBIDDEN_WORDS = [
    "投稿待ち",
    "未投稿",
    "投稿していない",
    "Pin未着手",
    "ピン未着手",
    "投稿未完了",
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

    行末に除外印 `<!-- 差別化参照 -->` を含む行は検知対象から外す（D-0110）。
    差別化目的の言及と結論済みの行が毎セッション警告として出続ける状態を、
    別ファイルの除外リストではなく対象行そのものへの印で解消する。行が消えれば
    除外も自動的に消える。除外印を使ってよいのは、実際にオーナー承認済みの
    窓口指示等で「差別化目的の言及であり対応不要」と結論が出ている行のみ。
    機械的な回避手段として乱用しないこと。
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
        if stripped.endswith("<!-- 差別化参照 -->"):
            continue
        hits = [s for s in slugs if s in line]
        if hits:
            warnings.append(
                "【警告】（要確認・差別化目的の言及なら対応不要）docs/ideas.md %d行目、"
                "公開済み記事のslug（%s）が未チェックのままストック節に残っています。"
                "これが差別化目的の言及であれば問題ありませんが、記事化済みの題材で"
                "あれば [x] を付けて prune-used-ideas.py を実行してください（D-0105補足）。"
                % (i, "、".join(hits))
            )
    return warnings


def check_status_forbidden_words():
    """docs/status.md 全文にPin投稿の未完了状態を示す禁止語が残っていないかを検知する
    （D-0114・status.mdをPin投稿状況の第三の台帳として機能させないための機械チェック）。
    禁止語を含む行がある場合、行番号と該当行・該当語を含む警告文字列のリストを返す。
    """
    if not os.path.isfile(STATUS_MD):
        return []
    lines = read_text(STATUS_MD).split("\n")
    warnings = []
    for i, line in enumerate(lines, start=1):
        hits = [w for w in STATUS_FORBIDDEN_WORDS if w in line]
        if hits:
            warnings.append(
                "【警告】docs/status.md %d行目にPin投稿の未完了状態を示す語が含まれています"
                "（%s）。該当行: %s ／ "
                "Pinの投稿状況は data/pin-posted.md と check-pin-posting-status.py が"
                "唯一の正本です。status.md には投稿の未完了状態を書かないでください（D-0114）。"
                % (i, "、".join(hits), line.strip())
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


def check_decisions_reports_references():
    """docs/decisions.md 本文中の reports/ 参照について、実在性検査と曖昧参照検知を
    行う（D-0109・D-0110で対象を絞り込み）。対象は decisions.md のみ、
    decisions-archive.md は対象外（decisions.mdは15,000字超過でarchiveへ退避される
    設計・D-0093により検査対象の文字数に構造的な上限がかかっているため、この
    コストは将来も一定に収まる）。

    検査対象は「詳細は」で始まり「参照」で終わる表記の内側のみ（DECISIONS_DETAIL_REF_RE）。
    書式の例示や決定記録本文中の引用はこの形を取らないため、対象を絞ることで
    件数に依存せず誤検知を構造的に除外する（D-0110）。
    """
    if not os.path.isfile(DECISIONS_MD):
        return []
    warnings = []
    lines = read_text(DECISIONS_MD).split("\n")
    for i, line in enumerate(lines, start=1):
        for span in DECISIONS_DETAIL_REF_RE.finditer(line):
            span_text = span.group(0)
            for match in DECISIONS_REPORTS_PATH_RE.finditer(span_text):
                rel_path = match.group(0)
                if DECISIONS_REPORTS_TEMPLATE_RE.search(rel_path):
                    continue  # 書式のテンプレート表記（例: reports/YYYY-MM-DD.md）
                abs_path = os.path.join(ROOT, rel_path)
                if not os.path.isfile(abs_path):
                    warnings.append(
                        "【警告】docs/decisions.md %d行目のreports/参照が実在しません（%s）。"
                        "ファイル名を確認して修正してください（D-0109）。" % (i, rel_path)
                    )
            for match in DECISIONS_REPORTS_VAGUE_RE.finditer(span_text):
                warnings.append(
                    "【警告】docs/decisions.md %d行目に具体的なファイル名を伴わないreports/参照が"
                    "あります（%s）。参照先ファイル名を明記してください（D-0109）。"
                    % (i, match.group(0))
                )
    return warnings


def check_archive_boundary():
    """docs/decisions.md 冒頭の境界行（D-0112）が、decisions-archive.md の実データと
    整合しているかを検査する。decisions-archive.md が存在しない、または見出しが
    1件も無い場合は検査自体をスキップする（[]を返す）。
    (1) 境界行の存在有無 (2) 境界行の番号がarchive側最大D番号と一致するか
    (3) archive側最大D番号+1がdecisions.md側の最小D番号と一致するか、の3点を検査する。
    """
    if not os.path.isfile(ARCHIVE_MD):
        return []
    archive_max = max_heading_num(read_text(ARCHIVE_MD))
    if archive_max is None:
        return []

    warnings = []
    fix_hint = "site/scripts/archive-decisions.py を実行すれば境界行は自動修復されます。"
    decisions_text = read_text(DECISIONS_MD) if os.path.isfile(DECISIONS_MD) else ""
    decisions_lines = decisions_text.split("\n")
    boundary_line = next((line for line in decisions_lines if BOUNDARY_LINE_RE.match(line)), None)

    if boundary_line is None:
        warnings.append(
            "【警告】docs/decisions.md 冒頭に境界行が見つかりません。"
            "期待値: 「%s」（decisions-archive.mdの最大D番号D-%04dに基づく）。%s（D-0112）"
            % (build_boundary_line(archive_max), archive_max, fix_hint)
        )
    else:
        matched = re.search(r"D-(\d{4})", boundary_line)
        boundary_num = int(matched.group(1)) if matched else None
        if boundary_num != archive_max:
            warnings.append(
                "【警告】docs/decisions.md の境界行の番号が%sですが、期待値はD-%04d"
                "（decisions-archive.mdの最大D番号）です。%s（D-0112）"
                % (("D-%04d" % boundary_num) if boundary_num is not None else "不明な形式", archive_max, fix_hint)
            )

    decisions_nums = [e["num"] for e in parse_decisions(decisions_text)]
    if decisions_nums:
        min_num = min(decisions_nums)
        expected_min = archive_max + 1
        if min_num != expected_min:
            warnings.append(
                "【警告】docs/decisions.md の最小D番号がD-%04dですが、期待値はD-%04d"
                "（decisions-archive.mdの最大D番号+1）です。%s（D-0112）"
                % (min_num, expected_min, fix_hint)
            )
    return warnings


def collect_d_reference_target_files():
    """D番号参照の実在性検査（D-0113）の対象ファイル一覧を返す。
    対象: CLAUDE.md本体・rules/配下の全.md・docs/配下の全.md（decisions-archive.md除く）・
    .claude/agents/配下の全.md。site/scripts/配下・.claude/hooks/配下は対象外（コード内
    コメントであり実害が無いため）。
    """
    paths = []
    if os.path.isfile(CLAUDE_MD):
        paths.append(CLAUDE_MD)
    if os.path.isdir(RULES_DIR):
        for name in sorted(os.listdir(RULES_DIR)):
            if name.endswith(".md"):
                paths.append(os.path.join(RULES_DIR, name))
    if os.path.isdir(DOCS_DIR):
        for dirpath, _dirnames, filenames in os.walk(DOCS_DIR):
            for name in sorted(filenames):
                if not name.endswith(".md"):
                    continue
                full = os.path.join(dirpath, name)
                if os.path.normpath(full) == os.path.normpath(ARCHIVE_MD):
                    continue
                paths.append(full)
    if os.path.isdir(AGENTS_DIR):
        for dirpath, _dirnames, filenames in os.walk(AGENTS_DIR):
            for name in sorted(filenames):
                if name.endswith(".md"):
                    paths.append(os.path.join(dirpath, name))
    return paths


def collect_valid_d_numbers():
    """decisions.md・decisions-archive.md の見出しに実在するD番号の集合を返す。"""
    valid = set()
    if os.path.isfile(DECISIONS_MD):
        valid.update(e["num"] for e in parse_decisions(read_text(DECISIONS_MD)))
    if os.path.isfile(ARCHIVE_MD):
        valid.update(e["num"] for e in parse_decisions(read_text(ARCHIVE_MD)))
    return valid


def check_d_number_references():
    """CLAUDE.md・rules/・docs/（decisions-archive.md除く）・.claude/agents/ 配下の
    D番号参照が、decisions.md または decisions-archive.md の見出しとして実在するかを
    検査する（D-0113）。実在しないものがあれば、D番号・ファイル名・行番号を列挙する。
    """
    valid_numbers = collect_valid_d_numbers()
    warnings = []
    for path in collect_d_reference_target_files():
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        for i, line in enumerate(read_text(path).split("\n"), start=1):
            for matched in D_NUMBER_REF_RE.finditer(line):
                num = int(matched.group(1))
                if num not in valid_numbers:
                    warnings.append(
                        "【警告】D-%04d の参照が decisions.md にも decisions-archive.md にも"
                        "実在しません（%s %d行目）。番号の誤記か記録漏れの可能性があります（D-0113）。"
                        % (num, rel, i)
                    )
    return warnings


def collect_script_files():
    """site/scripts/ 配下の実ファイル名の集合を返す（旧TMP_FILES相当）。
    ディレクトリ（__pycache__等）は拡張子フィルタで自然に除外される。"""
    if not os.path.isdir(SCRIPTS_DIR):
        return set()
    return set(n for n in os.listdir(SCRIPTS_DIR) if n.endswith(SCRIPT_EXTENSIONS))


def collect_tracked_scripts():
    """`git -C site ls-files scripts/` の出力からGit追跡済みスクリプト名の集合を返す
    （旧TMP_TRACKED相当）。gitの実行に失敗した場合は (None, 理由) を返し、
    呼び出し側で【警告】にする。黙って「追跡済み」扱いにすると、UNTRACKED判定が
    消えたことに気づけないsilent failureになるため（D-0138）。"""
    try:
        result = subprocess.run(
            ["git", "-C", SITE_DIR.replace("\\", "/"), "ls-files", "scripts/"],
            cwd=ROOT,
            capture_output=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except Exception as e:
        return None, "gitの起動に失敗しました（%s）" % e
    if result.returncode != 0:
        stderr_text = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        return None, "git ls-files が終了コード%dで失敗しました（%s）" % (result.returncode, stderr_text)
    stdout_text = (result.stdout or b"").decode("utf-8", errors="replace")
    tracked = set()
    for raw in stdout_text.split("\n"):
        path = raw.strip()
        if not path:
            continue
        name = path[len("scripts/"):] if path.startswith("scripts/") else path
        if name.endswith(SCRIPT_EXTENSIONS):
            tracked.add(name)
    return tracked, None


def load_extract_purpose():
    """generate-script-index.py の extract_purpose() を読み込んで返す。

    用途1行の抽出規則の正本はあちら1箇所であり、ここへ書き写さない
    （規則が2箇所へ分裂すると、片方だけ直した時に判定がずれるため）。
    ファイル名がハイフンを含みそのままimportできないため importlib で読み込む。
    あちらは実処理を `if __name__ == "__main__"` 配下の main() に置いており、
    importしただけでは索引生成もファイル書き込みも走らない。
    読み込みに失敗した場合は (None, None, 理由) を返し、呼び出し側で【警告】にする。
    """
    try:
        spec = importlib.util.spec_from_file_location(
            "generate_script_index", SCRIPT_INDEX_SCRIPT
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.extract_purpose, mod.PURPOSE_UNKNOWN, None
    except Exception as e:
        return None, None, "generate-script-index.py の読み込みに失敗しました（%s）" % e


def check_script_health():
    """site/scripts/ の実ファイルについて、用途未記載とGit未追跡を検出する（検出項目12）。

    用途未記載: generate-script-index.py の extract_purpose() が PURPOSE_UNKNOWN を
      返すファイル。docs/script-index.md の用途列が埋まらない状態を、索引を見に行く前に
      その場で気づけるようにする。
    Git未追跡: `git -C site ls-files scripts/` に現れないファイル（コミット漏れ）。
      判定ロジックは従来（D-0044・D-0138）から変更していない。
    """
    files = collect_script_files()
    warnings = []

    extract_purpose, purpose_unknown, load_error = load_extract_purpose()
    if extract_purpose is None:
        warnings.append(
            "【警告】スクリプトの用途未記載チェックができませんでした（%s）。"
            "今回は用途未記載の検知が行われていません。" % load_error
        )
    else:
        no_purpose = []
        for name in sorted(files):
            if extract_purpose(SCRIPTS_REL + "/" + name) == purpose_unknown:
                no_purpose.append(name)
        if no_purpose:
            warnings.append(
                "【警告】site/scripts/ に用途が読み取れないスクリプトがあります（%s）。"
                "docstring または冒頭#コメントに用途を1行書くこと。"
                % "、".join(no_purpose)
            )

    tracked, git_error = collect_tracked_scripts()
    if tracked is None:
        warnings.append(
            "【警告】Git追跡状況の照合ができませんでした（%s）。"
            "UNTRACKED判定（コミット漏れの検知）が今回は行われていません（D-0138）。" % git_error
        )
    else:
        untracked = sorted(files - tracked)
        if untracked:
            warnings.append(
                "【警告】site/scripts/ に実在するのにGit未追跡のスクリプトがあります（%s）。"
                "コミット漏れの可能性があります（D-0138）。" % "、".join(untracked)
            )
    return warnings


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
    warnings += check_decisions_reports_references()
    warnings += check_archive_boundary()
    warnings += check_d_number_references()
    warnings += check_status_forbidden_words()
    warnings += check_script_health()

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
