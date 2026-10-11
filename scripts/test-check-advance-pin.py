# -*- coding: utf-8 -*-
r"""check-advance-pin-today.py の判定（NEXT／INCOMPLETE／DONE／NONE・候補の並び・14日の除外・--require-row）の再発防止テスト（D-0275）。

本物の台帳・ピン・記事には触れず、一時ディレクトリに作ったダミーの台帳・記事・ピンmd・画像・
投稿済み台帳へ読み込み先を差し替えて、check-advance-pin-today.py の関数をそのまま呼ぶ
（テスト側で判定を再実装しない）。対象日は実日付と無関係な日付に固定する。
一時ディレクトリは終了時に必ず消す。

2つ目の群だけは publish-article.py の新規公開の経路を確かめるため、本物の output/articles/ に
ダミーの下書きを1件作って `--dry-run` 相当を実行し、直後に必ず消す（record-lesson.py の
セッションマーカーは作らない）。3つ目の群は、codex-gateway.py の growth-audit が本物の
growth/ledger/adopted-directives.tsv から先行ピンの指示（GD-0009・GD-0035）を読めることを、
gateway の読み取り関数を呼んで確かめる（Codex・外部APIは起動せず、何も書き込まない）。

使い方:
  python site/scripts/test-check-advance-pin.py
"""

import contextlib
import importlib.util
import io
import os
import shutil
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TARGET_DAY = "2031-05-05"  # 実日付と無関係な対象日
DUMMY_DRAFT_SLUG = "zz-test-advance-pin-require-row"
EXISTING_GIFT_SLUG = "kinrou-kansha-no-hi-koucha-petit-gift"  # 台帳に行のある公開済みの gift 記事


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


def _post(root, slug, category, date):
    _write(os.path.join(root, "posts", "%s.md" % slug),
           "---\ntitle: ダミー\nslug: %s\ndate: %s\ncategory: %s\nstatus: published\n---\n本文\n"
           % (slug, date, category))


def _pin(root, date, num, slug, branch, style, advance=None, head="答えの文言"):
    """ダミーのピンmdを作る。advance を渡すと先行ピン（その日付の作成日行つき）になる。"""
    name = "%s-pin-%d-%s-%02d.md" % (date, num, slug, branch)
    advance_line = "- 先行ピン作成日: %s\n" % advance if advance else ""
    _write(os.path.join(root, "pins", name), (
        "# ピン%d: %s（誘導先: ダミー記事）\n\n"
        "- ステータス: 画像生成済み（output/Pin-images/ピン%d ダミー（誘導先 ダミー記事）.png）\n"
        "%s"
        "- 誘導先URL: https://kohaku-jikan.com/posts/%s/?utm_source=pinterest&utm_medium=social"
        "&utm_campaign=%s&utm_content=pin%d\n"
        "ボード: 紅茶ギフト・贈り物\n\n"
        "## 画像指示書\n- 型: %s\n- 記事連番: 1\n"
        "- テキストオーバーレイ: 「%s」「二つ目の文言」（2件）\n\n"
        "## 投稿文\nタイトル: ダミーのタイトル\n"
        "説明文: ダミーの説明文です。二文目です。 #紅茶 #ギフト\n"
        "- X用説明文: ダミーのX用説明文です。 #紅茶\n"
        "- Threads用問いかけ: ダミーの問いかけですか？\n"
    ) % (num, style, num, advance_line, slug, slug, num, style, head))
    return name


def _image(root, num, hero_to_webp):
    """合成済みの目印が入ったダミーのPin画像を置く（合成は本物の stamp_pin を通す）。"""
    from PIL import Image
    source = os.path.join(root, "source-%d.png" % num)
    Image.new("RGB", (1000, 1500), (240, 230, 210)).save(source, "PNG")
    os.makedirs(os.path.join(root, "images"), exist_ok=True)
    dest = os.path.join(root, "images", "ピン%d ダミー（誘導先 ダミー記事）.png" % num)
    with contextlib.redirect_stdout(io.StringIO()):
        hero_to_webp.stamp_pin(source, dest)
    return dest


def _posted(root, numbers):
    _write(os.path.join(root, "pin-posted.md"),
           "# ダミーの投稿済み台帳\n投稿済み: %s\n" % ",".join(str(n) for n in numbers))


