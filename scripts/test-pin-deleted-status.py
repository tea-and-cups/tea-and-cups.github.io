# -*- coding: utf-8 -*-
r"""削除済みピン（data_status=DELETED）と、週次 gateway のピン日次の取得完了確認のテスト。

本物の data/pin-daily-metrics.tsv・growth/inputs・growth/outputs・外部API・Codex には触れない。
一時ディレクトリに作ったダミーの TSV へ growth-metrics.py の読み込み先を差し替え、codex-gateway.py の
growth-metrics.py 呼び出し（_run_metrics）を同じプロセス内の growth-metrics.py の main() 呼び出しへ
差し替えて、各スクリプトの関数をそのまま呼ぶ（テスト側で判定を再実装しない）。
一時ディレクトリは終了時に必ず消す。

確かめること:
  1. fetch-pin-daily-metrics.py の mark_deleted(): PROCESSING の行だけを DELETED にし、値と READY の行は
     変えない。deleted_pin_ids() が DELETED の行を持つ pin_id を返す
  2. growth-metrics.py の pins.daily_totals: DELETED の行は欠損日の判定（processing_rows）と合計から外れる
     （同じ行が PROCESSING のままなら欠損日になる＝修正前の状態の再現）
  3. codex-gateway.py の週次: 対象週に PROCESSING の行があると Codex を呼ぶ前に終了コード2で止まり、
     pins-daily-totals.json を作らない。--skip-pin-check（skip_pin_check=True）なら続行し、
     pins-daily-totals.json を作って注記を渡す。DELETED だけなら止まらない

使い方:
  python site/scripts/test-pin-deleted-status.py
"""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SINCE, UNTIL = "2026-09-15", "2026-09-21"   # 対象週（月〜日）。実日付より前の固定日付
FIRST_DAY = "2026-08-18"                    # TSV の最初の日（UNTIL の34日前）


def _load(file_name):
    spec = importlib.util.spec_from_file_location(
        file_name[:-3].replace("-", "_") + "_under_test", os.path.join(SCRIPT_DIR, file_name))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fetch = _load("fetch-pin-daily-metrics.py")
gm = _load("growth-metrics.py")
gw = _load("codex-gateway.py")

FAILURES = []


def check(label, ok, detail=""):
    print("%s %s%s" % ("OK  " if ok else "NG  ", label, (" - %s" % detail) if detail and not ok else ""))
    if not ok:
        FAILURES.append(label)


def _days():
    import datetime as dt
    day = dt.date.fromisoformat(FIRST_DAY)
    end = dt.date.fromisoformat(UNTIL)
    while day <= end:
        yield day.isoformat()
        day += dt.timedelta(days=1)


def _row(pin_id, pin_number, date, status, impressions):
    row = {c: "" for c in fetch.COLUMNS}
    row.update({"pin_id": pin_id, "pin_number": str(pin_number), "created_at": "2026-08-01",
                "date": date, "data_status": status, "impressions": str(impressions),
                "saves": "0", "outbound_clicks": "0", "pin_clicks": "0",
                "eligible_for_comparison": "false", "duplicate_detected": "false"})
    return row


def write_tsv(path, tail_status_b, tail_status_c):
    """ピンA（全日 READY・10imp）/ ピンB（対象週の最後の2日が tail_status_b）/
    ピンC（対象週の最後の3日が tail_status_c・値0）/ 埋め草20本（全日 READY・0imp）のダミー TSV。
    埋め草は、行数が前後の日の中央値の90%未満で欠損日になる判定に1行の差で掛からないようにするため。"""
    rows = []
    for day in _days():
        for n in range(20):
            rows.append(_row("F%d" % n, 100 + n, day, "READY", 0))
        rows.append(_row("A", 1, day, "READY", 10))
        rows.append(_row("B", 2, day, tail_status_b if day >= "2026-09-20" else "READY", 5))
        status_c = tail_status_c if day >= "2026-09-19" else "READY"
        rows.append(_row("C", 3, day, status_c, 0 if status_c != "READY" else 2))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(fetch.COLUMNS) + "\n")
        for row in rows:
            f.write("\t".join(row[c] for c in fetch.COLUMNS) + "\n")


def run_gm(argv):
    """growth-metrics.py の main() を同じプロセスで呼び、(契約JSON, 標準出力) を返す。"""
    out = io.StringIO()
    saved = sys.argv
    sys.argv = ["growth-metrics.py"] + [str(a) for a in argv]
    try:
        with contextlib.redirect_stdout(out):
            try:
                gm.main()
            except SystemExit:
                pass
    finally:
        sys.argv = saved
    text = out.getvalue()
    return json.loads(text), text


def fake_run_metrics(args):
    payload, text = run_gm(args)
    return payload, text, None


def test_mark_deleted():
    rows = {("X", "2026-09-19"): _row("X", 9, "2026-09-19", "READY", 3),
            ("X", "2026-09-20"): _row("X", 9, "2026-09-20", "PROCESSING", 0),
            ("Y", "2026-09-20"): _row("Y", 8, "2026-09-20", "PROCESSING", 0)}
    count = fetch.mark_deleted(rows, "X", "2031-01-01T00:00:00+09:00")
    check("1-1 mark_deleted が PROCESSING の1行だけを書き換える", count == 1, "count=%s" % count)
    check("1-2 書き換えた行が DELETED・値0のまま",
          rows[("X", "2026-09-20")]["data_status"] == "DELETED"
          and rows[("X", "2026-09-20")]["impressions"] == "0")
    check("1-3 READY の行は残る", rows[("X", "2026-09-19")]["data_status"] == "READY"
          and rows[("X", "2026-09-19")]["impressions"] == "3")
    check("1-4 他のピンの PROCESSING は変えない", rows[("Y", "2026-09-20")]["data_status"] == "PROCESSING")
    check("1-5 deleted_pin_ids が X だけを返す", fetch.deleted_pin_ids(rows) == {"X"})


