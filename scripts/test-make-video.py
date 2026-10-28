# -*- coding: utf-8 -*-
r"""make-video.py の部品（site/scripts/video/）のテスト。読むだけ（一時フォルダにも書かない）。

1. cut_tail の線（2026-10-28 (b)・Sho が聞いて選んだ線B）: ①は −9dB 以下の塊だけ削る。
   output/videos/_listen-2026-10-28/tts/raw の B-1・A-2・B-2・新S3 の生の take で、語（「手入れ」「好み」「このみ」「コノミ」）を食べず、
   S6 は投稿済みの動画と同じ長さ（3.98秒）に切れること。(a) の線（大きさを見ない）との差は NOTE で出す。
2. 合成した波形: 間を挟んだ短い語が末尾に並ぶ波形で、(a) の線では削られ、線B では語が残る・静かな雑音は削られる。守り（min_len）が削りを止め、印が立つ。
3. 読みの例外表: 画面の字を漢字のまま入力し、例外（鍵→カギ・・→、・琥珀時間）だけが直ること。kanji_left は無い。
4. 型: video-1.film.json から film.html が描けること（置き残しの {{ }} が無い・区間の秒・下の段の幕）。TAIL が 3.45。
5. R7（データから計算・mp4 は読まない）: 1画面の字数が30字以下、下の段・上の段の主題が帯の中、点が端で切れていない。ease・カメラの再現の基本。
6. (d) の gate（D-0303）: はみ出し 0px（動画1の全面の写真 B・G は不合格、0px は合格・0.5px は不合格）と、点のコントラスト 3.0
   （合成したコマで、中も縁取りも背景に近いと不合格・濃い縁取りか明るい中のどちらかが背景と離れていれば合格・lead の書き漏れは不合格）。
   点は中の大きさを変えずに縁取りを外へ足す形で描かれる。
7. 題材の候補（make-video.py next・D-0305）: 窓の内側・外側、投稿済み・制作中の除外、0件、並び順、--create の拒否と範囲外の注意（メモリ上のデータだけ）。

使い方: python site/scripts/test-make-video.py
終了コード: 全件合格で0、1件でも不合格で1
"""
import json
import os
import sys
from pathlib import Path

import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from video import film, lexicon, rules, voice  # noqa: E402
from video.runtime import PROJECT_ROOT  # noqa: E402

ROOT = Path(PROJECT_ROOT)
LISTEN = ROOT / "output" / "videos" / "_listen-2026-10-28" / "tts" / "raw"
VIDEO1 = ROOT / "output" / "videos" / "video-1"
OLD_LINE = {"r1_max_db": None}   # (a) の線（大きさを見ない）
# 声の入力（candidates.md の B-1・A-1 の句に、句 A・B の残りを合わせた文全体）
CASES = {"K_B-1": ("えらぶかぎは、場面、手入れ、好み。", 3.3), "K_A-2": ("えらぶ鍵は、ばめん、ていれ、このみ。", 3.7),
         "K_B-2": ("えらぶかぎは、バメン、テイレ、コノミ。", 3.2), "N_S3": ("選ぶカギは、場面、手入れ、好み。", 3.5)}

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f"  {detail}" if detail else ""))


def test_candidates():
    for key, (text, floor) in CASES.items():
        p = LISTEN / f"{key}.wav"
        if not p.exists():
            print(f"SKIP {key}: {p} が無い")
            continue
        y0 = voice.trim(voice.load(p))
        min_len = voice.mora(text) / voice.MIN_MORA_PER_S
        y_old, _, drops_old, _ = voice.cut_tail(y0, min_len, OLD_LINE)
        y_new, cut, drops, flag = voice.cut_tail(y0, min_len)
        d_old, d_new = len(y_old) / voice.SR, len(y_new) / voice.SR
        check(f"{key} は線B で語を食べない（{floor}秒以上残る）", d_new >= floor,
              f"元 {len(y0) / voice.SR:.2f}秒・(a) の線 {d_old:.2f}秒（{drops_old}回）・線B {d_new:.2f}秒（{drops}回・削った塊の最大 {flag['max_db']}）")
    s6 = VIDEO1 / "voice" / "raw" / "T_s11_S6.wav"
    if s6.exists():
        y, *_ = voice.cut_tail(voice.trim(voice.load(s6)), voice.mora("このみは、いろがらをそろえるか、いろちがいにするか。") / voice.MIN_MORA_PER_S)
        check("S6 は線B で投稿済みの動画と同じ長さ（3.98秒）", abs(len(y) / voice.SR - 3.98) < 0.015, f"{len(y) / voice.SR:.3f}秒")


