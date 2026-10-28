"""機械で測れる型の物差し（R7・点の端切れ）を、video-N.film.json のデータから計算する（mp4 は読まない。画の測定は qa.py）。
試作の check_pointing2.py の「カメラの値から画面の座標を出す」計算を、データ（cues・cover・photos）から組む形に移したもの（2026-10-28 (b)）。

カメラの動き: cues の tl.to / tl.set / 切り替え（fx）のうち、対象が4枚のカメラ（#t-aft・#b-mug・#b-col・#f-gift）の x・y・scale と、上下の境目（split）だけを
  GSAP と同じ順（開始の早い順・同じなら書いた順）に 1/30秒ごとに前へ進めて再現する。
  - 動いている間は毎コマ書く。終わったコマで終わりの値を1回だけ書き、そのあとは書かない（GSAP は終わった tween を描き直さない）
  - 最初に描くコマで、始めの値（from）を、その時の値から取る
画面の座標: 写真の点 (px, py) は、画面（1080×1920）の (x + scale·px, y + scale·py)。
字数（R7(b)）: 同じ時刻に見えている字（空白を除く）の合計。章の札（#p1〜#p3）は数えない。エンドカードは AI表示（credit）を数える。
主題（R7(c)）: video-N.film.json の qa_subjects（名前・カメラ・写真の中の主題の外接矩形・区間）の、画面での y の上端・下端が帯 BAND に入ること。
  band_worst は区間内で帯への余りが最も小さい値（負ならその px だけ帯の外）。qa の subject_overflow_0px は参考の行も含めてこれを見る。
主題の横（D-0311）: 同じ行の外接矩形の画面での x の左端・右端が SIDE（0〜1080）に入ること（subject_sides）。参考の行・全面の行も見る。
  行に WIDE（"wide"）の印があれば止めない。film の段・check-script（script_checks）と qa の subject_overflow_x_0px が同じ関数を使う。
"""
import math
import re
from html.parser import HTMLParser

FPS = 30
BAND = (168, 1330)
MAX_SCREEN_CHARS = 30
CAMS = ("#t-aft", "#b-mug", "#b-col", "#f-gift")
PROPS = ("x", "y", "scale")
SPLIT = "split"


# ---- 式の評価（cues の秒・値は JS の式。数・定数・四則だけ）

def letters(data):
    """区間の名前（sections の順。最後がエンドカード・film.section_letters と同じ）"""
    return list(data["sections"])


def constants(data):
    sec = data["sections"]
    c = {f"{k}0": float(sec[k]) for k in letters(data)}
    for k in letters(data):
        for cue in data["cues"][k]:
            if isinstance(cue, str):
                m = re.match(r"\s*const (\w+) = (.+);\s*$", cue)
                if m:
                    c[m.group(1)] = ev(m.group(2), c)
    return c


def ev(v, c):
    if isinstance(v, (int, float)):
        return float(v)
    return float(eval(v, {"__builtins__": {}}, dict(c)))


def ease(name, p):
    p = min(1.0, max(0.0, p))
    if name == "none" or name == "linear":
        return p
    m = re.match(r"^power([1-4])\.(in|out|inOut)$", name)
    if m:
        k, kind = int(m.group(1)) + 1, m.group(2)
        if kind == "in":
            return p ** k
        if kind == "out":
            return 1 - (1 - p) ** k
        return 0.5 * (2 * p) ** k if p < 0.5 else 1 - 0.5 * (2 * (1 - p)) ** k
    if name == "sine.inOut":
        return -(math.cos(math.pi * p) - 1) / 2
    if name == "sine.out":
        return math.sin(p * math.pi / 2)
    if name == "sine.in":
        return 1 - math.cos(p * math.pi / 2)
    if name == "expo.out":
        return 1.0 if p >= 1 else 1 - 2 ** (-10 * p)
    raise ValueError(f"ease が分からない: {name}")


# ---- カメラの動き

def sels(s):
    return s if isinstance(s, list) else [s]


