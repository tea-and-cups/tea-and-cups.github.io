# -*- coding: utf-8 -*-
r"""production-run.py の検証（T1〜T6）と、投稿文生成の不変性確認（T7）。

一時ディレクトリにGitリポジトリとダミー台帳を作って実行する。
本物の site / data には一切触れない（--fingerprint を除く）。

  T1: A・M・D と public/pin-images の D を含む差分で、new / changed / deleted が
      正しく出て、刈り込みが除外される
  T2: 同じ session_id で run1 を確定したあと run2 を開き、post を記録すると
      run2 の _steps にだけ入り、run1 には混入しない
  T3: 区間が重なる2つのrunが、どちらも completed にならない。Git由来のoutputが
      unresolved に入り、どちらのrunの outputs にも入らない
  T4: publish_attempt がNGで outputs が0件なら handoff が failed で保存される。
      activity も差分も無いrunは handoff を書かない
  T5: changed の記事だけのrunが completed になる。new の記事があってPinが
      未投稿のrunは partial になる
  T6: 他のsessionの開いているrunについて、transcriptが古ければ代理確定され、
      新しければ overlap が付く

--validate-growth <handoffのpath>:
  growth-agent/scripts/growth_routine.py の validate_production_handoff() を
  そのまま呼び、Growth側がこのhandoffを受け付けるかを確かめる。
  growth-agent 側は読み取り専用で、import以外の操作をしない。

--smoke:
  本物のプロジェクトに対して、open が使う読み取り処理（Pin台帳・Buffer台帳・
  site HEAD・transcriptの解決）だけを実行して結果を出す。書き込みは一切行わず、
  runも開かない。一時ディレクトリでは確かめられない「本物の台帳・リポジトリで
  例外が出ないこと」を確認するためのもの。

--fingerprint（T7）:
  本物の output/pins/ からピン286〜288を読み、Pinterest payload・build_text・
  build_instagram_text の出力のsha256をJSONで出す。変更前後で同じJSONになれば
  投稿文生成に影響していないと言える。読み取りのみで、APIへは一切送らない。

使い方:
  python site/scripts/test-production-run.py
  python site/scripts/test-production-run.py --fingerprint
"""

import datetime
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _load(file_name, module_name):
    path = os.path.join(SCRIPT_DIR, file_name)
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pr = _load("production-run.py", "production_run")
JST = pr.JST

FAILURES = []
CHECKS = [0]


def check(label, condition, detail=""):
    CHECKS[0] += 1
    if condition:
        print("  OK  %s" % label)
    else:
        print("  NG  %s%s" % (label, ("  … " + detail) if detail else ""))
        FAILURES.append(label)


# --------------------------------------------------------------------------
# 一時プロジェクトの用意
# --------------------------------------------------------------------------

