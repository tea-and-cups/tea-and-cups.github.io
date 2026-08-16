# -*- coding: utf-8 -*-
r"""スクリプトの存在と起動元の索引 docs/script-index.md を生成する（引数なしで実行）。

読み取り専用の走査のみを行い、docs/script-index.md を毎回全面再生成する。
既存の索引を部分更新することはしない（差分マージによる取りこぼしを避けるため）。

■ 抽出源（この4つに限定する。他を混ぜない）
  (a) .claude/settings.json と .claude/settings.local.json のフック定義（JSONパース）
  (b) session-start-check.py の CHILD_SCRIPTS
  (c) publish-article.py の PRE_PUBLISH_CHECKS
  (d) stop-hook-check.py の *_SCRIPT 定数（GOVERNANCE_SCRIPT / GDRIVE_SYNC_SCRIPT /
      TOKEN_USAGE_SCRIPT 等）および .claude/hooks/ 配下の、site/scripts/ を指す
      文字列リテラル固定のパス定数

  抽出は文字列リテラルとして確定できるものだけを採用する（Pythonソースは ast で解析し、
  os.path.join(SCRIPT_DIR, "x.py") / PROJECT_DIR / "site" / "scripts" / "x.py" のように
  リテラルだけで組み立てられた式のみを採る）。実行時に組み立てられる値・変数に依存する
  値は採用しない。したがって索引は「機械的に確定できる範囲の起動元」を表し、
  Windows Task Scheduler や CLAUDE.md 等の文章指示からの起動は原理的に検出できない。

■ 3節「未分類の呼び出し【要確認】」
  (a)〜(d) に該当しないのに他スクリプトの起動らしき記述（subprocess・os.system 等）を
  含むファイルを列挙する。除外は EXCLUDED_FROM_UNCLASSIFIED でのみ行う。

■ 失敗時の挙動
  走査・生成のいずれかに失敗した場合、既存の docs/script-index.md には一切触れず、
  エラー内容を標準出力に出して終了コード1で終わる。内容はすべてメモリ上で組み立て切って
  から最後に1回だけ書き出すため、部分的な内容や空ファイルで上書きされることはない。

使い方:
  python site/scripts/generate-script-index.py            docs/script-index.md を再生成
  python site/scripts/generate-script-index.py --dry-run  書き込まず内容を標準出力へ
"""

import ast
import datetime
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SITE_ROOT = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SITE_ROOT)

SCRIPTS_REL = "site/scripts"
HOOKS_REL = ".claude/hooks"
OUTPUT_REL = "docs/script-index.md"

SETTINGS_FILES = [".claude/settings.json", ".claude/settings.local.json"]
SESSION_START_SCRIPT = "session-start-check.py"
PUBLISH_SCRIPT = "publish-article.py"
STOP_HOOK_SCRIPT = "stop-hook-check.py"

# 3節の除外リスト。ここに挙げたファイルは subprocess 等を含んでいても
# 【要確認】として列挙しない。追加はオーナーの判断を経てから行う。
EXCLUDED_FROM_UNCLASSIFIED = [
    # stop-hook-check.py の判定関数を検証するためのテストであり、
    # 運用上の起動連鎖ではない（呼ぶのは常に人手・単体実行）。
    "test-stop-hook-check.py",
]

# 「他スクリプトの起動らしき記述」の検出に使う os モジュールの関数名。
# 検出は素朴な文字列一致ではなく ast による構文解析で行う。文字列一致方式では
# docstringやこの定数自身の記述に反応して自分自身を【要確認】に載せてしまうため。
OS_INVOCATION_FUNCS = ("system", "popen", "spawnl", "spawnv", "spawnve", "execv", "execvp")
SUBPROCESS_MODULE = "subprocess"

HEADER_NOTE = (
    "このファイルは generate-script-index.py が自動生成する。手で編集しない。\n"
    "「自動起動は検出されず」は、上記の抽出範囲内で起動元が見つからなかったことを意味する。\n"
    "Windows Task Scheduler・CLAUDE.md 等の文章指示からの起動は検出できない。\n"
)

HOOK_EVENT_ORDER = ["SessionStart", "Stop", "PreToolUse", "PostToolUse"]

RE_HOOK_TARGET = re.compile(r"((?:site/scripts|\.claude/hooks)/[A-Za-z0-9_.\-]+\.py)")


