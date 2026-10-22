# -*- coding: utf-8 -*-
r"""差し替えピン（D-0282）の再発防止テスト。

本物の output/pins/・台帳・Pinterest API には触れない。一時ディレクトリに作ったダミーのピンmd・画像・
投稿済み台帳・pin-daily-metrics.tsv へ読み込み先を差し替え、pinterest_api を偽物（メモリ上のピン一覧）に
入れ替えて、各スクリプトの関数をそのまま呼ぶ（テスト側で判定を再実装しない）。
一時ディレクトリは終了時に必ず消す。

確かめること:
  1. post-pins-to-pinterest.py の旧ピン処理: 削除・既に無い・401で停止・IDが複数・IDなし・link不一致・
     新ピンのGETが200でない・--dry-run・未投稿は対象外・--mark-manual・投稿成功の直後の処理（main 経由）
  2. pick-image-variation.py --replace-pin の骨組み（--dry-run は書かない）と再利用・
     骨組みが post-pins で「画像ファイルパス欠落」になること
  3. check-replacement-pins.py の未完了の行（画像なし・未投稿・旧ピン未処理・NONE）と --verify
  4. check-pin-image-naming.py の免除（差し替えピンの画像なしだけを免除する）
  5. 先行ピンの目印を持たない差し替えピンmdが check-advance-pin-today.py の判定に入らないこと
  6. .claude/hooks/check-pin-board.py が post-pins-to-pinterest.py から import する名前を読め、
     通常のピンmdの Write 相当を許可すること（ファイルは書かない）

使い方:
  python site/scripts/test-replacement-pins.py
"""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
HOOK_PATH = os.path.join(ROOT, ".claude", "hooks", "check-pin-board.py")
TODAY = "2031-05-05"  # 実日付と無関係な日付
SLUG = "zz-replace-article"
BOARD = "紅茶を選ぶ"
ARTICLE_URL = "https://kohaku-jikan.com/posts/%s/" % SLUG


def _load(file_name):
    spec = importlib.util.spec_from_file_location(
        file_name[:-3].replace("-", "_") + "_under_test", os.path.join(SCRIPT_DIR, file_name))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _pin_md(root, num, branch, replace_from=None, result=None, date="2031-05-01",
            style="写真ヒーロー", link_num=None):
    """ダミーのピンmd。replace_from を渡すと差し替えピン、result を渡すと旧ピン処理済み。"""
    name = "%s-pin-%d-%s-%02d.md" % (date, num, SLUG, branch)
    extra = ""
    if replace_from is not None:
        extra += "- 差し替え元ピン: %d\n" % replace_from
    if result is not None:
        extra += "- 旧ピン処理: %s\n" % result
    _write(os.path.join(root, "pins", name), (
        "# ピン%d: ダミー\n\n"
        "- ステータス: 画像生成済み（images/ピン%d ダミー（誘導先 ダミー記事）.png）\n"
        "%s"
        "- 誘導先URL: %s?utm_source=pinterest&utm_medium=social&utm_campaign=%s&utm_content=pin%d\n"
        "ボード: %s\n\n"
        "## 画像指示書\n- 型: %s\n- 記事連番: 1\n"
        "- テキストオーバーレイ: 「答えの文言」「二つ目の文言」（2件）\n\n"
        "## 投稿文\nタイトル: ダミーのタイトル\n"
        "説明文: ダミーの説明文です。二文目です。 #紅茶 #ギフト\n"
        "- X用説明文: ダミーのX用説明文です。 #紅茶\n"
        "- Threads用問いかけ: ダミーの問いかけですか？\n"
    ) % (num, num, extra, ARTICLE_URL, SLUG, link_num or num, BOARD, style))
    return name


def _image(root, num, stamp=None):
    """「ピン{番号} …（誘導先 …）」形式の画像を置く。stamp（hero-to-webp.py）を渡すと合成の目印も入れる。"""
    from PIL import Image
    dest = os.path.join(root, "images", "ピン%d ダミー（誘導先 ダミー記事）.png" % num)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if stamp is None:
        Image.new("RGB", (100, 150), (240, 230, 210)).save(dest, "PNG")
        return dest
    source = os.path.join(root, "source-%d.png" % num)
    Image.new("RGB", (1000, 1500), (240, 230, 210)).save(source, "PNG")
    with contextlib.redirect_stdout(io.StringIO()):
        stamp.stamp_pin(source, dest)
    return dest