def git(root, *args):
    return subprocess.run(
        ["git", "-C", os.path.join(root, "site"),
         "-c", "user.email=test@example.invalid", "-c", "user.name=test"] + list(args),
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def make_project(tmp, pin_ledger_lines="", buffer_ledger_lines=""):
    """<tmp>/site をGitリポジトリにし、台帳とピンファイルを置く。"""
    root = os.path.join(tmp, "proj")
    site = os.path.join(root, "site")
    os.makedirs(os.path.join(site, "src", "content", "posts"), exist_ok=True)
    os.makedirs(os.path.join(site, "public", "images"), exist_ok=True)
    os.makedirs(os.path.join(site, "public", "pin-images"), exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", site], check=True,
                   capture_output=True, timeout=60)

    write(os.path.join(site, "src", "content", "posts", "old-article.md"), "old\n")
    # T1で「run開始前から存在し、run中に削除される記事」として使う。
    write(os.path.join(site, "src", "content", "posts", "to-delete.md"), "bye\n")
    write(os.path.join(site, "public", "pin-images", "pin100.jpg"), "pin100\n")
    write(os.path.join(site, "README.md"), "readme\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")

    write(os.path.join(root, "data", "pin-posted.md"), pin_ledger_lines)
    write(os.path.join(root, "data", "buffer-posted.md"), buffer_ledger_lines)
    os.makedirs(os.path.join(root, "output", "pins"), exist_ok=True)
    return root


def make_transcripts(tmp):
    directory = os.path.join(tmp, "transcripts")
    os.makedirs(directory, exist_ok=True)
    return directory


def touch_transcript(directory, session_id, when):
    path = os.path.join(directory, session_id + ".jsonl")
    write(path, "{}\n")
    stamp = when.timestamp()
    os.utime(path, (stamp, stamp))


def load_handoff(root, run_id, opened_date):
    path = os.path.join(pr.handoff_dir(root),
                        "%s_%s.json" % (opened_date, pr.safe_run_id(run_id)))
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def by_entity(document):
    return {item["entity_id"]: item for item in document["outputs"]}


# --------------------------------------------------------------------------
# T1
# --------------------------------------------------------------------------

def t1(tmp):
    print("T1: new / changed / deleted と刈り込みの除外")
    root = make_project(os.path.join(tmp, "t1"))
    site = os.path.join(root, "site")
    transcripts = make_transcripts(os.path.join(tmp, "t1"))
    sid = "sess-t1"
    now = datetime.datetime(2026, 9, 20, 5, 0, tzinfo=JST)
    touch_transcript(transcripts, sid, now)

    record, _ = pr.open_run(root=root, session_id=sid, now=now, transcripts_dir=transcripts)

    write(os.path.join(site, "src", "content", "posts", "new-article.md"), "new\n")
    write(os.path.join(site, "src", "content", "posts", "old-article.md"), "old changed\n")
    write(os.path.join(site, "public", "images", "hero.webp"), "hero\n")
    write(os.path.join(site, "public", "pin-images", "pin101.jpg"), "pin101\n")
    # 刈り込み（pin-images の削除）は deleted から除外される
    os.remove(os.path.join(site, "public", "pin-images", "pin100.jpg"))
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "work")

    # run開始前から存在した記事を消して deleted を作る
    os.remove(os.path.join(site, "src", "content", "posts", "to-delete.md"))
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "delete to-delete")

    pr.finalize_run(root=root, session_id=sid, now=now + datetime.timedelta(minutes=10))
    document = load_handoff(root, record["run_id"], record["opened_date"])
    check("T1 handoffが作られる", document is not None)
    if not document:
        return
    items = by_entity(document)

    check("T1 新規記事が new", items.get("src/content/posts/new-article.md", {}).get("change") == "new",
          str(items.get("src/content/posts/new-article.md")))
    check("T1 既存記事が changed", items.get("src/content/posts/old-article.md", {}).get("change") == "changed")
    check("T1 hero画像が new / article_image",
          items.get("public/images/hero.webp", {}).get("asset_class") == "article_image")
    check("T1 Pin画像が new / pin_image",
          items.get("public/pin-images/pin101.jpg", {}).get("change") == "new")
    check("T1 pin-images の削除は載らない", "public/pin-images/pin100.jpg" not in items)
    deleted = items.get("src/content/posts/to-delete.md")
    check("T1 記事の削除が deleted", deleted is not None and deleted.get("change") == "deleted")
    check("T1 deleted の content_identity は null",
          deleted is not None and deleted.get("content_identity") is None)
    check("T1 deleted の previous は git-blob",
          deleted is not None and str(deleted.get("previous_content_identity", "")).startswith("git-blob:"))
    check("T1 deleted の evidence_refs に削除commitが入る",
          deleted is not None and len(deleted.get("evidence_refs") or []) >= 1)
    check("T1 new の記事に published_at が付く",
          items.get("src/content/posts/new-article.md", {}).get("published_at") is not None)
    check("T1 changed の identity が前後で異なる",
          items.get("src/content/posts/old-article.md", {}).get("content_identity")
          != items.get("src/content/posts/old-article.md", {}).get("previous_content_identity"))
    check("T1 site配下の対象外pathは載らない", "README.md" not in items)


# --------------------------------------------------------------------------
# T2
# --------------------------------------------------------------------------

