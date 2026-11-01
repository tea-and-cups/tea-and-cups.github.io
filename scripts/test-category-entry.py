# -*- coding: utf-8 -*-
r"""カテゴリページの入口5本（editorial.ts の selectCategoryEntry）のテスト。

引数なしは次を確かめる（本物のファイルには書き込まない）:
  1. 本物の設定を1年の全日（366日）でまわし、5本・重複なし・時期の過ぎた記事が前に来ないこと
  2. seasonal・spokes の slug が公開済みで同じカテゴリ、seasonal のないカテゴリは spokes のまま
  3. 選び方の関数（年またぎ・並び順）と日本時間の日付・日付の固定指定
  4. ビルド時のチェック（categoryEntryErrors）が崩れた設定を返すこと

--build はさらに astro build を動かす（dist を上書きする）:
  5. 日本時間 2026-11-01・2026-12-24・2027-01-10 に固定したビルドの gift・seasons の並びを表示する
  6. editorial.ts を一時的に崩してビルドが止まることを確かめ、元へ戻す（途中で落ちても finally で戻す）
  7. 最後に日付を固定せずビルドし、dist を今日の状態へ戻す

--save-dist <dir> は dist の HTML を保存し、--diff-dist <dir> は保存時から変わった HTML を一覧する。

使い方:
  python site/scripts/test-category-entry.py
  python site/scripts/test-category-entry.py --build
  python site/scripts/test-category-entry.py --save-dist <dir>
  python site/scripts/test-category-entry.py --diff-dist <dir>
"""

import io
import json
import os
import re
import shutil
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(SCRIPT_DIR)
EDITORIAL = os.path.join(SITE, "src", "data", "editorial.ts")
POSTS = os.path.join(SITE, "src", "content", "posts")
DIST = os.path.join(SITE, "dist")
BUILD_TIMEOUT = 600
FIXED_DATES = ("2026-11-01", "2026-12-24", "2027-01-10")
FAILED = []

NODE_DUMP = r"""
import { CATEGORY_EDITORIAL as E, selectCategoryEntry as sel, categoryEntryToday as today, categoryEntryErrors as errs } from '__URL__';
const days = __DAYS__;
const out = { editorial: E, entries: {}, fixture: {}, today: {}, errors: {} };
for (const c of Object.keys(E)) out.entries[c] = Object.fromEntries(days.map((d) => [d, sel(E[c], d)]));
const F = { spokes: ['e1', 'e2'], seasonal: [
  { slug: 'wrap', from: '12-10', to: '01-15' },
  { slug: 'nov', from: '11-01', to: '12-20' },
  { slug: 'short', from: '11-10', to: '11-20' },
  { slug: 'spring', from: '03-01', to: '03-10' },
  { slug: 'summer', from: '07-01', to: '08-31' },
] };
for (const d of ['01-05', '11-15', '12-15', '02-29', '12-31', '01-15', '01-16']) out.fixture[d] = sel(F, d);
delete process.env.GITHUB_ACTIONS;
delete process.env.CATEGORY_ENTRY_TODAY;
out.today.before_midnight = today(new Date('2026-10-31T14:59:00Z'));
out.today.after_midnight = today(new Date('2026-10-31T15:00:00Z'));
process.env.CATEGORY_ENTRY_TODAY = '2026-12-24';
out.today.fixed = today(new Date('2026-10-31T15:00:00Z'));
process.env.GITHUB_ACTIONS = 'true';
out.today.ignored_on_actions = today(new Date('2026-10-31T15:00:00Z'));
delete process.env.GITHUB_ACTIONS;
process.env.CATEGORY_ENTRY_TODAY = '12-24';
try { today(); out.today.bad_format = 'no error'; } catch { out.today.bad_format = 'thrown'; }
delete process.env.CATEGORY_ENTRY_TODAY;
const post = (category) => ({ data: { category } });
const find = (slug) => ({ a1: post('gift'), a2: post('gift'), a3: post('gift'), a4: post('gift'), a5: post('gift'), other: post('seasons') })[slug];
const five = { spokes: ['a1', 'a2'], seasonal: [{ slug: 'a3', from: '01-01', to: '01-31' }, { slug: 'a4', from: '02-01', to: '02-29' }, { slug: 'a5', from: '12-31', to: '01-01' }] };
const withS = (i, patch) => ({ ...five, seasonal: five.seasonal.map((s, j) => (j === i ? { ...s, ...patch } : s)) });
const cases = {
  ok: five,
  ok_spokes_only: { spokes: ['a1', 'a2', 'a3', 'a4', 'a5'] },
  bad_from_shape: withS(0, { from: '1-1' }),
  bad_to_month: withS(0, { to: '13-01' }),
  bad_to_day: withS(0, { to: '02-30' }),
  bad_missing_to: withS(0, { to: undefined }),
  unpublished: withS(0, { slug: 'none' }),
  other_category: withS(0, { slug: 'other' }),
  spokes_unpublished: { ...five, spokes: ['a1', 'none'] },
  too_few: { spokes: ['a1'], seasonal: five.seasonal },
  duplicate: { ...five, spokes: ['a1', 'a3'] },
  spokes_only_six: { spokes: ['a1', 'a2', 'a3', 'a4', 'a5', 'a1'] },
  spokes_only_four: { spokes: ['a1', 'a2', 'a3', 'a4'] },
};
for (const [k, v] of Object.entries(cases)) out.errors[k] = errs('gift', v, find);
process.stdout.write(JSON.stringify(out));
"""


