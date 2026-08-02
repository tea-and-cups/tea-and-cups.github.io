# -*- coding: utf-8 -*-
"""CLAUDE.md と rules/ 配下の規約ファイルの文字数を数える（引数なしで実行）。

CLAUDE.md の肥大化防止（CLAUDE.md 判断原則4・10節）の確認用。
分割・移動を行ったあとに「本体＋rules/ の合計」が分割前と大きく減っていないかを見る。
使い方: python site/scripts/count-doc-chars.py
"""
import io
import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RULES_DIR = os.path.join(ROOT, "rules")


def count(path):
    text = io.open(path, encoding="utf-8").read()
    lines = text.count("\n") + (0 if text.endswith("\n") else 1)
    return len(text), lines


targets = []
claude_md = os.path.join(ROOT, "CLAUDE.md")
if os.path.isfile(claude_md):
    targets.append(("CLAUDE.md", claude_md))

if os.path.isdir(RULES_DIR):
    for name in sorted(os.listdir(RULES_DIR)):
        if name.endswith(".md"):
            targets.append(("rules/" + name, os.path.join(RULES_DIR, name)))

if not targets:
    sys.stderr.write("CLAUDE.md も rules/*.md も見つかりません\n")
    sys.exit(1)

total_chars = 0
total_lines = 0
print("%-34s %10s %8s" % ("ファイル", "文字数", "行数"))
print("-" * 54)
for label, path in targets:
    chars, lines = count(path)
    total_chars += chars
    total_lines += lines
    print("%-34s %10d %8d" % (label, chars, lines))
print("-" * 54)
print("%-34s %10d %8d" % ("合計", total_chars, total_lines))
