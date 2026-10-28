"""声の段: 台本（script.json）→ ジョブ表 → Irodori-TTS（実行環境の voice_master.py）→ take の選択・末尾の処理・つなぎ・正規化 → 読み違いの目安。
試作の make_voice_jobs.py・build_voice.py・asr_check.py を移したもの。計算は変えていない。変えたのは次の3点だけ。
  - パス: 参照 WAV・ffmpeg・TTS は data/video-runtime.json から、読みの例外表は data/video-lexicon.json（＋video-N.film.json の lexicon）から引く
  - cut_tail の守り: モーラ数 ÷ MIN_MORA_PER_S 秒を「残してよい最短の長さ」とし、削ったあとがこれを下回る1回は取り消して止める
  - takes.tsv の印: 削った塊の大きさ（ピーク比 dB）の最大を tail_cut_max_db に、LOUD_CUT_DB を超えたら tail_loud=1（耳で聞く対象。自動では判断しない）
出力（動画フォルダの下）: voice/jobs/voice.json・voice/reading.tsv・voice/raw/・voice/takes.tsv・voice/selected/・
  work/narration-pre.wav・work/narration.wav・work/timeline.json・voice/asr-selected.tsv
"""
import difflib
import itertools
import json
import re
import subprocess
import wave
from pathlib import Path

import numpy as np

from video.lexicon import applied, merged_lexicon, voice_text

SR = 48000
HEAD, TAIL = 0.5, 3.45   # TAIL: 最後の文の終わりからの尺。エンドカードの AI表示が α≥0.9 で 2.5秒以上見えるように（2.6 から延ばした）
MASTER_F0 = 224.0
SMALL = set("ゃゅょぁぃぅぇぉャュョァィゥェォ")
MIN_MORA_PER_S = 9.0   # cut_tail の守り（これより速い読みになる長さまでは削らない）
LOUD_CUT_DB = -12.0    # 削った塊がこれを超えたら印（語の可能性）
# cut_tail の①の線（2026-10-28 (b)・Sho が聞いて選択: 線B）。①は「−9dB 以下の塊」だけ削る。
# 雑音の塊は −10.5〜−17.8dB、語の塊は −7.7dB より大きい（reports/2026-10-28-6.md）。(a) の線は max_db None（大きさを見ない）だった
LINE_A = {"r1_len": 0.45, "r1_drops": None, "r1_max_db": -9.0}
SEED = 11
ASR_PS1 = Path(__file__).resolve().parent / "asr_win.ps1"


# ---- ジョブ表（make_voice_jobs.py）

def make_jobs(d, rt, seeds=(SEED,), only=None):
    """voice/jobs/voice.json と voice/reading.tsv を書く。only（文の id の集まり）を渡すと、その文だけのジョブ表にする。
    返り値: (ジョブ表のパス, ジョブ数, reading の行)"""
    sc = json.loads((d / "script.json").read_text(encoding="utf-8"))
    lex = merged_lexicon(d)
    jobs, rows = [], ["id\tscreen\tvoice\texceptions"]
    for s in sc["sentences"]:
        v = voice_text(s, lex)
        rows.append(f"{s['id']}\t{''.join(s['phrases'])}\t{v}\t{applied(s, lex)}")
        if only is not None and s["id"] not in only:
            continue
        for seed in seeds:
            jobs.append({"id": f"T_s{seed}_{s['id']}", "set": "T", "sentence": s["id"], "text": v,
                         "caption": None, "seed": seed, "ref": "master", "duration_scale": 0.88,
                         "cfg_scale_speaker": 5.0, "cfg_scale_caption": 3.0})
    spec = {"name": "voice", "checkpoint": "Aratako/Irodori-TTS-v4.1-Small", "num_steps": 40,
            "master": rt.asset("ref_wav"), "master_sha256": rt.asset_sha256("ref_wav"), "jobs": jobs}
    out = d / "voice" / "jobs" / "voice.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "voice" / "reading.tsv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return out, len(jobs), rows