def _posted(root, numbers):
    _write(os.path.join(root, "pin-posted.md"),
           "# ダミーの投稿済み台帳\n" + "".join("投稿済み: %d\n" % n for n in numbers))


def _metrics(root, rows):
    """rows: [(pin_id, pin_number), ...]（同じ組を2行ずつ書いて日次の重複も再現する）。"""
    body = "pin_id\tpin_number\tdate\n"
    for pin_id, num in rows:
        body += "%s\t%d\t2031-05-01\n%s\t%d\t2031-05-02\n" % (pin_id, num, pin_id, num)
    _write(os.path.join(root, "metrics.tsv"), body)


def _link(num):
    return "%s?utm_source=pinterest&utm_content=pin%d" % (ARTICLE_URL, num)


class FakeApi(object):
    """pinterest_api の偽物。pins は {pin_id: link}。fail は {(メソッド, pin_id): HTTPステータス}。"""

    def __init__(self, real, pins, fail=None):
        self.PinterestApiError = real.PinterestApiError
        self.pins = dict(pins)
        self.fail = dict(fail or {})
        self.calls = []

    def request(self, method, path, access_token, body=None, extra_headers=None, timeout=15):
        pin_id = path.rstrip("/").rsplit("/", 1)[-1]
        self.calls.append((method, pin_id))
        if (method, pin_id) in self.fail:
            raise self.PinterestApiError(self.fail[(method, pin_id)], '{"message":"fake"}')
        if pin_id not in self.pins:
            raise self.PinterestApiError(404, '{"code":50,"message":"Pin not found."}')
        if method == "DELETE":
            del self.pins[pin_id]
            return {}
        return {"id": pin_id, "link": self.pins[pin_id]}

    def fetch_all_pages(self, path, access_token, page_size=100, timeout=15):
        self.calls.append(("LIST", path))
        return [{"id": k, "link": v} for k, v in self.pins.items()]

    def count(self, method):
        return len([c for c in self.calls if c[0] == method])


def _point_post(post, root, api):
    post.PINS_DIR = os.path.join(root, "pins")
    post.LEDGER_PATH = os.path.join(root, "pin-posted.md")
    post.METRICS_PATH = os.path.join(root, "metrics.tsv")
    post.DATA_DIR = root
    post.ROOT = root
    post.BOARDS_FILE = os.path.join(root, "boards.md")
    post.POST_INTERVAL_SECONDS = 0
    post.pinterest_api = api
    post.require_env = lambda name: "dummy-token"


def _run_main(func, *args):
    """関数を呼び、(戻り値または終了コード, 標準出力) を返す。"""
    buffer = io.StringIO()
    code = None
    with contextlib.redirect_stdout(buffer):
        try:
            code = func(*args)
        except SystemExit as e:
            code = e.code
    return code, buffer.getvalue()


