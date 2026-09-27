# -*- coding: utf-8 -*-
r"""記事の公開処理（公開前チェック → published化 → コピー → commit → push）を
1本のスクリプトに集約する（D-0128）。

【背景】
published化がこれまで「Editでfrontmatter書き換え → Bashでcp → commit・push」の
3操作に分散していたため、どの単一操作をフックで見張っても抜け道が残り、
公開前チェックを飛ばした経路が通ってしまう形だった。公開処理をこの1本に集約し、
Edit/Writeによるpublished化は .claude/hooks/check-publish-gate.py で拒否する。

【実行順（前段が1つでも失敗したら、以降を一切実行せず終了コード1で中断する）】
  1. output/articles/<slug>.md の存在確認
  2. 公開前チェック群を順に実行（1本でも非ゼロ終了なら中断）
       check-article-portability.py <slug>
       check-product-link-presence.py <slug> --min N
         （N は category で切り替える。gift・teaware は3点、それ以外は1点。
           categoryを読めなければ3点。D-0248）
       check-fact-source.py <slug>
       check-source-fetched.py <slug>
       check-pin-image-naming.py
       check-pin-image-style.py <slug>
       check-anchor-consistency.py <slug>
     ※quality-reviewer依頼前にも同じチェックを実行する運用は変えない。
       ここでの再実行は、レビュー往復中のEditで内容が変わっている可能性が
       あるための最終確認である。
  3. output/articles/<slug>.md の status を published に書き換える
  4. site/src/content/posts/<slug>.md へコピーする（既存があれば上書き）
  5. コピーしたファイルと、public/images/<slug>/ 配下の未追跡画像を add し commit
     （コミットメッセージは `publish: <slug>` の固定書式）
  6. push する

【冪等性】
  途中で失敗した後に同じコマンドを再実行しても二重コミット・二重pushにならない。
  3=既にpublishedならスキップ / 4=上書き / 5=ステージ対象が無ければcommitをスキップ /
  6=push済みなら「差分なし」で正常終了。

【--dry-run】
  1〜2は実際に実行し、3〜6は「何をするか」を1行ずつ表示するだけで一切実行しない。

使い方:
  python site/scripts/publish-article.py <slug>
  python site/scripts/publish-article.py <slug> --dry-run

終了コード: 0=完了（または--dry-runで中断なし） / 1=中断（どの段で落ちたかを表示）

【production runのstep記録（D-0235）】
  実行のたびに publish_attempt を1件だけ data/production-handoff/_steps/ へ
  追記する（slug・dry-runか本番か・OK/NG・NGだったチェック名）。記録の成否は
  標準出力・終了コード・公開処理のいずれにも影響しない。

【既存記事の修正・再公開（--prepare-revise / --revise）】
  published化した記事を、公開前チェックを通したうえで修正・再公開するための
  正規経路。正本は常に site/src/content/posts/ 側であり、output/articles/ 側の
  下書きは「修正作業中だけ一時的に存在する作業コピー」として扱う。

  手順:
    1. python site/scripts/publish-article.py --prepare-revise <slug>
       posts側の内容を output/articles/<slug>.md へ用意する（無ければ複製、
       既にあれば posts側と一致するか確認するだけで上書きはしない）。
    2. Editツールで output/articles/<slug>.md を直接修正する。
    3. python site/scripts/publish-article.py --revise <slug> --dry-run
       公開前チェック（Pin・SNS投稿文関連を除いた5本）と変更差分を確認する。
    4. quality-reviewer サブエージェントに変更箇所と前後の整合性を確認させる。
    5. python site/scripts/publish-article.py --revise <slug>
       本番反映（コピー→git add→commit「revise: <slug>」→push）する。

  --prepare-revise <slug>:
    posts側に記事が無い → 中断。
    下書きが無い → posts側をそのまま output/articles/ へ複製する。
    下書きが posts側と同一 → 何もせず正常終了。
    下書きが posts側と異なる → 差分を表示して中断する（下書きは上書きしない）。

  --revise <slug> [--dry-run]:
    posts側に記事が無い場合・下書きが無い場合・下書きの status が published
    でない場合・下書きが posts側と差分なしの場合は、いずれも中断する。
    公開前チェックは8本から check-pin-image-naming・check-pin-image-style・
    check-x-post-length を除いた5本（Pin・SNS投稿文は再公開で変わらないため）。
    商品リンクの基準は「公開中（posts側）の点数以上・上限3」（--min min(3, N)）。
    公開中が0点の記事は商品リンクのチェックを省く（減らしようが無いため）。
    本番実行時は下書きの updated を再公開日（日本時間）へ書き換えたうえで、
    site/src/content/posts/<slug>.md への上書きコピー→
    記事ファイルのみの git add→commit「revise: <slug>」→push まで行う（D-0250。
    初回の公開では updated を触らない）。--dry-run の差分にも updated の書き換えを含める。
    下書きが公開済みと updated の行以外で同一なら「差分なし」で中断する。
    prune-used-ideas・post-pins-to-pinterest・post-pins-to-buffer の実行や
    production runのstep記録・record-lessonのセッションマーカーは行わない
    （再公開はネタ帳消費・SNS新規投稿・日次生産のいずれにも当たらないため）。

【カテゴリの一括変更（--recategorize・D-0247。D-0239の例外）】
  公開済み記事の category の行だけを、対応表に従って一括で書き換える。
  python site/scripts/publish-article.py --recategorize <対応表.tsv> [--dry-run]
  対応表: 1行に「slug<TAB>新しいcategory」。空行と # 始まりの行は無視する。

  動き:
    1. 対応表の検査（slugが公開済みで実在／新しいcategoryが categories.ts の許可値／重複なし）。
       対象ファイルに未commitの変更があれば中断する。
    2. 各記事について、公開済みの本文の category の1行だけを置き換える。置き換え後の本文が
       元の本文と category の1行以外で一致することを行単位で確認し、外れれば全体を中断する。
       すでに同じcategoryの記事は「変更なし」として飛ばす。updated は変えない。
    3. 下書き（output/articles/<slug>.md）が公開済みと完全に同じ内容なら、下書きも同じ本文へ
       揃える。異なる場合は下書きに触れず「飛ばした」として報告する。下書きが無ければ何もしない。
    4. check-article-portability.py を全対象に、astro build を1回かける。落ちたら書き換えを
       すべて元に戻して中断する（commit・pushはしない）。
    5. 対象記事だけを add し、commit「recategorize: N記事」を1回、push を1回行う。
       ステージに対象以外のファイルが載っていれば中断する。
  --dry-run は1〜3の内容（対象・飛ばす記事）を表示するだけで、ファイルを書かず、4〜5もしない。
  prune-used-ideas・Pin/Buffer投稿・production runのstep記録は行わない（--reviseと同じ）。
"""

