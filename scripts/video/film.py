"""型の段（comp）: 型テンプレート templates/film-planA.html と1本ごとのデータ video-N.film.json から composition を組む。
深さは案A（写真4枚: 上 #t-aft・下 #b-mug と #b-col・全面 #f-gift／場面3つ）に固定。場面の数は一般化しない。

テンプレートが持つもの（型）: CSS・字の入りの関数（soft・slide・out・split）・0コマ目の固定の set・エンドカード（ロゴ・AI表示・H0 からの動き）・index.html の形。
データが持つもの（1本ごと）: 区間の秒・字の文言・写真と色調整・カメラの値・指す場所（spot・lead）・マスク・区間ごとの手順（cues）・読みの例外（lexicon）・
  qa が使う表（qa_text_sync 字の同期・qa_subjects 主題の帯・qa_points 点の位置）。尺（index.html の data-duration）は work/timeline.json の duration から入れる。

cues の1件は次のどれか。秒（t）と値は JS の式としてそのまま書く（数か、"E0 + 1.40" のような文字列）。
  "文字列"                                   その行をそのまま（注釈・const・forEach など）
  {"to"|"set": 対象, "v": {…}, "t": 秒}       tl.to / tl.set
  {"fromTo": 対象, "from": {…}, "v": {…}, "t": 秒}
  {"soft"|"slide"|"out": 対象, "t": 秒}       字の入り・出
  {"split": y, "t": 秒, "d": 長さ, "ease": …}  上下の境目
  {"spot": 名前, "img": …, "t", "d", "ease", "dot", "line", "ld"}   指し方 A＋C（写真を沈め、光の範囲・点・線を出す）
  {"pill": 番号, "t": 秒}                     章の札の点灯（1 は最初の点灯、2 以降は前の札を消して点ける）
  {"fx": 切り替えの種類, …}                   5種の切り替え（FX の関数。引数は各関数の説明）
値（v の中）の書き方: 数はそのまま。文字列は「数・大文字の定数（DIM・E0 など）・四則」だけなら式としてそのまま、それ以外は "" で囲む
（"power2.inOut" → "power2.inOut"、"H0 - G0 + 0.6" → H0 - G0 + 0.6）。キーが -- で始まるものは "" で囲む。
"""
import json
import re
import shutil
from decimal import Decimal, InvalidOperation
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

TEMPLATES = Path(__file__).resolve().parent / "templates"
FILM_TEMPLATE = TEMPLATES / "film-planA.html"
INDEX_TEMPLATE = TEMPLATES / "index.html"
CAMS = ("b-mug", "b-col", "t-aft", "f-gift")
SECTIONS = ("A", "B", "C", "D", "E", "F", "G")
CREDIT = "画像・文・ナレーション　AIの紅茶案内人"   # AI表示の文言（型の定数。qa が画面の字と照合する）
LOGO_D, LOGO_CX, LOGO_CY = 520, 540, 960       # エンドカードのロゴ（直径・中心）
RAW_VALUE = re.compile(r"^[-+*/0-9. ()A-Z_]+$")


# ---- 値と秒の書き方

def js_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if v in ("true", "false") or v.startswith(('"', "`")) or RAW_VALUE.match(v):
        return v
    return json.dumps(v, ensure_ascii=False)


def js_vars(d):
    if not d:
        return "{}"
    return "{ " + ", ".join(f'{json.dumps(k) if k.startswith("--") else k}: {js_value(v)}' for k, v in d.items()) + " }"


def js_sel(s):
    if isinstance(s, list):
        return "[" + ", ".join(json.dumps(x, ensure_ascii=False) for x in s) + "]"
    return json.dumps(s, ensure_ascii=False)


def at(t, off=0):
    """秒 t に off を足した式。t が数なら計算し（5.0＋0.05 → 5.05）、定数の式なら「F0 - 0.01」の形にする。"""
    if off == 0:
        return js_value(t)
    try:
        return str(Decimal(str(t)) + Decimal(str(off)))
    except InvalidOperation:
        return f"{t} {'+' if off > 0 else '-'} {abs(off)}"


# ---- 5種の切り替え（データの {"fx": 種類, …} から呼ぶ）

