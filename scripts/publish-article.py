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
       check-product-link-presence.py <slug>
       check-fact-source.py <slug>
       check-pin-image-naming.py
       check-pin-image-style.py <slug>
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
"""

import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SITE = os.path.join(ROOT, "site")
SCRIPTS_DIR = os.path.join(ROOT, "site", "scripts")
DRAFTS_DIR = os.path.join(ROOT, "output", "articles")
POSTS_DIR = os.path.join(ROOT, "site", "src", "content", "posts")

# (スクリプト名, slugを引数に取るか)
PRE_PUBLISH_CHECKS = [
    ("check-article-portability.py", True),
    ("check-product-link-presence.py", True),
    ("check-fact-source.py", True),
    ("check-pin-image-naming.py", False),
    ("check-pin-image-style.py", True),
]

CHECK_TIMEOUT = 120
GIT_TIMEOUT = 180

RE_FRONTMATTER = re.compile(r"\A---\r?\n(.*?\r?\n)---\r?\n", re.S)
RE_STATUS = re.compile(r"^(\s*status:\s*)(\S+)[ \t]*$", re.M)


def out(text=""):
    print(text)


def abort(message):
    """中断メッセージを表示して終了コード1を返す。"""
    out("【中断】%s" % message)
    return 1


# --- ステップ2: 公開前チェック群 -----------------------------------------------


def run_checks(slug):
    """公開前チェックを順に実行する。1本でも落ちたらFalseを返す。"""
    for script_name, takes_slug in PRE_PUBLISH_CHECKS:
        script_path = os.path.join(SCRIPTS_DIR, script_name)
        cmd = [sys.executable, script_path]
        if takes_slug:
            cmd.append(slug)
        label = script_name + ((" " + slug) if takes_slug else "")
        try:
            result = subprocess.run(
                cmd,
                cwd=ROOT,
                capture_output=True,
                timeout=CHECK_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            out("  NG  %s（タイムアウト %d秒）" % (label, CHECK_TIMEOUT))
            return False
        except Exception as e:
            out("  NG  %s（実行に失敗: %s）" % (label, e))
            return False

        stdout_text = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
        stderr_text = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""

        if result.returncode == 0:
            out("  OK  %s" % label)
            continue

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


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = [a for a in sys.argv[1:]]
    dry_run = "--dry-run" in args
    positional = [a for a in args if not a.startswith("-")]
    unknown = [a for a in args if a.startswith("-") and a != "--dry-run"]

    if len(positional) != 1 or unknown:
        out(__doc__)
        return 1

    slug = positional[0]
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
    if not run_checks(slug):
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
