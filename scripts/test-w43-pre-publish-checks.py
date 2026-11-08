# -*- coding: utf-8 -*-
r"""W43監査の採用指示で足した公開前チェックの再発防止テスト（GD-0048・GD-0050・GD-0053）。

  A check-fact-source.py の型9（食品の保存期間・衛生は同じブロックに出典URLを要する）
  B publish-article.py の公開時期の確認（季節の山まで28日未満はNG・28〜41日は警告・通年は対象外）
  C check-pin-image-style.py の予告型の先頭（ピン370以降・画像の先頭文言と投稿文の1行目）
  A2 check-fact-source.py の型10（手入れ手順・傷みやすさ。W43検証監査の指摘）／
  A3 check-fact-source.py の型11（保存・衛生・安全・手入れの助言。W44週次・2026-10月次の指摘）と
     型5の重曹・漂白剤の特則（case_a の中で実行する）／
  A4 check-fact-source.py の型12（体験を示す名詞修飾）・型13（将来の予告）（2026-11-07の指摘。
     case_a12_13 を case_a の中で実行する）／
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
    case_a12_13(results, root, fs)


def case_a12_13(results, root, fs):
    """型12（体験を示す名詞修飾）と型13（将来の予告）。2026-11-07の指摘の修正前の文は検出し、
    読者への呼びかけ・体験が無いと断る注記・レビュー投稿者の話・読者の行動の提案は検出しない。"""
    src = "（出典: [消費者庁](https://www.caa.go.jp/example)）"
    cases = [
        # 修正前の版の文（検出すべき）
        ("型12: 飲み比べた話（kokyu-koucha-brand-guide 修正前）",
         "なお、フォションを他ブランドと横並びで飲み比べた話は別記事に譲り、ここでは「名門の定番を一缶だけ持つなら」という視点で取り上げています。",
         ["型12"]),
        ("型12: 淹れた結果", "淹れた結果、渋みが強く出ました。", ["型12"]),
        ("型12: 試した感想", "試した感想をまとめます。", ["型12"]),
        ("型12: 使ってみた印象", "使ってみた印象は軽やかでした。", ["型12"]),
        ("型12: 飲んだ感想", "飲んだ感想を書きます。", ["型12"]),
        ("型12: 出典URLを付けても免除しない", "飲み比べた話は別記事に譲ります" + src + "。", ["型12"]),
        ("型13: 別記事で改めて扱う予定（koime・hot-brew 修正前）",
         "濃いめだからといって特別に早く傷むわけではありませんが、作り置きの保存期間については別記事で改めて扱う予定です。",
         ["型13"]),
        ("型13: 見つかり次第あらためてご紹介する予定（royal-albert 修正前）",
         "今回は見送りました。見つかり次第あらためてご紹介する予定です。", ["型13"]),
        ("型13: 近日公開", "ティーカップ編は近日公開です。", ["型13"]),
        ("型13: 今後の記事で", "価格の比較は今後の記事で取り上げます。", ["型13"]),
        ("型13: 出典URLを付けても免除しない", "別記事で改めて扱う予定です" + src + "。", ["型13"]),
        # 検出してはいけない文
        ("読者への呼びかけ（飲み比べてみたい方に）", "飲み比べてみたい方には、5大産地のセットが向いています。", []),
        ("読者への提案（試してみてください）", "次回は茶葉の量だけを控えめにして、好みの濃さを探ってみてください。", []),
        ("体験が無いと断る注記（含みません）", "実際に飲んだ感想は含みません。", []),
        ("体験が無いと断る注記（ではありません）", "合わせ方は一般的な特徴から考えた整理であり、実際に合わせて食べた感想ではありません。", []),
        ("レビュー投稿者の話", "実際に使っている方の声を確認しやすいのも安心材料のひとつです。", []),
        ("読者の行動の提案", "自分用として試してみて、気に入れば別の機会に贈り物にするという使い方もあります。", []),
        ("条件文（実際に飲んでみないと）", "どの方向が好みかは、実際に飲んでみないと分かりません。", []),
        ("AIが行った調査（読み比べた結果）", "資料を読み比べた結果、目安は3分とされています。", []),
        ("現在形の案内（別記事で詳しく紹介しています）", "保存期間は[別記事](/posts/x/)で詳しく紹介しています。", []),
        ("読者の予定（来客予定の前日）", "来客予定の前日にまとめて作っておくと当日が楽になります。", []),
        ("読者の予定（運転の予定がある日）", "運転の予定がある日にも選びやすい作り方です。", []),
        ("「あらためて知りたい方」の案内", "基本的な特徴や淹れ方をあらためて知りたい方は、[入門](/posts/x/)もご覧ください。", []),
    ]
    for description, body, expected in cases:
        path = _article(root, "case-a1213", body)
        got = [t for t in _types(fs, path) if t in ("型12", "型13")]
        results.append((description, got == expected, "期待=%s 実際=%s" % (expected, got)))
    # 型12・13は new_type（新規公開はNG・--revise と週次は警告）
    path = _article(root, "case-a1213-new", "飲み比べた話は別記事に譲ります。別記事で改めて扱う予定です。")
    hits = [v for v in fs.check_xy(path, "dummy") if v["hit"].startswith(("型12", "型13"))]
    results.append(("型12・13は new_type（--revise・週次は警告）",
                    len(hits) == 2 and all(v["new_type"] for v in hits), str(hits)))
    # カテゴリH（〜たところ）と二重に出さない
    path = _article(root, "case-a1213-h", "試したところ、淹れた結果は良好でした。")
    got = [t for t in _types(fs, path) if t == "型12"]
    results.append(("カテゴリHが拾う文は型12で二重に出さない", got == [], "実際=%s" % got))
    # 公開前チェックと同じ入口（run_single）と週次の入口（run_survey_xy）
    import contextlib, io
    old_drafts, old_posts = fs.DRAFTS_DIR, fs.POSTS_DIR
    fs.DRAFTS_DIR = root
    try:
        for description, revise, expected_code, expected_texts in (
            ("run_single: 型12・13のダミー → 終了コード1・[Y 型12]と[Y 型13]を表示（安全助言の案内は出さない）",
             False, 1, ["[Y] 飲み比べた話", "[Y 型12]", "[Y 型13]"]),
            ("run_single --revise: 型12・13のダミー → 終了コード0・【警告】",
             True, 0, ["【警告】", "型12", "型13"]),
        ):
            _article(root, "case-cli1213", "飲み比べた話は別記事に譲ります。別記事で改めて扱う予定です。")
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = fs.run_single("case-cli1213", revise=revise)
            text = buffer.getvalue()
            ok = code == expected_code and all(t in text for t in expected_texts)
            if not revise:
                ok = ok and "[Y] 安全・保存の助言" not in text
            results.append((description, ok, "終了コード=%s 出力=%s" % (code, text[:300])))
        # 週次（--survey-xy）: 公開済みとして置いたダミーに【警告】で件数が出る
        posts_dir = os.path.join(root, "posts")
        _write(os.path.join(posts_dir, "case-survey.md"),
               "---\ntitle: ダミー\nslug: case-survey\ncategory: how-to\nstatus: published\n---\n\n"
               "飲み比べた話は別記事に譲ります。別記事で改めて扱う予定です。\n")
        fs.POSTS_DIR = posts_dir
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = fs.run_survey_xy()
        text = buffer.getvalue()
        results.append(("run_survey_xy: 型12・13が【警告】で件数表示・終了コード0",
                        code == 0 and "【警告】XY_SURVEY_WARN_型12: 1件" in text and "【警告】XY_SURVEY_WARN_型13: 1件" in text,
                        text[-300:]))
    finally:
        fs.DRAFTS_DIR, fs.POSTS_DIR = old_drafts, old_posts


# 既知の指摘26件（直前の設計調査と同じ分母）: (群, 修正前のcommit, slug, 該当文に含まれる語)
ADVICE_KNOWN = [
    ("D-0312", "3037fe9", "toji-yuzu-koucha-oyatsu", "歳未満"),
    ("D-0312", "3037fe9", "chailatte-masala-chai-chigai", "飲み切る前提"),
    ("D-0312", "3037fe9", "creamdown-boushi", "いつもと違う"),
    ("D-0312", "3037fe9", "mizudashi-koucha-hozon-eisei-qa", "一口含ん"),
    ("D-0312", "3037fe9", "mizudashi-koucha-hozon-eisei-qa", "2日以内"),
    ("D-0312", "3037fe9", "chakan-canister-erabikata", "防ぎきれず"),
    ("D-0312", "3037fe9", "koucha-nisenme-degarashi-tanoshimikata", "乾かさず"),
    ("D-0312", "3037fe9", "tea-strainer-chakoshi-erabikata", "つけ置き"),
    ("D-0312", "3037fe9", "tea-strainer-chakoshi-erabikata", "煮沸"),
    ("D-0312", "3037fe9", "glass-cup-hikaku", "いきなり熱湯"),
    ("D-0312", "3037fe9", "glass-cup-hikaku", "重ねず"),
    ("D-0315", "72d34bf", "hot-apple-tea-tsukurikata", "はちみつを使わない"),
    ("D-0319", "4fcdd86", "aki-hotel-afternoontea-jitaku-styling", "コースター"),
    ("D-0319", "4fcdd86", "aki-hotel-afternoontea-jitaku-styling", "ペット"),
    ("D-0319", "4fcdd86", "aki-hotel-afternoontea-jitaku-styling", "ぐらつ"),
    ("W45", "33e1ab4", "aki-moyougae-hitoribun-tea-space", "常温に置きません"),
    ("W45", "33e1ab4", "aki-moyougae-hitoribun-tea-space", "耐熱性のある台"),
    ("W45", "33e1ab4", "bone-china-jiki-touki-chigai", "電子レンジで使えません"),
    ("W45", "33e1ab4", "bone-china-jiki-touki-chigai", "表記がない場合は使わない"),
    ("W45", "33e1ab4", "glass-cup-hikaku", "割れやすいため"),
    ("W45", "33e1ab4", "hot-apple-tea-tsukurikata", "こすり洗い"),
    ("W45", "33e1ab4", "koucha-shomikigen-kireta-fuumi-mikiwame", "少量だけ淹れ"),
    ("W45", "33e1ab4", "outdoor-camp-mizudashi-koucha", "1時間ごと"),
    ("W45", "33e1ab4", "shukaku-no-aki-koucha-fruit-pairing", "流水で"),
    ("W45", "33e1ab4", "teacup-shokusenki-denshirenji-otenire-qa", "発火"),
    ("W45", "33e1ab4", "teacup-shokusenki-denshirenji-otenire-qa", "浸け置き"),
]
ADVICE_RECALL_MIN = 23


def advice_recall(fs, root):
    """既知の26件の修正前の版に、新しい判定（候補）と現行の型1〜11をかける。
    戻り値: [(群, slug, 語, 判定)]。判定は "new"（候補）・"current"（型1〜11だけ）・"both"・"miss"・"no_file"・"not_found"。"""
    import subprocess
    site = os.path.dirname(SCRIPT_DIR)
    rows = []
    for group, commit, slug, anchor in ADVICE_KNOWN:
        r = subprocess.run(["git", "-C", site, "show", "%s:src/content/posts/%s.md" % (commit, slug)],
                           capture_output=True)
        if r.returncode != 0:
            rows.append((group, slug, anchor, "no_file"))
            continue
        path = _write_tmp(root, "recall-%s" % slug, r.stdout.decode("utf-8"))
        cand_texts = [c["text"] for c in fs.advice_candidates(path)]
        front, body = fs.split_frontmatter(fs.io_read(path))
        start = len(front.splitlines()) + 3 if front else 1
        found, new, current = False, False, False
        for unit in fs.build_units(body, start):
            for block in fs.advice_blocks(unit):
                text = fs.advice_block_text(block)
                if anchor not in text:
                    continue
                found = True
                new = new or text in cand_texts
            for sub in fs.safety_sub_units(unit):
                sub_text = fs.unit_text(sub)
                if anchor not in sub_text:
                    continue
                hits = (fs.safety_advice_hits(sub_text) + fs.food_storage_hits(sub_text)
                        + fs.care_hygiene_hits(sub_text) + fs.keeping_safety_hits(sub_text))
                current = current or any(anchor in h[2] or h[0] in ("型9", "型10") for h in hits)
        verdict = "not_found" if not found else ("both" if new and current else "new" if new
                                                  else "current" if current else "miss")
        rows.append((group, slug, anchor, verdict))
    return rows


def _write_tmp(root, name, text):
    path = os.path.join(root, name + ".md")
    _write(path, text.replace("\r\n", "\n"))
    return path


def case_e(results, root):
    """L097・L096（D-0328）: 助言の候補と処置の台帳、公開前チェックへの組み込み、posts側の直接編集の停止。"""
    import contextlib, io
    fs = _load("check-fact-source.py")
    # 1. 既知の26件の拾い率（新しい判定＋現行の型1〜11で23件以上）
    rows = advice_recall(fs, root)
    picked = [r for r in rows if r[3] in ("new", "current", "both")]
    counts = {k: sum(1 for r in rows if r[3] == k) for k in ("both", "new", "current")}
    missed = "・".join("%s %s（%s）" % (r[1], r[2], r[3]) for r in rows if r not in picked) or "なし"
    results.append(("既知の指摘26件のうち %d件以上を拾う（実際 %d件。両方%d・新しい判定だけ%d・型1〜11だけ%d。拾えなかった: %s）"
                    % (ADVICE_RECALL_MIN, len(picked), counts["both"], counts["new"], counts["current"], missed),
                    len(rows) == 26 and len(picked) >= ADVICE_RECALL_MIN,
                    "\n".join("%s %s %s → %s" % r for r in rows)))
    # 2. 候補の単位と台帳
    old = (fs.DRAFTS_DIR, fs.POSTS_DIR, fs.ADVICE_DISPOSITIONS_PATH)
    sf = fs._source_fetched_module()
    old_log = sf.LOG_PATH
    log_path = os.path.join(root, "webfetch-log.md")
    _write(log_path, "記録開始日: 2026-01-01\n\n- 2026-11-08 | https://www.caa.go.jp/example | 200\n")
    fs.DRAFTS_DIR = root
    fs.ADVICE_DISPOSITIONS_PATH = os.path.join(root, "advice-dispositions.tsv")
    real_loader = fs._source_fetched_module

    def patched_loader():
        module = real_loader()
        module.LOG_PATH = log_path
        return module
    fs._source_fetched_module = patched_loader
    try:
        unit_cases = [
            ("話題の語が前の文にある（電子レンジ…。表記がない場合は使わないのが無難） → 候補",
             "電子レンジ対応の表記を確認します。表記がない場合は使わないのが無難です。", 1),
            ("箇条書きは1項目ずつ（2項目とも助言） → 候補2件", "- 冷蔵で保存してください\n- 熱湯は避けてください", 2),
            ("表の1行ずつ（区切り行は除く） → 候補2件",
             "| 場面 | 目安 |\n|---|---|\n| 保存 | 冷暗所に置いてください |\n| 洗い方 | 手洗いがおすすめです |", 2),
            ("出典URLがあっても自動では処置済みにしない → 候補",
             "冷蔵で保存してください（[消費者庁](https://www.caa.go.jp/example)）。", 1),
            ("話題の語なし（淹れ方の手順） → なし", "ポットにお湯を注ぎ、3分蒸らしてください。", 0),
            ("見出し行だけに話題の語 → なし", "## 保存のコツ\n\n香りを楽しんでください。", 0),
            ("リンク文字だけに話題の語 → なし", "詳しくは[保存の記事](/posts/x/)をご覧ください。", 0),
        ]
        for description, body, expected in unit_cases:
            path = _article(root, "case-e-unit", body)
            got = len(fs.advice_candidates(path))
            results.append((description, got == expected, "期待=%d 実際=%d" % (expected, got)))
        # 3. ゲート（新規公開・--revise とも同じ入口）: 処置が無ければNG、処置を記録すれば通る
        body = ("冷蔵で保存し、早めに飲みきってください（[消費者庁](https://www.caa.go.jp/example)）。\n\n"
                "- 茶葉は密閉できる缶に入れると、香りが移りにくいとされています\n")
        _article(root, "case-e-gate", body)
        cands = fs.advice_candidates(os.path.join(root, "case-e-gate.md"))

        def gate():
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = fs.run_advice_gate("case-e-gate")
            return code, buffer.getvalue()

        def record(*args):
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = fs.run_advice_record("case-e-gate", *args)
            return code, buffer.getvalue()

        code, text = gate()
        results.append(("処置の無い候補が残るダミー → --advice は終了コード1・記録コマンドを表示",
                        len(cands) == 2 and code == 1 and "--advice-record %s source" % cands[0]["hash"] in text
                        and "--advice-record %s not_advice" % cands[1]["hash"] in text, text[:600]))
        code, text = record(cands[0]["hash"], "source", "https://example.com/not-in-body")
        results.append(("source: 本文に無いURL → 記録しない", code == 1 and "本文にありません" in text, text))
        _article(root, "case-e-gate", body + "\n参考: https://www.mhlw.go.jp/not-fetched\n")
        code, text = record(cands[0]["hash"], "source", "https://www.mhlw.go.jp/not-fetched")
        results.append(("source: WebFetchの記録に無いURL → 記録しない", code == 1 and "webfetch-log" in text, text))
        _article(root, "case-e-gate", body)
        code, text = record("000000000000", "not_advice", "理由")
        results.append(("存在しないハッシュ → 記録しない", code == 1, text))
        code, text = record(cands[0]["hash"], "source", "https://www.caa.go.jp/example")
        code2, text2 = record(cands[1]["hash"], "not_advice", "商品の仕様の説明で、保存の助言ではない")
        results.append(("source（本文にあり・WebFetch記録あり）と not_advice を記録", code == 0 and code2 == 0, text + text2))
        code, text = gate()
        results.append(("処置を記録すると --advice は終了コード0", code == 0 and "ADVICE_OK" in text, text))
        _article(root, "case-e-gate", body.replace("（[消費者庁](https://www.caa.go.jp/example)）", "")
                 + "\n参考: [消費者庁](https://www.caa.go.jp/example)\n")
        code, text = gate()
        results.append(("本文が変わってハッシュが合わない行は無視（その候補は再びNG）", code == 1, text[:300]))
        _article(root, "case-e-gate", "- 茶葉は密閉できる缶に入れると、香りが移りにくいとされています\n")
        code, text = gate()
        results.append(("source のURLが本文から消えた・候補を削除した → 残りは処置済みで通る", code == 0, text))
        with open(fs.ADVICE_DISPOSITIONS_PATH, encoding="utf-8") as f:
            lines = f.read().splitlines()
        results.append(("台帳は見出し＋記録した2行（ハッシュが合わない行も消さない）",
                        len(lines) == 3 and lines[0].split("\t") == fs.ADVICE_HEADER, "\n".join(lines)))
        # 4. 新規公開・--revise の両方の公開前チェックに --advice が入り、同じ引数で呼ばれる
        pa = _load("publish-article.py")
        draft = _article(root, "case-e-pub", "冷蔵で保存してください。", category="how-to")
        new_checks = pa.publish_checks(draft)
        revise_checks, _n = pa._revise_checks(draft)
        entry = ("check-fact-source.py", True, ["--advice"])
        results.append(("--advice は新規公開と --revise の両方の公開前チェックにある",
                        entry in new_checks and entry in revise_checks
                        and ("check-fact-source.py", True, ["--revise"]) in revise_checks,
                        "新規=%s / 改修=%s" % (new_checks, revise_checks)))
        for label, checks in (("新規公開", new_checks), ("--revise", revise_checks)):
            args = next(c[2] for c in checks if c == entry)
            original = sys.argv
            buffer = io.StringIO()
            try:
                sys.argv = ["check-fact-source.py", "case-e-pub"] + args
                with contextlib.redirect_stdout(buffer):
                    code = fs.main()
            finally:
                sys.argv = original
            results.append(("%s のチェックの引数で、処置の無い候補のダミー → 終了コード1" % label,
                            code == 1 and "L097" in buffer.getvalue(), buffer.getvalue()[:300]))
        h = fs.advice_candidates(draft)[0]["hash"]
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            record_code = fs.run_advice_record("case-e-pub", h, "not_advice", "テスト用のダミー")
            code = fs.run_advice_gate("case-e-pub")
        results.append(("処置を記録すると同じダミーが通る", record_code == 0 and code == 0, buffer.getvalue()))
    finally:
        fs.DRAFTS_DIR, fs.POSTS_DIR, fs.ADVICE_DISPOSITIONS_PATH = old
        fs._source_fetched_module = real_loader
        sf.LOG_PATH = old_log
    case_e_head(results, root)


def case_e_head(results, root):
    """L096（D-0328）: posts側の対象記事が git の HEAD と違えば --prepare-revise と --revise がどちらも止まる。
    一時ディレクトリに git リポジトリを作って試す（本物の posts は変更しない）。"""
    import contextlib, io, subprocess
    pa = _load("publish-article.py")
    pa.mark_daily_session = lambda: None
    site = os.path.join(root, "head-site")
    posts = os.path.join(site, "src", "content", "posts")
    drafts = os.path.join(root, "head-drafts")
    os.makedirs(drafts, exist_ok=True)
    slug = "case-head"
    article = ("---\ntitle: ダミー\nslug: %s\ncategory: how-to\nstatus: published\nupdated: 2026-01-01\n---\n\n本文です。\n"
               % slug)
    _write(os.path.join(posts, slug + ".md"), article)

    def g(*args):
        return subprocess.run(["git", "-C", site] + list(args), capture_output=True)
    g("init", "-q")
    g("add", "--", "src/content/posts/%s.md" % slug)
    g("-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-q", "-m", "init")
    old = (pa.SITE, pa.POSTS_DIR, pa.DRAFTS_DIR)
    pa.SITE, pa.POSTS_DIR, pa.DRAFTS_DIR = site, posts, drafts

    def run(fn, args):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = fn(args)
        return code, buffer.getvalue()
    try:
        code, text = run(pa._run_prepare_revise, [slug])
        results.append(("posts が HEAD と同じ → --prepare-revise は止めない", code == 0 and "L096" not in text, text[-300:]))
        _write(os.path.join(posts, slug + ".md"), article.replace("本文です。", "posts側を直接書き換えた本文です。"))
        _write(os.path.join(drafts, slug + ".md"), article.replace("本文です。", "下書きで直した本文です。"))
        code, text = run(pa._run_prepare_revise, [slug])
        results.append(("posts が HEAD と違う → --prepare-revise は止まる・戻し方を表示",
                        code == 1 and "L096" in text and "--prepare-revise %s からやり直" % slug in text, text[-400:]))
        code, text = run(pa._run_revise, [slug, "--dry-run"])
        results.append(("posts が HEAD と違う → --revise（--dry-run）も止まる",
                        code == 1 and "L096" in text and "公開前チェック群" not in text, text[-400:]))
        code, text = run(pa._run_revise, [slug])
        with open(os.path.join(posts, slug + ".md"), encoding="utf-8") as f:
            still = "posts側を直接書き換えた" in f.read()
        log = g("log", "--oneline").stdout.decode("utf-8", "replace").strip().splitlines()
        results.append(("posts が HEAD と違う → --revise（本番）も止まり、コピー・commit をしない",
                        code == 1 and "L096" in text and still and len(log) == 1, text[-300:]))
    finally:
        pa.SITE, pa.POSTS_DIR, pa.DRAFTS_DIR = old


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
        case_e(results, root)
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