def run_post_cases():
    results = []
    real_api = _load("pinterest_api.py")

    def case(description, ok, detail=""):
        results.append((description, ok, detail))

    def fresh(pins, metrics, fail=None, posted=(301, 302)):
        root = tempfile.mkdtemp(prefix="replace_pin_test_")
        roots.append(root)
        post = _load("post-pins-to-pinterest.py")
        api = FakeApi(real_api, pins, fail)
        _point_post(post, root, api)
        _pin_md(root, 201, 1)
        _pin_md(root, 202, 2)
        _metrics(root, metrics)
        _posted(root, posted)
        return root, post, api

    def apply(post, dry_run=False):
        return _run_main(post.apply_replacements, dry_run, TODAY)

    roots = []
    try:
        # --- 削除: 旧ピンが残っていて link が一致 → DELETE 1回 → GET 404 → deleted ---
        root, post, api = fresh({"N301": _link(301), "O201": _link(201)}, [("N301", 301), ("O201", 201)])
        name = _pin_md(root, 301, 4, replace_from=201)
        _code, out = apply(post)
        text = _read(os.path.join(root, "pins", name))
        case("1-a. 削除: GET 200・link一致 → DELETE 1回・「旧ピン処理: deleted」を書く",
             api.count("DELETE") == 1 and "- 旧ピン処理: deleted %s O201" % TODAY in text
             and "O201" not in api.pins, out.strip())
        lines = text.splitlines()
        case("1-b. 旧ピン処理の行は差し替え元ピン行の直後に入る",
             lines.index("- 旧ピン処理: deleted %s O201" % TODAY) == lines.index("- 差し替え元ピン: 201") + 1)
        _code, out = apply(post)
        case("1-c. 完了したmdは二度と照合しない", "未完了の差し替えピンはありません" in out
             and api.count("DELETE") == 1, out.strip())

        # --- 既に無い: 旧ピンの GET が404 → already_gone・DELETE 0回 ---
        root, post, api = fresh({"N301": _link(301)}, [("N301", 301), ("O201", 201)])
        name = _pin_md(root, 301, 4, replace_from=201)
        _code, out = apply(post, dry_run=True)
        case("2-a. 既に無い（--dry-run）: 「旧ピンは既に無い」と出し、書かない・DELETEしない",
             "旧ピンは既に無い(dry-run)" in out and "旧ピン処理" not in _read(os.path.join(root, "pins", name))
             and api.count("DELETE") == 0, out.strip())
        _code, out = apply(post)
        case("2-b. 既に無い: 「旧ピン処理: already_gone」を書き、DELETEは0回",
             "- 旧ピン処理: already_gone %s O201" % TODAY in _read(os.path.join(root, "pins", name))
             and api.count("DELETE") == 0 and "DELETE送信: 0件" in out, out.strip())

        # --- --dry-run で削除見込み: DELETE を送らず、書かない ---
        root, post, api = fresh({"N301": _link(301), "O201": _link(201)}, [("N301", 301), ("O201", 201)])
        name = _pin_md(root, 301, 4, replace_from=201)
        _code, out = apply(post, dry_run=True)
        case("3. --dry-run: GET 200・link一致でも DELETE を送らず、行も書かない",
             "DELETE見込み(dry-run)" in out and api.count("DELETE") == 0
             and "旧ピン処理" not in _read(os.path.join(root, "pins", name)), out.strip())

        # --- 401 で停止: 1件目で401 → 以降の DELETE を送らない ---
        root, post, api = fresh({"N301": _link(301), "N302": _link(302), "O201": _link(201), "O202": _link(202)},
                                [("N301", 301), ("N302", 302), ("O201", 201), ("O202", 202)],
                                fail={("GET", "O201"): 401})
        first = _pin_md(root, 301, 4, replace_from=201)
        second = _pin_md(root, 302, 5, replace_from=202)
        _code, out = apply(post)
        case("4. 401で停止: 「トークン失効または権限変更の疑い」と出し、以降の DELETE を送らない・どちらも未完了",
             "トークン失効または権限変更の疑い" in out and api.count("DELETE") == 0
             and "旧ピン処理" not in _read(os.path.join(root, "pins", first))
             and "旧ピン処理" not in _read(os.path.join(root, "pins", second))
             and ("GET", "O202") not in api.calls, out.strip())

        # --- 403 も同じ扱い（DELETE で403） ---
        root, post, api = fresh({"N301": _link(301), "O201": _link(201)}, [("N301", 301), ("O201", 201)],
                                fail={("DELETE", "O201"): 403})
        _pin_md(root, 301, 4, replace_from=201)
        _code, out = apply(post)
        case("5. DELETE が403 → 停止・未完了（行を書かない）",
             "トークン失効または権限変更の疑い" in out and "O201" in api.pins, out.strip())

        # --- ID が複数: metrics に2件 → 一覧を走査。一覧でも2件 → 決めずに未完了 ---
        root, post, api = fresh({"N301": _link(301), "O201a": _link(201), "O201b": _link(201)},
                                [("N301", 301), ("O201a", 201), ("O201b", 201)])
        name = _pin_md(root, 301, 4, replace_from=201)
        _code, out = apply(post)
        case("6-a. IDが複数（metrics 2件・一覧でも2件）→ 未完了・DELETEなし・記事URL/旧番号/ボードを併記",
             "1件に決められません" in out and api.count("DELETE") == 0 and api.count("LIST") == 1
             and ARTICLE_URL in out and "旧ピン番号: 201" in out and "ボード: %s" % BOARD in out
             and "旧ピン処理" not in _read(os.path.join(root, "pins", name)), out.strip())
        root, post, api = fresh({"N301": _link(301), "O201b": _link(201)},
                                [("N301", 301), ("O201a", 201), ("O201b", 201)])
        name = _pin_md(root, 301, 4, replace_from=201)
        _code, out = apply(post)
        case("6-b. metrics 2件でも、一覧で utm_content=pin201 かつ GET 200 が1件なら、それを削除する",
             "- 旧ピン処理: deleted %s O201b" % TODAY in _read(os.path.join(root, "pins", name))
             and api.count("DELETE") == 1, out.strip())

        # --- ID なし: metrics 0件・一覧 0件 → 未完了・記事URL等を併記 ---
        root, post, api = fresh({"N301": _link(301)}, [("N301", 301)])
        name = _pin_md(root, 301, 4, replace_from=201)
        _code, out = apply(post)
        case("7. IDなし（metrics 0件・一覧 0件）→ 未完了・記事URL/旧番号/ボードを併記",
             "1件に決められません" in out and ARTICLE_URL in out and "旧ピン番号: 201" in out
             and "旧ピン処理" not in _read(os.path.join(root, "pins", name)), out.strip())

        # --- link 不一致: 候補の link が pin201 でない → 未完了・直リンク ---
        root, post, api = fresh({"N301": _link(301), "O201": _link(777)}, [("N301", 301), ("O201", 201)])
        name = _pin_md(root, 301, 4, replace_from=201)
        _code, out = apply(post)
        case("8. link不一致 → DELETEなし・未完了・直リンクを出す",
             api.count("DELETE") == 0 and "https://www.pinterest.com/pin/O201/" in out
             and "utm_content が pin201 ではありません" in out
             and "旧ピン処理" not in _read(os.path.join(root, "pins", name)), out.strip())

        # --- 5xx: 旧ピンの GET が503 → 未完了 ---
        root, post, api = fresh({"N301": _link(301), "O201": _link(201)}, [("N301", 301), ("O201", 201)],
                                fail={("GET", "O201"): 503})
        name = _pin_md(root, 301, 4, replace_from=201)
        _code, out = apply(post)
        case("9. 旧ピンの GET が503 → 未完了・DELETEなし",
             api.count("DELETE") == 0 and "HTTP 503" in out
             and "旧ピン処理" not in _read(os.path.join(root, "pins", name)), out.strip())

        # --- 新ピンの GET が200でない → 何もしない ---
        root, post, api = fresh({"O201": _link(201)}, [("N301", 301), ("O201", 201)])
        name = _pin_md(root, 301, 4, replace_from=201)
        _code, out = apply(post)
        case("10. 新ピンの GET が200でない → 旧ピンに触れない（GETもしない）・未完了",
             ("GET", "O201") not in api.calls and api.count("DELETE") == 0 and "次回に持ち越し" in out, out.strip())

        # --- 未投稿の差し替えは --apply-replacements の対象外 ---
        root, post, api = fresh({"O201": _link(201)}, [("O201", 201)], posted=())
        _pin_md(root, 301, 4, replace_from=201)
        _code, out = apply(post)
        case("11. 新ピンが未投稿 → 対象外（APIを呼ばない）", "対象外" in out and not api.calls, out.strip())

        # --- --mark-manual: APIを呼ばずに manual を書く ---
        root, post, api = fresh({}, [])
        name = _pin_md(root, 301, 4, replace_from=201)
        code, out = _run_main(post.mark_manual, 301, TODAY)
        case("12-a. --mark-manual: 「旧ピン処理: manual 日付 -」を書き、APIは呼ばない",
             code == 0 and "- 旧ピン処理: manual %s -" % TODAY in _read(os.path.join(root, "pins", name))
             and not api.calls, out.strip())
        code, out = _run_main(post.mark_manual, 301, TODAY)
        case("12-b. --mark-manual: 完了済みのピンには書かない（終了コード1）", code == 1, out.strip())

        # --- 投稿成功の直後の処理（main の投稿経路を偽物の投稿で通す） ---
        root, post, api = fresh({}, [("O201", 201)], posted=(201, 202))
        name = _pin_md(root, 301, 4, replace_from=201)
        _image(root, 301)
        _write(post.BOARDS_FILE, "| ボード名 | board_id | a | b | c | 季節 |\n|---|---|---|---|---|---|\n"
               "| %s | B1 | - | - | - | 通年 |\n" % BOARD)
        status_loader = post._load_check_pin_posting_status

        def patched_status():
            module = status_loader()
            module.PINS_DIR = post.PINS_DIR
            module.LEDGER_PATH = post.LEDGER_PATH
            return module

        def fake_post(access_token, fields, board_id, sent=None):
            api.pins["N301"] = fields["guide_url"]
            api.calls.append(("POST", "N301"))
            return {"id": "N301"}

        post._load_check_pin_posting_status = patched_status
        post.compact_ledger = lambda today: None
        post.check_url_ok = lambda url: (True, "200 OK")
        post.fetch_recent_own_pins = lambda token: ([], False)
        post.post_pin = fake_post
        post.record_post_step = lambda *args, **kwargs: None
        original_argv = sys.argv
        sys.argv = ["post-pins-to-pinterest.py"]
        try:
            code, out = _run_main(post.main)
        finally:
            sys.argv = original_argv
        text = _read(os.path.join(root, "pins", name))
        case("13. 投稿成功の直後: 台帳へ記録し、続けて旧ピンを処理（already_gone は DELETE 0回で書く）",
             code == 0 and "301 / 成功" in out and "301 / 旧ピン処理: already_gone / 旧ピン201" in out
             and "- 旧ピン処理: already_gone" in text and api.count("DELETE") == 0
             and "投稿済み: 301" in _read(post.LEDGER_PATH), out.strip())
    finally:
        for root in roots:
            shutil.rmtree(root, ignore_errors=True)
    return results


