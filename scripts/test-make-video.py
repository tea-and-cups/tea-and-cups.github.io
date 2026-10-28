# -*- coding: utf-8 -*-
r"""make-video.py の部品（site/scripts/video/）のテスト。読むだけ（一時フォルダにも書かない）。

1. cut_tail の守り: 語の間に間を置く読み（output/videos/_voice-candidates-2026-10-28/_full-sentence の B-1・A-1）で、
   守りあり（モーラ数 ÷ 9.0秒）なら最短の長さを下回らず、B-1 では守りが働くこと。守りなしの長さも比較のため出す。
   B-1 が 3.5秒以上残るか（2026-10-28 の (a) の完了条件5）は NOTE として出すだけ（9.0 の守りでは 2回まで削れて届かない。
   2回目の塊は −2.1dB で、止めるには (b) で決める −12dB の条件が要る。reports/2026-10-28-5.md）。
2. 合成した波形: 間を挟んだ短い語が末尾に並ぶ波形で、守りが削りを止め、印（guard）が立つこと。
3. 型テンプレート: output/videos/video-1/video-1.film.json を描いた film.html が、試作 final-H2b の film.html と一致すること
   （試作フォルダが無ければ飛ばす）。

使い方: python site/scripts/test-make-video.py
終了コード: 全件合格で0、1件でも不合格で1
"""
import json
import os
import sys
from pathlib import Path

import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from video import film, voice  # noqa: E402
from video.runtime import PROJECT_ROOT  # noqa: E402

ROOT = Path(PROJECT_ROOT)
CAND = ROOT / "output" / "videos" / "_voice-candidates-2026-10-28" / "_full-sentence"
F = ROOT / "output" / "videos" / "_trial-2026-10" / "planA-full-v2" / "final-H2b" / "composition" / "compositions" / "film.html"
VIDEO1 = ROOT / "output" / "videos" / "video-1" / "video-1.film.json"
# 声の入力（candidates.md の B-1・A-1 の句に、句 A・B の残りを合わせた文全体）
TEXTS = {"B-1": "えらぶかぎは、場面、手入れ、好み。", "A-1": "えらぶカギは、ばめん、ていれ、このみ。"}

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f"  {detail}" if detail else ""))


def test_candidates():
    for key, text in TEXTS.items():
        p = CAND / f"{key}-sentence-S3.wav"
        if not p.exists():
            print(f"SKIP {key}: {p} が無い")
            continue
        y0 = voice.trim(voice.load(p))
        min_len = voice.mora(text) / voice.MIN_MORA_PER_S
        y_old, _, drops_old, _ = voice.cut_tail(y0)
        y_new, cut, drops, flag = voice.cut_tail(y0, min_len)
        d0, d_old, d_new = len(y0) / voice.SR, len(y_old) / voice.SR, len(y_new) / voice.SR
        detail = (f"元 {d0:.2f}秒・守りなし {d_old:.2f}秒（{drops_old}回）・守りあり {d_new:.2f}秒（{drops}回・最短 {min_len:.2f}秒・"
                  f"守りで止めた {flag['guard']}・削った塊の最大 {flag['max_db']}）")
        check(f"{key} は守りありで最短の長さを下回らない", d_new >= min_len, detail)
        if key == "B-1":
            check(f"{key} は守りが働く", flag["guard"] == 1 and drops < drops_old)
            one = len(voice.cut_tail(y0, d_new + 0.01)[0]) / voice.SR  # 2回目を止めた場合（1回だけ削った長さ）
            print(f"NOTE {key} の 3.5秒以上: {'届く' if d_new >= 3.5 else '届かない'}（守りあり {d_new:.2f}秒・1回だけ削った場合 {one:.2f}秒）")


def test_synthetic():
    sr = voice.SR
    t = np.arange(int(0.35 * sr)) / sr
    word = 0.5 * np.sin(2 * np.pi * 220 * t)
    gap = np.zeros(int(0.3 * sr))
    # 長い句のあとに、0.3秒の間を挟んで 0.35秒の語が3つ（どれも規則①に当たる）
    y = np.concatenate([0.5 * np.sin(2 * np.pi * 220 * np.arange(int(1.0 * sr)) / sr), gap, word, gap, word, gap, word, np.zeros(int(0.1 * sr))])
    _, _, drops_old, _ = voice.cut_tail(y.copy())
    y_new, _, drops_new, flag = voice.cut_tail(y.copy(), min_len=2.0)
    check("合成: 守りなしでは末尾の語が削られる", drops_old >= 2, f"{drops_old}回")
    check("合成: 守りありでは最短 2.0秒を下回らず、印が立つ", len(y_new) / sr >= 2.0 and flag["guard"] == 1,
          f"{len(y_new) / sr:.2f}秒・{drops_new}回・guard={flag['guard']}")


def test_template():
    if not F.exists() or not VIDEO1.exists():
        print("SKIP 型テンプレート: 試作の film.html か video-1.film.json が無い")
        return
    got = film.render_film(json.loads(VIDEO1.read_text(encoding="utf-8")))
    want = F.read_text(encoding="utf-8")
    check("型テンプレート＋video-1.film.json が試作 final-H2b の film.html と一致", got == want)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    test_candidates()
    test_synthetic()
    test_template()
    print(f"{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
