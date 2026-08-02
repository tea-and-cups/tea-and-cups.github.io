"""既存の全記事に対して、記事の可搬性規約（CLAUDE.md 9-2 / D-0005）を一括チェックする。

check-article-portability.py が1記事分の判定ロジックを持っているため、
それを import して再利用する（判定ロジックの二重管理を避けるため）。

共通スクリプト（check-article-portability.py・生成ロジック等）を変更した際に、
既存の全記事がまだ規約に適合しているか（回帰していないか）を確認する用途。

対象: output/articles/*.md と site/src/content/posts/*.md の両方をglobし、
同じslugが両方に存在する場合（下書き→公開済みに移行済み）は公開済み側を優先して1回だけチェックする。
slugの識別はfrontmatter内の`slug:`値を優先し、frontmatterが無い場合のみファイル名を使う
（output/articles/には日付プレフィックス付きファイル名の旧形式下書きがあり、ファイル名だけでは
公開済み版と重複除外できないため）。先頭が「_」のファイル（_TEMPLATE.md 等、実記事ではないもの）は対象外。

出力: OKだった記事は行を出さない。NGの記事のみ「slug: NG - <理由>」で列挙し、
最後に必ず「総合: X/Y OK」を1行出す。記事数が増えてもNGが無い限り出力サイズはほぼ一定。

使い方:
  python site/scripts/check-all-articles-portability.py

終了コード: 全記事OKなら0、1件でもNGがあれば1
"""

import glob
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DRAFTS_DIR = os.path.join(ROOT, "output", "articles")
PUBLISHED_DIR = os.path.join(ROOT, "site", "src", "content", "posts")

CAP_MODULE_PATH = os.path.join(ROOT, "site", "scripts", "check-article-portability.py")


def load_cap_module():
    # ファイル名にハイフンを含むため通常のimport文が使えず、importlibで直接読み込む
    spec = importlib.util.spec_from_file_location("check_article_portability", CAP_MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def slug_key(cap, path):
    """記事の識別キーを返す。frontmatterのslug値があればそれを優先し、
    無ければファイル名を使う（出力パスに日付プレフィックスが付いた旧形式の下書きは、
    ファイル名がfrontmatterのslugと一致しないため、これをしないと公開済み版と重複除外できない）。
    """
    try:
        text = cap.io_read(path)
        fm_text, _ = cap.split_frontmatter(text)
        if fm_text is not None:
            _, values = cap.parse_frontmatter_keys(fm_text)
            slug = values.get("slug", "").strip()
            if slug:
                return slug
    except OSError:
        pass
    return os.path.splitext(os.path.basename(path))[0]


def collect_slug_paths(cap):
    """slug -> パス の辞書を返す。draftsで作り、publishedで上書きして公開済みを優先する。"""
    paths = {}
    for path in glob.glob(os.path.join(DRAFTS_DIR, "*.md")):
        if os.path.basename(path).startswith("_"):
            continue
        paths[slug_key(cap, path)] = path
    for path in glob.glob(os.path.join(PUBLISHED_DIR, "*.md")):
        if os.path.basename(path).startswith("_"):
            continue
        paths[slug_key(cap, path)] = path
    return paths


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    cap = load_cap_module()
    allowed_slugs = cap.load_category_slugs()
    slug_paths = collect_slug_paths(cap)

    ng_slugs = 0
    total = len(slug_paths)

    for slug in sorted(slug_paths):
        path = slug_paths[slug]
        results = cap.check_article(path, allowed_slugs)
        failing = [f"{name}: {detail}" for name, ok, detail in results if not ok]
        if failing:
            ng_slugs += 1
            print(f"{slug}: NG - {'; '.join(failing)}")

    ok_count = total - ng_slugs
    print(f"総合: {ok_count}/{total} OK")
    sys.exit(0 if ng_slugs == 0 else 1)


if __name__ == "__main__":
    main()
