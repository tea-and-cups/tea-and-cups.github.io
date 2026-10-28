"""機械で測れる型の物差し（R7・点の端切れ）を、video-N.film.json のデータから計算する（mp4 は読まない。画の測定は qa.py）。
試作の check_pointing2.py の「カメラの値から画面の座標を出す」計算を、データ（cues・cover・photos）から組む形に移したもの（2026-10-28 (b)）。

カメラの動き: cues の tl.to / tl.set / 切り替え（fx）のうち、対象が4枚のカメラ（#t-aft・#b-mug・#b-col・#f-gift）の x・y・scale と、上下の境目（split）だけを
  GSAP と同じ順（開始の早い順・同じなら書いた順）に 1/30秒ごとに前へ進めて再現する。
  - 動いている間は毎コマ書く。終わったコマで終わりの値を1回だけ書き、そのあとは書かない（GSAP は終わった tween を描き直さない）
  - 最初に描くコマで、始めの値（from）を、その時の値から取る
画面の座標: 写真の点 (px, py) は、画面（1080×1920）の (x + scale·px, y + scale·py)。
字数（R7(b)）: 同じ時刻に見えている字（空白を除く）の合計。章の札（#p1〜#p3）は数えない。エンドカードは AI表示（credit）を数える。
主題（R7(c)）: video-N.film.json の qa_subjects（名前・カメラ・写真の中の主題の外接矩形・区間）の、画面での y の上端・下端が帯 BAND に入ること。
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

def constants(data):
    sec = data["sections"]
    c = {f"{k}0": float(sec[k]) for k in ("A", "B", "C", "D", "E", "F", "G", "H")}
    for k in ("A", "B", "C", "D", "E", "F", "G", "H"):
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

    for k in ("A", "B", "C", "D", "E", "F", "G", "H"):
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
        ref = len(row) > 5 and row[5] == "ref"
        t0, t1 = ev(t0, c), ev(t1, c)
        worst = None
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
        rows.append({"name": name, "cam": cam, "window": [round(t0, 2), round(t1, 2)], "band_margin": round(worst[1], 1),
                     "panel_margin": round(worst[2], 1) if worst[2] < 1e8 else None, "cover_margin": round(worst[6], 1), "worst_at": round(worst[3], 3),
                     "screen_y": [round(worst[4]), round(worst[5])], "ok": worst[0] >= 0, "gate": not ref})
    return rows


# ---- 見出しの字体に字がそろっているか（Zen Old Mincho は 7,815字。足りない字は別の字体で出てしまう）

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
    """点（lead の circle）の、時刻 t の画面の中心と半径（px）と、見える範囲の端までの余白（px）。"""
    lead = next(e for e in data["photos"][cam.lstrip("#")]["extras"] if isinstance(e, dict) and e.get("lead") == name)
    i = int(round(t * FPS))
    x, y, s = cam_at(traj, cam, i)
    sp = traj[(SPLIT, "y")][i]
    (x1, y1), (x2, y2), r = lead["from"], lead["to"], lead["r"]
    cx, cy, rr = x + s * x2, y + s * y2, r * s * 1.15  # 外縁の線の太さの分を 15% 足す
    lx, ly = x + s * x1, y + s * y1
    side = PANEL[cam]
    top = 0 if side != "bottom" else 968 + sp
    bot = 1920 if side != "top" else 952 + sp
    edges = {"left": min(cx - rr, lx), "right": 1080 - max(cx + rr, lx), "top": min(cy - rr, ly) - top, "bottom": bot - max(cy + rr, ly)}
    return {"center": [round(cx, 1), round(cy, 1)], "radius": round(rr, 1), "margin": {k: round(v, 1) for k, v in edges.items()},
            "clipped": min(edges.values()) < 0}


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
    for k in ("A", "B", "C", "D", "E", "F", "G", "H"):
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
    h0 = c["H0"]
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
