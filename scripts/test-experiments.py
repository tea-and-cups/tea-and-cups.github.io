# -*- coding: utf-8 -*-
r"""実験の台帳（experiments.py）と、週次 gateway の実験入力のテスト（S-0027 ①）。

本物の data/experiments.tsv・data/pin-daily-metrics.tsv・growth/・外部API・Codex には触れない。
一時ディレクトリに作ったダミーの台帳・提案ブロック（audit.md）・ピン日次 TSV へ experiments.py の
読み込み先を差し替え、Buffer の取得（fetch_sent_posts）をダミーの投稿を返す関数へ差し替えて、
experiments.py の関数をそのまま呼ぶ（テスト側で判定を再実装しない）。一時ディレクトリは終了時に必ず消す。

確かめること:
  1. 採用 → 実行中 → 集計 → 判定案（継続／戻し／延長）→ 戻しで設定値が既定に戻る／標準で設定値が残る
  2. 判定までの日数の下限・KEYS に無い設定キーの拒否（台帳は書き換わらない）
  3. 範囲の当てはめ（pin>=・channel=・slug=）
  4. 延長の上限（1回）
  5. adopt --dry-run が台帳を書き換えないこと
  6. measure が Buffer を1回だけ取得し、pin-14d.json・sns-posts-7d.json の対象を正しく選ぶこと
  7. codex-gateway.py: measure が失敗したら3つの JSON を空の形で置いて続行する
  8. judge-due: 判定日が来た実験に判定案を記録する（設定の戻しで active_setting が既定に戻る・ルールの戻しは
     RULE_REVERT_NEEDED・同じ週末日の再実行で記録し直さない）／adopt の同じ対象の重複拒否（S-0027 ②）
  9. codex-gateway.py: 新しい必須節（足りない節があれば無効）・遵守確認の除去・judge-due の結果の受け取り

使い方:
  python site/scripts/test-experiments.py
"""

import contextlib
import datetime as dt
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ADOPT_DAY = dt.date(2026, 9, 1)     # 採用日（開始日は翌日 09-02）
WEEK_END = dt.date(2026, 9, 30)     # 判定日（09-23）を過ぎた週末日
KEY = "pin-hook-style"


def _load(file_name):
    spec = importlib.util.spec_from_file_location(
        file_name[:-3].replace("-", "_") + "_under_test", os.path.join(SCRIPT_DIR, file_name))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ex = _load("experiments.py")
gw = _load("codex-gateway.py")

FAILURES = []


def check(label, ok, detail=""):
    print("%s %s%s" % ("OK  " if ok else "NG  ", label, (" - %s" % detail) if detail and not ok else ""))
    if not ok:
        FAILURES.append(label)


def run(fn, *args, **kwargs):
    """experiments.py の cmd_* を呼び、拒否（ExperimentError）なら 1 を返す。標準出力は捨てる。"""
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            return fn(*args, **kwargs)
        except ex.ExperimentError:
            return 1


PROPOSALS = [
    # 提案番号 種別 対象 内容 設定キー 設定値 範囲 主指標 判定までの日数
    ("P-1", "設定", "pin-hook", "先頭の一言を問いかけにする", KEY, "問いかけ", "pin>=200", "pin-impr-14d", "21"),
    ("P-2", "設定", "pin-hook", "下限未満", KEY, "x", "pin>=200", "pin-impr-14d", "20"),
    ("P-3", "設定", "pin-hook", "未登録キー", "no-such-key", "x", "pin>=200", "pin-impr-14d", "21"),
    ("P-4", "ルール", "post-text", "Xの投稿文を短くする", "", "", "channel=twitter", "x-impr-7d", "14"),
    ("P-5", "設定", "image-style", "記事を絞った一言", KEY, "B", "slug=s-a,s-b", "pin-impr-14d", "21"),
    ("P-6", "設定", "x-standalone", "対象0件", KEY, "C", "pin>=900", "pin-impr-14d", "21"),
    ("P-7", "ルール", "post-text", "X下限未満", "", "", "channel=twitter", "x-impr-7d", "13"),
    ("P-8", "ルール", "search-ctr", "descriptionを書き直す", "-", "-", "slug=s-a", "gsc-ctr-28d", "28"),
    # S-0027 ②: 同じ対象の重複拒否
    ("P-10", "設定", "pin-hook", "同じ対象の別案", KEY, "D", "pin>=300", "pin-impr-14d", "21"),
    ("P-11", "ルール", "pin-hook", "同じ対象の別案（ルール）", "-", "-", "全体", "pin-impr-14d", "21"),
    ("P-12", "ルール", "post-text", "継続判定済みの対象への新案", "-", "-", "channel=twitter", "x-impr-7d", "14"),
]


def write_audit(path):
    lines = ["# 監査", "", "## 要約", "- ダミー", "", "## 新しい実験の提案", "", "```tsv",
             "\t".join(ex.PROPOSAL_COLUMNS)]
    lines += ["\t".join(p) for p in PROPOSALS]
    lines += ["```", "", "## 改善指示", "- なし", ""]
    Path(path).write_text("\n".join(lines), encoding="utf-8")


PIN_COLUMNS = ("pin_id", "pin_number", "created_at", "date", "data_status", "impressions", "article_slug",
               "duplicate_detected")


