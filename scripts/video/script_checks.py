"""台本（script.json）と画面のデータ（video-N.film.json）の検査（make-video.py の check-script と build の最初が呼ぶ）。
動画2の審査の指摘（要修正）と Sho の指摘（終わりの声かけが弱い）が、動画3以降で機械的に止まるようにする（D-0306）。
合格線（数値・語）の正本はこのファイルの定数。rules/video-production.md には値を書き写さず、場所だけを書く。

検査
  (a) 画面の字のうち声と同じ文言の割合が SAME_TEXT_MAX を超えない（film.json が要る）
      画面の字: rules.overlay_texts（章の札以外の字・指し方の札）＋章の札（pills）＋カバーの問いなど（kick・q・答え・導線の「記事で読む」）＋
      script.json の end（label・title。URL と AI表示は数えない）。1か所の字を1単位とし、単位ごとに「声と同じ」かどうかを決める。
      声と同じ＝空白・句読点・記号と助詞（PARTICLES）を除いた画面の字が、同じ処理をした声（全 sentences の phrases をつないだもの）に連続して含まれる。
      割合＝声と同じ単位の字数 ÷ 画面の字の全字数（字数は空白・句読点を除いた数）。動画2の最終版で 0.309（審査は「約30%」）、直す前で 0.577、動画1で 0.413
  (b) 声の最初の文が問いの形（？で終わる、または「か」「かな」「でしょうか」で終わる）
  (c) 終わりの声（最後の sentence）が規約の形（rules/video-production.md 5-2節）の機械で見られる部分を満たす
      文の数・字数の下限・「記事」を含む文（答えの文のあとにあり、一定の長さ）・最後の文が「リンク」を含む
  (d) ぼかしなどの効果に戻す手順の書き漏れが無い（film.json が要る）
      ・色調整のぼかし（--hf-color-grading-blur）が BLUR_STRONG 以上になる cue（寄り・指し方・書いた to/set）は、BLUR_HOLD_MAX 秒以内に
        同じ画像へ BLUR_STRONG 未満へ戻す cue が要る。写真の初期のぼかし（photos の blur）は、あとで戻す cue が1つは要る
      ・文字の filter: blur(…) は、fromTo の終わりが blur(0) か、to なら opacity 0 への消え方だけ
      露出（暗くする）の戻しは、場面ごとに戻す先が違うため対象外（見るのは目と qa）

対象は動画 NEW_CHECK_START 以降。それより前の動画は結果を INFO で出すだけで、止めない。
"""
import json
import re

NEW_CHECK_START = 3
SAME_TEXT_MAX = 0.30
PARTICLES = "はがをにでもへと"
CLOSING_MIN_SENTENCES = 3
CLOSING_MIN_CHARS = 36
CLOSING_ARTICLE_MIN_CHARS = 12
CLOSING_ARTICLE_WORD = "記事"
CLOSING_LINK_WORD = "リンク"
BLUR_STRONG = 0.5
BLUR_HOLD_MAX = 4.0

PUNCT = re.compile(r"[\s、。，．,.「」『』（）()・！？!?：:；;…～〜―｜|]")
SENTENCE_END = re.compile(r"(?<=[。？！?!])")
BLUR_CUE = re.compile(r'tl\.(?:to|set)\((\[[^\]]*\]|"[^"]+"), \{(.*?)\}, (.+?)\);')
BLUR_VALUE = re.compile(r'"--hf-color-grading-blur": ([-0-9.]+)')
FILTER_BLUR = re.compile(r"blur\(\s*([0-9.]+)")


def squash(s):
    return PUNCT.sub("", s)


def voice_sentences(phrases):
    """phrases をつないで文（。？！で区切る）に分ける。区切りの記号は文に残す。"""
    return [x for x in SENTENCE_END.split("".join(phrases)) if x.strip()]


# ---- (a) 画面の字と声の同文率

def screen_units(film_data, script):
    """画面の字の単位（1か所の字）。URL と AI表示は含めない。"""
    from video import film, rules
    texts = rules.overlay_texts(film_data, film.CREDIT)
    texts.pop("cta", None)
    units = list(texts.values())
    units.append(film_data["cta"].split("｜")[0])
    units += film_data.get("pills") or []
    end = script.get("end") or {}
    units.append(end.get("label") or "")
    units.append("".join(end.get("title") or []))
    return [u for u in units if squash(u)]


def same_text_ratio(film_data, script):
    """戻り値: (割合, 全字数, 声と同じ字数, 声と同じ単位の一覧)"""
    strip = re.compile("[%s]" % PARTICLES)
    voice = strip.sub("", squash("".join("".join(s["phrases"]) for s in script["sentences"])))
    total, same_chars, same = 0, 0, []
    for u in screen_units(film_data, script):
        n = len(squash(u))
        total += n
        core = strip.sub("", squash(u))
        if core and core in voice:
            same_chars += n
            same.append(squash(u))
    return (same_chars / total if total else 0.0), total, same_chars, same


# ---- (b) 声の最初の文

def is_question(sentence):
    s = sentence.strip()
    return s.endswith(("？", "?")) or bool(re.search(r"(か|かな|でしょうか)。?$", s))


def check_opening(script):
    sentences = script.get("sentences") or []
    if not sentences or not sentences[0].get("phrases"):
        return []
    first = voice_sentences(sentences[0]["phrases"])[0]
    if is_question(first):
        return []
    return [f"声の最初の文が問いの形ではない（？で終わる、または「か」「かな」「でしょうか」で終わる）: {first}"]


# ---- (c) 終わりの声

