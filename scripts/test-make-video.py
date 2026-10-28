# -*- coding: utf-8 -*-
r"""make-video.py の部品（site/scripts/video/）のテスト。本物のファイルは読むだけ（9・10 は一時フォルダに書き、終わりに消す）。

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
8. 部品の形（D-0307）: 動画2を部品の形で書き直した video-2.parts.json から作った film.json が、qa の表と注釈を除いて今の video-2.film.json と同じで、
   film.html が今の composition の film.html とバイト単位で同じ。部品から作った qa の3つの表が手書きの表と同じ（違いは名前・句の頭でない声の秒・
   区間の 0.1秒以内・点を測る秒の 0.15秒以内だけで、gate の結果は同じ）。時刻の書き方・割り方とつなぎの検査・動画1・2の film.json を書き換えない守り。
9. 組み立ての指紋と似すぎ・投稿しないテスト（D-0308）: 動画1 対 動画2 は線以上、部品を入れ替えたダミーは線の下。似すぎは check-script・film の段・
   film の操作・build の最初（どの段も走らない）で終了コード1。比べる相手は投稿済み＋保留中のテストの直近3本で、見送りは除く。
   next --create --test は build.json の mode=test と動画md の保留の行を作り、drop で slug が候補に戻る（番号は使い切り）。
   release は季節の題材の【注意】で止まり、--confirmed で保留の行を消して mode=released。output/videos/ と台帳は一時フォルダの写し
10. 画像生成の上限（D-0308）: 1本6回・直近7日の動画の写真12回・日次の画像生成から5時間。基準日を差し替えたダミーの記録で、超えると1枚も作らずに止まる
11. 外部送信の遮断（D-0308）: os.environ に鍵があっても HyperFrames へ渡す env から外れ、snapshot は --describe false で呼ぶ
12. 場面の数を固定しない・部品 a・b・最初の試作の準備（D-0310）: 部品6つと10の組み立てから film.json・film.html・qa の3つの表を作り、film の段と
   check-script（D-0306・似すぎ）を通る。動画1・2の film.html は一般化の前と同じ。部品 a（なぞる）・b（時間の流れ）の宣言と止まる所。
   投稿済みの slug の --test（release は拒否）・--images-from（生成0回）。output/videos/drafts/ の試作の下書きが似すぎの判定を通る

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


def test_parts():
    """部品の形（video/parts.py・D-0307）。動画2の定義から作った film.json・film.html・qa の表を今のものと比べる。ファイルには書かない。"""
    from decimal import Decimal
    from video import parts, qa, script_checks
    if not (VIDEO2 / "video-2.parts.json").exists() or not (VIDEO2 / "work" / "timeline.json").exists():
        print("SKIP 部品の形: video-2.parts.json か timeline.json が無い")
        return
    hand = json.loads((VIDEO2 / "video-2.film.json").read_text(encoding="utf-8"))
    defn, tl, sc = parts.load(VIDEO2)
    gen, summary = parts.compile_film(defn, tl, sc)
    keys = [k for k in hand if not k.startswith("qa_") and k != "_comment"]
    check("部品の形: 動画2の film.json は qa の表と注釈を除いて今と同じ（cues・字・写真の点・隠す字・区間の秒）",
          list(gen) == list(hand) and all(gen[k] == hand[k] for k in keys), [k for k in keys if gen[k] != hand[k]])
    comp = (VIDEO2 / "composition" / "compositions" / "film.html").read_bytes()
    check("部品の形: 作った film.html が今の composition の film.html とバイト単位で同じ",
          film.render_film(gen).replace("\n", "\r\n").encode("utf-8") == comp)
    check("部品の形: 動画2の部品は8つ（A〜H）で、最後はエンドカード", [s["letter"] for s in summary] == list("ABCDEFGH") and summary[-1]["scene"] == "endcard")
    check("区間の数の一般化: 動画1・2の film.json は、答えの区間が G・エンドカードが H・定数の区間が E〜H（案Aと同じ）",
          film.answer_letter(hand) == "G" and film.section_letters(hand)[-1] == "H" and film.const_letters(film.section_letters(hand)) == list("EFGH")
          and film.answer_letter(json.loads((VIDEO1 / "video-1.film.json").read_text(encoding="utf-8"))) == "G")
    # 動画1の composition（11:57 に組んだもの）は、そのあとの型の更新（14:10）の前の出力で、今の型の出力とは元から違う。比べる相手は、区間の数を一般化する前の
    # film.py・型で動画1の film.json を描いた出力の sha256（2026-10-28・reports/2026-10-28-15.md）
    import hashlib
    v1 = film.render_film(json.loads((VIDEO1 / "video-1.film.json").read_text(encoding="utf-8"))).replace("\n", "\r\n").encode("utf-8")
    check("区間の数の一般化: 動画1の film.json から描いた film.html が、一般化の前の型の出力と同じ（sha256 29c112ea…29ba）",
          hashlib.sha256(v1).hexdigest() == "29c112ea396eb35514c78bad91f95fcdca2568ef307103d878c656cb526a29ba")

    # qa_text_sync: 予定秒と領域は同じ。声は句の頭で指したときの句（カードの2・3枚目は句の途中の語なので句の頭 11.8 になる）。名前は id で始まる
    th, tg = hand["qa_text_sync"][1:], gen["qa_text_sync"][1:]
    voice_diff = [g[0] for h, g in zip(th, tg) if h[2] != g[2]]
    check("qa_text_sync: 行の数・予定秒・領域が手書きと同じ。名前は同じ id で始まる",
          len(th) == len(tg) and all(h[1] == g[1] and h[3] == g[3] and g[0].split()[0] == h[0].split()[0].split("（")[0] for h, g in zip(th, tg)))
    check("qa_text_sync: 声の句の頭が違うのはカードの2・3枚目だけ（句の頭 11.8）", voice_diff == ["card2 2軽さ", "card3 3種類"]
          and all(g[2] == 11.8 for g in tg if g[0] in voice_diff), voice_diff)
    # qa_subjects: カメラ・矩形・参考の印は同じ。区間は 0.1秒以内の差で、gate の結果と余白は同じ
    ch = rules.constants(hand)
    sh, sg = hand["qa_subjects"][1:], gen["qa_subjects"][1:]
    window_ok = all(abs(rules.ev(h[3], ch) - g[3]) <= 0.1 + 1e-9 and abs(rules.ev(h[4], ch) - g[4]) <= 0.1 + 1e-9 for h, g in zip(sh, sg))
    check("qa_subjects: カメラ・主役の矩形・参考の印が同じで、区間の差は 0.1秒以内",
          len(sh) == len(sg) and window_ok and all(h[1:3] == g[1:3] and (len(h) > 5) == (len(g) > 5) for h, g in zip(sh, sg)))
    traj = rules.simulate(hand, tl["duration"])
    rh, rg = rules.subjects(hand, traj), rules.subjects(gen, traj)
    check("qa_subjects: 主役が帯の中（r7_subject_in_band）・はみ出し 0px の結果が手書きと同じ",
          [r["ok"] for r in rh] == [r["ok"] for r in rg] and qa.overflow_check(rh)[0] == qa.overflow_check(rg)[0] is True
          and all(abs(a["band_worst"] - b["band_worst"]) <= 0.5 for a, b in zip(rh, rg)))
    # qa_points: 名前とカメラは同じ。測る秒は点・線・光の範囲が出きった時（手書きとの差は 0.15秒以内）。端切れなし
    ph = {r[0]: r for r in hand["qa_points"][1:]}
    pg = gen["qa_points"][1:]
    check("qa_points: 点の名前とカメラが手書きと同じで、測る秒の差は 0.15秒以内",
          sorted(ph) == sorted(r[0] for r in pg) and all(ph[r[0]][1] == r[1] and abs(ph[r[0]][2] - r[2]) <= 0.15 for r in pg), str(pg))
    check("qa_points: 部品から作った秒で点が端で切れていない",
          not any(rules.point_geometry(gen, traj, r[0], r[1], r[2])["clipped"] for r in pg))
    # 案Aの物差し（script_checks・rules）は部品の形でも同じ値
    sj = json.loads((VIDEO2 / "script.json").read_text(encoding="utf-8"))
    check("script_checks の screen_units・blur_events・同文率と rules の字数・見出しの字・カメラの再現が、部品の形でも同じ値",
          script_checks.screen_units(gen, sj) == script_checks.screen_units(hand, sj) and script_checks.blur_events(gen) == script_checks.blur_events(hand)
          and script_checks.same_text_ratio(gen, sj) == script_checks.same_text_ratio(hand, sj)
          and rules.screens(gen, tl["duration"], film.CREDIT)[0] == rules.screens(hand, tl["duration"], film.CREDIT)[0]
          and rules.head_text(gen) == rules.head_text(hand) and rules.simulate(gen, tl["duration"]) == traj)

    # 時刻の書き方
    e = parts.Ctx(tl, (Decimal("23.25"), Decimal("36.30")), "E", {"ES": Decimal("30.00")})
    dd = parts.Ctx(tl, (Decimal("14.32"), Decimal("23.25")), "D", {"DS": Decimal("19.63")})
    check("時刻: 句の頭±秒・文の終わり・区間の始まり（型の定数がある区間は式）・終わり・mark",
          dd.t("S4.p3-0.26") == 17.35 and e.t("S7.end+0.45") == 48.73 and e.t("start+0.25") == "E0 + 0.25" and e.t("start-0.1") == "E0 - 0.1"
          and dd.t("start+0.05") == 14.37 and dd.t("end-0.25") == 23.0 and dd.t("DS+0.8") == "DS + 0.8" and e.t("S5.p2") == 24.093
          and e.ref("S4.p3+0.08").voice == Decimal("17.61"))
    for bad in ("S9.p1", "S4.p9", "DX", "17.35", "S4.p3*2"):
        try:
            dd.t(bad)
            ok = False
        except parts.PartsError:
            ok = True
        check(f"時刻: 書けない形・無い句・決めていない mark は止まる: {bad}", ok)
    # 割り方とつなぎ
    def broken(edit):
        d2 = json.loads(json.dumps(defn))
        edit(d2)
        try:
            parts.compile_film(d2, tl, sc)
            return None
        except parts.PartsError as ex:
            return str(ex)
    msgs = {"部品の数（1つ）": broken(lambda x: x.update({"parts": x["parts"][-1:]})),
            "エンドカードが途中": broken(lambda x: x["parts"].insert(3, {"scene": "endcard", "start": "S4.p1-0.40", "beats": []})),
            "つなぎの向き": broken(lambda x: x["parts"][1]["beats"][0].update({"fx": "wipe", "top": {"cam": "#t-aft", "from": {}, "to": {}},
                                                                               "bot": {"cam": "#b-mug", "from": {}, "to": {}}})),
            "つなぎ無しで割り方が変わる": broken(lambda x: x["parts"][3]["beats"].pop(0)),
            "見えないカメラ": broken(lambda x: x["parts"][2]["beats"].append({"cam": "#t-aft", "to": {"x": 0}, "d": 1, "ease": "none", "at": "start"})),
            "カメラを tween で書く": broken(lambda x: x["parts"][2]["beats"].append({"tween": "#f-gift", "v": {"x": 0}, "at": "start"})),
            "始まりが前の部品より前": broken(lambda x: x["parts"][4].update({"start": "S3.p1"}))}
    check("部品の検査: 部品の数（2〜26）・途中のエンドカード・つなぎの向き・つなぎ無しの割り方の変化・見えないカメラ・カメラの tween・始まりの順は止まる",
          all(msgs.values()), {k: (v or "")[:40] for k, v in msgs.items()})
    # 動画1・2は案Aの film.json のまま（film の段・film の操作は書かない）
    import argparse
    import importlib.util
    spec = importlib.util.spec_from_file_location("make_video", os.path.join(SCRIPT_DIR, "make-video.py"))
    mv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mv)
    before = (VIDEO2 / "video-2.film.json").read_bytes()
    rec = mv.stage_film(VIDEO2, None, None)
    rc = mv.cmd_film(argparse.Namespace(video="video-2", out=None))
    check("動画2: film の段は今の film.json を使い、film の操作も --out なしでは書かない（PARTS_FROM 3）",
          parts.PARTS_FROM == 3 and rec == {"source": "film.json"} and rc == 1 and (VIDEO2 / "video-2.film.json").read_bytes() == before)


def load_mv():
    import importlib.util
    spec = importlib.util.spec_from_file_location("make_video", os.path.join(SCRIPT_DIR, "make-video.py"))
    mv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mv)
    return mv


def quiet(fn, *a, **k):
    """標準出力を受けて (戻り値か SystemExit の文, 出力) を返す"""
    import contextlib
    import io
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            res = fn(*a, **k)
    except SystemExit as e:
        res = f"SystemExit: {e}"
    return res, buf.getvalue()


def dummy_defn(defn):
    """部品を入れ替えたダミーの組み立て（動画2と同じ冒頭の部品・同じ問いの形・同じエンドカード。ほかは全面の場面と別のつなぎ・章の見せ方）"""
    a, b = json.loads(json.dumps(defn["parts"][0])), json.loads(json.dumps(defn["parts"][1]))
    pt = {"point": "x", "cam": "#f-gift"}
    return {**defn, "parts": [a, b,
                              {"scene": "full", "beats": [{"chapter": 1}, pt, {"cam": "#f-gift", "to": {"scale": 1.2}, "ease": "power2.out"}]},
                              {"scene": "full", "beats": [{"chapter": 2}, pt]},
                              {"scene": "full", "beats": [{"chapter": 3}, {"answer": {}}]},
                              {"scene": "endcard", "beats": []}]}


def test_fingerprint_and_test_mode():
    """組み立ての指紋と似すぎ・投稿しないテスト・見送り・保留を外す（D-0308）。output/videos/ は一時フォルダに差し替え、本物の動画1・2は読むだけ。"""
    import argparse
    import datetime
    import shutil
    import tempfile
    from video import parts
    if not (VIDEO2 / "video-2.parts.json").exists() or not (VIDEO1 / "video-1.film.json").exists():
        print("SKIP 指紋: 動画1・2のファイルが無い")
        return
    mv = load_mv()
    tmp = Path(tempfile.mkdtemp(prefix="test-make-video-"))
    saved = mv.VIDEOS, mv.PIN_LEDGER, mv.advance_pin, mv.script_gate
    try:
        mv.VIDEOS, mv.PIN_LEDGER = tmp / "videos", tmp / "video-posted.md"
        mv.VIDEOS.mkdir()
        shutil.copy2(ROOT / "data" / "video-posted.md", mv.PIN_LEDGER)   # 投稿済みは動画1・2
        for n, names in ((1, ("video-1.film.json", "script.json", "video-1.build.json")),
                         (2, ("video-2.parts.json", "video-2.film.json", "script.json", "video-2.build.json", "work/timeline.json"))):
            for name in names:
                (mv.VIDEOS / f"video-{n}" / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / "output" / "videos" / f"video-{n}" / name, mv.VIDEOS / f"video-{n}" / name)
        defn2 = json.loads((VIDEO2 / "video-2.parts.json").read_text(encoding="utf-8"))
        sc2 = json.loads((VIDEO2 / "script.json").read_text(encoding="utf-8"))

        # 1. 指紋と似すぎ（動画1 対 動画2）
        fp1, src1 = mv.fingerprint_of(mv.VIDEOS / "video-1", prefer_parts=False)
        fp2, src2 = mv.fingerprint_of(mv.VIDEOS / "video-2", prefer_parts=False)
        s12, rows12 = parts.similarity(fp1, fp2)
        check("指紋: 動画1は動画2の parts.json を借り（film.json の区間・つなぎ・章の数が一致）、動画2は parts.json から作る",
              fp1 is not None and "video-2.parts.json の並び" in src1 and src2 == "video-2.parts.json", (src1, src2))
        check(f"似すぎ: 動画1 対 動画2 は線 {parts.SIMILAR_LINE} 以上（{s12}）", s12 >= parts.SIMILAR_LINE, rows12)
        dfp = parts.fingerprint(dummy_defn(defn2), sc2)
        sd, rowsd = parts.similarity(dfp, fp2)
        check(f"似すぎ: 部品を入れ替えたダミーは線の下で通る（動画2と {sd}・冒頭の部品と問いの形・比べ方は同じまま）",
              sd < parts.SIMILAR_LINE and dfp["opening"] == fp2["opening"] and dfp["compare"] == fp2["compare"], rowsd)
        print(f"NOTE 指紋 動画2: {json.dumps(fp2, ensure_ascii=False)}")
        print(f"NOTE 似すぎの点数 動画1 対 動画2 {s12}・ダミー 対 動画2 {sd}（線 {parts.SIMILAR_LINE}）")
        for ln in parts.similarity_lines(sd, rowsd):
            print(f"NOTE ダミー {ln.strip()}")
        check("指紋: 冒頭の問いの形（誤解・数字・選び方・予告）", [parts.hook_form(q) for q in
              ("実は熱湯はNG？", "何分蒸らす？", "お礼の紅茶、何で選ぶ？", "ミルクティーのコツ、知ってる？", "おいしい？")]
              == ["誤解", "数字", "選び方", "予告", "その他の問い"])

        # 2. 似すぎで止まる所: check-script・film の段・build の最初（どの段も書き出しの前）・film の操作
        v3 = mv.VIDEOS / "video-3"
        (v3 / "work").mkdir(parents=True)
        shutil.copy2(VIDEO2 / "video-2.parts.json", v3 / "video-3.parts.json")
        shutil.copy2(VIDEO2 / "work" / "timeline.json", v3 / "work" / "timeline.json")
        (v3 / "script.json").write_text(json.dumps(sc2, ensure_ascii=False), encoding="utf-8")
        (v3 / "video-3.build.json").write_text(json.dumps({"created_at": "2026-10-28T10:00:00", "runs": []}), encoding="utf-8")
        ng, info = mv.similarity_gate(v3)
        check("似すぎ: 動画2と同じ組み立ての動画3は、動画2・動画1の両方に似すぎ（重なった項目を出す）",
              len(ng) == 2 and all("組み立てが似すぎ" in m and "部品の並び 近さ 1.00" in m for m in ng), ng)
        rc, out = quiet(mv.cmd_check_script, argparse.Namespace(video="video-3"))
        check("似すぎ: check-script が終了コード1（NG に「組み立てが似すぎ」）", rc == 1 and "NG 組み立てが似すぎ" in out, out[-400:])
        rc, out = quiet(mv.stage_film, v3, None, None)
        check("似すぎ: film の段が止まり（SystemExit）、film.json を書かない", "似すぎ" in str(rc) and not (v3 / "video-3.film.json").exists(), rc)
        rc, out = quiet(mv.cmd_film, argparse.Namespace(video="video-3", out=None))
        check("似すぎ: film の操作も終了コード1で film.json を書かない", rc == 1 and not (v3 / "video-3.film.json").exists(), out[-200:])
        mv.script_gate = lambda *a, **k: []   # 台本の検査（D-0306）は別のテスト。ここは似すぎだけを見る
        for only in (None, "render"):
            rc, out = quiet(mv.cmd_build, argparse.Namespace(video="video-3", only=only, from_=None, redo=None), None)
            runs = json.loads((v3 / "video-3.build.json").read_text(encoding="utf-8"))["runs"]
            check(f"似すぎ: build（{only or '全段'}）は最初に終了コード1で止まり、どの段も走らない（書き出しの前）",
                  rc == 1 and "STOP similar" in out and runs == [], out[-300:])
        mv.script_gate = saved[3]
        v4 = mv.VIDEOS / "video-4"
        v4.mkdir()
        (v4 / "video-4.parts.json").write_text(json.dumps(dummy_defn(defn2), ensure_ascii=False), encoding="utf-8")
        (v4 / "script.json").write_text(json.dumps(sc2, ensure_ascii=False), encoding="utf-8")
        ng4, info4 = mv.similarity_gate(v4)
        check("似すぎ: 部品を入れ替えたダミー（動画4）は動画2・動画1と比べて通る", ng4 == [] and sum("似すぎではない" in x for x in info4) == 2, info4)

        # 3. 比べる相手: 投稿済み＋保留中のテスト（見送りは除く）の直近3本
        check("比べる相手: 投稿済みだけなら動画2・1（制作中の本番の動画3は入らない）", mv.similar_targets(4) == [2, 1], mv.similar_targets(4))
        mv.set_mode(v3, "test")
        check("比べる相手: 保留中のテストの動画3を入れる", mv.similar_targets(4) == [3, 2, 1], mv.similar_targets(4))
        ng4b, _ = mv.similarity_gate(v4)
        mv.set_mode(v3, "dropped")
        check("比べる相手: 見送りの動画3は外す", mv.similar_targets(4) == [2, 1], mv.similar_targets(4))
        check("比べる相手: ダミーは保留中のテスト（動画2と同じ組み立て）とも似すぎにならない", ng4b == [], ng4b)
        shutil.rmtree(v3)
        shutil.rmtree(v4)

        # 4. 投稿しないテスト（next --create --test）・見送り（drop）・保留を外す（release）
        adv = mv.advance_pin()
        posted = mv.posted_numbers()
        slug = next(s for s in sorted(adv.published_posts()) if s not in posted.values())
        rc, out = quiet(mv.cmd_next, argparse.Namespace(create=slug, test=True, date=None))
        v = mv.VIDEOS / "video-3"
        md = mv.VIDEOS / slug / "video-3.md"
        log = json.loads((v / "video-3.build.json").read_text(encoding="utf-8")) if v.exists() else {}
        check("テスト: next --create --test で動画3（次の番号）を作り、build.json に mode=test・動画md に保留の行",
              rc == 0 and log.get("mode") == "test" and md.exists() and mv.HOLD_LINE in md.read_text(encoding="utf-8").splitlines(), out)
        check("テスト: 保留中のテストは制作中に数える（題材の候補から外れ、--create は拒否）",
              slug in mv.wip_slugs_of(mv.wip_entries(posted), posted)
              and quiet(mv.cmd_next, argparse.Namespace(create=slug, test=False, date=None))[0] == 1)
        rc, out = quiet(mv.cmd_drop, argparse.Namespace(video="video-3", reason="テストの見送り"))
        check("見送り: drop で mode=dropped・slug は候補に戻る（制作中に数えない）",
              rc == 0 and mv.mode_of(v) == "dropped" and slug not in mv.wip_slugs_of(mv.wip_entries(posted), posted), out)
        rc, out = quiet(mv.cmd_next, argparse.Namespace(create=slug, test=True, date=None))
        check("見送り: 番号は使い切り（同じ slug の次のテストは動画4・動画3のフォルダは残る）",
              rc == 0 and (mv.VIDEOS / "video-4").exists() and v.exists() and (mv.VIDEOS / slug / "video-4.md").exists(), out)
        rc, out = quiet(mv.cmd_drop, argparse.Namespace(video="video-2", reason=None))
        check("見送り: 投稿済みの動画は拒否", rc == 1 and mv.mode_of(mv.VIDEOS / "video-2") is None, out)

        real = adv
        cal = {slug: {"peaks": [(12, 25)]}}

        def fake_adv(today):
            return argparse.Namespace(today_jst=lambda: today, load_calendar=lambda: (cal, []), next_peak=real.next_peak,
                                      WINDOW_MIN_DAYS=real.WINDOW_MIN_DAYS, WINDOW_MAX_DAYS=real.WINDOW_MAX_DAYS)
        c = datetime.date(2026, 10, 28)
        check("保留を外す前の注意: 山を過ぎた・窓の外・窓の中・山の無い題材",
              "過ぎている" in "".join(mv.season_notices(slug, c, datetime.date(2026, 12, 26), real, cal))
              and "窓" in "".join(mv.season_notices(slug, c, datetime.date(2026, 12, 10), real, cal))
              and mv.season_notices(slug, c, datetime.date(2026, 11, 15), real, cal) == []
              and mv.season_notices("no-peak", c, datetime.date(2026, 12, 26), real, {"no-peak": {"peaks": []}}) == [])
        v4, md4 = mv.VIDEOS / "video-4", mv.VIDEOS / slug / "video-4.md"
        mv.advance_pin = lambda: fake_adv(datetime.date(2026, 12, 26))
        rc, out = quiet(mv.cmd_release, argparse.Namespace(video="video-4", confirmed=False))
        check("保留を外す: 山を過ぎた季節の題材は【注意】を出して外さない（終了コード1・行も mode もそのまま）",
              rc == 1 and "【注意】" in out and mv.mode_of(v4) == "test" and mv.HOLD_LINE in md4.read_text(encoding="utf-8"), out)
        rc, out = quiet(mv.cmd_release, argparse.Namespace(video="video-4", confirmed=True))
        check("保留を外す: --confirmed で保留の行を消し mode=released（注意は build.json に残す）",
              rc == 0 and mv.mode_of(v4) == "released" and mv.HOLD_LINE not in md4.read_text(encoding="utf-8")
              and bool(json.loads((v4 / "video-4.build.json").read_text(encoding="utf-8"))["mode_log"][-1].get("notices")), out)
        rc, out = quiet(mv.cmd_release, argparse.Namespace(video="video-4", confirmed=False))
        check("保留を外す: 保留中のテストでない動画は拒否", rc == 1, out)
    finally:
        mv.VIDEOS, mv.PIN_LEDGER, mv.advance_pin, mv.script_gate = saved
        shutil.rmtree(tmp, ignore_errors=True)


FULL_SUBJECT = {"name": "贈り物の一式", "rect": [86, 940, 1400, 1442]}


def full_cover_part(v2parts):
    """全面のカバー（0コマ目から動画2の全面の写真）"""
    a = json.loads(json.dumps(v2parts[0]))
    return {"scene": "full", "name": "問い", "note": "全面のカバー",
            "cover": {**a["cover"], "cams": {**a["cover"]["cams"], "#f-gift": {"x": -150, "y": -12, "scale": 0.9}}},
            "beats": [{"cam": "#f-gift", "to": {"x": -160, "y": -20, "scale": 0.91}, "d": 4.7, "ease": "none", "at": "start", "subject": FULL_SUBJECT},
                      a["beats"][3]]}


def trace_part(start, base, pre="", tags=("小分けの袋", "小さな箱", "一杯の紅茶"), extra=()):
    """部品 a（なぞる）: 動画2の全面の写真の袋→箱→カップ。base は句（S3.p2 など）"""
    return {"scene": "trace", "name": "なぞる", "note": "部品 a", "start": start,
            "beats": [*extra, {"cam": "#f-gift", "to": {"x": -175, "y": -32, "scale": 0.92}, "d": 1.0, "ease": "power2.inOut", "at": "start",
                               "subject": FULL_SUBJECT},
                      {"trace": f"{pre}bags", "path": [[648, 1399], [702, 1264], [1015, 1231], [1161, 1404]], "at": f"{base}-0.55", "d": 0.6,
                       "lead": {"from": [1080, 1235], "to": [1085, 1330], "r": 11}, "dot": base, "line": f"{base}-0.05", "ld": 0.25,
                       "tag": {"text": tags[0], "x": 1060, "y": 1140, "w": 260, "at": f"{base}+0.06"}},
                      {"trace": f"{pre}box", "path": [[734, 1220], [726, 1010], [900, 1003], [1064, 999]], "at": f"{base}+0.45", "d": 0.6,
                       "lead": {"from": [1064, 900], "to": [1064, 990], "r": 11}, "dot": f"{base}+1.05", "line": f"{base}+1.0", "ld": 0.25,
                       "tag": {"text": tags[1], "x": 1064, "y": 806, "w": 220, "at": f"{base}+1.1"}},
                      {"trace": f"{pre}cup", "path": [[181, 1007], [420, 1063], [659, 1007], [420, 951], [181, 1007]], "at": f"{base}+1.15", "d": 0.6,
                       "lead": {"from": [420, 900], "to": [420, 1060], "r": 11}, "dot": f"{base}+1.75", "line": f"{base}+1.7", "ld": 0.25,
                       "tag": {"text": tags[2], "x": 440, "y": 806, "w": 260, "at": f"{base}+1.8"}}]}


def steps_part(start, sid, items, fx=None, extra=()):
    """部品 b（時間の流れ）。fx があれば上下から合わさって入る（merge）"""
    beats = list(extra)
    if fx:
        beats.append({"fx": "merge", "at": "start", "cam": "#f-gift", "from": {"x": -470, "y": -420, "scale": 1.15}, "exposure": 0, "split_y": 952,
                      "to": {"x": -500, "y": -450, "scale": 1.1}, "until": "start+1.0", "subject": {"name": "箱", "rect": [724, 940, 1400, 1350]}})
    else:
        beats.append({"cam": "#f-gift", "to": {"x": -500, "y": -450, "scale": 1.1}, "d": 1.0, "ease": "power2.inOut", "at": "start",
                      "subject": {"name": "箱", "rect": [724, 940, 1400, 1350]}})
    beats.append({"steps": sid, "at": "start+0.3", "items": [{"text": t, "at": at} for t, at in items]})
    return {"scene": "steps", "name": "流れ", "note": "部品 b", "start": start, "beats": beats}


def plain_full(start, name, extra=()):
    return {"scene": "full", "name": name, "note": "全面", "start": start,
            "beats": [*extra, {"cam": "#f-gift", "to": {"x": -122, "y": -67, "scale": 0.92}, "d": 1.0, "ease": "power2.inOut", "at": "start",
                               "subject": {"name": "全面", "rect": [78, 916, 1402, 1447]}}]}


def answer_part(v2parts, start=None, merge=True):
    g = json.loads(json.dumps(v2parts[6]))
    if start:
        g["start"] = start
    if not merge:
        g["beats"] = [b for b in g["beats"] if "fx" not in b] + [
            {"cam": "#f-gift", "to": {"x": -122, "y": -67, "scale": 0.92}, "d": 1.0, "ease": "power2.inOut", "at": "start",
             "subject": {"name": "全面", "rect": [78, 916, 1402, 1447]}}]
    return g


def count_defns(defn2):
    """部品の数が8でない組み立て（6と10）。動画2の写真・声の時刻表・場面を使い、部品 a・b を含む"""
    P = defn2["parts"]
    cp = lambda x: json.loads(json.dumps(x))   # noqa: E731
    base = {**cp(defn2), "photos": {**cp(defn2["photos"]), "f-gift": {**defn2["photos"]["f-gift"], "blur": 0}}}
    unblur_mug = {"grade": "#b-mug", "blur": 0, "d": 0.5, "ease": "power2.inOut", "at": "start"}
    hide_d = {"hide": ["#d-tag1", "#d-tag2", "#d-tag3", "#d-tag4"], "at": "start-0.1"}
    six = {**base, "parts": [full_cover_part(P), trace_part("S2.p1-0.10", "S3.p2", extra=[{"hide": ["#kick", "#kick-ul"], "at": "start"}]),
                             {**cp(P[3]), "beats": [{"hide": "#q", "at": "start"}, *cp(P[3])["beats"]]},
                             steps_part("S5.p1-0.26", "st", [("小さい", "S5.p2"), ("軽い", "S5.p3"), ("送れる", "S5.p6")], fx=True,
                                        extra=[hide_d, unblur_mug]),
                             answer_part(P, merge=False), cp(P[7])]}
    unspot = [{"hide": ["#b-tag", "#boxtag"], "at": "start+0.05"},
              {"tween": "#c-box", "v": {"opacity": 0, "duration": 0.2, "ease": "power2.in"}, "at": "start+0.05"},
              {"tween": "#spot-box", "v": {"opacity": 0, "duration": 0.5, "ease": "power2.in"}, "at": "start+0.05"},
              {"grade": "#f-gift", "blur": 0, "exposure": 0, "d": 0.5, "ease": "power2.inOut", "at": "start+0.05"}]
    b = cp(P[1])
    b["beats"] = [x for x in b["beats"] if "fx" not in x] + [{"cam": "#f-gift", "to": {"x": -470, "y": -499, "scale": 1.12}, "d": 5.0, "ease": "none",
                                                              "at": "start", "subject": FULL_SUBJECT}]
    ten = {**base, "parts": [full_cover_part(P), b, trace_part("S3.p1-0.09", "S3.p2", extra=unspot),
                             {**cp(P[3]), "beats": [{"hide": "#q", "at": "start"}, *cp(P[3])["beats"]]},
                             steps_part("S5.p1-0.26", "st", [("小さい", "S5.p2"), ("軽い", "S5.p3"), ("送れる", "S5.p6")], fx=True,
                                        extra=[hide_d, unblur_mug]),
                             plain_full("S5.p6-0.3", "軽さ2"),
                             trace_part("S6.p1-0.34", "S6.p2", pre="g", tags=("袋", "箱", "器")),
                             plain_full("S6.p5-0.2", "種類2"),
                             answer_part(P, merge=False), cp(P[7])]}
    return six, ten


def d0306_script(sc2):
    """D-0306 の (b)(c) を満たす台本（動画2の台本の最初と最後の文だけ差し替え・テスト用）"""
    sc = json.loads(json.dumps(sc2))
    sc["sentences"][0]["phrases"] = ["お礼の紅茶、", "何で選ぶ？"]
    sc["sentences"][2]["phrases"] = ["選ぶ視点は、", "3つあります。"]
    sc["sentences"][-1]["phrases"] = ["答えは、渡しやすさで選ぶことです。", "予算別の選び方は記事にまとめています。", "リンクからどうぞ。"]
    return sc


def test_scene_count_and_new_parts():
    """場面の数を固定しない（6と10）・部品 a・b・最初の試作の準備（D-0310）。output/videos/ は一時フォルダの写し"""
    import argparse
    import shutil
    import tempfile
    from video import images, parts, script_checks
    if not (VIDEO2 / "video-2.parts.json").exists() or not (VIDEO2 / "work" / "timeline.json").exists():
        print("SKIP 場面の数: 動画2のファイルが無い")
        return
    defn2, tl, sc2 = parts.load(VIDEO2)
    six, ten = count_defns(defn2)
    sc3 = d0306_script(sc2)

    # 1. 場面の数（6と10）: film.json・film.html・qa の3つの表
    for name, d in (("6", six), ("10", ten)):
        data, summary = parts.compile_film(d, tl, sc3)
        html = film.render_film(data)
        letters = film.letters_for(int(name))
        end = letters[-1]
        check(f"場面の数 {name}: 区間 A〜{end}・最後がエンドカード・film.html に置き残しが無く、エンドカードの定数が {end}0",
              list(data["sections"]) == letters and summary[-1]["scene"] == "endcard" and "{{" not in html
              and f'"#logo", {{ opacity: 1, duration: 0.6, ease: "sine.inOut" }}, {end}0)' in html
              and f"const {film.const_letters(letters)[0]}0 = " in html, end)
        check(f"場面の数 {name}: qa の3つの表を部品から作る（主役・点・字の同期の行がある）",
              len(data["qa_subjects"]) > 3 and len(data["qa_points"]) > 3 and len(data["qa_text_sync"]) > 5,
              (len(data["qa_subjects"]), len(data["qa_points"]), len(data["qa_text_sync"])))
        traj = rules.simulate(data, tl["duration"])
        check(f"場面の数 {name}: 案Aの物差し（字数・主役が帯の中・点の端切れ・答えの区間）が計算できる",
              rules.screens(data, tl["duration"], film.CREDIT)[0][0] <= rules.MAX_SCREEN_CHARS
              and all(r["ok"] for r in rules.subjects(data, traj) if r["gate"])
              and not any(rules.point_geometry(data, traj, r[0], r[1], r[2])["clipped"] for r in data["qa_points"][1:])
              and film.answer_letter(data) == letters[-2])

    mv = load_mv()
    tmp = Path(tempfile.mkdtemp(prefix="test-scene-count-"))
    saved = mv.VIDEOS, mv.PIN_LEDGER, mv.advance_pin
    try:
        mv.VIDEOS, mv.PIN_LEDGER = tmp / "videos", tmp / "video-posted.md"
        mv.VIDEOS.mkdir()
        shutil.copy2(ROOT / "data" / "video-posted.md", mv.PIN_LEDGER)
        for n, names in ((1, ("video-1.film.json", "script.json", "video-1.build.json")),
                         (2, ("video-2.parts.json", "video-2.film.json", "script.json", "video-2.build.json", "work/timeline.json",
                              "prompts/img1.txt", "images/img1.png", "images/img2.png", "images/img3.png", "images/img4.png",
                              "work/img/img1.jpg", "work/img/img2.jpg", "work/img/img3.jpg", "work/img/img4.jpg"))):
            for nm in names:
                if (ROOT / "output" / "videos" / f"video-{n}" / nm).exists():
                    (mv.VIDEOS / f"video-{n}" / nm).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(ROOT / "output" / "videos" / f"video-{n}" / nm, mv.VIDEOS / f"video-{n}" / nm)
        for name, d in (("6", six), ("10", ten)):
            v3 = mv.VIDEOS / "video-3"
            (v3 / "work").mkdir(parents=True)
            (v3 / "video-3.parts.json").write_text(json.dumps({**d, "n": 3}, ensure_ascii=False), encoding="utf-8")
            shutil.copy2(VIDEO2 / "work" / "timeline.json", v3 / "work" / "timeline.json")
            (v3 / "script.json").write_text(json.dumps(sc3, ensure_ascii=False), encoding="utf-8")
            rec, out = quiet(mv.stage_film, v3, None, None)
            fj = v3 / "video-3.film.json"
            check(f"場面の数 {name}: film の段が film.json を書き、check-script と同じ検査（D-0306）と似すぎを通る",
                  isinstance(rec, dict) and rec.get("source") == "parts.json" and fj.exists(), (rec, out[-600:]))
            rc, out2 = quiet(mv.cmd_check_script, argparse.Namespace(video="video-3"))
            scores = [ln for ln in out2.splitlines() if "似すぎではない" in ln]
            check(f"場面の数 {name}: check-script が SCRIPT_OK（似すぎは動画2・1と比べて線の下）", rc == 0 and "SCRIPT_OK" in out2 and len(scores) == 2,
                  out2[-600:])
            print(f"NOTE 場面の数 {name}: {' / '.join(s.split('（')[0].replace('INFO 似すぎではない ', '') + ' ' + s.split(': ')[-1] for s in scores)}")
            shutil.rmtree(v3)

        # 2. 部品 a・b の宣言（なぞる線・点・札・時間の流れの線と札）と止まる所
        data, summary = parts.compile_film(six, tl, sc3)
        ex = data["photos"]["f-gift"]["extras"]
        check("部品 a: なぞる線は写真の層の #rim-sweep（テンプレートの線）の中に部位ごとの g（glow・core）で、点・札より下",
              isinstance(ex[0], str) and ex[0].startswith('<svg id="rim-sweep"') and all(f'id="sw-{k}"' in ex[0] for k in ("bags", "box", "cup"))
              and ex[0].count('class="glow"') == 3 and ex[0].count('class="core"') == 3)
        pts = {r[0] for r in data["qa_points"][1:]}
        ts = {r[0].split()[0]: r for r in data["qa_text_sync"][1:]}
        check("部品 a: 部位ごとに点（qa_points）と札（qa_text_sync・画面の矩形は帯の中）が作られる",
              {"bags", "box", "cup"} <= pts and all(f"{k}tag" in ts and 168 <= ts[f"{k}tag"][3][1] and ts[f"{k}tag"][3][3] <= 1330 for k in ("bags", "box", "cup")),
              {k: ts.get(f"{k}tag") for k in ("bags", "box", "cup")})
        check("部品 b: 時間の流れの札は字の同期の行（矩形は帯の中・重ならない）、線・目盛り・札は最初は隠れる",
              all(f"st-t{k}" in ts and 168 <= ts[f"st-t{k}"][3][1] and ts[f"st-t{k}"][3][3] <= 1330 for k in (1, 2, 3))
              and ts["st-t1"][3][2] < ts["st-t2"][3][0] and ts["st-t2"][3][2] < ts["st-t3"][3][0]
              and {"#st", "#st-k1", "#st-k3", "#st-t1", "#st-t3"} <= {h for g in data["hidden"] for h in g})
        s_ab = {s["scene"]: s for s in summary}
        check("部品 a・b: 要約に割り方・カメラ・主役・点・字・見せ場の秒（部品の中）・指紋の語が出る",
              s_ab["trace"]["words"][0] == "部位をなぞる" and s_ab["steps"]["words"][0] == "時間の流れ"
              and all(s_ab[k]["start"] <= s_ab[k]["peak"] < s_ab[k]["end"] and s_ab[k]["subjects"] for k in ("trace", "steps"))
              and len(s_ab["trace"]["points"]) == 3 and len(s_ab["steps"]["texts"]) == 3)
        fp = parts.fingerprint(six, sc3)
        check("部品 a・b: 指紋の部品の並びに「部位をなぞる」「時間の流れ」、冒頭は全面", "部位をなぞる" in fp["parts"] and "時間の流れ" in fp["parts"]
              and fp["opening"].startswith("全面"), fp["parts"])

        def broken(edit):
            d2 = json.loads(json.dumps(six))
            edit(d2)
            try:
                parts.compile_film(d2, tl, sc3)
                return None
            except parts.PartsError as e:
                return str(e)
        msgs = {"trace を全面の寄りで": broken(lambda x: x["parts"][1].update({"scene": "full"})),
                "部位が1つ": broken(lambda x: x["parts"][1].update({"beats": x["parts"][1]["beats"][:3]})),
                "主役が無い": broken(lambda x: x["parts"][1]["beats"][1].pop("subject")),
                "線が長すぎる": broken(lambda x: x["parts"][1]["beats"][3].update({"path": [[0, 0], [1440, 0], [0, 10]]})),
                "札が重なる": broken(lambda x: x["parts"][3]["beats"][-1]["items"][1].update({"text": "とても長い札の字です"})),
                "札の時刻が近い": broken(lambda x: x["parts"][3]["beats"][-1]["items"][1].update({"at": "S5.p2+0.05"}))}
        check("部品 a・b の検査: 場面の違い・部位の数・主役なし・線の長さ・札の重なり・札の間隔は止まる", all(msgs.values()),
              {k: (v or "")[:40] for k, v in msgs.items()})

        # 3. 最初の試作の準備: 投稿済みの slug のテスト・release の拒否・--images-from
        posted = mv.posted_numbers()
        slug2 = posted[2]
        rc, out = quiet(mv.cmd_next, argparse.Namespace(create=slug2, test=False, images_from=None, date=None))
        check("試作: 投稿済みの slug は本番（--test なし）では今どおり拒否", rc == 1 and "拒否" in out and not (mv.VIDEOS / "video-3").exists(), out)
        rc, out = quiet(mv.cmd_next, argparse.Namespace(create=slug2, test=True, images_from="video-2", date=None))
        v3 = mv.VIDEOS / "video-3"
        log = json.loads((v3 / "video-3.build.json").read_text(encoding="utf-8")) if v3.exists() else {}
        check("試作: 投稿済みの slug でも --test なら作れる（【注意】・mode=test・same_slug_posted に動画2）",
              rc == 0 and "【注意】" in out and log.get("mode") == "test" and log.get("same_slug_posted") == [2], out)
        same = all((v3 / f).read_bytes() == (mv.VIDEOS / "video-2" / f).read_bytes() for f in log.get("images_from", {}).get("files", []))
        check("試作: --images-from video-2 で写真（images の png・prompts・work/img の jpg）を写し、build.json に記録、image_gens は無い",
              same and log["images_from"]["video"] == "video-2" and "images/img4.png" in log["images_from"]["files"]
              and "work/img/img4.jpg" in log["images_from"]["files"] and "image_gens" not in log, log.get("images_from"))
        ok_b, lines_b = images.budget(v3, mv.VIDEOS, 0)
        calls = []
        saved_run = images.subprocess.run
        images.subprocess.run = lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(AssertionError("gateway を呼んだ"))
        try:
            made, _ = quiet(images.generate, v3, ["img1", "img2", "img3", "img4"], "p", v3 / "video-3.build.json", mv.VIDEOS)
        finally:
            images.subprocess.run = saved_run
        check("試作: 写した写真は images の段が作らない（生成0回と数える: この動画 0回・gateway を呼ばない）",
              made == [] and not calls and "この動画 0+0/" in lines_b[0], (made, lines_b[0]))
        rc, out = quiet(mv.cmd_release, argparse.Namespace(video="video-3", confirmed=False))
        rc2, out2 = quiet(mv.cmd_release, argparse.Namespace(video="video-3", confirmed=True))
        check("試作: 同じ記事が投稿済みの動画の release は拒否（--confirmed でも・mode=test と保留の行はそのまま）",
              rc == 1 and rc2 == 1 and "投稿済み" in out2 and mv.mode_of(v3) == "test"
              and mv.HOLD_LINE in (mv.VIDEOS / slug2 / "video-3.md").read_text(encoding="utf-8"), out2)
        mv.set_mode(v3, "dropped")
        rc, out = quiet(mv.cmd_next, argparse.Namespace(create=slug2, test=True, images_from="video-9", date=None))
        check("試作: --images-from の動画が無ければ何も作らない", rc == 1 and "--images-from: 動画フォルダが無い" in out
              and not (mv.VIDEOS / "video-4").exists(), out)

        # 4. 明日の試作の下書き（output/videos/drafts/）が似すぎの判定を通る
        draft = ROOT / "output" / "videos" / "drafts" / "kinrou-kansha-no-hi-koucha-petit-gift.trial-1.parts.json"
        if draft.exists():
            dd = json.loads(draft.read_text(encoding="utf-8"))
            ng, info = mv.similarity_gate(mv.VIDEOS / "video-2", dd, "下書き")
            scores = [ln for ln in info if "似すぎではない" in ln]
            check("下書き: 試作の parts.json は部品 a を含み、直近（動画2・1）と比べて似すぎではない",
                  ng == [] and len(scores) == 2 and any(p["scene"] in ("trace", "steps") for p in dd["parts"]), (ng, scores))
            print(f"NOTE 下書き: {' / '.join(s.split(': ')[-1] for s in scores)}")
            data, _ = parts.compile_film(dd, tl, sc2)
            check("下書き: 動画2の声の時刻表で組める（部品7つ）", len(data["sections"]) == 7)
    finally:
        mv.VIDEOS, mv.PIN_LEDGER, mv.advance_pin = saved
        shutil.rmtree(tmp, ignore_errors=True)


def test_image_budget():
    """画像生成の上限（D-0308）: 1本・直近7日の動画の写真・日次の画像生成からの時間。基準日（now）を差し替えたダミーの記録で見る。"""
    import shutil
    import tempfile
    from datetime import datetime, timedelta
    from video import images
    tmp = Path(tempfile.mkdtemp(prefix="test-image-budget-"))
    base = datetime(2026, 11, 10, 12, 0)

    def video(name, gens=(), legacy=None):
        d = tmp / "videos" / name
        d.mkdir(parents=True)
        log = {"runs": [], "image_gens": [{"at": t.isoformat(timespec="seconds"), "name": "img"} for t in gens]}
        if legacy:
            log["runs"].append(legacy)
        (d / f"{name}.build.json").write_text(json.dumps(log), encoding="utf-8")
        return d

    def gw(*times):
        for t in times:
            (tmp / "gw" / f"{t:%Y%m%d-%H%M%S}-image-gen.jsonl").write_text("{}", encoding="utf-8")
    try:
        (tmp / "gw").mkdir()
        check("上限の値: 1本6回・7日12回・日次から5時間", (images.VIDEO_GEN_MAX, images.WEEK_GEN_MAX, images.WEEK_DAYS, images.DAILY_GAP_HOURS) == (6, 12, 7, 5))
        v7 = video("video-7", [base - timedelta(days=1)] * 5)
        b = lambda d, want, now=base: images.budget(d, tmp / "videos", want, now, tmp / "gw")   # noqa: E731
        check("1本: 5回作った動画は、あと1回なら作れる", b(v7, 1)[0] is True, b(v7, 1)[1])
        check("1本: 5回作った動画で2回作ろうとすると止まる（6回を超える）", b(v7, 2)[0] is False and "1本の上限" in "".join(b(v7, 2)[1]), b(v7, 2)[1])
        video("video-8", legacy={"stage": "images", "at": (base - timedelta(days=2)).isoformat(), "generated": ["a", "b", "c", "d", "e", "f"],
                                 "stage_seconds": 300})
        video("video-9", [base - timedelta(days=6)])
        res = b(v7, 1)
        check("7日: 動画7の5回＋動画8の6回（この仕組みの前の記録の数え方）＋動画9の1回＝12回に1回足すと止まる",
              res[0] is False and "直近7日の動画の写真の上限" in "".join(res[1]) and "12+1/12" in res[1][0], res[1])
        res = b(v7, 1, base + timedelta(days=1, hours=1))
        check("7日: 基準日を1日あとに差し替えると、動画9の1回が7日の外に出て作れる（11+1）", res[0] is True and "11+1/12" in res[1][0], res[1])
        gw(base - timedelta(hours=3))
        res = b(v7, 1, base + timedelta(days=1, hours=1))
        check("日次: 5時間より前の日次の画像生成は数えない（基準日の差し替えで28時間前）", res[0] is True, res[1])
        res = b(v7, 1)
        check("日次: 3時間前に日次の画像生成があれば止まる", res[0] is False and "5時間たっていない" in "".join(res[1]), res[1])
        gw(base - timedelta(days=1) + timedelta(seconds=40))
        res = b(v7, 0, base - timedelta(days=1) + timedelta(hours=1))
        check("日次: 動画の写真の記録の時刻の直後の gateway のログは、動画の生成として日次に数えない", "日次の画像生成 0回" in res[1][0], res[1])
        calls = []
        saved = images.subprocess.run
        images.subprocess.run = lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(AssertionError("gateway を呼んだ"))
        try:
            saved_logs = images.GATEWAY_LOGS
            images.GATEWAY_LOGS = tmp / "gw"
            before = (v7 / "video-7.build.json").read_text(encoding="utf-8")
            res, out = quiet(images.generate, v7, ["n1", "n2"], "p", v7 / "video-7.build.json", tmp / "videos", base)
        finally:
            images.subprocess.run, images.GATEWAY_LOGS = saved, saved_logs
        check("images の段: 上限を超えるなら1枚も作らずに止まる（gateway を呼ばない・記録も足さない）",
              "画像生成の上限で止めた" in str(res) and not calls and (v7 / "video-7.build.json").read_text(encoding="utf-8") == before, (res, out))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_external():
    """外部送信の遮断（D-0308）: HyperFrames へ渡す env から外部の解析の鍵を外し、snapshot は --describe false も付ける。"""
    from video import render, runtime
    saved = {k: os.environ.get(k) for k in runtime.HF_EXTERNAL_ENV}
    try:
        os.environ.update({k: "dummy" for k in runtime.HF_EXTERNAL_ENV})
        rt = runtime.Runtime()
        env = rt.env("hyperframes")
        check("外部送信: os.environ に鍵があっても env('hyperframes') には残らない（GEMINI_API_KEY ほか）",
              not any(k in env for k in runtime.HF_EXTERNAL_ENV) and env.get("HYPERFRAMES_NO_TELEMETRY") == "1")
        seen = []
        saved_run = render.subprocess.run
        render.subprocess.run = lambda args, **k: seen.append((args, k["env"])) or argparse_ns(returncode=0, stdout="", stderr="")
        try:
            render.snapshot(Path("comp"), rt, "1,2", Path("out"))
        finally:
            render.subprocess.run = saved_run
        args, senv = seen[0]
        check("外部送信: snapshot は --describe false・--no-end を付け、鍵を外した env で呼ぶ",
              args[2] == "snapshot" and args[args.index("--describe") + 1] == "false" and "--no-end" in args
              and not any(k in senv for k in runtime.HF_EXTERNAL_ENV), args)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def argparse_ns(**k):
    import argparse
    return argparse.Namespace(**k)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    test_fingerprint_and_test_mode()
    test_scene_count_and_new_parts()
    test_image_budget()
    test_external()
    test_parts()
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