def tweens(data):
    """カメラ・境目に当たる tween を書いた順に返す。[{sel, props:{名:目標}, start, dur, ease}]（set は dur 0）"""
    c = constants(data)
    out = []

    def add(sel, props, t, dur, e):
        props = {k: ev(v, c) for k, v in props.items() if k in PROPS}
        if props:
            out.append({"sel": sel, "props": props, "start": ev(t, c), "dur": ev(dur, c), "ease": e})

    def add_split(y, t, d, e):
        out.append({"sel": SPLIT, "props": {"y": ev(y, c)}, "start": ev(t, c), "dur": ev(d, c), "ease": e})

    for k in letters(data):
        for cue in data["cues"][k]:
            if isinstance(cue, str):
                continue
            if "fx" in cue:
                f, t = cue["fx"], cue["t"]
                if f == "dissolve":
                    add(f'#{cue["cam"].lstrip("#")}', cue["to"], t, cue["d"], "none")
                elif f == "wipe":
                    for part in (cue["top"], cue["bot"]):
                        add(part["cam"], part["from"], f"{ev(t, c) - 0.01}", 0, "none")
                    for part in (cue["top"], cue["bot"]):
                        add(part["cam"], part["to"], t, cue["d"], "none")
                elif f == "push_in":
                    add_split(0, t, 0.7, "power3.inOut")
                    add(cue["cam"], cue["to"], t, 0.75, "power3.inOut")
                    add(cue["other"], cue["other_to"], t, 0.7, "power3.inOut")
                elif f == "push_out":
                    add(cue["out"], {"x": cue["out_x"]}, t, 0.7, "power3.inOut")
                    add(cue["in"], {"x": cue["in_x"]}, t, 0.7, "power3.inOut")
                elif f == "merge":
                    add(cue["cam"], cue["from"], f"{ev(t, c) - 0.01}", 0, "none")
                    add(cue["cam"], cue["to"], t, cue["d"], "power2.out")
                continue
            if "split" in cue:
                add_split(cue["split"], cue["t"], cue["d"], cue["ease"])
                continue
            for kind in ("to", "set"):
                if kind in cue:
                    v = cue["v"]
                    for sel in sels(cue[kind]):
                        if sel in CAMS:
                            add(sel, v, cue["t"], 0 if kind == "set" else v.get("duration", 0.5), v.get("ease", "power1.out"))
    return out


def simulate(data, duration, fps=FPS):
    """1/30秒ごとのカメラの値。返り値: {(対象, 名): [値…]}（対象は #t-aft など・SPLIT）"""
    state = {}
    for cam in CAMS:
        init = data["cover"].get(cam, {})
        for p in PROPS:
            state[(cam, p)] = ev(init[p], {}) if p in init else (1.0 if p == "scale" else 0.0)
    state[(SPLIT, "y")] = 0.0
    tw = sorted(enumerate(tweens(data)), key=lambda it: (it[1]["start"], it[0]))
    tw = [t for _, t in tw]
    frm = [None] * len(tw)
    done = [False] * len(tw)
    n = int(round(duration * fps)) + 1
    traj = {k: [] for k in state}
    for i in range(n):
        t = i / fps
        for j, w in enumerate(tw):
            if done[j] or w["start"] > t + 1e-9:
                continue
            if frm[j] is None:
                frm[j] = {p: state[(w["sel"], p)] for p in w["props"]}
            end = w["start"] + w["dur"]
            if t >= end - 1e-9:
                for p, v in w["props"].items():
                    state[(w["sel"], p)] = v
                done[j] = True
            else:
                e = ease(w["ease"], (t - w["start"]) / w["dur"])
                for p, v in w["props"].items():
                    state[(w["sel"], p)] = frm[j][p] + (v - frm[j][p]) * e
        for k, v in state.items():
            traj[k].append(v)
    return traj


def cam_at(traj, cam, i):
    return traj[(cam, "x")][i], traj[(cam, "y")][i], traj[(cam, "scale")][i]


# ---- R7(c) 主題が帯の中

PANEL = {"#t-aft": "top", "#b-mug": "bottom", "#b-col": "bottom", "#f-gift": "full"}