import difflib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SITE = os.path.join(ROOT, "site")
SCRIPTS_DIR = os.path.join(ROOT, "site", "scripts")
DRAFTS_DIR = os.path.join(ROOT, "output", "articles")
POSTS_DIR = os.path.join(ROOT, "site", "src", "content", "posts")

# (スクリプト名, slugを引数に取るか, 追加の固定引数)
PRE_PUBLISH_CHECKS = [
    ("check-article-portability.py", True, []),
    # 商品点数の必須数はカテゴリで切り替える（gift・teaware=3、それ以外=1・D-0248）。
    # 実際の --min は publish_checks() が category から決めて差し替える（この3は既定値）。
    # 週次の健全性チェックは引数なし（1点以上）で実行する。
    ("check-product-link-presence.py", True, ["--min", "3"]),
    ("check-fact-source.py", True, []),
    ("check-source-fetched.py", True, []),
    ("check-pin-image-naming.py", False, []),
    ("check-pin-image-style.py", True, []),
    ("check-anchor-consistency.py", True, []),
    # X向けの本文（ピンmdの「- X用説明文: 」行）が280に収まるかを機械で見る。
    # 文章のルールとして書くだけでは守られないため、公開前に必ず通る位置に置く。
    ("check-x-post-length.py", True, []),
]

# --revise 用: Pin・SNS投稿文はrevise（再公開）で内容が変わらないため除外する3本。
REVISE_EXCLUDED_CHECKS = {
    "check-pin-image-naming.py",
    "check-pin-image-style.py",
    "check-x-post-length.py",
}
REVISE_PUBLISH_CHECKS = [
    c for c in PRE_PUBLISH_CHECKS if c[0] not in REVISE_EXCLUDED_CHECKS
]

CHECK_TIMEOUT = 120
GIT_TIMEOUT = 180
BUILD_TIMEOUT = 600

RE_FRONTMATTER = re.compile(r"\A---\r?\n(.*?\r?\n)---\r?\n", re.S)
RE_STATUS = re.compile(r"^(\s*status:\s*)(\S+)[ \t]*$", re.M)
RE_CATEGORY = re.compile(r"^(\s*category:\s*)(\S+)[ \t]*$", re.M)
RE_UPDATED = re.compile(r"^(\s*updated:\s*)(\S+)[ \t]*$", re.M)

# 商品点数の必須数（D-0248）。gift・teaware は購入検討が主の題材のため3点必須、
# それ以外のカテゴリは1点以上。categoryを読めなければ厳しい側（3点）に倒す。
STRICT_PRODUCT_CATEGORIES = ("gift", "teaware")
JST = timezone(timedelta(hours=9))


def read_category(path):
    """ファイルの frontmatter から category の値を返す。読めなければ None。"""
    try:
        with open(path, encoding="utf-8", newline="") as f:
            text = f.read()
    except OSError:
        return None
    m = RE_FRONTMATTER.match(text)
    if not m:
        return None
    cm = RE_CATEGORY.search(m.group(1))
    return cm.group(2) if cm else None