def tone(sec, amp=0.5, hz=220):
    t = np.arange(int(sec * voice.SR)) / voice.SR
    return amp * np.sin(2 * np.pi * hz * t)


def test_synthetic():
    sr = voice.SR
    gap = np.zeros(int(0.3 * sr))
    word = tone(0.35)
    # 長い句のあとに、0.3秒の間を挟んで 0.35秒の語が3つ（どれも規則①に当たる大きさ・長さ）
    y = np.concatenate([tone(1.0), gap, word, gap, word, gap, word, np.zeros(int(0.1 * sr))])
    _, _, drops_old, _ = voice.cut_tail(y.copy(), None, OLD_LINE)
    _, _, drops_b, _ = voice.cut_tail(y.copy())
    y_new, _, drops_new, flag = voice.cut_tail(y.copy(), 2.0, OLD_LINE)
    check("合成: (a) の線では末尾の語が削られる", drops_old >= 2, f"{drops_old}回")
    check("合成: 線B では大きい語（0dB）は削られない", drops_b == 0, f"{drops_b}回")
    check("合成: 守りありでは最短 2.0秒を下回らず、印が立つ", len(y_new) / sr >= 2.0 and flag["guard"] == 1,
          f"{len(y_new) / sr:.2f}秒・{drops_new}回・guard={flag['guard']}")
    quiet = np.concatenate([tone(1.0), gap, tone(0.3, amp=0.5 * 10 ** (-20 / 20)), np.zeros(int(0.1 * sr))])
    _, _, drops_q, flag_q = voice.cut_tail(quiet.copy())
    check("合成: 線B では静かな雑音（−20dB・0.3秒）は削られる", drops_q == 1 and flag_q["max_db"] is not None and flag_q["max_db"] <= -9.0,
          f"{drops_q}回・{flag_q['max_db']}")
    check("cut_tail の既定の線は −9dB", voice.LINE_A["r1_max_db"] == -9.0 and voice.LINE_A["r1_len"] == 0.45)


def test_lexicon():
    sc = json.loads((VIDEO1 / "script.json").read_text(encoding="utf-8"))
    lex = lexicon.merged_lexicon(VIDEO1)
    s3 = next(s for s in sc["sentences"] if s["id"] == "S3")
    check("読みの例外: 鍵→カギ・「・」→「、」だけ直り、場面・手入れ・好みは漢字のまま",
          lexicon.voice_text(s3, lex) == "選ぶカギは、場面、手入れ、好み。", lexicon.voice_text(s3, lex))
    check("読みの例外: 琥珀時間→こはくじかん", lexicon.voice_text({"phrases": ["琥珀時間の記事で。"]}, lex) == "こはくじかんの記事で。")
    check("読みの例外: 共通の表は例外だけ（10語以下）で、場面・選ぶ・使うは入っていない",
          len(json.loads(Path(lexicon.COMMON).read_text(encoding="utf-8"))["entries"]) <= 10
          and not any(k in ("場面", "選ぶ", "使う", "手入れ") for k, _ in lex))
    check("kanji_left は無い", not hasattr(lexicon, "kanji_left"))


def test_template():
    p = VIDEO1 / "video-1.film.json"
    if not p.exists():
        print("SKIP 型テンプレート: video-1.film.json が無い")
        return
    data = json.loads(p.read_text(encoding="utf-8"))
    html = film.render_film(data)
    check("型テンプレート: film.html が描けて、置き残しの {{ }} が無い", "{{" not in html and "scrim-bot" in html)
    sec = data["sections"]
    check("型テンプレート: 区間の秒が定数に入る", f"E0 = {sec['E']}" in html and f"H0 = {sec['H']}" in html)
    check("エンドカードの尺: TAIL が 3.45（AI表示の α≥0.9 が 2.5秒以上見える長さ）", voice.TAIL == 3.45, str(voice.TAIL))


