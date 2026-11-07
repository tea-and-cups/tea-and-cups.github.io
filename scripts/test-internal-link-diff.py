# -*- coding: utf-8 -*-
r"""check-internal-link-diff.py（内部リンクの追加だけを保証する検査と戻し・D-0324）のテスト。

本物の site/src/content/posts・output/articles には書き込まない。一時ディレクトリに作ったダミーの
記事を --base-file・--new-file・--posts-dir で渡し、次を確かめる:
  OK      リンクを1〜3本足しただけ（updated の行が変わっていても通る）
  NG(a)   リンクと同時に文字を1字変えた
  OK      上と同じだが --allow-text-change を付けた（b〜d は判定される）
  NG(b)   4本足した／自分自身へのリンク／既存のリンクと同じ先／同じ先へ2回
  NG(c)   見出し・表・引用・太字の質問文・冒頭の段落・既存リンクの内側に足した
  NG(d)   存在しない slug／status: draft の記事
  戻し    足したリンクを戻した結果が変更前の本文と一致する（他の先へのリンクは残る）

使い方:
  python site/scripts/test-internal-link-diff.py
"""

import io
import os
import shutil
import subprocess
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
SCRIPT = os.path.join(SCRIPT_DIR, "check-internal-link-diff.py")
FAILED = []


def check(label, cond, detail=""):
    print("%s  %s%s" % ("OK " if cond else "NG ", label, (" ... " + detail) if (detail and not cond) else ""))
    if not cond:
        FAILED.append(label)


def write(path, text):
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def article(posts_dir, slug, status="published"):
    write(os.path.join(posts_dir, slug + ".md"),
          "---\ntitle: %s\nslug: %s\ndate: 2026-10-01\nupdated: 2026-10-01\nstatus: %s\ncategory: how-to\n---\n\n本文\n"
          % (slug, slug, status))


BASE = """---
title: もとの記事
slug: src-article
date: 2026-09-01
updated: 2026-09-01
status: published
category: how-to
---

※当サイトはアフィリエイト広告（楽天アフィリエイト）を利用しています。

冒頭の段落です。水出し紅茶の保存について考えます。

## 保存の基本

作った紅茶は冷蔵庫で保存し、早めに飲み切ってください。賞味期限が切れた茶葉は香りが弱くなります。

茶葉の選び方は[茶葉の記事](/posts/existing-a/)を見てください。外部の[公式の案内文の説明](https://example.com/)もあります。

| 項目 | 内容 |
|---|---|
| 保存 | 冷蔵庫で保存 |

> 引用の中の保存の話です。

**Q. 何日もちますか？**
目安は2日です。急冷のコツもあります。
"""


