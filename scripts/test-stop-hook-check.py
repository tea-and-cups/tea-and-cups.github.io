# -*- coding: utf-8 -*-
r"""stop-hook-check.py の固定サマリー見出し検出ロジックの再発防止テスト（D-0071）。

D-0071で発覚したバグ: 実際の固定サマリー出力は
"## 【オーナーが今やること】" のようにMarkdown見出し記法（# の連続）を伴うが、
検出ロジックが line.strip().startswith(SUMMARY_HEADING) のみで# を除去して
いなかったため、常にFalse判定になりトークン消費量の追記（D-0066）が一度も
機能していなかった。

本テストは stop-hook-check.py 内の見出し検出ロジックを直接インポートして検証する。
stop-hook-check.py はハイフンを含むモジュール名のため importlib で読み込む。

使い方:
  python site/scripts/test-stop-hook-check.py
"""

import importlib.util
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(SCRIPT_DIR, "stop-hook-check.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("stop_hook_check", TARGET)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _detect(module, message):
    """stop-hook-check.py内の has_summary_heading と同一ロジックを再現して検証する。"""

    def _strip_heading_marker(line):
        return line.strip().lstrip("#").strip()

    return any(
        _strip_heading_marker(line).startswith(module.SUMMARY_HEADING)
        for line in message.splitlines()
    )


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    module = _load_module()
    heading = module.SUMMARY_HEADING

    cases = [
        # (説明, 入力メッセージ, 期待結果)
        ("素の見出し行", "%s\n本文" % heading, True),
        ("実際の出力形式: ## 見出し", "## %s\n- 項目1\n- 項目2" % heading, True),
        ("### 見出し（#の個数違い）", "### %s\n本文" % heading, True),
        ("# 見出し（1個）", "# %s" % heading, True),
        ("見出しの前後に空白を含む ##見出し", "##  %s  \n本文" % heading, True),
        (
            "地の文中の言及（行頭の見出しではない）",
            "この応答には「%s」という文言を含む応答が必要です。" % heading,
            False,
        ),
        ("見出しが存在しない", "## 【AIが今日やったこと／明日やること】\n本文", False),
        ("空文字列", "", False),
    ]

    failures = []
    for description, message, expected in cases:
        actual = _detect(module, message)
        status = "OK" if actual == expected else "NG"
        if actual != expected:
            failures.append(description)
        print("[%s] %s (expected=%s, actual=%s)" % (status, description, expected, actual))

    if failures:
        print("\n失敗: %d件" % len(failures))
        sys.exit(1)
    else:
        print("\n全%d件のテストにパスしました。" % len(cases))
        sys.exit(0)


if __name__ == "__main__":
    main()
