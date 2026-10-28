# -*- coding: utf-8 -*-
r"""動画を作る（本運用の入口・D-0300）。部品は site/scripts/video/ にあり、このスクリプトから import して使う。

道具と素材（CLI・ffmpeg・ロゴ・参照 WAV・字体・gsap）は実行環境（data/video-runtime.json・D-0299）から引く。
起動の最初に check-video-runtime.py を呼び、RUNTIME_OK でなければ何もせずに止める。
作品の場所は output/videos/<動画>/（<動画> はフォルダ名。例: video-1）。中身:
  script.json（台本）・video-N.parts.json（部品の並び・動画3以降・D-0307）・video-N.film.json（型に差し込む1本ごとのデータ。動画3以降は parts.json から作る）・
  prompts/・images/・voice/・work/・composition/・qa/
  work/video-N.raw.mp4（書き出し）・video-N.mp4（faststart の完成）・video-N.qa.json（機械QA）・video-N.build.json（段ごとの記録）

操作:
  next [--date YYYY-MM-DD] [--create <slug> [--test] [--images-from video-N]]
                                   題材の候補（先行ピンと同じ山の窓の seasons・gift の公開記事を、山が近い順→slug の昇順）と次の番号 N を出す。
                                   1行目は「NEXT_SLUG: <slug>」。候補が無ければ「VIDEO_NO_CANDIDATES」の1行だけ（終了コードは0・何も作らない）。
                                   --date は基準日の差し替え（検証用・既定は今日）。投稿済み・制作中の slug は候補に出さない
                                   --create で output/videos/video-N/ の骨組み（script.json の雛形・prompts/・build.json の created_at）を作る。
                                   投稿済み・制作中の slug は拒否（終了コード1・何も作らない）。候補の範囲外は「【注意】題材の範囲外」を出して作る。
                                   --test は投稿しないテスト（D-0308）: build.json に mode=test を書き、動画md（output/videos/<slug>/video-N.md）に
                                   保留の行（HOLD_LINE）を入れる。post-video-pins.py・post-video-to-buffer.py の check_review が、保留の行か mode=test で止める。
                                   --test に限り、投稿済みの slug でも作れる（同じ記事で組み立てだけ変える試作・評価専用。build.json に same_slug_posted。
                                   この動画の release は拒否する＝同じ記事の2本目を試作から出さない・D-0310）
                                   --images-from video-N は、その動画の写真（images/ の png・prompts/・work/img/ の jpg）を写して使う（D-0310）。
                                   写した写真は images の段が作り直さないので、画像生成は0回（build.json の images_from に記録・image_gens は足さない）
  release <動画> [--confirmed]     テストの保留を外す（Sho の「投稿して」のあと）: 動画md の保留の行を消し、build.json を mode=released にする。
                                   季節の題材で、作ったときに向けた山を過ぎた・今日から山までが窓の外なら【注意】を出して外さない（終了コード1）。
                                   Sho が確かめたら --confirmed で外す。mp4・qa.json・審査行は変えない（作り直さない）。
                                   同じ slug の動画が投稿済みなら拒否する（--confirmed でも外さない・試作は評価専用）
  drop <動画> [--reason 文]         見送り: build.json を mode=dropped にする。slug は題材の候補に戻り、似すぎの比べる相手から外れる。番号は使い切り。投稿済みは拒否
  snapshot <動画> --at 秒,… [--out DIR]
                                   composition の静止画（HyperFrames CLI の snapshot・--no-end）。既定の置き場所は qa/snapshots/
  check-script <動画>              script.json の形と句の字数（1行14字・1画面30字）を確かめ、読み辞書を当てた声の入力を出す（声は作らない）。
                                   動画3以降は、声の最初が問い・終わりの声の形・画面の字と声の同文率・ぼかしの戻しも検査する
                                   （video/script_checks.py・film.json が無い間は台本の分だけ）。build の最初も同じ検査を通る。
                                   動画3以降で parts.json があれば、組み立ての似すぎも判定する（下の「似すぎ」）

似すぎ（D-0308）: 部品の定義から作る指紋（video/parts.py の fingerprint）を、直近の投稿済み・保留中のテスト（見送りは除く）と比べ、
  点数が parts.SIMILAR_LINE 以上なら NG（重なった項目を出す）。check-script・build の最初（どの段も書き出しの前）・film の段と film の操作で止まる。
  film の段は film.json に指紋（fingerprint）を書く。動画1・2は対象外（INFO）で、比べる相手としては使う（動画1は parts.FINGERPRINT_BORROW）
画像生成の上限（D-0308）: images の段が作る前に video/images.py の budget を見て、超えるなら1枚も作らずに止める（status にも残りを出す）
外部送信の遮断（D-0308）: HyperFrames（render・snapshot）へ渡す env は video/runtime.py の env("hyperframes")（外部の解析の鍵を外す）。
  snapshot は --describe false も付ける。照合は check-video-runtime.py
  film <動画> [--out DIR] [--parts FILE] [--comp] [--peaks [--at 秒,…]]
                                   video-N.parts.json と work/timeline.json から video-N.film.json を作り、部品の要約を出す（video/parts.py）。
                                   --out は動画フォルダに書かず、DIR に film.json と film.html を書く（検証・見比べ用。似すぎなら書いたうえで終了コード1）。
                                   動画 PARTS_FROM 未満（動画1・2）は --out なしでは書かない（案Aの film.json のまま）
                                   --parts は動画の parts.json の代わりに FILE（番号を取る前の下書き）を、その動画の声の時刻表で組む（--out が要る）。
                                   似すぎは番号を問わず直近の parts.SIMILAR_RECENT 本と比べる（下書きはどの番号にもなりうるため）
                                   --comp は DIR/composition に composition を組む（写真・声・字体はその動画のもの）。
                                   --peaks は --comp に加えて、部品ごとの見せ場の秒（要約の「見せ場」）の静止画を DIR/snapshots/ に撮る（全編の書き出しはしない）。
                                   --at は見せ場に足して撮る秒（動きの途中を見るとき）
  build <動画> [--from 段|--only 段] [--redo S3,S4]
                                   段: voice → film → images → comp → render → finalize → qa（--from はその段から最後まで、--only はその段だけ）
                                   voice: 声の無い文（--redo の文は作り直し）だけ TTS → take の選択・末尾の処理・つなぎ → 読み違いの目安
                                   film: parts.json があれば film.json を作り直し、check-script と同じ検査を通す（無い・動画1・2なら今の film.json のまま）
                                   images: 無い写真だけ gateway で作る → 1440×2160 に整える
                                   comp: 型テンプレート＋video-N.film.json → composition/
                                   render: 全編の書き出し（所要と履歴の増加量を記録）／finalize: faststart だけ／qa: video-N.qa.json
  status <動画>                     作成からの経過・段ごとの成果物・sha256・qa の合否・台帳（Pinterest・Buffer）・書き出しの履歴を、読み取りだけで出す
  clean-history [--keep 1]          書き出しの履歴（実行環境の home の history の下の UUID 形のフォルダ）を、新しい keep 件を残して消す

終了コード: 0 正常 / 1 段の失敗・検査の NG・qa の不合格 / 2 実行環境の照合が RUNTIME_OK でない・引数の誤り
"""