def _point(module, root):
    """check-advance-pin-today.py の読み込み先を一時ディレクトリへ差し替える。"""
    module.CALENDAR_PATH = os.path.join(root, "calendar.tsv")
    module.PINS_DIR = os.path.join(root, "pins")
    module.PIN_IMAGES_DIR = os.path.join(root, "images")
    module.POSTED_LEDGER_PATH = os.path.join(root, "pin-posted.md")
    module.POSTS_DIR = os.path.join(root, "posts")
    module.DRAFTS_DIR = os.path.join(root, "drafts")


def _run(module, argv):
    """main() を呼び、(終了コード, 標準出力) を返す。"""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = module.main(list(argv))
    return code, buffer.getvalue()


def _base(root):
    """共通の土台: 記事4本・台帳・既存ピン（各記事の -01〜-03）。"""
    _write(os.path.join(root, "calendar.tsv"), (
        "# ダミーの台帳\nslug\tpeaks\t根拠\n"
        "event-june\t06-01\t6月1日の行事（対象日から27日）\n"
        "event-june-b\t06-01\t同じ日の行事\n"
        "event-far\t09-15\t遠い行事\n"
        "event-near\t05-20\t近すぎる行事（15日）\n"
        "generic-gift\t-\t汎用\n"))
    _post(root, "event-june", "seasons", "2031-01-10")
    _post(root, "event-june-b", "gift", "2031-01-11")
    _post(root, "event-far", "gift", "2031-01-12")
    _post(root, "event-near", "seasons", "2031-01-13")
    _post(root, "generic-gift", "gift", "2031-01-14")
    _post(root, "how-to-article", "how-to", "2031-01-15")
    number = 9000
    for slug in ("event-june", "event-june-b", "event-far"):
        for branch, style in ((1, "写真ヒーロー"), (2, "Q&A形式"), (3, "ビフォーアフター")):
            number += 1
            _pin(root, "2031-01-20", number, slug, branch, style)
    _posted(root, range(9001, number + 1))
    os.makedirs(os.path.join(root, "images"), exist_ok=True)
    return number