def t2(tmp):
    print("T2: 同じsession_idの連番runでstepが混ざらない")
    root = make_project(os.path.join(tmp, "t2"))
    transcripts = make_transcripts(os.path.join(tmp, "t2"))
    sid = "sess-t2"
    now = datetime.datetime(2026, 9, 20, 5, 0, tzinfo=JST)
    touch_transcript(transcripts, sid, now)

    os.environ["CLAUDE_CODE_SESSION_ID"] = sid
    run1, _ = pr.open_run(root=root, session_id=sid, now=now, transcripts_dir=transcripts)
    pr.record_step("post", root=root, pin_num=1, channel="pinterest",
                   payload_sha256="a" * 64, ok=True)
    pr.finalize_run(root=root, session_id=sid, now=now + datetime.timedelta(minutes=5))

    run2, _ = pr.open_run(root=root, session_id=sid,
                          now=now + datetime.timedelta(minutes=10), transcripts_dir=transcripts)
    pr.record_step("post", root=root, pin_num=2, channel="twitter",
                   payload_sha256="b" * 64, ok=True)

    check("T2 run1とrun2のrun_idが異なる", run1["run_id"] != run2["run_id"],
          "%s / %s" % (run1["run_id"], run2["run_id"]))
    check("T2 run2の連番が2", run2["run_id"].endswith(":2"), run2["run_id"])
    steps1 = pr.read_steps(root, run1["run_id"])
    steps2 = pr.read_steps(root, run2["run_id"])
    check("T2 run1のstepは1件のまま", len(steps1) == 1, str(steps1))
    check("T2 run2のstepは1件だけ", len(steps2) == 1, str(steps2))
    check("T2 run2のstepはpin2", steps2 and steps2[0].get("pin_num") == 2)
    check("T2 run1のstepにpin2は混入しない", all(s.get("pin_num") != 2 for s in steps1))


# --------------------------------------------------------------------------
# T3
# --------------------------------------------------------------------------