def run(tmp, args, new_text, base_text=BASE):
    base_path = os.path.join(tmp, "base.md")
    new_path = os.path.join(tmp, "new.md")
    write(base_path, base_text)
    write(new_path, new_text)
    proc = subprocess.run(
        [sys.executable, SCRIPT] + args + ["--base-file", base_path, "--new-file", new_path,
                                           "--posts-dir", os.path.join(tmp, "posts")],
        capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    return proc.returncode, proc.stdout


def sub(text, old, new):
    assert old in text, old
    return text.replace(old, new, 1)


def ng_line(out, letter):
    return any(line.strip().startswith("NG  %s." % letter) for line in out.splitlines())


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    tmp = tempfile.mkdtemp(prefix="test-internal-link-diff-")
    try:
        posts = os.path.join(tmp, "posts")
        os.makedirs(posts)
        for slug in ("tgt-one", "tgt-two", "tgt-three", "tgt-four", "existing-a", "src-article"):
            article(posts, slug)
        article(posts, "draft-one", status="draft")

        def check_mode(*extra):
            return ["check", "src-article"] + list(extra)

        # --- OK: 1〜3本足しただけ -------------------------------------------
        one = sub(BASE, "冷蔵庫で保存し、早めに", "[冷蔵庫で保存し](/posts/tgt-one/)、早めに")
        code, out = run(tmp, check_mode(), one)
        check("OK: 1本足しただけ", code == 0 and "src-article → 冷蔵庫で保存し → tgt-one" in out, out)

        three = sub(one, "賞味期限が切れた茶葉", "[賞味期限が切れた茶葉](/posts/tgt-two/)")
        three = sub(three, "急冷のコツ", "[急冷のコツ](/posts/tgt-three/#kotsu)")
        three_upd = sub(three, "updated: 2026-09-01", "updated: 2026-11-07")
        code, out = run(tmp, check_mode(), three_upd)
        listed = [l for l in out.splitlines() if l.startswith("  src-article → ")]
        check("OK: 3本足しただけ（updated の行の変更は無視）", code == 0 and len(listed) == 3, out)

        # --- NG(a): 文字を1字変えた --------------------------------------------
        changed = sub(one, "早めに飲み切って", "早めに飲みきって")
        code, out = run(tmp, check_mode(), changed)
        check("NG(a): リンクと同時に文字を1字変えた", code == 1 and ng_line(out, "a"), out)

        code, out = run(tmp, check_mode("--allow-text-change"), changed)
        check("OK: 同じ変更に --allow-text-change（a を飛ばす）", code == 0 and "a. 本文の一致（--allow-text-change" in out, out)

        changed_bad = sub(changed, "急冷のコツ", "[急冷のコツ](/posts/src-article/)")
        code, out = run(tmp, check_mode("--allow-text-change"), changed_bad)
        check("NG(b): --allow-text-change でも b〜d は判定される", code == 1 and ng_line(out, "b") and not ng_line(out, "a"), out)

        # --- NG(b) ---------------------------------------------------------------
        four = sub(three, "目安は2日です", "[目安は2日](/posts/tgt-four/)です")
        code, out = run(tmp, check_mode(), four)
        check("NG(b): 4本足した", code == 1 and ng_line(out, "b") and "上限3本" in out, out)

        selfl = sub(BASE, "冷蔵庫で保存し、早めに", "[冷蔵庫で保存し](/posts/src-article/)、早めに")
        code, out = run(tmp, check_mode(), selfl)
        check("NG(b): 自分自身へのリンク", code == 1 and "自分自身へのリンク" in out, out)

        dup_existing = sub(BASE, "冷蔵庫で保存し、早めに", "[冷蔵庫で保存し](/posts/existing-a/)、早めに")
        code, out = run(tmp, check_mode(), dup_existing)
        check("NG(b): 既存のリンクと同じ先", code == 1 and "既存のリンクと同じ先" in out, out)

        twice = sub(one, "急冷のコツ", "[急冷のコツ](/posts/tgt-one/)")
        code, out = run(tmp, check_mode(), twice)
        check("NG(b): 同じ先へ2回", code == 1 and "同じ先へ2回以上" in out, out)

        # --- NG(c) ---------------------------------------------------------------
        cases_c = [
            ("見出しの行", "## 保存の基本", "## [保存の基本](/posts/tgt-one/)"),
            ("表の行", "| 保存 | 冷蔵庫で保存 |", "| 保存 | [冷蔵庫で保存](/posts/tgt-one/) |"),
            ("引用の行", "> 引用の中の保存の話です。", "> 引用の中の[保存の話](/posts/tgt-one/)です。"),
            ("太字の質問文の行", "**Q. 何日もちますか？**", "**Q. [何日もちますか](/posts/tgt-one/)？**"),
            ("冒頭の段落", "水出し紅茶の保存について", "[水出し紅茶の保存](/posts/tgt-one/)について"),
            ("既存リンクの文言の内側", "[公式の案内文の説明](https://example.com/)",
             "[公式の[案内文](/posts/tgt-one/)の説明](https://example.com/)"),
        ]
        for where, old, new in cases_c:
            code, out = run(tmp, check_mode(), sub(BASE, old, new))
            check("NG(c): %sに足した" % where, code == 1 and ng_line(out, "c") and where in out, out)

        # --- NG(d) ---------------------------------------------------------------
        missing = sub(BASE, "冷蔵庫で保存し、早めに", "[冷蔵庫で保存し](/posts/no-such-article/)、早めに")
        code, out = run(tmp, check_mode(), missing)
        check("NG(d): 存在しない slug", code == 1 and ng_line(out, "d") and "存在しない" in out, out)

        draft = sub(BASE, "冷蔵庫で保存し、早めに", "[冷蔵庫で保存し](/posts/draft-one/)、早めに")
        code, out = run(tmp, check_mode(), draft)
        check("NG(d): status: draft の記事", code == 1 and ng_line(out, "d") and "published でない" in out, out)

        # --- NG: 何も足していない ------------------------------------------------
        code, out = run(tmp, check_mode(), BASE)
        check("NG: 足したリンクが無い", code == 1 and "足したリンクがありません" in out, out)

        # --- 戻し ----------------------------------------------------------------
        code, out = run(tmp, ["revert", "src-article", "--targets", "tgt-one,tgt-two,tgt-three", "--dry-run"], three_upd)
        check("戻し: 足したリンク3本を戻すと変更前と一致", code == 0 and "RESULT: MATCH" in out and "戻すリンク: 3本" in out, out)

        code, out = run(tmp, ["revert", "src-article", "--targets", "tgt-one", "--dry-run"], three_upd)
        check("戻し: 先を1つに絞ると他のリンクは残り、変更前とは一致しない",
              code == 1 and "RESULT: MISMATCH" in out and "戻すリンク: 1本" in out and "/posts/tgt-two/" in out, out)

        code, out = run(tmp, ["revert", "src-article", "--targets", "existing-a", "--dry-run"], three_upd)
        check("戻し: 変更前からある既存リンクは戻さない", "戻すリンク: 0本" in out, out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILED:
        print("RESULT: NG（%d件）" % len(FAILED))
        for f in FAILED:
            print("  - " + f)
        return 1
    print("RESULT: OK（全ケース合格）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
