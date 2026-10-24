# -*- coding: utf-8 -*-
r"""W43監査の採用指示で足した公開前チェックの再発防止テスト（GD-0048・GD-0050・GD-0053）。

  A check-fact-source.py の型9（食品の保存期間・衛生は同じブロックに出典URLを要する）
  B publish-article.py の公開時期の確認（季節の山まで28日未満はNG・28〜41日は警告・通年は対象外）
  C check-pin-image-style.py の予告型の先頭（ピン370以降・画像の先頭文言と投稿文の1行目）

本物の記事・ピン・台帳には触れない。A・C は一時ディレクトリにダミーを作り、B は判定関数へ
ダミーの台帳と日付を渡す。一時ディレクトリは終了時に必ず消す。

使い方:
  python site/scripts/test-w43-pre-publish-checks.py
"""

import importlib.util
import os
import shutil
import sys
import tempfile
from datetime import date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _load(file_name):
    spec = importlib.util.spec_from_file_location(
        file_name[:-3].replace("-", "_"), os.path.join(SCRIPT_DIR, file_name))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _article(root, name, body, category="how-to"):
    path = os.path.join(root, name + ".md")
    _write(path, "---\ntitle: ダミー\nslug: %s\ncategory: %s\nstatus: draft\n---\n\n%s\n" % (name, category, body))
    return path


def _types(module, path, slug="dummy"):
    return sorted({v["hit"].split(":")[0] for v in module.check_xy(path, slug) if v.get("new_type")})


def case_a(results, root):
    fs = _load("check-fact-source.py")
    cases = [
        ("出典URLなし・適用条件のみ → 型9", "## Q1\n\n冷蔵庫で保存し、製品の表示に従って2〜3日以内に飲み切ります。", ["型9"]),
        ("出典URLあり → 型9なし",
         "冷蔵庫で保存し、2〜3日以内に飲み切ります（[厚生労働省](https://www.mhlw.go.jp/example)）。", []),
        ("アフィリエイトURLだけ → 型9", "冷蔵で保存して3日以内。[商品](https://hb.afl.rakuten.co.jp/ichiba/x/y)", ["型9"]),
        ("保存の語だけ（期間なし） → なし", "冷蔵庫で保存するときは、清潔な容器を使います。", []),
        ("期間だけ（保存の語なし） → なし", "蒸らし時間は3分、冷やすのは1時間が目安です。", []),
        ("日付だけ（N月N日）＋保存 → なし", "10月25日までは常温で保存できます。", []),
        ("時間＋常温 → 型9", "抽出後は常温に4時間以上置かないでください。", ["型9"]),
        ("保存記述なしの記事 → なし", "ダージリンは3分蒸らします。香りが立ちます。", []),
    ]
    for description, body, expected in cases:
        path = _article(root, "case-a", body)
        got = [t for t in _types(fs, path) if t == "型9"]
        results.append((description, got == expected, "期待=%s 実際=%s" % (expected, got)))
    # 箇条書きは1項目ずつ: 出典URLが別の項目にあっても、URLのない項目は型9
    path = _article(root, "case-a-list",
                    "- 冷蔵で2日以内に飲み切る\n- 詳しくは[公的機関](https://www.mhlw.go.jp/example)を確認")
    got = [t for t in _types(fs, path) if t == "型9"]
    results.append(("箇条書きは1項目ずつ（URLが別項目なら型9）", got == ["型9"], "実際=%s" % got))
    # 新規公開ではNG・--revise では警告にとどまる（check_xy は new_type を立てる）
    path = _article(root, "case-a-new", "冷蔵で2日以内に飲み切ります。")
    hits = [v for v in fs.check_xy(path, "dummy") if v["hit"].startswith("型9")]
    results.append(("型9は new_type（--revise・週次は警告）", bool(hits) and all(v["new_type"] for v in hits), str(hits)))