def t3(tmp):
    print("T3: 区間の重なる2runはどちらもcompletedにならない")
    root = make_project(os.path.join(tmp, "t3"))
    site = os.path.join(root, "site")
    transcripts = make_transcripts(os.path.join(tmp, "t3"))
    sid_a, sid_b = "sess-t3a", "sess-t3b"
    t0 = datetime.datetime(2026, 9, 20, 5, 0, tzinfo=JST)
    touch_transcript(transcripts, sid_a, t0)
    touch_transcript(transcripts, sid_b, t0)

    run_a, _ = pr.open_run(root=root, session_id=sid_a, now=t0, transcripts_dir=transcripts)
    touch_transcript(transcripts, sid_a, t0 + datetime.timedelta(minutes=5))
    run_b, warn_b = pr.open_run(root=root, session_id=sid_b,
                                now=t0 + datetime.timedelta(minutes=5),
                                transcripts_dir=transcripts)
    check("T3 2本目のopenで【警告】が出る", any(w.startswith("【警告】") for w in warn_b), str(warn_b))

    write(os.path.join(site, "src", "content", "posts", "overlap-article.md"), "x\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "overlap work")

    pr.finalize_run(root=root, session_id=sid_a, now=t0 + datetime.timedelta(minutes=10))
    pr.finalize_run(root=root, session_id=sid_b, now=t0 + datetime.timedelta(minutes=20))

    doc_a = load_handoff(root, run_a["run_id"], run_a["opened_date"])
    doc_b = load_handoff(root, run_b["run_id"], run_b["opened_date"])
    check("T3 run Aのhandoffがある", doc_a is not None)
    check("T3 run Bのhandoffがある", doc_b is not None)
    if not (doc_a and doc_b):
        return
    check("T3 run Aがcompletedでない", doc_a["status"] != "completed", doc_a["status"])
    check("T3 run Bがcompletedでない", doc_b["status"] != "completed", doc_b["status"])
    check("T3 run AのoutputsにGit由来が入らない",
          "src/content/posts/overlap-article.md" not in by_entity(doc_a))
    check("T3 run BのoutputsにGit由来が入らない",
          "src/content/posts/overlap-article.md" not in by_entity(doc_b))
    check("T3 run Aのunresolvedに候補が列挙される",
          any("overlap-article.md" in u for u in doc_a["unresolved"]), str(doc_a["unresolved"]))
    check("T3 run Bのunresolvedに候補が列挙される",
          any("overlap-article.md" in u for u in doc_b["unresolved"]), str(doc_b["unresolved"]))
    check("T3 coverageがpartial", doc_a["coverage"]["state"] == "partial")


# --------------------------------------------------------------------------
# T4
# --------------------------------------------------------------------------

def t4(tmp):
    print("T4: failed の保存と、活動なしrunの非生成")
    root = make_project(os.path.join(tmp, "t4"))
    transcripts = make_transcripts(os.path.join(tmp, "t4"))
    sid = "sess-t4"
    now = datetime.datetime(2026, 9, 20, 5, 0, tzinfo=JST)
    touch_transcript(transcripts, sid, now)

    os.environ["CLAUDE_CODE_SESSION_ID"] = sid
    record, _ = pr.open_run(root=root, session_id=sid, now=now, transcripts_dir=transcripts)
    pr.record_step("publish_attempt", root=root, slug="broken-article", dry_run=False,
                   result="NG", failed_check="check-fact-source.py")
    pr.finalize_run(root=root, session_id=sid, now=now + datetime.timedelta(minutes=5))
    document = load_handoff(root, record["run_id"], record["opened_date"])
    check("T4 failedのhandoffが保存される", document is not None and document["status"] == "failed",
          str(document and document["status"]))
    check("T4 failedのoutputsは0件", document is not None and document["outputs"] == [])
    check("T4 failure_reasonに失敗したチェック名が入る",
          document is not None and "check-fact-source.py" in (document["failure_reason"] or ""),
          str(document and document["failure_reason"]))

    sid2 = "sess-t4-quiet"
    touch_transcript(transcripts, sid2, now)
    record2, _ = pr.open_run(root=root, session_id=sid2,
                             now=now + datetime.timedelta(minutes=10),
                             transcripts_dir=transcripts)
    path = pr.finalize_run(root=root, session_id=sid2,
                           now=now + datetime.timedelta(minutes=12))
    check("T4 活動なしrunはhandoffを書かない", path is None, str(path))
    check("T4 活動なしrunでもclose行は残る",
          any(r["run_id"] == record2["run_id"] and r["event"] == "close"
              for r in pr.read_runs(root)))


# --------------------------------------------------------------------------
# T5
# --------------------------------------------------------------------------

PIN_TEMPLATE = """# ピン{num}

- ステータス: 画像生成済み（output/Pin-images/dummy.png）
- 誘導先URL: https://example.invalid/posts/{slug}/?utm_source=pinterest&utm_campaign={slug}&utm_content=pin{num}
ボード: 器・道具選び

## 投稿文
タイトル: t
説明文: d #紅茶
- X用説明文: x #紅茶
"""


def t5(tmp):
    print("T5: changedのみ=completed / newでPin未投稿=partial")
    root = make_project(os.path.join(tmp, "t5"))
    site = os.path.join(root, "site")
    transcripts = make_transcripts(os.path.join(tmp, "t5"))
    now = datetime.datetime(2026, 9, 20, 5, 0, tzinfo=JST)

    sid = "sess-t5-changed"
    touch_transcript(transcripts, sid, now)
    record, _ = pr.open_run(root=root, session_id=sid, now=now, transcripts_dir=transcripts)
    write(os.path.join(site, "src", "content", "posts", "old-article.md"), "link swapped\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "swap product link")
    pr.finalize_run(root=root, session_id=sid, now=now + datetime.timedelta(minutes=5))
    document = load_handoff(root, record["run_id"], record["opened_date"])
    check("T5 changedのみのrunがcompleted",
          document is not None and document["status"] == "completed",
          str(document and (document["status"], document["failure_reason"])))
    check("T5 changedのみのrunのcoverageはcomplete",
          document is not None and document["coverage"]["state"] == "complete")

    sid2 = "sess-t5-new"
    touch_transcript(transcripts, sid2, now)
    write(os.path.join(root, "output", "pins", "2026-09-20-pin-900-fresh-article-01.md"),
          PIN_TEMPLATE.format(num=900, slug="fresh-article"))
    record2, _ = pr.open_run(root=root, session_id=sid2,
                             now=now + datetime.timedelta(minutes=10),
                             transcripts_dir=transcripts)
    write(os.path.join(site, "src", "content", "posts", "fresh-article.md"), "fresh\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "publish fresh-article")
    pr.finalize_run(root=root, session_id=sid2, now=now + datetime.timedelta(minutes=15))
    document2 = load_handoff(root, record2["run_id"], record2["opened_date"])
    check("T5 new記事でPin未投稿のrunがpartial",
          document2 is not None and document2["status"] == "partial",
          str(document2 and (document2["status"], document2["failure_reason"])))
    check("T5 partialの理由にピン番号が出る",
          document2 is not None and "900" in (document2["failure_reason"] or ""),
          str(document2 and document2["failure_reason"]))


# --------------------------------------------------------------------------
# T6
# --------------------------------------------------------------------------

def t6(tmp):
    print("T6: 他sessionの開いているrunの代理確定とoverlap")
    root = make_project(os.path.join(tmp, "t6"))
    site = os.path.join(root, "site")
    transcripts = make_transcripts(os.path.join(tmp, "t6"))
    t0 = datetime.datetime(2026, 9, 20, 5, 0, tzinfo=JST)

    stale_sid = "sess-t6-stale"
    touch_transcript(transcripts, stale_sid, t0)
    stale_run, _ = pr.open_run(root=root, session_id=stale_sid, now=t0,
                               transcripts_dir=transcripts)
    write(os.path.join(site, "src", "content", "posts", "crashed.md"), "crashed\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "crashed work")

    later = t0 + datetime.timedelta(minutes=45)
    new_sid = "sess-t6-new"
    touch_transcript(transcripts, new_sid, later)
    _record, warnings = pr.open_run(root=root, session_id=new_sid, now=later,
                                    transcripts_dir=transcripts)
    check("T6 代理確定の【警告】が出る",
          any("代理確定" in w for w in warnings), str(warnings))
    document = load_handoff(root, stale_run["run_id"], stale_run["opened_date"])
    check("T6 代理確定でhandoffが書かれる", document is not None)
    check("T6 代理確定のclose_reasonがsession_end_not_observed",
          any(r["run_id"] == stale_run["run_id"] and r["event"] == "close"
              and r["close_reason"] == "session_end_not_observed"
              for r in pr.read_runs(root)))
    check("T6 代理確定runはcompletedにならない",
          document is not None and document["status"] != "completed",
          str(document and document["status"]))
    check("T6 代理確定runの開始記録が消える",
          pr.find_open_record(root, stale_sid) is None)

    fresh_sid = "sess-t6-fresh"
    touch_transcript(transcripts, fresh_sid, later + datetime.timedelta(minutes=1))
    _r2, warn2 = pr.open_run(root=root, session_id=fresh_sid,
                             now=later + datetime.timedelta(minutes=2),
                             transcripts_dir=transcripts)
    check("T6 生存中のrunは代理確定されない", pr.find_open_record(root, new_sid) is not None)
    check("T6 生存中のrunにはoverlapが付く",
          any("重なっています" in w for w in warn2), str(warn2))
    other = pr.find_open_record(root, new_sid)
    check("T6 双方の開始記録にoverlap_withが入る",
          bool(other.get("overlap_with")), str(other))


# --------------------------------------------------------------------------
# T7: 投稿文生成の不変性
# --------------------------------------------------------------------------

def fingerprint():
    """本物の output/pins/ からピン286〜288の投稿文・payloadのsha256を出す。"""
    pinterest = _load("post-pins-to-pinterest.py", "fp_post_pins_to_pinterest")
    buffer_mod = _load("post-pins-to-buffer.py", "fp_post_pins_to_buffer")

    captured = {}

    def fake_request(method, path, token, body=None, timeout=None):
        captured["body"] = body
        return {"id": "dummy"}

    pinterest.pinterest_api.request = fake_request

    result = {}
    pin_files = pinterest._load_check_pin_posting_status().extract_created_pins()
    for pin_num in (286, 287, 288):
        key = "pin%d" % pin_num
        result[key] = {}
        file_name = pin_files[pin_num][0]

        fields, reason = pinterest.parse_pin_file(pin_num, file_name)
        if fields is None:
            result[key]["pinterest_payload"] = "PARSE_FAILED: %s" % reason
        else:
            pinterest.post_pin("dummy-token", fields, "dummy-board-id")
            result[key]["pinterest_payload"] = pr.sha256_hex(pr.canonical_json(captured["body"]))

        bfields, breason = buffer_mod.parse_pin_file(file_name)
        if bfields is None:
            result[key]["buffer"] = "PARSE_FAILED: %s" % breason
            continue
        for service in buffer_mod.SERVICES:
            text, _url = buffer_mod.build_text(pin_num, bfields, service)
            result[key]["build_text:%s" % service] = (
                pr.sha256_hex(text) if text is not None else "NONE"
            )
        result[key]["build_instagram_text"] = pr.sha256_hex(
            buffer_mod.build_instagram_text(bfields["description"])
        )
    return result


# --------------------------------------------------------------------------

def validate_growth(path):
    """growth-agent の validator をそのまま呼んで結果を表示する（読み取り専用）。"""
    import datetime as _dt

    growth_scripts = os.path.join(
        os.path.dirname(os.path.dirname(SCRIPT_DIR)), "growth-agent", "scripts"
    )
    if growth_scripts not in sys.path:
        sys.path.insert(0, growth_scripts)
    spec = importlib.util.spec_from_file_location(
        "growth_routine", os.path.join(growth_scripts, "growth_routine.py")
    )
    growth = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(growth)

    with open(path, encoding="utf-8") as f:
        document = json.load(f)
    target = _dt.date.fromisoformat(document["target_date"])

    print("validator: growth-agent/scripts/growth_routine.py validate_production_handoff()")
    print("対象: %s" % path)
    print("PRODUCER_CHANGE_CLASSES = %s" % sorted(growth.PRODUCER_CHANGE_CLASSES))
    classes = sorted({item.get("change") for item in document["outputs"]})
    print("このhandoffの change 一覧 = %s" % classes)
    try:
        growth.validate_production_handoff(document, target)
    except Exception as e:
        print("NG  %s: %s" % (type(e).__name__, e))
        return 1
    print("OK  Growth側のvalidatorを通過しました")
    return 0


def smoke():
    """本物のプロジェクトに対する読み取りのみの確認（書き込みなし）。"""
    root = pr.PROJECT_ROOT
    print("PROJECT_ROOT = %s" % root)
    print("site HEAD = %s" % pr.git_head(root))
    pins = pr.pin_ledger_numbers(root)
    print("Pin台帳の投稿済み番号: %d件（最大 %s）" % (len(pins), pins[-1] if pins else "-"))
    pairs = pr.buffer_ledger_pairs(root)
    print("Buffer台帳の組: %d件" % len(pairs))
    print("対象channel（Pinterest + Buffer）: %s" % (["pinterest"] + list(pr.buffer_services())))
    directory = pr.default_transcripts_dir(root)
    print("transcriptディレクトリ: %s（存在: %s）" % (directory, os.path.isdir(directory or "")))
    sid = pr.session_id_from_env()
    print("環境変数から得た session_id: %s" % sid)
    if sid:
        print("そのtranscriptの最終更新: %s" % pr.transcript_mtime(sid, root))
    print("現在開いているrun: %s" % [r["run_id"] for r in pr.list_open_records(root)])
    return 0


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if "--smoke" in argv:
        return smoke()

    if "--validate-growth" in argv:
        return validate_growth(argv[argv.index("--validate-growth") + 1])

    if "--fingerprint" in argv:
        print(json.dumps(fingerprint(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    saved = os.environ.get("CLAUDE_CODE_SESSION_ID")
    saved_hook = os.environ.pop("CLAUDE_HOOK_SESSION_ID", None)
    tmp = tempfile.mkdtemp(prefix="production-run-test-")
    try:
        for func in (t1, t2, t3, t4, t5, t6):
            func(tmp)
            print("")
    finally:
        if saved is None:
            os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
        else:
            os.environ["CLAUDE_CODE_SESSION_ID"] = saved
        if saved_hook is not None:
            os.environ["CLAUDE_HOOK_SESSION_ID"] = saved_hook
        shutil.rmtree(tmp, ignore_errors=True)

    print("=== %d件中 %d件が失敗 ===" % (CHECKS[0], len(FAILURES)))
    for label in FAILURES:
        print("  - %s" % label)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
