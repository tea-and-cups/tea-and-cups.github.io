# -*- coding: utf-8 -*-
r"""docs/decisions.md（決定記録）のパース処理を共有するライブラリ。単体では実行しない。

check-doc-governance.py（3行ルール・容量チェック）と archive-decisions.py
（古い決定の退避）の両方から import される。パース結果の解釈が2箇所でずれると
決定記録が壊れるため、ここに一本化する。

文字数の数え方は count-doc-chars.py と同一（テキストモードで読み、len(text)で数える。
全角・半角を区別しない。改行は "\n" を数える）。
"""

import io
import re

HEADING_RE = re.compile(r"^## D-(\d{4}):")
ANY_HEADING_RE = re.compile(r"^## ")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
# 「追記」「詳細は reports/ 参照」等の注記行は3行ルールのカウント対象外にする
NOTE_BULLET_RE = re.compile(r"^[-*]\s*(追記|補足|注記|備考|詳細)")


def read_text(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


def write_text(path, text):
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def count_chars_lines(text):
    """count-doc-chars.py と同一の数え方。"""
    lines = text.count("\n") + (0 if text.endswith("\n") else 1)
    return len(text), lines


def heading_date(heading):
    """見出し行から最初に現れる YYYY-MM-DD を返す。無ければ None。"""
    matched = DATE_RE.search(heading)
    return matched.group(0) if matched else None


def parse_decisions(text):
    """decisions.md を [{num, heading, body}] に分解する（ファイル順＝新しい順）。

    body は見出し行の次から、次の "## " 行（D-XXXX以外の見出しも含む）の直前までの
    生の行のリスト（区切り線 "---" 等も含む・未加工）。3行ルール判定（body_char_count）
    用の分解であり、この body だけでは元テキストを完全再構成できない場合がある
    （プリアンブルや末尾テンプレートを含まないため）。原文を欠損なく移動する用途には
    split_decisions_document() を使う。
    """
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


def split_decisions_document(text):
    """decisions.md（またはdecisions-archive.md）を原文無欠損で3分割する。

    返り値: {"preamble_lines": [...], "entries": [{"num", "heading_date", "lines"}...], "trailing_lines": [...]}
    - entries はファイル順（新しい順）。各エントリの "lines" は見出し行を含む生の行
      （区切り線 "---" も、そのエントリの直後にあれば含まれる）のリストで、
      元テキストの当該範囲を一切改変しない。
    - preamble_lines は最初のD-XXXX見出しより前の全行（タイトル・運用ルール説明文等）。
    - trailing_lines は最後のD-XXXXエントリの直後、次の "## " 行（D-XXXX以外の見出し。
      decisions.mdの末尾テンプレート行 "## D-XXXX: タイトル（日付）" 等）から
      ファイル末尾までの全行。D-XXXX以外の見出しが無ければ空リスト。

    render_document(preamble_lines, [e["lines"] for e in entries], trailing_lines) は
    元のtextと完全一致する（このプロパティをテストで検証している）。行のリストのまま
    受け渡し、str化した空文字列を再splitして偽の空行を生まないようにするため、
    preamble/trailing は文字列ではなく行リストで保持する。
    """
    lines = text.split("\n")

    starts = [i for i, line in enumerate(lines) if HEADING_RE.match(line)]

    if not starts:
        return {"preamble_lines": lines, "entries": [], "trailing_lines": []}

    ends = []
    for start in starts:
        end = len(lines)
        for j in range(start + 1, len(lines)):
            if ANY_HEADING_RE.match(lines[j]):
                end = j
                break
        ends.append(end)

    preamble_lines = lines[: starts[0]]

    entries = []
    for start, end in zip(starts, ends):
        entry_lines = lines[start:end]
        num = int(HEADING_RE.match(entry_lines[0]).group(1))
        entries.append({
            "num": num,
            "heading_date": heading_date(entry_lines[0]),
            "lines": entry_lines,
        })

    trailing_lines = lines[ends[-1]:]

    return {"preamble_lines": preamble_lines, "entries": entries, "trailing_lines": trailing_lines}


def render_document(preamble_lines, entry_line_lists, trailing_lines):
    """split_decisions_document() の逆演算。preamble/entries[].lines/trailing から原文相当のテキストを再構成する。"""
    lines = list(preamble_lines)
    for entry_lines in entry_line_lists:
        lines.extend(entry_lines)
    lines.extend(trailing_lines)
    return "\n".join(lines)
