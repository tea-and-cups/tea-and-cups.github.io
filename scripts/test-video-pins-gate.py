# -*- coding: utf-8 -*-
r"""post-video-pins.py の機械QA のゲートと、Pinterest の1日の上限の合算のテスト（D-0302）。

本物の台帳・Pinterest API には触れない。一時ディレクトリにダミーの mp4・qa.json・動画md・台帳を作り、
画像ピンの台帳（post-pins-to-pinterest.py の LEDGER_PATH）も一時ファイルへ差し替える。
動画md は本物の output/videos/iifuufu-no-hi-pair-cup-erabikata/video-1.md を動画2に書き換えた写し。
ffprobe・ボード・GET /v5/pins・誘導先URLの確認はダミーに差し替える。一時ディレクトリは終了時に必ず消す。

確かめること:
  1. 動画2以降の check_review: qa.json が無い・gate に不合格・passed が不合格・qa.json の mp4_sha256 が現物と違う・
     審査行の sha256 が現物と違う・審査行に sha256 が無い・「- 機械QA:」行が無い／qa.json 1つの形でない、のどれでも止まる。
     審査行・qa.json・現物の3つが一致するときだけ通る
  2. 動画1は対象外（本物の動画1の md と mp4 で、qa.json を見ずに通る）
  3. 止まったときの終了の仕方は既存の審査不合格と同じ（--dry-run --md で実行して終了コード1・[NG] の行）
  4. 1日の上限: count_today_posted は画像ピン（投稿日: 行）と動画ピン（台帳の作成日）を足す。
     画像ピン側の既定の数え方（引数なし）にも動画ピンが入る。当日に動画ピンが無ければ画像ピンだけの件数と同じ。
     当日の合計＋この1本が50を超えれば、GET /v5/pins の照合の前で保留（失敗に数えない）。ちょうど50なら進む

使い方: python site/scripts/test-video-pins-gate.py
終了コード: 全件合格で0、1件でも不合格で1
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
REAL_MD = os.path.join(ROOT, "output", "videos", "iifuufu-no-hi-pair-cup-erabikata", "video-1.md")
DAY = "2026-10-28"


def _load(file_name):
    spec = importlib.util.spec_from_file_location(
        file_name[:-3].replace("-", "_") + "_under_test", os.path.join(SCRIPT_DIR, file_name))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pvp = _load("post-video-pins.py")
pp = pvp._load_post_pins()

FAILURES = []


def check(label, ok, detail=""):
    print("%s %s%s" % ("OK  " if ok else "NG  ", label, (" - %s" % (detail,)) if detail and not ok else ""))
    if not ok:
        FAILURES.append(label)


def setup_v2(tmp, name, qa=True, gate=None, passed=True, qa_sha=None, pin_sha=None, qa_line=None):
    """動画2の一式を tmp/name/ に作る。*_sha は既定で現物の sha256（pin_sha="no" で審査行に sha256 を書かない）。
    qa_line を渡すと「- 機械QA:」行をその文字列に置き換える（"" なら行を消す）。戻り値: (md のパス, 現物の sha256)。"""
    d = os.path.join(tmp, name)
    os.makedirs(d)
    mp4 = os.path.join(d, "video-2.mp4")
    Path(mp4).write_bytes(b"dummy mp4 " + name.encode())
    actual = pvp.file_sha256(mp4)
    qa_path = os.path.join(d, "video-2.qa.json")
    if qa:
        Path(qa_path).write_text(json.dumps({
            "mp4": "video-2.mp4", "mp4_sha256": qa_sha or actual, "passed": passed,
            "gate": gate or {"ai_credit_visible": True, "ai_credit_text": True, "r7_chars": True}}), encoding="utf-8")
    lines = []
    for l in Path(REAL_MD).read_text(encoding="utf-8").splitlines():
        if l.startswith("- 審査:") or l.startswith("- X・Threads審査:"):
            continue
        if l.startswith("- 動画ファイル:"):
            l = "- 動画ファイル: " + mp4.replace(os.sep, "/")
        elif l.startswith("- 誘導先URL:"):
            l = l.replace("utm_content=video1", "utm_content=video2")
        elif l.startswith("- 機械QA:"):
            l = "- 機械QA: " + qa_path.replace(os.sep, "/") if qa_line is None else qa_line
            if not l:
                continue
        lines.append(l)
    lines.append("- 審査: 公開可 2026-10-28" + ("" if pin_sha == "no" else " sha256:" + (pin_sha or actual)))
    lines.append("- X・Threads審査: 公開可 2026-10-28 sha256:" + actual)
    md = os.path.join(d, "video-2.md")
    Path(md).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md, actual


def review(md):
    """parse_video_md → check_fields → check_review。戻り値: (止まった理由 or None, 結果の行)。"""
    try:
        fields = pvp.parse_video_md(md, pp)
        pvp.check_fields(fields, pp)
        return None, pvp.check_review(fields)
    except pvp._Stop as e:
        return str(e), []


def test_gate(tmp):
    other = "0" * 64
    cases = [
        ("qa.json が無い", dict(qa=False), "qa.json がありません"),
        ("gate に不合格の項目がある", dict(gate={"ai_credit_visible": True, "r7_chars": False}), "gate に不合格の項目"),
        ("gate が空", dict(gate={}), None),
        ("passed が合格でない", dict(passed=False), "passed が合格ではありません"),
        ("qa.json の mp4_sha256 が現物と違う", dict(qa_sha=other), "mp4_sha256 が現物と一致しません"),
        ("審査行の sha256 が現物と違う", dict(pin_sha=other), "sha256 が一致しません"),
        ("審査行に sha256 が無い", dict(pin_sha="no"), "sha256:<64桁> がありません"),
        ("「- 機械QA:」行が無い", dict(qa_line=""), "行なし"),
        ("「- 機械QA:」行に qa.json 以外も並ぶ", dict(qa_line="- 機械QA: a/video-2.qa.json・a/endcard.json"), "ちょうど1行"),
    ]
    for i, (label, kw, expect) in enumerate(cases):
        if label == "gate が空":
            # gate={} は setup の既定に置き換わるため、qa.json を直接書き換える
            md, sha = setup_v2(tmp, "g%d" % i)
            qa_path = os.path.join(tmp, "g%d" % i, "video-2.qa.json")
            Path(qa_path).write_text(json.dumps({"mp4_sha256": sha, "gate": {}, "passed": True}), encoding="utf-8")
            expect = "gate がありません"
        else:
            md, _sha = setup_v2(tmp, "g%d" % i, **kw)
        reason, _lines = review(md)
        check("動画2: %s → 止まる" % label, reason is not None and expect in reason, reason)
    md, sha = setup_v2(tmp, "ok")
    reason, lines = review(md)
    check("動画2: 審査行・qa.json・現物の sha256 が一致すれば通る",
          reason is None and any("機械QA: gate 3項目すべて合格" in l for l in lines), (reason, lines))

    reason, lines = review(REAL_MD)
    check("動画1: 対象外（qa.json を見ずに、既存の審査行の照合だけで通る）",
          reason is None and not any("機械QA" in l for l in lines), (reason, lines))

    # 終了の仕方: 既存の審査不合格と同じ（--dry-run --md で終了コード1・[NG] の行）
    md, _sha = setup_v2(tmp, "exit", qa=False)
    res = subprocess.run([sys.executable, os.path.join(SCRIPT_DIR, "post-video-pins.py"), "--dry-run",
                          "--md", md, "--ledger", os.path.join(tmp, "exit-ledger.md")],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    check("動画2: qa.json が無ければ --dry-run が終了コード1・[NG] で止まる（既存の審査不合格と同じ）",
          res.returncode == 1 and "[NG] 機械QA の qa.json がありません" in res.stdout
          and not os.path.exists(os.path.join(tmp, "exit-ledger.md")), (res.returncode, res.stdout, res.stderr))


def _image_ledger(path, count, other_day_count=0):
    rows = ["投稿日: %s %d" % (DAY, 400 + i) for i in range(count)]
    rows += ["投稿日: 2026-10-01 %d" % (300 + i) for i in range(other_day_count)]
    Path(path).write_text("# 台帳（テスト用）\n" + "\n".join(rows) + "\n", encoding="utf-8")


def _video_ledger(path, created_days):
    rows = ["動画%d | s%d | 作成済み | 公開可 %s | %s | %s | %d" % (9 + i, i, d, d, ("%x" % i) * 64, i)
            for i, d in enumerate(created_days)]
    Path(path).write_text(pvp.LEDGER_HEADER + "\n".join(rows) + "\n", encoding="utf-8")


def test_daily_limit(tmp):
    image = os.path.join(tmp, "pin-posted.md")
    video = os.path.join(tmp, "video-posted.md")
    saved = pp.LEDGER_PATH, pp._load_post_video_pins, pvp.probe_video, pvp.check_board, pp.check_url_ok
    pp.LEDGER_PATH = image
    try:
        _image_ledger(image, 3, other_day_count=2)
        _video_ledger(video, [DAY, DAY, "2026-10-27"])
        check("合算: 画像ピン3件＋動画ピン2件（作成日が当日）= 5",
              pp.count_today_posted(DAY, video_path=video) == 5, pp.count_today_posted(DAY, video_path=video))
        mod = saved[1]()
        mod.LEDGER_PATH = video
        pp._load_post_video_pins = lambda: mod
        check("画像ピン側の既定の数え方（引数なし）にも動画ピンが入る", pp.count_today_posted(DAY) == 5,
              pp.count_today_posted(DAY))
        mod.LEDGER_PATH = os.path.join(tmp, "no-video-ledger.md")
        check("当日に動画ピンが無ければ、画像ピンだけの件数と同じ（3）", pp.count_today_posted(DAY) == 3,
              pp.count_today_posted(DAY))
        pp._load_post_video_pins = saved[1]

        # process: ffprobe・ボード・誘導先URLはダミー。GET /v5/pins は空の一覧を渡す
        pvp.probe_video = lambda fields: ["動画の要件: （テストでは見ない）"]
        pvp.check_board = lambda fields, _pp, _m: ["ボード: （テストでは見ない）"]
        pp.check_url_ok = lambda url: (True, "200（テスト）")
        md, _sha = setup_v2(tmp, "limit")

        def run():
            ctx = {"dry_run": True, "token": "x", "board_id_map": {}, "ledger": pvp.load_ledger(video),
                   "ledger_path": video, "listing": [], "today": DAY}
            out = []
            return pvp.process(md, pp, ctx, out), out

        _image_ledger(image, 48)
        _video_ledger(video, [DAY, DAY])   # 48＋2＋この1本 = 51 > 50
        label, out = run()
        check("上限: 画像48＋動画2＋この1本 = 51 > 50 → GET /v5/pins の照合の前で保留（失敗に数えない）",
              label == "保留(1日の上限)" and any("本日すでに投稿 50件" in l for l in out)
              and not any("GET /v5/pins" in l for l in out), (label, out))
        _image_ledger(image, 47)          # 47＋2＋1 = 50 → 上限内
        label, out = run()
        check("上限: ちょうど50件なら進む（dry-run の成功見込み）", label == "成功見込み(dry-run)", (label, out))
    finally:
        pp.LEDGER_PATH, pp._load_post_video_pins, pvp.probe_video, pvp.check_board, pp.check_url_ok = saved


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    tmp = tempfile.mkdtemp(prefix="test-video-pins-gate-")
    try:
        test_gate(tmp)
        test_daily_limit(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("TEST_%s %d件NG" % ("NG" if FAILURES else "OK", len(FAILURES)))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