def case_b(results):
    pa = _load("publish-article.py")
    today = date(2031, 10, 25)
    peak = date(2031, 12, 25)
    cases = []
    for days, expected in ((20, "ng"), (27, "ng"), (28, "warn"), (35, "warn"), (41, "warn"), (42, "ok"), (50, "ok")):
        day = peak.toordinal() - days
        cases.append((days, expected, date.fromordinal(day)))
    for days, expected, today_d in cases:
        verdict, got_days, _ = pa.judge_publish_timing([(12, 25)], today_d)
        results.append(("山まで%d日 → %s" % (days, expected), verdict == expected and got_days == days,
                        "判定=%s 日数=%s" % (verdict, got_days)))
    verdict, _, _ = pa.judge_publish_timing([], today)
    results.append(("山なし（通年） → skip", verdict == "skip", verdict))
    # 山が複数: 今日以降で最も近い山で判定する
    verdict, days, _ = pa.judge_publish_timing([(11, 23), (12, 25)], date(2031, 11, 1))
    results.append(("山が複数 → 最も近い山（11-23まで22日 → ng）", verdict == "ng" and days == 22, "%s %s" % (verdict, days)))
    # 山を過ぎた直後（当日〜27日後）はNG・28日以上過ぎれば来季の山で判定する
    for since, expected in ((0, "ng"), (10, "ng"), (27, "ng"), (28, "ok"), (60, "ok")):
        day = date.fromordinal(date(2031, 9, 15).toordinal() + since)
        verdict, days, _ = pa.judge_publish_timing([(9, 15)], day)
        results.append(("山を%d日過ぎている → %s" % (since, expected),
                        verdict == expected and (days == -since if expected == "ng" else days > 250),
                        "%s %s" % (verdict, days)))
    ok, lines = pa.check_publish_timing("s-peak", "gift", "2031-12-30", {"s-peak": {"peaks": [(12, 25)], "basis": ""}})
    results.append(("山を過ぎた直後 → NGと「過ぎています」の表示",
                    (not ok) and any("過ぎています" in l for l in lines) and any(pa.TIMING_NG_ACTION in l for l in lines),
                    "\n".join(lines)))
    # check_publish_timing: 台帳の行・category の扱いと表示文言
    calendar = {"s-peak": {"peaks": [(12, 25)], "basis": ""}, "s-generic": {"peaks": [], "basis": ""}}
    ok, lines = pa.check_publish_timing("s-peak", "seasons", "2031-12-05", calendar)
    results.append(("seasons 20日前 → NGと保留の文言", (not ok) and any(pa.TIMING_NG_ACTION in l for l in lines), "\n".join(lines)))
    ok, lines = pa.check_publish_timing("s-peak", "gift", "2031-11-20", calendar)
    results.append(("gift 35日前 → 通す・警告あり", ok and any("【警告】" in l for l in lines), "\n".join(lines)))
    ok, lines = pa.check_publish_timing("s-peak", "gift", "2031-10-25", calendar)
    results.append(("gift 61日前 → 通す・警告なし", ok and not any("【警告】" in l for l in lines), "\n".join(lines)))
    ok, lines = pa.check_publish_timing("s-generic", "gift", "2031-12-24", calendar)
    results.append(("通年の行 → 対象外で通す", ok, "\n".join(lines)))
    ok, lines = pa.check_publish_timing("s-peak", "how-to", "2031-12-24", calendar)
    results.append(("seasons・gift 以外 → 対象外で通す", ok, "\n".join(lines)))
    ok, lines = pa.check_publish_timing("s-none", "gift", "2031-12-24", calendar)
    results.append(("台帳に行なし → 対象外で通す（--require-row が止める）", ok, "\n".join(lines)))


def case_b_dry_run(results):
    """publish-article.py <slug> --dry-run --today の経路で、公開時期の確認が効くことを確かめる（実際の下書きは書き換えない）。"""
    import contextlib, io
    pa = _load("publish-article.py")
    pa.mark_daily_session = lambda: None  # record-lesson のセッションマーカーを作らない
    slug = "kinrou-kansha-no-hi-koucha-petit-gift"  # 台帳の山 11-23 の gift 記事
    if not os.path.isfile(os.path.join(pa.DRAFTS_DIR, slug + ".md")):
        results.append(("B 経路: 下書きがあるため実行できる", False, "output/articles/%s.md が無い" % slug))
        return
    original_argv = sys.argv
    for today, expect_ng in (("2026-11-05", True), ("2026-09-20", False)):
        buffer = io.StringIO()
        try:
            sys.argv = [original_argv[0], slug, "--dry-run", "--today", today]
            with contextlib.redirect_stdout(buffer):
                code = pa._run({"slug": None, "dry_run": False, "failed_check": None})
        finally:
            sys.argv = original_argv
        text = buffer.getvalue()
        if expect_ng:
            ok = code == 1 and "NG  公開時期の確認" in text and pa.TIMING_NG_ACTION in text and "check-advance-pin-today.py" not in text
        else:
            ok = "OK  公開時期の確認（山 11-23 まで64日）" in text
        results.append(("--dry-run --today %s（山 11-23）→ %s" % (today, "NGで中断" if expect_ng else "公開時期は合格"),
                        ok, text.strip()[:500]))


