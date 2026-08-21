# -*- coding: utf-8 -*-
r"""記事内のページ内リンク（#見出しID）が実際に生成される見出しIDと一致するかを
機械チェックする（公開前チェックの1本）。

【背景】
比較記事の比較早見表から詳細セクションへのページ内リンクが、実際に生成される
見出しIDと一致しない事象が2026-08-16/17/18の3記事で連続発生した。検出が
quality-reviewer の都度の手作業実測に依存していたため、機械的な停止条件にする。

【見出しIDの生成元】
site/astro.config.mjs が @astrojs/markdown-remark の rehypeHeadingIds を使用しており、
その実装（site/node_modules/@astrojs/markdown-remark/dist/rehype-collect-headings.js）は
github-slugger の同一インスタンスで文書順に slug() を適用し、末尾の "-" を1つ除去する。
本スクリプトはスラッグ生成規則をPython側で再実装せず、記事1本につき1回だけ node を
起動して本物の github-slugger を呼ぶ（規則の二重実装を避けるため）。

【判定】
  対象: frontmatter とコードフェンス（```）内を除いた本文
  停止: 見出しに「**」「[」「`」が含まれる場合（IDの予測が未実測のため不合格にする）
  停止: astro.config.mjs に experimentalHeadingIdCompat がある場合（末尾"-"除去の前提が崩れる）
  不合格: 本文中の Markdown リンク `](#...)` の指すIDが、本文の見出しIDに存在しない場合のみ
  「見出しはあるがリンクが無い」は不合格にしない。記事の型による分岐は持たない
  （ページ内リンクが無い記事は自動的に合格になる）。

使い方:
  python site/scripts/check-anchor-consistency.py <slug>

終了コード: 0=OK（不一致0件、またはページ内リンク0件） / 1=不一致あり、または実行不能
"""

import json
import os
import re
import subprocess
import sys
from urllib.parse import unquote

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DRAFTS_DIR = os.path.join(ROOT, "output", "articles")
POSTS_DIR = os.path.join(ROOT, "site", "src", "content", "posts")
SLUGGER_ENTRY = os.path.join(ROOT, "site", "node_modules", "github-slugger", "index.js")
ASTRO_CONFIG = os.path.join(ROOT, "site", "astro.config.mjs")

NODE_TIMEOUT = 60

RE_FRONTMATTER = re.compile(r"\A---\r?\n(.*?\r?\n)---[ \t]*\r?\n", re.S)
RE_FENCE = re.compile(r"^\s{0,3}```")
RE_HEADING = re.compile(r"^(#{1,6}) +(.+?)\s*$")
# Markdown リンクのうち、リンク先が # で始まるものだけ（外部リンクは対象外）
RE_ANCHOR_LINK = re.compile(r"\[([^\]\[]*)\]\(\s*#([^)\s\"']*)")
# 見出しに使われていた場合にIDの予測が保証できないインライン記法。
# 「*」「_」の単体は日本語の見出しで誤検知しうるため対象に含めない。
RE_HEADING_INLINE_MARKUP = re.compile(r"\*\*|\[|`")

# github-slugger を同一インスタンスで文書順に適用し、Astro と同じ末尾"-"除去を行う。
NODE_SCRIPT = r"""
let raw = '';
process.stdin.setEncoding('utf8');
for await (const chunk of process.stdin) raw += chunk;
const input = JSON.parse(raw);
const mod = await import(input.sluggerUrl);
const Slugger = mod.default;
const slugger = new Slugger();
const ids = input.headings.map((text) => {
  let slug = slugger.slug(text);
  if (slug.endsWith('-')) slug = slug.slice(0, -1);
  return slug;
});
process.stdout.write(JSON.stringify(ids));
"""


def out(text=""):
    print(text)


def resolve_path(slug):
    draft = os.path.join(DRAFTS_DIR, "%s.md" % slug)
    if os.path.isfile(draft):
        return draft
    published = os.path.join(POSTS_DIR, "%s.md" % slug)
    if os.path.isfile(published):
        return published
    return None


def io_read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def body_lines(text):
    """frontmatter を除いた本文を [(元ファイルの行番号, 行), ...] で返す。"""
    m = RE_FRONTMATTER.match(text)
    offset = 0
    if m:
        offset = text[: m.end()].count("\n")
        text = text[m.end() :]
    return [(i + offset + 1, line) for i, line in enumerate(text.split("\n"))]


def strip_fences(lines):
    """コードフェンス内の行を除いた [(行番号, 行), ...] を返す。"""
    kept = []
    in_fence = False
    for lineno, line in lines:
        if RE_FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        kept.append((lineno, line))
    return kept


def find_markup_headings(lines):
    """インライン記法を含む見出しを [(行番号, 見出し行の原文), ...] で返す。

    heading_text() で記法を除去した後では検出できないため、必ず除去より前に呼ぶ。
    """
    result = []
    for lineno, line in lines:
        m = RE_HEADING.match(line)
        if m and RE_HEADING_INLINE_MARKUP.search(m.group(2)):
            result.append((lineno, line.rstrip()))
    return result


def check_astro_config():
    """astro.config.mjs の見出しID設定を確認する。問題があれば理由（文字列）を返す。

    注意: ここで拾えるのは設定変更のみで、Astro本体のバージョン更新による
    見出しID生成規則の変更は拾えない。
    """
    try:
        source = io_read(ASTRO_CONFIG)
    except Exception as e:
        return "site/astro.config.mjs を読めませんでした: %s" % e
    if "experimentalHeadingIdCompat" in source:
        return "site/astro.config.mjs に experimentalHeadingIdCompat が指定されています"
    return None


