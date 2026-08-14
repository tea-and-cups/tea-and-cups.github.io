# -*- coding: utf-8 -*-
r"""ボード正本（data/pinterest-boards.md）とボード選定規則（rules/pinterest-api.md）の
実態整合をセッション開始時に確認する（T2・フェーズC-2・D-0119）。

背景: オーナーがPinterest上でボードを改名・追加・削除した瞬間に data/pinterest-boards.md
が黙って古くなり、ボード名検証のPreToolUseフックが正しいボード名を弾いて記事作成が
止まる事故が実際に起きた（2026-08-14）。月次チェックリスト方式は最大1か月放置される
ため、SessionStartフックの子スクリプトとして毎回自動実行する。

動作:
  1. GET /v5/boards を1回だけ呼ぶ（generate-pinterest-boards.py の
     fetch_all_boards() をimportして再利用。同じ取得ロジックを2箇所に書かない）。
  2. 取得に成功し1件以上あれば、同じく generate-pinterest-boards.py の
     compute_rows_and_warnings() / write_file() で正本ファイルを再生成する。
     失敗・0件の場合は正本ファイルに一切触れない（前回の内容を保持する）。
  3. rules/pinterest-api.md の <!-- BOARD_SELECTION_NAMES_START/END --> 間から
     ボード選定規則が参照するボード名を機械抽出し、実在ボード名と突き合わせる。

警告条件:
  (a) 選定規則側のボード名が実在ボードに無い（改名・削除された）
  (b) 実在ボードが選定規則側に無い（新設された）
  (c) APIに到達できない、または取得結果が0件
  加えて、選定規則側の抽出結果が0件だった場合（マーカー欠落等）も警告として扱う
  （沈黙する失敗を作らないため）。generate-pinterest-boards.py側のboard_idマッピング
  警告（未分類のboard_id等）も、判断に迷う場合は過剰報告に倒す方針により合わせて出す。

出力: 問題が無い場合は "BOARDS_OK" の1行のみ。警告時は終了コード1で詳細を出力する。
想定外の例外は終了コード2。

使い方:
  python site/scripts/check-pinterest-boards-sync.py
"""

import importlib.util
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

RULES_FILE = os.path.join(PROJECT_ROOT, "rules", "pinterest-api.md")
API_TIMEOUT_SECONDS = 10  # session-start-check.py側の子スクリプトタイムアウト(30秒)を圧迫しないよう短めに固定

MARKER_START = "<!-- BOARD_SELECTION_NAMES_START -->"
MARKER_END = "<!-- BOARD_SELECTION_NAMES_END -->"


def extract_rule_board_names(rules_file):
    """rules/pinterest-api.md のマーカー間からボード名を機械抽出する。

    戻り値: (names, error_message)。マーカー不在・ファイル不在・0件抽出はいずれも
    names=set() かつ error_messageに理由を入れて返す（呼び出し側で警告扱いにする）。
    """
    if not os.path.isfile(rules_file):
        return set(), "rules/pinterest-api.md が見つかりません（%s）" % rules_file
    try:
        with open(rules_file, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        return set(), "rules/pinterest-api.md の読み込みに失敗しました: %s" % e

    if MARKER_START not in content or MARKER_END not in content:
        return set(), "rules/pinterest-api.md に機械抽出用マーカー（%s〜%s）が見つかりません" % (
            MARKER_START, MARKER_END,
        )

    block = content.split(MARKER_START, 1)[1].split(MARKER_END, 1)[0]
    names = set(line.strip() for line in block.splitlines() if line.strip())

    if not names:
        return set(), "rules/pinterest-api.md のマーカー間からボード名が0件でした（抽出失敗扱い）"

    return names, None


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    spec = importlib.util.spec_from_file_location(
        "generate_pinterest_boards", os.path.join(SCRIPT_DIR, "generate-pinterest-boards.py")
    )
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)

    from env_loader import require_env  # noqa: E402

    warnings = []

    access_token = require_env("PINTEREST_ACCESS_TOKEN")

    # --- API取得はここ1回のみ ---
    boards = gen.fetch_all_boards(access_token, timeout=API_TIMEOUT_SECONDS)
    if boards is None:
        print("【警告】GET /v5/boards への到達に失敗しました。正本ファイルは前回の内容を保持します。")
        sys.exit(1)
    if len(boards) == 0:
        print("【警告】GET /v5/boards の取得結果が0件でした。正本ファイルは前回の内容を保持します。")
        sys.exit(1)

    # 取得成功・1件以上のときのみ正本ファイルを再生成する
    rows, mapping_warnings = gen.compute_rows_and_warnings(boards)
    gen.write_file(rows)
    warnings.extend(mapping_warnings)

    # --- 選定規則側との突き合わせ（(a)(b)) ---
    api_names = set(b.get("name", "") for b in boards)
    rule_names, extract_error = extract_rule_board_names(RULES_FILE)
    if extract_error:
        warnings.append("【警告】%s" % extract_error)
    else:
        missing_in_real = rule_names - api_names  # (a)
        for name in sorted(missing_in_real):
            warnings.append(
                "【警告】選定規則側のボード名「%s」が実在ボードに見つかりません（改名・削除された可能性）" % name
            )
        missing_in_rule = api_names - rule_names  # (b)
        for name in sorted(missing_in_rule):
            warnings.append(
                "【警告】実在ボード「%s」が選定規則側（rules/pinterest-api.md）に記載されていません（新設された可能性）" % name
            )

    if warnings:
        for w in warnings:
            print(w)
        sys.exit(1)

    print("BOARDS_OK")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print("【警告】check-pinterest-boards-sync.py が想定外の例外で終了しました: %s" % e)
        sys.exit(2)