def subjects(data, traj):
    """qa_subjects の各行の、区間内の最も悪い余白（px）。band_margin は帯の上端・下端までの余り（負なら帯の外）、
    panel_margin は主題がいる段の見える範囲（境目の内側）までの余り（負なら境目で切れている）"""
    c = constants(data)
    rows = []
    for row in data.get("qa_subjects", []):
        if len(row) < 5:
            continue   # _note の行
        name, cam, (x0, y0, x1, y1), t0, t1 = row[:5]
        ref = "ref" in row[5:]
        t0, t1 = ev(t0, c), ev(t1, c)
        worst = None
        band_worst = None   # 区間内で帯への余りが最も小さいコマ（はみ出しの量。worst は3つの余白の最小で選ぶので別に持つ）
        for i in range(int(round(t0 * FPS)), int(round(t1 * FPS)) + 1):
            x, y, s = cam_at(traj, cam, i)
            sp = traj[(SPLIT, "y")][i]
            top, bot = y + s * y0, y + s * y1
            band = min(top - BAND[0], BAND[1] - bot)
            side = PANEL[cam]
            panel = (952 + sp - bot) if side == "top" else (top - (968 + sp)) if side == "bottom" else 1e9
            # 写真が段を覆っているか（横は左右の端・縦は上の段の下端。下の段の下は幕で隠すので見ない）。覆えていないと暗い帯が出る
            cover = min(-x, x + s * 1440 - 1080)
            if side == "top":
                cover = min(cover, -y, y + s * 2160 - (952 + sp))
            cur = (min(band, panel, cover), band, panel, i / FPS, top, bot, cover)
            if worst is None or cur[0] < worst[0]:
                worst = cur
            if band_worst is None or band < band_worst[0]:
                band_worst = (band, i / FPS)
        rows.append({"name": name, "cam": cam, "window": [round(t0, 2), round(t1, 2)], "band_margin": round(worst[1], 1),
                     "panel_margin": round(worst[2], 1) if worst[2] < 1e8 else None, "cover_margin": round(worst[6], 1), "worst_at": round(worst[3], 3),
                     "screen_y": [round(worst[4]), round(worst[5])], "ok": worst[0] >= 0, "gate": not ref,
                     "band_worst": round(band_worst[0], 1), "band_worst_at": round(band_worst[1], 3)})
    return rows


SIDE = (0, 1080)       # R7(c) 横: 主題の外接矩形が収まる画面の横（px）。線の正本はここ（rules/video-production.md には場所だけ）
SIDE_OVERFLOW_PX = 0   # 横に出てよい量（px）
SIDE_FROM = 3          # 横の切れを止める（NG・gate）最初の動画の番号。動画1・2は INFO だけ（D-0311）
WIDE = "wide"          # qa_subjects の行の印。意図して主役を画面より大きく写す場面が「横に切れてよい」と宣言する（部品の wide・拍の subject.wide）


def subject_sides(data, traj):
    """qa_subjects の全行（参考の行も）の、区間内で主題の外接矩形が画面の横（SIDE）から出る最大の量。
    overflow_px は出た量（収まっていれば 0）、margin_px は収まっているときの余り（負なら出た量）、screen_x はそのコマの左端・右端、
    wide は行に WIDE の印があるか（印のある行は gate に入れない）、ok は収まっている・または wide"""
    c = constants(data)
    rows = []
    for row in data.get("qa_subjects", []):
        if len(row) < 5:
            continue   # _note の行
        name, cam, (x0, y0, x1, y1), t0, t1 = row[:5]
        t0, t1 = ev(t0, c), ev(t1, c)
        worst = None
        for i in range(int(round(t0 * FPS)), int(round(t1 * FPS)) + 1):
            x, y, s = cam_at(traj, cam, i)
            left, right = x + s * x0, x + s * x1
            margin = min(left - SIDE[0], SIDE[1] - right)
            if worst is None or margin < worst[0]:
                worst = (margin, i / FPS, left, right)
        wide = WIDE in row[5:]
        rows.append({"name": name, "cam": cam, "window": [round(t0, 2), round(t1, 2)], "margin_px": round(worst[0], 1),
                     "overflow_px": round(max(0.0, -worst[0]), 1), "at": round(worst[1], 3),
                     "screen_x": [round(worst[2]), round(worst[3])], "wide": wide, "ok": wide or -worst[0] <= SIDE_OVERFLOW_PX + 1e-6})   # 1e-6 は浮動小数の誤差（矩形の端が写真の端と同じ位置のとき）
    return rows


