# -*- coding: utf-8 -*-
r"""docs/ideas.md の「## ストック」節から記事化済み行を「## 使用済み・見送り」節へ
機械的に退避する（D-0105）。

背景: ideas.mdの「一言メモ」欄は更新責任者・更新タイミングの規定を持たないまま
第二の進捗台帳として機能し、記事の実態（frontmatterのstatus）と乖離していた。
本スクリプトは進捗情報を残さず「このslugは記事化済みで在庫から外れた」という
事実のみを機械的に記録することで、ideas.mdを「未着手の題材在庫リスト」に純化する。

判定方法:
  「## ストック」節の各行について、以下のいずれかに一致すれば記事化済みとみなし
  「## 使用済み・見送り」節へ移動する（OR条件・D-0218/L010）。

  (a) slug一致: 行内に site/src/content/posts/ 配下に実在するslug（ファイル名
      から拡張子を除いたもの）が部分一致で含まれている。

      1行に複数のslugが部分一致することがある（例: 自分自身のslugに加えて、
      本文中で別記事への内部リンクとして他のslugへ言及している場合）。この場合、
      全角/半角の開き括弧に直後続くslugを自分自身のslugとして優先する。この
      リポジトリの記法では自分自身のslugは「（slug・category: xxx）」のように
      括弧直後に書かれ、他記事への言及は「既存記事slugへ」のように括弧を伴わずに
      書かれるため。

  (b) タイトル一致: 行の1番目のフィールド（タイトル）を正規化した文字列が、
      公開済み記事のfrontmatter titleを正規化した文字列と完全一致する。
      正規化はUnicode NFKC（全角/半角統一）＋空白除去のみ行い、部分一致・
      類似度判定は行わない（誤検出でネタ帳が勝手に減る方が損害が大きいため）。
      slugをネタ帳行に書き足さなくても検出できるようにするための経路。

  (a)(b)いずれの経路も、行が「- [ ]」または「- [x]」のいずれか（チェックボックス
      付きのストック行であること）を条件とし、チェックボックスの状態（[ ]/[x]）
      そのものは判定に使わない（D-0219/L010再発）。公開済み記事と一致した時点で
      その題材は消費済みであり、チェック付け忘れという人手の作業に判定を依存させ
      ない設計にするため。一致しない行はチェック状態にかかわらず退避されない。

移動時の変換:
  タイトル・種別・狙い・追加日の各フィールドは維持し、一言メモフィールド（進捗の
  経緯・状態）は削除する。行末に「| 記事化済み（<slug>）」を追記する。

件数上限:
  「## 使用済み・見送り」節は最新10件のみを保持する（定数上限型）。既存の使用済み
  行 + 新規移動行を結合し、超過分は行が持つ日付（4番目のフィールド）の古い方から
  削除する。行の位置では判定しない（手動退避が先頭へ挿入されるため、位置で判定すると
  最新行から消えてしまう・D-0203）。日付が読めない行は削除対象にせず残す。

使い方:
  python site/scripts/prune-used-ideas.py [--dry-run]

--dry-run 指定時は変更を書き込まず、移動対象行・削除対象行を一覧表示するのみ。
"""

import glob
import io
import os
import re
import sys
import unicodedata

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


def normalize_title(text):
    """タイトル一致判定用の正規化。NFKC（全角/半角統一）＋空白除去のみ行う。"""
    return "".join(unicodedata.normalize("NFKC", text).split())


def read_frontmatter_title(path):
    """記事ファイルのfrontmatterからtitleフィールドを読む。無ければNone。"""
    text = read_text(path)
    match = re.search(r'^title:\s*(.+)$', text, re.MULTILINE)
    if not match:
        return None
    return match.group(1).strip().strip('"').strip("'")


def collect_slug_titles():
    """正規化済みtitle -> slug の辞書を返す。"""
    titles = {}
    for path in glob.glob(os.path.join(POSTS_DIR, "*.md")):
        slug = os.path.splitext(os.path.basename(path))[0]
        title = read_frontmatter_title(path)
        if title:
            titles[normalize_title(title)] = slug
    return titles


