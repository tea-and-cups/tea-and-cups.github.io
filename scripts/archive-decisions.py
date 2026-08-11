# -*- coding: utf-8 -*-
r"""docs/decisions.md の古い決定を docs/decisions-archive.md へ機械的に退避する。

check-doc-governance.py が「decisions.mdが15,000字を超えている」と警告した際に使う
（このスクリプト自体はどの文字数からでも実行でき、無条件に「decisions.md本体が
10,000字を下回るまで、末尾＝最も古いD-XXXXエントリから順に」移動する。すでに
10,000字以下ならエントリを1件も動かさない）。

移動の原則:
  - 原文は一切書き換えない（要約・圧縮はしない。見出し・本文・区切り線をそのまま移す）
  - decisions.md冒頭の運用ルール説明文、末尾のテンプレート行（"## D-XXXX: タイトル（日付）"）
    は移動対象に含めない（実データではないため）
  - decisions-archive.md 側も「新しいものが上」の並びを維持する。今回退避した
    バッチ（相対的に新しい）は、既存のアーカイブ済みエントリ（相対的に古い）より
    上（アーカイブ本文の先頭側）に挿入する

パース・再構成のロジックは check-doc-governance.py と共有する decisions_lib.py を使う。

境界行の同期（D-0112）:
  decisions.md冒頭に「D-XXXX以前の決定はdecisions-archive.mdにある」という境界行を
  自動で挿入・更新する。移動対象が無い実行でも、archive側の実際の最大D番号と
  境界行の数字を必ず突き合わせて書き直す（自己修復）。decisions-archive.mdが
  存在しない場合は境界行を書き込まない（既存の境界行があれば削除する）。

使い方:
  python site/scripts/archive-decisions.py            実際に移動して書き込む
  python site/scripts/archive-decisions.py --dry-run   書き込まず、移動予定の件数・D番号のみ表示する
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from decisions_lib import (
    read_text,
    write_text,
    count_chars_lines,
    split_decisions_document,
    render_document,
    sync_boundary_line,
)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DECISIONS_MD = os.path.join(ROOT, "docs", "decisions.md")
ARCHIVE_MD = os.path.join(ROOT, "docs", "decisions-archive.md")

# 「15,000字超過で警告→10,000字まで退避」。15,000ちょうどで止めると次の警告が
# 数件の追記後すぐ再発するため、10,000字まで多めに動かしてバッファを持たせる
# （check-doc-governance.pyのDECISIONS_MD_CHAR_LIMITとは別の下限値）
TARGET_CHAR_LIMIT = 10000

ARCHIVE_HEADER_LINES = [
    "# decisions-archive.md — 決定記録アーカイブ",
    "",
    "decisions.md の容量が15,000字を超えた際、check-doc-governance.py の警告を受けて",
    "archive-decisions.py が古い決定から機械的にここへ移動したもの。原文は無改変（要約・圧縮なし）。",
    "3行ルール（docs/decisions.md 冒頭参照）の適用対象外。直近の決定は docs/decisions.md 本体を参照。",
    "",
    "並び順は decisions.md と同じく「新しいものが上」。ここより下は移動元では decisions.md の",
    "末尾（古い決定）だった部分であることに変わりない。",
    "",
    "---",
]


def plan_archive(decisions_text):
    """decisions.mdのテキストから、移動計画（残す部分・移動するエントリ）を返す。副作用なし。"""
    doc = split_decisions_document(decisions_text)
    remaining = list(doc["entries"])  # newest first
    moved_oldest_first = []

    def current_len():
        return len(render_document(
            doc["preamble_lines"],
            [e["lines"] for e in remaining],
            doc["trailing_lines"],
        ))

    while remaining and current_len() > TARGET_CHAR_LIMIT:
        moved_oldest_first.append(remaining.pop())  # 末尾＝最も古いエントリ

    new_decisions_text = render_document(
        doc["preamble_lines"],
        [e["lines"] for e in remaining],
        doc["trailing_lines"],
    )

    # アーカイブへは「新しいものが上」で挿入するため、退避バッチ内の並びを反転する
    # （moved_oldest_first は末尾からpopした順=古い順。反転すると新しい順になる）
    batch_newest_first = list(reversed(moved_oldest_first))

    return {
        "new_decisions_text": new_decisions_text,
        "moved_entries": batch_newest_first,
        "remaining_entries": remaining,
        "original_entries": doc["entries"],
    }


def build_new_archive_text(existing_archive_text, batch_newest_first):
    if existing_archive_text is None:
        lines = list(ARCHIVE_HEADER_LINES)
        for entry in batch_newest_first:
            lines.extend(entry["lines"])
        return "\n".join(lines)

    doc = split_decisions_document(existing_archive_text)
    new_entry_lines = [e["lines"] for e in batch_newest_first] + [e["lines"] for e in doc["entries"]]
    return render_document(doc["preamble_lines"], new_entry_lines, doc["trailing_lines"])


def apply_boundary_sync(decisions_text, archive_text_final):
    """decisions_text冒頭の境界行を、archive側の最終内容(archive_text_final)に整合させる
    （D-0112）。archive_text_final が None の場合は境界行を除去する。
    戻り値: (境界行反映後のdecisions_text, 書き込まれる境界行またはNone)。
    """
    doc = split_decisions_document(decisions_text)
    new_preamble, boundary_line = sync_boundary_line(doc["preamble_lines"], archive_text_final)
    new_text = render_document(new_preamble, [e["lines"] for e in doc["entries"]], doc["trailing_lines"])
    return new_text, boundary_line


def verify_no_loss(original_entries, moved_entries, remaining_entries):
    original_nums = sorted(e["num"] for e in original_entries)
    after_nums = sorted([e["num"] for e in moved_entries] + [e["num"] for e in remaining_entries])
    if original_nums != after_nums:
        raise AssertionError(
            "エントリのD番号集合が移動前後で一致しません（欠損または重複の疑い）: "
            "before=%r after=%r" % (original_nums, after_nums)
        )


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    dry_run = "--dry-run" in sys.argv[1:]

    decisions_text = read_text(DECISIONS_MD)
    before_chars, _ = count_chars_lines(decisions_text)

    plan = plan_archive(decisions_text)
    verify_no_loss(plan["original_entries"], plan["moved_entries"], plan["remaining_entries"])

    existing_archive_text = read_text(ARCHIVE_MD) if os.path.isfile(ARCHIVE_MD) else None

    if not plan["moved_entries"]:
        # 移動対象が無い場合でも、境界行の自己修復（新設・破損時の復旧）は必ず行う
        # （実際に退避が発生した場合と同じ経路を通す・作業指示2）。
        synced_text, boundary_line = apply_boundary_sync(decisions_text, existing_archive_text)
        print("decisions.md は%d字で閾値%d字以下のため、移動対象はありません。" % (before_chars, TARGET_CHAR_LIMIT))
        if boundary_line:
            print("境界行（予定）: %s" % boundary_line)
        else:
            print("境界行（予定）: なし（decisions-archive.md が存在しないため）")
        if dry_run:
            print("--dry-run のため書き込みは行っていません。")
            return
        if synced_text != decisions_text:
            write_text(DECISIONS_MD, synced_text)
            print("境界行を更新しました。")
        return

    moved_nums = sorted(e["num"] for e in plan["moved_entries"])
    new_archive_text = build_new_archive_text(existing_archive_text, plan["moved_entries"])
    new_archive_chars, _ = count_chars_lines(new_archive_text)

    synced_decisions_text, boundary_line = apply_boundary_sync(plan["new_decisions_text"], new_archive_text)
    after_chars, _ = count_chars_lines(synced_decisions_text)

    print("移動対象: %d件（D-%04d 〜 D-%04d）" % (len(moved_nums), moved_nums[0], moved_nums[-1]))
    print("decisions.md: %d字 → %d字" % (before_chars, after_chars))
    print(
        "decisions-archive.md: %s → %d字"
        % (("%d字" % count_chars_lines(existing_archive_text)[0]) if existing_archive_text else "(新規作成)", new_archive_chars)
    )
    print("境界行（予定）: %s" % boundary_line)

    if dry_run:
        print("--dry-run のため書き込みは行っていません。")
        return

    write_text(DECISIONS_MD, synced_decisions_text)
    write_text(ARCHIVE_MD, new_archive_text)
    print("書き込みました。")


if __name__ == "__main__":
    main()
