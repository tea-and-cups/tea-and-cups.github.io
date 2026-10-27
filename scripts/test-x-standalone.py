# -*- coding: utf-8 -*-
r"""X の記事なし投稿（post-x-standalone.py）と、それに合わせた変更のテスト（S-0027 ③・D-0294）。

本物の data/x-standalone-posted.tsv・output/x-posts/・data/experiments.tsv・Buffer API には触れない。
一時ディレクトリに作ったダミーの本文・台帳・記事へ読み込み先を差し替え、Buffer の呼び出し（graphql）は
ダミーの関数を渡す（テスト側で判定を再実装しない）。一時ディレクトリは終了時に必ず消す。

確かめること:
  1. 投稿文の検査（文字数・URL無し・ハッシュタグ・NG語（健康）・体験表現・型Y・価格・A〜G）
  2. 審査行の無い件は --post で送らない
  3. 予約時刻の計算（日本時間 8:00 → UTC 前日 23:00）と createPost の入力（customScheduled・assets []）
  4. 同じ件の二重予約の防止（台帳に予約済み）・同じ予定日の二重予約の防止・過去の予定日は送らない
  5. createPost の拒否で止まる（残りは送らない・台帳に「失敗」）／停止スイッチで何も送らない
  6. post-pins-to-buffer.py の画像の掃除: 画像の無い投稿は保護の判定から外れ、画像はあるが
     /pin-images/pinN.jpg でない投稿があれば今どおり止まる
  7. experiments.py: 記事なし投稿を x-impr-7d の集計（前・後）から除き、sns-posts-7d には印つきで残す
  8. check-routine-due.py: 翌日から7日間の予約が無ければ警告・あれば出さない・台帳が無ければ判定しない
  9. --candidates: A〜G・体験・型Y・価格・商品リンクの単位と、直近8週に使った slug を除く

使い方:
  python site/scripts/test-x-standalone.py
"""

import contextlib
import datetime as dt
import importlib.util
import io
import os
import shutil
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _load(file_name):
    spec = importlib.util.spec_from_file_location(
        file_name[:-3].replace("-", "_") + "_under_test", os.path.join(SCRIPT_DIR, file_name))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


xs = _load("post-x-standalone.py")
ex = _load("experiments.py")
routine = _load("check-routine-due.py")
ppb = xs.ppb()   # post-x-standalone.py が停止スイッチ・刈り込みに使うのと同じモジュール

FAILURES = []


def check(label, ok, detail=""):
    print("%s %s%s" % ("OK  " if ok else "NG  ", label, (" - %s" % detail) if detail and not ok else ""))
    if not ok:
        FAILURES.append(label)


class FakeBuffer:
    """createPost のダミー。reject_at 回目（1始まり）を MutationError で返す。"""

    def __init__(self, reject_at=None):
        self.calls = []
        self.reject_at = reject_at

    def __call__(self, document, variables=None, operation_name=None):
        self.calls.append(variables["input"])
        if self.reject_at == len(self.calls):
            return {"createPost": {"__typename": "InvalidInputError", "message": "dummy rejection"}}
        return {"createPost": {"__typename": "PostActionSuccess",
                               "post": {"id": "post%d" % len(self.calls), "status": "scheduled",
                                        "dueAt": variables["input"]["dueAt"], "text": variables["input"]["text"]}}}


GOOD = [
    "アッサムはインド北東部の低地で作られる紅茶。コクと濃さがはっきりしていて、ミルクティー向きといわれます。",
    "茶葉のグレード表記（OP・BOP・CTC）は、茶葉の大きさと形の分類です。味の格付けではありません。 #紅茶",
    "ペアカップは同じ柄だと統一感が出て、色違いだと自分のカップが分かりやすくなります。食卓の雰囲気で決めると迷いません。",
]


def write_week(directory, name, items):
    """items: [(ID, 予定日, 本文, 審査あり)]"""
    lines = ["# X単独投稿（テスト）", ""]
    for xid, day, text, reviewed in items:
        body = text.split("\n")
        lines += ["## %s" % xid, "- 予定日: %s" % day, "- 材料: assam-tea-nyumon ＃よくある質問",
                  "- 本文: %s" % body[0]] + ["  %s" % l for l in body[1:]]
        if reviewed:
            lines.append("- 審査: 公開可 2026-10-27")
        lines.append("")
    path = os.path.join(directory, name)
    Path(path).write_text("\n".join(lines), encoding="utf-8")
    return path


def quiet(fn, *args, **kwargs):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn(*args, out=lambda m="": print(m), **kwargs)
    return rc, buf.getvalue()