def fx_dissolve(c):
    """① 溶かし: 上下2枚の境目を縮め、全面の写真（ぼかしから戻る）を重ねて1枚にする。
    引数: cam（全面のカメラ）・t・to（寄りの終わりのカメラ）・d（寄りの長さ）"""
    cam = c["cam"]
    return [f'tl.to("#div", {{ scaleX: 0, duration: 0.5, ease: "power2.in" }}, {at(c["t"])});',
            f'tl.to("#full", {{ opacity: 1, duration: 0.8, ease: "power2.inOut" }}, {at(c["t"])});',
            f'tl.to("{cam}-img", {{ "--hf-color-grading-blur": 0, duration: 0.9, ease: "power2.out" }}, {at(c["t"], 0.05)});',
            f'tl.to("{cam}", {js_vars({**c["to"], "duration": c["d"], "ease": "none"})}, {at(c["t"])});']


def fx_wipe(c):
    """② 払う: 全面の写真を横に払い、上下2枚へ。境目は左から伸びる。
    引数: t・top/bot（各 {"cam", "from", "to"}: 払う直前に置くカメラと、流しの終わりのカメラ）・d（流しの長さ）"""
    top, bot, t = c["top"], c["bot"], c["t"]
    return [f'tl.set("{top["cam"]}", {js_vars(top["from"])}, {at(t, -0.01)});',
            f'tl.set("{bot["cam"]}", {js_vars(bot["from"])}, {at(t, -0.01)});',
            f'tl.set("#div", {{ transformOrigin: "0% 50%" }}, {at(t, -0.01)});',
            f'tl.to("#div", {{ scaleX: 1, duration: 0.7, ease: "power3.inOut" }}, {at(t)});',
            f'tl.to("#full", {{ clipPath: "inset(0px 0px 0px 1080px)", duration: 0.7, ease: "power3.inOut" }}, {at(t)});',
            f'tl.to("{top["cam"]}", {js_vars({**top["to"], "duration": c["d"], "ease": "none"})}, {at(t)});',
            f'tl.to("{bot["cam"]}", {js_vars({**bot["to"], "duration": c["d"], "ease": "none"})}, {at(t)});']


def fx_push_in(c):
    """③ 押し込む寄り: 境目を中央へ戻し、片方の写真へ強く寄る（ぼかしを少し）。もう片方は引いて暗くする。
    引数: t・cam・to（寄りの終わり）・other・other_to・other_exposure"""
    t, cam, other = c["t"], c["cam"], c["other"]
    return [f'split(0, {at(t)}, 0.7, "power3.inOut");',
            f'tl.to("{cam}", {js_vars({**c["to"], "duration": 0.75, "ease": "power3.inOut"})}, {at(t)});',
            f'tl.to("{cam}-img", {{ "--hf-color-grading-exposure": 0, "--hf-color-grading-blur": 0.6, duration: 0.6, ease: "power2.inOut" }}, {at(t)});',
            f'tl.to("{other}", {js_vars({**c["other_to"], "duration": 0.7, "ease": "power3.inOut"})}, {at(t)});',
            f'tl.to("{other}-img", {{ "--hf-color-grading-exposure": {js_value(c["other_exposure"])}, duration: 0.7, ease: "power2.inOut" }}, {at(t)});']


def fx_push_out(c):
    """④ 押し出し: 同じ段の写真を横に押し出し、次の写真を入れる。
    引数: t・out（押し出すカメラ）・out_x・in（入れるカメラ）・in_x"""
    t = c["t"]
    return [f'tl.set("{c["in"]}", {{ opacity: 1 }}, {at(t, -0.01)});',
            f'tl.to("{c["out"]}", {{ x: {js_value(c["out_x"])}, duration: 0.7, ease: "power3.inOut" }}, {at(t)});',
            f'tl.to("{c["in"]}", {{ x: {js_value(c["in_x"])}, duration: 0.7, ease: "power3.inOut" }}, {at(t)});']


def fx_merge(c):
    """⑤ 合わさる: 境目の位置（at の y）から上下に開いて、全面の写真1枚になる。
    引数: t・cam・from（開く前のカメラ）・exposure・at（開き始めの y）・to・d（寄りの長さ）"""
    t, cam, y = c["t"], c["cam"], int(c["at"])
    return [f'tl.to("#div", {{ opacity: 0, duration: 0.4, ease: "power2.in" }}, {at(t, 0.1)});',
            f'tl.set("{cam}", {js_vars(c["from"])}, {at(t, -0.01)});',
            f'tl.set("{cam}-img", {{ "--hf-color-grading-exposure": {js_value(c["exposure"])} }}, {at(t, -0.01)});',
            f'tl.set("#full", {{ clipPath: "inset({y}px 0px {1920 - y}px 0px)" }}, {at(t, -0.01)});',
            f'tl.to("#full", {{ clipPath: "inset(0px 0px 0px 0px)", duration: 0.8, ease: "power3.inOut" }}, {at(t)});',
            f'tl.to("{cam}", {js_vars({**c["to"], "duration": c["d"], "ease": "power2.out"})}, {at(t)});']


