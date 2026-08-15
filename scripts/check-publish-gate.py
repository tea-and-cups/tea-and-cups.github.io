# -*- coding: utf-8 -*-
r"""Edit/Write による記事のpublished化を機械的に拒否する判定本体（D-0128）。

【背景】
published化がこれまで「Editでfrontmatter書き換え → Bashでcp → commit・push」の
3操作に分散しており、どの単一操作を見張っても抜け道が残っていた。
公開処理を site/scripts/publish-article.py に集約したうえで、それ以外の経路
（Edit・Write）をこの判定で塞ぐ。

【違反と判定する条件（これ以外は一切干渉しない）】
  Edit : 書き込み後の内容（new_string）に `status: published` が含まれ、かつ
         書き込み前の内容（old_string）に `status: draft` が含まれる
  Write: 対象パスが site/src/content/posts/ 配下である、または
         書き込む内容に `status: published` が含まれる

Editは記事修正のたびに多数発火するため、判定は文字列の包含のみで軽量に保つ。

【入出力】
  標準入力: PreToolUseフックが渡すツール入力のJSON
  標準出力: 違反時のみ、拒否理由の1行

終了コード: 0=該当なし（通す） / 1=違反（拒否させる） / 2=想定外エラー
  ※終了コードの2は「判定できなかった」であり違反ではない。呼び出し元
    （.claude/hooks/check-publish-gate.py）は2を非ブロッキング警告として扱う。

使い方（単体検証）:
  echo '{"tool_name":"Write","tool_input":{"file_path":"site/src/content/posts/x.md"}}' | python site/scripts/check-publish-gate.py
"""

import json
import re
import sys

MESSAGE = (
    "記事の公開は python site/scripts/publish-article.py <slug> で行う。"
    "公開前チェックを通さずに published 化することはできない"
)

RE_POSTS_DIR = re.compile(r"site/src/content/posts/", re.IGNORECASE)

STATUS_PUBLISHED = "status: published"
STATUS_DRAFT = "status: draft"


def judge(data):
    """違反ならTrueを返す。"""
    tool_name = data.get("tool_name")
    tool_input = data.get("tool_input") or {}

    if tool_name == "Edit":
        new_string = tool_input.get("new_string") or ""
        if STATUS_PUBLISHED not in new_string:
            return False
        old_string = tool_input.get("old_string") or ""
        return STATUS_DRAFT in old_string

    if tool_name == "Write":
        file_path = (tool_input.get("file_path") or "").replace("\\", "/")
        if RE_POSTS_DIR.search(file_path):
            return True
        return STATUS_PUBLISHED in (tool_input.get("content") or "")

    return False


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    try:
        raw = sys.stdin.read()
    except Exception as e:
        print("判定できませんでした（標準入力の読み取りに失敗: %s）" % e)
        return 2

    if not raw.strip():
        return 0

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # ツール入力として解釈できないものは判定対象外（通す）
        return 0

    try:
        if judge(data):
            print(MESSAGE)
            return 1
        return 0
    except Exception as e:
        print("判定できませんでした（%s）" % e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