def test_rules():
    p = VIDEO1 / "video-1.film.json"
    tl = VIDEO1 / "work" / "timeline.json"
    if not p.exists() or not tl.exists():
        print("SKIP R7: video-1.film.json か timeline.json が無い")
        return
    data = json.loads(p.read_text(encoding="utf-8"))
    dur = json.loads(tl.read_text(encoding="utf-8"))["duration"]
    check("ease: power2.inOut の中間は 0.5・none は線形", abs(rules.ease("power2.inOut", 0.5) - 0.5) < 1e-9 and rules.ease("none", 0.3) == 0.3)
    traj = rules.simulate(data, dur)
    x, y, s = rules.cam_at(traj, "#b-mug", int(round(rules.constants(data)["DS"] * rules.FPS)) + 24)   # DS + 0.8 の直後
    check("カメラの再現: DS + 0.8 に下の段が目標の位置（x -210・y -305・scale 0.9）にいる", abs(x + 210) < 1 and abs(y + 305) < 1 and abs(s - 0.9) < 0.01,
          f"x{x:.1f} y{y:.1f} s{s:.3f}")
    (smax, at, ids), rows, _ = rules.screens(data, dur, film.CREDIT)
    check("R7(b): 1画面の字数が30字以下", smax <= rules.MAX_SCREEN_CHARS, f"最大 {smax}字（{at}秒 {ids}）")
    subj = rules.subjects(data, traj)
    bad = [r for r in subj if r["gate"] and not r["ok"]]
    check("R7(c): 主題が帯 168〜1330 の中（参考の行を除く）", subj and not bad, "; ".join(f"{r['name']} {r['band_margin']}" for r in bad))
    c = rules.constants(data)
    pts = [rules.point_geometry(data, traj, r[0], r[1], rules.ev(r[2], c)) for r in data.get("qa_points", []) if len(r) >= 3]
    check("点が見える範囲の端で切れていない", pts and not any(g["clipped"] for g in pts))
    from video.runtime import Runtime
    rt = Runtime()
    have = rules.cmap_chars(rt.asset("font_head_bold")) & rules.cmap_chars(rt.asset("font_head_medium"))
    missing = [ch for ch in rules.head_text(data) if ord(ch) not in have]
    check("見出しの字体（Zen Maru Gothic）に見出し・答えの字がそろっている", not missing and len(have) > 7000, f"{len(have)}字・不足 {missing}")
    html = film.render_film(data)
    check("見出しの字体が Zen Maru Gothic（太さ 700・500）", '--head:"Zen Maru Gothic"' in html and "--hw-b:700" in html and "--hw-s:500" in html)


def dot_frame(bg, fill, ring, ring_w, core=10.0):
    """背景 bg の 1080×1920 に、中心 (540, 960) の点（中 fill・縁取り ring・太さ ring_w × core）を 4倍で描いて縮めたコマと、その幾何"""
    from PIL import Image, ImageDraw
    s, cx, cy = 4, 540, 960
    fr, outer = film.DOT_FILL * core, (film.DOT_FILL + ring_w) * core
    im = Image.new("RGB", (240 * s, 240 * s), (bg,) * 3)
    d = ImageDraw.Draw(im)
    c = 120 * s
    d.ellipse([c - outer * s, c - outer * s, c + outer * s, c + outer * s], fill=(ring,) * 3)
    d.ellipse([c - fr * s, c - fr * s, c + fr * s, c + fr * s], fill=(fill,) * 3)
    frame = Image.new("RGB", (1080, 1920), (bg,) * 3)
    frame.paste(im.resize((240, 240), Image.BOX), (cx - 120, cy - 120))
    return np.asarray(frame), {"center": [cx, cy], "radius": round(outer, 1), "fill_radius": round(fr, 2), "core": core}


