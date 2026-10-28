"""機械QAの段（qa）: 完成 mp4 を読むだけ。結果は <動画フォルダ>/video-N.qa.json（gate・mp4_sha256・各項目の測定値）と qa/ の下の静止画。
試作の qa_final.py（仕様・音量・音と字の同期・クリップ音・変化の速さ・一覧）・check_final_h2b.py（エンドカード）・r8b_peaks.py を1本にしたもの。

gate（すべて true で合格）は AI表示の5項目（2026-10-28-4 の 6節）:
  ai_credit_visible  表示時間: 最後の数秒の各コマで AI表示の不透明度 α を画素から出し（字の画素と周りの明るさの差 ÷ 最後のコマの同じ差）、
                     α≥0.9 が動画の終わりまで続く時間が VISIBLE_S 秒以上
  ai_credit_size     字の高さ: 最後のコマで明るさ>130 の字の画素の高さが GLYPH_PX 以上（CSS の 40px も照合）
  ai_credit_contrast コントラスト: 終わりの 0.05秒前のコマをスマホ幅 390px に縮め、字と、字の外縁から 10px の帯の WCAG のコントラスト比が CONTRAST 以上
  ai_credit_in_band  位置: 字の画素の外接が帯 BAND（y）・画面の横幅に収まり、ロゴの下にある
  ai_credit_text     文言: composition の #credit の文字列が型の定数（film.CREDIT）と一致
R8(b)（0.5秒差 >25 のまとまり）・点のコントラスト・字の同期のずれは測るだけで、合否の線はまだ決めていない（gate に入れない）。
"""
import json
import os
import re
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from video import click, film
from video.render import sha256

FPS = 30
BAND = (168, 1330)
VISIBLE_S = 2.5
GLYPH_PX = 38
CONTRAST = 4.5
CREDIT_CSS_PX = 40
CREDIT_TOP = film.LOGO_CY + film.LOGO_D // 2 + 28   # #credit の top（型の CSS と同じ）


def run(cmd, binary=False):
    return subprocess.run(cmd, capture_output=True, text=not binary, encoding=None if binary else "utf-8",
                          errors=None if binary else "replace")


def frames(rt, mp4, vf, w, h, ch, ss=None):
    cmd = [rt.ffmpeg, "-v", "error"] + (["-ss", str(ss)] if ss is not None else []) + ["-i", str(mp4), "-vf", vf,
                                                                                   "-pix_fmt", "rgb24" if ch == 3 else "gray", "-f", "rawvideo", "-"]
    a = np.frombuffer(run(cmd, binary=True).stdout, dtype=np.uint8)
    return a.reshape(-1, h, w, ch) if ch == 3 else a.reshape(-1, h, w)


def lum(a):
    a = a.astype(np.float64)
    return 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]


def rel_lum(y):
    c = y / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def cr(l1, l2):
    a, b = float(rel_lum(l1)), float(rel_lum(l2))
    return round((max(a, b) + 0.05) / (min(a, b) + 0.05), 2)


