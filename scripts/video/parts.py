"""部品の段（film）: 1本ごとの動画の定義 video-N.parts.json（部品の並び・時刻は声の句の頭）と声の時刻表（work/timeline.json）から、
型のデータ video-N.film.json を作る（D-0307）。作った film.json は film.py が今までどおり型テンプレート（film-planA.html）へ差し込む。
動画 PARTS_FROM 以降が対象。動画1・2は案Aの作り（手で作った film.json）のまま。

部品（1つ＝1つの画面の割り方を一定の時間保つ場面。案Aのテンプレートの区間 A〜H に順に当たる）
  scene: "split"（上下の比べ）・"full"（全面の寄り）・"endcard"（エンドカード）。割り方・写真が見える矩形・所要の目安・指紋の語は SCENES。
  つなぎ（割り方が変わる所）は場面の中の fx の拍で受ける。前と次の割り方は FX（film.py の5種の切り替え）。
  name・note は区間の見出しの注釈。start は区間の始まり（最初の部品は 0 秒で書かない）。chapter は章の番号（字の注釈の見出しに使う）。
  texts は場面で使う字の要素（kind: text・follow・icon・headline・underline）。box（画面の矩形 x0,y0,x1,y1）があれば字の同期を測れる。
  beats は場面の中の拍（書いた順に cues になる）。拍の種類は BEATS の関数の説明。

時刻（at・dot・line・until・mark の値）: 秒は書かず、次のどれかで指す。オフセットは +0.08 のように足す。
  S4.p3        声の文 S4 の3つ目の句の頭（timeline.json の sentences[].phrases[].start）
  S7.end       声の文 S7 の終わり
  start・end   この部品の始まり・終わり（＝次の部品の始まり）
  DS など      この部品の mark の拍で決めた時刻（大文字2〜4字）

qa の3つの表は部品の宣言から作る（手で書かない）
  qa_subjects  拍の subject（主役の外接矩形）。区間は「その拍の動きが終わった時」から「同じカメラの次の構図の変化（カメラの寄り・引き、境目、切り替え）か部品の終わり」まで
  qa_points    point の拍。測る秒は点・線・光の範囲が出きった時
  qa_text_sync qa: true の拍（字の入り）。声の句の頭は、時刻を句で指したときのその句
"""
import json
import re
from decimal import Decimal
from pathlib import Path

from video import film

PARTS_FROM = 3
LETTERS = "ABCDEFGH"   # 案Aのテンプレートの区間（film-planA.html の cues_A〜cues_H）。部品はこの数だけ並べる
HIDDEN_PER_LINE = 10   # 最初に隠す字の一覧（hidden）を、部品ごとのまとまりで1行に詰める数（見た目の整形だけ）
PANEL_POS = {"#t-aft": "上", "#b-mug": "下", "#b-col": "下", "#f-gift": ""}

