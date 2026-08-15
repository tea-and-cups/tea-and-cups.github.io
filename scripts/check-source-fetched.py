# -*- coding: utf-8 -*-
"""記事に書かれた出典URLが、実際にWebFetchした記録に存在するかを照合する（D-0133）。

出典の妥当性をAIの自己申告に委ねる限り、実際に見ていないURLを出典として
書くことを防げない。data/webfetch-log.md（record-webfetch.py が
PostToolUse フックで自動記録）と突き合わせ、台帳に無いURLがあれば公開を止める。

【照合の対象外】
  ・af.moshimo.com のURL（アフィリエイトリンクであり出典ではない）
  ・記事の date が台帳の「記録開始日」より前のもの（記録が存在しない期間のため）
  ・台帳が存在しない場合（照合できないことを表示して通す）

【照合の粒度】
  ホスト＋パスで比較する。末尾スラッシュ・クエリ・フラグメント・
  大文字小文字・先頭 www. の違いでは不一致にしない。

【この照合が保証しないこと】
  台帳は直近14日分しか保持しない。記録開始日以降の記事であっても、
  保持期間を超えた過去に取得したURLは台帳から消えているため違反として出る。
  その場合は該当URLを取り直せば解消する（取り直せないURLは出典に使えない）。

使い方:
  python site/scripts/check-source-fetched.py <slug>

終了コード: OK=0 / 台帳に無いURLあり=1
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POSTS_DIR = os.path.join(ROOT, "site", "src", "content", "posts")
DRAFTS_DIR = os.path.join(ROOT, "output", "articles")
LOG_PATH = os.path.join(ROOT, "data", "webfetch-log.md")

RE_URL = re.compile(r"https?://[^\s\)\]\>\"'　]+")
RE_AFFILIATE = re.compile(r"^https?://(?:[\w.-]+\.)?af\.moshimo\.com", re.IGNORECASE)

RE_LOG_ENTRY = re.compile(r"^- (\d{4}-\d{2}-\d{2}) \| (\S+) \| (\S*)\s*$")
RE_LOG_START = re.compile(r"^記録開始日:\s*(\d{4}-\d{2}-\d{2})\s*$", re.M)
RE_DATE_LINE = re.compile(r"^date:\s*(\d{4}-\d{2}-\d{2})", re.M)


def io_read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def split_frontmatter(text):
    m = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n(.*)\Z", text, re.S)
    if not m:
        return "", text
    return m.group(1), m.group(2)


def strip_code_blocks(body):
    out = []
    in_code = False
    for line in body.splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if not in_code:
            out.append(line)
    return "\n".join(out)


def normalize(url):
    """ホスト＋パスへ正規化する。末尾スラッシュ・クエリ・大小文字の差を吸収する。"""
    stripped = re.sub(r"^https?://", "", url.strip(), flags=re.IGNORECASE)
    stripped = re.split(r"[?#]", stripped, 1)[0]
    stripped = stripped.rstrip("/")
    stripped = re.sub(r"[.,、。」）\)]+$", "", stripped)
    if "/" in stripped:
        host, path = stripped.split("/", 1)
        path = "/" + path
    else:
        host, path = stripped, ""
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    return host + path


def resolve_path(slug):
    draft = os.path.join(DRAFTS_DIR, "%s.md" % slug)
    if os.path.isfile(draft):
        return draft
    published = os.path.join(POSTS_DIR, "%s.md" % slug)
    if os.path.isfile(published):
        return published
    return None


def load_log():
    """(記録開始日, 正規化済みURL集合) を返す。台帳が無ければ (None, None)。"""
    if not os.path.isfile(LOG_PATH):
        return None, None
    text = io_read(LOG_PATH)
    m = RE_LOG_START.search(text)
    start = m.group(1) if m else None
    fetched = set()
    for line in text.splitlines():
        entry = RE_LOG_ENTRY.match(line)
        if entry:
            fetched.add(normalize(entry.group(2)))
    return start, fetched


def article_urls(body):
    """本文中のURLを、出現順・重複なしで返す（af.moshimo.com は除く）。"""
    urls = []
    seen = set()
    for raw in RE_URL.findall(strip_code_blocks(body)):
        url = raw.rstrip(".,、。")
        if RE_AFFILIATE.match(url):
            continue
        key = normalize(url)
        if key in seen:
            continue
        seen.add(key)
        urls.append(url)
    return urls


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) != 2:
        print(__doc__)
        return 1

    slug = sys.argv[1]
    path = resolve_path(slug)
    if path is None:
        print("見つかりません: output/articles/%s.md / site/src/content/posts/%s.md" % (slug, slug))
        return 1

    start_date, fetched = load_log()
    if fetched is None:
        print("SOURCE_FETCHED_SKIP（data/webfetch-log.md が無いため照合できません）")
        return 0
    if start_date is None:
        print("SOURCE_FETCHED_SKIP（data/webfetch-log.md に記録開始日の行が無いため照合できません）")
        return 0

    text = io_read(path)
    front, body = split_frontmatter(text)
    date_m = RE_DATE_LINE.search(front)
    article_date = date_m.group(1) if date_m else None

    if article_date is not None and article_date < start_date:
        print(
            "SOURCE_FETCHED_SKIP（記事の日付 %s が記録開始日 %s より前のため照合対象外）"
            % (article_date, start_date)
        )
        return 0

    urls = article_urls(body)
    missing = [u for u in urls if normalize(u) not in fetched]

    if not missing:
        print("SOURCE_FETCHED_OK（照合対象 %d件・記録開始日 %s）" % (len(urls), start_date))
        return 0

    print("WebFetchの記録に無いURL: %d件 / 照合対象 %d件" % (len(missing), len(urls)))
    for url in missing:
        print("  %s" % url)
    print("")
    print("対処: 出典として使うURLは実際にWebFetchしてから記事に書く。")
    print("      台帳（data/webfetch-log.md）は直近14日分のみ保持するため、")
    print("      それ以前に取得したURLは取り直すと解消する。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
