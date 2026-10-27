# -*- coding: utf-8 -*-
r"""動画の X・Threads 投稿（post-video-to-buffer.py）と、それに合わせた変更のテスト（D-0298）。

本物の data/video-buffer-posted.tsv・video-tmp・Buffer API には触れない。一時ディレクトリに作ったダミーの
動画md・台帳へ読み込み先を差し替え、git・公開URLの確認・Buffer の呼び出しはダミーの関数を渡す。
動画md は本物の output/videos/iifuufu-no-hi-pair-cup-erabikata/video-1.md の写しに審査行を足したもの
（mp4 は本物を読むだけ）。一時ディレクトリは終了時に必ず消す。

確かめること:
  1. 投稿文の検査（2行の有無・審査行・UTM の4項目・X の文字数）
  2. createPost の入力（shareNow・assets は video だけ・AI表示の項目なし）と台帳への記録
  3. 再実行で二重投稿しない（台帳に両チャンネルあり → createPost を呼ばない）／片方だけなら残りだけ送る
  4. createPost の拒否で止まる（台帳に書かない・エラーの全文を出す）／停止スイッチで何もしない
  5. --cleanup: 送信済みでなければ消さない／送信済みなら消して404確認後に削除日／404未確認なら削除日を書かない
  6. 画像の掃除（fetch_scheduled_pin_numbers）: 動画の投稿がキューにあれば止まる側に倒れる
  7. experiments.py: 動画の postId を前・後から除き、sns-posts-7d には video: true で残す。
     動画の投稿を一覧から丸ごと抜いた場合と件数・中央値が同じ

使い方:
  python site/scripts/test-video-to-buffer.py
  python site/scripts/test-video-to-buffer.py --real --week-end YYYY-MM-DD
      本物の Buffer（buffer.sent_posts を1回）と本物の data/experiments.tsv・data/video-buffer-posted.tsv で、
      実行中の実験の前・後の件数を (a) 動画の postId を足す前（印なし）(b) 足した後（印あり）
      (c) 動画の投稿を一覧から抜いた場合 で比べる。書き込みはしない。週末日が未来なら、Buffer の取得の
      終わりだけ今日で切る（未来の until を受け付けないため）。
"""

import datetime as dt
import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
REAL_MD = os.path.join(ROOT, "output", "videos", "iifuufu-no-hi-pair-cup-erabikata", "video-1.md")


def _load(file_name):
    spec = importlib.util.spec_from_file_location(
        file_name[:-3].replace("-", "_") + "_under_test", os.path.join(SCRIPT_DIR, file_name))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


vb = _load("post-video-to-buffer.py")
ex = _load("experiments.py")
ppb = vb.ppb()

FAILURES = []


def check(label, ok, detail=""):
    print("%s %s%s" % ("OK  " if ok else "NG  ", label, (" - %s" % (detail,)) if detail and not ok else ""))
    if not ok:
        FAILURES.append(label)


class FakeBuffer:
    """createPost・post のダミー。reject_service のチャンネルへの createPost を MutationError で返す。"""

    def __init__(self, reject_channel=None, statuses=None):
        self.calls = []
        self.reject_channel = reject_channel
        self.statuses = statuses or {}

    def __call__(self, document, variables=None, operation_name=None):
        self.calls.append((operation_name, variables))
        if operation_name == "CreatePost":
            payload = variables["input"]
            if payload["channelId"] == self.reject_channel:
                return {"createPost": {"__typename": "InvalidInputError", "message": "video url rejected"}}
            return {"createPost": {"__typename": "PostActionSuccess",
                                   "post": {"id": "P-%s" % payload["channelId"], "status": "sending", "dueAt": None}}}
        if operation_name == "VideoPost":
            status, sent = self.statuses.get(variables["id"], ("sending", None))
            return {"post": {"id": variables["id"], "status": status, "sentAt": sent, "assets": []}}
        raise AssertionError("想定外の呼び出し: %s" % operation_name)

    def creates(self):
        return [v["input"] for op, v in self.calls if op == "CreatePost"]