# 場面の部品。layout は割り方、visible は写真が見える画面の矩形（split は境目のずれ）、min・max は所要の目安（秒・判定はしない）、words は指紋の語（持たせるだけ）
SCENES = {
    "split": {"layout": "上下", "visible": {"#t-aft": "0,0,1080,952+split", "#b-mug": "0,968+split,1080,1920", "#b-col": "0,968+split,1080,1920"},
              "min": 5.0, "max": 10.0, "words": ("上下の比べ",)},
    "full": {"layout": "全面", "visible": {"#f-gift": "0,0,1080,1920"}, "min": 3.0, "max": 6.0, "words": ("全面の寄り",)},
    "endcard": {"layout": "全面", "visible": {"#f-gift": "0,0,1080,1920"}, "min": 2.5, "max": 3.5, "words": ("エンドカード",)},
}
# つなぎ（film.py の5種の切り替え）: 前の割り方 → 次の割り方・構図が落ち着くまでの秒（film.py の #full・#div・カメラの動きの長さ）・関わるカメラの項目・指紋の語
FX = {
    "dissolve": {"from": "split", "to": "full", "settle": "0.8", "cams": ("cam",), "words": ("溶かし",)},
    "wipe": {"from": "full", "to": "split", "settle": "0.7", "cams": ("top.cam", "bot.cam"), "words": ("払う",)},
    "push_in": {"from": "split", "to": "split", "settle": "0.75", "cams": ("cam", "other"), "words": ("押し込む",)},
    "push_out": {"from": "split", "to": "split", "settle": "0.7", "cams": ("out", "in"), "words": ("押し出し",)},
    "merge": {"from": "split", "to": "full", "settle": "0.8", "cams": ("cam",), "words": ("合わさる",)},
}
# 場面の中に重ねる部品（拍）。min・max は所要の目安（秒・判定はしない）、words は指紋の語
OVERLAYS = {
    "cover": {"min": 0.0, "max": 3.0, "words": ("カバーの問い",)},
    "point": {"min": 1.5, "max": 2.5, "words": ("点と札",)},
    "chapter": {"words": ("章の札",)},
    "cards": {"min": 2.0, "max": 4.0, "words": ("写真の小窓つきカード",)},
    "answer": {"min": 3.0, "max": 5.0, "words": ("答え・導線",)},
}
# 字の入り（show の how）。film-planA.html の soft・slide と、fromTo の形
ENTRANCES = {
    "fade": ({"opacity": 0}, {"opacity": 1, "duration": "IN", "ease": "power2.out"}),
    "pop": ({"opacity": 0, "scale": 1.08, "filter": "blur(16px)"}, {"opacity": 1, "scale": 1, "filter": "blur(0px)", "duration": 0.2, "stagger": None, "ease": "power3.out"}),
    "from_right": ({"opacity": 0, "x": 70}, {"opacity": 1, "x": 0, "duration": 0.2, "ease": "expo.out"}),
    "focus": ({"opacity": 0, "filter": "blur(8px)"}, {"opacity": 1, "filter": "blur(0px)", "duration": 0.2, "ease": "power4.out"}),
}
ICONS = {
    "bag": ('<svg width="88" height="72" viewBox="0 0 76 64"><rect x="10" y="22" width="56" height="38" rx="6" fill="none" stroke="#3a2a1f" stroke-width="4" />'
            '<path d="M26 22 V16 a12 12 0 0 1 24 0 V22" fill="none" stroke="#3a2a1f" stroke-width="3.5" /></svg>'),
    "mail": ('<svg width="88" height="72" viewBox="0 0 76 64"><rect x="6" y="12" width="64" height="42" rx="6" fill="none" stroke="#3a2a1f" stroke-width="4" />'
             '<path d="M9 17 L38 38 L67 17" fill="none" stroke="#3a2a1f" stroke-width="3.5" /></svg>'),
}
DOT_IN = Decimal("0.2")   # 点（circle）が出きる長さ（film.spot の circle の duration）
NOTE_TEXT_SYNC = "_note: 字の同期の測り方（qa が使う）。名前・字の入りの予定秒・対応する声の句の頭（無ければ null）・領域 x0,y0,x1,y1。エンドカードのロゴと AI表示は型から足す"
NOTE_SUBJECTS = ("_note: 主題が帯 168〜1330 の中か（qa が使う）。名前・カメラ・写真の中の主題の外接矩形 x0,y0,x1,y1・区間の始め・終わり（秒または式）・"
                 "[参考なら \"ref\"（gate に入れない）]。上の段は境目の上、下の段は境目の下にあること")
NOTE_POINTS = "_note: 点（指し方の円）の画面の位置・端切れ・コントラストを測る秒（qa が使う）。名前（photos の lead の名前）・カメラ・測る秒（点が出て円がそろったあと）"

REF = re.compile(r"^(?:(S\d+)\.(?:p(\d+)|(end))|(start|end)|([A-Z]{2,4}))([+-]\d+(?:\.\d+)?)?$")


class PartsError(ValueError):
    pass


def parts_path(d):
    return d / f"{d.name}.parts.json"


def num(v):
    """Decimal → JSON の数（小数の桁が無ければ int・あれば float。8.00 → 8.0・0 → 0）"""
    return int(v) if v.as_tuple().exponent >= 0 else float(v)


def off_text(off):
    return "" if off == 0 else f" {'+' if off > 0 else '-'} {abs(off)}"


class Time:
    """解いた時刻。value は秒（Decimal）。kind: phrase・sentence_end・start・end・mark。voice は句の頭（phrase のときだけ）"""

    def __init__(self, value, kind, name=None, off=Decimal(0), voice=None):
        self.value, self.kind, self.name, self.off, self.voice = value, kind, name, off, voice