def endcard(rt, mp4, h0, comp_film):
    """AI表示の5項目とロゴ（check_final_h2b.py の 2〜5 と同じ計算。比べる mp4 は要らない）"""
    cx, cy, r = film.LOGO_CX, film.LOGO_CY, film.LOGO_D // 2
    t0 = round(h0 - 0.2, 3)
    fr = frames(rt, mp4, "null", 1080, 1920, 3, ss=t0)
    end_t = t0 + len(fr) / FPS
    yy, xx = np.mgrid[0:1920, 0:1080]
    rr = np.hypot(xx - cx, yy - cy)
    in_logo = rr < 0.8 * r
    bg_logo = (rr >= 360) & (rr <= 400) & (yy < 1230)
    last = lum(fr[-1])
    box = (slice(CREDIT_TOP - 12, CREDIT_TOP + 72), slice(60, 1020))
    gl = np.zeros((1920, 1080), bool)
    gl[box] = last[box] > 130
    rows = np.where(gl.any(axis=1))[0]
    cols = np.where(gl.any(axis=0))[0]
    near = np.asarray(Image.fromarray((gl * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(7))) > 0
    ring_c = np.zeros_like(gl)
    ring_c[box] = True
    ring_c &= ~near
    ref_logo = last[in_logo].mean() - last[bg_logo].mean()
    ref_c = last[gl].mean() - last[ring_c].mean()
    alpha = []
    for k, f in enumerate(fr):
        L = lum(f)
        alpha.append((round(t0 + k / FPS, 3), round(float((L[in_logo].mean() - L[bg_logo].mean()) / ref_logo), 3),
                      round(float((L[gl].mean() - L[ring_c].mean()) / ref_c), 3)))

    def first(th, col):
        for i in range(len(alpha)):
            if all(a[col] >= th for a in alpha[i:]):
                return alpha[i][0]
        return None

    vis = {}
    for th in (0.9, 0.99):
        tl_, tc_ = first(th, 1), first(th, 2)
        vis[f"alpha>={th}"] = {"logo_from": tl_, "credit_from": tc_,
                               "credit_seconds": None if tc_ is None else round(end_t - tc_, 3),
                               "logo_seconds": None if tl_ is None else round(end_t - tl_, 3)}

    # コントラスト（終わりの 0.05秒前のコマ・スマホ幅）
    kk = min(len(fr) - 1, int(round((end_t - 0.05 - t0) * FPS)))
    im = Image.fromarray(fr[kk])
    k = 390 / 1080
    ph = np.asarray(im.resize((390, round(1920 * k)), Image.LANCZOS))
    lp = lum(ph)
    mp = np.asarray(Image.fromarray((gl * 255).astype(np.uint8)).resize((390, round(1920 * k)), Image.BOX)).astype(np.float64) / 255
    g_p = mp >= 0.5
    o_p = mp > 0.02
    ring_p = (np.asarray(Image.fromarray((o_p * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(21))) > 0) & ~o_p
    ring_p[: int(1230 * k)] = False  # ロゴにかけない
    contrast = cr(lp[g_p].mean(), lp[ring_p].mean())

    # 位置
    a = fr[kk].astype(np.int32)
    logo_px = (lum(a) > 150) & (rr < r + 30) & (yy < CREDIT_TOP - 12)  # AI表示の字をロゴに数えない
    ly, lx = np.where(logo_px)
    in_band = bool(BAND[0] <= rows[0] and rows[-1] <= BAND[1] and cols[0] > 0 and cols[-1] < 1079 and rows[0] > ly.max())

    css = re.search(r"#credit \{[^}]*font:600 (\d+)px", comp_film)
    text = re.search(r'<div id="credit">(.*?)</div>', comp_film)
    glyph_h = int(rows[-1] - rows[0] + 1)
    secs = vis["alpha>=0.9"]["credit_seconds"]
    gate = {"ai_credit_visible": secs is not None and secs >= VISIBLE_S,
            "ai_credit_size": glyph_h >= GLYPH_PX and bool(css) and int(css.group(1)) == CREDIT_CSS_PX,
            "ai_credit_contrast": contrast >= CONTRAST,
            "ai_credit_in_band": in_band,
            "ai_credit_text": bool(text) and text.group(1) == film.CREDIT}
    measure = {
        "ai_credit_visible": {"seconds_alpha_0.9": secs, "need": VISIBLE_S, "end": round(end_t, 3), "detail": vis},
        "ai_credit_size": {"glyph_px": glyph_h, "need": GLYPH_PX, "css_px": int(css.group(1)) if css else None,
                           "rows": [int(rows[0]), int(rows[-1])], "cols": [int(cols[0]), int(cols[-1])]},
        "ai_credit_contrast": {"ratio_390px": contrast, "need": CONTRAST, "frame_at": round(t0 + kk / FPS, 3),
                               "glyph_lum": round(float(lp[g_p].mean()), 1), "ring_lum": round(float(lp[ring_p].mean()), 1)},
        "ai_credit_in_band": {"band": list(BAND), "credit_y": [int(rows[0]), int(rows[-1])], "credit_x": [int(cols[0]), int(cols[-1])],
                              "logo_y": [int(ly.min()), int(ly.max())], "logo_x": [int(lx.min()), int(lx.max())]},
        "ai_credit_text": {"want": film.CREDIT, "got": text.group(1) if text else None},
    }
    return gate, measure, alpha


def r8b(dd):
    """0.5秒差が 25 を超える所を、1秒以内のまとまりごとに最大値で並べる"""
    out = []
    for i in np.where(dd > 25)[0]:
        if out and i / 10 - out[-1][1] <= 1.0:
            if dd[i] > out[-1][2]:
                out[-1] = (out[-1][0], i / 10, float(dd[i]), i / 10)
            else:
                out[-1] = (out[-1][0], i / 10, out[-1][2], out[-1][3])
        else:
            out.append((i / 10, i / 10, float(dd[i]), i / 10))
    return [{"range": [round(a, 1), round(b, 1)], "max": round(m, 1), "at": round(t, 1)} for a, b, m, t in out]


def pcm(rt, path, sr=8000):
    raw = run([rt.ffmpeg, "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"], binary=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32)


def run_qa(d, rt, mp4, out_json):
    _, data = film.load_data(d)
    h0 = float(data["sections"]["H"])
    comp_film = (d / "composition" / "compositions" / "film.html").read_text(encoding="utf-8")
    qd = d / "qa"
    qd.mkdir(exist_ok=True)
    res = {"mp4": os.path.relpath(mp4, d), "mp4_sha256": sha256(mp4)}

    gate, measure, alpha = endcard(rt, mp4, h0, comp_film)
    res["gate"] = gate
    res["passed"] = all(gate.values())
    res["measure"] = measure

    # 仕様
    res["probe"] = json.loads(run([rt.ffprobe, "-v", "error", "-show_entries",
                                   "stream=codec_type,codec_name,width,height,r_frame_rate,nb_frames,sample_rate,channels,pix_fmt:format=duration,size",
                                   "-of", "json", str(mp4)]).stdout)
    # 音量・無音
    e = run([rt.ffmpeg, "-hide_banner", "-nostats", "-i", str(mp4), "-af", "ebur128=peak=true", "-f", "null", "-"]).stderr
    loud = {}
    for line in e[e.rfind("Summary:"):].splitlines():
        s = line.strip()
        if s.startswith("I:"):
            loud["integrated_lufs"] = float(s.split()[1])
        if s.startswith("Peak:"):
            loud["true_peak_dbtp"] = float(s.split()[1])
    sil = run([rt.ffmpeg, "-hide_banner", "-nostats", "-i", str(mp4), "-af", "silencedetect=noise=-50dB:d=0.2", "-f", "null", "-"]).stderr
    loud["silences"] = [(l.split("silence_")[1].split(":")[0], float(l.split(":")[1].split("|")[0]))
                        for l in sil.splitlines() if "silence_start" in l or "silence_end" in l]
    res["loudness"] = loud

    # 音の同期（元の narration.wav とのずれ）
    a, b = pcm(rt, mp4), pcm(rt, d / "work" / "narration.wav")
    n = min(len(a), len(b))
    best = max(range(-400, 401), key=lambda k: float(np.dot(a[max(0, k):n + min(0, k)], b[max(0, -k):n - max(0, k)])))
    res["audio_offset_ms"] = best / 8.0
    res["audio_len_s"] = [len(a) / 8000, len(b) / 8000]

    # 字の同期: 字の入りごとに、字の領域の変化が最大のコマと、予定の秒・声の句の頭との差
    cues = [tuple(c) for c in data.get("qa_text_sync", []) if len(c) == 4] + [
        ("logo（ロゴ・0.6秒で浮かぶ）", h0, None, (film.LOGO_CX - film.LOGO_D // 2, film.LOGO_CY - film.LOGO_D // 2,
                                                film.LOGO_CX + film.LOGO_D // 2, film.LOGO_CY + film.LOGO_D // 2)),
        ("credit（AI 表示・ロゴの下）", round(h0 + 0.2, 3), None, (100, CREDIT_TOP, 980, CREDIT_TOP + 48))]
    w, h = 270, 480
    fr = frames(rt, mp4, f"scale={w}:{h}", w, h, 1).astype(np.float32)
    sync = []
    for name, t, voice, (x0, y0, x1, y1) in cues:
        i0, i1 = int((t - 0.4) * FPS), int((t + 0.8) * FPS)
        reg = fr[i0 - 1:i1, y0 // 4:y1 // 4, x0 // 4:x1 // 4]
        dif = np.abs(np.diff(reg, axis=0)).mean(axis=(1, 2))
        pk = (i0 + int(np.argmax(dif))) / FPS
        sync.append({"cue": name, "planned": t, "visual_peak": round(pk, 3), "voice_start": voice,
                     "peak_minus_planned": round(pk - t, 3), "peak_minus_voice": None if voice is None else round(pk - voice, 3)})
    res["text_sync"] = sync

    # クリップ音
    tl = json.loads((d / "work" / "timeline.json").read_text(encoding="utf-8"))
    res["click"] = click.detect(click.audio(rt, mp4), tl)

    # 変化の速さ（R4・metrics.py と同じ）と R8(b)
    g = frames(rt, mp4, "fps=10,scale=54:96", 54, 96, 1).astype(np.float32)
    m = g.shape[0]
    dd = np.zeros(m)
    dd[5:] = np.abs(g[5:] - g[:-5]).mean(axis=(1, 2))
    met = {}
    for th in (12.0, 6.0):
        key_i, ks = 0, []
        for i in range(1, m):
            if np.abs(g[i] - g[key_i]).mean() >= th:
                if not ks or i / 10 - ks[-1] >= 1.0:
                    ks.append(i / 10)
                key_i = i
        gaps = np.diff([0.0] + [k for k in ks if k < h0] + [h0])
        met[f"looks_th{int(th)}"] = {"n": len(ks), "mean_interval": round(float(gaps.mean()), 2),
                                     "max_interval": round(float(gaps.max()), 2), "at": [round(k, 1) for k in ks]}
    met["moving_share"] = round(float((dd[5:] >= 2).mean()), 3)
    met["still_share"] = round(float((dd[5:] < 0.8).mean()), 3)
    met["2s_mean"] = [round(float(dd[i * 20:(i + 1) * 20].mean()), 1) for i in range(int(np.ceil(m / 20)))]
    met["top_0.5s_diff"] = sorted([(round(i / 10, 1), round(float(dd[i]), 1)) for i in range(m)], key=lambda x: -x[1])[:12]
    res["metrics"] = met
    res["r8b_over_25"] = r8b(dd)

    # 一覧（0.5秒ごと）と 0秒のコマ
    fdir = qd / "frames"
    fdir.mkdir(exist_ok=True)
    for f in fdir.glob("f*.png"):
        f.unlink()
    run([rt.ffmpeg, "-y", "-v", "error", "-i", str(mp4), "-vf", "select='not(mod(n\\,15))',scale=180:320", "-fps_mode", "vfr",
         str(fdir / "f%04d.png")])
    run([rt.ffmpeg, "-y", "-v", "error", "-i", str(mp4), "-frames:v", "1", str(qd / "frame-0s-cover.png")])
    files = sorted(fdir.glob("f*.png"))
    font = ImageFont.truetype(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "arial.ttf"), 18)
    cols = 12
    nrows = (len(files) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 184, nrows * 346), "white")
    for k, f in enumerate(files):
        im = Image.open(f).convert("RGB")
        x, y = (k % cols) * 184, (k // cols) * 346
        sheet.paste(im, (x + 2, y + 24))
        ImageDraw.Draw(sheet).text((x + 4, y + 2), f"{k * 0.5:.1f}s #{k:03d}", fill="black", font=font)
    sheet.save(qd / "contact-sheet-0.5s.jpg", quality=86)
    res["contact_sheet_frames"] = len(files)
    (qd / "endcard-alpha.json").write_text(json.dumps(alpha, ensure_ascii=False), encoding="utf-8")

    out_json.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res
