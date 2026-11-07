# -*- coding: utf-8 -*-
r"""内部リンクの追加だけを機械的に保証し、戻すときも機械的に戻す（内部リンク実験 EX-IL1・D-0324）。

【目的】
  既存記事の本文に /posts/<slug>/ への内部リンクを足すとき、「足したのはリンクの記法だけで、
  本文の文字は一字も変えていない」ことを検査する。実験をやめるときは、足したリンクだけを
  文言に戻した本文を作る。効いた場合に週次・月次へ組み込めるよう、部品として再利用できる形にしてある。
  今回は publish-article.py の検査一覧には組み込まない（定期実行に組み込むときに検討する）。

【検査モード】 check <slug>
  「変更前の本文」と「変更後の本文」を比べ、新しく足された /posts/ リンクについて次を判定する。
  1つでも違反があれば NG・終了コード1。
    a. 足したリンクの記法を外すと、変更前の本文と一字一句同じになる（frontmatter の updated の行は除く）。
       --allow-text-change を付けたときだけ a を飛ばし、b〜d だけを判定する。
    b. 足すリンクは1記事3本まで。足したリンクの先が既存リンクの先と重ならない。同じ先へは1回まで。
       自分自身へのリンクは禁止。
    c. 足したリンクが、見出しの行・表の行・引用の行・太字の質問文の行（「**Q. 〜**」等）・
       冒頭の段落（広告表記「※…広告…」を除いた最初の段落）・既存リンクの文言の内側に無い。
    d. リンク先の site/src/content/posts/<slug>.md が実在し、status: published である。
  比べる版:
    --base を付けない: 変更前＝公開中（site/src/content/posts/<slug>.md）、変更後＝下書き（output/articles/<slug>.md）
    --base <git ref>: 変更前＝その ref の site/src/content/posts/<slug>.md、変更後＝公開中のファイル
  出力: 足したリンクを1行ずつ「リンク元slug → 文言 → リンク先slug」で出す（レポートへそのまま転記できる形）。

【戻しモード】 revert <slug> --base <git ref> --targets <slug1,slug2> [--dry-run]
  --base の版と比べ、--targets の先へ新しく足されたリンクだけを文言に戻した本文を作る。
  --dry-run: 書き込まずに、戻した本文が変更前の本文と（updated の行を除いて）一致するかだけを表示する。
             一致すれば終了コード0、一致しなければ差分を出して終了コード1。
  --dry-run なし: 戻した本文を output/articles/<slug>.md へ書く。下書きが --prepare-revise 済み
             （公開中と同一）でなければ中断する。戻した本文が変更前と一致しない場合も中断する
             （--allow-text-change を付けたときだけ書く）。書いたあとは通常の
             publish-article.py --revise <slug> --dry-run → quality-reviewer → --revise の経路で公開する。
  git revert は使わない（検査を通らず、output/articles の下書きもずれるため）。

【検証用の引数】（テスト用。日常の運用では使わない）
  --base-file <path>   変更前の本文をファイルから読む（--base の代わり）
  --new-file <path>    変更後（戻しモードでは戻す元）の本文をファイルから読む
  --posts-dir <dir>    d の確認に使う記事ディレクトリを差し替える

使い方:
  python site/scripts/check-internal-link-diff.py check <slug>
  python site/scripts/check-internal-link-diff.py check <slug> --allow-text-change
  python site/scripts/check-internal-link-diff.py check <slug> --base <commit>
  python site/scripts/check-internal-link-diff.py revert <slug> --base <commit> --targets <slug1,slug2> --dry-run

終了コード: 0=OK / 1=NG・中断 / 2=引数の誤り
"""

import difflib
import importlib.util
import os
import re
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
SITE = os.path.join(ROOT, "site")
POSTS_DIR = os.path.join(SITE, "src", "content", "posts")
DRAFTS_DIR = os.path.join(ROOT, "output", "articles")

MAX_ADDED_LINKS = 3

# 内部リンク: [文言](/posts/<slug>/) と、その後ろの #見出し も許す。文言に角かっこは含めない。
RE_POST_LINK = re.compile(r"\[([^\[\]\n]+)\]\((/posts/([a-z0-9-]+)/?(?:#[^)\s]*)?)\)")
# 既存リンクの文言の範囲を見るための、外部リンクも含めた一般のリンク（画像は先頭の ! を別に扱う）
RE_ANY_LINK = re.compile(r"\[((?:[^\[\]\n]|\[[^\[\]\n]*\])*)\]\(([^)\s]*)\)")
RE_FRONTMATTER = re.compile(r"\A---\r?\n(.*?\r?\n)---\r?\n", re.S)
RE_STATUS = re.compile(r"^\s*status:\s*(\S+)", re.M)
RE_BOLD_QUESTION = re.compile(r"^\*\*Q[0-9０-９]*[.．:：]")