class Ctx:
    def __init__(self, timeline, bounds, letter, marks=None):
        self.heads = {}
        self.ends = {}
        for s in timeline["sentences"]:
            self.ends[s["id"]] = Decimal(str(s["end"]))
            for i, ph in enumerate(s["phrases"], 1):
                self.heads[(s["id"], i)] = Decimal(str(ph["start"]))
        self.start, self.end = bounds
        self.letter = letter
        self.marks = marks if marks is not None else {}

    def ref(self, s, where=""):
        m = REF.match(str(s).replace(" ", ""))
        if not m:
            raise PartsError(f"{self.letter}{where}: 時刻の書き方が分からない: {s!r}（S4.p3・S7.end・start・end・mark の名前に ±秒）")
        sid, p, s_end, edge, mark, off = m.groups()
        off = Decimal(off) if off else Decimal(0)
        if sid and p:
            key = (sid, int(p))
            if key not in self.heads:
                raise PartsError(f"{self.letter}{where}: 声の時刻表に無い句: {s}")
            return Time(self.heads[key] + off, "phrase", off=off, voice=self.heads[key])
        if sid:
            if sid not in self.ends:
                raise PartsError(f"{self.letter}{where}: 声の時刻表に無い文: {s}")
            return Time(self.ends[sid] + off, "sentence_end", off=off)
        if edge:
            if self.start is None:
                raise PartsError(f"{self.letter}{where}: 区間の始まりが決まる前に {edge} は使えない: {s}")
            return Time((self.start if edge == "start" else self.end) + off, edge, off=off)
        if mark not in self.marks:
            raise PartsError(f"{self.letter}{where}: mark の拍で決めていない名前: {s}")
        return Time(self.marks[mark] + off, "mark", name=mark, off=off)

    def t(self, s, where=""):
        """cues に書く時刻。区間の始まりからの時刻は、型が定数を持つ区間（film.CONST_SECTIONS）なら「E0 + 0.25」の式、mark は「DS + 0.8」の式、ほかは数"""
        r = self.ref(s, where)
        if r.kind == "start" and self.letter in film.CONST_SECTIONS:
            return f"{self.letter}0{off_text(r.off)}"
        if r.kind == "mark":
            return f"{r.name}{off_text(r.off)}"
        return num(r.value)

    def until(self, at, until, next_letter, where=""):
        """at から until までの長さ。始まり→次の区間の始まりで、両方に型の定数があれば「H0 - G0 + 0.6」の式"""
        a, u = self.ref(at, where), self.ref(until, where)
        if (a.kind == "start" and a.off == 0 and u.kind == "end" and self.letter in film.CONST_SECTIONS
                and next_letter in film.CONST_SECTIONS):
            return f"{next_letter}0 - {self.letter}0{off_text(u.off)}"
        return num(u.value - a.value)


# ---- 字の要素

def element_id(e):
    return e["id"]


def element_overlay(e):
    kind = e.get("kind", "text")
    if kind == "text":
        return {k: e[k] for k in ("id", "class", "style", "text") if k in e}
    if kind == "follow":   # 境目と一緒に動く字（外側の箱 <id>w を split の拍と同じだけ動かす）
        return (f'<div id="{e["id"]}w" style="position:absolute; left:0; top:{e["follow"]}px; width:1080px; height:0">'
                f'<div id="{e["id"]}" class="{e["class"]}" style="{e["style"]}">{e["text"]}</div></div>')
    if kind == "icon":
        return f'<div id="{e["id"]}" class="care-ic">{ICONS[e["icon"]]}{e["text"]}</div>'
    if kind == "headline":
        return (f'<div id="{e["id"]}"><span class="s">{e["sub"]}</span><span class="b">'
                + "".join(f'<span class="w">{w}</span>' for w in e["words"]) + "</span></div>")
    if kind == "underline":
        w, h = e["w"], e["h"]
        return f'<div id="{e["id"]}"><svg viewBox="0 0 {w} {h}"><path d="M 4 {h // 2 + 2} Q {w // 4} {h // 2 - 6} {w // 2} {h // 2} T {w - 4} {h // 2 - 2}" /></svg></div>'
    raise PartsError(f"字の要素の kind が分からない: {kind}")


def element_text(e):
    kind = e.get("kind", "text")
    if kind == "headline":
        return e["sub"] + "".join(e["words"])
    return e.get("text", "")


def element_hidden(e):
    if "hide" in e:
        return list(e["hide"])
    kind = e.get("kind", "text")
    if kind == "headline":
        return [f'#{e["id"]} .s', f'#{e["id"]} .w']
    if kind == "underline":
        return []
    return [f'#{e["id"]}']


def first_id(sel):
    m = re.match(r"^#([\w-]+)", sel)
    return m.group(1) if m else None


# ---- 拍（beats）。どれも (ctx, b, out) を受け、out.cues に cue を足し、宣言（qa の行・写真の点・隠す字）を out に足す

class Out:
    def __init__(self):
        self.cues, self.hidden, self.overlays = [], [], []
        self.text_sync, self.subjects, self.points = [], [], []
        self.extras = {}   # カメラ → photos の extras（点・光の範囲・札）
        self.anchors = []  # (秒, カメラ, 構図が落ち着くまでの秒, 構図の変化か, subject)
        self.cams = []     # (カメラ, 動きの種類)
        self.words = []
        self.pill_from = None


def kind_of(before, after, ease):
    """カメラの動きの種類（指紋の語）: 寄る（ゆっくり寄る）・引く・流す・止め"""
    s0, s1 = float(Decimal(str(before.get("scale", 1)))), float(Decimal(str(after.get("scale", before.get("scale", 1)))))
    if s1 - s0 > 0.005:
        return "ゆっくり寄る" if ease == "none" else "寄る"
    if s0 - s1 > 0.005:
        return "引く"
    if any(after.get(k) is not None and str(after[k]) != str(before.get(k)) for k in ("x", "y")):
        return "流す"
    return "止め"


def beat_cam(ctx, b, out, st):
    cam = b["cam"]
    t = ctx.t(b["at"], f" {cam}")
    out.cues.append({"to": cam, "v": {**b["to"], "duration": b["d"], "ease": b["ease"]}, "t": t})
    out.anchors.append((ctx.ref(b["at"]).value, cam, Decimal(str(b["d"])), b["ease"] != "none", b.get("subject")))
    out.cams.append((cam, kind_of(st.cam.get(cam, {}), b["to"], b["ease"])))
    st.cam[cam] = {**st.cam.get(cam, {}), **b["to"]}