def required_products(category):
    """category に応じた商品点数の必須数（gift・teaware=3、それ以外=1、不明=3）。"""
    if category is None or category in STRICT_PRODUCT_CATEGORIES:
        return 3
    return 1


def publish_checks(draft_path):
    """初回公開用のチェック群。商品点数の要求だけ category で切り替える。"""
    n = required_products(read_category(draft_path))
    checks = []
    for name, takes_slug, extra_args in PRE_PUBLISH_CHECKS:
        if name == "check-product-link-presence.py":
            extra_args = ["--min", str(n)]
        checks.append((name, takes_slug, extra_args))
    return checks


def today_jst():
    """今日の日付（日本時間）を YYYY-MM-DD で返す。"""
    return datetime.now(JST).strftime("%Y-%m-%d")


def normalize_updated(text):
    """updated の値を固定文字列に置き換えた本文を返す（updated以外の差分判定用）。"""
    m = RE_FRONTMATTER.match(text)
    if not m:
        return text
    front = m.group(1)
    um = RE_UPDATED.search(front)
    if not um:
        return text
    new_front = front[: um.start(2)] + "<UPDATED>" + front[um.end(2) :]
    return text[: m.start(1)] + new_front + text[m.end(1) :]


def set_updated(text, date_str):
    """updated の値を date_str へ書き換えた本文を返す。updated 行が無ければ None。"""
    m = RE_FRONTMATTER.match(text)
    if not m:
        return None
    front = m.group(1)
    um = RE_UPDATED.search(front)
    if not um:
        return None
    new_front = front[: um.start(2)] + date_str + front[um.end(2) :]
    return text[: m.start(1)] + new_front + text[m.end(1) :]


def out(text=""):
    print(text)


def abort(message):
    """中断メッセージを表示して終了コード1を返す。"""
    out("【中断】%s" % message)
    return 1


# --- ステップ2: 公開前チェック群 -----------------------------------------------


