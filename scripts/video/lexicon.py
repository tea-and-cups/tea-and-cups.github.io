"""声の入力の読み替え（例外表）。漢字のまま入力し、読み違える語だけをここで直す（2026-10-28 (b)・窓口指示）。
共通の例外表 data/video-lexicon.json に、記事ごとの例外（video-N.film.json の lexicon 欄。film.json がまだ無ければ script.json の lexicon）を重ねる。
同じ語は記事ごとの表が勝つ。長い語から順に置換する。文に voice_override があればそれを使う（作った声の入力を固定したいとき）。
読み違いは耳（Sho）か、asr の不一致（点検の入口だけ・合否には使わない）で見つけ、見つけた語だけを表へ足す。"""
import json
import os

from video.runtime import PROJECT_ROOT

COMMON = os.path.join(PROJECT_ROOT, "data", "video-lexicon.json")


def article_entries(d):
    """記事ごとの例外 [[語, 読み], …]。video-N.film.json の lexicon、無ければ script.json の lexicon。"""
    found = sorted(d.glob("video-*.film.json"))
    if found:
        film = json.loads(found[0].read_text(encoding="utf-8"))
        if "lexicon" in film:
            return film["lexicon"]
    sc = d / "script.json"
    return json.loads(sc.read_text(encoding="utf-8")).get("lexicon", []) if sc.exists() else []


def merged_lexicon(d):
    """共通の表＋記事ごとの表（同じ語は記事ごとの表が勝つ）。d は動画フォルダ。"""
    with open(COMMON, encoding="utf-8") as fp:
        lex = dict(json.load(fp)["entries"])
    lex.update(dict(article_entries(d)))
    return [[k, v] for k, v in lex.items()]


def voice_text(sent, lexicon):
    if sent.get("voice_override"):
        return sent["voice_override"]
    text = "".join(sent["phrases"])
    for src, dst in sorted(lexicon, key=lambda kv: -len(kv[0])):
        text = text.replace(src, dst)
    return text


def applied(sent, lexicon):
    """この文に当たった例外（点検用）。「語→読み」を ; で並べる。voice_override の文は 'override'。"""
    if sent.get("voice_override"):
        return "override"
    text = "".join(sent["phrases"])
    hit = []
    for src, dst in sorted(lexicon, key=lambda kv: -len(kv[0])):
        if src in text:
            hit.append(f"{src}→{dst}")
            text = text.replace(src, dst)
    return ";".join(hit)