def side_failures(rows):
    """subject_sides の行のうち、横に出ていて宣言（wide）が無いもの。止める文の一覧"""
    return [f"主役「{r['name']}」（{r['cam']}・{r['window'][0]}〜{r['window'][1]}秒）が画面の横から {r['overflow_px']}px 出る"
            f"（{r['at']}秒・画面の x {r['screen_x'][0]}〜{r['screen_x'][1]}・収める範囲 {SIDE[0]}〜{SIDE[1]}・出てよい量 {SIDE_OVERFLOW_PX}px）。"
            f"カメラの x・scale を直す。意図して画面より大きく写す場面は、部品か拍の subject に wide を宣言する"
            for r in rows if not r["ok"]]


def sides_of(data, duration=None):
    """film.json のデータだけから横の行を出す（mp4・時刻表は読まない）。duration が無ければ最後の区間の始まり＋5秒"""
    return subject_sides(data, simulate(data, duration or float(data["sections"][letters(data)[-1]]) + 5))


PHOTO_W, PHOTO_H = 1440, 2160
RATIO_9_16_H = round(PHOTO_W * 16 / 9)   # 9:16 の写真を幅 1440 に合わせたときの高さ（2560）


def full_windows(data, traj):
    """全面の写真（#f-gift）の qa_subjects の各行について、はみ出し 0px で収まる主役の範囲。カメラの動きが区間内で動くので、
    区間の全コマで「上端 ≥ 帯の上端・下端 ≤ 帯の下端」になる写真の y（px）の範囲 [lo, hi] を出す（主役がこの中なら全コマではみ出さない）。
    比率ごとの「写真の上端からの %」:
      p23     2:3 の写真（1440×2160）。lo/2160〜hi/2160
      p916    9:16 の写真をそのまま使う場合（幅 1440・高さ 2560・上端を写真の座標 0 に置く）。lo/2560〜hi/2560
      p916_src 9:16 の写真を今の images の段（中央を 2:3 に切る）で使う場合の、元の写真の上端からの %。上下に切り捨てる分だけずれる
    幅（hi−lo の px）は比率によらず同じ（カメラと帯が決める）。主役の今の位置（subject_*）と、帯に収めるのに足りない px（shift_up_px）も付ける。"""
    c = constants(data)
    out = []
    for row in data.get("qa_subjects", []):
        if len(row) < 5:
            continue
        name, cam, (x0, y0, x1, y1), t0, t1 = row[:5]
        if PANEL.get(cam) != "full":
            continue
        t0, t1 = ev(t0, c), ev(t1, c)
        lo, hi = -1e9, 1e9
        for i in range(int(round(t0 * FPS)), int(round(t1 * FPS)) + 1):
            x, y, s = cam_at(traj, cam, i)
            lo, hi = max(lo, (BAND[0] - y) / s), min(hi, (BAND[1] - y) / s)
        lo, hi = max(lo, 0.0), min(hi, float(PHOTO_H))
        cut = RATIO_9_16_H - PHOTO_H            # 9:16 を 2:3 に切るとき、上下で捨てる px の合計（400）
        pct = lambda v, h: round(v / h * 100, 1)
        out.append({"name": name, "cam": cam, "window": [round(t0, 2), round(t1, 2)],
                    "lo_px": round(lo, 1), "hi_px": round(hi, 1), "width_px": round(hi - lo, 1),
                    "p23": [pct(lo, PHOTO_H), pct(hi, PHOTO_H)],
                    "p916": [pct(lo, RATIO_9_16_H), pct(hi, RATIO_9_16_H)],
                    "p916_src": [pct(lo + cut / 2, RATIO_9_16_H), pct(hi + cut / 2, RATIO_9_16_H)],
                    "subject_px": [y0, y1], "subject_p23": [pct(y0, PHOTO_H), pct(y1, PHOTO_H)],
                    "subject_p916_src": [pct(y0 + cut / 2, RATIO_9_16_H), pct(y1 + cut / 2, RATIO_9_16_H)],
                    "fits": hi - lo >= y1 - y0,
                    "shift_up_px": round(max(0.0, y1 - hi), 1), "shift_down_px": round(max(0.0, lo - y0), 1)})
    return out


