# -*- coding: utf-8 -*-
r"""10〜12月の gift・seasons 週3本の判定（GD-0007・GD-0043）と、型8の執筆年月の再発防止テスト。

本物の docs/tasks.md・site/src/content/posts・output/ には書き込まない。一時ディレクトリに作った
ダミーの記事と tasks.md を使い、次の4群を確かめる:
  1. rotate-today-tasks.py の category_quota_status（必要な日・必要でない日・10月より前/12月より後・境界）
  2. rotate-today-tasks.py を --dry-run --date --posts-dir --tasks-file で起動した出力
     （CATEGORY_QUOTA_REQUIRED／OK の行と、MONTHLY_NEXT が改修の行を選ばないこと）
  3. publish-article.py の check_category_quota（新規公開・--revise の通す/止める）と --today の取り扱い
  4. check-fact-source.py の型8（「YYYY年M月執筆」を含む節は通り、年月が無い節は止まる）
最後に参考として、本物の公開記事で 2026-10-13〜10-18 の各日の判定を表示する（読み取りのみ・合否に使わない）。

使い方:
  python site/scripts/test-category-quota.py
"""

import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
FAILED = []


def load(file_name):
    spec = importlib.util.spec_from_file_location(
        file_name[:-3].replace("-", "_"), os.path.join(SCRIPT_DIR, file_name))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check(label, cond, detail=""):
    print("%s  %s%s" % ("OK " if cond else "NG ", label, (" ... " + detail) if (detail and not cond) else ""))
    if not cond:
        FAILED.append(label)


def write(path, text):
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def article(posts_dir, slug, date, category, status="published"):
    write(os.path.join(posts_dir, slug + ".md"),
          "---\ntitle: %s\nslug: %s\ndate: %s\nupdated: %s\nstatus: %s\ncategory: %s\n---\n\n本文\n"
          % (slug, slug, date, date, status, category))


