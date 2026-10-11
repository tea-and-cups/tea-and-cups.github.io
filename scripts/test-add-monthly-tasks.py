# -*- coding: utf-8 -*-
r"""add-monthly-tasks.py の解析・書き込み（--list／--adopt・M番号・重複・上限外の位置・月マーカー）の再発防止テスト（D-0276）。

本物の docs/tasks.md・監査出力には書き込まない。一時ディレクトリに作ったダミーの監査出力と
tasks.md（固定の内容・対象日は実日付と無関係な日付）に対して add-monthly-tasks.py の main() を
そのまま呼び、書き込んだ後の内容で rotate-today-tasks.py の monthly_next_line()（MONTHLY_NEXT の
選び方）をそのまま呼ぶ（テスト側で判定を再実装しない）。

3つ目の群は、本物の docs/tasks.md を一時ディレクトリへ複製したものへ書き込み、本物が1バイトも
変わっていないことを確かめる。4つ目の群は、codex-gateway.py の growth-audit が本物の
growth/ledger/adopted-directives.tsv から GD-0036 の判定対象・判定方法・対象開始を読み、週次の
遵守確認へ配れることを、gateway の読み取り関数を呼んで確かめる（Codex・外部APIは起動せず、
何も書き込まない）。一時ディレクトリは終了時に必ず消す。

使い方:
  python site/scripts/test-add-monthly-tasks.py
"""

import contextlib
import hashlib
import importlib.util
import io
import os
import shutil
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RUN_DATE = "2031-05-15"  # 実日付と無関係な対象日（ダミーの月マーカーは 2031-05）

HEADER = "Q番号\tタグ\tslug\tcategory\tGD番号\t内容\t根拠"
QUEUE_ROWS = [
    "Q-1\t改修\tnew-safe\tteaware\tGD-0033\t保存の助言に出典か適用条件を付ける\t区切り P-1 の所見",
    "Q-2\t改修+画像\tnew-image\tgift\t-\thero画像を差し替え本文の見出しを直す\t区切り S-2 の所見",
    "Q-3\t改修\texist-survey\thow-to\tGD-0032\t調査方法の行を裏取りし直す\t区切り G-1 の所見",
    "Q-4\t新規記事執筆\texist-survey-b\ttea-leaves\t-\t既にある行と同じslugの新規記事\t改善指示3",
    "Q-5\t新規記事執筆\tnew-article\tgift\t-\t冬の贈り物の選び方\t改善指示5",
]
# 重複の照合の補足（同じslugでGD番号が違う改修は書く／GD番号の無い改修はGD番号の無い行と照合する）
QUEUE_ROWS_EXTRA = [
    "Q-1\t改修\texist-survey\thow-to\tGD-0033\t同じ記事の安全の助言を直す\t区切り P-3 の所見",
    "Q-2\t改修\texist-new\tgift\t-\tGD番号の無い行と同じslugの改修\t区切り P-4 の所見",
]

TASKS_HEAD = (
    "# tasks.md — ダミー\n\n"
    "## 今日\n<!-- date: 2031-05-15 -->\n"
    "- [ ] [M-6] [改修] 安全の助言を直す（GD-0033・判定Y）（exist-safe・category: teaware）\n\n"
    "## 今週\n- [x] ダミーの今週の行\n\n"
    "## 今月\n<!-- month: %s -->\n<!-- 行の形の説明（ダミー） -->\n"
)
TASKS_MONTH_ROWS = (
    "- [x] [M-4] [改修] 完了済みの改修（GD-0032・判定X）（done-a・how-to）\n"
    "- [ ] [M-6] [改修] 安全の助言を直す（GD-0033・判定Y）（exist-safe・teaware）（上限外）\n"
    "- [ ] [M-1] [改修] 調査方法を直す（GD-0032・判定X）（exist-survey・how-to）\n"
    "- [ ] [M-2] [改修] 調査方法を直す（GD-0032・判定X）（exist-survey-b・tea-leaves）\n"
    "- [ ] [M-9] [新規記事執筆] 既にある新規記事の候補（exist-new・gift）\n"
)
TASKS_TAIL = "\n## バックログ\n- [ ] ダミーのバックログ（other-slug・gift）\n"