def run_tts(d, rt, jobs_path):
    """実行環境の voice_master.py でジョブ表の声を作る（voice/raw/<id>.wav）。"""
    r = subprocess.run([rt.tts_python, "-I", rt.tts_runner, rt.tts_repo, str(jobs_path), str(d / "voice")],
                       env=rt.env("tts"), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit("声の生成に失敗: " + (r.stdout + r.stderr)[-1500:])
    return r.stdout


# ---- take の選択・末尾の処理（build_voice.py）

def mora(text):
    n = 0
    for ch in text:
        if ch in "、。・，． ":
            continue
        if ch in SMALL:
            continue
        if re.match(r"[぀-ヿ]", ch):
            n += 1
        elif re.match(r"[0-9,]", ch):
            n += 1
        else:
            n += 2  # 漢字・記号はおよそ2モーラ
    return n


def load(p):
    with wave.open(str(p)) as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        sw = w.getsampwidth()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype={2: np.int16, 4: np.int32}[sw]).astype(np.float64)
        x /= {2: 32768.0, 4: 2147483648.0}[sw]
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if sr != SR:
        n = int(round(len(x) * SR / sr))
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)
    return x


def rms_db(x, win=0.02):
    n = int(SR * win)
    k = len(x) // n
    r = np.sqrt(np.mean(x[:k * n].reshape(k, n) ** 2, axis=1) + 1e-12)
    return 20 * np.log10(r), n


def trim(x):
    db, n = rms_db(x)
    peak = db.max()
    on = np.where(db > peak - 38)[0]
    # 頭は「-18dB を 0.1秒以上続けて越える」最初の位置の 0.08秒前（声の前の -20dB 前後の小さな音を頭に残さない）
    loud = db > peak - 18
    run = np.convolve(loud.astype(int), np.ones(5, int), "valid")
    first = int(np.argmax(run >= 5)) if (run >= 5).any() else on[0]
    # 促音の前の短い拍（「みっつ」の「み」）は 0.1秒続かないので、直前 0.2秒の中の -12dB を越える音まで頭を戻す
    while first > 0:
        w0 = max(0, first - 10)
        hit = np.where(db[w0:first] > peak - 12)[0]
        if not len(hit):
            break
        first = w0 + int(hit[0])
    a = max(0, first * n - int(0.08 * SR))
    b = min(len(x), (on[-1] + 1) * n + int(0.06 * SR))
    y = x[a:b].copy()
    k = int(0.01 * SR)  # 頭の 10ms のフェードイン（無音からのつなぎ目に段差を作らない）
    y[:k] *= np.linspace(0, 1, k)
    return y


def pauses(x, rel=-30.0, min_len=0.06):
    db, n = rms_db(x, 0.01)
    peak = db.max()
    low = db < peak + rel
    # 30ms 未満の小さな音（息・クリック）は谷の一部とみなす
    k = 0
    while k < len(low):
        if not low[k]:
            j = k
            while j < len(low) and not low[j]:
                j += 1
            if j - k < 3 and k > 0 and j < len(low):
                low[k:j] = True
            k = j
        else:
            k += 1
    out = []
    i = 0
    while i < len(low):
        if low[i]:
            j = i
            while j < len(low) and low[j]:
                j += 1
            if (j - i) * 0.01 >= min_len and i > 0 and j < len(low):
                out.append((i * 0.01, j * 0.01))
            i = j
        else:
            i += 1
    return out


def f0_median(x):
    fr = int(0.04 * SR)
    hop = int(0.02 * SR)
    vals = []
    for s in range(0, len(x) - fr, hop):
        seg = x[s:s + fr] * np.hanning(fr)
        if np.sqrt(np.mean(seg ** 2)) < 0.02:
            continue
        ac = np.correlate(seg, seg, "full")[fr - 1:]
        lo, hi = int(SR / 400), int(SR / 120)
        k = lo + int(np.argmax(ac[lo:hi]))
        if ac[k] > 0.35 * ac[0]:
            vals.append(SR / k)
    return float(np.median(vals)) if vals else float("nan")


