"""声の入力の読み替え（試作 make_voice_jobs.py の 22〜41行を移したもの。方式は変えない）。
共通の表 data/video-lexicon.json に、台本（script.json）の lexicon（記事ごとの表）を重ねる。同じ語は記事ごとの表が勝つ。
長い語から順に置換する。文に voice_override があればそれを使う。"""
import json
import os
import re

from video.runtime import PROJECT_ROOT

COMMON = os.path.join(PROJECT_ROOT, "data", "video-lexicon.json")


def merged_lexicon(sc):
    """共通の表＋記事ごとの表（同じ語は記事ごとの表が勝つ）。"""
    with open(COMMON, encoding="utf-8") as fp:
        lex = dict(json.load(fp)["entries"])
    lex.update(dict(sc.get("lexicon", [])))
    return [[k, v] for k, v in lex.items()]


def kanji_left(text):
    return "".join(re.findall(r"[一-鿿々]", text))


def voice_text(sent, lexicon):
    if sent.get("voice_override"):
        return sent["voice_override"]
    text = "".join(sent["phrases"])
    for src, dst in sorted(lexicon, key=lambda kv: -len(kv[0])):
        text = text.replace(src, dst)
    return text