def run_check_cases():
    results = []
    roots = []

    def case(description, ok, detail=""):
        results.append((description, ok, detail))

    try:
        root = tempfile.mkdtemp(prefix="replace_pin_check_")
        roots.append(root)
        hero_to_webp = _load("hero-to-webp.py")
        crp = _load("check-replacement-pins.py")
        cap = crp.cap()
        cap.PINS_DIR = os.path.join(root, "pins")
        cap.PIN_IMAGES_DIR = os.path.join(root, "images")
        cap.POSTED_LEDGER_PATH = os.path.join(root, "pin-posted.md")
        cap.POSTS_DIR = os.path.join(root, "posts")
        _write(os.path.join(root, "posts", "%s.md" % SLUG),
               "---\ntitle: ダミー\nslug: %s\ndate: 2031-01-10\ncategory: how-to\nstatus: published\n---\n本文\n" % SLUG)
        os.makedirs(cap.PIN_IMAGES_DIR, exist_ok=True)
        _pin_md(root, 201, 1, style="Q&A形式")
        _pin_md(root, 202, 2, style="比較グリッド")
        _pin_md(root, 203, 3, style="手順図解")
        _pin_md(root, 301, 4, replace_from=201)                     # 画像なし
        _pin_md(root, 302, 5, replace_from=202, style="チェックリスト")  # 画像あり・未投稿
        _pin_md(root, 303, 6, replace_from=203, date="2031-04-25")  # 画像あり・投稿済み
        _pin_md(root, 304, 7, replace_from=201, result="deleted 2031-05-01 X1")  # 完了
        _image(root, 302)
        _image(root, 303)
        _posted(root, [201, 202, 203, 303, 304])
        import datetime
        today = datetime.date.fromisoformat(TODAY)
        lines = crp.open_lines(today)
        case("14-a. 未完了の3件を1件1行で出し、完了したmdは出さない", len(lines) == 3, "\n".join(lines))
        case("14-b. 画像なし → 次の操作=画像生成→審査→投稿",
             any(l.startswith("REPLACEMENT_OPEN pin=301 old=201 状態=画像なし 経過4日 次の操作=画像生成→審査→投稿")
                 for l in lines))
        case("14-c. 画像あり・未投稿 → 状態=未投稿",
             any(l.startswith("REPLACEMENT_OPEN pin=302 old=202 状態=未投稿 ") for l in lines))
        case("14-d. 投稿済み → 状態=旧ピン未処理・次の操作=--apply-replacements",
             any(l.startswith("REPLACEMENT_OPEN pin=303 old=203 状態=旧ピン未処理 経過10日 "
                              "次の操作=post-pins-to-pinterest.py --apply-replacements を実行") for l in lines))

        # 先行ピンの目印を持たない差し替えピンmdは、先行ピンの判定に入らない
        case("15. 差し替えピンmdは check-advance-pin-today.py の先行ピン一覧に入らない",
             cap.advance_pins() == [], str(cap.advance_pins()))

        # --verify: 合格（枝番 -04・画像1件・公開中の記事・旧mdあり・型の重複なし・X本文）
        _image(root, 302, stamp=hero_to_webp)
        ng = []
        code_out = io.StringIO()
        with contextlib.redirect_stdout(code_out):
            ng = crp.verify(302, print)
        case("16-a. --verify: 条件を満たす差し替えピンは合格", ng == [], code_out.getvalue().strip())
        # 旧番号のmdが無い・枝番が -03 以前・型が記事の他のピンと重複 → NG
        _pin_md(root, 305, 2, replace_from=299, style="手順図解")
        _image(root, 305, stamp=hero_to_webp)
        code_out = io.StringIO()
        with contextlib.redirect_stdout(code_out):
            ng = crp.verify(305, print)
        joined = "\n".join(ng)
        case("16-b. --verify: 枝番 -02・同じ枝番・旧mdなし・型の重複をそれぞれNGにする",
             "枝番が -02" in joined and "同じ枝番" in joined and "旧ピン299 のmd" in joined
             and "同じ型" in joined, joined)
        code_out = io.StringIO()
        with contextlib.redirect_stdout(code_out):
            ng = crp.verify(201, print)
        case("16-c. --verify: 差し替え元ピン行の無いmdはNG", len(ng) == 1 and "差し替え元ピン行が無い" in ng[0], "\n".join(ng))

        # 全部完了すれば REPLACEMENT_NONE
        for name in sorted(os.listdir(cap.PINS_DIR)):
            if "-pin-30" in name:
                os.remove(os.path.join(cap.PINS_DIR, name))
        _pin_md(root, 304, 7, replace_from=201, result="manual 2031-05-01 -")
        code, out = _run_main(crp.main, [])
        case("17. 未完了が無ければ REPLACEMENT_NONE・終了コード0", code == 0 and out.strip() == "REPLACEMENT_NONE", out.strip())

        # --- naming の免除: 差し替えピンの画像なしだけを免除する ---
        naming = _load("check-pin-image-naming.py")
        naming.PINS_DIR = os.path.join(root, "naming-pins")
        naming.PIN_IMAGES_DIR = os.path.join(root, "naming-images")
        os.makedirs(naming.PIN_IMAGES_DIR, exist_ok=True)
        _write(os.path.join(naming.PINS_DIR, "2031-05-01-pin-9001-%s-04.md" % SLUG),
               "# ダミー\n- 差し替え元ピン: 201\n")
        code, out = _run_main(naming.main)
        case("18-a. naming: 差し替えピンの画像なしは警告に留める（総合OK）",
             code is None and "総合: OK" in out and "ピン9001" in out and "[警告]" in out, out.strip())
        _write(os.path.join(naming.PINS_DIR, "2031-05-01-pin-9002-%s-05.md" % SLUG), "# ダミー\n")
        code, out = _run_main(naming.main)
        case("18-b. naming: 目印の無い通常のピンの画像なしは従来どおりNG",
             code == 1 and "[NG] ピン9002" in out and "[NG] ピン9001" not in out, out.strip())
    finally:
        for root in roots:
            shutil.rmtree(root, ignore_errors=True)
    return results