FX = {"dissolve": fx_dissolve, "wipe": fx_wipe, "push_in": fx_push_in, "push_out": fx_push_out, "merge": fx_merge}


def spot(c):
    """指し方 A＋C: 写真を沈め、指す物だけを光の範囲（.spot）で戻し、点（circle）と線（path）を出す。"""
    n = c["spot"]
    return [f'tl.to("{c["img"]}", {{ "--hf-color-grading-exposure": -0.95, "--hf-color-grading-blur": 0.55, duration: {js_value(c["d"])}, ease: {json.dumps(c["ease"])} }}, {at(c["t"])});',
            f'tl.to("#spot-{n}", {{ opacity: 1, duration: {js_value(c["d"])}, ease: {json.dumps(c["ease"])} }}, {at(c["t"])});',
            f'tl.to("#c-{n} circle", {{ scale: 1, opacity: 1, duration: 0.2, ease: "back.out(2)" }}, {at(c["dot"])});',
            f'tl.to("#c-{n} path", {{ strokeDashoffset: 0, duration: {js_value(c["ld"])}, ease: "power2.out" }}, {at(c["line"])});']


def pill(c):
    """章の札の点灯。1 は最初の点灯（ほかの札を暗く）。2 以降は前の札を暗くして点け、少し弾ませる。"""
    k, t = int(c["pill"]), c["t"]
    if k == 1:
        return [f'tl.to("#p1", {{ backgroundColor: "#c8873f", duration: 0.4, ease: "power2.out" }}, {at(t)});',
                f'tl.to(["#p2", "#p3"], {{ backgroundColor: DIM, color: DIMC, boxShadow: "0 0 0 rgba(0,0,0,0)", duration: 0.4, ease: "power2.out" }}, {at(t)});']
    return [f'tl.to("#p{k - 1}", {{ backgroundColor: DIM, color: DIMC, boxShadow: "0 0 0 rgba(0,0,0,0)", duration: 0.3, ease: "power2.out" }}, {at(t)});',
            f'tl.to("#p{k}", {{ backgroundColor: "#c8873f", color: "#3a2a1f", boxShadow: "0 8px 26px rgba(0,0,0,.30)", duration: 0.3, ease: "power2.out" }}, {at(t)});',
            f'tl.fromTo("#p{k}", {{ scale: 1 }}, {{ scale: 1.12, duration: 0.15, ease: "power2.out", yoyo: true, repeat: 1, immediateRender: false }}, {at(t)});']


def cue_lines(c):
    if isinstance(c, str):
        return [c]
    if "fx" in c:
        return FX[c["fx"]](c)
    if "spot" in c:
        return spot(c)
    if "pill" in c:
        return pill(c)
    note = f'  // {c["note"]}' if c.get("note") else ""
    for k in ("to", "set"):
        if k in c:
            return [f'tl.{k}({js_sel(c[k])}, {js_vars(c["v"])}, {at(c["t"])});{note}']
    if "fromTo" in c:
        return [f'tl.fromTo({js_sel(c["fromTo"])}, {js_vars(c["from"])}, {js_vars(c["v"])}, {at(c["t"])});{note}']
    for k in ("soft", "slide", "out"):
        if k in c:
            return [f'{k}({js_sel(c[k])}, {at(c["t"])});{note}']
    if "split" in c:
        return [f'split({js_value(c["split"])}, {at(c["t"])}, {js_value(c["d"])}, {json.dumps(c["ease"])});{note}']
    raise ValueError(f"cue の形が分からない: {c}")


def indent(lines, n=2):
    return "\n".join((" " * n + ln) if ln else "" for ln in lines)


# ---- DOM

def grade_attr(grade):
    return json.dumps(grade, separators=(",", ":"), ensure_ascii=False).replace('"', "&quot;")