class ScanError(Exception):
    """走査失敗。呼び出し側はこれを捕まえて終了コード1で終わる。"""


def abs_path(rel):
    return os.path.join(PROJECT_ROOT, rel.replace("/", os.sep))


def read_text(rel):
    path = abs_path(rel)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as exc:
        raise ScanError("%s の読み込みに失敗しました: %s" % (rel, exc))


def parse_module(rel):
    try:
        return ast.parse(read_text(rel))
    except SyntaxError as exc:
        raise ScanError("%s の構文解析に失敗しました: %s" % (rel, exc))


def literal_str(node):
    """ノードが文字列リテラルならその値を返す。それ以外は None。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def literal_path_parts(node):
    """os.path.join(...) / pathlib の `/` 連結の式から、文字列リテラルだけで
    構成された部品列を返す。リテラルとして確定できない部品が1つでも混ざる式は
    None を返す（変数・実行時組み立ては採用しない、の実装）。
    先頭の変数名（SCRIPT_DIR・PROJECT_DIR 等）は基点として許容し、部品列には含めない。
    """
    if isinstance(node, ast.Constant):
        text = literal_str(node)
        return [text] if text is not None else None
    if isinstance(node, ast.Name):
        # 基点となる変数（SCRIPT_DIR 等）。部品としては空扱い。
        return []
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = literal_path_parts(node.left)
        right = literal_path_parts(node.right)
        if left is None or right is None:
            return None
        return left + right
    if isinstance(node, ast.Call):
        func = node.func
        is_join = (
            isinstance(func, ast.Attribute)
            and func.attr == "join"
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "path"
        )
        if not is_join:
            return None
        parts = []
        for arg in node.args:
            sub = literal_path_parts(arg)
            if sub is None:
                return None
            parts.extend(sub)
        return parts
    return None


def detect_invocations(rel):
    """他スクリプトの起動らしき記述を ast で検出し、見つかった表記の一覧を返す。
    コメント・docstring・単なる文字列リテラル中の言及には反応しない。
    """
    tree = parse_module(rel)
    found = []

    def note(text):
        if text not in found:
            found.append(text)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == SUBPROCESS_MODULE:
                    note("import subprocess")
        elif isinstance(node, ast.ImportFrom):
            if node.module == SUBPROCESS_MODULE:
                note("from subprocess import ...")
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == SUBPROCESS_MODULE:
                note("subprocess.%s" % node.attr)
            elif node.value.id == "os" and node.attr in OS_INVOCATION_FUNCS:
                note("os.%s" % node.attr)
    return found


def script_name_from_parts(parts):
    """部品列が site/scripts 配下の .py を指していればファイル名を返す。"""
    if not parts:
        return None
    last = parts[-1]
    if not last.endswith(".py"):
        return None
    joined = "/".join(parts).replace("\\", "/")
    if "scripts/" not in joined and len(parts) > 1:
        return None
    return last


# --- (a) settings のフック定義 ---------------------------------------------


def collect_hook_definitions():
    """[(イベント名, matcher, 起動されるファイルの相対パス, 定義元settingsファイル)] を返す。"""
    entries = []
    for rel in SETTINGS_FILES:
        path = abs_path(rel)
        if not os.path.exists(path):
            continue
        try:
            data = json.loads(read_text(rel))
        except Exception as exc:
            raise ScanError("%s のJSONパースに失敗しました: %s" % (rel, exc))
        hooks = data.get("hooks") or {}
        if not isinstance(hooks, dict):
            raise ScanError("%s の hooks がオブジェクトではありません" % rel)
        for event, groups in hooks.items():
            if not isinstance(groups, list):
                raise ScanError("%s の hooks.%s が配列ではありません" % (rel, event))
            for group in groups:
                matcher = (group or {}).get("matcher") or ""
                for hook in (group or {}).get("hooks") or []:
                    tokens = [str(hook.get("command") or "")]
                    tokens.extend(str(a) for a in (hook.get("args") or []))
                    for token in tokens:
                        found = RE_HOOK_TARGET.search(token.replace("\\", "/"))
                        if found:
                            entries.append((event, matcher, found.group(1), rel))
                            break
    if not entries:
        raise ScanError("settings のフック定義から起動スクリプトを1件も抽出できませんでした")
    return entries


# --- (b) session-start-check.py の CHILD_SCRIPTS ----------------------------


def collect_list_of_first_strings(rel, const_name):
    """モジュール直下の `NAME = [(...), ...]` から各要素の先頭文字列リテラルを集める。"""
    tree = parse_module(rel)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if const_name not in names:
            continue
        if not isinstance(node.value, (ast.List, ast.Tuple)):
            raise ScanError("%s の %s がリテラルのリストではありません" % (rel, const_name))
        result = []
        for elt in node.value.elts:
            text = literal_str(elt)
            if text is None and isinstance(elt, (ast.Tuple, ast.List)) and elt.elts:
                text = literal_str(elt.elts[0])
            if text is None:
                raise ScanError(
                    "%s の %s に文字列リテラルとして確定できない要素があります" % (rel, const_name)
                )
            result.append(text)
        if not result:
            raise ScanError("%s の %s が空です" % (rel, const_name))
        return result
    raise ScanError("%s に %s が見つかりません" % (rel, const_name))


# --- (d) *_SCRIPT 定数 ------------------------------------------------------


def collect_script_constants(rel):
    """モジュール直下の代入のうち、site/scripts 配下の .py を文字列リテラルだけで
    指しているものを [(定数名, ファイル名)] として、ソース上の出現順で返す。
    """
    tree = parse_module(rel)
    found = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        parts = literal_path_parts(node.value)
        if parts is None:
            continue
        name = script_name_from_parts(parts)
        if not name:
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                found.append((target.id, name))
    return found


# --- ファイル一覧 -----------------------------------------------------------


def list_real_files(rel_dir, extensions=None):
    path = abs_path(rel_dir)
    if not os.path.isdir(path):
        raise ScanError("%s が存在しません" % rel_dir)
    names = []
    for name in sorted(os.listdir(path)):
        if not os.path.isfile(os.path.join(path, name)):
            continue
        if extensions and not name.endswith(extensions):
            continue
        names.append(name)
    if not names:
        raise ScanError("%s にファイルがありません" % rel_dir)
    return names


# --- 索引の組み立て ---------------------------------------------------------


def build_index():
    hook_entries = collect_hook_definitions()
    child_scripts = collect_list_of_first_strings(
        SCRIPTS_REL + "/" + SESSION_START_SCRIPT, "CHILD_SCRIPTS"
    )
    publish_checks = collect_list_of_first_strings(
        SCRIPTS_REL + "/" + PUBLISH_SCRIPT, "PRE_PUBLISH_CHECKS"
    )
    stop_constants = collect_script_constants(SCRIPTS_REL + "/" + STOP_HOOK_SCRIPT)

    hook_files = list_real_files(HOOKS_REL, extensions=(".py",))
    hook_constants = {}
    for hook_file in hook_files:
        consts = collect_script_constants(HOOKS_REL + "/" + hook_file)
        if consts:
            hook_constants[hook_file] = consts

    script_files = list_real_files(SCRIPTS_REL)

    # 起動元マップ: 相対パス -> 起動元の説明の一覧
    callers = {}

    def add_caller(rel_target, description):
        callers.setdefault(rel_target, [])
        if description not in callers[rel_target]:
            callers[rel_target].append(description)

    for event, matcher, target, source in hook_entries:
        label = "%s フック" % event
        if matcher:
            label += "（matcher: %s）" % matcher
        add_caller(target, "%s ← %s" % (label, source))

    for name in child_scripts:
        add_caller(
            SCRIPTS_REL + "/" + name,
            "%s/%s の CHILD_SCRIPTS" % (SCRIPTS_REL, SESSION_START_SCRIPT),
        )
    for name in publish_checks:
        add_caller(
            SCRIPTS_REL + "/" + name,
            "%s/%s の PRE_PUBLISH_CHECKS" % (SCRIPTS_REL, PUBLISH_SCRIPT),
        )
    for const_name, name in stop_constants:
        add_caller(
            SCRIPTS_REL + "/" + name,
            "%s/%s の %s" % (SCRIPTS_REL, STOP_HOOK_SCRIPT, const_name),
        )
    for hook_file, consts in hook_constants.items():
        for const_name, name in consts:
            add_caller(
                SCRIPTS_REL + "/" + name,
                "%s/%s の %s" % (HOOKS_REL, hook_file, const_name),
            )

    # (a)〜(d) の抽出源そのものとして扱うファイル（3節の判定に使う）
    recognized_sources = set(
        [
            SCRIPTS_REL + "/" + SESSION_START_SCRIPT,
            SCRIPTS_REL + "/" + PUBLISH_SCRIPT,
            SCRIPTS_REL + "/" + STOP_HOOK_SCRIPT,
        ]
    )
    for hook_file in hook_constants:
        recognized_sources.add(HOOKS_REL + "/" + hook_file)

    lines = []
    lines.append("# スクリプト索引（自動生成）")
    lines.append("")
    lines.append(HEADER_NOTE.rstrip("\n"))
    lines.append("")

    # 1節 -------------------------------------------------------------------
    lines.append("## 1. 自動起動の連鎖")
    lines.append("")
    grouped = {}
    for event, matcher, target, source in hook_entries:
        grouped.setdefault(event, []).append((matcher, target, source))
    ordered_events = [e for e in HOOK_EVENT_ORDER if e in grouped]
    ordered_events += [e for e in sorted(grouped) if e not in HOOK_EVENT_ORDER]

    for event in ordered_events:
        lines.append("### %s" % event)
        lines.append("")
        for matcher, target, source in grouped[event]:
            lines.append("- matcher: %s" % (matcher if matcher else "（指定なし）"))
            lines.append("  - %s" % target)
            name = target.split("/")[-1]
            if name == SESSION_START_SCRIPT:
                for child in child_scripts:
                    lines.append("    - %s/%s" % (SCRIPTS_REL, child))
            elif name == STOP_HOOK_SCRIPT:
                for const_name, child in stop_constants:
                    lines.append("    - %s/%s  （%s）" % (SCRIPTS_REL, child, const_name))
            else:
                hook_name = target.split("/")[-1]
                for const_name, child in hook_constants.get(hook_name, []):
                    lines.append("    - %s/%s  （%s）" % (SCRIPTS_REL, child, const_name))
        lines.append("")

    # 2節 -------------------------------------------------------------------
    lines.append("## 2. 起動元つきスクリプト一覧")
    lines.append("")
    lines.append("### %s（%d件）" % (SCRIPTS_REL, len(script_files)))
    lines.append("")
    for name in script_files:
        rel = SCRIPTS_REL + "/" + name
        sources = callers.get(rel)
        lines.append("- %s — %s" % (name, " / ".join(sources) if sources else "自動起動は検出されず"))
    lines.append("")
    lines.append("### %s（%d件）" % (HOOKS_REL, len(hook_files)))
    lines.append("")
    for name in hook_files:
        rel = HOOKS_REL + "/" + name
        sources = callers.get(rel)
        lines.append("- %s — %s" % (name, " / ".join(sources) if sources else "自動起動は検出されず"))
    lines.append("")

    # 3節 -------------------------------------------------------------------
    lines.append("## 3. 未分類の呼び出し【要確認】")
    lines.append("")
    unclassified = []
    for rel_dir, names in ((SCRIPTS_REL, script_files), (HOOKS_REL, hook_files)):
        for name in names:
            if not name.endswith(".py"):
                continue
            rel = rel_dir + "/" + name
            if rel in recognized_sources:
                continue
            if name in EXCLUDED_FROM_UNCLASSIFIED:
                continue
            hits = detect_invocations(rel)
            if hits:
                unclassified.append("- %s — %s を含む" % (rel, "・".join(hits)))
    if unclassified:
        lines.extend(unclassified)
    else:
        lines.append("該当なし")
    lines.append("")

    # 4節 -------------------------------------------------------------------
    lines.append("## 4. 生成日時")
    lines.append("")
    lines.append(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    lines.append("")

    return "\n".join(lines)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    dry_run = "--dry-run" in sys.argv[1:]

    try:
        content = build_index()
    except ScanError as exc:
        print("エラー: 索引の生成に失敗しました。docs/script-index.md は変更していません。")
        print("  %s" % exc)
        sys.exit(1)
    except Exception as exc:
        print("エラー: 索引の生成中に想定外の例外が発生しました。docs/script-index.md は変更していません。")
        print("  %s: %s" % (type(exc).__name__, exc))
        sys.exit(1)

    if dry_run:
        print(content)
        sys.exit(0)

    out_path = abs_path(OUTPUT_REL)
    try:
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
    except Exception as exc:
        print("エラー: %s の書き込みに失敗しました: %s" % (OUTPUT_REL, exc))
        sys.exit(1)

    print("%s を再生成しました。" % OUTPUT_REL)
    sys.exit(0)


if __name__ == "__main__":
    main()