def test_daily_totals(tmp):
    tsv = os.path.join(tmp, "deleted.tsv")
    write_tsv(tsv, "READY", "DELETED")
    gm.PIN_DAILY_METRICS_TSV = tsv
    payload, _ = run_gm(["pins", "--operation", "pins.daily_totals", "--since", SINCE, "--until", UNTIL])
    series = {r["date"]: r for r in payload["data"]["series"]}
    flagged = [d for d, r in series.items() if r["missing_flag"]]
    check("2-1 DELETED の日は欠損日にならない", not flagged, "flagged=%s" % flagged)
    check("2-2 DELETED の行は processing_rows・row_count に入らない",
          series["2026-09-21"]["processing_rows"] == 0 and series["2026-09-21"]["row_count"] == 22,
          str(series["2026-09-21"]))
    check("2-3 合計は READY の行だけ（A10+B5）", series["2026-09-21"]["impressions"] == 15)

    tsv2 = os.path.join(tmp, "processing.tsv")
    write_tsv(tsv2, "READY", "PROCESSING")
    gm.PIN_DAILY_METRICS_TSV = tsv2
    payload, _ = run_gm(["pins", "--operation", "pins.daily_totals", "--since", SINCE, "--until", UNTIL])
    flagged = [r["date"] for r in payload["data"]["series"] if r["missing_flag"]]
    check("2-4 同じ行が PROCESSING のままなら欠損日になる（修正前の再現）",
          flagged == ["2026-09-19", "2026-09-20", "2026-09-21"], "flagged=%s" % flagged)


class _Reached(Exception):
    pass


def _audit(tmp, skip_pin_check):
    """週次 gateway を、入力 (a)〜(e) の生成の直前まで動かす。戻り値: (終了コード or "reached", 標準出力, 注記)"""
    reached = {}

    def stop_before_inputs(input_dir, since, until, pin_notes=None):
        reached["notes"] = pin_notes
        raise _Reached()

    gw.GROWTH_INPUTS_DIR = Path(tmp) / "inputs"
    gw.AUDIT_OUTPUTS_DIR = Path(tmp) / "outputs"
    gw._run_metrics = fake_run_metrics
    gw._prepare_weekly_inputs = stop_before_inputs
    out = io.StringIO()
    target = Path(tmp) / "outputs" / "test-week" / "audit.md"
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        try:
            code = gw.run_growth_audit("growth-audit", "unused.md", str(target), mode="weekly",
                                       since=SINCE, until=UNTIL, render_only=str(Path(tmp) / "render"),
                                       skip_sns=True, skip_pin_check=skip_pin_check)
        except _Reached:
            code = "reached"
    return code, out.getvalue(), reached.get("notes")


def test_gateway(tmp):
    totals = Path(tmp) / "inputs" / "test-week" / "pins-daily-totals.json"
    tsv = os.path.join(tmp, "gw-processing.tsv")
    write_tsv(tsv, "PROCESSING", "DELETED")
    gm.PIN_DAILY_METRICS_TSV = tsv

    code, stdout, _ = _audit(tmp, False)
    check("3-1 対象週に PROCESSING があると終了コード2で止まる", code == 2, "code=%s" % code)
    check("3-2 止めたときの文言を含む", gw.PIN_CHECK_MESSAGE in stdout, stdout[:200])
    check("3-3 止めたときは pins-daily-totals.json を作らない", not totals.exists())

    code, _stdout, notes = _audit(tmp, True)
    check("3-4 --skip-pin-check なら続行する", code == "reached", "code=%s" % code)
    check("3-5 続行したときは pins-daily-totals.json を作る", totals.is_file())
    if totals.is_file():
        saved = json.loads(totals.read_text(encoding="utf-8"))
        check("3-6 保存した JSON は pins.daily_totals の35日・4週比較",
              saved.get("operation") == "pins.daily_totals" and len(saved["data"]["series"]) == 35
              and saved["params"].get("compare_weeks") == 4, str(saved.get("params")))
    check("3-7 続行したときは注記を入力一覧へ渡す",
          bool(notes) and "--skip-pin-check" in notes[0], str(notes))

    totals.unlink()
    tsv2 = os.path.join(tmp, "gw-deleted.tsv")
    write_tsv(tsv2, "READY", "DELETED")
    gm.PIN_DAILY_METRICS_TSV = tsv2
    code, _stdout, notes = _audit(tmp, False)
    check("3-8 DELETED だけなら止まらず、注記も無い", code == "reached" and not notes,
          "code=%s notes=%s" % (code, notes))
    check("3-9 止まらなかったときは pins-daily-totals.json を作る", totals.is_file())


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    tmp = tempfile.mkdtemp(prefix="test-pin-deleted-")
    try:
        test_mark_deleted()
        test_daily_totals(tmp)
        test_gateway(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("")
    if FAILURES:
        print("失敗 %d件: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("すべて合格")
    return 0


if __name__ == "__main__":
    sys.exit(main())
