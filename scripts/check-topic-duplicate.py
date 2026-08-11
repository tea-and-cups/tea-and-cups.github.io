"""公開済み記事との題材重複を機械的に検査する（D-0104）。

背景: docs/ideas.md の「一言メモ」欄が実態と乖離した進捗情報を持ったままになり、
それを根拠に公開済み記事と同じ題材で新規記事の執筆に着手する事故が発生した
（2026-08-11・silverweek-suitou-tea-tumbler-hikaku）。本スクリプトは ideas.md には
一切依存せず、site/src/content/posts/ 配下の実ファイルのみを正とし、候補の
slug・タイトルが既存の公開済み記事と重複・類似していないかを判定する。

使い方:
  python site/scripts/check-topic-duplicate.py "<候補slugまたはタイトル>" ["<候補2>" ...]

判定:
  - 候補文字列が既存slugのいずれかと完全一致            -> DUPLICATE
  - 正規化後タイトルが既存タイトルのいずれかと完全一致    -> DUPLICATE
  - 正規化後タイトルの文字bigram Jaccard係数が既存タイトルの
    いずれかと0.6以上                                    -> SIMILAR
  - いずれにも該当しない                                  -> OK

正規化: Unicode NFKC正規化 -> 小文字化 -> 空白（半角・全角）と記号類
  （・ | ｜ （ ） ( ) 【 】 「 」 - ー 〜 ~）を除去

終了コード: DUPLICATE が1件でもあれば2、それ以外（SIMILAR/OK混在含む）は0。
読み取り専用。いかなるファイルも書き換えない。
"""

import os
import re
import sys
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POSTS_DIR = os.path.join(ROOT, "site", "src", "content", "posts")

STRIP_CHARS_RE = re.compile(
    r"[\s　・|｜（）()【】「」\-ー〜~]+"
)


def normalize(text):
    """NFKC正規化 -> 小文字化 -> 空白/記号除去"""
    if text is None:
        return ""
    t = unicodedata.normalize("NFKC", text)
    t = t.lower()
    t = STRIP_CHARS_RE.sub("", t)
    return t


def char_bigrams(text):
    if len(text) < 2:
        return {text} if text else set()
    return {text[i:i + 2] for i in range(len(text) - 1)}


def jaccard(a, b):
    set_a = char_bigrams(a)
    set_b = char_bigrams(b)
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    return inter / union if union else 0.0


def split_frontmatter(text):
    m = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
    if not m:
        return {}
    fm_text = m.group(1)
    data = {}
    for line in fm_text.splitlines():
        m2 = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if m2:
            key = m2.group(1)
            val = m2.group(2).strip()
            # クオート除去（簡易）
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            data[key] = val
    return data


def load_existing_posts():
    """(slug, title, norm_title) のリストを返す"""
    posts = []
    if not os.path.isdir(POSTS_DIR):
        return posts
    for fname in sorted(os.listdir(POSTS_DIR)):
        if not fname.endswith(".md"):
            continue
        slug = fname[:-3]
        path = os.path.join(POSTS_DIR, fname)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        fm = split_frontmatter(text)
        title = fm.get("title", "")
        posts.append((slug, title, normalize(title)))
    return posts


def judge_candidate(candidate, posts):
    """候補1件を判定し、(level, message_lines) を返す。level: DUPLICATE/SIMILAR/OK"""
    norm_candidate = normalize(candidate)
    lines = []

    # slug完全一致
    for slug, title, norm_title in posts:
        if candidate == slug:
            lines.append(
                f"DUPLICATE: {candidate} → 既存記事 {slug}「{title}」（slug完全一致）"
            )
            return "DUPLICATE", lines

    # タイトル完全一致
    for slug, title, norm_title in posts:
        if norm_candidate and norm_candidate == norm_title:
            lines.append(
                f"DUPLICATE: {candidate} → 既存記事 {slug}「{title}」（タイトル完全一致）"
            )
            return "DUPLICATE", lines

    # 類似度判定
    best_slug = None
    best_title = None
    best_score = 0.0
    for slug, title, norm_title in posts:
        if not norm_candidate or not norm_title:
            continue
        score = jaccard(norm_candidate, norm_title)
        if score > best_score:
            best_score = score
            best_slug = slug
            best_title = title

    if best_score >= 0.6:
        lines.append(
            f"SIMILAR: {candidate} → 既存記事 {best_slug}「{best_title}」"
            f"（タイトル類似度Jaccard={best_score:.2f}）"
        )
        return "SIMILAR", lines

    lines.append(f"OK: {candidate}")
    return "OK", lines


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    candidates = sys.argv[1:]
    posts = load_existing_posts()

    levels = []
    for candidate in candidates:
        level, lines = judge_candidate(candidate, posts)
        levels.append(level)
        for line in lines:
            print(line)

    if "DUPLICATE" in levels:
        overall = "DUPLICATE"
    elif "SIMILAR" in levels:
        overall = "SIMILAR"
    else:
        overall = "OK"

    print(f"RESULT: {overall}")
    sys.exit(2 if overall == "DUPLICATE" else 0)


if __name__ == "__main__":
    main()