def run_replace_pin_cases():
    results = []
    roots = []

    def case(description, ok, detail=""):
        results.append((description, ok, detail))

    try:
        root = tempfile.mkdtemp(prefix="replace_pin_pick_")
        roots.append(root)
        piv = _load("pick-image-variation.py")
        piv.PINS_DIR = os.path.join(root, "pins")
        piv.LEDGER_PATH = os.path.join(root, "image-variation.tsv")
        piv.today_jst = lambda: TODAY
        _pin_md(root, 201, 1, style="Q&A形式")
        _pin_md(root, 202, 2, style="比較グリッド")
        before = sorted(os.listdir(piv.PINS_DIR))

        code, out = _run_main(piv.cmd_replace_pin, [SLUG, "201", "--dry-run"])
        case("19-a. --replace-pin --dry-run: 番号・内容を出し、mdは書かない",
             sorted(os.listdir(piv.PINS_DIR)) == before and "ピン番号: 203" in out
             and "--dry-run のため書きません" in out and "  | - 差し替え元ピン: 201" in out, out.strip())

        code, out = _run_main(piv.cmd_replace_pin, [SLUG, "201"])
        name = "%s-pin-203-%s-04.md" % (TODAY, SLUG)
        path = os.path.join(piv.PINS_DIR, name)
        text = _read(path) if os.path.isfile(path) else ""
        case("19-b. --replace-pin: 骨組みのmd（差し替え元ピン・旧ピンのボード・utm_content=pin新番号・括弧なしのステータス）を書く",
             "- 差し替え元ピン: 201\n" in text and "ボード: %s\n" % BOARD in text
             and "utm_content=pin203\n" in text and "- ステータス: 作成中\n" in text
             and not os.path.isfile(piv.LEDGER_PATH), text)

        code, out = _run_main(piv.cmd_replace_pin, [SLUG, "201"])
        case("19-c. 同じ旧番号でもう一度実行すると、作成中の1枚を再利用し書き直さない",
             len(os.listdir(piv.PINS_DIR)) == len(before) + 1 and "ピン番号: 203" in out
             and "既にあるため書き直しません" in out and _read(path) == text, out.strip())

        code, out = _run_main(piv.cmd_replace_pin, [SLUG, "202", "--dry-run"])
        case("19-d. 別の旧番号なら次の番号・次の枝番を採る", "ピン番号: 204" in out and "-05" in out, out.strip())

        code, out = _run_main(piv.cmd_replace_pin, ["other-slug", "201", "--dry-run"])
        case("19-e. 旧ピンの誘導先と違う slug は止める", code and "slug を確認する" in str(code), str(code))

        post = _load("post-pins-to-pinterest.py")
        post.PINS_DIR = piv.PINS_DIR
        fields, reason = post.parse_pin_file(203, name)
        case("19-f. 骨組みのmdは post-pins で「画像ファイルパス」欠落としてスキップされる",
             fields is None and "画像ファイルパス" in (reason or ""), reason or "")
    finally:
        for root in roots:
            shutil.rmtree(root, ignore_errors=True)
    return results