GRADE_KEYS = {"exposure": "--hf-color-grading-exposure", "blur": "--hf-color-grading-blur"}


def beat_grade(ctx, b, out, st):
    v = {GRADE_KEYS[k]: b[k] for k in b if k in GRADE_KEYS}
    out.cues.append({"to": f'{b["grade"]}-img', "v": {**v, "duration": b["d"], "ease": b["ease"]}, "t": ctx.t(b["at"])})


def beat_show(ctx, b, out, st):
    sel, how = b["show"], b["how"]
    t = ctx.t(b["at"], f" {sel}")
    if how in ("soft", "slide"):
        out.cues.append({how: sel, "t": t})
    elif how in ENTRANCES:
        frm, v = ENTRANCES[how]
        v = {k: (b["stagger"] if k == "stagger" else x) for k, x in v.items()}
        out.cues.append({"fromTo": sel, "from": dict(frm), "v": v, "t": t})
    else:
        raise PartsError(f"{ctx.letter}: 字の入り how が分からない: {how}")
    if b.get("qa"):
        text_sync_row(ctx, out, st, first_id(sel), b["at"], b.get("box"))


def text_sync_row(ctx, out, st, eid, at, box=None):
    """qa_text_sync の1行: 名前（id と画面の字）・字の入りの秒・声の句の頭（時刻を句で指したときだけ）・字の領域"""
    r = ctx.ref(at)
    e = st.elements.get(eid)
    box = box or (e or {}).get("box")
    if not box:
        raise PartsError(f"{ctx.letter}: 字の同期を測る {eid} に box（画面の矩形）が無い")
    text = re.sub(r"\s+", "", (st.template_text.get(eid) if e is None else element_text(e)) or "")
    out.text_sync.append([f"{eid} {text}".strip(), num(r.value), num(r.voice) if r.voice is not None else None, list(box)])


def beat_hide(ctx, b, out, st):
    out.cues.append({"out": b["hide"], "t": ctx.t(b["at"])})


def beat_draw(ctx, b, out, st):
    """下線を引く（#kick-ul・#cta-ul・underline の要素）"""
    out.cues.append({"to": f'{b["draw"]} path', "v": {"strokeDashoffset": 0, "duration": b["d"], "ease": "power2.inOut"}, "t": ctx.t(b["at"])})
    if b.get("qa"):
        text_sync_row(ctx, out, st, first_id(b["draw"]), b["at"], b.get("box"))


def beat_tween(ctx, b, out, st):
    """字・飾り・幕などの動き（カメラ・写真の色調整は cam・grade の拍で書く）"""
    if first_id(b["tween"]) in film.CAMS:
        raise PartsError(f"{ctx.letter}: カメラ {b['tween']} は tween でなく cam の拍で書く")
    t = ctx.t(b["at"])
    if "from" in b:
        out.cues.append({"fromTo": b["tween"], "from": b["from"], "v": b["v"], "t": t})
    else:
        c = {"to": b["tween"], "v": b["v"], "t": t}
        if b.get("note"):
            c["note"] = b["note"]
        out.cues.append(c)


def beat_split(ctx, b, out, st):
    """上下の境目を動かす（注目の移動）。y は 952 からのずれ"""
    out.cues.append({"split": b["split"], "t": ctx.t(b["at"]), "d": b["d"], "ease": b["ease"]})
    t = ctx.ref(b["at"]).value
    for cam in ("#t-aft", "#b-mug", "#b-col"):
        sub = b.get("subject") if b.get("subject", {}).get("cam") == cam else None
        out.anchors.append((t, cam, Decimal(str(b["d"])), True, sub))


def beat_mark(ctx, b, out, st):
    out.cues.append(f'const {b["mark"]} = {film.js_value(num(ctx.marks[b["mark"]]))};')


def beat_comment(ctx, b, out, st):
    out.cues.append(f'// {b["comment"]}')


def fx_cams(b):
    out = []
    for path in FX[b["fx"]]["cams"]:
        v = b
        for k in path.split("."):
            v = v[k]
        out.append(v)
    return out


