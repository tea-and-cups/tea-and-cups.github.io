# -*- coding: utf-8 -*-
r"""動画を作る（本運用の入口・D-0300）。部品は site/scripts/video/ にあり、このスクリプトから import して使う。

道具と素材（CLI・ffmpeg・ロゴ・参照 WAV・字体・gsap）は実行環境（data/video-runtime.json・D-0299）から引く。
起動の最初に check-video-runtime.py を呼び、RUNTIME_OK でなければ何もせずに止める。
作品の場所は output/videos/<動画>/（<動画> はフォルダ名。例: video-1）。中身:
  script.json（台本）・video-N.film.json（型に差し込む1本ごとのデータ）・prompts/・images/・voice/・work/・composition/・qa/
  work/video-N.raw.mp4（書き出し）・video-N.mp4（faststart の完成）・video-N.qa.json（機械QA）・video-N.build.json（段ごとの記録）

操作:
  next [--create <slug>]           次の番号 N（data/video-posted.md と output/videos/video-* の最大＋1）と、動画の無い公開記事を出す。
                                   --create で output/videos/video-N/ の骨組み（script.json の雛形・prompts/）を作る
  check-script <動画>              script.json の形と句の字数（1行14字・1画面30字）を確かめ、読み辞書を当てた声の入力を出す（声は作らない）
  build <動画> [--from 段|--only 段] [--redo S3,S4]
                                   段: voice → images → comp → render → finalize → qa（--from はその段から最後まで、--only はその段だけ）
                                   voice: 声の無い文（--redo の文は作り直し）だけ TTS → take の選択・末尾の処理・つなぎ → 読み違いの目安
                                   images: 無い写真だけ gateway で作る → 1440×2160 に整える
                                   comp: 型テンプレート＋video-N.film.json → composition/
                                   render: 全編の書き出し（所要と履歴の増加量を記録）／finalize: faststart だけ／qa: video-N.qa.json
  status <動画>                     段ごとの成果物・sha256・qa の合否・台帳（Pinterest・Buffer）・書き出しの履歴を、読み取りだけで出す
  clean-history [--keep 1]          書き出しの履歴（実行環境の home の history の下の UUID 形のフォルダ）を、新しい keep 件を残して消す

終了コード: 0 正常 / 1 段の失敗・検査の NG・qa の不合格 / 2 実行環境の照合が RUNTIME_OK でない・引数の誤り
"""

import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from video import runtime  # noqa: E402

ROOT = Path(runtime.PROJECT_ROOT)
VIDEOS = ROOT / "output" / "videos"
POSTS = ROOT / "site" / "src" / "content" / "posts"
PIN_LEDGER = ROOT / "data" / "video-posted.md"
BUFFER_LEDGER = ROOT / "data" / "video-buffer-posted.tsv"
STAGES = ("voice", "images", "comp", "render", "finalize", "qa")
LINE_CHARS, SCREEN_CHARS = 14, 30


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def video_dir(name):
    d = VIDEOS / name
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", name) or not d.is_dir():
        raise SystemExit(f"動画フォルダが無い: output/videos/{name}")
    return d


def number(d):
    found = sorted(d.glob("video-*.film.json"))
    if found:
        return json.loads(found[0].read_text(encoding="utf-8"))["n"]
    m = re.match(r"^video-(\d+)$", d.name)
    if not m:
        raise SystemExit(f"動画の番号が分からない: {d}")
    return int(m.group(1))


def paths(d):
    n = number(d)
    return {"n": n, "raw": d / "work" / f"video-{n}.raw.mp4", "final": d / f"video-{n}.mp4", "qa": d / f"video-{n}.qa.json",
            "log": d / f"video-{n}.build.json", "render_log": d / "work" / "render.log"}


def record(d, stage, rec):
    p = paths(d)["log"]
    log = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"runs": []}
    log["runs"].append({"stage": stage, "at": now(), **rec})
    p.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


# ---- next

def posted_numbers():
    out = {}
    if PIN_LEDGER.exists():
        for line in PIN_LEDGER.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^動画(\d+) \| ([^ |]+) \|", line)
            if m:
                out[int(m.group(1))] = m.group(2)
    return out


