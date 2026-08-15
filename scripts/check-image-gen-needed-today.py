# -*- coding: utf-8 -*-
r"""今回のセッションでChatGPT経由の画像生成が発生するかを判定する
（読み取り専用・他ファイルへの書き込みは行わない）。

背景: Claude for Chromeのchatgpt.comへの移動確認は、拡張機能の仕様上セッション中に
必ず一度は出る（回避不可）。この確認を画像生成の直前ではなくセッション冒頭に前倒しできるよう、
「今回のセッションで画像生成が発生するか」を判定する。

判定方式（重要）: status.md・tasks.mdの自由記述文からキーワードの有無や近接関係を推測する
方式は採用しない。D-0071（stdin文字化けにより見出し検知が一度も機能していなかった不具合）と
同種の失敗を避けるため、「書く側が固定タグを機械的に書く」「読む側はそのタグの完全一致
（exact substring match）だけを見る」設計にする。あいまいな推測ロジックは持たせない。

判定対象:
  1. docs/status.md の全文に「【画像生成持ち越しあり】」という文字列が完全一致で含まれるか
  2. docs/tasks.md の「## 今日」節（次の「## 」見出しの直前まで）に
     「[新規記事執筆]」という文字列が完全一致で含まれるか
  3. （2026-08-15・D-0126）ファイル実在からの導出判定: 対象記事（下記）のhero画像・Pin画像の
     実ファイルが揃っているか。1・2は文章ベースのため、list-latest-reports.pyが読ませる範囲を
     外れたりtasks.mdの完了行がrotate-today-tasks.pyで削除されたりすると、日をまたいだ・
     セッションを挟んだ持ち越し検知が失われる。3はそれを補い、ファイルの実在という状態から
     毎セッション導出する（D-0111と同じ考え方）。対象記事は次の2範囲に限定する
     （記事数の増加に比例して処理量が増えない設計にするため）:
       a. output/articles/ 配下の status: draft の記事すべて
       b. site/src/content/posts/ 配下のうち、公開日（frontmatterのdate）が
          実行日から直近14日以内の記事
     各対象記事について、hero画像（frontmatterのhero値をsite/public/配下に解決したファイル）と、
     その記事に対応するPin画像（output/pins/配下の投稿文からutm_content=pin{番号}と
     /posts/{slug}/の対応を読み取り、output/Pin-images/配下に新形式「ピン{番号} …」または
     legacy形式「pin-{番号}-…」のファイルがあるか）の実在を確認する。対象記事に紐づく
     Pin投稿文が1件も見つからない場合（＝まだ画像生成の工程に到達していない記事）は
     Pin画像欠落として扱わない。

出力:
  いずれかが真であれば "NEEDED: <該当箇所>" を1行以上、両方偽であれば "NOT_NEEDED" を出力する。
  3の出力は記事ごとに1行、最大10行まで（超える場合は件数のみを示す）。
  ブロックや強制終了は行わない（情報提供のみ）。終了コードは常に0。

使い方:
  python site/scripts/check-image-gen-needed-today.py
"""

import datetime
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATUS_MD = os.path.join(ROOT, "docs", "status.md")
TASKS_MD = os.path.join(ROOT, "docs", "tasks.md")
ARTICLES_DIR = os.path.join(ROOT, "output", "articles")
POSTS_DIR = os.path.join(ROOT, "site", "src", "content", "posts")
PUBLIC_DIR = os.path.join(ROOT, "site", "public")
PINS_DIR = os.path.join(ROOT, "output", "pins")
PIN_IMAGES_DIR = os.path.join(ROOT, "output", "Pin-images")

STATUS_TAG = "【画像生成持ち越しあり】"
TASKS_TAG = "[新規記事執筆]"

RECENT_DAYS = 14
MAX_REPORT_LINES = 10

NEW_PIN_IMG_NUM_RE = re.compile(r"^ピン(\d+)\s")
LEGACY_PIN_IMG_NUM_RE = re.compile(r"^pin-(\d+)-")
PIN_POST_SLUG_RE = re.compile(r"/posts/([a-z0-9][a-z0-9-]*)/")
PIN_POST_NUM_RE = re.compile(r"utm_content=pin(\d+)")
FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)
FRONTMATTER_KV_RE = re.compile(r"^([a-zA-Z_]+):\s*(.*)$")


def read_text(path):
    if not os.path.isfile(path):
        return ""
    with io.open(path, "r", encoding="utf-8") as f:
        return f.read()