def heading_text(raw):
    """見出し行のMarkdown記法を除き、レンダリング後のテキスト内容へ寄せる。

    rehypeHeadingIds はテキストノードのみを連結するため、強調・リンク等の記法文字は
    IDに影響しない。コードスパン（`...`）の中身はそのまま連結される。
    """
    parts = []
    for i, segment in enumerate(raw.split("`")):
        if i % 2 == 1:  # コードスパンの中身はそのまま
            parts.append(segment)
            continue
        s = segment
        s = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", s)  # 画像 → alt
        s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)  # リンク → テキスト
        s = s.replace("**", "").replace("__", "").replace("~~", "")
        s = s.replace("*", "")
        s = s.replace("{", "${")  # rehype-collect-headings の非コードテキストの扱い
        parts.append(s)
    return "".join(parts)


def collect_headings(lines):
    """[(行番号, 見出しテキスト), ...] を文書順で返す。"""
    result = []
    for lineno, line in lines:
        m = RE_HEADING.match(line)
        if m:
            result.append((lineno, heading_text(m.group(2))))
    return result


def collect_anchor_links(lines):
    """[(行番号, リンクテキスト, 指しているID), ...] を返す。"""
    result = []
    for lineno, line in lines:
        for m in RE_ANCHOR_LINK.finditer(line):
            target = unquote(m.group(2))
            result.append((lineno, m.group(1), target))
    return result


def slugify_all(texts):
    """github-slugger（本物）で文書順にIDへ変換する。失敗時は (None, 理由)。"""
    if not os.path.isfile(SLUGGER_ENTRY):
        return None, "site/node_modules/github-slugger が見つかりません（site で npm install が必要）"
    payload = json.dumps(
        {
            "sluggerUrl": "file:///" + SLUGGER_ENTRY.replace("\\", "/").lstrip("/"),
            "headings": texts,
        },
        ensure_ascii=False,
    )
    try:
        result = subprocess.run(
            ["node", "--input-type=module", "-e", NODE_SCRIPT],
            input=payload.encode("utf-8"),
            capture_output=True,
            timeout=NODE_TIMEOUT,
        )
    except FileNotFoundError:
        return None, "node コマンドが見つかりません"
    except subprocess.TimeoutExpired:
        return None, "node の実行がタイムアウトしました（%d秒）" % NODE_TIMEOUT
    except Exception as e:
        return None, "node の起動に失敗しました: %s" % e

    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        return None, "node が終了コード %d で失敗しました: %s" % (result.returncode, stderr)
    try:
        ids = json.loads(result.stdout.decode("utf-8", errors="replace"))
    except ValueError:
        return None, "node の出力をJSONとして読めませんでした"
    if not isinstance(ids, list) or len(ids) != len(texts):
        return None, "node の出力件数が見出し数と一致しません"
    return ids, None


def env_error(reason):
    out("環境エラー: %s" % reason)
    out("これは記事の問題ではなく実行環境の問題です。ページ内リンクの検証ができないため、")
    out("公開を通さずに中断します。環境を復旧してから再実行してください。")
    return 1


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) != 2:
        out("使い方: python site/scripts/check-anchor-consistency.py <slug>")
        return 1

    slug = sys.argv[1]
    path = resolve_path(slug)
    if path is None:
        out("見つかりません: output/articles/%s.md / site/src/content/posts/%s.md" % (slug, slug))
        return 1

    config_problem = check_astro_config()
    if config_problem is not None:
        out("見出しID設定: NG（%s）" % config_problem)
        out("見出しIDの生成規則が変わった可能性があるため、本スクリプトの末尾ハイフン除去処理")
        out("（slug が \"-\" で終わる場合に1つ除去する箇所）の見直しが必要です。")
        out("Astroの実際の挙動を実測し直してから公開してください。")
        return 1

    lines = strip_fences(body_lines(io_read(path)))

    markup_headings = find_markup_headings(lines)
    if markup_headings:
        out("見出しの記法: NG（%d件の見出しにインライン記法が含まれています）" % len(markup_headings))
        for lineno, raw in markup_headings:
            out("  %d行目: %s" % (lineno, raw))
        out("")
        out("Astroが生成するIDの予測と一致するか未実測のため、見出しはプレーンテキストで書いてください")
        out("（「**」「[」「`」を見出しに使わない）。")
        return 1

    links = collect_anchor_links(lines)
    if not links:
        out("ページ内リンク: OK（本文にページ内リンクはありません）")
        return 0

    headings = collect_headings(lines)
    ids, reason = slugify_all([text for _, text in headings])
    if ids is None:
        return env_error(reason)

    valid = set(ids)
    bad = [(lineno, text, target) for lineno, text, target in links if target not in valid]

    if not bad:
        out("ページ内リンク: OK（%d件すべて見出しIDと一致）" % len(links))
        return 0

    out("ページ内リンク: NG（%d件中 %d件が存在しない見出しIDを指しています）" % (len(links), len(bad)))
    for lineno, text, target in bad:
        out("  %d行目 / リンクテキスト: %s / 指しているID: #%s" % (lineno, text, target))
    out("")
    out("本文の全見出しID（正しいIDへ書き換える際の参照用）:")
    for (lineno, text), anchor_id in zip(headings, ids):
        out("  %d行目 #%s  ← %s" % (lineno, anchor_id, text))
    return 1


if __name__ == "__main__":
    sys.exit(main())