def test_text_checks():
    for text in GOOD:
        check("検査OK: %s" % text[:12], xs.text_problems(text) == [], xs.text_problems(text))
    cases = [
        ("文字数", "紅茶" * 141, "文字数超過"),
        ("URL", "アッサムの選び方 https://kohaku-jikan.com/posts/assam-tea-nyumon/", "URL"),
        ("URL（ドメインだけ）", "詳しくは kohaku-jikan.com で", "URL"),
        ("ハッシュタグ3件", "アッサムはミルクティー向きです。 #紅茶 #アッサム #ミルクティー", "ハッシュタグ"),
        ("健康の断定語", "紅茶にはリラックス効果があるといわれます。", "健康の断定語"),
        ("体験表現", "淹れ比べたところ、アッサムのほうが濃く感じました。", "体験表現"),
        ("型Y（型9）", "水出し紅茶は冷蔵で2日以内に飲み切りましょう。", "型Y"),
        ("価格", "1,000円台のティーカップでも十分です。", "価格"),
        ("A〜G（シェア）", "日本の紅茶市場でシェアが大きいブランドです。", "カテゴリ"),
    ]
    for label, text, want in cases:
        problems = xs.text_problems(text)
        check("検査NG: %s" % label, any(want in p for p in problems), problems)
    # 280 ちょうどは通る（全角140字＝X重み280）
    check("検査: 全角140字はX重み280で通る", xs.text_problems("あ" * 140) == [], xs.text_problems("あ" * 140))


def test_due_at():
    check("予約時刻: 2026-10-28 08:00 JST → 2026-10-27T23:00:00.000Z",
          xs.due_at_utc(dt.date(2026, 10, 28)) == "2026-10-27T23:00:00.000Z", xs.due_at_utc(dt.date(2026, 10, 28)))
    check("予約時刻: 月末をまたぐ 2026-11-01 → 2026-10-31T23:00:00.000Z",
          xs.due_at_utc(dt.date(2026, 11, 1)) == "2026-10-31T23:00:00.000Z")
    payload = xs.build_input("CH", "本文", "2026-10-27T23:00:00.000Z")
    check("createPost の入力: customScheduled・automatic・assets []・dueAt",
          payload == {"channelId": "CH", "text": "本文", "mode": "customScheduled", "schedulingType": "automatic",
                      "dueAt": "2026-10-27T23:00:00.000Z", "assets": []}, payload)


def test_post(tmp):
    week = os.path.join(tmp, "x-posts")
    os.makedirs(week)
    ledger = os.path.join(tmp, "x-standalone-posted.tsv")
    now = dt.datetime(2026, 10, 27, 12, 0, tzinfo=dt.timezone.utc)
    channels = {"twitter": ("CH-X", "kohaku_jikan")}
    path = write_week(week, "2026-10-26.md", [
        ("XS-0001", "2026-10-28", GOOD[0], True),
        ("XS-0002", "2026-10-29", GOOD[1], False),            # 審査行なし
        ("XS-0003", "2026-10-30", GOOD[2] + "\n2行目です。", True),
        ("XS-0004", "2026-10-27", GOOD[0], True),             # 過去（2026-10-26T23:00Z）
    ])
    rc, out = quiet(xs.cmd_check, path, directory=week)
    check("--check: 全件OK・審査行なしは警告", rc == 0 and "【警告】審査行" in out, out)

    fake = FakeBuffer()
    rc, out = quiet(xs.cmd_post, path, graphql=fake, now=now, ledger_path=ledger, directory=week,
                    channels=channels, today=dt.date(2026, 10, 27))
    sent = [c["dueAt"] for c in fake.calls]
    check("--post: 審査済みの未来の件だけを送る（XS-0001・0003）",
          rc == 0 and sent == ["2026-10-27T23:00:00.000Z", "2026-10-29T23:00:00.000Z"], (rc, sent, out))
    check("--post: 審査行の無い件は送らない（HELD_UNREVIEWED）", "HELD_UNREVIEWED: XS-0002" in out, out)
    check("--post: 過去の予定日は送らない", "SKIP XS-0004" in out and "過去" in out, out)
    check("--post: 2行の本文は改行つきで送る", fake.calls[1]["text"].endswith("\n2行目です。"), fake.calls[1]["text"])
    rows = xs.load_ledger(ledger)
    check("台帳: 予約済み2行・postId・予定日時・本文ファイル",
          [(r["ID"], r["postId"], r["状態"], r["予定日時"]) for r in rows]
          == [("XS-0001", "post1", "予約済み", "2026-10-28 08:00"), ("XS-0003", "post2", "予約済み", "2026-10-30 08:00")]
          and rows[0]["dueAt"] == "2026-10-27T23:00:00.000Z" and rows[0]["記録日"] == "2026-10-27", rows)

    fake2 = FakeBuffer()
    rc, out = quiet(xs.cmd_post, path, graphql=fake2, now=now, ledger_path=ledger, directory=week, channels=channels)
    check("二重予約の防止: 2回目は1件も送らない", rc == 0 and fake2.calls == [] and "台帳に予約済み" in out, out)

    # 同じ予定日の別の件（別ファイル・別ID）は送らない
    other = write_week(week, "2026-11-02.md", [("XS-0010", "2026-11-02", GOOD[0], True)])
    dup_dir = os.path.join(tmp, "dup")
    os.makedirs(dup_dir)
    path_dup = write_week(dup_dir, "2026-10-26.md", [("XS-0011", "2026-10-28", GOOD[2], True)])
    rc, out = quiet(xs.cmd_post, path_dup, graphql=FakeBuffer(), now=now, ledger_path=ledger, directory=week,
                    channels=channels)
    check("二重予約の防止: 同じ予定日に予約済みなら送らない", "同じ予定日" in out, out)
    os.remove(other)

    # ID の重複は検査NGで1件も送らない
    path_iddup = write_week(tmp, "2026-10-26.md", [("XS-0001", "2026-10-31", GOOD[0], True)])
    fake3 = FakeBuffer()
    rc, out = quiet(xs.cmd_post, path_iddup, graphql=fake3, now=now, ledger_path=ledger, directory=week,
                    channels=channels)
    check("ID の重複（他のファイル）は検査NG・1件も送らない", rc == 1 and fake3.calls == [], out)