def setup(tmp, review=True, x_line=None):
    lines = [l for l in Path(REAL_MD).read_text(encoding="utf-8").splitlines()
             if not l.startswith("- X・Threads審査:")]   # 審査行は review で付け直す
    if x_line is not None:
        lines = [x_line if l.startswith("- X用説明文:") else l for l in lines]
    text = "\n".join(lines) + "\n"
    if review:
        text += "- X・Threads審査: 公開可 2026-10-27\n"
    md = os.path.join(tmp, "video-1.md")
    Path(md).write_text(text, encoding="utf-8")
    pinned = os.path.join(tmp, "video-posted.md")
    Path(pinned).write_text(vb.pvp().LEDGER_HEADER + "動画1 | iifuufu-no-hi-pair-cup-erabikata | 作成済み | "
                            "公開可 2026-10-27 | 2026-10-27 | x | 1101552390143174813\n", encoding="utf-8")
    return md, pinned


CHANNELS = {"twitter": ["CT"], "threads": ["CH"], "instagram": ["CI"]}


def run_post(md, pinned, ledger, fake, dry_run=False, stage_calls=None):
    lines = []
    stage_calls = stage_calls if stage_calls is not None else []
    rc = vb.cmd_post(md, ledger, pinned, dry_run=dry_run, out=lines.append, graphql=fake, channels=CHANNELS,
                     now=dt.datetime(2026, 10, 27, 22, 0, tzinfo=vb.JST),
                     stage=lambda fields, key, out: stage_calls.append(key),
                     wait=lambda url, size, out: "HTTP 200 / video/mp4")
    return rc, lines


def test_texts(tmp):
    md, pinned = setup(tmp, review=False)
    rc, lines = run_post(md, pinned, os.path.join(tmp, "l0.tsv"), FakeBuffer())
    check("審査行が無ければ止める", rc == 1 and any("X・Threads審査" in l for l in lines), lines)
    md, pinned = setup(tmp, x_line="- X用説明文: " + "あ" * 150)
    rc, lines = run_post(md, pinned, os.path.join(tmp, "l1.tsv"), FakeBuffer())
    check("X の本文が上限を超えれば止める", rc == 1 and any("X の本文が上限" in l for l in lines), lines)
    md, pinned = setup(tmp, x_line="（行なし）")
    rc, lines = run_post(md, pinned, os.path.join(tmp, "l2.tsv"), FakeBuffer())
    check("X用説明文の行が無ければ止める", rc == 1 and any("X用説明文" in l for l in lines), lines)


def test_post_and_rerun(tmp):
    md, pinned = setup(tmp)
    ledger = os.path.join(tmp, "ledger.tsv")
    fake = FakeBuffer()
    rc, lines = run_post(md, pinned, ledger, fake, dry_run=True)
    check("dry-run は createPost も台帳も触らない", rc == 0 and not fake.calls and not os.path.exists(ledger), lines)

    stage_calls = []
    rc, lines = run_post(md, pinned, ledger, fake, stage_calls=stage_calls)
    creates = fake.creates()
    check("X・Threads の2件を送る（Instagram は送らない）",
          rc == 0 and [c["channelId"] for c in creates] == ["CT", "CH"], (rc, lines))
    key = "iifuufu-no-hi-pair-cup-erabikata-video-1"
    url = "https://kohaku-jikan.com/video-tmp/%s.mp4" % key
    check("createPost: mode=shareNow・assets は video の url だけ・metadata なし",
          all(c["mode"] == "shareNow" and c["assets"] == [{"video": {"url": url}}] and "metadata" not in c
              and "aiAssisted" not in c for c in creates), creates)
    check("X の本文: X用説明文＋改行＋utm_source=x の URL",
          creates[0]["text"].endswith("utm_source=x&utm_medium=social&utm_campaign=iifuufu-no-hi-pair-cup-erabikata"
                                      "&utm_content=video1") and "\n" in creates[0]["text"], creates[0]["text"])
    check("Threads の本文: utm_source=threads",
          "utm_source=threads&utm_medium=social" in creates[1]["text"], creates[1]["text"])
    rows = vb.load_ledger(ledger)
    check("台帳に2行（動画キー・service・postId・投稿日時・公開URL・削除日は空）",
          [(r["動画キー"], r["service"], r["postId"], r["公開URL"], r["削除日"]) for r in rows]
          == [(key, "twitter", "P-CT", url, ""), (key, "threads", "P-CH", url, "")]
          and rows[0]["投稿日時"] == "2026-10-27T22:00:00+09:00", rows)
    check("公開（コピー・push）を1回だけ呼ぶ", stage_calls == [key], stage_calls)

    fake2, stage2 = FakeBuffer(), []
    rc, lines = run_post(md, pinned, ledger, fake2, stage_calls=stage2)
    check("再実行: 両チャンネルとも台帳にあれば createPost も公開も呼ばずにスキップ",
          rc == 0 and not fake2.calls and not stage2 and any("スキップ" in l for l in lines), lines)
    check("再実行: 台帳は2行のまま", len(vb.load_ledger(ledger)) == 2)

    # 片方（threads）だけ残っている場合は残りだけ送る
    vb._write_rows([r for r in vb.load_ledger(ledger) if r["service"] == "twitter"], ledger)
    fake3 = FakeBuffer()
    rc, lines = run_post(md, pinned, ledger, fake3)
    check("片方だけ台帳にあれば、残りの1チャンネルだけ送る",
          rc == 0 and [c["channelId"] for c in fake3.creates()] == ["CH"], lines)