def beat_fx(ctx, b, out, st):
    """つなぎ（film.py の5種の切り替え）。at → t、until → d（drift の終わり）、split_y → at（merge の開き始めの y）に読み替えて書いた順のまま渡す"""
    spec = FX.get(b["fx"])
    if not spec:
        raise PartsError(f"{ctx.letter}: つなぎ fx が分からない: {b['fx']}")
    c = {}
    for k, v in b.items():
        if k == "subject":
            continue
        if k == "at":
            c["t"] = ctx.t(v, f" {b['fx']}")
        elif k == "until":
            c["d"] = ctx.until(b["at"], v, st.next_letter, f" {b['fx']}")
        elif k == "split_y":
            c["at"] = v
        else:
            c[k] = v
    out.cues.append(c)
    t = ctx.ref(b["at"]).value
    cams = fx_cams(b)
    sub = b.get("subject")
    for cam in cams:
        mine = sub if sub and sub.get("cam", cams[0]) == cam else None
        out.anchors.append((t, cam, Decimal(spec["settle"]), True, mine))
    out.words += spec["words"]
    st.fx.append((b["fx"], spec))
    # カメラの動きの種類
    moves = {"dissolve": [(b.get("cam"), b.get("to"))], "merge": [(b.get("cam"), b.get("to"))],
             "wipe": [(b["top"]["cam"], b["top"]["to"]), (b["bot"]["cam"], b["bot"]["to"])] if b["fx"] == "wipe" else [],
             "push_in": [(b.get("cam"), None), (b.get("other"), b.get("other_to"))],
             "push_out": [(b.get("out"), {"x": b.get("out_x")}), (b.get("in"), {"x": b.get("in_x")})]}[b["fx"]]
    if b["fx"] == "wipe":
        for part in (b["top"], b["bot"]):
            st.cam[part["cam"]] = {**st.cam.get(part["cam"], {}), **part["from"]}
    if b["fx"] == "merge":
        st.cam[b["cam"]] = {**st.cam.get(b["cam"], {}), **b["from"]}
    for cam, to in moves:
        if to is None:
            out.cams.append((cam, "押し込む"))
            st.cam[cam] = {**st.cam.get(cam, {}), **b["to"]}
        else:
            out.cams.append((cam, kind_of(st.cam.get(cam, {}), to, "none")))
            st.cam[cam] = {**st.cam.get(cam, {}), **to}


def beat_point(ctx, b, out, st):
    """点と札（指し方 A＋C）: spot があれば写真を沈めて光の範囲・点・線を出す（film.spot）。無ければ点と線だけを出す。
    tag があれば点の札（svg）を写真に足し、跳ねて出す。写真の extras（光の範囲・点・札）と qa_points の行もここで作る"""
    name, cam = b["point"], b["cam"]
    ex = out.extras.setdefault(cam, [])
    if b.get("spot"):
        ex.append({"spot": name, "ellipses": b["spot"]})
    ex.append({"lead": name, **b["lead"]})
    dot, line = ctx.ref(b["dot"]).value, ctx.ref(b["line"]).value
    ends = [dot + DOT_IN, line + Decimal(str(b["ld"]))]
    if b.get("spot"):
        out.cues.append({"spot": name, "img": f"{cam}-img", "t": ctx.t(b["at"]), "d": b["d"], "ease": b["ease"],
                         "dot": ctx.t(b["dot"]), "line": ctx.t(b["line"]), "ld": b["ld"]})
        ends.append(ctx.ref(b["at"]).value + Decimal(str(b["d"])))
    else:
        out.cues.append({"to": f"#c-{name} circle", "v": {"scale": 1, "opacity": 1, "duration": float(DOT_IN), "ease": "back.out(2)"}, "t": ctx.t(b["dot"])})
        out.cues.append({"to": f"#c-{name} path", "v": {"strokeDashoffset": 0, "duration": b["ld"], "ease": "power2.out"}, "t": ctx.t(b["line"])})
    tag = b.get("tag")
    if tag:
        x, y, w, h = tag["x"], tag["y"], tag["w"], 84
        ex.append(f'<svg id="{name}tag" viewBox="0 0 1440 2160"><rect x="{x - w // 2}" y="{y}" width="{w}" height="{h}" rx="14" fill="rgba(30,22,16,.62)" />'
                  f'<text x="{x}" y="{y + 60}" text-anchor="middle" font-family="Noto Sans JP" font-weight="700" font-size="44" fill="#fbf8f2">{tag["text"]}</text></svg>')
        out.cues.append({"fromTo": f"#{name}tag", "from": {"opacity": 0, "scale": 0.85, "transformOrigin": f"{x}px {y + h // 2}px"},
                         "v": {"opacity": 1, "scale": 1, "duration": "IN", "ease": "back.out(2)"}, "t": ctx.t(tag["at"])})
        out.hidden.append(f"#{name}tag")
    out.points.append([name, cam, num(max(ends))])
    out.words += OVERLAYS["point"]["words"]


def beat_chapter(ctx, b, out, st):
    out.cues.append({"pill": b["chapter"], "t": ctx.t(b["at"])})
    out.words += OVERLAYS["chapter"]["words"]


def pill_sels(st):
    return [f"#p{i}" for i in range(1, len(st.chapters) + 1)]


def beat_chapters_off(ctx, b, out, st):
    out.cues.append({"to": pill_sels(st), "v": {"opacity": 0, "duration": 0.3, "ease": "power2.in"}, "t": ctx.t(b["at"])})