def test_new_gates():
    from video import qa
    check("(d) の gate の線: はみ出し 0px・点のコントラスト 3.0・動画2から", qa.OVERFLOW_PX == 0 and qa.POINT_CONTRAST == 3.0 and qa.NEW_GATES_FROM == 2)
    # はみ出し
    row = {"name": "x", "cam": "#f-gift", "band_worst_at": 1.0}
    ok0, _ = qa.overflow_check([{**row, "band_worst": 0.0}])
    ok1, m1 = qa.overflow_check([{**row, "band_worst": -0.5}])
    okn, _ = qa.overflow_check([])
    check("はみ出し: 帯の端ちょうど（0px）は合格・0.5px 出ると不合格・行が無いと不合格", ok0 and not ok1 and m1["max_px"] == 0.5 and not okn)
    p = VIDEO1 / "video-1.film.json"
    tl = VIDEO1 / "work" / "timeline.json"
    if p.exists() and tl.exists():
        data = json.loads(p.read_text(encoding="utf-8"))
        traj = rules.simulate(data, json.loads(tl.read_text(encoding="utf-8"))["duration"])
        ok, m = qa.overflow_check(rules.subjects(data, traj))
        over = {r["name"][:4]: r["overflow_px"] for r in m["rows"] if r["overflow_px"] > 0}
        check("はみ出し: 動画1の作り直しは、全面の写真 B・G だけが帯の下に出て不合格", not ok and sorted(over) == ["参考 B", "参考 G"]
              and over["参考 B"] >= 79 and over["参考 G"] >= 132, str(over))
        leads = [e["lead"] for ph in data["photos"].values() for e in ph.get("extras", []) if isinstance(e, dict) and "lead" in e]
        pts = [{"name": n, "best_390px": 5.0, "contrast_390px": 5.0, "outline_contrast_390px": 1.0} for n in leads]
        okc, _ = qa.contrast_check(data, pts)
        okm, mm = qa.contrast_check(data, pts[1:])
        check("点のコントラスト: lead がすべて qa_points にあれば合格・1つ書き漏れると不合格", okc and not okm and mm["leads_missing"] == [leads[0]])
        html = film.render_film(data)
        r = next(e["r"] for e in data["photos"]["b-mug"]["extras"] if isinstance(e, dict) and e.get("lead") == "handle")
        check("点: 中の大きさを変えずに縁取りを外へ足す（円の半径＝中＋太さの半分・線の太さ＝太さ）",
              f'r="{r * (film.DOT_FILL + film.DOT_RING / 2):.2f}" style="stroke-width:{r * film.DOT_RING:.2f}px"' in html)
    # 点のコントラスト（合成のコマ。中・縁取り・背景の明るさだけを変える）
    weak = qa.point_contrast(*dot_frame(bg=95, fill=160, ring=70, ring_w=film.DOT_RING))
    dark = qa.point_contrast(*dot_frame(bg=150, fill=160, ring=10, ring_w=film.DOT_RING))
    light = qa.point_contrast(*dot_frame(bg=40, fill=250, ring=40, ring_w=film.DOT_RING))
    check("点のコントラスト: 中も縁取りも背景に近いと 3.0 未満", weak["best_390px"] < qa.POINT_CONTRAST, str(weak))
    check("点のコントラスト: 濃い縁取りが明るい背景と離れていれば、中が背景に近くても 3.0 以上",
          dark["contrast_390px"] < qa.POINT_CONTRAST <= dark["outline_contrast_390px"] and dark["best_390px"] >= qa.POINT_CONTRAST, str(dark))
    check("点のコントラスト: 明るい中が暗い背景と離れていれば 3.0 以上", light["contrast_390px"] >= qa.POINT_CONTRAST, str(light))