def full_window_lines(rows):
    """full_windows の行を、作り直しの依頼文にそのまま貼れる形の文にする。"""
    lines = []
    for r in rows:
        fit = "" if r["fits"] else f"（主役の高さ {r['subject_px'][1] - r['subject_px'][0]}px が範囲の幅より大きい。主役を小さくする）"
        move = (f"・今は {r['shift_up_px']}px（2:3 で {round(r['shift_up_px'] / PHOTO_H * 100, 1)}%）上へ寄せる必要" if r["shift_up_px"] > 0
                else f"・今は {r['shift_down_px']}px 下へ寄せる必要" if r["shift_down_px"] > 0 else "・今は範囲の中")
        lines.append(f"{r['name']}（{r['window'][0]}〜{r['window'][1]}秒）: 主役の上端〜下端を写真の上端から "
                     f"2:3 なら {r['p23'][0]}〜{r['p23'][1]}%／9:16 をそのまま（幅1440・高さ{RATIO_9_16_H}）なら {r['p916'][0]}〜{r['p916'][1]}%"
                     f"／9:16 を中央で 2:3 に切る今の段なら元の写真の {r['p916_src'][0]}〜{r['p916_src'][1]}% の中に収める"
                     f"（幅 {r['width_px']}px）{move}{fit}")
    return lines


# ---- 見出しの字体に字がそろっているか（Zen Maru Gothic は 7,812字。足りない字は別の字体で出てしまう）

def cmap_chars(path):
    """TrueType の cmap（format 4・12）にある文字コードの集まり。"""
    import struct
    b = open(path, "rb").read()
    n = struct.unpack(">H", b[4:6])[0]
    off = next(struct.unpack(">I", b[12 + 16 * i + 8:12 + 16 * i + 12])[0] for i in range(n) if b[12 + 16 * i:16 + 16 * i] == b"cmap")
    chars = set()
    for i in range(struct.unpack(">H", b[off + 2:off + 4])[0]):
        st = off + struct.unpack(">I", b[off + 8 + 8 * i:off + 12 + 8 * i])[0]
        fmt = struct.unpack(">H", b[st:st + 2])[0]
        if fmt == 12:
            for g in range(struct.unpack(">I", b[st + 12:st + 16])[0]):
                s, e, _ = struct.unpack(">III", b[st + 16 + 12 * g:st + 28 + 12 * g])
                chars.update(range(s, e + 1))
        elif fmt == 4:
            x2 = struct.unpack(">H", b[st + 6:st + 8])[0]
            ends = struct.unpack(f">{x2 // 2}H", b[st + 14:st + 14 + x2])
            starts = struct.unpack(f">{x2 // 2}H", b[st + 16 + x2:st + 16 + 2 * x2])
            for s, e in zip(starts, ends):
                if s != 0xFFFF:
                    chars.update(range(s, e + 1))
    return chars


def head_text(data):
    """見出しの字体（--head）で出る字: 問い・答え・手入れの見出し・「か」・「？」"""
    t = overlay_texts(data, "")
    return "".join(data["q"]) + data["ans_s"] + "".join("".join(x) for x in data["ans_b"]) + t.get("care-hd1", "") + t.get("care-hd2", "") + t.get("ka", "") + "？"


# ---- 点（指し方の点と線）の画面の位置と端切れ

def point_geometry(data, traj, name, cam, t):
    """点（lead の circle）の、時刻 t の画面の中心と半径（px）と、見える範囲の端までの余白（px）。
    radius は縁取りの外縁、fill_radius は明るい中の外縁、core は lead の r（中の測り方の基準）を画面の px にしたもの。"""
    from video import film
    lead = next(e for e in data["photos"][cam.lstrip("#")]["extras"] if isinstance(e, dict) and e.get("lead") == name)
    i = int(round(t * FPS))
    x, y, s = cam_at(traj, cam, i)
    sp = traj[(SPLIT, "y")][i]
    (x1, y1), (x2, y2), r = lead["from"], lead["to"], lead["r"]
    cx, cy, rr = x + s * x2, y + s * y2, r * s * (film.DOT_FILL + film.DOT_RING)  # 中の外に縁取りの太さを足した外縁
    lx, ly = x + s * x1, y + s * y1
    side = PANEL[cam]
    top = 0 if side != "bottom" else 968 + sp
    bot = 1920 if side != "top" else 952 + sp
    edges = {"left": min(cx - rr, lx), "right": 1080 - max(cx + rr, lx), "top": min(cy - rr, ly) - top, "bottom": bot - max(cy + rr, ly)}
    return {"center": [round(cx, 1), round(cy, 1)], "radius": round(rr, 1), "fill_radius": round(r * s * film.DOT_FILL, 2), "core": round(r * s, 2),
            "margin": {k: round(v, 1) for k, v in edges.items()}, "clipped": min(edges.values()) < 0}