def periodicity(x):
    """有声らしさ（80〜400Hz の自己相関の最大・0〜1）。突発音・息は低い。"""
    x = x - x.mean()
    if len(x) < int(0.02 * SR) or not np.any(x):
        return 0.0
    ac = np.correlate(x, x, "full")[len(x) - 1:]
    lo, hi = int(SR / 400), min(len(ac) - 1, int(SR / 80))
    return float(max(0.0, ac[lo:hi].max() / ac[0])) if hi > lo else 0.0


def cut_tail(y, min_len=None, line=None):
    """末尾の余計な音を落とす。4回まで。返り値: (切った波形, 切った秒, 回数, 印)
    最後の音の塊（-30dB を越える 10ms の続き。規則ごとの長さの谷で分ける）が次のどれかなら、その前の塊の終わり＋0.08秒で切る:
      ① 0.22秒以上の間の後ろの、R1_LEN 秒未満の音（v1 からの規則。既定 0.45秒）。line の r1_drops 回まで・r1_max_db 以下の塊だけ、にもできる
      ② 0.12秒以上の間の後ろの、-18dB に届かない 0.45秒未満の弱い音（息・雑音）
      ③ 0.05秒以上の間の後ろの、0.12秒未満の -12dB を越える有声でない短い突発音
    line: ①の線（dict）。r1_len（塊の長さの上限・秒）・r1_drops（①で削る回数の上限・None なら無制限）・
      r1_max_db（①は塊のピーク比 dB がこの値以下のときだけ・None なら条件なし）。省略は (a) の線（0.45秒・無制限・条件なし）。
    守り: min_len（秒）を渡すと、削ったあとの長さがそれを下回る1回は取り消して止める（語の間に間を置く読みで、
      ①が末尾から語を1つずつ食べるのを止める。2026-10-28-4 の 4-1）。
    印: {"guard": 守りで止めたら1, "max_db": 削った塊の大きさ（ピーク比 dB）の最大・削っていなければ None}
    最後に 40ms のフェードアウト（つなぎ目に段差を作らない）。"""
    ln_ = {**LINE_A, **(line or {})}
    n0 = len(y)
    drops = 0
    r1_used = 0
    flag = {"guard": 0, "max_db": None}
    for _ in range(4):
        db, n = rms_db(y, 0.01)
        peak = db.max()
        on = db > peak - 30
        act = np.where(on)[0]
        if len(act) < 2:
            break
        # ①②では 30ms 未満の音の粒は谷の一部とみなす（谷が 10ms の粒で分断されて規則が外れないように）
        sm = on.copy()
        k = 0
        while k < len(sm):
            if sm[k]:
                j = k
                while j < len(sm) and sm[j]:
                    j += 1
                if j - k < 3 and j < len(sm):
                    sm[k:j] = False
                k = j
            else:
                k += 1
        act_sm = np.where(sm)[0]
        cut = None
        r1_ok = ln_["r1_drops"] is None or r1_used < ln_["r1_drops"]
        for rule, (min_gap, act, test) in enumerate(((0.05, np.where(on)[0], lambda ln, mx, seg: ln < 0.12 and mx > -12 and periodicity(seg) < 0.4),
                                                     (0.12, act_sm, lambda ln, mx, seg: ln < 0.45 and mx < -18),
                                                     (0.22, act_sm, lambda ln, mx, seg: r1_ok and ln < ln_["r1_len"]
                                                      and (ln_["r1_max_db"] is None or mx <= ln_["r1_max_db"])))):
            if len(act) < 2:
                continue
            gaps = np.where(np.diff(act) * 0.01 >= min_gap)[0]
            if len(gaps) == 0:
                continue
            g = gaps[-1]
            a, b = act[g + 1], act[-1] + 1
            mx = db[a:b].max() - peak
            if test((b - a) * 0.01, mx, y[a * n:b * n]):
                cut = (min((act[g] + 1) * n + int(0.08 * SR), a * n), float(mx), rule)
                break
        if cut is None:
            # 最後の塊の後ろに残る -30dB 未満の小さな雑音は、塊の終わり＋0.08秒で切る
            end = (act_sm[-1] + 1) * n + int(0.08 * SR) if len(act_sm) else len(y)
            if end < len(y) - int(0.02 * SR):
                y = y[:end].copy()
            break
        if min_len is not None and cut[0] / SR < min_len:
            flag["guard"] = 1
            break
        y = y[:cut[0]].copy()
        drops += 1
        r1_used += cut[2] == 2
        flag["max_db"] = cut[1] if flag["max_db"] is None else max(flag["max_db"], cut[1])
    k = int(0.04 * SR)
    y[-k:] *= np.linspace(1, 0, k)
    return y, (n0 - len(y)) / SR, drops, flag