def beat_cards(ctx, b, out, st):
    """写真の小窓つきカード（章の数だけ）を声に合わせて置き、章の札をカードの下に出す（札はあとで cards_done が上の列へ運ぶ）"""
    cards = b["cards"]
    if len(cards) != len(st.chapters):
        raise PartsError(f"{ctx.letter}: カードの数 {len(cards)} が章の数 {len(st.chapters)} と違う")
    items = []
    for i, c in enumerate(cards, 1):
        out.overlays.append({"card": i, "file": c["file"], "style": c["style"]})
        items.append(f'["#card{i}", "#p{i}", {film.js_value(ctx.t(c["at"]))}]')
    out.cues += [f'[{", ".join(items)}].forEach(([c, p, t]) => {{',
                 '  tl.fromTo(c, { opacity: 0, x: 60 }, { opacity: 1, x: 0, duration: 0.45, ease: "expo.out" }, t);',
                 '  tl.fromTo(p, { opacity: 0, filter: "blur(6px)" }, { opacity: 1, filter: "blur(0px)", duration: IN, ease: "power3.out" }, t + 0.06);',
                 "});"]
    out.hidden += [".card", *pill_sels(st)]
    out.pill_from = [c["pill_from"] for c in cards]
    for i, c in enumerate(cards, 1):
        r = ctx.ref(c["at"])
        out.text_sync.append([f"card{i} {i}{st.chapters[i - 1]['text']}", num(r.value + Decimal("0.06")),
                              num(r.voice) if r.voice is not None else None, list(c["box"])])
    out.words += OVERLAYS["cards"]["words"]


def beat_cards_done(ctx, b, out, st):
    """カードを消し、章の札を上の列へ運んで1つ目の章を点ける"""
    t = ctx.t(b["at"])
    out.cues += [{"to": ".card", "v": {"opacity": 0, "y": -24, "filter": "blur(8px)", "duration": 0.3, "ease": "power2.in"}, "t": t},
                 f"// 札が上の列へ運ばれ、現在地になる（1 {st.chapters[0]['text']}が点灯）",
                 {"to": pill_sels(st), "v": {"x": 0, "y": 0, "scale": 1, "duration": 0.6, "ease": "power3.inOut", "stagger": 0.05}, "t": t},
                 {"pill": 1, "t": num(ctx.ref(b["at"]).value + Decimal("0.3"))}]


def beat_answer(ctx, b, out, st):
    """答え・導線: 問いの板を戻し、問いを薄く残して、答えの前置き（ans-s）→答え（ans-b の語が順に）→問いと答えを消して導線（cta）→下線"""
    a = b["answer"]
    st.template_text.update({"ans-s": a["s"], "ans-b": "".join("".join(x) for x in a["b"]), "cta": a["cta"]})
    st.answer = a
    pop_from, pop_v = ENTRANCES["pop"]
    out.cues += [
        {"to": "#qplate", "v": {"opacity": 1, "duration": 0.4, "ease": "power2.out"}, "t": ctx.t(a["plate"])},
        {"to": "#q", "v": {"opacity": 0.7, "filter": "blur(0px)", "duration": "IN", "ease": "power2.out"}, "t": ctx.t(a["q"])},
        {"fromTo": "#ans-s", "from": dict(ENTRANCES["fade"][0]), "v": dict(ENTRANCES["fade"][1]), "t": ctx.t(a["s_at"])},
        {"fromTo": "#ans-b .w", "from": dict(pop_from), "v": {k: (a["stagger"] if k == "stagger" else x) for k, x in pop_v.items()}, "t": ctx.t(a["b_at"])},
        {"out": ["#q", "#ans-s", "#ans-b"], "t": ctx.t(a["out"])},
        {"slide": "#cta", "t": ctx.t(a["cta_at"])},
        {"to": "#cta-ul path", "v": {"strokeDashoffset": 0, "duration": 0.5, "ease": "power2.inOut"}, "t": ctx.t(a["ul"])},
    ]
    out.hidden += ["#ans-s", "#ans-b .w", "#cta"]
    for eid, at in (("ans-s", a["s_at"]), ("ans-b", a["b_at"]), ("cta", a["cta_at"])):
        text_sync_row(ctx, out, st, eid, at, a["box"][eid])
    out.words += OVERLAYS["answer"]["words"]


BEATS = {"cam": beat_cam, "grade": beat_grade, "show": beat_show, "hide": beat_hide, "draw": beat_draw, "tween": beat_tween,
         "split": beat_split, "mark": beat_mark, "comment": beat_comment, "fx": beat_fx, "point": beat_point,
         "chapter": beat_chapter, "chapters_off": beat_chapters_off, "cards": beat_cards, "cards_done": beat_cards_done,
         "answer": beat_answer}


BEAT_ORDER = ("fx", "point", "answer", "cards", "cards_done", "chapters_off", "chapter", "mark", "comment", "split", "show", "hide",
              "draw", "grade", "tween", "cam")   # 拍の種類を見分ける順（fx・point も cam の項目を持つので先に見る）


def beat_kind(b):
    for k in BEAT_ORDER:
        if k in b:
            return k
    raise PartsError(f"拍の種類が分からない: {json.dumps(b, ensure_ascii=False)[:80]}")


