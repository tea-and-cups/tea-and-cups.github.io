# -*- coding: utf-8 -*-
r"""読み取り専用: 現在のセッションが使用したトークン数を集計して表示する。

このスクリプトはファイルへの書き込みを一切行わない。stop-hook-check.pyや
D-0056のStopフック挙動には影響を与えない（Stopフックからは呼ばれず、日次ルーチンの
固定サマリー出力前にAIが手動実行する想定。CLAUDE.md 5節ステップ6参照）。

■ セッション特定方法（実測で確認済み・2026-08-08）
環境変数 CLAUDE_CODE_SESSION_ID を使用する。Claude CodeがBash/PowerShellツールの
子プロセスに設定しており、値は現在のtranscriptファイル名（<session_id>.jsonl）と
一致することを実機で確認済み。
この環境変数が取得できない場合は「特定不可」と表示して何もせず終了する。
※ transcriptファイルの最終更新日時が最も新しいものを「今のセッション」とみなす代用案は
  採用していない。同時に複数のClaudeCodeウィンドウ／セッションを開いている場合に
  誤って別セッションのtranscriptを拾うリスクがあるため。

■ プロジェクトディレクトリ名の決定方法（D-0084・2026-08-10修正）
以前は os.getcwd()（実行時のカレントディレクトリ）からプロジェクトディレクトリ名を
組み立てていたが、Bashツールのcwdがcd等で本来のプロジェクトルート以外（例: site/）に
ずれた状態でこのスクリプトが呼ばれると、実際には存在しない別名
（例: ...-site）を参照してtranscriptファイルが見つからなくなる不具合があった
（実例はrules/command-execution.md 1節参照）。
このためstop-hook-check.pyの__file__基準の絶対パス解決と同じ方式に統一し、
本スクリプト自身の絶対パス（__file__）から2階層上（site/scripts → site → プロジェクトルート）
を求め、その絶対パスをslugifyしてプロジェクトディレクトリ名を得る。os.getcwd()は使わない。

■ トークン重複カウント対策
transcriptのJSONL内では、1つのassistantメッセージ（message.id）がストリーミング中の
スナップショットとして複数行にわたって重複記録される（実測で1メッセージあたり2〜4行が
一般的）。message.id単位で重複排除してから usage を合算する。

■ 対象範囲
- メイン会話: %USERPROFILE%\.claude\projects\<project-dir>\<session_id>.jsonl
- サブエージェント（quality-reviewer・researcher等）:
  同ディレクトリの <session_id>\subagents\*.jsonl を走査し、メイン分と分けて合算する

■ 対象外（既知の制約）
- Remote Control経由・外部チャット窓口経由のセッションは対象外とする
  （transcriptがローカルに同期されない場合があることを確認済み・2026-08-08調査）
- 複数のClaudeCodeウィンドウを同時に開いて同じプロジェクトを操作している場合、
  本スクリプトの集計自体は環境変数ベースのため誤爆しないが、
  参考情報程度に留めること（正式な課金上のトークン数ではなく概算）

使い方:
  python site/scripts/session-token-usage.py
"""

import glob
import json
import os
import re
import sys

USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# site/scripts -> site -> プロジェクトルート の2階層上。カレントディレクトリに依存しない。
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))


def slugify_path_to_project_dir(path):
    """Claude Codeのプロジェクトディレクトリ命名規則（英数字以外を全て'-'に置換）を再現する。
    D-0084: 以前はcwdを受け取っていたが、__file__基準の絶対パス（PROJECT_ROOT）を
    渡す運用に変更したため引数名・関数名をcwd非依存に改めた。"""
    return re.sub(r"[^a-zA-Z0-9]", "-", path)


def sum_usage_from_file(path):
    totals = {key: 0 for key in USAGE_KEYS}
    seen_ids = set()
    if not os.path.exists(path):
        return totals, 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("type") != "assistant":
                continue
            message = obj.get("message") or {}
            msg_id = message.get("id")
            if msg_id is None or msg_id in seen_ids:
                continue
            seen_ids.add(msg_id)
            usage = message.get("usage") or {}
            for key in USAGE_KEYS:
                totals[key] += usage.get(key, 0) or 0
    return totals, len(seen_ids)


def fmt(totals):
    return "input=%d output=%d cache_write=%d cache_read=%d" % (
        totals["input_tokens"],
        totals["output_tokens"],
        totals["cache_creation_input_tokens"],
        totals["cache_read_input_tokens"],
    )


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not session_id:
        print("トークン使用量: 特定不可（環境変数CLAUDE_CODE_SESSION_IDが取得できません）")
        return

    userprofile = os.environ.get("USERPROFILE")
    if not userprofile:
        print("トークン使用量: 特定不可（環境変数USERPROFILEが取得できません）")
        return

    project_dir = slugify_path_to_project_dir(PROJECT_ROOT)
    base_dir = os.path.join(userprofile, ".claude", "projects", project_dir)
    main_path = os.path.join(base_dir, session_id + ".jsonl")

    if not os.path.exists(main_path):
        print("トークン使用量: 特定不可（transcriptファイルが見つかりません: %s）" % main_path)
        return

    main_totals, main_count = sum_usage_from_file(main_path)

    sub_totals = {key: 0 for key in USAGE_KEYS}
    sub_count = 0
    subagents_dir = os.path.join(base_dir, session_id, "subagents")
    if os.path.isdir(subagents_dir):
        for path in glob.glob(os.path.join(subagents_dir, "*.jsonl")):
            t, c = sum_usage_from_file(path)
            for key in USAGE_KEYS:
                sub_totals[key] += t[key]
            sub_count += c

    print(
        "このセッションの使用トークン数（概算・メイン会話%dメッセージ分）: %s"
        % (main_count, fmt(main_totals))
    )
    if sub_count:
        print(
            "  うちサブエージェント分（%dメッセージ分）: %s" % (sub_count, fmt(sub_totals))
        )


if __name__ == "__main__":
    main()
