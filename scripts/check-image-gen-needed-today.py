# -*- coding: utf-8 -*-
r"""今回のセッションでChatGPT経由の画像生成が発生するかを、固定タグの完全一致だけで判定する
（読み取り専用・他ファイルへの書き込みは行わない）。

背景: Claude for Chromeのchatgpt.comへの移動確認は、拡張機能の仕様上セッション中に
必ず一度は出る（回避不可）。この確認を画像生成の直前ではなくセッション冒頭に前倒しできるよう、
「今回のセッションで画像生成が発生するか」を判定する。

判定方式（重要）: status.md・tasks.mdの自由記述文からキーワードの有無や近接関係を推測する
方式は採用しない。D-0071（stdin文字化けにより見出し検知が一度も機能していなかった不具合）と
同種の失敗を避けるため、「書く側が固定タグを機械的に書く」「読む側はそのタグの完全一致
（exact substring match）だけを見る」設計にする。あいまいな推測ロジックは持たせない。

判定対象:
  1. docs/status.md の全文に「【画像生成持ち越しあり】」という文字列が完全一致で含まれるか
  2. docs/tasks.md の「## 今日」節（次の「## 」見出しの直前まで）に
     「[新規記事執筆]」という文字列が完全一致で含まれるか

出力:
  いずれかが真であれば "NEEDED: <該当箇所>" を1行以上、両方偽であれば "NOT_NEEDED" を出力する。
  ブロックや強制終了は行わない（情報提供のみ）。終了コードは常に0。

使い方:
  python site/scripts/check-image-gen-needed-today.py
"""

import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATUS_MD = os.path.join(ROOT, "docs", "status.md")
TASKS_MD = os.path.join(ROOT, "docs", "tasks.md")

STATUS_TAG = "【画像生成持ち越しあり】"
TASKS_TAG = "[新規記事執筆]"


def read_text(path):
    if not os.path.isfile(path):
        return ""
    with io.open(path, "r", encoding="utf-8") as f:
        return f.read()


def extract_today_section(tasks_text):
    """tasks.mdの「## 今日」節（次の「## 」見出しの直前まで）を返す。節が無ければ空文字。"""
    lines = tasks_text.split("\n")
    start = None
    for i, line in enumerate(lines):
        if line.strip() == "## 今日":
            start = i + 1
            break
    if start is None:
        return ""
    end = len(lines)
    for i in range(start, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    return "\n".join(lines[start:end])


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    reasons = []

    status_text = read_text(STATUS_MD)
    if STATUS_TAG in status_text:
        reasons.append("NEEDED: docs/status.md に「%s」あり" % STATUS_TAG)

    tasks_today = extract_today_section(read_text(TASKS_MD))
    if TASKS_TAG in tasks_today:
        reasons.append("NEEDED: docs/tasks.md「今日」欄に「%s」あり" % TASKS_TAG)

    if reasons:
        for r in reasons:
            print(r)
    else:
        print("NOT_NEEDED")

    sys.exit(0)


if __name__ == "__main__":
    main()