def extract_today_section(tasks_text):
    """tasks.mdの「## 今日」節（次の「## 」見出しの直前まで）を行のリストで返す。節が無ければ空リスト。"""
    lines = tasks_text.split("\n")
    start = None
    for i, line in enumerate(lines):
        if line.strip() == "## 今日":
            start = i + 1
            break
    if start is None:
        return []
    end = len(lines)
    for i in range(start, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    return lines[start:end]


def is_checked_line(line):
    """チェックボックスが済み（- [x] / - [X]）の行かどうかを判定する（大文字小文字両対応）。"""
    stripped = line.strip()
    return stripped.startswith("- [x]") or stripped.startswith("- [X]")


def parse_frontmatter(text):
    """frontmatterのkey: valueをフラットな辞書で返す（値の複雑なパース・型変換はしない）。"""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        mm = FRONTMATTER_KV_RE.match(line)
        if mm:
            fm[mm.group(1)] = mm.group(2).strip()
    return fm


def get_draft_target_articles():
    """output/articles/配下のstatus: draftの記事を[(slug, hero), ...]で返す。"""
    targets = []
    if not os.path.isdir(ARTICLES_DIR):
        return targets
    for name in sorted(os.listdir(ARTICLES_DIR)):
        if not name.endswith(".md") or name.startswith("_"):
            continue
        fm = parse_frontmatter(read_text(os.path.join(ARTICLES_DIR, name)))
        if fm.get("status") != "draft":
            continue
        slug = fm.get("slug") or os.path.splitext(name)[0]
        targets.append((slug, fm.get("hero", "")))
    return targets


def get_recent_published_target_articles(today, days=RECENT_DAYS):
    """site/src/content/posts/配下のうち公開日が直近days日以内の記事を[(slug, hero), ...]で返す。"""
    targets = []
    if not os.path.isdir(POSTS_DIR):
        return targets
    cutoff = today - datetime.timedelta(days=days - 1)
    for name in sorted(os.listdir(POSTS_DIR)):
        if not name.endswith(".md"):
            continue
        fm = parse_frontmatter(read_text(os.path.join(POSTS_DIR, name)))
        try:
            d = datetime.date.fromisoformat(fm.get("date", ""))
        except ValueError:
            continue
        if cutoff <= d <= today:
            slug = fm.get("slug") or os.path.splitext(name)[0]
            targets.append((slug, fm.get("hero", "")))
    return targets


def get_target_articles(today):
    """対象記事をslug -> heroのdictで返す（draft側を優先。同一slugが両方にある場合はdraftを採用）。"""
    combined = {}
    for slug, hero in get_recent_published_target_articles(today):
        combined[slug] = hero
    for slug, hero in get_draft_target_articles():
        combined[slug] = hero
    return combined


def hero_missing(hero_value):
    """frontmatterのhero値が指すファイルが実在しなければTrue。"""
    if not hero_value:
        return True
    path = os.path.join(PUBLIC_DIR, hero_value.lstrip("/"))
    return not os.path.isfile(path)


def build_pin_slug_map():
    """output/pins/配下の投稿文を1回だけ走査し、slug -> Pin番号集合のdictを返す。"""
    mapping = {}
    if not os.path.isdir(PINS_DIR):
        return mapping
    for name in sorted(os.listdir(PINS_DIR)):
        if not name.endswith(".md"):
            continue
        text = read_text(os.path.join(PINS_DIR, name))
        slugs = set(PIN_POST_SLUG_RE.findall(text))
        nums = set(int(n) for n in PIN_POST_NUM_RE.findall(text))
        if not slugs or not nums:
            continue
        for slug in slugs:
            mapping.setdefault(slug, set()).update(nums)
    return mapping


def build_pin_image_nums():
    """output/Pin-images/配下のファイル名から、新形式・legacy形式を問わずPin番号の集合を返す。"""
    nums = set()
    if not os.path.isdir(PIN_IMAGES_DIR):
        return nums
    for name in os.listdir(PIN_IMAGES_DIR):
        m = NEW_PIN_IMG_NUM_RE.match(name)
        if not m:
            m = LEGACY_PIN_IMG_NUM_RE.match(name)
        if m:
            nums.add(int(m.group(1)))
    return nums


def check_missing_images(today=None):
    """対象記事ごとのhero画像・Pin画像の欠落を["NEEDED: ...", ...]（記事ごと1行）で返す。"""
    if today is None:
        today = datetime.date.today()
    targets = get_target_articles(today)
    if not targets:
        return []

    pin_slug_map = build_pin_slug_map()
    image_nums = build_pin_image_nums()

    reasons = []
    for slug in sorted(targets):
        hero = targets[slug]
        missing_parts = []
        if hero_missing(hero):
            missing_parts.append(f"hero画像（{hero or '未設定'}）")

        pin_nums = pin_slug_map.get(slug)
        if pin_nums:
            missing_nums = sorted(n for n in pin_nums if n not in image_nums)
            if missing_nums:
                nums_str = "・".join(f"ピン{n}" for n in missing_nums)
                missing_parts.append(f"Pin画像（{nums_str}）")

        if missing_parts:
            reasons.append(f"NEEDED: {slug} の{'・'.join(missing_parts)}が見つかりません")

    return reasons


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    reasons = []

    status_text = read_text(STATUS_MD)
    if STATUS_TAG in status_text:
        reasons.append("NEEDED: docs/status.md に「%s」あり" % STATUS_TAG)

    tasks_today_lines = extract_today_section(read_text(TASKS_MD))
    for line in tasks_today_lines:
        if is_checked_line(line):
            continue
        if TASKS_TAG in line:
            reasons.append(
                "NEEDED: docs/tasks.md「今日」欄に「%s」あり（該当行: %s）" % (TASKS_TAG, line.strip())
            )

    image_reasons = check_missing_images()
    if len(image_reasons) > MAX_REPORT_LINES:
        reasons.append(
            "NEEDED: ファイル実在チェックで画像欠落のある記事が%d件あります（%d行を超えるため詳細省略）"
            % (len(image_reasons), MAX_REPORT_LINES)
        )
    else:
        reasons.extend(image_reasons)

    if reasons:
        for r in reasons:
            print(r)
    else:
        print("NOT_NEEDED")

    sys.exit(0)


if __name__ == "__main__":
    main()