def run_cases():
    results = []
    module = _load("check-advance-pin-today.py")
    hero_to_webp = _load("hero-to-webp.py")
    original = {key: getattr(module, key) for key in (
        "CALENDAR_PATH", "PINS_DIR", "PIN_IMAGES_DIR", "POSTED_LEDGER_PATH", "POSTS_DIR", "DRAFTS_DIR")}

    def case(description, ok, detail):
        results.append((description, ok, detail))

    def fresh():
        root = tempfile.mkdtemp(prefix="advance_pin_test_")
        last = _base(root)
        _point(module, root)
        return root, last

    roots = []
    try:
        # --- 1. 候補あり → NEXT（山が近い順 → 先行ピンが少ない順 → slug昇順） ---
        root, last = fresh()
        roots.append(root)
        code, out = _run(module, ["--date", TARGET_DAY])
        case("1-a. 候補あり → ADVANCE_PIN_NEXT・同じ山なら slug の昇順で先頭",
             code == 0 and out.startswith("ADVANCE_PIN_NEXT slug=event-june peak=06-01 残り27日"), out.strip())

        # 過去に先行ピンが1件ある記事は、同じ山の記事より後ろへ回る（15日前＝除外期間の外）
        _pin(root, "2031-04-20", last + 1, "event-june", 4, "ポイント整理", advance="2031-04-20")
        _posted(root, range(9001, last + 2))
        code, out = _run(module, ["--date", TARGET_DAY])
        case("1-b. 先行ピンが少ない記事が先（15日前に作成済みの記事は候補に残るが後ろへ回る）",
             out.startswith("ADVANCE_PIN_NEXT slug=event-june-b "), out.strip())

        # --- 2. 14日以内に先行ピンを作った slug は候補から外れる ---
        _pin(root, "2031-04-25", last + 2, "event-june-b", 4, "ポイント整理", advance="2031-04-25")
        _posted(root, range(9001, last + 3))
        code, out = _run(module, ["--date", TARGET_DAY])
        case("2-a. 10日前に先行ピンを作った slug は外れ、残りの候補が出る",
             out.startswith("ADVANCE_PIN_NEXT slug=event-june "), out.strip())
        _pin(root, "2031-04-30", last + 3, "event-june", 5, "チェックリスト", advance="2031-04-30")
        _posted(root, range(9001, last + 4))
        code, out = _run(module, ["--date", TARGET_DAY])
        case("2-b. 候補がすべて14日以内に作成済み → ADVANCE_PIN_NONE（理由つき）",
             out.startswith("ADVANCE_PIN_NONE ") and "直近14日以内" in out, out.strip())

        # --- 3. 山が窓に入らない日付 → NONE ---
        code, out = _run(module, ["--date", "2031-01-20"])
        case("3. 山が21〜60日先に無い日付 → ADVANCE_PIN_NONE",
             out.startswith("ADVANCE_PIN_NONE ") and "来る記事がありません" in out, out.strip())

        # --- 4. 当日の先行ピン: md だけ／画像なし／未投稿 → INCOMPLETE、そろえば DONE ---
        root, last = fresh()
        roots.append(root)
        pin_num = last + 1
        _pin(root, TARGET_DAY, pin_num, "event-june", 4, "ポイント整理", advance=TARGET_DAY)
        code, out = _run(module, ["--date", TARGET_DAY])
        case("4-a. mdだけ（画像なし・未投稿） → ADVANCE_PIN_INCOMPLETE",
             out.startswith("ADVANCE_PIN_INCOMPLETE pin=%d " % pin_num)
             and "画像が未配置" in out and "未投稿" in out, out.strip())

        _posted(root, list(range(9001, last + 1)) + [pin_num])
        code, out = _run(module, ["--date", TARGET_DAY])
        case("4-b. 投稿済みだが画像が無い → ADVANCE_PIN_INCOMPLETE（画像が未配置）",
             out.startswith("ADVANCE_PIN_INCOMPLETE pin=%d " % pin_num)
             and "画像が未配置" in out and "未投稿" not in out, out.strip())

        _image(root, pin_num, hero_to_webp)
        _posted(root, range(9001, last + 1))
        code, out = _run(module, ["--date", TARGET_DAY])
        case("4-c. 画像あり・検査合格だが未投稿 → ADVANCE_PIN_INCOMPLETE（未投稿だけ）",
             out.startswith("ADVANCE_PIN_INCOMPLETE pin=%d " % pin_num)
             and "未投稿" in out and "画像が未配置" not in out and "検査がNG" not in out, out.strip())

        code, verify_out = _run(module, ["--verify", "--date", TARGET_DAY])
        case("4-d. --verify が合格（終了コード0・ADVANCE_PIN_VERIFY_OK）",
             code == 0 and "ADVANCE_PIN_VERIFY_OK" in verify_out, verify_out.strip()[-300:])

        _posted(root, list(range(9001, last + 1)) + [pin_num])
        code, out = _run(module, ["--date", TARGET_DAY])
        case("4-e. 画像あり・検査合格・投稿済み → ADVANCE_PIN_DONE",
             out.strip() == "ADVANCE_PIN_DONE pin=%d" % pin_num, out.strip())

        # 検査がNGになる先行ピン（先頭文言が疑問形・この記事の他のピンと同じ型・枝番が -03）
        root, last = fresh()
        roots.append(root)
        pin_num = last + 1
        _pin(root, TARGET_DAY, pin_num, "event-far", 3, "写真ヒーロー", advance=TARGET_DAY, head="どれを選ぶ？")
        _image(root, pin_num, hero_to_webp)
        _posted(root, list(range(9001, last + 1)) + [pin_num])
        code, out = _run(module, ["--date", TARGET_DAY])
        case("4-f. 画像あり・投稿済みでも検査がNG → ADVANCE_PIN_INCOMPLETE（検査がNG）",
             out.startswith("ADVANCE_PIN_INCOMPLETE pin=%d " % pin_num) and "検査がNG" in out, out.strip())
        code, verify_out = _run(module, ["--verify", "--date", TARGET_DAY])
        case("4-g. --verify が不合格（終了コード1・疑問形／型の重複／枝番を指摘）",
             code == 1 and "疑問形" in verify_out and "同じ型" in verify_out and "枝番" in verify_out,
             verify_out.strip()[-300:])

        # --- 5. 対象日に公開した記事は候補にしない／台帳に行が無い記事の検知 ---
        root, last = fresh()
        roots.append(root)
        _post(root, "event-june", "seasons", TARGET_DAY)
        _post(root, "new-seasonal", "seasons", "2031-02-01")
        code, out = _run(module, ["--date", TARGET_DAY])
        case("5-a. 対象日に公開した記事は候補にせず、次の候補を出す",
             out.startswith("ADVANCE_PIN_NEXT slug=event-june-b "), out.strip())
        case("5-b. 台帳に行の無い seasons 記事 → ADVANCE_PIN_CALENDAR_MISSING",
             "ADVANCE_PIN_CALENDAR_MISSING slug=new-seasonal" in out, out.strip())

        # --- 6. --since/--until は各日1行＋集計1行 ---
        code, out = _run(module, ["--since", "2031-05-04", "--until", "2031-05-06"])
        lines = out.strip().splitlines()
        case("6. --since/--until → 各日1行と ADVANCE_PIN_PERIOD の集計1行",
             len(lines) == 4 and lines[0].startswith("2031-05-04 ADVANCE_PIN_")
             and lines[3].startswith("ADVANCE_PIN_PERIOD ") and "3日／3日" in lines[3], out.strip())

        # --- 7. --require-row ---
        _write(os.path.join(root, "drafts", "draft-seasons-norow.md"),
               "---\ntitle: ダミー\ncategory: seasons\nstatus: draft\n---\n")
        _write(os.path.join(root, "drafts", "draft-howto.md"),
               "---\ntitle: ダミー\ncategory: how-to\nstatus: draft\n---\n")
        code, out = _run(module, ["--require-row", "draft-seasons-norow"])
        case("7-a. seasons の下書きで台帳に行が無い → 終了コード1", code == 1 and "[NG]" in out, out.strip())
        code, out = _run(module, ["draft-howto", "--require-row"])
        case("7-b. seasons・gift 以外は対象外 → 終了コード0（<slug> --require-row の順でも可）",
             code == 0, out.strip())
        code, out = _run(module, ["--require-row", "generic-gift"])
        case("7-c. 行がある既存記事（peaks が - でも可） → 終了コード0", code == 0, out.strip())
    finally:
        for key, value in original.items():
            setattr(module, key, value)
        for root in roots:
            shutil.rmtree(root, ignore_errors=True)
    results.append(("一時ディレクトリの削除（%d件）" % len(roots),
                    not any(os.path.exists(r) for r in roots), ""))
    return results