def _pin_text(head, title="ダミーのタイトル", desc="ダミーの説明文です。二文目です。"):
    return (
        "# ピンN: ダミー\n\n- 誘導先URL: https://example.invalid/\n\n"
        "## 画像指示書\n- 型: Q&A形式\n- テキストオーバーレイ: 「%s」「二つ目の文言」（2件）\n\n"
        "## 投稿文\nタイトル: %s\n説明文: %s #紅茶 #ギフト\n- X用説明文: x #紅茶\n" % (head, title, desc))


def case_c(results):
    ps = _load("check-pin-image-style.py")
    cases = [
        ("画像の先頭が「〜まとめました」 → 予告型", _pin_text("選び方をまとめました"), True),
        ("画像の先頭が「〜ご紹介」 → 予告型", _pin_text("選び方のご紹介"), True),
        ("画像の先頭が「〜チェック」 → 予告型", _pin_text("贈る前の3チェック"), True),
        ("画像の先頭が「〜の疑問」 → 予告型", _pin_text("ペアカップの疑問"), True),
        ("投稿文の1文目が「〜解説します。」 → 予告型", _pin_text("答えの文言", desc="選び方を解説します。条件は3つ。"), True),
        ("投稿文の1文目が「〜調べました。」 → 予告型", _pin_text("答えの文言", desc="口コミを調べました。結論は後半。"), True),
        ("投稿文の1文目が「疑問をまとめました。」 → 予告型", _pin_text("答えの文言", desc="選ぶ前の疑問をまとめました。"), True),
        ("投稿文のタイトルが「〜まとめ」 → 予告型", _pin_text("答えの文言", title="冬のギフトまとめ"), True),
        ("結論型（「紅茶は2倍の濃さで淹れる」） → 合格", _pin_text("2倍の濃さで淹れる", desc="氷をたっぷり使うと香りが残ります。"), False),
        ("結論型の1文目に途中の「まとめ」 → 合格", _pin_text("答えの文言", desc="まとめ買いより少量を選ぶのが安心です。"), False),
        ("疑問形「？」は4の判定（このチェックは対象外） → 合格", _pin_text("色違いでもいい？"), False),
    ]
    for description, text, expected in cases:
        got = bool(ps.forecast_hits(text))
        results.append((description, got == expected, "期待=%s 実際=%s %s" % (expected, got, ps.forecast_hits(text))))
    # ファイル単位: ピン369は対象外・ピン370以降は対象
    root = tempfile.mkdtemp(prefix="w43-pin-")
    try:
        old = ps.PINS_DIR
        ps.PINS_DIR = root
        for num, expected in ((369, 0), (370, 1)):
            name = "2031-01-01-pin-%d-dummy-slug-01.md" % num
            _write(os.path.join(root, name), _pin_text("選び方をまとめました"))
            import contextlib, io
            with contextlib.redirect_stdout(io.StringIO()):
                ng = ps.check_head_forecast("dummy-slug")
            results.append(("ピン%d の予告型 → NG %d件" % (num, expected), len(ng) == expected, str(ng)))
            os.remove(os.path.join(root, name))
        ps.PINS_DIR = old
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    root = tempfile.mkdtemp(prefix="w43-art-")
    results = []
    try:
        case_a(results, root)
        case_b(results)
        case_b_dry_run(results)
        case_c(results)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    failed = 0
    for description, ok, detail in results:
        print("%s %s" % ("OK  " if ok else "NG  ", description))
        if not ok:
            failed += 1
            print("      " + detail.replace("\n", "\n      "))
    print()
    print("結果: %d件中 %d件合格" % (len(results), len(results) - failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