def cmd_next(args):
    posted = posted_numbers()
    local = [int(m.group(1)) for p in VIDEOS.glob("video-*") if p.is_dir() and (m := re.match(r"^video-(\d+)$", p.name))]
    n = max([0, *posted, *local]) + 1
    print(f"NEXT_N {n}（台帳の最大 {max(posted, default=0)}・作業フォルダの最大 {max(local, default=0)}）")
    done = set(posted.values())
    cands = []
    for f in POSTS.glob("*.md"):
        text = f.read_text(encoding="utf-8")
        head = text.split("---", 2)[1] if text.startswith("---") else ""
        if "status: published" not in head:
            continue
        slug = re.search(r"^slug: (.+)$", head, re.M)
        date = re.search(r"^date: (.+)$", head, re.M)
        if slug and slug.group(1).strip() not in done:
            cands.append((date.group(1).strip() if date else "", slug.group(1).strip()))
    print("CANDIDATES（動画の無い公開記事・新しい順に5件）")
    for date, slug in sorted(cands, reverse=True)[:5]:
        print(f"  {date} {slug}")
    if args.create:
        if not (POSTS / f"{args.create}.md").exists():
            print(f"記事が無い: site/src/content/posts/{args.create}.md")
            return 1
        d = VIDEOS / f"video-{n}"
        for sub in ("prompts", "images", "voice/raw", "work"):
            (d / sub).mkdir(parents=True, exist_ok=True)
        sc = d / "script.json"
        if not sc.exists():
            sc.write_text(json.dumps({
                "_note": f"動画{n}の台本。phrases＝画面の字（句ごと）。voice は phrases を漢字のまま入力し、data/video-lexicon.json（共通の例外表）＋video-{n}.film.json の lexicon（記事ごとの例外。film.json が無い間はこの lexicon）で読み違える語だけ直す。"
                         "事実の出どころは source（記事の本文）。記事に無い事実・商品・体験は足さない。",
                "slug": args.create, "article_url": f"https://kohaku-jikan.com/posts/{args.create}/", "lexicon": [], "gap_after": {},
                "sentences": [{"id": "S1", "scene": "hook", "phrases": [], "source": ""}]}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"CREATED output/videos/video-{n}/（script.json・prompts/）。video-{n}.film.json は型のデータとして別に作る")
    return 0


# ---- check-script

def cmd_check_script(args):
    from video.lexicon import applied, merged_lexicon, voice_text
    d = video_dir(args.video)
    sc = json.loads((d / "script.json").read_text(encoding="utf-8"))
    ng = []
    for k in ("slug", "article_url", "sentences"):
        if k not in sc:
            ng.append(f"必須の項目が無い: {k}")
    ids = set()
    for i, s in enumerate(sc.get("sentences", [])):
        sid = s.get("id", f"#{i + 1}")
        if sid in ids:
            ng.append(f"{sid}: id が重複")
        ids.add(sid)
        if not s.get("scene"):
            ng.append(f"{sid}: scene が無い")
        if not s.get("phrases") or not all(isinstance(p, str) and p for p in s["phrases"]):
            ng.append(f"{sid}: phrases が空")
        for p in s.get("phrases", []):
            if len(p) > SCREEN_CHARS:
                ng.append(f"{sid}: 句が {len(p)}字（1画面 {SCREEN_CHARS}字まで）: {p}")
            elif len(p) > LINE_CHARS:
                print(f"INFO {sid}: 句が {len(p)}字（1行 {LINE_CHARS}字を超えるので2行になる）: {p}")
    lex = merged_lexicon(d)
    print("id\tscreen\tvoice\texceptions")
    for s in sc.get("sentences", []):
        if s.get("phrases"):
            v = voice_text(s, lex)
            print(f"{s['id']}\t{''.join(s['phrases'])}\t{v}\t{applied(s, lex)}")
    for m in ng:
        print("NG", m)
    print("SCRIPT_OK" if not ng else f"SCRIPT_NG {len(ng)}件")
    return 0 if not ng else 1


# ---- build

def stage_voice(d, rt, args):
    from video import voice
    redo = [x for x in (args.redo or "").split(",") if x]
    need = sorted(set(voice.raw_missing(d)) | set(redo))
    jobs_path, n_jobs, _ = voice.make_jobs(d, rt, only=set(need))
    rec = {"tts_sentences": need}
    if need:
        print(f"voice: TTS {need}（{n_jobs}本）")
        voice.run_tts(d, rt, jobs_path)
    tl, rows = voice.build(d, rt)
    asr_path = voice.asr(d)
    rec.update({"duration": tl["duration"], "narration_sha256": runtime_sha(d / "work" / "narration.wav"),
                "tail_loud": [r["id"] for r in rows if r["tail_loud"]], "tail_guard": [r["id"] for r in rows if r["tail_guard"]],
                "asr": str(asr_path.relative_to(d))})
    print(f"voice: narration.wav {rec['narration_sha256']} 長さ {tl['duration']}秒・"
          f"−12dB を超える塊を削った take {rec['tail_loud']}・守りで止めた take {rec['tail_guard']}")
    return rec


def stage_images(d, rt, args):
    from video import film, images
    n = number(d)
    _, data = film.load_data(d)
    names = sorted({p["src"] for p in data["photos"].values()})
    made = images.generate(d, names, f"{data['slug']}-video-{n}")
    images.prep(d, names)
    print(f"images: 作った {made}・整えた {names}")
    return {"generated": made, "prepared": names}


def stage_comp(d, rt, args):
    from video import film
    comp = film.build(d, rt)
    rec = {name: runtime_sha(comp / rel) for name, rel in (("film_html", "compositions/film.html"), ("index_html", "index.html"))}
    print(f"comp: film.html {rec['film_html']}・index.html {rec['index_html']}")
    return rec


def stage_render(d, rt, args):
    from video import render
    p = paths(d)
    comp = d / "composition"
    if not (comp / "index.html").exists():
        raise SystemExit("composition が無い（先に comp の段）")
    p["raw"].parent.mkdir(exist_ok=True)
    print("render: 書き出し中（10分前後）")
    rec = render.render(comp, rt, p["raw"], p["render_log"])
    print(f"render: 終了コード {rec['exit']}・{rec['seconds']}秒・{rec.get('sha256')}・履歴 +{rec['history_added_bytes']:,}B／+{rec['history_added_files']}ファイル")
    if rec["exit"] != 0 or "sha256" not in rec:
        raise SystemExit(f"書き出しに失敗（{p['render_log']}）")
    return rec


def stage_finalize(d, rt, args):
    from video import render
    p = paths(d)
    rec = render.finalize(rt, p["raw"], p["final"])
    print(f"finalize: moov が mdat より前 {rec['moov_before_mdat']}・中身が元と同じ {rec['streams_same_as_raw']}・"
          f"タグが元と同じ {rec['tags_same_as_raw']}・PSNR {rec['psnr_average']}・音の差 {rec['audio_diff_max_db']}dB・{rec['sha256']}")
    if not (rec["moov_before_mdat"] and rec["streams_same_as_raw"] and rec["tags_same_as_raw"]):
        raise SystemExit("faststart の結果が想定と違う")
    return rec


def stage_qa(d, rt, args):
    from video import qa
    p = paths(d)
    res = qa.run_qa(d, rt, p["final"], p["qa"])
    bad = [k for k, v in res["gate"].items() if not v]
    print(f"qa: {p['qa'].name} 合格 {res['passed']}・不合格の項目 {bad}・{res['mp4_sha256']}")
    return {"passed": res["passed"], "failed": bad, "mp4_sha256": res["mp4_sha256"]}


STAGE_FN = {"voice": stage_voice, "images": stage_images, "comp": stage_comp, "render": stage_render,
            "finalize": stage_finalize, "qa": stage_qa}


def runtime_sha(p):
    from video.render import sha256
    return sha256(p) if os.path.exists(p) else None


def cmd_build(args, rt):
    d = video_dir(args.video)
    if args.only and args.from_:
        print("--from と --only は一緒に使えない")
        return 2
    todo = [args.only] if args.only else list(STAGES[STAGES.index(args.from_ or "voice"):])
    rc = 0
    for st in todo:
        t0 = datetime.datetime.now()
        try:
            rec = STAGE_FN[st](d, rt, args)
        except SystemExit as e:
            record(d, st, {"ok": False, "error": str(e)})
            print(f"STOP {st}: {e}")
            return 1
        rec["stage_seconds"] = round((datetime.datetime.now() - t0).total_seconds(), 1)
        record(d, st, {"ok": True, **rec})
        if st == "qa" and not rec["passed"]:
            rc = 1
    return rc


# ---- status

def cmd_status(args, rt):
    from video import render
    d = video_dir(args.video)
    p = paths(d)
    n = p["n"]
    log = json.loads(p["log"].read_text(encoding="utf-8"))["runs"] if p["log"].exists() else []
    last = {r["stage"]: r for r in log if r.get("ok")}
    data = None
    if list(d.glob("video-*.film.json")):
        from video import film
        _, data = film.load_data(d)
    print(f"動画{n}  output/videos/{d.name}/  slug={data['slug'] if data else '-'}")

    def line(stage, text):
        r = last.get(stage)
        print(f"  {stage:<8} {text}" + (f"（最後の実行 {r['at']}・{r.get('stage_seconds')}秒）" if r else "（記録なし）"))

    tl = d / "work" / "timeline.json"
    dur = json.loads(tl.read_text(encoding="utf-8"))["duration"] if tl.exists() else None
    line("voice", f"narration.wav {runtime_sha(d / 'work' / 'narration.wav') or '無し'}・長さ {dur}秒"
         + (f"・印 {last['voice'].get('tail_loud')}" if "voice" in last else ""))
    imgs = sorted(x.name for x in (d / "work" / "img").glob("*.jpg")) if (d / "work" / "img").exists() else []
    line("images", f"work/img {len(imgs)}枚 {imgs}")
    line("comp", f"film.html {runtime_sha(d / 'composition' / 'compositions' / 'film.html') or '無し'}・"
         f"index.html {runtime_sha(d / 'composition' / 'index.html') or '無し'}")
    r = last.get("render")
    lint = render.lint_from_log(p["render_log"].read_text(encoding="utf-8")) if p["render_log"].exists() else None
    line("render", f"{p['raw'].relative_to(d)} {runtime_sha(p['raw']) or '無し'}"
         + (f"・所要 {r['seconds']}秒・履歴の増加 {r['history_added_bytes']:,}B／{r['history_added_files']}ファイル" if r else "")
         + (f"・lint（render.log）warning {lint['warnings']}・error {lint['errors']}" if lint else ""))
    f = last.get("finalize")
    line("finalize", f"{p['final'].name} {runtime_sha(p['final']) or '無し'}"
         + (f"・moov が先 {f['moov_before_mdat']}・中身が元と同じ {f['streams_same_as_raw']}" if f else ""))
    if p["qa"].exists():
        q = json.loads(p["qa"].read_text(encoding="utf-8"))
        cur = runtime_sha(p["final"])
        line("qa", f"{p['qa'].name} 合格 {q['passed']}・gate {q['gate']}・mp4 と一致 {q['mp4_sha256'] == cur}")
    else:
        line("qa", f"{p['qa'].name} 無し")

    pin = [ln for ln in (PIN_LEDGER.read_text(encoding="utf-8").splitlines() if PIN_LEDGER.exists() else [])
           if re.match(rf"^動画{n} \|", ln)]
    print(f"  Pinterest 台帳 {pin[0] if pin else '無し'}")
    if BUFFER_LEDGER.exists() and data:
        key = f"{data['slug']}-video-{n}"
        rows = [ln.split("\t") for ln in BUFFER_LEDGER.read_text(encoding="utf-8").splitlines()[1:] if ln.startswith(key + "\t")]
        print(f"  Buffer 台帳 {len(rows)}行 " + ", ".join(f"{x[1]}:{'削除済み ' + x[5] if len(x) > 5 and x[5] else '未削除'}" for x in rows))
    hist = render.history(rt)
    print(f"  書き出しの履歴 {len(hist)}件・{sum(h[1] for h in hist):,}B（{rt.hf_history}）")
    return 0


# ---- clean-history

def cmd_clean_history(args, rt):
    from video import render
    rec = render.clean_history(rt, keep=args.keep)
    print(f"clean-history: home {rec['before']['bytes']:,}B／{rec['before']['files']}ファイル → {rec['after']['bytes']:,}B／{rec['after']['files']}ファイル"
          f"（{rec['before']['bytes'] - rec['after']['bytes']:,}B 減）")
    print(f"  残した {rec['kept']}")
    for r in rec["removed"]:
        print(f"  消した {r['id']} {r['bytes']:,}B／{r['files']}ファイル")
    return 0


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="動画を作る（make-video）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("next")
    a.add_argument("--create", metavar="slug")
    a = sub.add_parser("check-script")
    a.add_argument("video")
    a = sub.add_parser("build")
    a.add_argument("video")
    a.add_argument("--from", dest="from_", choices=STAGES)
    a.add_argument("--only", choices=STAGES)
    a.add_argument("--redo", metavar="S3,S4")
    a = sub.add_parser("status")
    a.add_argument("video")
    a = sub.add_parser("clean-history")
    a.add_argument("--keep", type=int, default=1)
    args = ap.parse_args()

    ok, out = runtime.check()
    if not ok:
        print(out)
        print("STOP 実行環境が照合値どおりでない（python site/scripts/check-video-runtime.py）")
        return 2
    rt = runtime.Runtime()
    if args.cmd == "next":
        return cmd_next(args)
    if args.cmd == "check-script":
        return cmd_check_script(args)
    if args.cmd == "build":
        return cmd_build(args, rt)
    if args.cmd == "status":
        return cmd_status(args, rt)
    if args.cmd == "clean-history":
        if args.keep < 1:
            print("--keep は 1 以上")
            return 2
        return cmd_clean_history(args, rt)
    return 2


if __name__ == "__main__":
    sys.exit(main())