def test_reject_and_switch(tmp):
    md, pinned = setup(tmp)
    ledger = os.path.join(tmp, "reject.tsv")
    fake = FakeBuffer(reject_channel="CT")
    rc, lines = run_post(md, pinned, ledger, fake)
    check("拒否: 止めて残りは送らない・台帳に書かない",
          rc == 1 and len(fake.creates()) == 1 and not vb.load_ledger(ledger), (rc, lines))
    check("拒否: エラーの全文を出す", any("video url rejected" in l and "エラーの全文" in l for l in lines), lines)

    saved = ppb.check_kill_switch
    ppb.check_kill_switch = lambda: "buffer-auto-post-off.txt"
    try:
        fake = FakeBuffer()
        rc, lines = run_post(md, pinned, os.path.join(tmp, "switch.tsv"), fake)
        check("停止スイッチ: 何もしない", rc == 0 and not fake.calls and any("停止スイッチ" in l for l in lines), lines)
    finally:
        ppb.check_kill_switch = saved


def test_cleanup(tmp):
    ledger = os.path.join(tmp, "cleanup.tsv")
    key = "s-video-1"
    url = "https://kohaku-jikan.com/video-tmp/s-video-1.mp4"
    vb._write_rows([{"動画キー": key, "service": "twitter", "postId": "A", "投稿日時": "t", "公開URL": url, "削除日": ""},
                    {"動画キー": key, "service": "threads", "postId": "B", "投稿日時": "t", "公開URL": url, "削除日": ""}],
                   ledger)
    removed = []

    def run(statuses, gone_result=True, wait=False):
        lines = []
        rc = vb.cmd_cleanup(ledger, wait=wait, out=lines.append, graphql=FakeBuffer(statuses=statuses),
                            today=dt.date(2026, 10, 27), sleep=lambda s: None,
                            remove=lambda k, out: removed.append(k), gone=lambda u, out, sleep: gone_result)
        return rc, lines

    rc, lines = run({"A": ("sent", "2026-10-27T13:00:00Z"), "B": ("sending", None)})
    check("掃除: 片方が送信済みでなければ消さない", not removed and all(not r["削除日"] for r in vb.load_ledger(ledger)),
          lines)
    rc, lines = run({"A": ("sent", "x"), "B": ("sent", "y")}, gone_result=False)
    check("掃除: 404 を確かめられなければ削除日を書かない",
          removed == [key] and rc == 1 and all(not r["削除日"] for r in vb.load_ledger(ledger)), lines)
    rc, lines = run({"A": ("sent", "x"), "B": ("sent", "y")})
    check("掃除: 両方送信済み → 消して404確認後に削除日",
          rc == 0 and all(r["削除日"] == "2026-10-27" for r in vb.load_ledger(ledger)), lines)
    removed.clear()
    rc, lines = run({"A": ("sent", "x"), "B": ("sent", "y")})
    check("掃除: 削除日のある動画は二度と消さない", not removed and any("削除待ちの動画はありません" in l for l in lines), lines)


