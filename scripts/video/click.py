"""クリップ音の検出（試作の click_check.py を移したもの。計算は同じ）。完成 mp4 の音を、文のつなぎ目と最後の1秒で調べる。
  ① 短い突発音: 声の大きい所（5ms RMS の 99 パーセンタイル＝ref）から -30dB を越える音の塊（40ms 以上の谷で区切る）のうち、
     0.10秒以下・前に 40ms 以上の谷・大きさが ref から -12dB 以内・有声でない（80〜400Hz の自己相関 < 0.4）
  ② 不連続な飛び: take のつなぎ目（時刻表の各文の頭と終わり）の ±3ms で、隣のサンプルとの差が無音の側・take の側より大きく跳ねる所
"""
import subprocess

import numpy as np

SR = 48000


def audio(rt, mp4):
    raw = subprocess.run([rt.ffmpeg, "-v", "error", "-i", str(mp4), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).astype(np.float64)


def periodicity(x):
    x = x - x.mean()
    if len(x) < int(0.02 * SR) or not np.any(x):
        return 0.0
    ac = np.correlate(x, x, "full")[len(x) - 1:]
    lo, hi = int(SR / 400), min(len(ac) - 1, int(SR / 80))
    return float(max(0.0, ac[lo:hi].max() / ac[0])) if hi > lo else 0.0


def regions(tl, dur):
    S = tl["sentences"]
    out = []
    for i, s in enumerate(S[:-1]):
        out.append((f"{s['id']}→{S[i + 1]['id']}", max(0, s["end"] - 0.3), S[i + 1]["start"] + 0.15))
    out.append(("最後の1秒", max(0, S[-1]["end"] - 1.0), dur))
    return out


def detect(x, tl):
    dur = len(x) / SR
    w = int(0.005 * SR)
    k = len(x) // w
    env = 20 * np.log10(np.sqrt(np.mean(x[:k * w].reshape(k, w) ** 2, axis=1)) + 1e-9)
    ref = float(np.percentile(env, 99))
    d = np.abs(np.diff(x))
    found = []
    # 音の塊（40ms＝8コマ以上の谷で区切る）はファイル全体で作る（調べる区間の端で切れた塊を短い音と見誤らない）
    on = env > ref - 30
    segs, i = [], 0
    while i < len(on):
        if on[i]:
            j, quiet, e = i, 0, i
            while j < len(on) and quiet < 8:
                if on[j]:
                    quiet, e = 0, j
                else:
                    quiet += 1
                j += 1
            segs.append((i, e + 1))
            i = e + 1
        else:
            i += 1
    for name, t0, t1 in regions(tl, dur):
        a, b = int(t0 / 0.005), min(k, int(t1 / 0.005))
        for s0, s1 in segs:
            if not (a < s0 < b):
                continue  # 塊の頭が区間の中にあるものだけ
            ln = (s1 - s0) * 0.005
            pk = float(env[s0:s1].max())
            if ln <= 0.10 and pk >= ref - 12:
                per = periodicity(x[s0 * w:s1 * w])
                if per < 0.4:
                    found.append({"kind": "短い突発音", "region": name, "t": round(s0 * 0.005, 3), "len_s": round(ln, 3),
                                  "peak_dbfs": round(pk, 1), "ref_dbfs": round(ref, 1), "periodicity": round(per, 2)})
    # 不連続な飛び（take のつなぎ目）
    for s in tl["sentences"]:
        for side, t in (("頭", s["start"]), ("終わり", s["end"])):
            c = int(t * SR)
            win = d[max(0, c - 144):min(len(d), c + 144)]
            if not len(win):
                continue
            quiet = d[max(0, c - 144 - 960):max(0, c - 144)] if side == "頭" else d[c + 144:c + 144 + 960]
            voice = d[c + 144:c + 144 + 960] if side == "頭" else d[max(0, c - 144 - 960):max(0, c - 144)]
            qm = float(np.median(quiet)) if len(quiet) else 0.0
            vp = float(np.percentile(voice, 95)) if len(voice) else 0.0
            j = float(win.max())
            # 無音の側から見て大きく、かつ take の側の差（95 パーセンタイル）の 2倍も越える段差だけ
            if j > 0.02 and j > 12 * max(qm, 1e-4) and j > 2 * vp:
                found.append({"kind": "不連続な飛び", "region": f"{s['id']}の{side}", "t": round((max(0, c - 144) + int(np.argmax(win))) / SR, 4),
                              "jump": round(j, 3), "quiet_side_median": round(qm, 5), "take_side_p95": round(vp, 4)})
    return {"regions": [{"name": n, "t0": round(a, 3), "t1": round(b, 3)} for n, a, b in regions(tl, dur)],
            "ref_dbfs": round(ref, 1), "found": found, "count": len(found)}
