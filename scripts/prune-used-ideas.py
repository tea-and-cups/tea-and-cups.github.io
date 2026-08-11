# -*- coding: utf-8 -*-
r"""docs/ideas.md の「## ストック」節から記事化済み行を「## 使用済み・見送り」節へ
機械的に退避する（D-0105）。

背景: ideas.mdの「一言メモ」欄は更新責任者・更新タイミングの規定を持たないまま
第二の進捗台帳として機能し、記事の実態（frontmatterのstatus）と乖離していた。
本スクリプトは進捗情報を残さず「このslugは記事化済みで在庫から外れた」という
事実のみを機械的に記録することで、ideas.mdを「未着手の題材在庫リスト」に純化する。

判定方法:
  「## ストック」節の各行について、行内に site/src/content/posts/ 配下に実在する
  slug（ファイル名から拡張子を除いたもの）が部分一致で含まれているかを判定する。
  含まれていれば、その行は記事化済みとみなし「## 使用済み・見送り」節へ移動する。

  1行に複数のslugが部分一致することがある（例: 自分自身のslugに加えて、本文中で
  別記事への内部リンクとして他のslugへ言及している場合）。この場合、全角/半角の
  開き括弧に直後続くslugを自分自身のslugとして優先する。このリポジトリの記法では
  自分自身のslugは「（slug・category: xxx）」のように括弧直後に書かれ、他記事への
  言及は「既存記事slugへ」のように括弧を伴わずに書かれるため。

移動時の変換:
  タイトル・種別・狙い・追加日の各フィールドは維持し、一言メモフィールド（進捗の
  経緯・状態）は削除する。行末に「| 記事化済み（<slug>）」を追記する。

件数上限:
  「## 使用済み・見送り」節は最新10件のみを保持する（定数上限型）。既存の使用済み
  行 + 新規移動行を結合し、超過分は古い方（リストの先頭側）から削除する。

使い方:
  python site/scripts/prune-used-ideas.py [--dry-run]

--dry-run 指定時は変更を書き込まず、移動対象行・削除対象行を一覧表示するのみ。
"""

import glob
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IDEAS_MD = os.path.join(ROOT, "docs", "ideas.md")
POSTS_DIR = os.path.join(ROOT, "site", "src", "content", "posts")

STOCK_HEADING = "## ストック"
USED_HEADING_PREFIX = "## 使用済み"
USED_KEEP = 10


def read_text(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_text(path, text):
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def collect_slugs():
    slugs = []
    for path in glob.glob(os.path.join(POSTS_DIR, "*.md")):
        slugs.append(os.path.splitext(os.path.basename(path))[0])
    return slugs


def find_own_slug(line, slugs):
    """行内に含まれるslugのうち、この行自身のslugと判定されるものを1つ返す。
    一致が無ければNoneを返す。判定方法はモジュールdocstring参照。
    """
    matches = [s for s in slugs if s in line]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    for s in matches:
        idx = line.find(s)
        if idx > 0 and line[idx - 1] in (u"（", "("):
            return s
    return matches[0]


def build_used_line(line, slug):
    """ストック行を使用済み行へ変換する。一言メモフィールド（4番目）は削除し、
    行末に「| 記事化済み（slug）」を追記する。
    """
    parts = [p.strip() for p in line.split(" | ")]
    if len(parts) >= 5:
        del parts[3]
        rebuilt = " | ".join(parts)
    else:
        rebuilt = line.rstrip()
    return rebuilt + u" | 記事化済み（%s）" % slug


def split_sections(lines):
    """(stock_start, stock_end, used_start, used_end) を行インデックスで返す。
    stock_start/used_start は見出し行そのもののインデックス。
    stock_end は「## ストック」節の直後に現れる最初の「## 」見出し行のインデックス
    （通常は使用済み見出し自身）。used_end はそれ以降で次に現れる「## 」見出し、
    無ければ len(lines)。
    """
    stock_start = None
    stock_end = None
    used_start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == STOCK_HEADING and stock_start is None:
            stock_start = i
            continue
        if stock_start is not None and stock_end is None and stripped.startswith("## "):
            stock_end = i
        if stripped.startswith(USED_HEADING_PREFIX) and used_start is None:
            used_start = i

    if stock_start is None:
        raise SystemExit(u"エラー: docs/ideas.md に「## ストック」節が見つかりません")
    if used_start is None:
        raise SystemExit(u"エラー: docs/ideas.md に「## 使用済み・見送り」節が見つかりません")
    if stock_end is None:
        stock_end = used_start

    used_end = len(lines)
    for i in range(used_start + 1, len(lines)):
        if lines[i].strip().startswith("## "):
            used_end = i
            break

    return stock_start, stock_end, used_start, used_end


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    dry_run = "--dry-run" in sys.argv[1:]

    slugs = collect_slugs()
    text = read_text(IDEAS_MD)
    lines = text.split("\n")
    stock_start, stock_end, used_start, used_end = split_sections(lines)

    stock_lines = lines[stock_start + 1:stock_end]
    to_move = []
    kept_stock_lines = []
    for line in stock_lines:
        stripped = line.strip()
        # [x]（着手済み）の行のみ移動対象にする。[ ]（未着手）の行は、他記事への
        # 差別化言及としてslug文字列を含むことがあり（例: 「既存の◯◯記事(slug)とは
        # 別に」）、それだけでは記事化済みと判定しない。
        if stripped[:5].lower() == "- [x]":
            slug = find_own_slug(line, slugs)
            if slug:
                to_move.append((line, slug))
                continue
        kept_stock_lines.append(line)

    existing_used_lines = [
        l for l in lines[used_start + 1:used_end] if l.strip().startswith("- [")
    ]
    other_used_lines = [
        l for l in lines[used_start + 1:used_end] if not l.strip().startswith("- [")
    ]

    new_used_entries = [build_used_line(line, slug) for line, slug in to_move]
    combined_used = existing_used_lines + new_used_entries
    dropped = []
    if len(combined_used) > USED_KEEP:
        overflow = len(combined_used) - USED_KEEP
        dropped = combined_used[:overflow]
        combined_used = combined_used[overflow:]

    if dry_run:
        print(u"=== 移動対象（ストック → 使用済み・見送り）: %d件 ===" % len(to_move))
        for line, slug in to_move:
            print(u"  slug=%s : %s" % (slug, line.strip()))
        if dropped:
            print(u"=== 使用済み節から10件超過のため削除される行: %d件 ===" % len(dropped))
            for line in dropped:
                print(u"  %s" % line.strip())
        else:
            print(u"使用済み節からの削除: なし（移動後 %d件で%d件以内）" % (len(combined_used), USED_KEEP))
        return

    if not to_move and not dropped:
        print(u"変更なし（移動対象・削除対象ともになし）")
        return

    new_lines = (
        lines[:stock_start + 1]
        + kept_stock_lines
        + lines[stock_end:used_start + 1]
        + other_used_lines
        + combined_used
        + lines[used_end:]
    )
    write_text(IDEAS_MD, "\n".join(new_lines))
    print(u"移動: %d件、使用済み節から削除: %d件、使用済み節の現在件数: %d件" % (
        len(to_move), len(dropped), len(combined_used)
    ))


if __name__ == "__main__":
    main()
