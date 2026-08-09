# -*- coding: utf-8 -*-
r"""stop-hook-check.py の固定サマリー見出し検出ロジックの再発防止テスト（D-0071・D-0081）。

D-0071で発覚したバグ: 実際の固定サマリー出力は
"## 【オーナーが今やること】" のようにMarkdown見出し記法（# の連続）を伴うが、
検出ロジックが line.strip().startswith(SUMMARY_HEADING) のみで# を除去して
いなかったため、常にFalse判定になりトークン消費量の追記（D-0066）が一度も
機能していなかった。

D-0081で発覚したバグ: D-0071の修正は#の除去にしか対応しておらず、実際のセッション
transcriptを実測したところ "**【オーナーが今やること】**" のような太字（**）記法
でも出力されていることが判明した（過去セッションで多数実測・c3e43d4eセッション等）。
装飾記号を都度列挙して剥がす方式は、未対応の記法が出るたびに同種の検知漏れを
繰り返す構造的な脆さを持つと判断し、行の中にマーカー文字列が含まれているかの
部分一致判定（has_summary_heading_in()）に置き換えた。

本テストは stop-hook-check.py の has_summary_heading_in() を直接インポートして
検証する（テスト側でロジックを再実装しない。再実装すると、本体側だけ直して
テスト側が古いロジックのまま残る＝検知しない、という事態を招くため）。
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


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    module = _load_module()
    heading = module.SUMMARY_HEADING
    detect = module.has_summary_heading_in

    cases = [
        # (説明, 入力メッセージ, 期待結果)
        ("無装飾（D-0080指示の1）: 「- 見出し」", "- %s\n本文" % heading, True),
        ("素の見出し行（装飾なし）", "%s\n本文" % heading, True),
        ("#見出し（D-0080指示の2）: ## 見出し", "## %s\n- 項目1\n- 項目2" % heading, True),
        ("### 見出し（#の個数違い）", "### %s\n本文" % heading, True),
        ("# 見出し（1個）", "# %s" % heading, True),
        (
            "太字（D-0080指示の3・実際にc3e43d4eセッションで発生した形）: **見出し**",
            "---\n\n**%s**\n- 項目1" % heading,
            True,
        ),
        ("__見出し__（アンダースコア太字）", "__%s__\n本文" % heading, True),
        ("見出しの前後に空白を含む ##見出し", "##  %s  \n本文" % heading, True),
        ("絵文字付き見出し: ## 📋 見出し", "## 📋 %s" % heading, True),
        (
            "地の文中の言及（行内に含まれる・意図的に緩めた判定のため今はTrue）",
            "この応答には「%s」という文言を含む応答が必要です。" % heading,
            True,
        ),
        ("見出しが存在しない", "## 【AIが今日やったこと／明日やること】\n本文", False),
        ("空文字列", "", False),
    ]

    failures = []
    for description, message, expected in cases:
        actual = detect(message)
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