def test_prune_guard():
    def queue(nodes):
        def graphql(document, variables=None, operation_name=None):
            if operation_name == "Account":
                return {"account": {"organizations": [{"id": "org"}]}}
            return {"posts": {"pageInfo": {"hasNextPage": False}, "edges": [{"node": n} for n in nodes]}}
        return graphql

    numbers, note = ppb.fetch_scheduled_pin_numbers(queue([
        {"id": "v", "assets": [{"source": "https://kohaku-jikan.com/video-tmp/s-video-1.mp4"}]},
        {"id": "a", "assets": [{"source": "https://kohaku-jikan.com/pin-images/pin380.jpg"}]}]))
    check("画像の掃除: 動画の投稿がキューにあれば止まる（None）", numbers is None, note)


def _post(pid, day, views, service="twitter"):
    return {"entity_id": pid, "service": service, "text": "t",
            "sent_at": "%sT01:00:00Z" % day, "metrics": [{"type": "impressions", "value": views}]}


def test_measure(tmp):
    ledger = os.path.join(tmp, "video-ledger.tsv")
    vb._write_rows([{"動画キー": "s-video-1", "service": "twitter", "postId": "V1", "投稿日時": "t", "公開URL": "u",
                     "削除日": "2026-10-27"},
                    {"動画キー": "s-video-1", "service": "threads", "postId": "V2", "投稿日時": "t", "公開URL": "u",
                     "削除日": ""}], ledger)
    check("measure: 台帳の postId を読む（削除日の有無は問わない）", ex.load_video_ids(ledger) == {"V1", "V2"},
          ex.load_video_ids(ledger))
    base = [_post("P1", "2026-10-20", 100), _post("P2", "2026-10-22", 120),
            _post("P3", "2026-10-29", 200), _post("P4", "2026-10-30", 220)]
    videos = [_post("V1", "2026-10-27", 9000), _post("V3", "2026-10-29", 9000)]   # V3 は台帳に無い（印なし）
    row = {c: "" for c in ex.COLUMNS}
    row.update({"実験ID": "EX-0003", "状態": "実行中", "種別": "ルール", "対象": "x-standalone",
                "範囲": "channel=twitter", "主指標": "x-impr-7d", "開始日": "2026-10-28",
                "判定日": "2026-11-25", "延長": "0"})
    week_end = dt.date(2026, 11, 8)
    saved = ex.VIDEO_BUFFER_LEDGER, ex.X_STANDALONE_LEDGER, ex.fetch_sent_posts
    ex.VIDEO_BUFFER_LEDGER, ex.X_STANDALONE_LEDGER = ledger, os.path.join(tmp, "none-x.tsv")
    try:
        ex.fetch_sent_posts = lambda lo, hi: ([dict(p) for p in base + videos[:1]], None)
        exps, _p, _pins, posts, source, _w = ex.collect([row], week_end, os.path.join(tmp, "none.tsv"))
        ex.fetch_sent_posts = lambda lo, hi: ([dict(p) for p in base], None)
        bare, *_ = ex.collect([row], week_end, os.path.join(tmp, "none.tsv"))
        check("measure: 動画の postId は前から外れ、動画を丸ごと抜いた場合と同じ（前2件・中央値110）",
              exps[0]["before"] == bare[0]["before"] and exps[0]["before"]["count"] == 2, (exps[0]["before"], bare[0]["before"]))
        check("measure: 後も同じ（後2件・中央値210）", exps[0]["after"] == bare[0]["after"], exps[0]["after"])
        check("measure: buffer の取得元に動画の投稿の件数", source.get("video_posts") == 1, source)
        sns = ex.build_sns_posts(posts, dt.date(2026, 11, 3))
        marked = [p for p in sns["posts"] if p["video"]]
        check("sns-posts-7d: 動画の投稿を残し video: true を付ける（standalone は false）",
              len(marked) == 1 and marked[0]["post_id"] == "V1" and not marked[0]["standalone"], sns["posts"])
        ex.fetch_sent_posts = lambda lo, hi: ([dict(p) for p in base + videos[1:]], None)
        unmarked, *_ = ex.collect([row], week_end, os.path.join(tmp, "none.tsv"))
        check("measure: 台帳に無い postId は除かない（意味を変えない）", unmarked[0]["after"]["count"] == 3,
              unmarked[0]["after"])
    finally:
        ex.VIDEO_BUFFER_LEDGER, ex.X_STANDALONE_LEDGER, ex.fetch_sent_posts = saved