def _load(file_name):
    spec = importlib.util.spec_from_file_location(
        file_name[:-3].replace("-", "_"), os.path.join(SCRIPT_DIR, file_name))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _audit(rows, header=HEADER, fenced=True, heading="## 来月の作業キュー案"):
    """ダミーの監査出力（まとめ）。候補表の前後にほかの節を置く。"""
    table = "\n".join([header] + list(rows))
    if fenced:
        table = "```tsv\n%s\n```" % table
    return ("## 要約\n1.【B】ダミーの要約\n\n## 評価できなかったもの\nなし\n\n"
            "%s\n\n%s\n\n## 監査範囲\n- ダミー\n" % (heading, table))


def _tasks(month="2031-05", rows=TASKS_MONTH_ROWS):
    return (TASKS_HEAD % month) + rows + TASKS_TAIL


def _run(module, argv):
    """main() を呼び、(終了コード, 標準出力) を返す。"""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = module.main(list(argv))
    return code, buffer.getvalue()


def _month_section(rotate, text):
    """今月節のタスク行（- [ ] / - [x]）だけを上から順に返す。"""
    lines = text.split("\n")
    start, end = rotate.find_month_section(lines)
    return [line for line in lines[start + 1:end] if line.startswith("- [")]


def _ids(rows):
    """各行の M番号（M-nn）を上から順に返す。"""
    return ["M-" + row.split("[M-", 1)[1].split("]", 1)[0] for row in rows]


def run_list_cases(module, root):
    results = []
    audit = os.path.join(root, "audit.md")
    _write(audit, _audit(QUEUE_ROWS))
    code, out = _run(module, ["--list", audit])
    lines = out.strip().splitlines()
    results.append(("1-a. 候補表5行 → --list が5行を表示（終了コード0）",
                    code == 0 and len(lines) == 6 and "5件" in lines[0]
                    and all(lines[i + 1].startswith("Q-%d " % (i + 1)) for i in range(5)),
                    "\n" + out.strip()))
    results.append(("1-b. 表示は書き込む行の形（GD-0033 の行だけ末尾の印の後ろに根拠が続く）",
                    "（new-safe・teaware）（上限外） ｜根拠:" in lines[1]
                    and sum("（上限外）" in line for line in lines) == 1, ""))

    _write(audit, _audit(QUEUE_ROWS, fenced=False))
    code, out = _run(module, ["--list", audit])
    results.append(("1-c. コードブロックの囲みが無くても読める", code == 0 and "5件" in out, out.strip().splitlines()[0]))

    broken = list(QUEUE_ROWS)
    broken[2] = "Q-3\t改修\texist-survey\thow-to\tGD-0032\t根拠の列が無い行"   # 6列
    broken[3] = "Q-4\t書き直し\tExist_B\ttea-leaves\tGD-32\t内容\t改善指示3"      # タグ・slug・GD番号
    _write(audit, _audit(broken))
    text_lines = _read(audit).split("\n")
    line_6col = text_lines.index(broken[2]) + 1
    line_bad = text_lines.index(broken[3]) + 1
    code, out = _run(module, ["--list", audit])
    results.append(("1-d. 形式違反の行（列数・タグ・slug・GD番号） → 終了コード1・行番号つきで全件",
                    code == 1 and ("行%d: 列数が6" % line_6col) in out and ("行%d: タグ" % line_bad) in out
                    and "slug「Exist_B」" in out and "GD番号「GD-32」" in out and "形式違反 2件" in out,
                    "\n" + out.strip()))

    _write(audit, _audit([row.replace("\t", "  ") for row in QUEUE_ROWS], header=HEADER.replace("\t", "  ")))
    code, out = _run(module, ["--list", audit])
    results.append(("1-e. タブでなく空白で区切った表 → 終了コード1（列名の行の行番号）",
                    code == 1 and "列名の行が違います" in out and "行" in out, out.strip()))

    _write(audit, _audit(QUEUE_ROWS + ["Q-5\t改修\tdup-q\tgift\t-\tQ番号の重複\t所見",
                                       "Q-6\t改修\tnote-row\tgift\t-\t印を書いた行（上限外）\t所見"]))
    code, out = _run(module, ["--list", audit])
    results.append(("1-f. Q番号の重複・内容に「（上限外）」 → 終了コード1",
                    code == 1 and "Q番号 Q-5 が行" in out and "内容に「（上限外）」" in out, out.strip()))

    _write(audit, _audit(QUEUE_ROWS, heading="## 来月の候補"))
    code, out = _run(module, ["--list", audit])
    results.append(("1-g. 節が無い → 終了コード1", code == 1 and "節がありません" in out, out.strip()))

    _write(audit, _audit([]))
    code, out = _run(module, ["--list", audit])
    results.append(("1-h. 列名の行だけ（候補なし） → 0件・終了コード0", code == 0 and "0件" in out, out.strip()))

    code, out = _run(module, ["--list", os.path.join(root, "no-such-audit.md")])
    results.append(("1-i. 監査出力のファイルが無い → 終了コード1", code == 1 and "見つかりません" in out, out.strip()))
    return results