def test_reject_and_switch(tmp):
    week = os.path.join(tmp, "x-posts2")
    os.makedirs(week)
    ledger = os.path.join(tmp, "ledger2.tsv")
    now = dt.datetime(2026, 10, 27, 12, 0, tzinfo=dt.timezone.utc)
    channels = {"twitter": ("CH-X", "kohaku_jikan")}
    path = write_week(week, "2026-10-26.md", [
        ("XS-0001", "2026-10-28", GOOD[0], True),
        ("XS-0002", "2026-10-29", GOOD[1], True),
        ("XS-0003", "2026-10-30", GOOD[2], True),
    ])
    fake = FakeBuffer(reject_at=1)
    rc, out = quiet(xs.cmd_post, path, graphql=fake, now=now, ledger_path=ledger, directory=week, channels=channels)
    rows = xs.load_ledger(ledger)
    check("拒否: 1件目が拒否されたら残りを送らない", rc == 1 and len(fake.calls) == 1, (rc, len(fake.calls)))
    check("拒否: 文言をそのまま出す", "dummy rejection" in out, out)
    check("拒否: 台帳に「失敗」1行（予約済みに数えない）",
          [(r["ID"], r["状態"], r["postId"]) for r in rows] == [("XS-0001", "失敗", "-")], rows)
    fake_retry = FakeBuffer()
    rc, out = quiet(xs.cmd_post, path, graphql=fake_retry, now=now, ledger_path=ledger, directory=week,
                    channels=channels)
    check("拒否のあとの再実行で失敗した件から送り直す", rc == 0 and len(fake_retry.calls) == 3, out)

    data_dir = os.path.join(tmp, "data")
    os.makedirs(data_dir)
    Path(os.path.join(data_dir, "buffer-auto-post-off.txt")).write_text("", encoding="utf-8")
    saved = ppb.DATA_DIR
    ppb.DATA_DIR = data_dir
    try:
        fake_sw = FakeBuffer()
        path2 = write_week(week, "2026-11-02.md", [("XS-0009", "2026-11-03", GOOD[0], True)])
        rc, out = quiet(xs.cmd_post, path2, graphql=fake_sw, now=now, ledger_path=ledger, directory=week,
                        channels=channels)
        check("停止スイッチ: 何も送らない", rc == 0 and fake_sw.calls == [] and "緊急停止スイッチ" in out, out)
    finally:
        ppb.DATA_DIR = saved