# ---- R7(b) 字数

class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack, self.texts = [], {}

    def handle_starttag(self, tag, attrs):
        self.stack.append((tag, dict(attrs).get("id")))

    def handle_endtag(self, tag):
        while self.stack and self.stack.pop()[0] != tag:
            pass

    def handle_data(self, data):
        t = re.sub(r"\s+", "", data)
        if not t:
            return
        for _, i in reversed(self.stack):
            if i:
                self.texts[i] = self.texts.get(i, "") + t
                return


def overlay_texts(data, credit):
    """id → 画面の字（空白を除く）。章の札は含めない。"""
    from video import film
    p = _Text()
    p.feed(film.overlay_html(data["overlays"]))
    texts = dict(p.texts)
    texts["kick"] = re.sub(r"\s+", "", data["kick"])
    texts["q"] = "".join(data["q"])
    texts["ans-s"] = data["ans_s"]
    texts["ans-b"] = "".join("".join(ln) for ln in data["ans_b"])
    texts["cta"] = re.sub(r"\s+", "", data["cta"])
    for e in data["photos"]["f-gift"]["extras"]:   # 指し方の札（svg の text）
        if isinstance(e, str):
            m = re.search(r'id="([\w-]+)".*?<text[^>]*>(.*?)</text>', e)
            if m:
                texts[m.group(1)] = m.group(2)
    return {k: v for k, v in texts.items() if v}


def first_id(sel):
    m = re.match(r"^#([\w-]+)", sel)
    return m.group(1) if m else None


def screens(data, duration, credit):
    """字が見えている区間と、同時に見えている字数の最大。返り値: (最大・その時刻・区間の一覧)"""
    c = constants(data)
    texts = overlay_texts(data, credit)
    hidden = {first_id(s) for grp in data["hidden"] for s in grp}
    events = []   # (秒, 順, 種類, id)
    n = 0
    for k in letters(data):
        for cue in data["cues"][k]:
            if isinstance(cue, str):
                continue
            kinds = []
            if "soft" in cue or "slide" in cue:
                kinds = [("in", cue.get("soft") or cue.get("slide"))]
            elif "out" in cue:
                kinds = [("out", cue["out"])]
            else:
                for key in ("to", "set", "fromTo"):
                    if key in cue and "v" in cue and "opacity" in cue["v"]:
                        kinds = [("in" if cue["v"]["opacity"] else "out", cue[key])]
            for kind, sel in kinds:
                for s in sels(sel):
                    i = first_id(s)
                    if i in texts:
                        events.append((ev(cue["t"], c), n, kind, i))
                        n += 1
    h0 = c[f"{letters(data)[-1]}0"]   # エンドカードの始まり
    visible = {i for i in texts if i not in hidden}
    start = {i: 0.0 for i in visible}
    spans = []
    for t, _, kind, i in sorted(events):
        if t >= h0:
            continue
        if kind == "in" and i not in start:
            start[i] = t
        elif kind == "out" and i in start:
            spans.append((start.pop(i), t, i))
    spans += [(t, h0, i) for i, t in start.items()]
    texts = {**texts, "credit": credit}
    spans.append((h0 + 0.2, duration, "credit"))
    points = sorted({0.0} | {a for a, _, _ in spans} | {b for _, b, _ in spans})
    best = (0, 0.0, [])
    rows = []
    for t in points:
        now = [i for a, b, i in spans if a - 1e-9 <= t < b - 1e-9]
        total = sum(len(texts[i]) for i in now)
        rows.append((round(t, 2), total, now))
        if total > best[0]:
            best = (total, round(t, 2), now)
    return best, rows, texts