def write_pins(path):
    """開始日前のピン 190〜199（毎日10imp）／開始後のピン 200〜204（slug s-x・毎日20imp）／
    205・206（slug s-a・毎日5imp）／207（14日の途中に PROCESSING）／208（DELETED）。"""
    rows = []

    def pin(number, created, slug, imp, status_of=lambda i: "READY"):
        for i in range(20):
            day = created + dt.timedelta(days=i)
            rows.append(("id%d" % number, str(number), created.isoformat(), day.isoformat(), status_of(i),
                         str(imp), slug, "false"))

    for k, number in enumerate(range(190, 200)):
        pin(number, dt.date(2026, 8, 10) + dt.timedelta(days=k), "s-old", 10)
    for k, number in enumerate(range(200, 205)):
        pin(number, dt.date(2026, 9, 2) + dt.timedelta(days=k), "s-x", 20)
    pin(205, dt.date(2026, 9, 3), "s-a", 5)
    pin(206, dt.date(2026, 9, 3), "s-a", 5)
    pin(207, dt.date(2026, 9, 10), "s-y", 50, lambda i: "PROCESSING" if i == 5 else "READY")
    pin(208, dt.date(2026, 9, 10), "s-y", 50, lambda i: "DELETED" if i == 0 else "READY")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(PIN_COLUMNS) + "\n")
        for r in rows:
            f.write("\t".join(r) + "\n")


def _post(service, day, value, text="本文"):
    sent = dt.datetime.combine(day, dt.time(10, 0), tzinfo=ex.JST).astimezone(dt.timezone.utc)
    metric = "impressions" if service == "twitter" else "views"
    return {"service": service, "sent_at": sent.isoformat().replace("+00:00", "Z"), "text": text,
            "metrics": [{"type": metric, "value": value}, {"type": "reactions", "value": 1},
                        {"type": "clicks", "value": 2}]}


POSTS = ([_post("twitter", dt.date(2026, 8, 19) + dt.timedelta(days=i), 10) for i in range(0, 14, 2)]
         + [_post("twitter", dt.date(2026, 9, 2) + dt.timedelta(days=i), 30, "X投稿%d\n改行" % i) for i in range(0, 22, 3)]
         + [_post("threads", dt.date(2026, 9, 18), 4)])
FETCH_CALLS = []


def fake_fetch(since, until):
    FETCH_CALLS.append((since, until))
    return list(POSTS), None


def by_id(rows, ex_id):
    return next(r for r in rows if r["実験ID"] == ex_id)


