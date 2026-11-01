# -*- coding: utf-8 -*-
r"""W43監査の採用指示で足した公開前チェックの再発防止テスト（GD-0048・GD-0050・GD-0053）。

  A check-fact-source.py の型9（食品の保存期間・衛生は同じブロックに出典URLを要する）
  B publish-article.py の公開時期の確認（季節の山まで28日未満はNG・28〜41日は警告・通年は対象外）
  C check-pin-image-style.py の予告型の先頭（ピン370以降・画像の先頭文言と投稿文の1行目）
  A2 check-fact-source.py の型10（手入れ手順・傷みやすさ。W43検証監査の指摘）／
  A3 check-fact-source.py の型11（保存・衛生・安全・手入れの助言。W44週次・2026-10月次の指摘）と
     型5の重曹・漂白剤の特則（case_a の中で実行する）／
  D check-pin-image-style.py の断定語の先頭（P-1・ピン383以降）

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
        ("抽出時間（冷蔵庫で8時間置く） → なし（D-0286）", "水出しは、茶葉と水を入れて冷蔵庫で8時間置くだけです。", []),
        ("保存期間（冷蔵で2〜3日以内に飲みきる） → 型9（D-0286）", "冷蔵で2〜3日以内に飲みきる。", ["型9"]),
        ("抽出の語があっても保存の判断語がある（抽出後…2〜3日以内） → 型9", "抽出後は冷蔵庫で2〜3日以内に飲み切ります。", ["型9"]),
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
    # 型10（W43検証監査の指摘）: 手入れ手順・傷みやすさは出典URLを要し、適用条件の語では免除しない
    cases10 = [
        ("出典なし・取扱説明書の条件語あり（目止め・とぎ汁） → 型10",
         "使い始めに目止め（米のとぎ汁で煮る方法）をします。メーカーの取扱説明書に従ってください。", ["型10"]),
        ("出典なし・パッケージの表示の条件語あり（常温で長く・傷みやすく） → 型10",
         "パッケージの表示どおりの時間置きます。常温で長く置くと傷みやすくなるため早めに飲み切ります。", ["型10"]),
        ("出典URLあり → なし",
         "使い始めに目止めをします（[無印良品](https://www.muji.com/example)）。米のとぎ汁で煮ます。", []),
        ("アフィリエイトURLだけ → 型10", "目止めがおすすめ。[商品](https://hb.afl.rakuten.co.jp/ichiba/x/y)", ["型10"]),
        ("紅茶のレシピの「煮る・煮出す」 → なし（誤検知を避ける）", "鍋で茶葉を煮出し、牛乳を加えて煮る。", []),
        ("検知語なしの保存の記述 → 型10なし", "湿気を避けて保管します。", []),
    ]
    for description, body, expected in cases10:
        path = _article(root, "case-a10", body)
        got = [t for t in _types(fs, path) if t == "型10"]
        results.append((description, got == expected, "期待=%s 実際=%s" % (expected, got)))
    # 新規公開ではNG・--revise では警告にとどまる（check_xy は new_type を立てる）
    path = _article(root, "case-a-new", "冷蔵で2日以内に飲み切ります。")
    hits = [v for v in fs.check_xy(path, "dummy") if v["hit"].startswith("型9")]
    results.append(("型9は new_type（--revise・週次は警告）", bool(hits) and all(v["new_type"] for v in hits), str(hits)))
    # 型11（W44週次・2026-10月次の指摘）: 保存・衛生・安全・手入れの助言は同じブロックに出典URLを要し、
    # 適用条件の語では免除しない。重曹・漂白剤の手入れ（型5）も適用条件の語で免除しない
    src = "（出典: [消費者庁](https://www.caa.go.jp/example)）"
    cases11 = [
        ("乳児への注意・出典なし → 型11", "はちみつを含むため、1歳未満の乳児には与えないでください。", ["型11"]),
        ("乳児への注意・出典URLあり → なし", "はちみつを含むため、1歳未満の乳児には与えないでください" + src + "。", []),
        ("年齢の書き方（1歳未満）＋使わない・出典なし → 型11",
         "はちみつは1歳未満のお子さんには使わないでください。", ["型11"]),
        ("年齢の書き方（1歳未満）＋与えない・出典なし → 型11", "はちみつは1歳未満の子には与えてはいけません。", ["型11"]),
        ("年齢の書き方（2歳未満）＋避ける・出典なし → 型11", "2歳未満の子どもには避けてください。", ["型11"]),
        ("年齢の書き方（1歳未満）・出典URLあり → なし",
         "はちみつは1歳未満のお子さんには使わないでください" + src + "。", []),
        ("年齢の書き方だけで助言語なし → なし", "1歳未満のお子さんの飲み物については医師に相談すると安心です。", []),
        ("妊娠中の方は医師に相談（助言語なし） → なし", "妊娠中の方は、気になる場合は医師に相談すると安心です。", []),
        ("傷みの見分け（いつもと違えば飲まない）・出典なし → 型11", "酸っぱいにおいや味など、いつもと違うと感じたら飲まないでください。", ["型11"]),
        ("傷みの見分け・出典URLあり → なし", "酸っぱいにおいなど、いつもと違うと感じたら飲まないでください" + src + "。", []),
        ("一口含んで確かめる手順 → 型11", "- 味に違和感がある — 一口含んで確かめ、残りは処分する", ["型11"]),
        ("早めに飲み切る前提 → 型11", "作り置きは早めに飲み切る前提で考えます。", ["型11"]),
        ("飲み切れる量に合わせた容量選び → なし", "容量は、早めに飲み切れる量に合わせて選びます。", []),
        ("湿気や匂い移りを防ぎきれず → 型11", "袋のまま留めるだけでは、湿気や匂い移りを防ぎきれません。", ["型11"]),
        ("商品の仕様（湿気を防ぎ密封） → なし", "内蓋が付いているので、湿気を防ぎしっかり密封します。", []),
        ("カビが生えるので避ける → 型11", "乾かさずに置くと、カビが生えることがあるので避けます。", ["型11"]),
        ("冷たいグラスにいきなり熱湯 → 型11", "冷たいグラスにいきなり熱湯を注がないようにしましょう。", ["型11"]),
        ("淹れ方の「熱湯を注ぐ」 → なし", "ポットに熱湯を注ぎ、3分蒸らします。", []),
        ("熱湯を注いでも耐えやすい仕様 → なし", "強化ガラス製で、熱湯を注いでも急激な温度変化に耐えやすい仕様です。", []),
        ("適用条件の語があっても免除しない（製品の表示に従う） → 型11",
         "冷蔵庫の外では、製品の表示に従いつつ早めに飲み切る前提で考えます。", ["型11"]),
        ("アフィリエイトURLだけ → 型11", "早めに飲み切る前提で。[商品](https://hb.afl.rakuten.co.jp/ichiba/x/y)", ["型11"]),
        # 2026-10月次の指摘（aki-hotel-afternoontea-jitaku-styling）: 直す前の文は検出され、直した後の文は通る
        ("熱い器にコースター・ポットマット（直す前） → 型11",
         "熱いポットやカップを直接置けるかどうかは分からないため、熱い器を載せるときは、コースターやポットマットを間に敷いてください。",
         ["型11"]),
        ("熱い器の耐熱性は確かめられていない（直した後の事実の記述） → なし",
         "熱いポットやカップを直接置けるかどうかは、この記事では確かめられていません。", []),
        ("子ども・ペットの手が届く場所では使わない（直す前） → 型11",
         "- テーブルの端に置かない。小さな子どもやペットの手が届く場所では使わない", ["型11"]),
        ("熱い紅茶のカップは載せない（直す前） → 型11",
         "- 載せるのは軽い菓子だけにし、熱い紅茶の入ったカップやポットは載せない", ["型11"]),
        ("ぐらつく場合は使いません（直す前） → 型11", "ぐらつく場合は使いません。", ["型11"]),
        ("底が平らな小さな台に皿を載せる（直した後） → なし",
         "底が平らな小さな木の台や器の上に皿を載せても、高さの差が作れます。", []),
        ("熱い紅茶を淹れる手順（助言ではない） → なし", "熱い紅茶を注いで、3分蒸らします。", []),
        ("子ども向けの茶葉の紹介（助言語なし） → なし", "子どもにも飲みやすい味と紹介されています。", []),
    ]
    for description, body, expected in cases11:
        path = _article(root, "case-a11", body)
        got = [t for t in _types(fs, path) if t == "型11"]
        results.append((description, got == expected, "期待=%s 実際=%s" % (expected, got)))
    path = _article(root, "case-a11-list",
                    "- 乳児には与えない\n- 詳しくは[公的機関](https://www.mhlw.go.jp/example)を確認")
    got = [t for t in _types(fs, path) if t == "型11"]
    results.append(("箇条書きは1項目ずつ（URLが別項目なら型11）", got == ["型11"], "実際=%s" % got))
    path = _article(root, "case-a11-new", "早めに飲み切る前提で考えます。")
    hits = [v for v in fs.check_xy(path, "dummy") if v["hit"].startswith("型11")]
    results.append(("型11は new_type（--revise・週次は警告）", bool(hits) and all(v["new_type"] for v in hits), str(hits)))
    # 公開前チェックと同じ入口（run_single）: 出典なしのダミーは終了コード1（NG）・出典URL付きは0（--revise は警告で0）
    import contextlib, io
    old_drafts = fs.DRAFTS_DIR
    fs.DRAFTS_DIR = root
    try:
        for description, body, revise, expected_code, expected_text in (
            ("run_single: 出典なしの保存助言ダミー → 終了コード1・型11を表示",
             "はちみつを含むため、1歳未満の乳児には与えないでください。", False, 1, "型11"),
            ("run_single: 出典URLを付けたダミー → 終了コード0・FACT_SOURCE_OK",
             "はちみつを含むため、1歳未満の乳児には与えないでください" + src + "。", False, 0, "FACT_SOURCE_OK"),
            ("run_single --revise: 出典なしのダミー → 終了コード0・【警告】型11",
             "はちみつを含むため、1歳未満の乳児には与えないでください。", True, 0, "【警告】"),
        ):
            _article(root, "case-cli", body)
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = fs.run_single("case-cli", revise=revise)
            text = buffer.getvalue()
            results.append((description, code == expected_code and expected_text in text,
                            "終了コード=%s 出力=%s" % (code, text[:200])))
    finally:
        fs.DRAFTS_DIR = old_drafts
    # 型5の特則: 重曹・漂白剤の手入れは「表示に従ってください」の適用条件で免除しない。手洗い等は従来どおり免除
    cases5 = [
        ("重曹・漂白剤のつけ置き＋表示に従う → 型5", "重曹や漂白剤でつけ置きする場合は、製品の表示に従ってください。", ["型5"]),
        ("重曹・漂白剤のつけ置き＋出典URL → なし",
         "重曹や漂白剤でつけ置きする場合は、製品の表示に従ってください（[メーカー](https://example.com/care)）。", []),
        ("手洗いのおすすめ＋表示に従う → なし（従来どおり免除）", "手洗いがおすすめです。製品の表示に従ってください。", []),
    ]
    for description, body, expected in cases5:
        path = _article(root, "case-a5", body)
        got = [t for t in _types(fs, path) if t == "型5"]
        results.append((description, got == expected, "期待=%s 実際=%s" % (expected, got)))


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


def case_d(results):
    """P-1（実験 EX-0001）: ピン383以降の先頭文言の断定語はNG。383未満は対象外。"""
    ps = _load("check-pin-image-style.py")
    first = ps.HEAD_ASSERTION_FROM_PIN
    words = [
        ("解決", "なくなる紅茶で解決"), ("必ず", "必ず合うカップの選び方"), ("絶対", "絶対に外さない一杯"),
        ("間違いない", "この一杯なら間違いない"), ("失敗しない", "失敗しないギフトの選び方"),
        ("これだけで", "これだけで選べる基準"),
    ]
    for word, head in words:
        got = ps.head_assertion_words(ps.head_text_of(_pin_text(head)))
        results.append(("先頭文言の断定語「%s」 → 検知" % word, word in got, "実際=%s" % got))
    got = ps.head_assertion_words(ps.head_text_of(_pin_text("網目の細かさで選ぶ")))
    results.append(("選び方の文言 → 合格", got == [], "実際=%s" % got))
    # 先頭の「」だけを見る（2つ目の「」に断定語があっても合格）
    text = _pin_text("網目の細かさで選ぶ").replace("「二つ目の文言」", "「必ず合う」")
    got = ps.head_assertion_words(ps.head_text_of(text))
    results.append(("2つ目の「」の断定語は対象外 → 合格", got == [], "実際=%s" % got))
    # ファイル単位: 開始番号未満は対象外・開始番号以降は断定語でNG／OK
    root = tempfile.mkdtemp(prefix="p1-pin-")
    try:
        import contextlib, io
        old = ps.PINS_DIR
        ps.PINS_DIR = root
        cases = [
            (first - 1, "なくなる紅茶で解決", 0, "開始番号未満の断定語"),
            (first, "なくなる紅茶で解決", 1, "開始番号の断定語"),
            (first + 5, "必ず合う選び方", 1, "開始番号より後の断定語"),
            (first, "網目の細かさで選ぶ", 0, "開始番号の断定語なし"),
        ]
        for num, head, expected, label in cases:
            name = "2031-01-01-pin-%d-dummy-slug-01.md" % num
            _write(os.path.join(root, name), _pin_text(head))
            with contextlib.redirect_stdout(io.StringIO()):
                ng = ps.check_head_assertion("dummy-slug")
            results.append(("ピン%d %s → NG %d件" % (num, label, expected), len(ng) == expected, str(ng)))
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
        case_d(results)
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