def real_check(week_end):
    """本物の Buffer・台帳で、動画の postId を足す前・後・動画を抜いた場合の件数を比べる（書き込みなし）。"""
    rows = ex.load_ledger()
    ids = ex.load_video_ids()
    print("台帳の動画 postId: %s" % (", ".join(sorted(ids)) or "なし"))
    fetched = {}
    real_fetch = ex.fetch_sent_posts

    def once(lo, hi):
        if "posts" not in fetched:
            # Buffer は未来の until を受け付けないため、取得の終わりだけ今日で切る（窓の判定は week_end のまま）
            until = min(hi, dt.date.today())
            print("buffer.sent_posts: %s〜%s（週末日 %s）" % (lo, until, week_end))
            fetched["posts"], fetched["problem"] = real_fetch(lo, until)
        return [dict(p) for p in fetched["posts"]], fetched["problem"]

    ex.fetch_sent_posts = once
    saved_ids = ex.load_video_ids
    try:
        ex.load_video_ids = lambda path=None: set()
        before_add, *_ = ex.collect(rows, week_end)
        ex.load_video_ids = saved_ids
        after_add, _p, _pins, posts, source, warnings = ex.collect(rows, week_end)
        present = [p for p in fetched["posts"] if p.get("entity_id") in ids]
        print("Buffer の送信済み %d件のうち動画の投稿 %d件: %s" % (len(fetched["posts"]), len(present), [
            (p.get("entity_id"), p.get("service"), p.get("sent_at")) for p in present]))
        fetched["posts"] = [p for p in fetched["posts"] if p.get("entity_id") not in ids]
        without, *_ = ex.collect(rows, week_end)
    finally:
        ex.fetch_sent_posts, ex.load_video_ids = real_fetch, saved_ids
    for a, b, c in zip(before_add, after_add, without):
        if "before" not in b:
            print("%s %s: %s（%s）" % (b["id"], b["metric"], b.get("proposal"), b.get("reason")))
            continue
        print("%s %s: 前 足す前%d件→足した後%d件（動画を抜いた場合%d件）／後 %d件→%d件（%d件）" % (
            b["id"], b["metric"], a["before"]["count"], b["before"]["count"], c["before"]["count"],
            a["after"]["count"], b["after"]["count"], c["after"]["count"]))
        check("%s: 足した後の前・後が、動画を抜いた場合と同じ" % b["id"],
              b["before"] == c["before"] and b["after"] == c["after"])
    print("buffer: posts=%s video_posts=%s standalone_posts=%s warnings=%s" % (
        source.get("posts"), source.get("video_posts"), source.get("standalone_posts"), warnings))
    check("動画の postId に印が付く（台帳の行数ぶん・送信済みのもの）", source.get("video_posts") == len(present))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if "--real" in sys.argv:
        i = sys.argv.index("--week-end") if "--week-end" in sys.argv else -1
        if i < 0 or i + 1 >= len(sys.argv):
            print("usage: test-video-to-buffer.py --real --week-end YYYY-MM-DD")
            return 2
        real_check(dt.date.fromisoformat(sys.argv[i + 1]))
    else:
        tmp = tempfile.mkdtemp(prefix="test-video-to-buffer-")
        try:
            test_texts(tmp)
            test_post_and_rerun(tmp)
            test_reject_and_switch(tmp)
            test_cleanup(tmp)
            test_prune_guard()
            test_measure(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print("TEST_%s %d件NG" % ("NG" if FAILURES else "OK", len(FAILURES)))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