def clip_runs(x):
    a = np.abs(x) >= 0.999
    return int(np.sum(a[:-2] & a[1:-1] & a[2:]))


def write_wav(p, x, ch=1):
    y = np.clip(x, -1, 1)
    if ch == 2:
        y = np.repeat(y[:, None], 2, axis=1).ravel()
    with wave.open(str(p), "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((y * 32767).astype(np.int16).tobytes())


def phrase_times(x, phrases, voice_phr):
    """句の境目を -30dB の谷から選ぶ（谷の中央）。谷が足りなければモーラの割合の位置。"""
    d = len(x) / SR
    ms = [mora(p) for p in voice_phr]
    tot = sum(ms)
    expect = list(itertools.accumulate(ms))[:-1]
    expect = [e / tot * d for e in expect]
    cands = [((a + b) / 2, a, b) for a, b in pauses(x)]
    cuts = []
    used = set()
    for e in expect:
        best = None
        for k, (c, a, b) in enumerate(cands):
            if k in used:
                continue
            if cuts and c <= cuts[-1][0]:
                continue
            cost = abs(c - e)
            if best is None or cost < best[0]:
                best = (cost, k)
        if best is not None and best[0] < 0.6:
            used.add(best[1])
            c, a, b = cands[best[1]]
            cuts.append((c, a, b, "valley"))
        else:
            cuts.append((e, e, e, "mora"))
    bounds = []
    st = 0.0
    for c, a, b, how in cuts:
        bounds.append((st, a, how))
        st = b
    bounds.append((st, d, "end"))
    return [{"text": t, "start": round(s, 3), "end": round(e, 3), "cut": how} for t, (s, e, how) in zip(phrases, bounds)]


def voice_phrases(sent, lex):
    """声の入力を画面の句と同じ数に分ける（読点で）。"""
    parts = [p for p in re.split(r"(?<=[、。])", sent["voice"]) if p]
    n = len(sent["phrases"])
    if len(parts) != n:
        # 読み替えで読点が増えた句は、画面の句ごとに読み替えて数をそろえる
        per = [voice_text({"phrases": [p]}, lex) for p in sent["phrases"]]
        if "".join(per) == sent["voice"]:
            return per
    if len(parts) == n:
        return parts
    # 読点の数が違うとき: 画面の句のモーラの割合で寄せる
    out, buf = [], ""
    targets = [mora(p) for p in sent["phrases"]]
    k = 0
    for p in parts:
        buf += p
        if k < n - 1 and mora(buf) >= targets[k] * 0.8:
            out.append(buf)
            buf = ""
            k += 1
    out.append(buf)
    while len(out) < n:
        out.append("")
    return out[:n]


TAKE_COLS = ["id", "sentence", "seed", "raw_dur", "dur", "mora", "mora_per_s", "tail_cut_s", "tail_drops", "clip", "dur_outlier",
             "f0", "f0_diff_st", "pauses", "defect", "picked", "why", "tail_min_s", "tail_guard", "tail_cut_max_db", "tail_loud"]


def build(d, rt):
    """take を選び、末尾を処理し、つないで正規化する。返り値: timeline（dict）"""
    voice, work = d / "voice", d / "work"
    sc = json.loads((d / "script.json").read_text(encoding="utf-8"))
    lex = merged_lexicon(d)
    gap = sc.get("gap_after", {})
    want = sc.get("pick", {})
    for s in sc["sentences"]:
        s["voice"] = voice_text(s, lex)
    raw = voice / "raw"
    rows = []
    pick = {}
    for s in sc["sentences"]:
        cand = []
        seeds = sorted({int(f.stem.split("_")[1][1:]) for f in raw.glob(f"T_s*_{s['id']}.wav")})
        for seed in seeds:
            f = raw / f"T_s{seed}_{s['id']}.wav"
            x = load(f)
            y0 = trim(x)
            m = mora(s["voice"])
            min_len = m / MIN_MORA_PER_S
            y, cut, drops, flag = cut_tail(y0, min_len)
            dur = len(y) / SR
            row = {"id": f.stem, "sentence": s["id"], "seed": seed, "raw_dur": round(len(y0) / SR, 2), "dur": round(dur, 2), "mora": m,
                   "mora_per_s": round(m / dur, 2), "tail_cut_s": round(cut, 2), "tail_drops": drops,
                   "clip": clip_runs(x), "f0": round(f0_median(y), 1), "pauses": len(pauses(y)),
                   "tail_min_s": round(min_len, 2), "tail_guard": flag["guard"],
                   "tail_cut_max_db": "" if flag["max_db"] is None else round(flag["max_db"], 1),
                   "tail_loud": int(flag["max_db"] is not None and flag["max_db"] > LOUD_CUT_DB)}
            cand.append((row, y))
        if not cand:
            raise SystemExit(f"take が無い: voice/raw/T_s*_{s['id']}.wav")
        for r, _ in cand:
            r["dur_outlier"] = int(r["mora_per_s"] > 6.2 or r["mora_per_s"] < 3.4)
            r["f0_diff_st"] = round(12 * np.log2(r["f0"] / MASTER_F0), 2) if r["f0"] == r["f0"] else None
            r["defect"] = int(r["clip"] > 0 or r["dur_outlier"])
        ok = [c for c in cand if not c[0]["defect"]]
        first = [c for c in ok if c[0]["seed"] == want.get(s["id"], SEED)]
        if first:
            chosen = first[0]
            why = (f"シード {want[s['id']]}（台本の pick：読み違いの作り直し）・欠けなし" if s["id"] in want
                   else "シード 11（ブランドの記録と同じ）・欠けなし")
        elif ok:
            chosen = min(ok, key=lambda c: abs(c[0]["f0_diff_st"] or 9))
            why = "シード 11 に欠け（" + ",".join(k for k in ("clip", "dur_outlier") if [c for c in cand if c[0]["seed"] == SEED][0][0][k]) + "）→ 欠けの無い中でマスターの高さに近い take"
        else:
            chosen, why = cand[0], "全 take に欠け。シード 11（耳で確かめる）"
        for r, _ in cand:
            r["picked"] = int(r is chosen[0])
            r["why"] = why if r["picked"] else ""
            rows.append(r)
        pick[s["id"]] = chosen
    (voice / "takes.tsv").write_text("\t".join(TAKE_COLS) + "\n" + "\n".join("\t".join(str(r[c]) for c in TAKE_COLS) for r in rows) + "\n",
                                     encoding="utf-8")

    sel = voice / "selected"
    sel.mkdir(exist_ok=True)
    work.mkdir(exist_ok=True)
    t = HEAD
    pieces = [np.zeros(int(HEAD * SR))]
    tl = {"head": HEAD, "sr": SR, "sentences": []}
    for s in sc["sentences"]:
        r, y = pick[s["id"]]
        write_wav(sel / f"{s['id']}.wav", y)
        dur = len(y) / SR
        ph = phrase_times(y, s["phrases"], voice_phrases(s, lex))
        tl["sentences"].append({"id": s["id"], "scene": s["scene"], "take": r["id"], "start": round(t, 3), "end": round(t + dur, 3),
                                "phrases": [{**p, "start": round(t + p["start"], 3), "end": round(t + p["end"], 3)} for p in ph]})
        pieces.append(y)
        t += dur
        g = gap.get(s["id"], 0.0)
        if g:
            pieces.append(np.zeros(int(g * SR)))
            t += g
    pieces.append(np.zeros(int(TAIL * SR)))
    t += TAIL
    tl["duration"] = round(t, 3)
    x = np.concatenate(pieces)
    pre = work / "narration-pre.wav"
    write_wav(pre, x * 0.5, ch=2)
    # 音量: loudnorm の2回通し（線形）
    m = subprocess.run([rt.ffmpeg, "-hide_banner", "-i", str(pre), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    js = json.loads(m[m.rindex("{"):m.rindex("}") + 1])
    af = (f"loudnorm=I=-16:TP=-1.5:LRA=11:measured_I={js['input_i']}:measured_TP={js['input_tp']}:"
          f"measured_LRA={js['input_lra']}:measured_thresh={js['input_thresh']}:offset={js['target_offset']}:linear=true,aresample=48000")
    subprocess.run([rt.ffmpeg, "-y", "-loglevel", "error", "-i", str(pre), "-af", af, "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le",
                    str(work / "narration.wav")], check=True)
    (work / "timeline.json").write_text(json.dumps(tl, ensure_ascii=False, indent=1), encoding="utf-8")
    return tl, rows


# ---- 読み違いの目安（asr_check.py）

def similarity(want, got):
    """声の入力と asr の文字の近さ（0〜1・記号と空白を除いて比べる）。読み違いの点検の入口だけに使う（asr は精度が低く、合否には使わない）。"""
    norm = lambda t: re.sub(r"[、。・，． 　]", "", t or "")
    a, b = norm(want), norm(got)
    return round(difflib.SequenceMatcher(None, a, b).ratio(), 2) if a and b else 0.0


def asr(d, kind="selected"):
    """WAV の頭と末尾に 0.6秒の無音を足して work/asr/ に置き、Windows 標準の日本語の音声認識（手元だけ）で起こす。
    結果は voice/asr-<kind>.tsv（file・voice_input・asr・confidence・similarity）。similarity は点検の入口だけ（合否ではない）。耳の代わりではない。"""
    src = d / "voice" / kind
    dst = d / "work" / "asr" / kind
    dst.mkdir(parents=True, exist_ok=True)
    for f in sorted(src.glob("*.wav")):
        with wave.open(str(f)) as w:
            sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
            x = np.frombuffer(w.readframes(w.getnframes()), dtype={2: np.int16, 4: np.int32}[sw]).astype(np.float64)
            x /= {2: 32768.0, 4: 2147483648.0}[sw]
        if ch > 1:
            x = x.reshape(-1, ch).mean(axis=1)
        pad = np.zeros(int(0.6 * sr))
        y = np.concatenate([pad, x, pad])
        with wave.open(str(dst / f.name), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes())
    out = d / "work" / "asr" / f"asr-{kind}.tsv"
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ASR_PS1), str(dst), str(out)], check=True)
    sc = json.loads((d / "script.json").read_text(encoding="utf-8"))
    lex = merged_lexicon(d)
    want = {s["id"]: voice_text(s, lex) for s in sc["sentences"]}
    rows = ["file\tvoice_input\tasr\tconfidence\tsimilarity"]
    for line in out.read_text(encoding="utf-8").splitlines()[1:]:
        name, text, conf = (line.split("\t") + ["", ""])[:3]
        sid = Path(name).stem.split("_")[-1]
        rows.append(f"{name}\t{want.get(sid, '')}\t{text}\t{conf}\t{similarity(want.get(sid, ''), text)}")
    res = d / "voice" / f"asr-{kind}.tsv"
    res.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return res


def raw_missing(d):
    """声がまだ無い文の id（voice/raw/T_s11_<id>.wav が無いもの）"""
    sc = json.loads((d / "script.json").read_text(encoding="utf-8"))
    return [s["id"] for s in sc["sentences"] if not (d / "voice" / "raw" / f"T_s{SEED}_{s['id']}.wav").exists()]