def measure(out):
    FETCH_CALLS.clear()
    rc = run(ex.cmd_measure, WEEK_END, out)
    status = json.loads((Path(out) / "experiments-status.json").read_text(encoding="utf-8"))
    return rc, {e["id"]: e for e in status["experiments"]}, status


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    tmp = tempfile.mkdtemp(prefix="test-experiments-")
    try:
        ex.LEDGER = os.path.join(tmp, "experiments.tsv")
        ex.PIN_DAILY_METRICS_TSV = os.path.join(tmp, "pins.tsv")
        ex.PINS_DIR = os.path.join(tmp, "no-pins")
        ex.KEYS = (KEY,)
        real_narrow = ex.NARROW_EXPERIMENTS
        ex.NARROW_EXPERIMENTS = {}   # 以下の台帳の EX-0004/0005 は試験用の行。本物の絞り込み対象と取り違えない
        ex.fetch_sent_posts = fake_fetch
        ex.save_ledger([])
        audit = os.path.join(tmp, "audit.md")
        write_audit(audit)
        write_pins(ex.PIN_DAILY_METRICS_TSV)
        ledger_bytes = lambda: Path(ex.LEDGER).read_bytes()

        # --- 5. dry-run は台帳を書き換えない ---
        before = ledger_bytes()
        check("adopt --dry-run は終了コード0", run(ex.cmd_adopt, audit, ["P-1"], dry_run=True, today=ADOPT_DAY) == 0)
        check("adopt --dry-run は台帳を書き換えない", ledger_bytes() == before)

        # --- 2. 下限日数・未登録キーの拒否 ---
        check("pin-impr-14d の判定まで20日（下限21）は拒否", run(ex.cmd_adopt, audit, ["P-2"], today=ADOPT_DAY) == 1)
        check("x-impr-7d の判定まで13日（下限14）は拒否", run(ex.cmd_adopt, audit, ["P-7"], today=ADOPT_DAY) == 1)
        check("KEYS に無い設定キーは拒否", run(ex.cmd_adopt, audit, ["P-3"], today=ADOPT_DAY) == 1)
        check("拒否のあとも台帳は空のまま", ledger_bytes() == before)
        check("ブロックに無い提案番号は拒否", run(ex.cmd_adopt, audit, ["P-99"], today=ADOPT_DAY) == 1)

        # --- 1. 採用 → 実行中 ---
        check("adopt P-1 P-4 P-5 P-6 は終了コード0",
              run(ex.cmd_adopt, audit, ["P-1", "P-4", "P-5", "P-6"], today=ADOPT_DAY) == 0)
        rows = ex.load_ledger()
        check("採番は EX-0001〜EX-0004", [r["実験ID"] for r in rows] == ["EX-0001", "EX-0002", "EX-0003", "EX-0004"])
        r1 = by_id(rows, "EX-0001")
        check("設定は実行中で入り、開始日=採用日の翌日・判定日=開始日+21日",
              (r1["状態"], r1["開始日"], r1["判定日"], r1["延長"]) == ("実行中", "2026-09-02", "2026-09-23", "0"))
        check("ルールは実装待ちで入る", by_id(rows, "EX-0002")["状態"] == "実装待ち")
        check("同じ提案の二重採用は拒否", run(ex.cmd_adopt, audit, ["P-1"], today=ADOPT_DAY) == 1)
        check("start: 実装待ち→実行中（判定日は開始日+14日）",
              run(ex.cmd_start, "EX-0002", today=ADOPT_DAY) == 0
              and (by_id(ex.load_ledger(), "EX-0002")["状態"], by_id(ex.load_ledger(), "EX-0002")["判定日"])
              == ("実行中", "2026-09-16"))
        check("start: 実行中の行には使えない", run(ex.cmd_start, "EX-0001", today=ADOPT_DAY) == 1)

        # --- 3. 範囲の当てはめ ---
        check("pin>=200: 200 は当てはまる", ex.range_matches("pin>=200", pin=200))
        check("pin>=200: 199 は当てはまらない", not ex.range_matches("pin>=200", pin=199))
        check("pin>=200＋channel=twitter: twitter は当てはまる",
              ex.range_matches("pin>=200＋channel=twitter", pin=250, channel="twitter"))
        check("pin>=200＋channel=twitter: threads は当てはまらない",
              not ex.range_matches("pin>=200＋channel=twitter", pin=250, channel="threads"))
        check("slug=s-a,s-b: s-b は当てはまる", ex.range_matches("slug=s-a,s-b", slug="s-b"))
        check("slug=s-a,s-b: s-c は当てはまらない", not ex.range_matches("slug=s-a,s-b", slug="s-c"))
        check("値の無い次元の条件は当てはまらない（設定の適用）", not ex.range_matches("channel=twitter", pin=1))
        try:
            ex.parse_range("foo=1")
            check("不正な範囲は拒否", False)
        except ex.ExperimentError:
            check("不正な範囲は拒否", True)
        check("active_setting: pin=201 は EX-0001 の値", ex.active_setting(KEY, pin=201, default="既定") == "問いかけ")
        check("active_setting: pin=150 は既定", ex.active_setting(KEY, pin=150, default="既定") == "既定")
        check("active_setting: slug=s-a は新しい EX-0003 の値",
              ex.active_setting(KEY, pin=201, slug="s-a", default="既定") == "B")

        # --- 1. 集計 → 判定案 ---
        out = os.path.join(tmp, "out")
        rc, st, status = measure(out)
        check("measure は終了コード0で3つの JSON を書く",
              rc == 0 and all((Path(out) / n).is_file() for n in ("experiments-status.json", "pin-14d.json", "sns-posts-7d.json")))
        check("Buffer の取得は1回だけ", len(FETCH_CALLS) == 1, str(FETCH_CALLS))
        e1 = st.get("EX-0001", {})
        check("EX-0001（pin>=200 の確定7枚・後 280 ＞ 前 140）の判定案は継続",
              (e1.get("proposal"), e1.get("after", {}).get("median"), e1.get("before", {}).get("median"),
               e1.get("after", {}).get("count"), e1.get("before", {}).get("count"), e1.get("after", {}).get("pending"))
              == ("継続", 280, 140, 7, 7, 2), str(e1))
        e3 = st.get("EX-0003", {})
        check("EX-0003（slug=s-a・後 70 ≦ 前 140）の判定案は戻し",
              (e3.get("proposal"), e3.get("after", {}).get("count"), e3.get("before", {}).get("pins")) == ("戻し", 2, [198, 199]), str(e3))
        e2 = st.get("EX-0002", {})
        check("EX-0002（X・後 30 ＞ 前 10）の判定案は継続",
              (e2.get("proposal"), e2.get("before", {}).get("median"), e2.get("after", {}).get("median")) == ("継続", 10, 30), str(e2))
        e4 = st.get("EX-0004", {})
        check("EX-0004（対象0件・延長0）の判定案は延長", e4.get("proposal") == "延長", str(e4))
        pin14 = json.loads((Path(out) / "pin-14d.json").read_text(encoding="utf-8"))
        confirmed = {p["pin_number"]: p["impressions_14d"] for p in pin14["pins"]}
        pending = {p["pin_number"]: p["reason"] for p in pin14["pending"]}
        check("pin-14d.json: 直近4週（09-03〜）作成・14日確定のピンだけ",
              sorted(confirmed) == [201, 202, 203, 204, 205, 206] and confirmed[205] == 70, str(confirmed))
        check("pin-14d.json: PROCESSING・DELETED のピンは pending",
              pending.get(207, "").startswith("14日分に") and pending.get(208) == "DELETED", str(pending))
        sns = json.loads((Path(out) / "sns-posts-7d.json").read_text(encoding="utf-8"))
        check("sns-posts-7d.json: 送信日が週末日の13〜7日前（09-17〜09-23）の投稿だけ",
              sns["sent_window"] == ["2026-09-17", "2026-09-23"]
              and sorted((p["service"], p["views"]) for p in sns["posts"]) == [("threads", 4), ("twitter", 30), ("twitter", 30), ("twitter", 30)]
              and all("\n" not in p["text_head"] and p["reactions"] == 1 and p["clicks"] == 2 for p in sns["posts"]), str(sns))

        # --- 4. 延長の上限 ---
        check("judge 延長（1回目）は通り、判定日が7日延びる",
              run(ex.cmd_judge, "EX-0004", "延長", "対象0件", today=WEEK_END) == 0
              and (by_id(ex.load_ledger(), "EX-0004")["延長"], by_id(ex.load_ledger(), "EX-0004")["判定日"]) == ("1", "2026-09-30"))
        _rc, st, _s = measure(out)
        check("延長1でも0件なら判定案は戻し", st.get("EX-0004", {}).get("proposal") == "戻し", str(st.get("EX-0004")))
        check("judge 延長（2回目）は拒否", run(ex.cmd_judge, "EX-0004", "延長", "再延長", today=WEEK_END) == 1)

        # --- 1. 戻し・標準 ---
        check("judge EX-0001 戻し", run(ex.cmd_judge, "EX-0001", "戻し", "テスト", today=WEEK_END) == 0)
        check("戻しで設定値は既定に戻る", ex.active_setting(KEY, pin=201, default="既定") == "既定")
        check("judge EX-0003 継続（設定）→ 標準", run(ex.cmd_judge, "EX-0003", "継続", "テスト", today=WEEK_END) == 0
              and by_id(ex.load_ledger(), "EX-0003")["状態"] == "標準")
        check("標準で設定値は残る", ex.active_setting(KEY, slug="s-a", default="既定") == "B")
        check("judge EX-0002 継続（ルール）は判定欄に継続と記録し、状態は実行中のまま",
              run(ex.cmd_judge, "EX-0002", "継続", "テスト", today=WEEK_END) == 0
              and (by_id(ex.load_ledger(), "EX-0002")["状態"], by_id(ex.load_ledger(), "EX-0002")["判定"])
              == ("実行中", "継続 2026-09-30"))
        _rc, st, _s = measure(out)
        check("判定済み（戻し・標準・継続）の実験は集計しない", sorted(st) == ["EX-0004"], str(sorted(st)))
        check("判定済みの行への再判定は拒否", run(ex.cmd_judge, "EX-0001", "継続", "再", today=WEEK_END) == 1)
        # --- CTR（同じページの開始前28日と開始後28日） ---
        gsc_calls = []

        def fake_gsc(since, until):
            gsc_calls.append((since.isoformat(), until.isoformat()))
            before_window = until < dt.date(2026, 9, 2)
            return ({"s-a": {"ctr": 0.02 if before_window else 0.04},
                     "s-z": {"ctr": 0.05 if before_window else 0.01}}, None)

        ex.fetch_gsc_by_page = fake_gsc
        check("adopt P-8（search-ctr）→ start", run(ex.cmd_adopt, audit, ["P-8"], today=ADOPT_DAY) == 0
              and run(ex.cmd_start, "EX-0005", today=ADOPT_DAY) == 0)
        _rc, st, _s = measure(out)
        e5 = st.get("EX-0005", {})
        check("CTR: slug=s-a だけを前後で比べ（0.04 ＞ 0.02）判定案は継続",
              (e5.get("proposal"), e5.get("before", {}).get("median"), e5.get("after", {}).get("median"),
               e5.get("after", {}).get("pages")) == ("継続", 0.02, 0.04, ["s-a"])
              and gsc_calls == [("2026-08-05", "2026-09-01"), ("2026-09-02", "2026-09-29")], "%s %s" % (e5, gsc_calls))
        check("台帳は LF・ヘッダーつき",
              b"\r\n" not in ledger_bytes() and ledger_bytes().decode("utf-8").startswith("\t".join(ex.COLUMNS) + "\n"))

        # --- 7. gateway: measure の失敗で空の形を置く ---
        gw_dir = Path(tmp) / "gw-inputs"
        gw_dir.mkdir()
        gw.EXPERIMENTS_SCRIPT = Path(tmp) / "no-such-experiments.py"
        with contextlib.redirect_stderr(io.StringIO()) as err:
            result = gw._prepare_experiment_inputs(gw_dir, "2026-09-30")
        empties = [json.loads((gw_dir / n).read_text(encoding="utf-8")) for n, _note in result]
        check("gateway: measure 失敗でも3つの JSON を空の形で置く",
              [n for n, _ in result] == ["experiments-status.json", "pin-14d.json", "sns-posts-7d.json"]
              and all(d.get("status") == "unavailable" for d in empties)
              and empties[0]["experiments"] == [] and empties[1]["pins"] == [] and empties[2]["posts"] == [])
        check("gateway: 【注意】を出す", err.getvalue().count("【注意】") == 3)

        # --- 8. judge-due（判定日が来た実験の自動記録）と同じ対象の重複拒否（S-0027 ②） ---
        ex.save_ledger([])
        ex.fetch_gsc_by_page = lambda since, until: (
            {"s-a": {"ctr": 0.04 if until < dt.date(2026, 9, 2) else 0.02}}, None)
        check("重複拒否: 対象がすべて違う adopt P-1 P-5 P-6 P-8 P-4 は終了コード0",
              run(ex.cmd_adopt, audit, ["P-1", "P-5", "P-6", "P-8", "P-4"], today=ADOPT_DAY) == 0)
        rows = ex.load_ledger()
        check("ルールの設定キー・設定値の「-」は空欄で入る",
              (by_id(rows, "EX-0004")["設定キー"], by_id(rows, "EX-0004")["設定値"]) == ("", ""))
        before = ledger_bytes()
        check("重複拒否: 実行中の同じ対象（pin-hook・EX-0001）への adopt P-10 は終了コード1",
              run(ex.cmd_adopt, audit, ["P-10"], today=ADOPT_DAY) == 1)
        check("重複拒否: 実装待ちの同じ対象（post-text・EX-0005）への adopt P-12 は終了コード1",
              run(ex.cmd_adopt, audit, ["P-12"], today=ADOPT_DAY) == 1)
        check("重複拒否のあと台帳は変わらない", ledger_bytes() == before)
        run(ex.cmd_start, "EX-0004", today=ADOPT_DAY)
        run(ex.cmd_start, "EX-0005", today=ADOPT_DAY)
        check("judge-due 前: slug=s-a の設定値は実行中の EX-0002 の B",
              ex.active_setting(KEY, slug="s-a", default="既定") == "B")
        out_due = os.path.join(tmp, "out-due")
        _rc, _st, status = measure(out_due)
        status_path = os.path.join(out_due, "experiments-status.json")
        check("experiments-status.json に busy_targets（提案できない対象）が載る",
              sorted(status.get("busy_targets", {})) == sorted(["pin-hook", "image-style", "x-standalone",
                                                               "search-ctr", "post-text"]), str(status.get("busy_targets")))
        before = ledger_bytes()
        check("judge-due: status の週末日と --week-end が違えば拒否（台帳は変わらない）",
              run(ex.cmd_judge_due, dt.date(2026, 10, 1), status_path, today=WEEK_END) == 1 and ledger_bytes() == before)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = ex.cmd_judge_due(WEEK_END, status_path, today=WEEK_END)
        text = buf.getvalue()
        rows = ex.load_ledger()
        r1, r2, r3, r4, r5 = (by_id(rows, "EX-000%d" % i) for i in range(1, 6))
        check("judge-due は終了コード0で5件を記録する",
              rc == 0 and "JUDGE_DUE_DONE week_end=2026-09-30 judged=5 rule_revert_needed=1 errors=0" in text, text)
        check("継続（設定）→ 標準・根拠は「中央値 前140 後280 件数7/7」",
              (r1["状態"], r1["判定"]) == ("標準", "継続 2026-09-30")
              and "judge-due（週末日 2026-09-30）: 中央値 前140 後280 件数7/7" in r1["根拠"], r1["根拠"])
        check("戻し（設定）→ 状態は戻し", r2["状態"] == "戻し", str(r2))
        check("設定型の戻しで active_setting は既定に戻る", ex.active_setting(KEY, slug="s-a", default="既定") == "既定")
        check("延長 → 延長1・判定日が7日延びる・根拠に件数0と理由",
              (r3["状態"], r3["延長"], r3["判定日"]) == ("実行中", "1", "2026-09-30")
              and "件数0/0（対象が0件" in r3["根拠"], str(r3))
        check("ルール型の戻し → 状態は戻し・RULE_REVERT_NEEDED EX-0004 を出す",
              r4["状態"] == "戻し" and "RULE_REVERT_NEEDED EX-0004" in text, text)
        check("ルール型の継続 → 実行中のまま判定欄に継続（RULE_REVERT_NEEDED は出さない）",
              (r5["状態"], r5["判定"]) == ("実行中", "継続 2026-09-30") and "RULE_REVERT_NEEDED EX-0005" not in text)
        before = ledger_bytes()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = ex.cmd_judge_due(WEEK_END, None, today=WEEK_END)
        check("同じ週末日の再実行（--status なし）は記録し直さない（延長後も判定日が週末日以前の EX-0003 を飛ばす）",
              rc == 0 and ledger_bytes() == before and "JUDGE_DUE_SKIP EX-0003" in buf.getvalue(), buf.getvalue())
        check("1回の adopt で同じ対象（pin-hook）が2件なら拒否", run(ex.cmd_adopt, audit, ["P-10", "P-11"], today=ADOPT_DAY) == 1
              and ledger_bytes() == before)
        check("標準になった対象（pin-hook）には新しい実験を採用できる", run(ex.cmd_adopt, audit, ["P-10"], today=ADOPT_DAY) == 0)
        check("継続判定済み（標準化待ち）のルールの対象（post-text）には新しい実験を採用できる",
              run(ex.cmd_adopt, audit, ["P-12"], today=ADOPT_DAY) == 0)

        # --- 9. gateway: 新しい必須節（足りない節があれば無効）と judge-due の呼び出し（S-0027 ②） ---
        def section_check(headers, required):
            path = Path(tmp) / "audit-check.md"
            path.write_text("\n\n".join("%s\n- ダミー" % h for h in headers) + "\n", encoding="utf-8")
            ok, info = gw._make_check(path, time.time() - 5, required, {"written_by": None})("")
            return ok, info.get("reason")

        weekly = gw.REQUIRED_SUMMARY_SECTIONS_BY_MODE["weekly"]
        monthly = gw.REQUIRED_SUMMARY_SECTIONS_BY_MODE["monthly"]
        check("gateway: 週次まとめの必須節は 要約・実験の判定・新しい実験の提案・誠実さの重大な指摘・評価できなかったもの",
              weekly == ("## 要約", "## 実験の判定", "## 新しい実験の提案", "## 誠実さの重大な指摘", "## 評価できなかったもの"))
        check("gateway: 月次まとめは週次の5節＋到達数の振り返り・来月のチャネル配分・前月の作業キューの結果・"
              "来月の作業キュー案・サイト改善の提案・監査範囲（この順・2026-11-01）",
              monthly == weekly + ("## 到達数の振り返り", "## 来月のチャネル配分", "## 前月の作業キューの結果",
                                   "## 来月の作業キュー案", "## サイト改善の提案", "## 監査範囲"))
        check("gateway: 区切りの必須節は 所見・部分監査範囲 だけ（遵守確認（部分）は無い）",
              gw.REQUIRED_PART_SECTIONS_BY_MODE == {"weekly": ("## 所見", "## 部分監査範囲"),
                                                    "monthly": ("## 所見", "## 部分監査範囲")})
        check("gateway: 週次の5節がそろったダミーは有効", section_check(weekly, weekly) == (True, "ok"))
        for missing in weekly:
            check("gateway: 週次で %s が無いダミーは無効" % missing,
                  section_check([h for h in weekly if h != missing], weekly) == (False, "missing_sections"))
        check("gateway: 旧形式（改善指示・遵守確認）の週次ダミーは無効",
              section_check(("## 要約", "## 改善指示", "## 前回採用した指示の遵守確認", "## 評価できなかったもの",
                             "## 成長の判断に足りなかった情報"), weekly) == (False, "missing_sections"))
        check("gateway: 月次の11節がそろったダミーは有効", section_check(monthly, monthly) == (True, "ok"))
        for missing in monthly[len(weekly):]:
            check("gateway: 月次で %s が無いダミーは無効" % missing,
                  section_check([h for h in monthly if h != missing], monthly) == (False, "missing_sections"))
        mprompt = (Path(gw.PROJECT_ROOT) / "growth" / "prompts" / "monthly-audit.md").read_text(encoding="utf-8")
        check("gateway: 月次まとめのプロンプトは11節をこの順で指示し、作業キューのタグを CTR改修・新規記事執筆 に限る",
              "要約・実験の判定・新しい実験の提案・誠実さの重大な指摘・評価できなかったもの・到達数の振り返り・" in mprompt
              and "来月のチャネル配分・前月の作業キューの結果・来月の作業キュー案・サイト改善の提案・監査範囲" in mprompt
              and "CTR改修 か 新規記事執筆 のどちらか" in mprompt and "誠実さの修正は、この表に入れない" in mprompt
              and "Q番号\tタグ\tslug\tcategory\tGD番号\t内容\t対象指標\t根拠" in mprompt)
        check("gateway: 遵守確認の台帳を読む定数・関数が残っていない",
              not any(hasattr(gw, n) for n in ("GROWTH_LEDGER_PATH", "_ledger_adopted_rows", "_check_compliance",
                                               "_weekly_compliance_plan")))
        prompt = (Path(gw.PROJECT_ROOT) / "growth" / "prompts" / "weekly-audit.md").read_text(encoding="utf-8")
        built = gw._build_summary_prompt(prompt, Path(tmp) / "parts", [{"name": "R-1"}], "2026-10-12", "2026-10-18")
        check("gateway: 週次まとめのプロンプトに期間が入り、{{COMPLIANCE}} が残らず、3つの JSON を案内する",
              "2026-10-12〜2026-10-18" in built and "{{" not in built.replace("{{WEEK}}", "").replace("{{INPUT_DIR}}", "")
              and all(n in built for n in ("experiments-status.json", "pin-14d.json", "sns-posts-7d.json",
                                           "gsc-page-28d.json")))
        fake = Path(tmp) / "fake-experiments.py"
        fake.write_text("import sys\nprint('JUDGED EX-0009 戻し\\tx')\nprint('RULE_REVERT_NEEDED EX-0009')\n"
                        "sys.exit(int(sys.argv[-1] == 'fail'))\n", encoding="utf-8")
        gw.EXPERIMENTS_SCRIPT = fake
        result = gw._run_judge_due("2026-09-30", Path(tmp) / "no-status.json")
        check("gateway: judge-due の結果（RULE_REVERT_NEEDED の実験ID）を judge_due に載せる",
              result["ok"] and result["rule_revert_needed"] == ["EX-0009"] and len(result["lines"]) == 2, str(result))
        fake.write_text("import sys\nsys.stderr.write('boom')\nsys.exit(1)\n", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            result = gw._run_judge_due("2026-09-30", Path(tmp) / "no-status.json")
        check("gateway: judge-due が失敗しても例外にせず ok=false と【注意】を返す",
              not result["ok"] and result["returncode"] == 1 and "【注意】" in err.getvalue(), str(result))

        # --- 絞り込んだ値（EX-0004 の image-style・EX-0005 の post-text・D-0317） ---
        ex.NARROW_EXPERIMENTS = real_narrow
        md_dir = Path(tmp) / "pins-md"
        md_dir.mkdir()

        def put_md(number, style, count):
            text = "# ピン%d\n- 型: %s\n- テキストオーバーレイ: 「a」「b」（%s件）\n" % (number, style, count)
            (md_dir / ("2026-09-01-pin-%d-s-x-01.md" % number)).write_text(text, encoding="utf-8")

        for number, style, count in ((195, "比較グリッド", 2), (196, "比較グリッド", 3), (197, "写真ヒーロー", 1),
                                     (200, "比較グリッド", 3), (201, "比較グリッド", 2), (202, "チェックリスト", 3),
                                     (203, "比較グリッド", 3)):
            put_md(number, style, count)
        ex.PINS_DIR = str(md_dir)
        md = ex.load_pin_md_info()
        check("ピンmdの「- 型:」と「（N件」を読む", md.get(196) == ("比較グリッド", 3) and md.get(197) == ("写真ヒーロー", 1), str(md))
        pins = ex.load_pins(ex.PIN_DAILY_METRICS_TSV)
        row_pin = {"実験ID": "EX-0004", "対象": "image-style", "範囲": "pin>=200", "開始日": "2026-09-02", "判定日": "2026-09-23", "延長": "0"}
        n = ex._narrow_pin(row_pin, pins, WEEK_END, md)
        check("EX-0004: 後は比較グリッドかつ3件のピン（200・203）だけ・前は開始前の比較グリッドのピン",
              (n["after"]["pins"], n["after"]["median"], n["before"]["pins"], n["before"]["median"], n["basis_before"])
              == ([200, 203], 280, [195, 196], 140, "比較グリッドのピン"), str(n))
        md_no_grid = {k: v for k, v in md.items() if k < 200}
        md_no_grid = {k: ("写真ヒーロー", 1) for k in md_no_grid}
        md_no_grid.update({200: ("比較グリッド", 3), 203: ("比較グリッド", 3)})
        n2 = ex._narrow_pin(row_pin, pins, WEEK_END, md_no_grid)
        check("EX-0004: 開始前に比較グリッドのピンが無ければ直近の全ピンを前にする",
              (n2["before"]["pins"], n2["basis_before"].startswith("直近の全ピン")) == ([198, 199], True), str(n2))
        check("EX-0004: 条件の文に pin>=200・比較グリッド・3件が出る",
              all(w in n["condition"] for w in ("pin>=200", "比較グリッド", "3件")), n["condition"])
        row_post = {"実験ID": "EX-0005", "対象": "post-text", "範囲": "channel=twitter＋pin>=398", "主指標": "x-impr-7d", "開始日": "2026-09-02",
                    "判定日": "2026-09-16", "延長": "0"}
        url = "\nhttps://k.example/posts/s/?utm_source=x&utm_content=pin%d"
        sample = [_post("twitter", dt.date(2026, 9, 3), 40, "新型" + url % 398),
                  _post("twitter", dt.date(2026, 9, 4), 99, "旧型" + url % 397),
                  _post("twitter", dt.date(2026, 9, 5), 60, "新型" + url % 400),
                  _post("twitter", dt.date(2026, 9, 6), 77, "リンクなし #タグ"),
                  _post("threads", dt.date(2026, 9, 5), 88, "x" + url % 500)]
        np = ex._narrow_posts(row_post, sample, WEEK_END, [10, 10])
        check("EX-0005: 後は utm_content が pin398 以上の X 投稿だけ（40・60 → 中央値50）",
              (np["after"]["count"], np["after"]["median"], np["before"]["median"]) == (2, 50, 10), str(np))
        empty = ex._empty_narrowed(row_post, "開始日前")
        check("開始前でも絞り込み条件が出る（後0件・pin398 を含む）",
              empty["after"]["count"] == 0 and "pin398" in empty["condition"], str(empty))
        entry = {"proposal": "継続", "reason": "r", "before": {"median": 10, "count": 2}, "after": {"median": 30, "count": 3},
                 "narrowed": {"before": {"median": 10, "count": 2}, "after": {"median": 50, "count": 2}}}
        text = ex._due_reason(entry, dt.date(2026, 9, 30))
        check("judge-due の根拠は絞り込んだ値が本体・全体の値が「参考」",
              "中央値 前10 後50 件数2/2" in text and text.endswith("；参考: 全体 中央値 前10 後30"), text)

        # --- 判定案は絞り込んだ前後で決める（EX-0004・EX-0005）。EX-0001〜0003 型の行は全体の値のまま ---
        def synth_pin(number, created, imp, style=None, count=3):
            days = {created + dt.timedelta(days=i): ("READY", imp) for i in range(20)}
            if style:
                put_md(number, style, count)
            return {"pin_id": "i%d" % number, "slug": "s-n", "created": created, "created_source": "created_at",
                    "days": days, "deleted": False, "duplicate": False}

        sp = {}
        for k, number in enumerate((601, 602)):    # 開始前の比較グリッド（100）
            sp[number] = synth_pin(number, dt.date(2026, 8, 20) + dt.timedelta(days=k), 100, "比較グリッド", 2)
        for k, number in enumerate((603, 604, 605, 606)):    # 開始前のほかの型（200）
            sp[number] = synth_pin(number, dt.date(2026, 8, 22) + dt.timedelta(days=k), 200, "チェックリスト")
        for k, number in enumerate((610, 611)):    # 開始後の比較グリッド3件（300）
            sp[number] = synth_pin(number, dt.date(2026, 9, 2) + dt.timedelta(days=k), 300, "比較グリッド", 3)
        for k, number in enumerate((612, 613, 614, 615)):    # 開始後のほかの型（10）
            sp[number] = synth_pin(number, dt.date(2026, 9, 2) + dt.timedelta(days=k), 10, "チェックリスト")

        def led(ex_id, target, rng, metric):
            r = {c: "" for c in ex.COLUMNS}
            r.update({"実験ID": ex_id, "状態": "実行中", "種別": "ルール", "対象": target, "範囲": rng, "主指標": metric,
                      "開始日": "2026-09-02", "判定日": "2026-09-16", "延長": "0"})
            return r

        sp_posts = ([_post("twitter", dt.date(2026, 8, 20) + dt.timedelta(days=i), 100, "旧") for i in range(3)]
                    + [_post("twitter", dt.date(2026, 9, 3), 300, "新型" + url % 400),
                       _post("twitter", dt.date(2026, 9, 4), 300, "新型" + url % 401)]
                    + [_post("twitter", dt.date(2026, 9, 5) + dt.timedelta(days=i), 5, "旧型" + url % 397) for i in range(3)]
                    + [_post("twitter", dt.date(2026, 9, 8) + dt.timedelta(days=i), 5, "リンクなし") for i in range(2)])
        rows_n = [led("EX-0004", "image-style", "pin>=610", "pin-impr-14d"),
                  led("EX-0005", "post-text", "channel=twitter＋pin>=398", "x-impr-7d"),
                  led("EX-0007", "pin-hook", "pin>=610", "pin-impr-14d"),
                  led("EX-0008", "x-standalone", "channel=twitter", "x-impr-7d")]
        exps, _pending = ex.build_status(rows_n, WEEK_END, sp, sp_posts, [])
        st_n = {e["id"]: e for e in exps}
        a = st_n["EX-0004"]
        check("全体が戻し・絞り込みが継続 → EX-0004 の判定案は継続（全体の案は whole_proposal に残る）",
              (a["whole_proposal"]["proposal"], a["narrowed"]["proposal"], a["proposal"]) == ("戻し", "継続", "継続"), str(a))
        check("EX-0004: 絞り込みの前後は 1400／4200（ピンの14日合計。全体は 2800／140）",
              (a["narrowed"]["before"]["median"], a["narrowed"]["after"]["median"], a["before"]["median"], a["after"]["median"])
              == (1400, 4200, 2800, 140), str(a))
        b = st_n["EX-0005"]
        check("全体が戻し・絞り込みが継続 → EX-0005 の判定案は継続",
              (b["whole_proposal"]["proposal"], b["proposal"], b["narrowed"]["after"]["median"], b["after"]["median"])
              == ("戻し", "継続", 300, 5), str(b))
        row_zero = led("EX-0004", "image-style", "pin>=612", "pin-impr-14d")
        exps_z, _p = ex.build_status([row_zero], WEEK_END, sp, sp_posts, [])
        c = exps_z[0]
        check("絞り込んだ「後」が0件（全体の後には4枚ある）→ 既存の0件の扱い（延長）",
              (c["after"]["count"], c["narrowed"]["after"]["count"], c["whole_proposal"]["proposal"], c["proposal"])
              == (4, 0, "戻し", "延長"), str(c))
        row_zero2 = dict(row_zero, 延長="1")
        c2 = ex.build_status([row_zero2], WEEK_END, sp, sp_posts, [])[0][0]
        check("延長済みで絞り込んだ「後」が0件 → 既存の扱い（戻し）", c2["proposal"] == "戻し", str(c2))
        d = st_n["EX-0007"]
        check("EX-0001〜0003 型（pin-hook）の判定案は全体の値のまま・項目も増えない",
              (d["proposal"], "narrowed" not in d, "whole_proposal" not in d) == ("戻し", True, True), str(d))
        d2 = st_n["EX-0008"]
        check("EX-0001〜0003 型（x-standalone）の判定案は全体の値のまま・項目も増えない",
              (d2["proposal"], "narrowed" not in d2, "whole_proposal" not in d2) == ("戻し", True, True), str(d2))
        check("実験IDと対象が合わない行（EX-0004 の対象が x-standalone）は絞り込まない",
              ex._narrow_condition(dict(row_zero, 対象="x-standalone")) is None)
        due = ex._due_reason(a, WEEK_END)
        check("judge-due の根拠: 絞り込んだ値が本体・「；参考: 全体 中央値 前2800 後140」が残る",
              "中央値 前1400 後4200 件数2/2" in due and due.endswith("；参考: 全体 中央値 前2800 後140"), due)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("")
    if FAILURES:
        print("FAILED %d: %s" % (len(FAILURES), " / ".join(FAILURES)))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