def test_dot_layer_and_windows():
    """点の層（陰の上・D-0304）と、全面の写真の許容範囲（rules.full_windows）。"""
    p = VIDEO1 / "video-1.film.json"
    tl = VIDEO1 / "work" / "timeline.json"
    if not p.exists() or not tl.exists():
        print("SKIP 点の層・許容範囲: video-1.film.json か timeline.json が無い")
        return
    data = json.loads(p.read_text(encoding="utf-8"))
    html = film.render_film(data)
    pos = {k: html.find(k) for k in ('class="shade-bot"', 'id="b-mug-d"', 'id="b-col-d"', 'id="scrim-bot"', 'class="shade-top"', 'id="t-aft-d"',
                                      'id="c-handle"', 'id="c-saucer"', 'id="c-rim"', 'id="c-box"', 'id="f-gift"', 'id="b-mug"')}
    check("点の層: 下の段の点は陰（.shade-bot）の後・幕（scrim-bot）の前、上の段の点は陰（.shade-top）の後",
          min(pos.values()) >= 0 and pos['class="shade-bot"'] < pos['id="b-mug-d"'] < pos['id="b-col-d"'] < pos['id="scrim-bot"']
          and pos['class="shade-top"'] < pos['id="t-aft-d"'], str(pos))
    check("点の層: handle は下の段の点の層・saucer と rim は上の段の点の層に入り、写真の層（#b-mug）には無い",
          pos['id="b-col-d"'] > pos['id="c-handle"'] > pos['id="b-mug-d"'] and pos['id="c-saucer"'] > pos['id="t-aft-d"'] and pos['id="c-rim"'] > pos['id="t-aft-d"']
          and not (pos['id="b-mug"'] < pos['id="c-handle"'] < pos['class="shade-bot"']))
    check("点の層: 全面の写真（陰が無い）の点 box は写真と同じ層のまま（-d の層は無い）", 'id="f-gift-d"' not in html and pos['id="c-box"'] > pos['id="f-gift"'])
    check("点の層: カメラの動き（#t-aft 形の対象）は点の層にも同じ値を当て、#t-aft-img は変えない",
          'gsap.set("#t-aft, #t-aft-d", ' in html and 'tl.to("#b-mug, #b-mug-d", ' in html and '"#t-aft-img, ' not in html and "#b-mug-d-img" not in html)
    check("点の層: mirror_cams は #t-aft 形だけに足し、#t-aft-img・#c-handle は変えない",
          film.mirror_cams('a("#t-aft"); b("#t-aft-img"); c("#c-handle")') == 'a("#t-aft, #t-aft-d"); b("#t-aft-img"); c("#c-handle")')
    # 許容範囲
    traj = rules.simulate(data, json.loads(tl.read_text(encoding="utf-8"))["duration"])
    rows = rules.full_windows(data, traj)
    by = {r["name"][:4]: r for r in rows}
    check("許容範囲: 全面の行は動画1で B・G の2行", sorted(by) == ["参考 B", "参考 G"], str(sorted(by)))
    b, g = by.get("参考 B"), by.get("参考 G")
    if b and g:
        check("許容範囲: 幅（px）は比率によらず同じで、2:3 の %・9:16 の % はその px を高さで割った値",
              abs(b["width_px"] - (b["p23"][1] - b["p23"][0]) / 100 * rules.PHOTO_H) < 5
              and abs(b["width_px"] - (b["p916"][1] - b["p916"][0]) / 100 * rules.RATIO_9_16_H) < 5
              and abs(g["p916_src"][0] - g["p916"][0] - 200 / rules.RATIO_9_16_H * 100) < 0.2, f"B {b['p23']} {b['p916']} {b['p916_src']}")
        check("許容範囲: 動画1 の B は 77px・G は 144px 上へ寄せれば収まる（下に出ている量）", 76 <= b["shift_up_px"] <= 79 and 143 <= g["shift_up_px"] <= 146,
              f"B {b['shift_up_px']}・G {g['shift_up_px']}")
        # 範囲どおりに主役を動かすと、gate のはみ出し（rules.subjects）が 0 になる
        def move_up(r):
            if len(r) < 5 or r[1] != "#f-gift":
                return r
            dy = by[r[0][:4]]["shift_up_px"] + 0.5
            x0, y0, x1, y1 = r[2]
            return [r[0], r[1], [x0, y0 - dy, x1, y1 - dy], *r[3:]]
        moved = {**data, "qa_subjects": [move_up(r) for r in data["qa_subjects"]]}
        over = [x["band_worst"] for x in rules.subjects(moved, traj) if x["cam"] == "#f-gift"]
        check("許容範囲: 範囲の分だけ主役を上へ動かすと、全面の行のはみ出しが 0px になる", over and min(over) >= 0, str(over))
    lines = rules.full_window_lines(rows)
    check("許容範囲: 依頼文の行に 2:3・9:16 の % が入る", len(lines) == 2 and all("2:3 なら" in ln and "9:16 をそのまま" in ln for ln in lines))