# ---- 組み立て

class State:
    def __init__(self, defn):
        self.chapters = defn.get("chapters", [])
        self.cam = {}
        self.elements = {}
        self.template_text = {}
        self.answer = None
        self.fx = []
        self.next_letter = None


def subject_rows(letter, scene, anchors, end):
    """拍の subject から qa_subjects の行。区間は「その拍の動きが終わった時」から「同じカメラの次の構図の変化（または部品の終わり）」まで"""
    rows = []
    for i, (t, cam, settle, _, sub) in enumerate(anchors):
        if not sub:
            continue
        nxt = [t2 for t2, cam2, _, change, _ in anchors[i + 1:] if cam2 == cam and change and t2 > t]
        t0, t1 = t + settle, min([end, *nxt])
        ref = scene != "split"
        pos = PANEL_POS[cam]
        name = f"参考 {letter} {sub['name']}" if ref else f"{letter}{pos} {sub['name']}"
        rows.append([name, cam, list(sub["rect"]), num(t0), num(t1), *(["ref"] if ref else [])])
    return rows


def compile_film(defn, timeline, script=None):
    """parts.json の定義と timeline.json から film.json のデータを作る。返り値: (film のデータ, 部品の要約の一覧)"""
    parts = defn["parts"]
    if len(parts) != len(LETTERS):
        raise PartsError(f"案Aのテンプレートは {len(LETTERS)} 区間（{LETTERS}）。部品が {len(parts)} 個")
    if parts[-1].get("scene") != "endcard":
        raise PartsError("最後の部品は endcard（エンドカード）")
    duration = Decimal(str(timeline["duration"]))
    # 区間の始まり（最初は 0）
    starts = [Decimal(0)]
    for k, p in enumerate(parts[1:], 1):
        if "start" not in p:
            raise PartsError(f"{LETTERS[k]}: start が無い")
        starts.append(Ctx(timeline, (None, None), LETTERS[k]).ref(p["start"], " start").value)
    for k in range(1, len(starts)):
        if starts[k] <= starts[k - 1]:
            raise PartsError(f"{LETTERS[k]}: 始まり {starts[k]} が前の部品の始まり {starts[k - 1]} より後でない")
    if starts[-1] >= duration:
        raise PartsError(f"エンドカードの始まり {starts[-1]} が声の尺 {duration} より後")
    bounds = [(starts[k], starts[k + 1] if k + 1 < len(starts) else duration) for k in range(len(starts))]

    st = State(defn)
    if "cover" not in parts[0]:
        raise PartsError("A: 最初の部品に cover（カバーの問いとカメラの初期値）が無い")
    cover = parts[0]["cover"]
    st.template_text.update({"kick-ul": cover["kick"], "kick": cover["kick"], "q": "".join(cover["q"])})
    st.cam = {cam: dict(v) for cam, v in cover["cams"].items()}
    cues, hidden_groups, overlay_groups = {}, [], []
    text_sync, subjects, points, extras = [], [], [], {}
    pill_from, summary = None, []
    prev_layout = None
    for k, p in enumerate(parts):
        letter, scene = LETTERS[k], p.get("scene")
        if scene not in SCENES:
            raise PartsError(f"{letter}: scene が分からない: {scene}（{'・'.join(SCENES)}）")
        spec = SCENES[scene]
        st.next_letter = LETTERS[k + 1] if k + 1 < len(LETTERS) else None
        marks = {}
        base = Ctx(timeline, bounds[k], letter)
        for b in p.get("beats", []):
            if "mark" in b:
                if not re.match(r"^[A-Z]{2,4}$", b["mark"]):
                    raise PartsError(f"{letter}: mark の名前は大文字2〜4字: {b['mark']}")
                marks[b["mark"]] = base.ref(b["at"], f" mark {b['mark']}").value
        ctx = Ctx(timeline, bounds[k], letter, marks)
        for e in p.get("texts", []):
            st.elements[element_id(e)] = e
        out = Out()
        out.words += spec["words"]
        if k == 0:
            out.words += OVERLAYS["cover"]["words"]
        st.fx = []
        if scene != "endcard":
            s, e = bounds[k]
            out.cues.append(f"// ==== {letter} {p['name']}（{'0.0' if s == 0 else f'{s:.2f}'}–{e:.2f}）: {p['note']}")
        for b in p.get("beats", []):
            kind = beat_kind(b)
            if kind in ("cam",) and b["cam"] not in spec["visible"]:
                raise PartsError(f"{letter}: {spec['layout']}の場面で {b['cam']} は見えない")
            BEATS[kind](ctx, b, out, st)
        # つなぎと割り方の対応
        for name, fx in st.fx:
            if fx["to"] != (scene if scene != "endcard" else "full") or (prev_layout and fx["from"] != prev_layout):
                raise PartsError(f"{letter}: つなぎ {name} は {fx['from']}→{fx['to']}。前の部品 {prev_layout}→この部品 {scene} に合わない")
        here = "full" if scene == "endcard" else scene
        if not st.fx and prev_layout and prev_layout != here:
            raise PartsError(f"{letter}: 割り方が {prev_layout}→{here} と変わるのに、つなぎ（fx の拍）が無い")
        prev_layout = here
        cues[letter] = out.cues
        group = [h for e in p.get("texts", []) for h in element_hidden(e)] + out.hidden
        if group:
            hidden_groups.append(group)
        og = [element_overlay(e) for e in p.get("texts", [])] + out.overlays
        if og:
            if p.get("chapter"):
                og = [f"<!-- {st.chapters[p['chapter'] - 1]['text']} -->", *og]
            overlay_groups.append(og)
        text_sync += out.text_sync
        rows = subject_rows(letter, scene, out.anchors, bounds[k][1])
        subjects += rows
        points += out.points
        for cam, ex in out.extras.items():
            extras.setdefault(cam, []).extend(ex)
        if out.pill_from:
            pill_from = out.pill_from
        s, e = bounds[k]
        length = float(e - s)
        cams = {}
        for cam, kind in out.cams:
            cams.setdefault(cam, []).append(kind)
        summary.append({"letter": letter, "scene": scene, "name": p.get("name", "エンドカード"), "start": float(s), "end": float(e),
                        "seconds": round(length, 2), "min": spec["min"], "max": spec["max"], "in_range": spec["min"] <= length <= spec["max"],
                        "layout": spec["layout"], "visible": spec["visible"], "camera": cams or {"-": ["止め"]},
                        "subjects": [r[0] for r in rows],
                        "points": [x[0] for x in out.points], "texts": [r[0] for r in out.text_sync], "words": list(dict.fromkeys(out.words))})

    if st.answer is None:
        raise PartsError("答え（answer の拍）が無い")
    chapters = st.chapters
    overlays = []
    if chapters:
        overlays.append("<style>" + "".join(f'#p{i}{{left:{c["left"]}px;width:{c["width"]}px}}' for i, c in enumerate(chapters, 1)) + "</style>")
    for i, g in enumerate(overlay_groups):
        overlays += ([""] if i else []) + g
    hidden = []
    for g in hidden_groups:
        if hidden and len(hidden[-1]) + len(g) <= HIDDEN_PER_LINE:
            hidden[-1] += g
        else:
            hidden.append(list(g))
    photos = {}
    for cam, ph in defn["photos"].items():
        photos[cam] = {**ph, "extras": extras.get(f"#{cam}", [])}
    lexicon = defn["lexicon"] if "lexicon" in defn else (script or {}).get("lexicon", [])
    data = {
        "_comment": f"動画{defn['n']}。部品の定義 video-{defn['n']}.parts.json と声の時刻表（work/timeline.json）から make-video が作った（手で直さない。直すのは parts.json）",
        "n": defn["n"], "lexicon": lexicon, "slug": defn["slug"], "title": defn["title"], "timeline_label": defn["timeline_label"],
        "sections": {LETTERS[k]: num(s) for k, (s, _) in enumerate(bounds)},
        "grade": defn["grade"], "photos": photos, "masks": defn.get("masks", {}),
        "kick": cover["kick"], "q": cover["q"], "overlays": overlays,
        "ans_s": st.answer["s"], "ans_b": st.answer["b"], "cta": st.answer["cta"],
        "pills": [c["text"] for c in chapters], "cover": cover["cams"], "hidden": hidden, "pill_from": pill_from or [],
        "qa_text_sync": [[NOTE_TEXT_SYNC], *text_sync], "qa_subjects": [[NOTE_SUBJECTS], *subjects], "qa_points": [[NOTE_POINTS], *points],
        "cues": cues,
    }
    return data, summary


def load(d):
    """動画フォルダの parts.json・timeline.json・script.json を読む。返り値: (定義, 時刻表, 台本)"""
    defn = json.loads(parts_path(d).read_text(encoding="utf-8"))
    tl = d / "work" / "timeline.json"
    if not tl.exists():
        raise PartsError(f"声の時刻表が無い（先に voice の段）: {tl}")
    sc = d / "script.json"
    return defn, json.loads(tl.read_text(encoding="utf-8")), (json.loads(sc.read_text(encoding="utf-8")) if sc.exists() else None)


def dump(data):
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def summary_lines(summary):
    out = []
    for s in summary:
        cam = "・".join(f"{c} {'/'.join(k)}" for c, k in s["camera"].items())
        rng = "" if s["in_range"] else f"（目安 {s['min']}〜{s['max']}秒の外）"
        out.append(f"{s['letter']} {s['scene']:<7} {s['name']}  {s['start']:.2f}–{s['end']:.2f}（{s['seconds']}秒{rng}）  割り方 {s['layout']}  カメラ {cam}  "
                   f"主役 {len(s['subjects'])}・点 {len(s['points'])}・字の同期 {len(s['texts'])}  語 {'・'.join(s['words'])}")
    return out