def check(label, cond, detail=""):
    print("%s  %s%s" % ("OK " if cond else "NG ", label, (" ... " + detail) if (detail and not cond) else ""))
    if not cond:
        FAILED.append(label)


def all_days():
    lengths = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return ["%02d-%02d" % (m + 1, d + 1) for m, n in enumerate(lengths) for d in range(n)]


def in_period(item, day):
    start, end = item["from"], item["to"]
    return start <= day <= end if start <= end else (day >= start or day <= end)


def order_problem(entry, spokes, seasonal, day):
    """入口の並びの問題を文字列で返す（無ければ None）。関数の実装とは独立に判定する。"""
    if len(entry) != 5:
        return "%d本" % len(entry)
    if len(set(entry)) != 5:
        return "重複"
    by_slug = {s["slug"]: s for s in seasonal}
    wanted = set(spokes) | {s["slug"] for s in seasonal if in_period(s, day)}
    past = [i for i, slug in enumerate(entry) if slug not in wanted]
    current = [i for i, slug in enumerate(entry) if slug in wanted]
    if past and current and min(past) < max(current):
        return "時期の過ぎた記事が先"
    if past and wanted - set(entry):
        return "時期の過ぎた記事が、入るべき記事を押し出した"
    if any(slug not in by_slug and slug not in spokes for slug in entry):
        return "設定に無い slug"
    return None


def load_posts():
    posts = {}
    for name in os.listdir(POSTS):
        if not name.endswith(".md"):
            continue
        with io.open(os.path.join(POSTS, name), encoding="utf-8") as f:
            text = f.read(2000)
        fields = dict(re.findall(r"^(slug|status|category):\s*['\"]?([^'\"\r\n]+)", text, re.M))
        posts[fields.get("slug", name[:-3])] = fields
    return posts


def run_dump():
    url = "file:///" + EDITORIAL.replace("\\", "/")
    code = NODE_DUMP.replace("__URL__", url).replace("__DAYS__", json.dumps(all_days()))
    proc = subprocess.run(["node", "--no-warnings", "--input-type=module"], input=code,
                          capture_output=True, text=True, encoding="utf-8", cwd=SITE)
    if proc.returncode != 0:
        print(proc.stderr)
        sys.exit("node での読み込みに失敗しました")
    return json.loads(proc.stdout)


def group_real(dump):
    print("--- 1. 本物の設定を366日でまわす ---")
    days = all_days()
    check("日数は366", len(days) == 366, str(len(days)))
    for cat in ("gift", "seasons"):
        ed = dump["editorial"][cat]
        problems = []
        for day in days:
            p = order_problem(dump["entries"][cat][day], ed["spokes"], ed["seasonal"], day)
            if p:
                problems.append("%s %s" % (day, p))
        check("%s: 全日で5本・重複なし・時期の過ぎた記事が前に来ない" % cat, not problems, " / ".join(problems[:5]))
    print("--- （検査が落ちることの確認）---")
    sample = {"spokes": ["e1"], "seasonal": [{"slug": "past", "from": "01-01", "to": "01-02"},
                                             {"slug": "now", "from": "11-01", "to": "11-30"},
                                             {"slug": "x", "from": "02-01", "to": "02-02"},
                                             {"slug": "y", "from": "03-01", "to": "03-02"},
                                             {"slug": "z", "from": "04-01", "to": "04-02"}]}
    s, e = sample["spokes"], sample["seasonal"]
    check("過ぎた記事が先の並びを検知する", order_problem(["past", "now", "e1", "x", "y"], s, e, "11-15") is not None)
    check("期間中の記事を押し出した並びを検知する", order_problem(["e1", "past", "x", "y", "z"], s, e, "11-15") is not None)
    check("4本を検知する", order_problem(["now", "e1", "x", "y"], s, e, "11-15") is not None)
    check("重複を検知する", order_problem(["now", "e1", "x", "y", "y"], s, e, "11-15") is not None)
    check("正しい並びは通す", order_problem(["now", "e1", "x", "y", "z"], s, e, "11-15") is None)