def run_rotate(args):
    proc = subprocess.run([sys.executable, os.path.join(SCRIPT_DIR, "rotate-today-tasks.py")] + args,
                          capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    return proc.stdout.splitlines()


# 2026-11-02(月)〜11-08(日) を対象週にする。前週の日曜 11-01 と翌週の月曜 11-09 は数えない。
WEEK = {"mon": "2026-11-02", "tue": "2026-11-03", "wed": "2026-11-04", "thu": "2026-11-05",
        "fri": "2026-11-06", "sat": "2026-11-07", "sun": "2026-11-08"}


def build_posts(tmp, n_in_week, today_gift=False):
    """対象週に gift・seasons を n_in_week 本置く（数えないもの: 前後の週・draft・他カテゴリ・改修だけの updated）。"""
    d = os.path.join(tmp, "posts-%d-%s" % (n_in_week, today_gift))
    if os.path.isdir(d):
        return d
    os.makedirs(d)
    article(d, "prev-sun-gift", "2026-11-01", "gift")
    article(d, "next-mon-gift", "2026-11-09", "gift")
    article(d, "draft-gift", "2026-11-03", "gift", status="draft")
    article(d, "howto-in-week", "2026-11-03", "how-to")
    days = ["2026-11-02", "2026-11-04", "2026-11-05"]
    cats = ["gift", "seasons", "gift"]
    for i in range(n_in_week):
        article(d, "q%d" % i, days[i], cats[i])
    if today_gift:
        article(d, "today-gift", WEEK["sat"], "gift")
    return d


def group_status(rot, tmp):
    print("--- 1. category_quota_status ---")
    cases = [
        ("火曜・0本・残り6日 → 必要でない", WEEK["tue"], 0, False),
        ("金曜・0本・残り3日 → 必要（3-0=3 ≥ 3）", WEEK["fri"], 0, True),
        ("金曜・1本・残り3日 → 必要でない（2 < 3）", WEEK["fri"], 1, False),
        ("土曜・1本・残り2日 → 必要（2 ≥ 2）", WEEK["sat"], 1, True),
        ("土曜・2本・残り2日 → 必要でない（1 < 2）", WEEK["sat"], 2, False),
        ("日曜・2本・残り1日 → 必要（1 ≥ 1）", WEEK["sun"], 2, True),
        ("日曜・3本・残り1日 → 必要でない", WEEK["sun"], 3, False),
    ]
    for label, day, n, want in cases:
        st = rot.category_quota_status(day, build_posts(tmp, n))
        check(label, st is not None and st["required"] == want and st["count"] == n,
              repr(st))
    st = rot.category_quota_status(WEEK["fri"], build_posts(tmp, 1))
    check("残り日数は今日を含む（金曜=3日）", st["remaining_days"] == 3, repr(st))
    check("前後の週・draft・他カテゴリを数えない（0本の週で count=0）",
          rot.category_quota_status(WEEK["tue"], build_posts(tmp, 0))["count"] == 0)
    check("10月より前（2026-09-30）は対象外 None", rot.category_quota_status("2026-09-30", build_posts(tmp, 0)) is None)
    check("12月より後（2027-01-01）は対象外 None", rot.category_quota_status("2027-01-01", build_posts(tmp, 0)) is None)
    st = rot.category_quota_status("2026-10-01", build_posts(tmp, 0))
    check("境界 2026-10-01（木・週は 9/28〜10/4・残り4日）は必要でない",
          st is not None and not st["required"] and st["remaining_days"] == 4
          and st["week_start"] == "2026-09-28", repr(st))
    st = rot.category_quota_status("2026-12-31", build_posts(tmp, 0))
    check("境界 2026-12-31 は対象（木曜・残り4日・必要でない）", st is not None and not st["required"], repr(st))
    check("必要でない日は CATEGORY_QUOTA_OK だけを返す",
          rot.category_quota_lines(rot.category_quota_status(WEEK["tue"], build_posts(tmp, 0)))
          == ["CATEGORY_QUOTA_OK 今週 0/3"])
    lines = rot.category_quota_lines(rot.category_quota_status(WEEK["fri"], build_posts(tmp, 0)))
    check("必要な日は REQUIRED と題材の探し方の2行",
          len(lines) == 2 and lines[0] == "CATEGORY_QUOTA_REQUIRED 今週 0/3・残り3日" and "ideas.md" in lines[1]
          and "advance-pin-calendar.tsv" in lines[1], repr(lines))
    check("対象期間外は何も出さない", rot.category_quota_lines(None) == [])


TASKS = (
    "# tasks.md — ダミー\n\n## 今日\n<!-- date: {d} -->\n\n## 今週\n\n## 今月\n<!-- month: {m} -->\n"
    "- [ ] [M-1] [改修] 先頭の改修（GD-0032・判定X）（rev-a・how-to）\n"
    "- [ ] [M-2] [改修+画像] 画像つき改修（rev-b・gift）（上限外）\n"
    "- [ ] [M-3] [新規記事執筆] howto の新規（new-howto・how-to）\n"
    "{gift}\n## バックログ\n"
)
GIFT_ROW = "- [ ] [M-4] [新規記事執筆] ギフトの新規（new-gift・gift）\n"


def group_cli(tmp):
    print("--- 2. rotate-today-tasks.py の出力 ---")
    for label, day, n, with_gift_row, want_first in [
        ("必要な日・gift 新規の行あり → その行を選び、改修を保留と数える", WEEK["fri"], 0, True, "MONTHLY_NEXT: - [ ] [M-4]"),
        ("必要な日・gift・seasons の新規の行なし → MONTHLY_NONE", WEEK["fri"], 0, False, "MONTHLY_NONE"),
        ("必要でない日 → 従来どおり先頭の改修", WEEK["tue"], 0, True, "MONTHLY_NEXT: - [ ] [M-1]"),
    ]:
        tasks = os.path.join(tmp, "tasks-%s-%s.md" % (day, with_gift_row))
        write(tasks, TASKS.format(d=day, m=day[:7], gift=GIFT_ROW if with_gift_row else ""))
        lines = run_rotate(["--dry-run", "--date", day, "--posts-dir", build_posts(tmp, n), "--tasks-file", tasks])
        last = lines[-1] if lines else ""
        check(label, last.startswith(want_first), last)
        if "必要な日" in label:
            check("  └ REQUIRED の行が先頭側に出る", any(l.startswith("CATEGORY_QUOTA_REQUIRED 今週 0/3・残り3日") for l in lines), repr(lines))
            check("  └ 改修保留の注記（2行）", "（週3本のため改修保留2行）" in last, last)
        else:
            check("  └ OK の行を出す（REQUIRED は出さない）",
                  any(l.startswith("CATEGORY_QUOTA_OK 今週 0/3") for l in lines)
                  and not any(l.startswith("CATEGORY_QUOTA_REQUIRED") for l in lines), repr(lines))
            check("  └ 改修保留の注記が付かない", "改修保留" not in last, last)
    tasks = os.path.join(tmp, "tasks-before.md")
    write(tasks, TASKS.format(d="2026-09-30", m="2026-09", gift=GIFT_ROW))
    lines = run_rotate(["--dry-run", "--date", "2026-09-30", "--posts-dir", build_posts(tmp, 0), "--tasks-file", tasks])
    check("10月より前は CATEGORY_QUOTA の行を出さず、従来どおり先頭の改修",
          not any(l.startswith("CATEGORY_QUOTA") for l in lines) and lines[-1].startswith("MONTHLY_NEXT: - [ ] [M-1]"),
          repr(lines))
    # 改修の月上限（D-0273）との併用: 上限に達していても、必要な日は gift・seasons の新規だけを選ぶ
    check("quota_required=False の既定は従来の関数どおり（引数なしで呼べる）",
          load("rotate-today-tasks.py").monthly_next_line(TASKS.format(d="x", m="x", gift="").split("\n")).startswith("MONTHLY_NEXT"))


def group_publish(rot, pub, tmp):
    print("--- 3. publish-article.py の判定 ---")
    req_posts = build_posts(tmp, 0)          # 金曜・0本 → 必要
    ok_posts = build_posts(tmp, 0)           # 火曜 → 必要でない
    fri, tue = WEEK["fri"], WEEK["tue"]
    for cat, want in [("how-to", False), ("tea-leaves", False), ("teaware", False), ("gift", True), ("seasons", True)]:
        ok, line = pub.check_category_quota(cat, False, fri, req_posts)
        check("必要な日・新規公開 category=%s → %s" % (cat, "OK" if want else "NG"), ok == want, line)
    for cat in ("how-to", "gift"):
        ok, line = pub.check_category_quota(cat, False, tue, ok_posts)
        check("必要でない日・新規公開 category=%s → OK" % cat, ok and "CATEGORY_QUOTA_OK" in line, line)
    ok, line = pub.check_category_quota("how-to", True, fri, req_posts)
    check("必要な日・今日の gift・seasons 新規が無い → --revise は NG", not ok and "--revise" in line, line)
    sat_posts = build_posts(tmp, 1, today_gift=True)   # 土曜: 前に1本+今日の gift 1本=2本 → 必要でない（1<2）
    st = rot.category_quota_status(WEEK["sat"], sat_posts)
    check("（準備）土曜に今日の gift が出ると 2本・必要でなくなる", st["count"] == 2 and not st["required"], repr(st))
    # 必要な日のまま今日の新規がある状態: 日曜・今週2本のうち1本が今日(日曜)の gift
    sun_posts = os.path.join(tmp, "sun")
    os.makedirs(sun_posts)
    article(sun_posts, "w1", "2026-11-03", "gift")
    article(sun_posts, "sun-today", WEEK["sun"], "seasons")
    st = rot.category_quota_status(WEEK["sun"], sun_posts)
    check("（準備）日曜・2本（うち1本が今日）は必要（1 ≥ 1）かつ published_today=1",
          st["required"] and st["published_today"] == 1, repr(st))
    ok, line = pub.check_category_quota("how-to", True, WEEK["sun"], sun_posts)
    check("必要な日・今日の gift・seasons 新規がある → --revise は OK", ok, line)
    ok, line = pub.check_category_quota("how-to", False, WEEK["sun"], sun_posts)
    check("  └ ただし新規公開は引き続き gift・seasons のみ（how-to は NG）", not ok, line)
    ok, line = pub.check_category_quota("how-to", True, tue, ok_posts)
    check("必要でない日・--revise は OK", ok, line)
    ok, line = pub.check_category_quota("how-to", False, "2026-09-30", ok_posts)
    check("10月より前は新規公開も OK（対象期間外）", ok and "対象期間外" in line, line)
    ok, line = pub.check_category_quota(None, False, fri, req_posts)
    check("必要な日・category を読めない新規公開は NG（通さない）", not ok, line)
    # --today の取り扱い
    rest, today, err = pub.pop_today_arg(["slug", "--dry-run", "--today", "2026-10-13"])
    check("--today は --dry-run と一緒なら取り出せる", rest == ["slug", "--dry-run"] and today == "2026-10-13" and err is None,
          repr((rest, today, err)))
    _, _, err = pub.pop_today_arg(["slug", "--today", "2026-10-13"])
    check("--today は --dry-run なしだと拒否（本番で判定を迂回させない）", err is not None, repr(err))
    _, _, err = pub.pop_today_arg(["slug", "--dry-run", "--today", "10-13"])
    check("--today の日付の形が違えば拒否", err is not None, repr(err))
    rest, today, err = pub.pop_today_arg(["slug", "--dry-run"])
    check("--today が無ければ何も変えない", rest == ["slug", "--dry-run"] and today is None and err is None)


def group_type8(tmp):
    print("--- 4. 型8（執筆年月）---")
    fs = load("check-fact-source.py")

    def hits_for(section_text, name):
        p = os.path.join(tmp, name + ".md")
        write(p, "---\ntitle: t\nslug: %s\ndate: 2026-10-18\ncategory: gift\nstatus: draft\n---\n\n"
                 "## ギフトの予算の目安\n\n%s\n" % (name, section_text))
        return [v for v in fs.check_xy(p, name) if "型8" in v.get("hit", "")]

    check("「2026年10月執筆」を含む節は OK", not hits_for("相場は2026年10月執筆の時点で3,000円前後といわれています。", "t8a"))
    check("「2026年10月執筆」だけ（時点なし）でも OK", not hits_for("2026年10月執筆。相場は3,000円前後です。", "t8b"))
    check("「2026年10月時点」は引き続き OK", not hits_for("2026年10月時点で3,000円前後です。", "t8c"))
    check("「2026年10月執筆時点」も引き続き OK", not hits_for("2026年10月執筆時点で3,000円前後です。", "t8d"))
    check("全角数字「２０２６年１０月執筆」も OK", not hits_for("２０２６年１０月執筆。", "t8e"))
    check("年月が何も無い節は NG", len(hits_for("相場は3,000円前後です。", "t8f")) == 1)
    check("「執筆」だけで年月が無ければ NG", len(hits_for("執筆時点の相場は3,000円前後です。", "t8g")) == 1)


def show_real(rot):
    print("--- 参考: 本物の公開記事での判定（読み取りのみ）---")
    for day in ("2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16", "2026-10-17", "2026-10-18"):
        st = rot.category_quota_status(day)
        print("  %s  週 %s〜%s  gift・seasons %d/3  残り%d日  %s  今日の新規 %d本"
              % (day, st["week_start"], st["week_end"], st["count"], st["remaining_days"],
                 "必要" if st["required"] else "必要でない", st["published_today"]))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    tmp = tempfile.mkdtemp(prefix="test-category-quota-")
    try:
        rot = load("rotate-today-tasks.py")
        pub = load("publish-article.py")
        group_status(rot, tmp)
        group_cli(tmp)
        group_publish(rot, pub, tmp)
        group_type8(tmp)
        show_real(rot)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("")
    if FAILED:
        print("失敗 %d 件: %s" % (len(FAILED), " / ".join(FAILED)))
        sys.exit(1)
    print("すべて OK")


if __name__ == "__main__":
    main()
