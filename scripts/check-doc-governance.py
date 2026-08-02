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
import hashlib
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RULES_DIR = os.path.join(ROOT, "rules")
CLAUDE_MD = os.path.join(ROOT, "CLAUDE.md")
DECISIONS_MD = os.path.join(ROOT, "docs", "decisions.md")
STATE_TSV = os.path.join(ROOT, "data", "doc-state.tsv")

CLAUDE_MD_CHAR_LIMIT = 10000
# 「3行程度」の目安は文字数で判定する。物理行数だと、短文を折り返した決定が警告になる一方で
# 1行にまとめた長い決定がすり抜けるという逆転が起きるため（実測でD-0051とD-0050が逆転した）。
DECISION_BODY_CHAR_LIMIT = 400
RECENT_DECISIONS = 5

STATE_HEADER = [
    "# doc-state.tsv — 運営文書（CLAUDE.md・decisions.md・rules/）の変更検出用の状態台帳",
    "#",
    "# このファイルは自動生成。手で編集しない。",
    "# site/scripts/check-doc-governance.py が読み書きする。",
    "# 形式: <種別> <キー> <値> のタブ区切り3列",
]

HEADING_RE = re.compile(r"^## D-(\d{4}):")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
# 「追記」「詳細は reports/ 参照」等の注記行は3行ルールのカウント対象外にする
NOTE_BULLET_RE = re.compile(r"^[-*]\s*(追記|補足|注記|備考|詳細)")


def read_text(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


def count_chars_lines(text):
    """count-doc-chars.py と同一の数え方。"""
    lines = text.count("\n") + (0 if text.endswith("\n") else 1)
    return len(text), lines


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


def parse_decisions(text):
    """decisions.md を [{num, heading, body}] に分解する（ファイル順＝新しい順）。"""
    entries = []
    current = None
    for raw in text.split("\n"):
        matched = HEADING_RE.match(raw)
        if matched:
            current = {"num": int(matched.group(1)), "heading": raw.rstrip(), "body": []}
            entries.append(current)
            continue
        if current is not None:
            if raw.startswith("## "):
                current = None  # D-XXXX以外の見出しが来たらそのエントリは終わり
                continue
            current["body"].append(raw)
    return entries


def heading_date(heading):
    """見出し行から最初に現れる YYYY-MM-DD を返す。無ければ None。

    D-0032「（…・2026-08-01）」やD-0009「（2026-07-21・2026-07-23更新）」のように
    日付が複数あったり末尾以外にある見出しも拾える。D-0001はプレースホルダーのため None。
    """
    matched = DATE_RE.search(heading)
    return matched.group(0) if matched else None


def body_char_count(body):
    """「決定」「理由」「決定者」本体の文字数を返す（注記行とその継続行は除外）。"""
    chars = 0
    in_note = False
    for raw in body:
        stripped = raw.strip()
        if not stripped or stripped == "---":
            continue
        if raw.startswith("- ") or raw.startswith("* "):
            in_note = NOTE_BULLET_RE.match(stripped) is not None
        if in_note:
            continue
        chars += len(stripped)
    return chars


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
    entries = parse_decisions(read_text(DECISIONS_MD))
    max_d = max(e["num"] for e in entries) if entries else 0
    latest_date = heading_date(entries[0]["heading"]) if entries else None

    warnings = check_recent_decisions(entries)
    notices = []

    if claude_chars > CLAUDE_MD_CHAR_LIMIT:
        warnings.append(
            "【警告】CLAUDE.md が%d字で閾値%d字を超えています。"
            "フェーズ限定の規約は rules/ へ分割してください。" % (claude_chars, CLAUDE_MD_CHAR_LIMIT)
        )

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