def run_hook_cases():
    results = []
    post = _load("post-pins-to-pinterest.py")
    names = ("load_board_id_map", "resolve_board_id", "extract_slug_from_guide_url",
             "check_board_group_rules", "PINS_DIR", "BOARD_LINE_RE", "GUIDE_URL_RE")
    missing = [n for n in names if not hasattr(post, n)]
    results.append(("20-a. check-pin-board.py が import する名前を post-pins-to-pinterest.py から読める",
                     not missing, "不足: %s" % missing if missing else ""))
    content = (
        "# ピン99999: ダミー\n\n- ステータス: 作成中\n"
        "- 誘導先URL: https://kohaku-jikan.com/posts/zz-hook-test-only/?utm_content=pin99999\n"
        "ボード: %s\n\n## 画像指示書\n- 型: 写真ヒーロー\n- 記事連番: 1\n" % BOARD)
    payload = {"tool_name": "Write", "tool_input": {
        "file_path": os.path.join(ROOT, "output", "pins", "2099-01-01-pin-99999-zz-hook-test-only-01.md"),
        "content": content}}
    proc = subprocess.run([sys.executable, HOOK_PATH], input=json.dumps(payload, ensure_ascii=False),
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    results.append(("20-b. check-pin-board.py フックが通常のピンmdの Write 相当を許可する（終了コード0・ファイルは書かない）",
                     proc.returncode == 0 and not os.path.exists(payload["tool_input"]["file_path"]),
                     "終了コード %s %s" % (proc.returncode, (proc.stderr or "").strip())))
    return results


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    failures = []
    total = 0
    for title, cases in (
        ("post-pins-to-pinterest.py の旧ピン処理（偽の pinterest_api・一時ディレクトリ）", run_post_cases()),
        ("check-replacement-pins.py・check-pin-image-naming.py・check-advance-pin-today.py", run_check_cases()),
        ("pick-image-variation.py --replace-pin", run_replace_pin_cases()),
        (".claude/hooks/check-pin-board.py との互換", run_hook_cases()),
    ):
        print("=== %s ===" % title)
        for description, ok, detail in cases:
            total += 1
            if not ok:
                failures.append(description)
            print("[%s] %s%s" % ("OK" if ok else "NG", description, " — %s" % detail if detail and not ok else ""))
        print()
    if failures:
        print("失敗: %d件 / 全%d件" % (len(failures), total))
        for description in failures:
            print("  - %s" % description)
        sys.exit(1)
    print("全%d件のテストにパスしました。" % total)


if __name__ == "__main__":
    main()