def group_slugs(dump):
    print("--- 2. slug の実在とカテゴリ ---")
    posts = load_posts()
    for cat, ed in dump["editorial"].items():
        slugs = list(ed.get("spokes", [])) + [s["slug"] for s in ed.get("seasonal", [])]
        bad = [s for s in slugs if posts.get(s, {}).get("status") != "published" or posts[s].get("category") != cat]
        check("%s: 全 slug が公開済み・同じカテゴリ（%d本）" % (cat, len(slugs)), not bad, ", ".join(bad))
        if not ed.get("seasonal"):
            same = all(dump["entries"][cat][d] == list(ed["spokes"]) for d in all_days())
            check("%s: seasonal なしは全日で spokes のまま" % cat, same)
    want_gift = {"zansho-mimai-koucha-gift", "keirounohi-koucha-gift", "kisei-temiyage-koucha-gift"}
    want_seasons = {"bousai-koucha-teabag-erabikata", "otsukimi-wakoucha-tsukimi-dango",
                    "halloween-ouchi-ochakai-noncaffeine", "natsumatsuri-hanabi-suitou-icetea"}
    check("gift: 時期のある3本が spokes に残っていない", not want_gift & set(dump["editorial"]["gift"]["spokes"]))
    check("seasons: 時期のある4本が spokes に残っていない", not want_seasons & set(dump["editorial"]["seasons"]["spokes"]))


def group_function(dump):
    print("--- 3. 選び方の関数と日付 ---")
    fx = dump["fixture"]
    check("年またぎの期間中（01-05）→ wrap が先頭、続いて spokes、残りは from が近い順",
          fx["01-05"] == ["wrap", "e1", "e2", "spring", "summer"], repr(fx["01-05"]))
    check("期間中は to が近い順（11-15 → short, nov）",
          fx["11-15"] == ["short", "nov", "e1", "e2", "wrap"], repr(fx["11-15"]))
    check("年をまたぐ to の近さ（12-15 → nov 12-20 が wrap 01-15 より先）",
          fx["12-15"] == ["nov", "wrap", "e1", "e2", "spring"], repr(fx["12-15"]))
    check("閏日も動く（02-29 → spokes のあと from が近い順）",
          fx["02-29"] == ["e1", "e2", "spring", "summer", "nov"], repr(fx["02-29"]))
    check("年末（12-31）も期間中に数える", fx["12-31"][0] == "wrap", repr(fx["12-31"]))
    check("to の当日は期間中（01-15）", fx["01-15"][0] == "wrap", repr(fx["01-15"]))
    check("to の翌日は期間外で、いちばん後ろへ（01-16）", fx["01-16"][-1] != "wrap" and "wrap" not in fx["01-16"][:2], repr(fx["01-16"]))
    t = dump["today"]
    check("日本時間 10-31 23:59 は 10-31", t["before_midnight"] == "10-31", repr(t))
    check("日本時間 11-01 00:00（UTC では 10-31）は 11-01", t["after_midnight"] == "11-01", repr(t))
    check("CATEGORY_ENTRY_TODAY で固定できる", t["fixed"] == "12-24", repr(t))
    check("GitHub Actions では固定の指定を無視する", t["ignored_on_actions"] == "11-01", repr(t))
    check("固定の指定の形が違えば止まる", t["bad_format"] == "thrown", repr(t))


def group_errors(dump):
    print("--- 4. ビルド時のチェック ---")
    err = dump["errors"]
    check("正しい設定はエラーなし", err["ok"] == [], repr(err["ok"]))
    check("spokes だけ5本の設定はエラーなし", err["ok_spokes_only"] == [], repr(err["ok_spokes_only"]))
    for key in ("bad_from_shape", "bad_to_month", "bad_to_day", "bad_missing_to", "unpublished", "other_category",
                "spokes_unpublished", "too_few", "duplicate", "spokes_only_six", "spokes_only_four"):
        check("%s はエラーを返す" % key, len(err[key]) > 0, repr(err[key]))


def run_build(today=None):
    env = dict(os.environ)
    env.pop("CATEGORY_ENTRY_TODAY", None)
    if today:
        env["CATEGORY_ENTRY_TODAY"] = today
    proc = subprocess.run(["node", os.path.join(SITE, "node_modules", "astro", "astro.js"), "build"], cwd=SITE, env=env,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=BUILD_TIMEOUT)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def read_entry(cat):
    with io.open(os.path.join(DIST, "category", cat, "index.html"), encoding="utf-8") as f:
        html = f.read()
    block = re.search(r'<ol class="hub-spokes"[^>]*>(.*?)</ol>', html, re.S)
    return re.findall(r'href="/posts/([^/"]+)/"', block.group(1)) if block else []


