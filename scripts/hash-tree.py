# -*- coding: utf-8 -*-
r"""ディレクトリの中身をハッシュ化して1行ずつ出す（変更検知用・D-0253）。

growth-audit（読み取り専用のはず）の実行前後で対象ディレクトリの中身が
変わっていないことを確認する用途を主目的とする。ファイル一覧＋各ファイルの
内容（バイト列そのまま）をまとめて sha256 する。ファイルの追加・削除・
中身の変更・リネームのいずれも検知する（mtime 等のメタデータは見ない）。

使い方:
  python site/scripts/hash-tree.py <dir1> [<dir2> ...]

存在しないディレクトリは "MISSING" と出す（エラーにはしない・空ディレクトリと
明確に区別するため）。
"""
import hashlib
import sys
from pathlib import Path


def hash_dir(path: Path) -> str:
    if not path.is_dir():
        return "MISSING"
    digest = hashlib.sha256()
    for file_path in sorted(path.rglob("*")):
        if not file_path.is_file():
            continue
        rel = file_path.relative_to(path).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def main() -> None:
    if len(sys.argv) < 2:
        sys.stderr.write("usage: python site/scripts/hash-tree.py <dir1> [<dir2> ...]\n")
        raise SystemExit(2)
    for arg in sys.argv[1:]:
        path = Path(arg)
        print("%s\t%s" % (arg, hash_dir(path)))


if __name__ == "__main__":
    main()