def cam_html(cam, p, grade):
    lines = [f'<div id="{cam}" class="cam" data-layout-allow-overflow>',
             f'  <img data-color-grading="{grade_attr(grade)}" id="{cam}-img" style="--hf-color-grading-blur: {p.get("blur", 0)}; '
             f'--hf-color-grading-exposure: 0" src="assets/img/{p["file"]}" alt="">']
    for e in p.get("extras", []):
        if isinstance(e, str):
            lines.append("  " + e)
        elif "spot" in e:
            if "png" in e:
                m = f'url(assets/img/{e["png"]})'
                style = f"-webkit-mask-image:{m}; mask-image:{m}; -webkit-mask-size:1440px 2160px; mask-size:1440px 2160px"
            else:
                m = ", ".join(f"radial-gradient(ellipse {rx}px {ry}px at {x}px {y}px, #000 80%, transparent 100%)" for rx, ry, x, y in e["ellipses"])
                style = f"-webkit-mask-image:{m}; mask-image:{m}"
            lines.append(f'  <img class="spot" id="spot-{e["spot"]}" src="assets/img/{p["file"]}" alt="" style="{style}">')
        elif "lead" in e:
            (x1, y1), (x2, y2), r = e["from"], e["to"], e["r"]
            lines.append(f'  <svg id="c-{e["lead"]}" class="line lead" viewBox="0 0 1440 2160"><path d="M {x1} {y1} L {x2} {y2}" '
                         f'style="stroke-width:{r / 4:.2f}px" /><circle cx="{x2}" cy="{y2}" r="{r}" style="stroke-width:{r * 0.3:.2f}px" /></svg>')
    lines.append("</div>")
    return indent(lines, 4)


def overlay_html(items):
    out = []
    for e in items:
        if isinstance(e, str):
            out.append(e)
        elif "card" in e:
            out.append(f'<div id="card{e["card"]}" class="card"><img src="assets/img/{e["file"]}" alt="" style="{e["style"]}"></div>')
        else:
            cls = f' class="{e["class"]}"' if e.get("class") else ""
            st = f' style="{e["style"]}"' if e.get("style") else ""
            out.append(f'<div id="{e["id"]}"{cls}{st}>{e["text"]}</div>')
    return indent(out)


def render_film(data, template=None):
    s = (template or FILM_TEMPLATE.read_text(encoding="utf-8"))
    sec = data["sections"]
    rep = {
        "cams": {c: cam_html(c, data["photos"][c], data["grade"]) for c in CAMS},
        "kick": data["kick"],
        "q": "".join(f'<span class="l">{x}</span>' for x in data["q"]),
        "overlays": overlay_html(data["overlays"]),
        "ans_s": data["ans_s"],
        "ans_b": "".join('<span class="l">' + "".join(f'<span class="w">{w}</span>' for w in ln) + "</span>" for ln in data["ans_b"]),
        "cta": data["cta"],
        "pills": indent([f'<div id="p{i}" class="pill">{i} {k}</div>' for i, k in enumerate(data["pills"], 1)]),
        "credit": CREDIT,
        "timeline_label": data["timeline_label"],
        "sections": " / ".join(f"{k} {js_value(sec[k])}" for k in (*SECTIONS, "H")),
        "consts": ", ".join(f"{k}0 = {js_value(sec[k])}" for k in ("E", "F", "G", "H")),
        "H0": js_value(sec["H"]),
        "cover": indent([f'gsap.set("{c}", {js_vars(v)});' for c, v in data["cover"].items()]),
        "hidden": indent(["gsap.set([" + (",\n" + "    ").join(", ".join(json.dumps(x, ensure_ascii=False) for x in ln) for ln in data["hidden"])
                          + ', "#credit", "#logo"], { opacity: 0 });']),
        "pill_from": indent([f'gsap.set("#p{i}", {js_vars(v)});' for i, v in enumerate(data["pill_from"], 1)]),
        "cues_H": indent([ln for c in data["cues"]["H"] for ln in cue_lines(c)]),
    }
    for k in SECTIONS:
        rep[f"cues_{k}"] = indent([ln for c in data["cues"][k] for ln in cue_lines(c)])

    def sub(m):
        key = m.group(1)
        if key.startswith("cam:"):
            return rep["cams"][key[4:]]
        return str(rep[key])
    return re.sub(r"\{\{([a-zA-Z0-9_:\-]+)\}\}", sub, s)


def render_index(data):
    s = INDEX_TEMPLATE.read_text(encoding="utf-8")
    return s.replace("{{title}}", data["title"]).replace("{{duration}}", js_value(data["duration"]))