def record_production_step(kind, **fields):
    """production runのstep記録（D-0235）。公開処理そのものには影響しない。
    記録の失敗で公開を止めないため、例外はすべて握りつぶす。"""
    try:
        path = os.path.join(SCRIPTS_DIR, "production-run.py")
        spec = importlib.util.spec_from_file_location("production_run", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.record_step(kind, **fields)
    except Exception:
        pass


def run_checks(slug, attempt=None, checks=None):
    """公開前チェックを順に実行する。1本でも落ちたらFalseを返す。

    attempt は呼び出し元が渡す記録用の辞書で、落ちたチェック名を書き戻す
    （D-0235）。標準出力・終了コードはこの引数の有無で変わらない。
    checks を省略すると PRE_PUBLISH_CHECKS（8本）を使う。--revise は
    REVISE_PUBLISH_CHECKS（5本）を明示的に渡す。
    """
    if checks is None:
        checks = PRE_PUBLISH_CHECKS
    for script_name, takes_slug, extra_args in checks:
        script_path = os.path.join(SCRIPTS_DIR, script_name)
        cmd = [sys.executable, script_path]
        if takes_slug:
            cmd.append(slug)
        cmd.extend(extra_args)
        label = script_name + ((" " + slug) if takes_slug else "")
        if extra_args:
            label += " " + " ".join(extra_args)
        try:
            result = subprocess.run(
                cmd,
                cwd=ROOT,
                capture_output=True,
                timeout=CHECK_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            out("  NG  %s（タイムアウト %d秒）" % (label, CHECK_TIMEOUT))
            if attempt is not None:
                attempt["failed_check"] = script_name
            return False
        except Exception as e:
            out("  NG  %s（実行に失敗: %s）" % (label, e))
            if attempt is not None:
                attempt["failed_check"] = script_name
            return False

        stdout_text = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
        stderr_text = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""

        if result.returncode == 0:
            out("  OK  %s" % label)
            continue

        if attempt is not None:
            attempt["failed_check"] = script_name
        out("  NG  %s（終了コード: %d）" % (label, result.returncode))
        out("  --- %s の出力 ---" % script_name)
        for line in (stdout_text or stderr_text).rstrip("\n").splitlines():
            out("  " + line)
        out("  ---")
        return False
    return True


# --- ステップ3: status書き換え -------------------------------------------------


def read_text(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def current_status(draft_path):
    """(status文字列, エラーメッセージ) を返す。読めない場合は (None, 理由)。"""
    text = read_text(draft_path)
    m = RE_FRONTMATTER.match(text)
    if not m:
        return None, "frontmatter（--- で囲まれた先頭ブロック）が見つかりません"
    sm = RE_STATUS.search(m.group(1))
    if not sm:
        return None, "frontmatter に status 行が見つかりません"
    return sm.group(2), None


def set_published(draft_path):
    """statusをpublishedへ書き換える。既にpublishedなら書き換えない。"""
    text = read_text(draft_path)
    m = RE_FRONTMATTER.match(text)
    front = m.group(1)
    sm = RE_STATUS.search(front)
    new_front = front[: sm.start()] + sm.group(1) + "published" + front[sm.end() :]
    write_text(draft_path, text[: m.start(1)] + new_front + text[m.end(1) :])


# --- ステップ5・6: git ---------------------------------------------------------


def git(*args):
    return subprocess.run(
        ["git", "-C", SITE] + list(args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=GIT_TIMEOUT,
    )


def untracked_images(slug):
    """public/images/<slug>/ 配下の未追跡ファイル（siteからの相対パス）を返す。"""
    rel_dir = "public/images/%s" % slug
    if not os.path.isdir(os.path.join(SITE, "public", "images", slug)):
        return []
    result = git("ls-files", "--others", "--exclude-standard", "--", rel_dir)
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def diff_text(old_text, new_text, old_label, new_label):
    """unified diffを1つの文字列で返す（difflib）。"""
    return "".join(
        difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=old_label,
            tofile=new_label,
        )
    )


def out_lines(text):
    for line in text.rstrip("\n").splitlines():
        out("  " + line)


def ahead_count():
    """origin/main より何コミット先行しているか。判定できなければNone。"""
    result = git("rev-list", "--count", "@{u}..HEAD")
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


# --- メイン --------------------------------------------------------------------


MARKER_SCRIPT = os.path.join(SCRIPTS_DIR, "record-lesson.py")


def mark_daily_session():
    """教訓リストのセッションマーカーを作る（D-0163）。
    このスクリプトは日次フローでしか実行されないため、実行された事実を
    「今日は日次セッションである」ことの根拠として record-lesson.py へ渡す。
    マーカーの失敗で本来の処理が止まるのは本末転倒のため、例外・非ゼロ終了は
    すべて握りつぶし、呼び出し元の動作には一切影響させない。
    """
    try:
        subprocess.run(
            [sys.executable, MARKER_SCRIPT, "mark"],
            capture_output=True,
            timeout=15,
        )
    except Exception:
        pass


def _run_prepare_revise(rest_args):
    """--prepare-revise <slug>: posts側の内容を下書きとして用意する。"""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if len(rest_args) != 1 or rest_args[0].startswith("-"):
        out(__doc__)
        return 1

    slug = rest_args[0]
    draft_path = os.path.join(DRAFTS_DIR, "%s.md" % slug)
    published_path = os.path.join(POSTS_DIR, "%s.md" % slug)

    out("=== publish-article.py --prepare-revise %s ===" % slug)

    out("1. 公開済みの存在確認: site/src/content/posts/%s.md" % slug)
    if not os.path.isfile(published_path):
        return abort(
            "site/src/content/posts/%s.md が見つかりません。この記事はまだ公開されていません"
            % slug
        )
    out("  OK")

    published_text = read_text(published_path)

    if not os.path.isfile(draft_path):
        out("2. 下書きが無いため、公開済みの内容をそのまま output/articles/%s.md へ複製します" % slug)
        write_text(draft_path, published_text)
        out("  完了: output/articles/%s.md" % slug)
        out("=== --prepare-revise 完了 ===")
        return 0

    draft_text = read_text(draft_path)
    out("2. 既存の下書きと公開済み内容を比較します")
    if draft_text == published_text:
        out("  OK  下書きは公開済み内容と同一です。そのまま --revise へ進められます")
        out("=== --prepare-revise 完了（変更なし） ===")
        return 0

    out("  下書きが公開済み内容と異なります。下書きは上書きしていません")
    out("  --- 差分（site/src/content/posts/ → output/articles/） ---")
    out_lines(
        diff_text(
            published_text,
            draft_text,
            "site/src/content/posts/%s.md" % slug,
            "output/articles/%s.md" % slug,
        )
    )
    out("  ---")
    return abort(
        "output/articles/%s.md が公開済み内容と異なるため中断しました。"
        "どちらが新しいかは判断せず、内容を確認してください" % slug
    )


def _revise_checks(published_path):
    """--revise 用のチェック群と、公開中の商品点数Nを返す（Nが数えられなければNone）。

    商品リンクの基準は「公開中の点数から減らさない（上限3）」。数え方は
    check-product-link-presence.py の count_products を再利用する（複製しない）。
    """
    path = os.path.join(SCRIPTS_DIR, "check-product-link-presence.py")
    spec = importlib.util.spec_from_file_location("check_product_link_presence", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _, body = module.split_frontmatter(read_text(published_path))
    n = module.count_products(body)
    checks = []
    for name, takes_slug, extra_args in REVISE_PUBLISH_CHECKS:
        if name == "check-product-link-presence.py":
            if n == 0:
                continue  # --min は1以上のみ。公開中0点なら減ることは無いので省く
            extra_args = ["--min", str(min(3, n))]
        checks.append((name, takes_slug, extra_args))
    return checks, n


def _run_revise(rest_args):
    """--revise <slug> [--dry-run]: 公開済み記事を修正・再公開する。"""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    dry_run = "--dry-run" in rest_args
    positional = [a for a in rest_args if not a.startswith("-")]
    unknown = [a for a in rest_args if a.startswith("-") and a != "--dry-run"]
    if len(positional) != 1 or unknown:
        out(__doc__)
        return 1

    slug = positional[0]
    draft_path = os.path.join(DRAFTS_DIR, "%s.md" % slug)
    published_path = os.path.join(POSTS_DIR, "%s.md" % slug)

    out("=== publish-article.py --revise %s%s ===" % (slug, "（--dry-run）" if dry_run else ""))

    out("1. 公開済みの存在確認: site/src/content/posts/%s.md" % slug)
    if not os.path.isfile(published_path):
        return abort(
            "site/src/content/posts/%s.md が見つかりません。この記事はまだ公開されていません。"
            "新規公開は python site/scripts/publish-article.py %s で行ってください" % (slug, slug)
        )
    out("  OK")

    if not os.path.isfile(draft_path):
        return abort(
            "output/articles/%s.md が見つかりません。"
            "先に python site/scripts/publish-article.py --prepare-revise %s を実行してください"
            % (slug, slug)
        )

    status, err = current_status(draft_path)
    if err:
        return abort("output/articles/%s.md の %s" % (slug, err))
    if status != "published":
        return abort(
            "output/articles/%s.md の status が published ではありません（%s）。"
            "この記事は公開済みのため、下書きの status は published のまま修正してください"
            % (slug, status)
        )

    published_text = read_text(published_path)
    draft_text = read_text(draft_path)
    if normalize_updated(draft_text) == normalize_updated(published_text):
        return abort(
            "output/articles/%s.md は site/src/content/posts/%s.md と差分がありません"
            "（updated の行は差分に数えません）" % (slug, slug)
        )
    # 再公開日（日本時間）を updated に反映する（D-0250）。下書きの updated が何であっても上書きする。
    revised_date = today_jst()
    draft_text = set_updated(draft_text, revised_date)
    if draft_text is None:
        return abort("output/articles/%s.md の frontmatter に updated 行が見つかりません" % slug)
    diff = diff_text(
        published_text,
        draft_text,
        "site/src/content/posts/%s.md" % slug,
        "output/articles/%s.md" % slug,
    )

    out("2. 公開前チェック群（Pin・SNS投稿文関連の3本を除いた5本）")
    revise_checks, published_products = _revise_checks(published_path)
    out("  商品リンク基準: 公開中の点数（%d点）以上（上限3）" % published_products)
    if not run_checks(slug, checks=revise_checks):
        return abort("公開前チェックに失敗したため、以降の処理（コピー・commit・push）は一切実行していません")

    out("3. 変更差分")
    out_lines(diff)

    if dry_run:
        out("4. [dry-run] updated を %s へ更新し、site/src/content/posts/%s.md へ上書きコピーする" % (revised_date, slug))
        out(
            "5. [dry-run] git add src/content/posts/%s.md → git commit -m \"revise: %s\""
            % (slug, slug)
        )
        out("6. [dry-run] git push")
        out("=== dry-run 完了（4〜6は実行していません） ===")
        return 0

    # 4. updated を再公開日へ書き換え（下書き側）→コピー
    write_text(draft_path, draft_text)
    out("4. updated を %s（日本時間の再公開日）へ更新: output/articles/%s.md" % (revised_date, slug))
    shutil.copyfile(draft_path, published_path)
    out("   コピー完了: site/src/content/posts/%s.md" % slug)

    # 5. add・commit（記事ファイルのみ。Pin画像はrevise対象外）
    add_target = "src/content/posts/%s.md" % slug
    result = git("add", "--", add_target)
    if result.returncode != 0:
        return abort("git add に失敗しました: %s" % (result.stderr or result.stdout).strip())
    out("5. git add: %s" % add_target)

    staged = git("diff", "--cached", "--quiet")
    if staged.returncode == 0:
        out("   ステージ対象に差分が無いため commit をスキップ")
    elif staged.returncode == 1:
        result = git("commit", "-m", "revise: %s" % slug)
        if result.returncode != 0:
            return abort("git commit に失敗しました: %s" % (result.stderr or result.stdout).strip())
        out("   git commit: revise: %s" % slug)
    else:
        return abort("git diff --cached の判定に失敗しました: %s" % (staged.stderr or staged.stdout).strip())

    # 6. push
    ahead = ahead_count()
    if ahead == 0:
        out("6. git push は差分なしのためスキップ（origin/main と同一）")
    else:
        result = git("push")
        if result.returncode != 0:
            return abort("git push に失敗しました: %s" % (result.stderr or result.stdout).strip())
        out("6. git push 完了")
        push_out = (result.stdout + result.stderr).strip()
        for line in push_out.splitlines():
            out("   " + line)

    out("=== 再公開完了: %s ===" % slug)
    out("再公開のため prune-used-ideas・post-pins-to-pinterest・post-pins-to-buffer は実行しない")
    return 0


def _load_allowed_categories():
    """categories.ts の CATEGORY_SLUGS を返す（check-article-portability.py の読み取りを再利用する）。"""
    path = os.path.join(SCRIPTS_DIR, "check-article-portability.py")
    spec = importlib.util.spec_from_file_location("check_article_portability", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load_category_slugs()


def _parse_recategorize_map(map_path):
    """対応表（slug<TAB>category）を読む。(list of (slug, category), エラー文言) を返す。"""
    if not os.path.isfile(map_path):
        return None, "対応表が見つかりません: %s" % map_path
    rows = []
    seen = set()
    for no, raw in enumerate(read_text(map_path).splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
            return None, "対応表 %d行目が「slug<TAB>category」の形ではありません: %s" % (no, raw)
        slug, category = parts[0].strip(), parts[1].strip()
        if slug in seen:
            return None, "対応表に同じslugが2回あります: %s" % slug
        seen.add(slug)
        rows.append((slug, category))
    if not rows:
        return None, "対応表に有効な行がありません"
    return rows, None


def _replace_category(text, new_category):
    """本文の category の1行だけを置き換える。(新しい本文, エラー文言) を返す。

    置き換え後が元の本文と category の1行以外で一致することを行単位で確認する。
    """
    m = RE_FRONTMATTER.match(text)
    if not m:
        return None, "frontmatterが見つかりません"
    front = m.group(1)
    cm = RE_CATEGORY.search(front)
    if not cm:
        return None, "category 行が見つかりません"
    new_front = front[: cm.start(2)] + new_category + front[cm.end(2) :]
    new_text = text[: m.start(1)] + new_front + text[m.end(1) :]
    old_lines = text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    if len(old_lines) != len(new_lines):
        return None, "行数が変わりました"
    changed = [i for i, (a, b) in enumerate(zip(old_lines, new_lines)) if a != b]
    if len(changed) > 1:
        return None, "category 以外の行も変わりました（%d行）" % len(changed)
    if changed and not old_lines[changed[0]].lstrip().startswith("category:"):
        return None, "category 以外の行が変わりました（%d行目）" % (changed[0] + 1)
    return new_text, None


def _run_build():
    """astro build を実行する。(成功か, 出力末尾) を返す。"""
    try:
        result = subprocess.run(
            ["node", os.path.join(SITE, "node_modules", "astro", "astro.js"), "build"],
            cwd=SITE,
            capture_output=True,
            timeout=BUILD_TIMEOUT,
        )
    except Exception as e:
        return False, "ビルドの実行に失敗: %s" % e
    text = (result.stdout or b"").decode("utf-8", errors="replace") + (result.stderr or b"").decode(
        "utf-8", errors="replace"
    )
    return result.returncode == 0, "\n".join(text.rstrip("\n").splitlines()[-15:])


def _run_recategorize(rest_args):
    """--recategorize <対応表> [--dry-run]: 公開済み記事の category の行だけを一括で書き換える（D-0247）。"""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    dry_run = "--dry-run" in rest_args
    positional = [a for a in rest_args if not a.startswith("-")]
    unknown = [a for a in rest_args if a.startswith("-") and a != "--dry-run"]
    if len(positional) != 1 or unknown:
        out(__doc__)
        return 1

    out("=== publish-article.py --recategorize %s%s ===" % (positional[0], "（--dry-run）" if dry_run else ""))

    out("1. 対応表の検査")
    rows, err = _parse_recategorize_map(positional[0])
    if err:
        return abort(err)
    allowed = _load_allowed_categories()
    if not allowed:
        return abort("categories.ts から CATEGORY_SLUGS を読み取れませんでした")
    for slug, category in rows:
        if category not in allowed:
            return abort("%s: category '%s' は許可値（%s）にありません" % (slug, category, ", ".join(allowed)))
        if not os.path.isfile(os.path.join(POSTS_DIR, "%s.md" % slug)):
            return abort("site/src/content/posts/%s.md が見つかりません（公開済みの記事だけが対象です）" % slug)
    rel_paths = ["src/content/posts/%s.md" % slug for slug, _ in rows]
    status = git("status", "--porcelain", "--", *rel_paths)
    if status.returncode != 0:
        return abort("git status に失敗しました: %s" % (status.stderr or status.stdout).strip())
    if status.stdout.strip():
        return abort("対象記事に未commitの変更があります。先に片付けてください:\n" + status.stdout.rstrip())
    out("  OK  %d件" % len(rows))

    out("2. category の1行だけを置き換えた本文を作る")
    plans = []  # (slug, old_text, new_text, old_category, new_category, draft_action)
    for slug, category in rows:
        published_path = os.path.join(POSTS_DIR, "%s.md" % slug)
        old_text = read_text(published_path)
        old_category = read_category(published_path)
        if old_category == category:
            out("  変更なし  %s（すでに %s）" % (slug, category))
            continue
        new_text, err = _replace_category(old_text, category)
        if err:
            return abort("%s: %s。何も書き換えていません" % (slug, err))
        draft_path = os.path.join(DRAFTS_DIR, "%s.md" % slug)
        if not os.path.isfile(draft_path):
            draft_action = "なし"
        elif read_text(draft_path) == old_text:
            draft_action = "揃える"
        else:
            draft_action = "飛ばす"
        plans.append((slug, old_text, new_text, old_category, category, draft_action))
        out("  %s: %s → %s（下書き: %s）" % (slug, old_category, category, draft_action))
    if not plans:
        out("=== 変更対象がありません ===")
        return 0
    skipped = [p[0] for p in plans if p[5] == "飛ばす"]
    if skipped:
        out("  下書きが公開済みと異なるため触らない記事（%d件）: %s" % (len(skipped), ", ".join(skipped)))

    if dry_run:
        out("3. [dry-run] 書き換え・チェック・ビルド・commit・push は実行していません")
        out("=== dry-run 完了（変更対象 %d件） ===" % len(plans))
        return 0

    # 3. 書き換え（失敗時に戻せるよう元の本文を保持している）
    written = []  # (path, old_text)

    def rollback():
        for path, old in written:
            write_text(path, old)

    for slug, old_text, new_text, _oc, _nc, draft_action in plans:
        published_path = os.path.join(POSTS_DIR, "%s.md" % slug)
        write_text(published_path, new_text)
        written.append((published_path, old_text))
        if draft_action == "揃える":
            draft_path = os.path.join(DRAFTS_DIR, "%s.md" % slug)
            write_text(draft_path, new_text)
            written.append((draft_path, old_text))
    out("3. 書き換え完了（公開済み %d件・下書きを揃えたもの %d件）" % (len(plans), sum(1 for p in plans if p[5] == "揃える")))

    # 4. チェックとビルド
    out("4. portability チェックとビルド")
    ng = False
    for slug, *_rest in plans:
        result = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS_DIR, "check-article-portability.py"), slug],
            cwd=ROOT,
            capture_output=True,
            timeout=CHECK_TIMEOUT,
        )
        if result.returncode != 0:
            out("  NG  check-article-portability.py %s" % slug)
            out_lines((result.stdout or b"").decode("utf-8", errors="replace"))
            ng = True
            break
    if not ng:
        out("  OK  check-article-portability.py（%d件）" % len(plans))
        ok, tail = _run_build()
        if not ok:
            out("  NG  astro build")
            out_lines(tail)
            ng = True
        else:
            out("  OK  astro build")
    if ng:
        rollback()
        return abort("チェックまたはビルドに失敗したため、書き換えをすべて元に戻しました（commit・pushは実行していません）")

    # 5. add・commit（1回）・push（1回）
    staged_before = git("diff", "--cached", "--name-only")
    if staged_before.returncode != 0:
        rollback()
        return abort("git diff --cached に失敗しました。書き換えを元に戻しました")
    foreign = [f for f in staged_before.stdout.split() if f not in rel_paths]
    if foreign:
        rollback()
        return abort("対象以外のファイルがステージされています（%s）。書き換えを元に戻しました" % ", ".join(foreign))
    result = git("add", "--", *rel_paths)
    if result.returncode != 0:
        return abort("git add に失敗しました: %s" % (result.stderr or result.stdout).strip())
    out("5. git add: %d件" % len(rel_paths))
    result = git("commit", "-m", "recategorize: %d記事" % len(plans))
    if result.returncode != 0:
        return abort("git commit に失敗しました: %s" % (result.stderr or result.stdout).strip())
    out("   git commit: recategorize: %d記事" % len(plans))
    result = git("push")
    if result.returncode != 0:
        return abort("git push に失敗しました: %s" % (result.stderr or result.stdout).strip())
    out("6. git push 完了")
    for line in (result.stdout + result.stderr).strip().splitlines():
        out("   " + line)
    out("=== カテゴリ変更完了: %d記事 ===" % len(plans))
    return 0


def main():
    """本体（_run）を呼び、その結果を production run の step として1件だけ記録する。

    標準出力・終了コードは _run() のものをそのまま返す（D-0235で追加した記録は
    公開処理の挙動を変えない）。

    --prepare-revise / --revise はここで分岐し、_run() を一切経由しない
    （mark_daily_session・record_production_stepのいずれも呼ばない。D-0239）。
    """
    args = list(sys.argv[1:])

    if args[:1] == ["--prepare-revise"]:
        return _run_prepare_revise(args[1:])

    if args[:1] == ["--revise"]:
        return _run_revise(args[1:])

    if args[:1] == ["--recategorize"]:
        return _run_recategorize(args[1:])

    attempt = {"slug": None, "dry_run": False, "failed_check": None}
    rc = _run(attempt)
    record_production_step(
        "publish_attempt",
        slug=attempt["slug"],
        dry_run=attempt["dry_run"],
        result="OK" if rc == 0 else "NG",
        failed_check=attempt["failed_check"],
    )
    return rc


def _run(attempt):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    # 日次フロー実行の記録（D-0163）。判定・公開処理そのものには影響しない。
    mark_daily_session()

    args = [a for a in sys.argv[1:]]
    dry_run = "--dry-run" in args
    attempt["dry_run"] = dry_run
    positional = [a for a in args if not a.startswith("-")]
    unknown = [a for a in args if a.startswith("-") and a != "--dry-run"]

    if len(positional) != 1 or unknown:
        out(__doc__)
        return 1

    slug = positional[0]
    attempt["slug"] = slug
    draft_path = os.path.join(DRAFTS_DIR, "%s.md" % slug)
    published_path = os.path.join(POSTS_DIR, "%s.md" % slug)

    out("=== publish-article.py %s%s ===" % (slug, "（--dry-run）" if dry_run else ""))

    # 1. 存在確認
    out("1. 下書きの存在確認: output/articles/%s.md" % slug)
    if not os.path.isfile(draft_path):
        return abort("output/articles/%s.md が見つかりません" % slug)
    out("  OK")

    # 2. 公開前チェック群
    out("2. 公開前チェック群")
    new_checks = publish_checks(draft_path)
    out("  商品点数の必須数: %d点（category: %s）" % (required_products(read_category(draft_path)), read_category(draft_path)))
    if not run_checks(slug, attempt, checks=new_checks):
        return abort("公開前チェックに失敗したため、以降の処理（status書き換え・コピー・commit・push）は一切実行していません")

    # 3. status書き換え
    status, err = current_status(draft_path)
    if err:
        return abort("output/articles/%s.md の %s" % (slug, err))
    if status not in ("draft", "published"):
        return abort(
            "output/articles/%s.md の status が想定外の値です（%s）。draft か published のみ扱えます"
            % (slug, status)
        )

    if dry_run:
        if status == "published":
            out("3. [dry-run] status は既に published のため書き換えをスキップする")
        else:
            out("3. [dry-run] output/articles/%s.md の status を draft → published に書き換える" % slug)
        out(
            "4. [dry-run] output/articles/%s.md → site/src/content/posts/%s.md へコピーする（%s）"
            % (slug, slug, "既存を上書き" if os.path.isfile(published_path) else "新規作成")
        )
        add_targets = ["src/content/posts/%s.md" % slug] + untracked_images(slug)
        out(
            "5. [dry-run] git add %s → git commit -m \"publish: %s\"（ステージ対象が無ければcommitはスキップ）"
            % (" ".join(add_targets), slug)
        )
        ahead = ahead_count()
        if ahead is None:
            out("6. [dry-run] git push（先行コミット数を判定できないため実行時はpushを試みる）")
        elif ahead == 0:
            out("6. [dry-run] git push は差分なしのためスキップする（origin/main と同一）")
        else:
            out("6. [dry-run] git push（現在 origin/main より %d コミット先行）" % ahead)
        out("=== dry-run 完了（3〜6は実行していません） ===")
        return 0

    # 3. 実行
    if status == "published":
        out("3. status は既に published のため書き換えをスキップ")
    else:
        set_published(draft_path)
        out("3. status を draft → published に書き換え: output/articles/%s.md" % slug)

    # 4. コピー
    os.makedirs(POSTS_DIR, exist_ok=True)
    shutil.copyfile(draft_path, published_path)
    out("4. コピー完了: site/src/content/posts/%s.md" % slug)

    # 5. add・commit
    add_targets = ["src/content/posts/%s.md" % slug] + untracked_images(slug)
    result = git("add", "--", *add_targets)
    if result.returncode != 0:
        return abort("git add に失敗しました: %s" % (result.stderr or result.stdout).strip())
    out("5. git add: %s" % " ".join(add_targets))

    staged = git("diff", "--cached", "--quiet")
    if staged.returncode == 0:
        out("   ステージ対象に差分が無いため commit をスキップ")
    elif staged.returncode == 1:
        result = git("commit", "-m", "publish: %s" % slug)
        if result.returncode != 0:
            return abort("git commit に失敗しました: %s" % (result.stderr or result.stdout).strip())
        out("   git commit: publish: %s" % slug)
    else:
        return abort("git diff --cached の判定に失敗しました: %s" % (staged.stderr or staged.stdout).strip())

    # 6. push
    ahead = ahead_count()
    if ahead == 0:
        out("6. git push は差分なしのためスキップ（origin/main と同一）")
    else:
        result = git("push")
        if result.returncode != 0:
            return abort("git push に失敗しました: %s" % (result.stderr or result.stdout).strip())
        out("6. git push 完了")
        push_out = (result.stdout + result.stderr).strip()
        for line in push_out.splitlines():
            out("   " + line)

    out("=== 公開完了: %s ===" % slug)
    return 0


if __name__ == "__main__":
    sys.exit(main())