def find_own_title_slug(line, title_map):
    """行の1番目のフィールド（タイトル）を正規化し、記事titleと完全一致すれば
    そのslugを返す。一致が無ければNoneを返す。判定方法はモジュールdocstring参照。
    """
    stripped = line.strip()
    body = stripped[5:].strip()
    title_field = body.split(" | ", 1)[0].strip()
    return title_map.get(normalize_title(title_field))


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

    冪等性: 既に「記事化済み（<slug>）」で終わっている行（＝退避済みの行）は
    変換せずそのまま返す。再処理すると4番目のフィールド（退避済み行では日付欄）を
    削ってしまい、日付を失うため（実際に meissen 行で発生した・D-0203）。
    """
    if line.rstrip().endswith(u"）") and u"| 記事化済み（" in line:
        return line.rstrip()
    parts = [p.strip() for p in line.split(" | ")]
    if len(parts) >= 5:
        del parts[3]
        rebuilt = " | ".join(parts)
    else:
        rebuilt = line.rstrip()
    return rebuilt + u" | 記事化済み（%s）" % slug


def used_line_date(line):
    """使用済み行の4番目のフィールド（YYYY-MM-DD）を返す。日付でなければNone。"""
    parts = [p.strip() for p in line.split(" | ")]
    if len(parts) < 4:
        return None
    value = parts[3]
    if len(value) == 10 and value[4] == "-" and value[7] == "-":
        head = value[:4] + value[5:7] + value[8:]
        if head.isdigit():
            return value
    return None


def select_drop_indexes(used_lines):
    """USED_KEEP を超えた分の削除対象を、行の位置ではなく行が持つ日付で選ぶ。

    背景: 従来は先頭側（combined_used[:overflow]）を捨てていたが、手動退避は
    「## 使用済み・見送り」見出しの直後（＝先頭）へ挿入されてきたため、
    最新の退避行から消える挙動になっていた（実測確定・D-0203）。

    日付が同着の場合はファイル内の出現順で先に現れる方を先に削除する。
    sorted() は安定ソートであり、ここでは日付のみをキーにしているため、
    同着行の相対順序＝元の出現順が保たれることでこの要件を満たす。

    日付がパースできない行は削除対象に含めない（残す）。その結果として
    保持件数が USED_KEEP を超えることは許容する（上限超過は無害だが、
    判定不能な行を消すとデータが失われるため）。
    """
    overflow = len(used_lines) - USED_KEEP
    if overflow <= 0:
        return set()
    datable = [(i, used_line_date(l)) for i, l in enumerate(used_lines)]
    datable = [(i, d) for i, d in datable if d is not None]
    datable.sort(key=lambda pair: pair[1])
    return set(i for i, _ in datable[:overflow])


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
    title_map = collect_slug_titles()
    text = read_text(IDEAS_MD)
    lines = text.split("\n")
    stock_start, stock_end, used_start, used_end = split_sections(lines)

    stock_lines = lines[stock_start + 1:stock_end]
    to_move = []
    kept_stock_lines = []
    for line in stock_lines:
        stripped = line.strip()
        # チェックボックス付きのストック行（[ ]/[x]どちらでも）を対象にする。
        # チェック状態は判定に使わない（D-0219）。slug/タイトルが一致しない限り
        # 退避されないため、他記事への言及（例:「既存の◯◯記事(slug)とは別に」）
        # だけでは誤って退避されない。
        if stripped[:5].lower() in ("- [x]", "- [ ]"):
            slug = find_own_slug(line, slugs) or find_own_title_slug(line, title_map)
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
    drop_indexes = select_drop_indexes(combined_used)
    dropped = [(combined_used[i], used_line_date(combined_used[i])) for i in drop_indexes]
    if drop_indexes:
        combined_used = [
            l for i, l in enumerate(combined_used) if i not in drop_indexes
        ]

    if dry_run:
        print(u"=== 移動対象（ストック → 使用済み・見送り）: %d件 ===" % len(to_move))
        for line, slug in to_move:
            print(u"  slug=%s : %s" % (slug, line.strip()))
        if dropped:
            print(u"=== 使用済み節から10件超過のため削除される行: %d件 ===" % len(dropped))
            for line, day in dropped:
                print(u"  日付=%s : %s" % (day, line.strip()))
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