def run_adopt_cases(module, rotate, root):
    results = []
    audit = os.path.join(root, "audit.md")
    tasks = os.path.join(root, "tasks.md")
    _write(audit, _audit(QUEUE_ROWS))
    _write(tasks, _tasks())
    before = _read(tasks)

    code, out = _run(module, ["--adopt", "Q-1,Q-3,Q-5", "--from", audit, "--tasks", tasks, "--date", RUN_DATE])
    after = _read(tasks)
    rows = _month_section(rotate, after)
    results.append(("2-a. --adopt Q-1,Q-3,Q-5 → 終了コード0・追加2件・重複1件",
                    code == 0 and "ADD_MONTHLY_DONE 追加2件・重複で飛ばした1件" in out, "\n" + out.strip()))
    results.append(("2-b. M番号は今月節の最大（M-9）＋1から通し（M-10・M-11）",
                    "- [ ] [M-10] [改修] 保存の助言に出典か適用条件を付ける（GD-0033）（new-safe・teaware）（上限外）" in rows
                    and "- [ ] [M-11] [新規記事執筆] 冬の贈り物の選び方（new-article・gift）" in rows, ""))
    results.append(("2-c. 未完了行と slug×GD番号 が同じ Q-3 は飛ばされ、既存の行とともに報告される",
                    "重複のため飛ばしました ← Q-3（slug exist-survey × GD番号 GD-0032）" in out
                    and "既存の未完了行: - [ ] [M-1] " in out and not any("[M-12]" in row for row in rows), ""))
    results.append(("2-d. 「（上限外）」が付くのは GD-0033 の行だけ（書き込んだ2行のうち1行）",
                    [row.endswith("（上限外）") for row in rows if "[M-10]" in row or "[M-11]" in row] == [True, False],
                    ""))
    results.append(("2-e. 位置: 上限外の行は最初の「上限外でない未完了行」（M-1）の直前・それ以外は今月節の末尾",
                    _ids(rows) == ["M-4", "M-6", "M-10", "M-1", "M-2", "M-9", "M-11"], " → ".join(_ids(rows))))
    outside_before = before.split("## 今月")[0] + before.split("## バックログ")[1]
    outside_after = after.split("## 今月")[0] + after.split("## バックログ")[1]
    results.append(("2-f. 今月節以外（今日・今週・バックログ）と月マーカー・コメント行は変わらない",
                    outside_before == outside_after and "<!-- month: 2031-05 -->\n<!-- 行の形の説明（ダミー） -->\n- [x] [M-4]" in after
                    and after.count("\n\n## バックログ") == 1, ""))

    # 書き込んだ後の内容で、rotate-today-tasks.py の MONTHLY_NEXT の選び方を確かめる
    lines = after.split("\n")
    next_line = rotate.monthly_next_line(lines)
    results.append(("2-g. MONTHLY_NEXT は従来どおり既存の上限外の行（M-6）",
                    next_line.startswith("MONTHLY_NEXT: - [ ] [M-6] "), next_line))
    lines = [line.replace("- [ ] [M-6]", "- [x] [M-6]") if line.startswith("- [ ] [M-6]") else line for line in lines]
    next_line = rotate.monthly_next_line(lines)
    results.append(("2-h. M-6 の完了後は、書き込んだ上限外の行（M-10）が M-1 より先に選ばれる",
                    next_line.startswith("MONTHLY_NEXT: - [ ] [M-10] "), next_line))
    lines = [line.replace("- [ ] [M-10]", "- [x] [M-10]") if line.startswith("- [ ] [M-10]") else line for line in lines]
    next_line = rotate.monthly_next_line(lines)
    results.append(("2-i. 上限外の行がすべて完了すれば、上限に数える改修（M-1）へ進む",
                    next_line.startswith("MONTHLY_NEXT: - [ ] [M-1] "), next_line))

    # 改修の上限に達している月: 上限外の行は飛ばされず、上限に数える改修は保留になる
    capped_rows = "".join(
        "- [x] [M-%d] [改修] 完了済みの改修（GD-0032・判定X）（done-%d・how-to）\n" % (n, n) for n in (20, 21, 22, 23)
    ) + TASKS_MONTH_ROWS.split("\n", 2)[2]  # M-4・M-6 の行を除き、上限外の未完了行が無い状態にする
    _write(tasks, _tasks(rows=capped_rows))
    code, out = _run(module, ["--adopt", "Q-1,Q-5", "--from", audit, "--tasks", tasks, "--date", RUN_DATE])
    lines = _read(tasks).split("\n")
    rows = _month_section(rotate, "\n".join(lines))
    next_line = rotate.monthly_next_line(lines)
    results.append(("2-j. 上限到達（4/4）の月: 上限外の行（M-24）が先頭の未完了行の前に入り、MONTHLY_NEXT に選ばれる",
                    code == 0 and _ids(rows) == ["M-20", "M-21", "M-22", "M-23", "M-24", "M-1", "M-2", "M-9", "M-25"]
                    and next_line.startswith("MONTHLY_NEXT: - [ ] [M-24] ") and "（改修上限 4/4・保留2行）" in next_line,
                    next_line))
    lines = [line.replace("- [ ] [M-24]", "- [x] [M-24]") if line.startswith("- [ ] [M-24]") else line for line in lines]
    next_line = rotate.monthly_next_line(lines)
    results.append(("2-k. その完了後は、保留の改修を飛ばして新規記事（M-9）が選ばれる（上限外の完了は上限に数えない）",
                    next_line.startswith("MONTHLY_NEXT: - [ ] [M-9] ") and "（改修上限 4/4・保留2行）" in next_line,
                    next_line))

    # 重複の照合の補足
    _write(tasks, _tasks())
    code, out = _run(module, ["--adopt", "Q-4,Q-2", "--from", audit, "--tasks", tasks, "--date", RUN_DATE])
    rows = _month_section(rotate, _read(tasks))
    results.append(("2-l. 新規記事の候補（Q-4）は slug だけで照合して飛ばす（既存の行は GD-0032 の改修）・Q-2 は書く",
                    code == 0 and "重複のため飛ばしました ← Q-4（slug exist-survey-b）" in out
                    and rows[-1] == "- [ ] [M-10] [改修+画像] hero画像を差し替え本文の見出しを直す（new-image・gift）",
                    "\n" + out.strip()))
    code, out = _run(module, ["--adopt", "Q-2", "--from", audit, "--tasks", tasks, "--date", RUN_DATE])
    results.append(("2-m. 同じQ番号をもう一度採用しても、書き込み済みの行と重複して飛ばされる（ファイルは変わらない）",
                    code == 0 and "追加0件・重複で飛ばした1件" in out
                    and _month_section(rotate, _read(tasks)) == rows, out.strip()))
    extra = os.path.join(root, "audit-extra.md")
    _write(extra, _audit(QUEUE_ROWS_EXTRA))
    _write(tasks, _tasks())
    code, out = _run(module, ["--adopt", "Q-1,Q-2", "--from", extra, "--tasks", tasks, "--date", RUN_DATE])
    rows = _month_section(rotate, _read(tasks))
    results.append(("2-n. 同じslugでもGD番号が違う改修は書く／GD番号の無い改修はGD番号の無い行と重複",
                    code == 0 and "- [ ] [M-10] [改修] 同じ記事の安全の助言を直す（GD-0033）（exist-survey・how-to）（上限外）" in rows
                    and "重複のため飛ばしました ← Q-2（slug exist-new × GD番号 -）" in out, "\n" + out.strip()))

    # 何も書かずに止まる場合
    _write(tasks, _tasks(month="2031-04"))
    digest = _sha(tasks)
    code, out = _run(module, ["--adopt", "Q-1,Q-3,Q-5", "--from", audit, "--tasks", tasks, "--date", RUN_DATE])
    results.append(("3-a. 月マーカー（2031-04）が実行月（2031-05）と違う → 終了コード1・ファイルは変わらない",
                    code == 1 and "月マーカー（2031-04）が実行月（2031-05）と違う" in out and _sha(tasks) == digest,
                    out.strip()))
    _write(tasks, _tasks().replace("<!-- month: 2031-05 -->\n", ""))
    digest = _sha(tasks)
    code, out = _run(module, ["--adopt", "Q-1", "--from", audit, "--tasks", tasks, "--date", RUN_DATE])
    results.append(("3-b. 月マーカーが無い → 終了コード1・ファイルは変わらない",
                    code == 1 and "読み取れない" in out and _sha(tasks) == digest, out.strip()))
    _write(tasks, _tasks())
    digest = _sha(tasks)
    code, out = _run(module, ["--adopt", "Q-1,Q-9", "--from", audit, "--tasks", tasks, "--date", RUN_DATE])
    results.append(("3-c. 表に無いQ番号が混ざる → 終了コード1・ファイルは変わらない",
                    code == 1 and "表に無いQ番号です: Q-9" in out and _sha(tasks) == digest, out.strip()))
    broken = list(QUEUE_ROWS)
    broken[4] = "Q-5\t新規記事執筆\tnew-article\tgift\t-\t根拠の列が無い行"
    _write(audit, _audit(broken))
    code, out = _run(module, ["--adopt", "Q-1", "--from", audit, "--tasks", tasks, "--date", RUN_DATE])
    results.append(("3-d. 採用しない行でも表に形式違反があれば → 終了コード1・ファイルは変わらない",
                    code == 1 and "形式違反 1件" in out and _sha(tasks) == digest, out.strip()))
    return results