def test_prune_protection():
    def queue(nodes):
        def graphql(document, variables=None, operation_name=None):
            if operation_name == "Account":
                return {"account": {"organizations": [{"id": "org1"}]}}
            return {"posts": {"pageInfo": {"hasNextPage": False},
                              "edges": [{"node": n} for n in nodes]}}
        return graphql

    base = "https://kohaku-jikan.com/pin-images/pin%d.jpg"
    numbers, note = ppb.fetch_scheduled_pin_numbers(queue([
        {"id": "a", "assets": [{"source": base % 380}]},
        {"id": "b", "assets": []},                         # 記事なし投稿
        {"id": "c", "assets": None},
        {"id": "d", "assets": [{"source": base % 381}]},
    ]))
    check("掃除: 画像の無い投稿があっても止まらず、ピン番号を返す", numbers == {380, 381}, (numbers, note))
    check("掃除: 画像の無い投稿の件数を表示する", "画像の無い投稿 2件" in note, note)
    numbers, note = ppb.fetch_scheduled_pin_numbers(queue([
        {"id": "a", "assets": [{"source": base % 380}]},
        {"id": "e", "assets": [{"source": "https://example.com/other.jpg"}]},
    ]))
    check("掃除: 画像はあるが pinN.jpg でない投稿があれば今どおり止まる（None）", numbers is None, note)
    numbers, note = ppb.fetch_scheduled_pin_numbers(queue([{"id": "b", "assets": []}]))
    check("掃除: 記事なし投稿だけのキューは空集合（削除を止めない）", numbers == set(), (numbers, note))


def test_measure_exclusion(tmp):
    ledger = os.path.join(tmp, "x-ledger.tsv")
    Path(ledger).write_text("\t".join(xs.LEDGER_COLUMNS) + "\n"
                            + "XS-0001\t2026-10-28 08:00\t2026-10-27T23:00:00.000Z\tSA1\tx\t予約済み\t2026-10-27\n"
                            + "XS-0002\t2026-10-29 08:00\t2026-10-28T23:00:00.000Z\t-\tx\t失敗\t2026-10-27\n",
                            encoding="utf-8")
    check("measure: 台帳の予約済み postId だけを読む", ex.load_standalone_ids(ledger) == {"SA1"},
          ex.load_standalone_ids(ledger))

    def post(pid, day, views, service="twitter"):
        return {"entity_id": pid, "service": service, "text": "t",
                "sent_at": "%sT01:00:00Z" % day, "metrics": [{"type": "impressions", "value": views}]}

    # 開始 2026-10-28。前 = 10-14〜10-27 の X 投稿、後 = 10-28〜(週末日-7)
    posts = [post("P1", "2026-10-20", 100), post("P2", "2026-10-22", 120),
             post("P3", "2026-10-29", 200), post("P4", "2026-10-30", 220),
             post("SA1", "2026-10-28", 5000)]
    saved_ledger, saved_fetch = ex.X_STANDALONE_LEDGER, ex.fetch_sent_posts
    ex.X_STANDALONE_LEDGER = ledger
    ex.fetch_sent_posts = lambda lo, hi: ([dict(p) for p in posts], None)
    try:
        row = {c: "" for c in ex.COLUMNS}
        row.update({"実験ID": "EX-0003", "状態": "実行中", "種別": "ルール", "対象": "x-standalone",
                    "範囲": "channel=twitter", "主指標": "x-impr-7d", "開始日": "2026-10-28",
                    "判定日": "2026-11-25", "延長": "0"})
        week_end = dt.date(2026, 11, 8)
        experiments, _pending, _pins, got_posts, source, _w = ex.collect([row], week_end, os.path.join(tmp, "none.tsv"))
        entry = experiments[0]
        check("measure: 記事なし投稿を後の集計から除く（後=2件・中央値210）",
              entry["after"]["count"] == 2 and entry["after"]["median"] == 210, entry["after"])
        check("measure: 前の集計は2件（中央値110）", entry["before"]["count"] == 2 and entry["before"]["median"] == 110,
              entry["before"])
        check("measure: buffer の取得元に記事なし投稿の件数", source.get("standalone_posts") == 1, source)
        sns = ex.build_sns_posts(got_posts, week_end)
        marked = [p for p in sns["posts"] if p["standalone"]]
        check("sns-posts-7d: 記事なし投稿を残し post_id と standalone: true を付ける",
              len(marked) == 1 and marked[0]["post_id"] == "SA1", sns["posts"])
        # 対象が x-standalone 以外の実験でも同じに除く
        row2 = dict(row, 実験ID="EX-0004", 対象="post-text")
        experiments, *_ = ex.collect([row2], week_end, os.path.join(tmp, "none.tsv"))
        check("measure: x-standalone 以外の実験でも記事なし投稿を除く", experiments[0]["after"]["count"] == 2,
              experiments[0]["after"])
    finally:
        ex.X_STANDALONE_LEDGER, ex.fetch_sent_posts = saved_ledger, saved_fetch