def load_publish_article():
    """publish-article.py の normalize_updated を再利用する（updated の行の扱いを1か所にそろえるため）。"""
    path = os.path.join(SCRIPT_DIR, "publish-article.py")
    spec = importlib.util.spec_from_file_location("publish_article", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_PUBLISH = None


def normalize_updated(text):
    global _PUBLISH
    if _PUBLISH is None:
        _PUBLISH = load_publish_article()
    return _PUBLISH.normalize_updated(text)


def read_text(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read().replace("\r\n", "\n")


def git_show(ref, slug):
    result = subprocess.run(
        ["git", "-C", SITE, "show", "%s:src/content/posts/%s.md" % (ref, slug)],
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError("git show %s:src/content/posts/%s.md に失敗しました: %s"
                           % (ref, slug, result.stderr.decode("utf-8", "replace").strip()))
    return result.stdout.decode("utf-8").replace("\r\n", "\n")


def post_links(text):
    """本文中の /posts/ リンクを (start, end, 文言, 先slug) の一覧で返す。"""
    return [(m.start(), m.end(), m.group(1), m.group(3)) for m in RE_POST_LINK.finditer(text)]


def added_links(base_text, new_text):
    """new_text で新しく足されたリンクと、base_text から消えたリンクを返す。

    両方のリンクを (文言, 先slug) の列として並べ、difflib で対応を取る。対応の取れなかった
    new 側を「足したリンク」、base 側を「消えたリンク」とする。
    """
    base = post_links(base_text)
    new = post_links(new_text)
    base_keys = [(b[2], b[3]) for b in base]
    new_keys = [(n[2], n[3]) for n in new]
    matcher = difflib.SequenceMatcher(None, base_keys, new_keys, autojunk=False)
    added, removed = [], []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "insert"):
            added.extend(new[j1:j2])
        if tag in ("replace", "delete"):
            removed.extend(base[i1:i2])
    return added, removed, base


def strip_links(text, links):
    """links のリンク記法を外して文言だけにした本文と、各文言の (start, end) を返す。"""
    out = []
    spans = []
    pos = 0
    shift = 0
    for start, end, anchor, _slug in sorted(links):
        out.append(text[pos:start])
        new_start = start - shift
        out.append(anchor)
        spans.append((new_start, new_start + len(anchor)))
        shift += (end - start) - len(anchor)
        pos = end
    out.append(text[pos:])
    return "".join(out), spans


def body_start(text):
    m = RE_FRONTMATTER.match(text)
    return m.end() if m else 0


def first_paragraph_span(text):
    """広告表記を除いた、本文の最初の段落の (start, end)。見つからなければ None。"""
    start = body_start(text)
    for m in re.finditer(r"(?:[^\n]+\n?)+", text[start:]):
        para = m.group(0).strip()
        if not para:
            continue
        if para.startswith("※") and "広告" in para:
            continue
        return start + m.start(), start + m.end()
    return None


def line_at(text, pos):
    line_start = text.rfind("\n", 0, pos) + 1
    line_end = text.find("\n", pos)
    if line_end == -1:
        line_end = len(text)
    return text[line_start:line_end]


def location_problem(stripped, span, any_link_spans, first_para):
    """足したリンクの文言の位置 span が、置いてはいけない場所なら理由を返す。"""
    line = line_at(stripped, span[0]).strip()
    if line.startswith("#"):
        return "見出しの行"
    if line.startswith("|"):
        return "表の行"
    if line.startswith(">"):
        return "引用の行"
    if RE_BOLD_QUESTION.match(line):
        return "太字の質問文の行"
    if first_para and first_para[0] <= span[0] < first_para[1]:
        return "冒頭の段落"
    for a_start, a_end in any_link_spans:
        if a_start <= span[0] and span[1] <= a_end:
            return "既存リンクの文言の内側"
    return None


def link_anchor_spans(text):
    """一般のリンク（外部・画像を含む）の文言部分の (start, end) 一覧。"""
    return [(m.start(1), m.end(1)) for m in RE_ANY_LINK.finditer(text)]


def target_problem(slug, posts_dir):
    path = os.path.join(posts_dir, "%s.md" % slug)
    if not os.path.isfile(path):
        return "リンク先の記事が存在しない（%s.md）" % slug
    m = RE_FRONTMATTER.match(read_text(path))
    sm = RE_STATUS.search(m.group(1)) if m else None
    status = sm.group(1) if sm else "(なし)"
    if status != "published":
        return "リンク先の記事が published でない（%s: status %s）" % (slug, status)
    return None


def diff_lines(old_text, new_text, old_label, new_label):
    return list(difflib.unified_diff(old_text.splitlines(), new_text.splitlines(),
                                     fromfile=old_label, tofile=new_label, lineterm=""))


def check(slug, base_text, new_text, allow_text_change, posts_dir, base_label, new_label):
    """検査本体。(OKか, 出力行の一覧) を返す。"""
    lines = []
    problems = []
    added, removed, base = added_links(base_text, new_text)
    stripped, spans = strip_links(new_text, added)

    lines.append("足したリンク: %d本（変更前 %s → 変更後 %s）" % (len(added), base_label, new_label))
    for _s, _e, anchor, target in sorted(added):
        lines.append("  %s → %s → %s" % (slug, anchor, target))
    for _s, _e, anchor, target in removed:
        lines.append("  【警告】変更前にあって変更後に無いリンク: %s → %s" % (anchor, target))

    # a. 記法を外すと変更前と同じ
    if allow_text_change:
        lines.append("  --  a. 本文の一致（--allow-text-change のため判定していません）")
    elif normalize_updated(stripped) == normalize_updated(base_text):
        lines.append("  OK  a. 足したリンクの記法を外すと変更前の本文と一致（updated の行を除く）")
    else:
        problems.append("a")
        lines.append("  NG  a. 足したリンクの記法を外しても変更前の本文と一致しません")
        for d in diff_lines(normalize_updated(base_text), normalize_updated(stripped),
                            base_label, new_label + "（足したリンクを外した本文）"):
            lines.append("      " + d)

    # b. 本数・重なり・自分自身
    b_ng = []
    if len(added) > MAX_ADDED_LINKS:
        b_ng.append("足したリンクが%d本（上限%d本）" % (len(added), MAX_ADDED_LINKS))
    existing = set(b[3] for b in base)
    seen = set()
    for _s, _e, anchor, target in sorted(added):
        if target == slug:
            b_ng.append("自分自身へのリンク（%s）" % anchor)
        if target in existing:
            b_ng.append("既存のリンクと同じ先（%s）" % target)
        if target in seen:
            b_ng.append("同じ先へ2回以上（%s）" % target)
        seen.add(target)
    if b_ng:
        problems.append("b")
        lines.append("  NG  b. " + "／".join(b_ng))
    else:
        lines.append("  OK  b. 本数（%d本・上限%d）・既存リンクとの重なり・同じ先・自分自身" % (len(added), MAX_ADDED_LINKS))

    # c. 置き場所
    c_ng = []
    any_spans = [s for s in link_anchor_spans(stripped)]
    first_para = first_paragraph_span(stripped)
    for (_s, _e, anchor, target), span in zip(sorted(added), spans):
        where = location_problem(stripped, span, any_spans, first_para)
        if where:
            c_ng.append("%s（%s → %s）" % (where, anchor, target))
    if c_ng:
        problems.append("c")
        lines.append("  NG  c. 置いてはいけない場所: " + "／".join(c_ng))
    else:
        lines.append("  OK  c. 置き場所（見出し・表・引用・太字の質問文・冒頭の段落・既存リンクの内側に無い）")

    # d. リンク先の実在と published
    d_ng = []
    for target in sorted(seen):
        p = target_problem(target, posts_dir)
        if p:
            d_ng.append(p)
    if d_ng:
        problems.append("d")
        lines.append("  NG  d. " + "／".join(d_ng))
    else:
        lines.append("  OK  d. リンク先が実在し status: published")

    if not added:
        problems.append("none")
        lines.append("  NG  足したリンクがありません")
    return not problems, lines


def revert(slug, base_text, current_text, targets):
    """targets の先へ新しく足されたリンクだけを文言に戻した本文と、戻したリンクの一覧を返す。"""
    added, _removed, _base = added_links(base_text, current_text)
    chosen = [a for a in added if a[3] in targets]
    reverted, _spans = strip_links(current_text, chosen)
    return reverted, sorted(chosen)


def pop_value(args, name):
    if name not in args:
        return args, None
    i = args.index(name)
    if i + 1 >= len(args):
        raise ValueError("%s の値がありません" % name)
    return args[:i] + args[i + 2:], args[i + 1]


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if not argv or argv[0] not in ("check", "revert"):
        print(__doc__)
        return 2
    mode, args = argv[0], list(argv[1:])
    try:
        args, base_ref = pop_value(args, "--base")
        args, base_file = pop_value(args, "--base-file")
        args, new_file = pop_value(args, "--new-file")
        args, posts_dir = pop_value(args, "--posts-dir")
        args, targets = pop_value(args, "--targets")
    except ValueError as e:
        print("【引数の誤り】%s" % e)
        return 2
    allow_text_change = "--allow-text-change" in args
    dry_run = "--dry-run" in args
    flags = {"--allow-text-change", "--dry-run"}
    unknown = [a for a in args if a.startswith("-") and a not in flags]
    positional = [a for a in args if not a.startswith("-")]
    if unknown or len(positional) != 1:
        print("【引数の誤り】slug を1つ指定してください（不明な引数: %s）" % " ".join(unknown))
        return 2
    slug = positional[0]
    posts_dir = posts_dir or POSTS_DIR
    published_path = os.path.join(POSTS_DIR, "%s.md" % slug)
    draft_path = os.path.join(DRAFTS_DIR, "%s.md" % slug)

    try:
        if base_file:
            base_text, base_label = read_text(base_file), base_file
        elif base_ref:
            base_text, base_label = git_show(base_ref, slug), "%s:posts/%s.md" % (base_ref[:10], slug)
        elif mode == "check":
            base_text, base_label = read_text(published_path), "posts/%s.md（公開中）" % slug
        else:
            print("【引数の誤り】revert には --base（または --base-file）が必要です")
            return 2
        if new_file:
            new_text, new_label = read_text(new_file), new_file
        elif mode == "check" and not (base_ref or base_file):
            new_text, new_label = read_text(draft_path), "output/articles/%s.md（下書き）" % slug
        else:
            new_text, new_label = read_text(published_path), "posts/%s.md（現在）" % slug
    except (OSError, RuntimeError) as e:
        print("【中断】本文を読めません: %s" % e)
        return 1

    if mode == "check":
        print("=== check-internal-link-diff.py check %s%s ===" % (slug, "（--allow-text-change）" if allow_text_change else ""))
        ok, lines = check(slug, base_text, new_text, allow_text_change, posts_dir, base_label, new_label)
        for line in lines:
            print(line)
        print("RESULT: %s" % ("OK" if ok else "NG"))
        return 0 if ok else 1

    # revert
    if not targets:
        print("【引数の誤り】revert には --targets <slug1,slug2> が必要です")
        return 2
    target_set = set(t.strip() for t in targets.split(",") if t.strip())
    reverted, chosen = revert(slug, base_text, new_text, target_set)
    print("=== check-internal-link-diff.py revert %s%s ===" % (slug, "（--dry-run）" if dry_run else ""))
    print("戻すリンク: %d本（先: %s）" % (len(chosen), ",".join(sorted(target_set))))
    for _s, _e, anchor, target in chosen:
        print("  %s → %s → %s" % (slug, anchor, target))
    match = normalize_updated(reverted) == normalize_updated(base_text)
    if match:
        print("  一致: 戻した本文は変更前（%s）と一致します（updated の行を除く）" % base_label)
    else:
        print("  不一致: 戻した本文は変更前（%s）と一致しません" % base_label)
        for d in diff_lines(normalize_updated(base_text), normalize_updated(reverted),
                            base_label, "戻した本文"):
            print("      " + d)
    if dry_run:
        print("RESULT: %s" % ("MATCH" if match else "MISMATCH"))
        return 0 if match else 1
    if not chosen:
        print("【中断】戻すリンクがありません")
        return 1
    if not match and not allow_text_change:
        print("【中断】戻した本文が変更前と一致しないため書き込みません（--allow-text-change で書けます）")
        return 1
    if not os.path.isfile(draft_path) or read_text(draft_path) != read_text(published_path):
        print("【中断】output/articles/%s.md が公開中と同一ではありません。"
              "先に python site/scripts/publish-article.py --prepare-revise %s を実行してください" % (slug, slug))
        return 1
    with open(draft_path, "w", encoding="utf-8", newline="") as f:
        f.write(reverted)
    print("  書き込み: output/articles/%s.md（次は publish-article.py --revise %s --dry-run）" % (slug, slug))
    print("RESULT: WRITTEN")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