def check_closing(script):
    sentences = script.get("sentences") or []
    if not sentences or not sentences[-1].get("phrases"):
        return []
    last = sentences[-1]
    ss = voice_sentences(last["phrases"])
    total = len(squash("".join(ss)))
    ng = []
    if len(ss) < CLOSING_MIN_SENTENCES:
        ng.append(f"終わりの声（{last.get('id')}）が {len(ss)}文（{CLOSING_MIN_SENTENCES}文以上: 答え→記事に載っていること→リンクから）")
    if total < CLOSING_MIN_CHARS:
        ng.append(f"終わりの声（{last.get('id')}）が {total}字（{CLOSING_MIN_CHARS}字以上）")
    article = [i for i, x in enumerate(ss) if CLOSING_ARTICLE_WORD in x]
    link = [i for i, x in enumerate(ss) if CLOSING_LINK_WORD in x]
    if not article:
        ng.append(f"終わりの声に「{CLOSING_ARTICLE_WORD}」を含む文が無い（記事に何が載っているかを言う）")
    elif article[0] < 1:
        ng.append("終わりの声が、答えの文より前に「記事」を言っている（答えを1文でまとめてから記事を言う）")
    elif len(squash(ss[article[0]])) < CLOSING_ARTICLE_MIN_CHARS:
        ng.append(f"終わりの声の「記事」の文が短い（{CLOSING_ARTICLE_MIN_CHARS}字以上・見出しの言い直しで終わらない）: {ss[article[0]]}")
    if not link:
        ng.append(f"終わりの声に「{CLOSING_LINK_WORD}」を含む文が無い（行き方を言う）")
    else:
        if link[-1] != len(ss) - 1:
            ng.append("終わりの声の最後の文が行き方（リンクから）になっていない")
        if article and link[-1] <= article[0]:
            ng.append("終わりの声で、行き方（リンク）が記事に載っていることの文より前にある")
    return ng


# ---- (d) 戻す手順の書き漏れ

def blur_events(film_data):
    """色調整のぼかしの変化。{画像の selector: [(秒, 値, 由来)]}（時刻順）。cue は film.cue_lines が出す JS から読む。"""
    from video import film, rules
    consts = rules.constants(film_data)
    ev = {}
    for cam, p in film_data["photos"].items():
        if p.get("blur", 0):
            ev.setdefault(f"#{cam}-img", []).append((0.0, float(p["blur"]), "initial"))
    for sec in rules.letters(film_data):
        for cue in film_data["cues"][sec]:
            if isinstance(cue, str):
                continue
            for line in film.cue_lines(cue):
                m = BLUR_CUE.search(line)
                v = BLUR_VALUE.search(m.group(2)) if m else None
                if not v:
                    continue
                sels = json.loads(m.group(1))
                for s in sels if isinstance(sels, list) else [sels]:
                    if s.endswith("-img"):
                        ev.setdefault(s, []).append((rules.ev(m.group(3), consts), float(v.group(1)), json.dumps(cue, ensure_ascii=False)[:60]))
    return {k: sorted(v, key=lambda e: e[0]) for k, v in ev.items()}


def check_effects(film_data):
    ng = []
    for sel, events in blur_events(film_data).items():
        for i, (t, val, src) in enumerate(events):
            if val < BLUR_STRONG:
                continue
            later = [e for e in events[i + 1:] if e[1] < BLUR_STRONG]
            if src == "initial":
                if not later:
                    ng.append(f"{sel}: 初期のぼかし {val} を戻す cue が無い")
            elif not later or later[0][0] - t > BLUR_HOLD_MAX:
                when = f"{later[0][0] - t:.1f}秒後" if later else "最後まで"
                ng.append(f"{sel}: {t:.2f}秒に入れたぼかし {val} の戻しが {BLUR_HOLD_MAX}秒以内に無い（戻りは{when}・{src}）")
    from video import rules
    for sec in rules.letters(film_data):
        for cue in film_data["cues"][sec]:
            if isinstance(cue, str):
                continue
            v, frm =cue.get("v") or {}, cue.get("from") or {}
            if "fromTo" in cue and FILTER_BLUR.search(str(frm.get("filter", ""))):
                end = FILTER_BLUR.search(str(v.get("filter", "")))
                if not end or float(end.group(1)) > 0:
                    ng.append(f"{sec}: 文字の filter blur が 0 に戻らない fromTo: {json.dumps(cue, ensure_ascii=False)[:80]}")
            elif "to" in cue:
                b = FILTER_BLUR.search(str(v.get("filter", "")))
                if b and float(b.group(1)) > 0 and v.get("opacity") != 0:
                    ng.append(f"{sec}: 文字の filter blur を入れたまま消えない to: {json.dumps(cue, ensure_ascii=False)[:80]}")
    return ng


# ---- まとめ

def run(script, film_data, n):
    """戻り値: (NG の一覧, INFO の一覧)。n が NEW_CHECK_START 未満なら NG を INFO に回す（対象外）。"""
    found = check_opening(script) + check_closing(script)
    info = []
    if film_data is None:
        info.append("INFO film.json がまだ無いので、画面の字の同文率と戻し手順は film.json ができたあと（check-script の再実行・build の最初）に検査する")
    else:
        ratio, total, same_chars, same = same_text_ratio(film_data, script)
        info.append(f"INFO 画面の字と声の同文率 {ratio:.1%}（{same_chars}/{total}字・線 {SAME_TEXT_MAX:.0%}）")
        if ratio > SAME_TEXT_MAX:
            found.append(f"画面の字のうち声と同じ文言が {ratio:.1%}（{SAME_TEXT_MAX:.0%}以下）。声の言い換えに直す: {'・'.join(same)}")
        found += check_effects(film_data)
    if n < NEW_CHECK_START:
        return [], info + [f"INFO（動画{n}は対象外・動画{NEW_CHECK_START}以降） {m}" for m in found]
    return found, info