import argparse
import datetime
import importlib.util
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
STAGES = ("voice", "film", "images", "comp", "render", "finalize", "qa")
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


def load_log(d):
    p = paths(d)["log"]
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"runs": []}


def save_log(d, log):
    paths(d)["log"].write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


def record(d, stage, rec):
    log = load_log(d)
    log["runs"].append({"stage": stage, "at": now(), **rec})
    save_log(d, log)


# ---- 動画の状態（build.json の mode・D-0308）。無ければ本番の制作（投稿まで進む）

MODES = {"test": "保留中のテスト（投稿は Sho の一言のあと release で外す）", "released": "テストの保留を外した（投稿できる）",
         "dropped": "見送り（投稿しない。slug は題材の候補に戻る・番号は使い切り）"}
HOLD_LINE = "- 保留: テスト（Sho の確認待ち）"
HOLD_RE = re.compile(r"^-\s*保留:")   # post-video-pins.py の HOLD_RE と同じ形（どちらかを変えるときは両方）


def mode_of(d):
    try:
        return load_log(d).get("mode")
    except (ValueError, SystemExit):
        return None


def set_mode(d, mode, **extra):
    log = load_log(d)
    log["mode"] = mode
    log.setdefault("mode_log", []).append({"mode": mode, "at": now(), **extra})
    save_log(d, log)


def slug_of(d):
    for f in [d / "script.json", *sorted(d.glob("video-*.film.json"))]:
        if f.exists():
            try:
                slug = json.loads(f.read_text(encoding="utf-8")).get("slug")
            except ValueError:
                slug = None
            if slug:
                return slug
    return None


def rel(p):
    """プロジェクトのルートからのパス（ルートの外ならそのまま）"""
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def video_md(d):
    """投稿用の動画md（output/videos/<slug>/video-N.md）。slug が分からなければ None"""
    slug = slug_of(d)
    return VIDEOS / slug / f"video-{number(d)}.md" if slug else None


# ---- next

def posted_numbers():
    out = {}
    if PIN_LEDGER.exists():
        for line in PIN_LEDGER.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^動画(\d+) \| ([^ |]+) \|", line)
            if m:
                out[int(m.group(1))] = m.group(2)
    return out