def test_next_candidates():
    """題材の候補（make-video.py next・D-0305）。メモリ上のデータだけを使い、ファイルには書かない。窓の値は check-advance-pin-today.py のものを使う。"""
    import datetime
    import importlib.util
    spec = importlib.util.spec_from_file_location("make_video", os.path.join(SCRIPT_DIR, "make-video.py"))
    mv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mv)
    adv = mv.advance_pin()
    target = datetime.date(2026, 10, 28)

    def peak_in(days):
        d = target + datetime.timedelta(days=days)
        return [(d.month, d.day)]

    lo, hi = adv.WINDOW_MIN_DAYS, adv.WINDOW_MAX_DAYS
    calendar = {"in-min": {"peaks": peak_in(lo)}, "in-max": {"peaks": peak_in(hi)}, "out-near": {"peaks": peak_in(lo - 1)},
                "out-far": {"peaks": peak_in(hi + 1)}, "no-peak": {"peaks": []}, "not-target": {"peaks": peak_in(lo + 5)},
                "unpublished": {"peaks": peak_in(lo + 5)}}
    posts = {s: {"category": "gift", "date": "2026-01-01"} for s in ("in-min", "in-max", "out-near", "out-far", "no-peak")}
    posts["not-target"] = {"category": "tea", "date": "2026-01-01"}   # unpublished は posts に無い
    slugs = lambda cs: [c["slug"] for c in cs]   # noqa: E731
    cands = mv.pick_candidates(target, calendar, posts, set(), adv)
    check("候補: 窓の内側（下限・上限ちょうど）だけ。外側・山なし・対象外のカテゴリ・未公開は出ない", slugs(cands) == ["in-min", "in-max"], str(slugs(cands)))
    check("候補: 残り日数が窓の値（check-advance-pin-today.py の WINDOW_MIN_DAYS・WINDOW_MAX_DAYS）と一致", [c["days"] for c in cands] == [lo, hi])
    check("候補: 投稿済みの slug は出ない", slugs(mv.pick_candidates(target, calendar, posts, {"in-min"}, adv)) == ["in-max"])
    wip = mv.wip_slugs_of([(1, "in-min"), (2, "in-max"), (3, None)], {1: "in-min"})
    check("制作中: 台帳に無い番号のフォルダの slug だけ（台帳にある番号・slug の無いフォルダは数えない）", wip == {"in-max"}, str(wip))
    check("候補: 制作中の slug は出ない", slugs(mv.pick_candidates(target, calendar, posts, wip, adv)) == ["in-min"])
    check("候補: 投稿済みと制作中で窓の中がすべて除かれると 0件", mv.pick_candidates(target, calendar, posts, {"in-min", "in-max"}, adv) == [])
    tie = {"b-tie": {"peaks": peak_in(lo + 3)}, "a-tie": {"peaks": peak_in(lo + 3)}, "z-near": {"peaks": peak_in(lo + 1)}}
    tie_posts = {s: {"category": "seasons", "date": "2026-01-01"} for s in tie}
    check("並び順: 山が近い順 → slug の昇順", slugs(mv.pick_candidates(target, tie, tie_posts, set(), adv)) == ["z-near", "a-tie", "b-tie"])
    year = {"x": {"peaks": [(1, 5), (12, 1)]}}
    yc = mv.pick_candidates(datetime.date(2026, 12, 1) - datetime.timedelta(days=lo), year, {"x": posts["in-min"]}, set(), adv)
    check("候補: 複数の山のうち次の山で数える", slugs(yc) == ["x"] and yc[0]["days"] == lo)
    check("--create: 投稿済みは拒否（理由を1行）", mv.create_verdict("in-min", {"in-min"}, set(), {"in-max"})[0] is True)
    check("--create: 制作中は拒否（理由を1行）", mv.create_verdict("in-max", set(), {"in-max"}, {"in-min"})[0] is True)
    refused, msg = mv.create_verdict("elsewhere", {"in-min"}, {"in-max"}, {"c"})
    check("--create: 候補の範囲外は拒否せず「【注意】題材の範囲外」", refused is False and msg and msg.startswith("【注意】題材の範囲外"), str(msg))
    check("--create: 候補の中は注意なしで通る", mv.create_verdict("c", set(), set(), {"c"}) == (False, None))


VIDEO2 = ROOT / "output" / "videos" / "video-2"
# 動画2の画面の字の直し（審査の指摘 R3）。(直した後, 直す前)。直す前の film.json は残っていないため、直した後から逆に戻して作る（scratchpad の patch_gen.py の置き換えの逆）
V2_TEXT_BEFORE = [("配るときに", "職場でも家族でも"), ("分けやすい", "1袋ずつ"), ("受け取る側は", "もらった人は"), ("自分のペースで", "好きなときに"),
                  ("コンパクト", "かさばらない"), ("持ち歩ける", "バッグ"), ("渡す人にも、もらう人にも", "渡す側も受け取る側も"), ("気軽に", "負担に"),
                  ("渡せる", "ならない"), ("遠くの家族にも", "離れて暮らす家族にも"), ("送るのもラク", "メール便なら送りやすい"),
                  ("クセ控えめ", "クセの強い茶葉より"), ("飲みやすさ重視", "飲みやすい紅茶"), ("いろいろ試せる", "数種類の飲み比べ"), (">贈る</text>", ">お礼</text>")]