def test_routine(tmp):
    ledger = os.path.join(tmp, "routine-ledger.tsv")
    check("routine: 台帳が無ければ判定しない", routine.x_standalone_unreserved(dt.date(2026, 11, 1), ledger) is False)
    Path(ledger).write_text("\t".join(xs.LEDGER_COLUMNS) + "\n"
                            + "XS-0001\t2026-10-28 08:00\tz\tp1\tx\t予約済み\t2026-10-27\n"
                            + "XS-0005\t2026-11-01 08:00\tz\t-\tx\t失敗\t2026-10-27\n", encoding="utf-8")
    check("routine: 翌日から7日間に予約済みがあれば警告なし（基準 10-27）",
          routine.x_standalone_unreserved(dt.date(2026, 10, 27), ledger) is False)
    check("routine: 翌日から7日間に予約済みが無ければ警告（基準 10-28・失敗は数えない）",
          routine.x_standalone_unreserved(dt.date(2026, 10, 28), ledger) is True)
    check("routine: 予約日の前日まで（基準 10-21 → 10-22〜10-28）は警告なし",
          routine.x_standalone_unreserved(dt.date(2026, 10, 21), ledger) is False)


ARTICLE = """---
title: テスト記事
category: {cat}
status: published
---

## 選び方

カップは口が広いものほど香りが立ちやすく、色も見やすいといわれます。厚手のものは冷めにくく、薄手のものは口当たりが軽くなります。

## よくある質問

**Q. 何を基準に選べばよいですか？**
まず使う場面を決めると迷いません。来客用なら揃いのセット、自分用なら手になじむ重さを優先するのが選びやすい順番です。

**Q. 値段はどのくらいですか？**
1,000円台から選べるものもあります。予算に合わせて選びやすいのが特徴で、迷ったら定番の形を選ぶと失敗しにくくなります。

**Q. 実際の使い心地は？**
実際に淹れ比べてみると、薄手のほうが香りを感じやすい印象でした。ここでは厚手と薄手の違いを整理しています。

**Q. 冷めた紅茶は置いておけますか？**
常温で長く置くと傷みやすいため、早めに飲み切るのがよいとされます。作り置きをする場合は冷蔵庫に入れてください。
"""


def test_candidates(tmp):
    posts = os.path.join(tmp, "posts")
    week = os.path.join(tmp, "x-posts-cand")
    os.makedirs(posts)
    os.makedirs(week)
    Path(os.path.join(posts, "s-cup.md")).write_text(ARTICLE.format(cat="teaware"), encoding="utf-8")
    Path(os.path.join(posts, "s-tea.md")).write_text(ARTICLE.format(cat="tea-leaves"), encoding="utf-8")
    Path(os.path.join(posts, "s-used.md")).write_text(ARTICLE.format(cat="gift"), encoding="utf-8")
    # s-used を直近8週の材料に使った扱いにする
    Path(os.path.join(week, "2026-10-19.md")).write_text(
        "## XS-0001\n- 予定日: 2026-10-20\n- 材料: s-used ＃よくある質問\n- 本文: x\n", encoding="utf-8")
    today = dt.date(2026, 10, 27)
    cands, excluded, used = xs.collect_candidates(today, posts, week)
    heads = [(c["slug"], c["heading"]) for c in cands]
    check("候補: 直近8週に使った slug を除く", "s-used" in used and all(s != "s-used" for s, _ in heads), heads)
    check("候補: 価格・体験・型Y の単位を除く",
          not any("値段" in h or "使い心地" in h or "冷めた" in h for _, h in heads)
          and excluded.get("A〜G") and excluded.get("体験表現") and excluded.get("型Y"), (heads, excluded))
    check("候補: よくある質問と選び方の節から拾う（記事ごとに2件）", len(cands) == 4
          and {c["kind"] for c in cands} == {"faq", "guide"}, heads)
    check("候補: カテゴリが交互に並ぶ", [c["category"] for c in cands[:2]] in (["tea-leaves", "teaware"],),
          [c["category"] for c in cands])
    rc, out = quiet(xs.cmd_candidates, 10, today=today, posts_dir=posts, directory=week,
                    ledger_path=os.path.join(tmp, "no-ledger.tsv"))
    check("候補: NEXT_ID は既存の最大＋1", "NEXT_ID XS-0002" in out, out)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    tmp = tempfile.mkdtemp(prefix="test-x-standalone-")
    try:
        test_text_checks()
        test_due_at()
        test_post(tmp)
        test_reject_and_switch(tmp)
        test_prune_protection()
        test_measure_exclusion(tmp)
        test_routine(tmp)
        test_candidates(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILURES:
        print("FAILED %d件: %s" % (len(FAILURES), " / ".join(FAILURES)))
        return 1
    print("ALL_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