def run_publish_dry_run_case():
    """publish-article.py <slug> --dry-run が、台帳に行の無い seasons の新規記事で中断することを確かめる。"""
    publish = _load("publish-article.py")
    publish.mark_daily_session = lambda: None  # 検証で record-lesson のセッションマーカーを作らない
    draft_path = os.path.join(publish.DRAFTS_DIR, "%s.md" % DUMMY_DRAFT_SLUG)
    if os.path.exists(draft_path):
        return [("publish-article.py --dry-run（ダミーの下書き）", False, "同名のファイルが既にあるため実行しない")]
    original_argv = sys.argv
    buffer = io.StringIO()
    try:
        _write(draft_path, "---\ntitle: 検証用のダミー\nslug: %s\ndate: 2031-05-05\ncategory: seasons\n"
                           "status: draft\n---\n検証用のダミーです。\n" % DUMMY_DRAFT_SLUG)
        sys.argv = [original_argv[0], DUMMY_DRAFT_SLUG, "--dry-run"]
        with contextlib.redirect_stdout(buffer):
            code = publish._run({"slug": None, "dry_run": False, "failed_check": None})
    finally:
        sys.argv = original_argv
        if os.path.exists(draft_path):
            os.remove(draft_path)
    out = buffer.getvalue()
    results = [
        ("8-a. 台帳に行の無い seasons の新規記事 → publish-article.py --dry-run が中断（終了コード1）",
         code == 1 and "NG  check-advance-pin-today.py %s --require-row" % DUMMY_DRAFT_SLUG in out,
         out.strip()[:400]),
        ("8-b. ダミーの下書き output/articles/%s.md を削除済み" % DUMMY_DRAFT_SLUG,
         not os.path.exists(draft_path), ""),
    ]

    # 台帳に行のある既存の gift 記事では、同じ経路で行チェックが通る（後続のチェックの成否は問わない）。
    if os.path.isfile(os.path.join(publish.DRAFTS_DIR, "%s.md" % EXISTING_GIFT_SLUG)):
        buffer = io.StringIO()
        try:
            sys.argv = [original_argv[0], EXISTING_GIFT_SLUG, "--dry-run"]
            with contextlib.redirect_stdout(buffer):
                code = publish._run({"slug": None, "dry_run": False, "failed_check": None})
        finally:
            sys.argv = original_argv
        out = buffer.getvalue()
        results.append((
            "8-c. 台帳に行のある既存記事（%s） → 行チェックは OK（--dry-run 全体の終了コード %d）"
            % (EXISTING_GIFT_SLUG, code),
            "OK  check-advance-pin-today.py %s --require-row" % EXISTING_GIFT_SLUG in out,
            "\n" + out.strip()))
    return results