def run_real_copy_case(module, rotate, root):
    """本物の docs/tasks.md の複製へ書き込み、本物が変わらないことと、複製の MONTHLY_NEXT を確かめる。"""
    real = module.TASKS_MD
    digest = _sha(real)
    copy = os.path.join(root, "real-copy", "tasks.md")
    os.makedirs(os.path.dirname(copy))
    shutil.copyfile(real, copy)
    lines = _read(copy).split("\n")
    start, end = rotate.find_month_section(lines)
    month = next((rotate.MONTH_MARKER_RE.match(lines[i].strip()).group(1)
                  for i in range(start + 1, end) if rotate.MONTH_MARKER_RE.match(lines[i].strip())), None)
    open_rows = [row for row in module.month_rows(lines, start, end) if row["open"]]
    numbers = [int(n) for i in range(start + 1, end) for n in module.M_NUMBER_RE.findall(lines[i])]
    top = max(numbers) if numbers else 0
    next_before = rotate.monthly_next_line(lines)

    # Q-3 は、複製にある未完了行（slug と GD番号 を持つ最初の行）と同じ slug×GD番号 にする
    existing = next((row for row in open_rows if row["slug"] and row["gds"]), None)
    rows = list(QUEUE_ROWS)
    rows[0] = "Q-1\t改修\tzz-test-new-safe\tteaware\tGD-0033\t検証用のダミー（上限外になる行）\t検証"
    rows[4] = "Q-5\t新規記事執筆\tzz-test-new-article\tgift\t-\t検証用のダミー（新規記事）\t検証"
    if existing:
        rows[2] = "Q-3\t改修\t%s\thow-to\t%s\t検証用のダミー（既存の行と重複）\t検証" % (
            existing["slug"], sorted(existing["gds"])[0])
    audit = os.path.join(root, "real-copy", "audit.md")
    _write(audit, _audit(rows))

    code, out = _run(module, ["--adopt", "Q-1,Q-3,Q-5", "--from", audit, "--tasks", copy,
                              "--date", "%s-15" % month])
    after = _read(copy).split("\n")
    month_rows = _month_section(rotate, "\n".join(after))
    next_after = rotate.monthly_next_line(after)
    new_exempt = "- [ ] [M-%d] [改修] 検証用のダミー（上限外になる行）（GD-0033）（zz-test-new-safe・teaware）（上限外）" % (top + 1)
    new_article = "- [ ] [M-%d] [新規記事執筆] 検証用のダミー（新規記事）（zz-test-new-article・gift）" % (top + 2)
    first_capped = next((row["text"] for row in open_rows if not row["exempt"]), None)
    results = [
        ("4-a. 本物の docs/tasks.md の複製（月マーカー %s・今月節の最大 M-%d）へ --adopt Q-1,Q-3,Q-5 → 終了コード0"
         % (month, top), code == 0, "\n" + out.strip()),
        ("4-b. M-%d（上限外）・M-%d が書かれ、新規記事の行は今月節の末尾" % (top + 1, top + 2),
         new_exempt in month_rows and month_rows[-1] == new_article, ""),
        ("4-c. 上限外の行は最初の「上限外でない未完了行」の直前（無ければ末尾側）",
         first_capped is None or month_rows.index(new_exempt) + 1 == month_rows.index(first_capped),
         "直後の行: %s" % (first_capped or "（該当なし）")),
    ]
    if existing:
        results.append(("4-d. 既存の未完了行と slug×GD番号 が同じ Q-3 は飛ばされる",
                        "重複のため飛ばしました ← Q-3" in out and "ADD_MONTHLY_DONE 追加2件・重複で飛ばした1件" in out, ""))
    # 既存の未完了の先頭が上限外の行なら MONTHLY_NEXT は変わらない。そうでなければ書き込んだ上限外の行になる。
    head_exempt = bool(open_rows) and open_rows[0]["exempt"]
    expected = next_before if head_exempt else "MONTHLY_NEXT: " + new_exempt
    results.append(("4-e. 複製の MONTHLY_NEXT は%s" % ("書き込み前と同じ（既存の上限外の行が先頭）" if head_exempt
                                                 else "書き込んだ上限外の行"),
                    next_after.startswith(expected), "前: %s\n      後: %s" % (next_before, next_after)))
    results.append(("4-f. 本物の docs/tasks.md は1バイトも変わっていない（sha256 一致）",
                    _sha(real) == digest, digest[:16]))
    results.append(("4-g. 複製の今月節（書き込み後）の並び", True, " → ".join(_ids(month_rows))))
    return results


