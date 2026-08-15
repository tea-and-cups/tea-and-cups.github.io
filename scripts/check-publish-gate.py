# -*- coding: utf-8 -*-
r"""Edit/Write による記事のpublished化を機械的に拒否する判定本体（D-0128）。

【背景】
published化がこれまで「Editでfrontmatter書き換え → Bashでcp → commit・push」の
3操作に分散しており、どの単一操作を見張っても抜け道が残っていた。
公開処理を site/scripts/publish-article.py に集約したうえで、それ以外の経路
（Edit・Write）をこの判定で塞ぐ。

【違反と判定する条件（これ以外は一切干渉しない・D-0129でパス限定へ変更）】
  1. Write: 書き込み先パスが site/src/content/posts/ 配下
  2. Write: 書き込み先パスが output/articles/ 配下で、かつ書き込む内容の
           frontmatter に published 指定がある
  3. Edit : 書き込み先パスが output/articles/ または site/src/content/posts/
           配下で、かつ old_string に draft 指定、new_string に published 指定がある

判定は必ずパス条件から評価し、パスが対象外なら内容を一切走査せずに通す。
公開経路は上記3つのパス操作しか存在しないため、パス限定にしてもゲートの強度は
落ちない。逆に、旧条件（内容に published 指定を含むWriteを無条件に拒否）は
日次レポート等の無関係なファイルのWriteまで拒否する副作用があったため廃止した。
Editは記事修正のたびに多数発火するため、判定は軽量に保つ。

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
RE_DRAFTS_DIR = re.compile(r"output/articles/", re.IGNORECASE)

# frontmatter（先頭の --- 〜 --- ）を取り出す。区切りが無い場合はNoneを返す
RE_FRONTMATTER = re.compile(r"\A\s*---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)

STATUS_PUBLISHED = "status: published"
STATUS_DRAFT = "status: draft"


def frontmatter_of(content):
    """先頭のfrontmatterを返す。区切りが無ければ内容全体を返す（安全側）。"""
    m = RE_FRONTMATTER.match(content)
    return m.group(1) if m else content


def judge(data):
    """違反ならTrueを返す。パス条件を先に評価し、対象外なら内容を走査しない。"""
    tool_name = data.get("tool_name")
    tool_input = data.get("tool_input") or {}
    file_path = (tool_input.get("file_path") or "").replace("\\", "/")

    in_posts = bool(RE_POSTS_DIR.search(file_path))
    in_drafts = bool(RE_DRAFTS_DIR.search(file_path))

    if not in_posts and not in_drafts:
        # 記事の公開経路ではない。内容が何であれ通す
        return False

    if tool_name == "Write":
        # 条件1: 公開先ディレクトリへの直接書き込みは内容を問わず違反
        if in_posts:
            return True
        # 条件2: 下書きディレクトリへの書き込みはfrontmatterのみを見る
        return STATUS_PUBLISHED in frontmatter_of(tool_input.get("content") or "")

    if tool_name == "Edit":
        # 条件3: draft → published への書き換えのみ違反
        if STATUS_PUBLISHED not in (tool_input.get("new_string") or ""):
            return False
        return STATUS_DRAFT in (tool_input.get("old_string") or "")

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