def swap(obj, pairs):
    if isinstance(obj, dict):
        return {k: swap(v, pairs) for k, v in obj.items()}
    if isinstance(obj, list):
        return [swap(v, pairs) for v in obj]
    if isinstance(obj, str):
        for a, b in pairs:
            obj = obj.replace(a, b)
    return obj


def v2_before(film_data):
    """動画2の直す前: 画面の字を声の写しに戻し、E区間のぼかしの戻し（E0 + 0.8 の t-aft-img）を外す。"""
    f = swap(film_data, V2_TEXT_BEFORE)
    f["cues"]["E"] = [c for c in f["cues"]["E"] if not (isinstance(c, dict) and c.get("to") == "#t-aft-img" and c.get("t") == "E0 + 0.8")]
    return f


def test_script_checks():
    """動画3以降の台本・film.json の検査（D-0306）: (a) 同文率 (b) 最初の問い (c) 終わりの声 (d) ぼかしの戻し。"""
    from video import script_checks as sc
    p = VIDEO2 / "video-2.film.json"
    if not p.exists() or not (VIDEO2 / "script.json").exists():
        print("SKIP script_checks: 動画2の film.json か script.json が無い")
        return
    film_data = json.loads(p.read_text(encoding="utf-8"))
    script = json.loads((VIDEO2 / "script.json").read_text(encoding="utf-8"))
    check("線: 動画3から・同文率 0.30・ぼかしは 0.5 以上を 4.0秒以内に戻す",
          sc.NEW_CHECK_START == 3 and sc.SAME_TEXT_MAX == 0.30 and sc.BLUR_STRONG == 0.5 and sc.BLUR_HOLD_MAX == 4.0)

    # (a) 画面の字と声の同文率
    after, before = sc.same_text_ratio(film_data, script)[0], sc.same_text_ratio(v2_before(film_data), script)[0]
    check("(a) 動画2の最終版の同文率は 0.30 台（審査は「約30%」）、直す前は 0.55 を超える", 0.30 < after < 0.33 and before > 0.55, f"最終 {after:.3f}・直す前 {before:.3f}")
    ng_before, _ = sc.run({**script, "sentences": script["sentences"]}, v2_before(film_data), 3)
    check("(a) 直す前の画面の字（声の写し）は動画3の検査で不合格", any("声と同じ文言" in m for m in ng_before), ng_before)
    ok_film = swap(film_data, [("受け取る側は", "贈られた人は")])
    check("(a) 最終版の1単位を声に無い言い方にすると 0.30 以下で合格", sc.same_text_ratio(ok_film, script)[0] <= 0.30
          and not any("声と同じ文言" in m for m in sc.run(script, ok_film, 3)[0]))

    # (b) 声の最初が問い
    def with_first(*phrases):
        s = json.loads(json.dumps(script))
        s["sentences"][0]["phrases"] = list(phrases)
        return s
    check("(b) 最初の文が問いでない（動画2の S1）→ 不合格", any("問いの形ではない" in m for m in sc.check_opening(script)))
    for phrases in (("お礼の紅茶、", "何で選ぶ？"), ("お礼の紅茶は、", "何で選びますか。"), ("どれを選ぶか、", "迷っていませんか？"), ("お礼に贈るなら、どれにするかな。",)):
        check(f"(b) 問いの形は合格: {''.join(phrases)}", sc.check_opening(with_first(*phrases)) == [])
    check("(b) 問いのあとに答えが続いても、最初の文が問いなら合格", sc.check_opening(with_first("何で選ぶ？", "答えは、渡しやすさ。")) == [])
    check("(b) 最初の文が答えで、2文目が問いなら不合格", sc.check_opening(with_first("答えは渡しやすさ。", "何で選ぶ？")) != [])

    # (c) 終わりの声
    def with_last(*phrases):
        s = json.loads(json.dumps(script))
        s["sentences"][-1]["phrases"] = list(phrases)
        return s
    check("(c) 動画2の終わりの声（見出しの言い直しで終わる）→ 不合格", len(sc.check_closing(script)) >= 3, sc.check_closing(script))
    good = ("答えは、", "渡しやすさで選ぶことです。", "予算別のおすすめは", "記事にまとめています。", "リンクからどうぞ。")
    check("(c) 形を満たす終わりの声（答え→記事に載っていること→リンクから）は合格", sc.check_closing(with_last(*good)) == [], sc.check_closing(with_last(*good)))
    for label, phrases, want in (
            ("短い言い直し（渡しやすさで選ぶ。記事を読む。）", ("渡しやすさで選ぶ。", "記事を読む。"), "文"),
            ("リンクの案内が無い", ("答えは、渡しやすさで選ぶことです。", "予算別のおすすめは記事にまとめています。", "気になる方はぜひ。"), "リンク"),
            ("記事に何が載っているかを言わない", ("答えは、渡しやすさで選ぶことです。", "とても役に立つ内容です。", "リンクからどうぞ。"), "記事"),
            ("記事の文が短い（記事で読む。）", ("答えは、渡しやすさで選ぶことです。", "続きは記事で。", "リンクからどうぞ。"), "短い"),
            ("最後の文が行き方でない", ("答えは、渡しやすさで選ぶことです。", "リンクから記事に進めます。", "予算別のおすすめは記事にまとめています。"), "最後の文"),
            ("答えの文より前に記事を言う", ("予算別のおすすめは記事にまとめています。", "答えは、渡しやすさで選ぶことです。", "リンクからどうぞ。"), "答えの文より前"),
            ("字数が足りない", ("答えは渡す人。", "詳しくは記事で見られます。", "リンクからどうぞ。"), "字（")):
        res = sc.check_closing(with_last(*phrases))
        check(f"(c) 不合格: {label}", any(want in m for m in res), res)

    # (d) ぼかしなどの戻し
    check("(d) 動画2の最終版は合格（E0 + 0.8 の戻しがある）", sc.check_effects(film_data) == [], sc.check_effects(film_data))
    bad = sc.check_effects(v2_before(film_data))
    check("(d) 直す前（E0 + 0.8 の戻しが無い）は不合格・寄りのぼかしが13秒戻らない", len(bad) == 1 and "#t-aft-img" in bad[0] and "13.0秒後" in bad[0], bad)
    v1 = json.loads((VIDEO1 / "video-1.film.json").read_text(encoding="utf-8")) if (VIDEO1 / "video-1.film.json").exists() else None
    if v1:
        check("(d) 動画1の最終版（E0 + 1.10 の戻し）も合格", sc.check_effects(v1) == [], sc.check_effects(v1))
    no_initial = json.loads(json.dumps(film_data))
    no_initial["photos"]["b-col"]["blur"] = 1
    check("(d) 写真の初期のぼかしを戻す cue が無ければ不合格", any("#b-col-img" in m and "初期" in m for m in sc.check_effects(no_initial)), sc.check_effects(no_initial))
    late = json.loads(json.dumps(film_data))
    for c in late["cues"]["E"]:
        if isinstance(c, dict) and c.get("t") == "E0 + 0.8" and c.get("to") == "#t-aft-img":
            c["t"] = "E0 + 5"
    check("(d) 戻しが 4.0秒より遅ければ不合格", any("4.0秒以内" in m for m in sc.check_effects(late)), sc.check_effects(late))
    text_bad = json.loads(json.dumps(film_data))
    text_bad["cues"]["E"].append({"fromTo": "#care-hd2", "from": {"opacity": 0, "filter": "blur(8px)"}, "v": {"opacity": 1}, "t": 34.8})
    text_bad["cues"]["E"].append({"to": "#care-hd1", "v": {"filter": "blur(6px)", "duration": 0.3}, "t": 35})
    res = sc.check_effects(text_bad)
    check("(d) 文字の blur が戻らない fromTo と、消えない to は不合格", len(res) == 2, res)

    # 対象外: 動画1・2は止めない（INFO で出す）・動画3は止める
    ng2, info2 = sc.run(script, v2_before(film_data), 2)
    ng3, _ = sc.run(script, v2_before(film_data), 3)
    check("動画2は対象外（NG に数えず INFO で出す）・動画3は同じ内容で不合格", ng2 == [] and any("対象外" in m for m in info2) and len(ng3) >= 5, (ng2, len(ng3)))
    ng_none, info_none = sc.run(script, None, 3)
    check("film.json が無い間は台本の分（b・c）だけ検査し、(a)(d) は後で検査すると INFO で出す", len(ng_none) >= 4 and any("film.json がまだ無い" in m for m in info_none), (ng_none, info_none))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    test_script_checks()
    test_next_candidates()
    test_candidates()
    test_synthetic()
    test_lexicon()
    test_template()
    test_rules()
    test_new_gates()
    test_dot_layer_and_windows()
    print(f"{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