def run_growth_ledger_case():
    """codex-gateway.py の growth-audit が、本物の growth/ledger/adopted-directives.tsv から
    先行ピンの指示（GD-0009・GD-0035）を読めることを確かめる。

    gateway の読み取り関数をそのまま呼ぶだけで、Codex も外部APIも起動しない。週次の --dry-run は
    入力ファイルの生成（外部APIの読み取りと手元ビルド）を伴うため、ここでは使わない。
    """
    gateway = _load("codex-gateway.py")
    since, until, week = "2026-10-12", "2026-10-18", "2026-W42"
    rows = {(row.get("ID") or "").strip(): row for row in gateway._ledger_adopted_rows()}
    plan = gateway._weekly_compliance_plan(since, until, week)
    assigned = {gd["id"]: gd for gd in plan["gds"]}
    results = [("9-a. 台帳の採用・一部採用の行に GD-0009・GD-0035 がある",
                "GD-0009" in rows and "GD-0035" in rows, "採用・一部採用 %d行" % len(rows))]
    for gd_id in ("GD-0009", "GD-0035"):
        gd = assigned.get(gd_id)
        kinds = "・".join(kind for kind, _ranges in gd["specs"]) if gd else ""
        results.append((
            "9-b. %s が週次（%s〜%s）の遵守確認へ配られる（判定対象・対象開始を読める）" % (gd_id, since, until),
            gd is not None and gd["start"][0] == "date",
            "判定対象の種別=%s／対象開始=%s" % (kinds, gateway._gd_start_label(gd["start"]))
            if gd else "事前判定: %s" % (plan["prefilled"].get(gd_id),)))
    gd = assigned.get("GD-0035")
    results.append(("9-c. GD-0035 の対象開始が 2026-10-12・判定方法に check-advance-pin-today.py がある",
                    gd is not None and gd["start"] == ("date", "2026-10-12")
                    and "check-advance-pin-today.py --since" in (gd["row"].get("判定方法") or ""), ""))
    if gd is not None:
        block = gateway._format_directives_block(plan, {"GD-0035": ["（検証用の該当）"]})
        results.append(("9-d. 区切りのプロンプトへ差し込む GD-0035 の割り当てを組み立てられる",
                        "check-advance-pin-today.py" in block, "\n" + block))
    return results


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    failures = []
    total = 0
    for title, cases in (
        ("check-advance-pin-today.py の判定（一時ディレクトリのダミーで実行）", run_cases()),
        ("publish-article.py の新規公開の経路（ダミーの下書きを作って消す）", run_publish_dry_run_case()),
        ("codex-gateway.py の growth-audit が台帳を読み込める（Codex・外部APIは起動しない）",
         run_growth_ledger_case()),
    ):
        print("=== %s ===" % title)
        for description, ok, detail in cases:
            total += 1
            if not ok:
                failures.append(description)
            print("[%s] %s%s" % ("OK" if ok else "NG", description, " — %s" % detail if detail else ""))
        print()
    if failures:
        print("失敗: %d件 / 全%d件" % (len(failures), total))
        for description in failures:
            print("  - %s" % description)
        sys.exit(1)
    print("全%d件のテストにパスしました。" % total)


if __name__ == "__main__":
    main()