# ---- 素材

def make_mask(path, spec):
    """多角形（写真の座標）を塗ってから、縁を 2px 内へ縮めてぼかす（試作 make_final_h2.py の mug_mask と同じ）。"""
    m = Image.new("L", (1440, 2160), 0)
    d = ImageDraw.Draw(m)
    for poly in spec["polygons"]:
        d.polygon([tuple(p) for p in poly["points"]], fill=poly["fill"])
    m = m.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.GaussianBlur(3))
    rgba = Image.new("RGBA", (1440, 2160), (255, 255, 255, 0))
    rgba.putalpha(m)
    rgba.save(path)


def make_logo(src, dst):
    """ロゴの素材（白い地に丸いバッジ）から円の外を透明にし、表示の2倍の解像度で書く（試作 make_final_h2b.py の make_logo と同じ）。"""
    im = Image.open(src).convert("RGB")
    a = np.asarray(im).astype(np.int32)
    ink = (255 - a).max(axis=2) > 12
    ys, xs = np.where(ink)
    x0, x1 = xs.min(), xs.max()
    cx, cy, r = (x0 + x1) / 2, (im.size[1] - 1) / 2, (x1 - x0) / 2
    rc = r - 2.5  # 円の縁の白いにじみを残さないよう 2.5px 内側で切る
    k = 4  # 4倍で描いて縮める（縁のなめらかさ）
    w, h = im.size
    m = Image.new("L", (w * k, h * k), 0)
    ImageDraw.Draw(m).ellipse([(cx - rc) * k, (cy - rc) * k, (cx + rc) * k, (cy + rc) * k], fill=255)
    m = m.resize((w, h), Image.LANCZOS)
    rgba = im.convert("RGBA")
    rgba.putalpha(m)
    side = int(np.ceil(rc)) + 1
    rgba = rgba.crop((round(cx) - side, round(cy) - side, round(cx) + side, round(cy) + side))
    rgba = rgba.resize((LOGO_D * 2, LOGO_D * 2), Image.LANCZOS)
    rgba.save(dst)


def load_data(d):
    """動画フォルダの video-N.film.json（1本だけ）を読む。返り値: (パス, データ)"""
    found = sorted(d.glob("video-*.film.json"))
    if len(found) != 1:
        raise SystemExit(f"video-N.film.json が1本ではない: {d}（{len(found)}本）")
    return found[0], json.loads(found[0].read_text(encoding="utf-8"))


def build(d, rt):
    """composition/ を組み直す（.hyperframes/ は残す。書き出しの履歴の id を変えないため）。返り値: composition のパス"""
    _, data = load_data(d)
    # 尺は声の時刻表（work/timeline.json）が正本。film.json には書かない（TAIL を変えても手で合わせ直さなくて済むように）
    data = {**data, "duration": json.loads((d / "work" / "timeline.json").read_text(encoding="utf-8"))["duration"]}
    comp = d / "composition"
    comp.mkdir(exist_ok=True)
    for p in comp.iterdir():
        if p.name == ".hyperframes":
            continue
        shutil.rmtree(p) if p.is_dir() else p.unlink()
    for sub in ("compositions", "assets/img", "assets/fonts", "assets/brand"):
        (comp / sub).mkdir(parents=True, exist_ok=True)
    for cam in CAMS:
        p = data["photos"][cam]
        shutil.copyfile(d / "work" / "img" / f'{p["src"]}.jpg', comp / "assets" / "img" / p["file"])
    for name, spec in data.get("masks", {}).items():
        make_mask(comp / "assets" / "img" / name, spec)
    make_logo(rt.asset("logo"), comp / "assets" / "brand" / "badge-circle.png")
    for name in ("font_sans", "font_serif", "font_head_bold", "font_head_semibold"):
        shutil.copyfile(rt.asset(name), comp / "assets" / "fonts" / Path(rt.asset(name)).name)
    shutil.copyfile(rt.asset("gsap"), comp / "gsap.min.js")
    shutil.copyfile(d / "work" / "narration.wav", comp / "assets" / "narration.wav")
    # 改行は CRLF に固定（試作の film.html・index.html と同じ。動かす機械で変わらないように）
    (comp / "compositions" / "film.html").write_text(render_film(data), encoding="utf-8", newline="\r\n")
    (comp / "index.html").write_text(render_index(data), encoding="utf-8", newline="\r\n")
    return comp