def advance_pin():
    """先行ピンの山の窓と山の計算の正本（check-advance-pin-today.py）。値はここへ書き写さない。"""
    spec = importlib.util.spec_from_file_location("check_advance_pin_today", os.path.join(SCRIPT_DIR, "check-advance-pin-today.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wip_slugs_of(entries, posted):
    """制作中の slug の集合。entries は (N, slug)。台帳にある番号と slug の無いものは数えない。"""
    return {slug for n, slug in entries if slug and n not in posted}


def wip_entries(posted):
    """制作中の動画: output/videos/video-N/ のうち台帳に無く、見送り（build.json の mode が dropped）でない番号の (N, 題材の slug)。
    slug は script.json、無ければ film.json から。保留中のテスト（test・released）は制作中に数える"""
    out = []
    for p in sorted(VIDEOS.glob("video-*")):
        m = re.match(r"^video-(\d+)$", p.name)
        if not (p.is_dir() and m) or int(m.group(1)) in posted or mode_of(p) == "dropped":
            continue
        out.append((int(m.group(1)), slug_of(p)))
    return out


def pick_candidates(target, calendar, posts, excluded, adv):
    """題材の候補。公開中の seasons・gift で、台帳に山があり、基準日から次の山までが窓の中の記事。除外（投稿済み・制作中）を除き、山が近い順→slug の昇順。"""
    out = []
    for slug, entry in calendar.items():
        post = posts.get(slug)
        if slug in excluded or not entry["peaks"] or not post or post["category"] not in adv.TARGET_CATEGORIES:
            continue
        peak = adv.next_peak(entry["peaks"], target)
        days = (peak - target).days
        if adv.WINDOW_MIN_DAYS <= days <= adv.WINDOW_MAX_DAYS:
            out.append({"slug": slug, "peak": peak, "days": days})
    return sorted(out, key=lambda c: (c["days"], c["slug"]))


def create_verdict(slug, posted_slugs, wip_slugs, candidate_slugs, test=False):
    """--create の可否。戻り値 (拒否か, 出す1行 または None)。範囲外は拒否せず注意だけ。
    投稿済みの slug は、テスト（test）に限り注意だけで作れる（組み立てだけ変える試作・評価専用。release は cmd_release が拒否する）"""
    if slug in posted_slugs and not test:
        return True, f"拒否: {slug} は投稿済み（data/video-posted.md）"
    if slug in wip_slugs:
        return True, f"拒否: {slug} は制作中（output/videos/ に同じ slug の制作フォルダがある）"
    if slug in posted_slugs:
        return False, (f"【注意】{slug} は投稿済み（data/video-posted.md）。テストとして作る（評価専用: この動画の release は拒否され、"
                       "同じ記事の2本目は出さない）")
    if slug not in candidate_slugs:
        return False, "【注意】題材の範囲外（先行ピンと同じ山の窓の seasons・gift の公開記事ではない）"
    return False, None


def images_source(name):
    """--images-from の動画フォルダ。返り値: (パス, None) か (None, 理由)。images/ に png が1枚以上ある video-N だけ"""
    d = VIDEOS / name
    if not re.match(r"^video-\d+$", name) or not d.is_dir():
        return None, f"動画フォルダが無い: output/videos/{name}"
    if not list((d / "images").glob("*.png")):
        return None, f"写真が無い: output/videos/{name}/images/*.png"
    return d, None


def copy_images(src, d):
    """src の写真（images/*.png・prompts/*.txt・work/img/*.jpg）を d へ写す。生成の記録（images/gen.log）は写さない。返り値: build.json の images_from"""
    import shutil
    files = []
    for sub, pat in (("images", "*.png"), ("prompts", "*.txt"), ("work/img", "*.jpg")):
        for p in sorted((src / sub).glob(pat)):
            (d / sub).mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, d / sub / p.name)
            files.append(f"{sub}/{p.name}")
    return {"video": src.name, "at": now(), "files": files,
            "sha256": {f: runtime_sha(d / f) for f in files if f.startswith("images/")}}


def cmd_next(args):
    adv = advance_pin()
    if args.date:
        try:
            target = datetime.date.fromisoformat(args.date)
        except ValueError:
            print(f"--date は YYYY-MM-DD: {args.date}")
            return 2
    else:
        target = adv.today_jst()
    posted = posted_numbers()
    wip_slugs = wip_slugs_of(wip_entries(posted), posted)
    calendar, _ = adv.load_calendar()
    cands = pick_candidates(target, calendar, adv.published_posts(), set(posted.values()) | wip_slugs, adv)
    if not args.create and not cands:
        print("VIDEO_NO_CANDIDATES")
        return 0
    local = [int(m.group(1)) for p in VIDEOS.glob("video-*") if p.is_dir() and (m := re.match(r"^video-(\d+)$", p.name))]
    n = max([0, *posted, *local]) + 1
    if not args.create:
        print(f"NEXT_SLUG: {cands[0]['slug']}")
        print(f"NEXT_N {n}（台帳の最大 {max(posted, default=0)}・作業フォルダの最大 {max(local, default=0)}）")
        print(f"CANDIDATES（基準日 {target.isoformat()}・山が近い順）")
        for c in cands:
            print(f"  {c['slug']}  山 {c['peak'].isoformat()}  残り{c['days']}日")
    else:
        if not (POSTS / f"{args.create}.md").exists():
            print(f"記事が無い: site/src/content/posts/{args.create}.md")
            return 1
        test = bool(getattr(args, "test", False))
        refused, msg = create_verdict(args.create, set(posted.values()), wip_slugs, {c["slug"] for c in cands}, test)
        if msg:
            print(msg)
        if refused:
            return 1
        src = None
        if getattr(args, "images_from", None):
            src, why = images_source(args.images_from)
            if src is None:
                print(f"--images-from: {why}")
                return 1
        d = VIDEOS / f"video-{n}"
        for sub in ("prompts", "images", "voice/raw", "work"):
            (d / sub).mkdir(parents=True, exist_ok=True)
        log = {"created_at": now(), "runs": []}
        if test:
            log.update({"mode": "test", "mode_log": [{"mode": "test", "at": log["created_at"]}]})
            same = sorted(k for k, s in posted.items() if s == args.create)
            if same:
                log["same_slug_posted"] = same
        if src is not None:
            log["images_from"] = copy_images(src, d)
            print(f"IMAGES_FROM {src.name}: 写した {log['images_from']['files']}（画像生成は0回・images の段は作り直さない）")
        (d / f"video-{n}.build.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
        if args.test:
            md = VIDEOS / args.create / f"video-{n}.md"
            md.parent.mkdir(exist_ok=True)
            note = (f"（テストの動画。上の保留の行は、Sho の「投稿して」のあと `make-video.py release video-{n}` が外す。手で消さない"
                    f"（消しても video-{n}.build.json の test で止まる）。ほかの項目の書き方は rules/pinterest-api.md「動画ピン」節）")
            if md.exists():
                lines = md.read_text(encoding="utf-8").splitlines()
                if not any(HOLD_RE.match(x.strip()) for x in lines):
                    md.write_text("\n".join(lines[:1] + ["", HOLD_LINE] + lines[1:]) + "\n", encoding="utf-8")
            else:
                md.write_text(f"# 動画{n}: （題名を書く）\n\n{HOLD_LINE}\n\n{note}\n", encoding="utf-8")
            print(f"TEST 動画{n}は投稿しないテスト（build.json の mode=test・{rel(md)} に保留の行）")
        sc = d / "script.json"
        if not sc.exists():
            sc.write_text(json.dumps({
                "_note": f"動画{n}の台本。phrases＝画面の字（句ごと）。voice は phrases を漢字のまま入力し、data/video-lexicon.json（共通の例外表）＋video-{n}.film.json の lexicon（記事ごとの例外。film.json が無い間はこの lexicon）で読み違える語だけ直す。"
                         "事実の出どころは source（記事の本文）。記事に無い事実・商品・体験は足さない。",
                "slug": args.create, "article_url": f"https://kohaku-jikan.com/posts/{args.create}/", "lexicon": [], "gap_after": {},
                "sentences": [{"id": "S1", "scene": "hook", "phrases": [], "source": ""}]}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"CREATED output/videos/video-{n}/（script.json・prompts/・video-{n}.build.json の created_at）。video-{n}.film.json は型のデータとして別に作る")
    return 0


# ---- check-script

def script_gate(d, sc, need_film=False):
    """台本と film.json の検査（video/script_checks.py・D-0306）。INFO は出し、NG の一覧を返す。
    need_film（build の最初）は、動画 NEW_CHECK_START 以降で film.json が無ければ NG にする。
    parts.json がある動画は film.json を voice のあとの film の段で作るので、無くても NG にしない（film の段でこの検査をもう一度通す）。"""
    from video import parts, script_checks
    n = number(d)
    films = sorted(d.glob("video-*.film.json"))
    film_data = json.loads(films[0].read_text(encoding="utf-8")) if films else None
    ng, info = script_checks.run(sc, film_data, n)
    for line in info:
        print(line)
    if need_film and film_data is None and n >= script_checks.NEW_CHECK_START:
        if parts.parts_path(d).exists():
            print(f"INFO video-{n}.film.json は film の段で {parts.parts_path(d).name} から作り、その段で同文率・戻し手順を検査する")
        else:
            ng.append(f"video-{n}.film.json が無い（画面の字の同文率・戻し手順を検査できない）")
    return ng


# ---- film（部品の定義から film.json）

def compile_parts(d, defn=None):
    """parts.json と timeline.json から film.json のデータと部品の要約を作る（書かない）。指紋（fingerprint）も入れる。返り値: (データ, 要約)。
    defn を渡すと動画の parts.json の代わりに使う（下書き）"""
    from video import parts
    try:
        own, tl, sc = parts.load(d, need_parts=defn is None)
        defn = defn if defn is not None else own
        data, summary = parts.compile_film(defn, tl, sc)
        data["fingerprint"] = parts.fingerprint(defn, sc)
        return data, summary
    except (parts.PartsError, KeyError) as e:
        raise SystemExit(f"parts.json から film.json を作れない: {e}")


# ---- 組み立ての似すぎ（D-0308）。指紋と点数は video/parts.py、比べる相手と止める所はここ

def read_json(p):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def film_fx(film_data):
    """手で作った film.json の cues から、つなぎの並び（fx の名前）"""
    return [c["fx"] for sec in sorted(film_data["cues"]) for c in film_data["cues"][sec] if isinstance(c, dict) and c.get("fx")]


def fingerprint_of(d, prefer_parts):
    """動画の指紋。返り値: (指紋, 出どころ) か (None, 理由)。
    prefer_parts（判定する側）は今の parts.json を先に見る。比べる相手は film.json に書いた指紋（書き出したときの組み立て）を先に見る。
    どちらも無い動画1は parts.FINGERPRINT_BORROW の動画の parts.json を借りる（film.json の区間の数・つなぎの並び・章の数が同じときだけ）"""
    from video import parts
    n = number(d)
    sc = read_json(d / "script.json")
    films = sorted(d.glob("video-*.film.json"))
    fd = read_json(films[0]) if films else None
    pp = parts.parts_path(d)
    if fd and "fingerprint" in fd and not (prefer_parts and pp.exists()):
        return fd["fingerprint"], films[0].name
    if pp.exists():
        return parts.fingerprint(json.loads(pp.read_text(encoding="utf-8")), sc), pp.name
    src = parts.FINGERPRINT_BORROW.get(n)
    sp = parts.parts_path(VIDEOS / f"video-{src}") if src else None
    if not (sp and sp.exists() and fd):
        return None, "parts.json も film.json の指紋も無い"
    defn = json.loads(sp.read_text(encoding="utf-8"))
    fp = parts.fingerprint(defn, sc)
    same = (len(fd["sections"]) == len(defn["parts"]), film_fx(fd) == fp["fx"], len(fd.get("pills") or []) == len(defn.get("chapters") or []))
    if not all(same):
        return None, f"{sp.name} を借りられない（区間の数・つなぎの並び・章の数の一致 {same}）"
    return fp, f"{sp.name} の並び（動画{n}は動画{src}と同じ並びとして扱う。冒頭の問いは動画{n}の台本から）"


def similar_targets(n):
    """比べる相手: 投稿済み（data/video-posted.md）か保留中のテスト（mode が test・released）の番号の新しい順に parts.SIMILAR_RECENT 本。見送りは除く。
    n が None（番号を取る前の下書き）なら、どの番号も除かない"""
    from video import parts
    posted = posted_numbers()
    out = []
    for p in VIDEOS.glob("video-*"):
        m = re.match(r"^video-(\d+)$", p.name)
        if not (p.is_dir() and m) or int(m.group(1)) == n:
            continue
        mode = mode_of(p)
        if mode != "dropped" and (int(m.group(1)) in posted or mode in ("test", "released")):
            out.append(int(m.group(1)))
    return sorted(out, reverse=True)[:parts.SIMILAR_RECENT]


def similarity_gate(d, defn=None, label="下書き"):
    """組み立ての似すぎの判定。返り値: (NG の一覧, INFO の一覧)。動画 PARTS_FROM 未満は NG を INFO に回す（対象外）。
    defn（下書きの parts.json の中身）を渡すと、その組み立てを動画 d の台本（冒頭の問い）で判定し、番号を問わず直近と比べる"""
    from video import parts
    n = None if defn is not None else number(d)
    ng, info = [], []
    try:
        if defn is not None:
            fp, src = parts.fingerprint(defn, read_json(d / "script.json")), label
        else:
            fp, src = fingerprint_of(d, prefer_parts=True)
    except (parts.PartsError, KeyError, ValueError) as e:
        fp, src = None, f"指紋を作れない: {e}"
    if fp is None:
        if defn is not None:
            return [f"組み立ての指紋を作れない（{src}）"], info
        if n >= parts.PARTS_FROM and parts.parts_path(d).exists():
            ng.append(f"組み立ての指紋を作れない（{src}）")
        else:
            info.append(f"INFO 組み立ての似すぎは {parts.parts_path(d).name} を書いたあとに判定する（{src}）")
        return ng, info
    info.append(f"INFO 指紋（{src}）: 部品 {'→'.join(fp['parts'])}／つなぎ {'→'.join(fp['fx']) or 'なし'}／カメラ {'・'.join(fp['camera'])}／"
                f"比べ方 {fp['compare']}／冒頭 {fp['opening']}／{fp['chapters']}")
    for k in similar_targets(n):
        try:
            fp2, src2 = fingerprint_of(VIDEOS / f"video-{k}", prefer_parts=False)
        except (parts.PartsError, KeyError, ValueError) as e:
            fp2, src2 = None, str(e)
        if fp2 is None:
            info.append(f"INFO 動画{k}の指紋が無いので比べない（{src2}）")
            continue
        score, rows = parts.similarity(fp, fp2)
        head = f"{label if n is None else f'動画{n}'} 対 動画{k}（{src2}）: {score:.3f}（線 {parts.SIMILAR_LINE:.2f}）"
        if score >= parts.SIMILAR_LINE:
            ng.append("\n".join([f"組み立てが似すぎ {head}。重なりの大きい項目から変える（video/parts.py の SIMILAR_WEIGHTS）",
                                 *parts.similarity_lines(score, rows)]))
        else:
            info.append(f"INFO 似すぎではない {head}")
            if n is None:
                info += [f"INFO   {ln.strip()}" for ln in parts.similarity_lines(score, rows)]
    if n is not None and n < parts.PARTS_FROM:
        return [], info + [f"INFO（動画{n}は対象外・動画{parts.PARTS_FROM}以降） {m}" for m in ng]
    return ng, info


def cmd_film(args, rt=None):
    from video import film, parts
    d = video_dir(args.video)
    draft = getattr(args, "parts", None)
    comp, peaks = getattr(args, "comp", False) or getattr(args, "peaks", False), getattr(args, "peaks", False)
    if (draft or comp) and not args.out:
        print("--parts・--comp・--peaks は --out DIR と一緒に使う（動画フォルダには書かない）")
        return 2
    defn = None
    if draft:
        try:
            defn = json.loads(Path(draft).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"--parts を読めない: {e}")
            return 1
    elif not parts.parts_path(d).exists():
        print(f"{parts.parts_path(d).name} が無い（output/videos/{d.name}/）")
        return 1
    n = number(d)
    if not args.out and n < parts.PARTS_FROM:
        print(f"拒否: 動画{n}は案Aの作りのまま（parts.json から film.json を作り直さない・PARTS_FROM {parts.PARTS_FROM}）。見比べるときは --out DIR")
        return 1
    data, summary = compile_parts(d, defn)
    for ln in parts.summary_lines(summary):
        print(ln)
    sim_ng, sim_info = similarity_gate(d, defn, f"下書き {Path(draft).name}" if draft else "下書き")
    for line in sim_info + [f"NG {m}" for m in sim_ng]:
        print(line)
    if sim_ng and not args.out:
        print("拒否: 組み立てが直近の動画と似すぎ。film.json は書かない（見比べるときは --out DIR）")
        return 1
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        stem = f"video-{n}" if not draft else Path(draft).name.replace(".parts.json", "")
        (out / f"{stem}.film.json").write_text(parts.dump(data), encoding="utf-8")
        (out / "film.html").write_text(film.render_film(data), encoding="utf-8", newline="\r\n")
        print(f"WROTE {out / f'{stem}.film.json'}・{out / 'film.html'}（{runtime_sha(out / 'film.html')}）")
        if comp:
            c = film.build(d, rt, data=data, comp=out / "composition")
            print(f"COMP {c}（写真・声は output/videos/{d.name}/ から。film.html {runtime_sha(c / 'compositions' / 'film.html')}）")
        if peaks:
            from video import render
            at = ",".join([f"{s['peak']:.2f}" for s in summary] + [x for x in (getattr(args, "at", None) or "").split(",") if x])
            rc, text = render.snapshot(out / "composition", rt, at, out / "snapshots")
            print(text.strip())
            for s in summary:
                print(f"PEAK {s['letter']} {s['scene']} {s['name']} {s['peak']:.2f}秒")
            print(f"snapshot: 終了コード {rc}・{out / 'snapshots'}（外部の解析なし: 鍵を外した env・--describe false）")
            if rc != 0:
                return 1
        if sim_ng:
            return 1
    else:
        p = d / f"video-{n}.film.json"
        p.write_text(parts.dump(data), encoding="utf-8")
        print(f"WROTE {p.relative_to(ROOT)}（{runtime_sha(p)}）")
    return 0


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
    ng += script_gate(d, sc)
    sim_ng, sim_info = similarity_gate(d)
    for line in sim_info:
        print(line)
    ng += sim_ng
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


def stage_film(d, rt, args):
    from video import parts
    n = number(d)
    if not parts.parts_path(d).exists() or n < parts.PARTS_FROM:
        why = "parts.json が無い" if not parts.parts_path(d).exists() else f"動画{n}は案Aの作り（PARTS_FROM {parts.PARTS_FROM} 未満）"
        print(f"film: {why}。今の video-{n}.film.json を使う")
        return {"source": "film.json"}
    data, summary = compile_parts(d)
    sim_ng, _ = similarity_gate(d)
    if sim_ng:
        for m in sim_ng:
            print("NG", m)
        raise SystemExit(f"組み立てが直近の動画と似すぎ（{len(sim_ng)}件）。film.json は書いていない")
    p = d / f"video-{n}.film.json"
    p.write_text(parts.dump(data), encoding="utf-8")
    for ln in parts.summary_lines(summary):
        print(f"film: {ln}")
    print(f"film: {p.name} {runtime_sha(p)}（{parts.parts_path(d).name} から）")
    ng = script_gate(d, json.loads((d / "script.json").read_text(encoding="utf-8")), need_film=True)
    if ng:
        for m in ng:
            print("NG", m)
        raise SystemExit(f"台本・film.json の検査に不合格（{len(ng)}件・check-script と同じ検査）")
    return {"source": "parts.json", "film_json": runtime_sha(p)}


def stage_images(d, rt, args):
    from video import film, images
    n = number(d)
    _, data = film.load_data(d)
    names = sorted({p["src"] for p in data["photos"].values()})
    made = images.generate(d, names, f"{data['slug']}-video-{n}", paths(d)["log"], VIDEOS)
    images.prep(d, names)
    print(f"images: 作った {made}・整えた {names}")
    return {"generated": made, "prepared": names, "image_gens_logged": True}


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


STAGE_FN = {"voice": stage_voice, "film": stage_film, "images": stage_images, "comp": stage_comp, "render": stage_render,
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
    gate_ng = script_gate(d, json.loads((d / "script.json").read_text(encoding="utf-8")), need_film=True)
    if gate_ng:
        for m in gate_ng:
            print("NG", m)
        print(f"STOP script_gate: 台本・film.json の検査に不合格（{len(gate_ng)}件・check-script と同じ検査）")
        return 1
    sim_ng, sim_info = similarity_gate(d)
    for line in sim_info:
        print(line)
    if sim_ng:
        for m in sim_ng:
            print("NG", m)
        print(f"STOP similar: 組み立てが直近の動画と似すぎ（{len(sim_ng)}件）。parts.json の組み立てを変えてから build（どの段も書き出しの前に止まる）")
        return 1
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

def elapsed_line(log_path):
    """作成からの経過（build.json の created_at から今まで）と、記録済みの段の stage_seconds の合計。1本全体の時間は created_at から審査行が書かれるまで（rules/video-production.md 0-1）。"""
    log = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else {}
    if not log.get("created_at"):
        return "作成からの経過: 記録なし（build.json に created_at が無い）"
    sec = int((datetime.datetime.now() - datetime.datetime.fromisoformat(log["created_at"])).total_seconds())
    stages = [r["stage_seconds"] for r in log.get("runs", []) if isinstance(r.get("stage_seconds"), (int, float))]
    return (f"作成からの経過: {sec // 3600}時間{sec % 3600 // 60}分（{log['created_at']} から）・"
            f"記録済みの段の stage_seconds の合計 {round(sum(stages), 1)}秒（{len(stages)}回）")


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
    print("  " + elapsed_line(p["log"]))
    mode = mode_of(d)
    print(f"  状態 {mode or '本番'}" + (f"（{MODES[mode]}）" if mode in MODES else ""))
    blog = load_log(d)
    if blog.get("same_slug_posted"):
        print(f"  同じ記事の投稿済み: 動画{'・'.join(map(str, blog['same_slug_posted']))}（評価専用の試作。release は拒否される）")
    if blog.get("images_from"):
        f = blog["images_from"]
        print(f"  写真: {f['video']} から写した {len(f['files'])}ファイル（{f['at']}・画像生成は0回）")
    from video import images
    print("  " + images.budget(d, VIDEOS, 0)[1][0])

    def line(stage, text):
        r = last.get(stage)
        print(f"  {stage:<8} {text}" + (f"（最後の実行 {r['at']}・{r.get('stage_seconds')}秒）" if r else "（記録なし）"))

    tl = d / "work" / "timeline.json"
    dur = json.loads(tl.read_text(encoding="utf-8"))["duration"] if tl.exists() else None
    line("voice", f"narration.wav {runtime_sha(d / 'work' / 'narration.wav') or '無し'}・長さ {dur}秒"
         + (f"・印 {last['voice'].get('tail_loud')}" if "voice" in last else ""))
    from video import parts
    fj = d / f"video-{n}.film.json"
    src = f"{parts.parts_path(d).name} から作る" if parts.parts_path(d).exists() and n >= parts.PARTS_FROM else "案A（手で作った film.json）"
    line("film", f"{fj.name} {runtime_sha(fj) or '無し'}・{src}")
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
    if data:
        from video import rules
        rows = rules.full_windows(data, rules.simulate(data, dur or float(data["sections"][rules.letters(data)[-1]]) + 5))
        if rows:
            print("  全面の写真で主役がはみ出さない範囲（写真の作り直しの依頼文にそのまま使う。rules/video-production.md 3節）")
            for ln in rules.full_window_lines(rows):
                print(f"    {ln}")

    pin =[ln for ln in (PIN_LEDGER.read_text(encoding="utf-8").splitlines() if PIN_LEDGER.exists() else [])
           if re.match(rf"^動画{n} \|", ln)]
    print(f"  Pinterest 台帳 {pin[0] if pin else '無し'}")
    if BUFFER_LEDGER.exists() and data:
        key = f"{data['slug']}-video-{n}"
        rows = [ln.split("\t") for ln in BUFFER_LEDGER.read_text(encoding="utf-8").splitlines()[1:] if ln.startswith(key + "\t")]
        print(f"  Buffer 台帳 {len(rows)}行 " + ", ".join(f"{x[1]}:{'削除済み ' + x[5] if len(x) > 5 and x[5] else '未削除'}" for x in rows))
    hist = render.history(rt)
    print(f"  書き出しの履歴 {len(hist)}件・{sum(h[1] for h in hist):,}B（{rt.hf_history}）")
    return 0


# ---- テストの保留を外す・見送り・静止画（D-0308）

def season_notices(slug, created, today, adv, calendar):
    """季節の題材の【注意】: 作ったときに向けた山（created 以降で最も近い山）を過ぎた・今日から山までが先行ピンの窓の外。山の無い題材は無し"""
    entry = calendar.get(slug)
    if not entry or not entry["peaks"]:
        return []
    peak = adv.next_peak(entry["peaks"], created)
    days = (peak - today).days
    if days < 0:
        return [f"【注意】山（{peak.isoformat()}）を {-days}日過ぎている。声・字の日付が古い。投稿文だけ直して再審査するか、見送る（drop）"]
    if not adv.WINDOW_MIN_DAYS <= days <= adv.WINDOW_MAX_DAYS:
        return [f"【注意】山（{peak.isoformat()}）まで残り{days}日で、窓（{adv.WINDOW_MIN_DAYS}〜{adv.WINDOW_MAX_DAYS}日）の外"]
    return []


def cmd_release(args):
    d = video_dir(args.video)
    n, log = number(d), load_log(d)
    if log.get("mode") != "test":
        print(f"拒否: 動画{n}は保留中のテストではない（mode={log.get('mode') or '本番'}）")
        return 1
    slug = slug_of(d)
    same = sorted(k for k, s in posted_numbers().items() if s == slug and k != n)
    if same or log.get("same_slug_posted"):
        print(f"拒否: 同じ記事（{slug}）の動画{'・'.join(map(str, same or log['same_slug_posted']))}が投稿済み。"
              f"この動画は組み立てを比べる試作（評価専用）で、同じ記事の2本目は出さない（--confirmed でも外さない）。使わないなら drop video-{n}")
        return 1
    adv = advance_pin()
    created =datetime.datetime.fromisoformat(log["created_at"]).date() if log.get("created_at") else adv.today_jst()
    notes = season_notices(slug, created, adv.today_jst(), adv, adv.load_calendar()[0]) if slug else []
    for m in notes:
        print(m)
    if notes and not args.confirmed:
        print(f"STOP 保留は外していない。Sho に上の【注意】を伝え、投稿すると決まったら release video-{n} --confirmed")
        return 1
    md = video_md(d)
    removed = 0
    if md and md.exists():
        lines = md.read_text(encoding="utf-8").splitlines()
        kept = [x for x in lines if not HOLD_RE.match(x.strip())]
        removed = len(lines) - len(kept)
        md.write_text("\n".join(kept) + "\n", encoding="utf-8")
    set_mode(d, "released", **({"notices": notes} if notes else {}))
    where = rel(md) if md else "動画md（slug が分からない）"
    print(f"RELEASED 動画{n}: build.json の mode=released・{where} の保留の行 {removed}行を外した（mp4・qa.json・審査行はそのまま）。"
          f"次は post-video-pins.py --dry-run --md {where}")
    return 0


def cmd_drop(args):
    d = video_dir(args.video)
    n = number(d)
    if n in posted_numbers():
        print(f"拒否: 動画{n}は投稿済み（data/video-posted.md）")
        return 1
    set_mode(d, "dropped", **({"reason": args.reason} if args.reason else {}))
    print(f"DROPPED 動画{n}: build.json の mode=dropped。slug {slug_of(d) or '-'} は題材の候補に戻り、似すぎの比べる相手から外れる。"
          f"番号 {n} は使い切り（フォルダは残す）")
    return 0


def cmd_snapshot(args, rt):
    from video import render
    d = video_dir(args.video)
    comp = d / "composition"
    if not (comp / "index.html").exists():
        print("composition が無い（先に build --only comp）")
        return 1
    out = Path(args.out) if args.out else d / "qa" / "snapshots"
    rc, text = render.snapshot(comp, rt, args.at, out)
    print(text.strip())
    print(f"snapshot: 終了コード {rc}・{out}（外部の解析なし: 鍵を外した env・--describe false）")
    return 0 if rc == 0 else 1


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
    a.add_argument("--test", action="store_true")
    a.add_argument("--images-from", dest="images_from", metavar="video-N")
    a.add_argument("--date", metavar="YYYY-MM-DD")
    a = sub.add_parser("release")
    a.add_argument("video")
    a.add_argument("--confirmed", action="store_true")
    a = sub.add_parser("drop")
    a.add_argument("video")
    a.add_argument("--reason")
    a = sub.add_parser("snapshot")
    a.add_argument("video")
    a.add_argument("--at", required=True, metavar="秒,秒")
    a.add_argument("--out", metavar="DIR")
    a = sub.add_parser("check-script")
    a.add_argument("video")
    a = sub.add_parser("film")
    a.add_argument("video")
    a.add_argument("--out", metavar="DIR")
    a.add_argument("--parts", metavar="FILE")
    a.add_argument("--comp", action="store_true")
    a.add_argument("--peaks", action="store_true")
    a.add_argument("--at", metavar="秒,秒")
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
        if (args.test or args.images_from) and not args.create:
            print("--test・--images-from は --create と一緒に使う")
            return 2
        return cmd_next(args)
    if args.cmd == "release":
        return cmd_release(args)
    if args.cmd == "drop":
        return cmd_drop(args)
    if args.cmd == "snapshot":
        return cmd_snapshot(args, rt)
    if args.cmd == "check-script":
        return cmd_check_script(args)
    if args.cmd == "film":
        return cmd_film(args, rt)
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
