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


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
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