def read_head(cat):
    with io.open(os.path.join(DIST, "category", cat, "index.html"), encoding="utf-8") as f:
        html = f.read()
    title = re.search(r"<title>(.*?)</title>", html, re.S).group(1)
    desc = re.search(r'<meta name="description" content="([^"]*)"', html).group(1)
    return title, desc


def group_build():
    print("--- 5. 日付を固定したビルド ---")
    for today in FIXED_DATES:
        code, tail = run_build(today)
        check("%s のビルドが通る" % today, code == 0, tail[-800:])
        if code != 0:
            continue
        for cat in ("gift", "seasons"):
            entry = read_entry(cat)
            check("  %s %s は5本" % (today, cat), len(entry) == 5, repr(entry))
            print("    %s" % " / ".join(entry))
    print("--- 6. 崩した設定でビルドが止まる ---")
    with io.open(EDITORIAL, "rb") as f:
        original = f.read()
    text = original.decode("utf-8")
    cases = [
        ("期間の形の崩れ（07-15 → 7-15）", "from: '07-15'", "from: '7-15'"),
        ("公開されていない slug", "slug: 'zansho-mimai-koucha-gift'", "slug: 'no-such-article'"),
        ("ほかのカテゴリの slug", "slug: 'zansho-mimai-koucha-gift'", "slug: 'assam-tea-nyumon'"),
        ("seasonal のないカテゴリの spokes が4本", "'assam-tea-nyumon', ", ""),
    ]
    try:
        for label, old, new in cases:
            if text.count(old) != 1:
                check("%s（差し替え箇所が1つ）" % label, False, str(text.count(old)))
                continue
            with io.open(EDITORIAL, "wb") as f:
                f.write(text.replace(old, new).encode("utf-8"))
            code, out = run_build()
            line = next((re.sub(r"\x1b\[[0-9;]*m", "", l).strip() for l in out.splitlines() if "hub selection failed" in l), "")
            check("%s → 止まる" % label, code != 0 and bool(line), "code=%s %s" % (code, out[-500:]))
            print("    code=%s %s" % (code, line))
    finally:
        with io.open(EDITORIAL, "wb") as f:
            f.write(original)
    with io.open(EDITORIAL, "rb") as f:
        check("editorial.ts が元に戻っている", f.read() == original)
    print("--- 7. 日付を固定しない今日のビルド ---")
    code, tail = run_build()
    check("今日のビルドが通る", code == 0, tail[-800:])
    if code == 0:
        print("    gift: %s" % " / ".join(read_entry("gift")))
        print("    seasons: %s" % " / ".join(read_entry("seasons")))
        print("    gift title: %s" % read_head("gift")[0])
        print("    gift description: %s" % read_head("gift")[1])


def html_files(root):
    for base, _dirs, names in os.walk(root):
        for name in names:
            if name.endswith(".html"):
                path = os.path.join(base, name)
                yield os.path.relpath(path, root).replace("\\", "/"), path


def save_dist(dest):
    code, tail = run_build()
    if code != 0:
        sys.exit("ビルドに失敗しました\n" + tail[-800:])
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    count = 0
    for rel, path in html_files(DIST):
        target = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(path, target)
        count += 1
    print("保存 %d ファイル: %s" % (count, dest))


def diff_dist(dest):
    before = dict(html_files(dest))
    after = dict(html_files(DIST))
    changed = []
    for rel in sorted(set(before) | set(after)):
        if rel not in before or rel not in after:
            changed.append(rel + "（片方のみ）")
            continue
        with io.open(before[rel], "rb") as a, io.open(after[rel], "rb") as b:
            if a.read() != b.read():
                changed.append(rel)
    print("比較 %d ファイル・変更 %d ファイル" % (len(after), len(changed)))
    for rel in changed:
        print("  " + rel)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    if args[:1] == ["--save-dist"] and len(args) == 2:
        return save_dist(args[1])
    if args[:1] == ["--diff-dist"] and len(args) == 2:
        return diff_dist(args[1])
    if args not in ([], ["--build"]):
        sys.exit(__doc__)
    dump = run_dump()
    group_real(dump)
    group_slugs(dump)
    group_function(dump)
    group_errors(dump)
    if args == ["--build"]:
        group_build()
    print("")
    if FAILED:
        print("失敗 %d 件: %s" % (len(FAILED), " / ".join(FAILED)))
        sys.exit(1)
    print("すべて OK")


if __name__ == "__main__":
    main()
