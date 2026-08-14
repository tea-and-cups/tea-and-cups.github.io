# -*- coding: utf-8 -*-
r"""GET /v5/boards からボード正本ファイル（data/pinterest-boards.md）を生成する（T3・フェーズC）。

board_id をキーにした固定マッピング表を持つ（ボード名はオーナーが改名可能なため、
名前をキーにすると壊れる）。マッピングに無いboard_idを検出した場合・マッピングに
あるboard_idがAPI結果に無い場合はいずれも警告し、終了コード1で終わる（黙って落とさない）。
APIエラー・0件取得の場合も、既存の正本ファイルを書き換えずに終了コード1で終わる。

使い方:
  python site/scripts/generate-pinterest-boards.py
"""

import os
import sys
import urllib.error

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
from env_loader import require_env  # noqa: E402
from pinterest_api import fetch_all_pages, PinterestApiError  # noqa: E402

OUTPUT_PATH = os.path.join(PROJECT_ROOT, "data", "pinterest-boards.md")

# board_id → (選定条件, 状態)。状態は "選定可" または "廃止予定"。
# 廃止対象3ボード（ティーカップ・食器／紅茶のいれ方／ブランドティーカップ・紅茶の時間）は
# T2でのピン移動が実行できなかった（Pinterest API側の権限制限 pin_edit 未許可により
# PATCH /v5/pins が全件401で失敗）ため、"凍結扱い" として 廃止予定 で載せる。
BOARD_MAPPING = {
    "1101552458798668431": {"condition": "ギフト・贈答が主題", "status": "選定可"},
    "1101552458798646171": {"condition": "器・カップ・道具が主題", "status": "選定可"},
    "1101552458798670574": {"condition": "淹れ方・保存・手入れの手順が主題", "status": "選定可"},
    "1101552458798645296": {"condition": "茶葉・銘柄の選び方が主題", "status": "選定可"},
    "1101552458798697766": {"condition": "お菓子・スイーツとの組み合わせが主題", "status": "選定可"},
    "1101552458798651523": {"condition": "屋外・キャンプ・ピクニックが主題", "status": "選定可"},
    "1101552458798638307": {"condition": "季節性が明確（夏）", "status": "選定可"},
    "1101552458798697777": {"condition": "季節性が明確（秋）", "status": "選定可"},
    "1101552458798640168": {"condition": "いずれにも当たらない場合の既定", "status": "選定可"},
    "1101552458798696958": {"condition": "廃止予定（凍結・T2でのピン移動未達）", "status": "廃止予定"},
    "1101552458798645292": {"condition": "廃止予定（凍結・T2でのピン移動未達）", "status": "廃止予定"},
    "1101552458798676784": {"condition": "廃止予定（凍結・0件のまま維持）", "status": "廃止予定"},
}


def fetch_all_boards(access_token):
    try:
        return fetch_all_pages("/boards", access_token)
    except PinterestApiError as e:
        print("エラー: GET /v5/boards がHTTP %d を返しました: %s" % (e.status_code, e.body), file=sys.stderr)
        return None
    except urllib.error.URLError as e:
        print("エラー: GET /v5/boards への接続に失敗しました: %s" % e, file=sys.stderr)
        return None


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    access_token = require_env("PINTEREST_ACCESS_TOKEN")

    boards = fetch_all_boards(access_token)
    if boards is None:
        print("エラー: API取得に失敗したため、正本ファイルは書き換えません。", file=sys.stderr)
        sys.exit(1)
    if len(boards) == 0:
        print("エラー: 取得ボードが0件のため、正本ファイルは書き換えません。", file=sys.stderr)
        sys.exit(1)

    api_ids = {b.get("id"): b for b in boards}
    mapping_ids = set(BOARD_MAPPING.keys())

    warnings = []
    unknown_ids = api_ids.keys() - mapping_ids
    for uid in unknown_ids:
        warnings.append(
            "未分類・要確認: board_id=%s（名前: %s）がマッピング表に存在しません"
            % (uid, api_ids[uid].get("name"))
        )
    missing_ids = mapping_ids - api_ids.keys()
    for mid in missing_ids:
        warnings.append(
            "警告: マッピング表のboard_id=%sがAPI結果に存在しません（削除された可能性）" % mid
        )

    rows = []
    for board_id, meta in BOARD_MAPPING.items():
        b = api_ids.get(board_id)
        if b is None:
            # missing_idsで既に警告済み。行としては出力しない（実在しないため）。
            continue
        name = b.get("name", "")
        pin_count = b.get("pin_count", "")
        rows.append((name, board_id, pin_count, meta["status"], meta["condition"]))
    for uid in unknown_ids:
        b = api_ids[uid]
        rows.append((b.get("name", ""), uid, b.get("pin_count", ""), "未分類・要確認", "未分類・要確認"))

    # ボード名でソートして出力を安定させる
    rows.sort(key=lambda r: r[0])

    lines = []
    lines.append("# pinterest-boards.md — Pinterestボード正本（自動生成・手書き編集禁止）")
    lines.append("生成コマンド: python site/scripts/generate-pinterest-boards.py")
    lines.append("最終生成: 2026-08-14")
    lines.append("")
    lines.append("| ボード名 | board_id | ピン数 | 状態 | 選定条件 |")
    lines.append("|---|---|---|---|---|")
    for name, board_id, pin_count, status, condition in rows:
        lines.append("| %s | %s | %s | %s | %s |" % (name, board_id, pin_count, status, condition))
    lines.append("")

    with open(OUTPUT_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))

    print("正本ファイルを生成しました: %s（%d行）" % (OUTPUT_PATH, len(rows)))

    if warnings:
        for w in warnings:
            print(w, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