def run_growth_ledger_case():
    """台帳 GD-0036 の判定対象・判定方法・対象開始を gateway が読め、週次の遵守確認へ配れることを確かめる。"""
    gateway = _load("codex-gateway.py")
    since, until, week = "2026-10-12", "2026-10-18", "2026-W42"
    rows = {(row.get("ID") or "").strip(): row for row in gateway._ledger_adopted_rows()}
    row = rows.get("GD-0036") or {}
    plan = gateway._weekly_compliance_plan(since, until, week)
    gd = next((item for item in plan["gds"] if item["id"] == "GD-0036"), None)
    results = [
        ("5-a. 台帳の GD-0036 は11列がそろい、判定対象・判定方法・対象開始が埋まっている",
         all((row.get(key) or "").strip() for key in ("判定対象", "判定方法", "対象開始"))
         and set(row) == {"ID", "週", "区分", "指示", "採否", "実装D番号", "実装日", "遵守確認",
                          "判定対象", "判定方法", "対象開始"},
         "\n      判定対象: %s\n      判定方法: %s\n      対象開始: %s\n      遵守確認: %s" % (
             row.get("判定対象"), row.get("判定方法"), row.get("対象開始"), row.get("遵守確認"))),
        ("5-b. 判定方法は check-pin-image-style.py の検査で、実装状況の文は判定方法の列に残っていない",
         "check-pin-image-style.py" in (row.get("判定方法") or "") and "実装済み" not in (row.get("判定方法") or "")
         and "実装済み" in (row.get("遵守確認") or ""), ""),
        ("5-c. 週次（%s〜%s）の遵守確認の計画で GD-0036 が区切りへ配る対象になる（事前の「判定不能」でない）"
         % (since, until),
         gd is not None and gd["start"] == ("date", "2026-10-12") and "GD-0036" not in plan["prefilled"],
         "判定対象の種別=%s／対象開始=%s" % ("・".join(kind for kind, _r in gd["specs"]),
                                    gateway._gd_start_label(gd["start"]))
         if gd else "事前判定: %s" % (plan["prefilled"].get("GD-0036"),)),
    ]
    if gd is not None:
        objects = [
            {"kind": "Pin", "date": "2026-10-11", "number": 352, "label": "ピン352（2026-10-11付）"},
            {"kind": "Pin", "date": "2026-10-12", "number": 353, "label": "ピン353（2026-10-12付・検証用）"},
            {"kind": "記事", "date": "2026-10-12", "label": "記事（検証用）"},
        ]
        matched = gateway._gd_matches_for_objects(plan, objects).get("GD-0036", [])
        results.append(("5-d. 生成物の区切りでは、対象開始以降のピンにだけ GD-0036 が割り当たる（記事・対象開始より前のピンは外れる）",
                        matched == ["ピン353（2026-10-12付・検証用）"], "該当: %s" % "、".join(matched)))
        by_path = gateway._gd_matches_for_path(plan, "site/scripts/make-image-prompt.py").get("GD-0036", [])
        results.append(("5-e. ルールの区切りでは、期間内に make-image-prompt.py が変わったときに GD-0036 が割り当たる",
                        bool(by_path), "該当: %s" % "、".join(by_path)))
        block = gateway._format_directives_block(plan, {"GD-0036": matched})
        results.append(("5-f. 区切りのプロンプトへ差し込む GD-0036 の割り当てを組み立てられる",
                        "check-pin-image-style.py" in block and "対象開始: 2026-10-12以降" in block, "\n" + block))
    return results


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    module = _load("add-monthly-tasks.py")
    rotate = module.rotate
    root = tempfile.mkdtemp(prefix="add_monthly_tasks_test_")
    groups = []
    try:
        groups.append(("--list（ダミーの監査出力）", run_list_cases(module, root)))
        groups.append(("--adopt（ダミーの tasks.md・対象日 %s）と MONTHLY_NEXT の選び方" % RUN_DATE,
                       run_adopt_cases(module, rotate, root)))
        groups.append(("本物の docs/tasks.md の複製への書き込み（本物は書き換えない）",
                       run_real_copy_case(module, rotate, root)))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    groups.append(("後片付け", [("一時ディレクトリ（ダミーの監査出力・tasks.md・複製）を削除済み: %s" % root,
                            not os.path.exists(root), "")]))
    groups.append(("codex-gateway.py の growth-audit が台帳 GD-0036 を読み込める（Codex・外部APIは起動しない）",
                   run_growth_ledger_case()))

    failures = []
    total = 0
    for title, cases in groups:
        print("=== %s ===" % title)
        for description, ok, detail in cases:
            total += 1
            if not ok:
                failures.append(description)
            print("[%s] %s%s" % ("OK" if ok else "NG", description, " — %s" % detail if detail else ""))
        print()
    if failures:
        print("失敗: %d件 / 全%d件" % (len(failures), total))
        for description in failures:
            print("  - %s" % description)
        sys.exit(1)
    print("全%d件のテストにパスしました。" % total)


if __name__ == "__main__":
    main()
