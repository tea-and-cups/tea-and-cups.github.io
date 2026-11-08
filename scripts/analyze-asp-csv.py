# -*- coding: utf-8 -*-
r"""ASP成果CSV（もしもの日次CSV・楽天の monthly.csv）を期間で集計し、レポートに貼れる文章で出す（読み取り専用・L075）。

背景: 週次と月次の第2段のたびに、もしもの日次CSVと楽天の monthly.csv をその場限りの
コマンドで手集計していた（L075・rules/command-execution.md 3節）。集計を本スクリプトに
固定し、あわせて「頼まれた期間のうちCSVに含まれない日」を機械的に「未取得」として出す
（W45 で10月分が欠けていたことを、人が気づく形にしないため）。

入力:
  CSVファイルを位置引数で1つ以上渡す（もしも・楽天の順不同・それぞれ複数可）。
  取得元はファイル名ではなく中身の見出しで見分ける。どちらの形とも一致しないファイル、
  見出しの列が想定と1つでも違うファイルは、推測で読まずにエラーで止まる。
    もしも: CP932。1行目が次の見出しと完全一致すること。
            成果発生日,インプレッション数,クリック数,クリック金額,発生成果数,発生成果金額,承認成果数,承認成果金額,報酬額
            日付は「YYYY年MM月DD日」。金額は「\1,234」「￥1,234」の形（円記号・桁区切りを外して数値にする）。
    楽天:   UTF-8（BOMの有無どちらも）。1行目が「期間別成果: YYYY.MM」、続いて
            発生日,成果報酬,クリック数,売上件数,売上金額 と date,rewards,clicks,sales,amount の2行。
            クリック・成果の無い日は行が出ない。

集計の決まり:
  - もしもと楽天は合算しない（rules/weekly-report.md 4-1節）。出力は取得元ごとに分ける。
  - もしも: 期間のうち、どのファイルにも行の無い日を「未取得」として列挙する。
  - 楽天: どのファイルの対象月にも入らない日を「未取得」として列挙する。対象月の中で
    行の無い日は0とみなし、その旨を出す。楽天のCSVには承認の列が無いため「確定は未確認」と出す。
  - 同じ日が複数のファイルにある場合（月をまたぐ取得・取り直し）は1回だけ数える。
    値が食い違うときは、どちらが正しいかを推測せずエラーで止める（新しい方だけを渡し直す）。
    楽天で同じ対象月のファイルが2つあり中身が違う場合も同様に止める。

出力: 標準出力のみ。どのファイルにも書き込まない（--self-test だけは一時フォルダに
      ダミーのCSVを作り、終わったら消す）。

終了コード:
  0  期間の全日が、もしも・楽天とも取得済み
  2  一部の日が未取得（集計は出す）。未取得の範囲をレポートに書き、オーナーへCSVを依頼する
  1  読めない（ファイルが無い・文字コード・見出しの不一致・値の食い違い・引数の誤り）

使い方:
  python site/scripts/analyze-asp-csv.py --since 2026-10-26 --until 2026-11-01 <CSV> [<CSV> ...]
  python site/scripts/analyze-asp-csv.py --self-test
"""

import argparse
import csv
import datetime
import hashlib
import io
import os
import re
import shutil
import sys
import tempfile

MOSHIMO_HEADER = [
    "成果発生日", "インプレッション数", "クリック数", "クリック金額",
    "発生成果数", "発生成果金額", "承認成果数", "承認成果金額", "報酬額",
]
MOSHIMO_KEYS = ["impressions", "clicks", "click_amount", "occurred", "occurred_amount",
                "approved", "approved_amount", "payout"]
RAKUTEN_HEADER_JA = ["発生日", "成果報酬", "クリック数", "売上件数", "売上金額"]
RAKUTEN_HEADER_EN = ["date", "rewards", "clicks", "sales", "amount"]
RAKUTEN_KEYS = ["rewards", "clicks", "sales", "amount"]

RE_RAKUTEN_PERIOD = re.compile(r"^期間別成果:\s*(\d{4})\.(\d{1,2})$")
RE_MOSHIMO_DATE = re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日$")
RE_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
RE_NUMBER = re.compile(r"^-?\d+$")
YEN_SIGNS = ("\\", "￥", "¥")


class CsvError(Exception):
    """読めないファイル（終了コード1）。"""


# ---------------------------------------------------------------- 読み取り

def parse_number(cell, path, line_no):
    s = cell.strip()
    for sign in YEN_SIGNS:
        if s.startswith(sign):
            s = s[len(sign):]
            break
    if s.endswith("円"):
        s = s[:-1]
    s = s.replace(",", "")
    if not RE_NUMBER.match(s):
        raise CsvError("%s: %d行目の値「%s」を数値として読めません" % (path, line_no, cell))
    return int(s)


def rows_of(text):
    """(行番号, セルのリスト) を返す。空行は飛ばす。"""
    out = []
    for i, row in enumerate(csv.reader(io.StringIO(text, newline="")), start=1):
        if not row or all(c.strip() == "" for c in row):
            continue
        out.append((i, [c.strip() for c in row]))
    return out


def detect_and_decode(path, data):
    """中身の見出しで取得元を見分ける。('moshimo'|'rakuten', 文字列, 文字コード名) を返す。"""
    try:
        text_u = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text_u = None
    try:
        text_s = data.decode("cp932")
    except UnicodeDecodeError:
        text_s = None

    def first_row(text):
        rows = rows_of(text) if text is not None else []
        return rows[0][1] if rows else []

    fu = first_row(text_u)
    fs = first_row(text_s)
    if fu and RE_RAKUTEN_PERIOD.match(fu[0]):
        enc = "UTF-8（BOMあり）" if data.startswith(b"\xef\xbb\xbf") else "UTF-8"
        return "rakuten", text_u, enc
    if fs and fs[0] == MOSHIMO_HEADER[0]:
        if fs != MOSHIMO_HEADER:
            raise CsvError("%s: もしもの見出しの列が想定と違います（推測では読みません）\n  想定: %s\n  実際: %s"
                           % (path, ",".join(MOSHIMO_HEADER), ",".join(fs)))
        return "moshimo", text_s, "CP932"
    if fu and fu[0] == MOSHIMO_HEADER[0]:
        raise CsvError("%s: もしもの見出しですが、CP932ではなくUTF-8で保存されています（管理画面から取り直してください）" % path)
    if fs and RE_RAKUTEN_PERIOD.match(fs[0]):
        raise CsvError("%s: 楽天の形式ですが、UTF-8として読めません" % path)
    if text_u is None and text_s is None:
        raise CsvError("%s: UTF-8・CP932のどちらとしても読めません" % path)
    head = ",".join(fu or fs)
    raise CsvError("%s: もしも・楽天のどちらの見出しとも一致しません（先頭行: %s）" % (path, head[:120]))


def parse_moshimo(path, text):
    rows = rows_of(text)
    days = {}
    for line_no, row in rows[1:]:
        if len(row) != len(MOSHIMO_HEADER):
            raise CsvError("%s: %d行目の列の数が%dです（想定%d）" % (path, line_no, len(row), len(MOSHIMO_HEADER)))
        m = RE_MOSHIMO_DATE.match(row[0])
        if not m:
            raise CsvError("%s: %d行目の日付「%s」が「YYYY年MM月DD日」の形ではありません" % (path, line_no, row[0]))
        try:
            d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            raise CsvError("%s: %d行目の日付「%s」が実在しません" % (path, line_no, row[0]))
        if d in days:
            raise CsvError("%s: %s の行が同じファイルに2つあります" % (path, d.isoformat()))
        days[d] = dict(zip(MOSHIMO_KEYS, [parse_number(c, path, line_no) for c in row[1:]]))
    if not days:
        raise CsvError("%s: もしもの見出しのみで、日付の行がありません" % path)
    return days


def parse_rakuten(path, text):
    rows = rows_of(text)
    m = RE_RAKUTEN_PERIOD.match(rows[0][1][0])
    year, month = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        raise CsvError("%s: 対象月「%s」が読めません" % (path, rows[0][1][0]))
    if len(rows) < 3 or rows[1][1] != RAKUTEN_HEADER_JA or rows[2][1] != RAKUTEN_HEADER_EN:
        got_ja = ",".join(rows[1][1]) if len(rows) > 1 else "（なし）"
        got_en = ",".join(rows[2][1]) if len(rows) > 2 else "（なし）"
        raise CsvError("%s: 楽天の見出しの列が想定と違います（推測では読みません）\n  想定: %s / %s\n  実際: %s / %s"
                       % (path, ",".join(RAKUTEN_HEADER_JA), ",".join(RAKUTEN_HEADER_EN), got_ja, got_en))
    days = {}
    for line_no, row in rows[3:]:
        if len(row) != len(RAKUTEN_HEADER_EN):
            raise CsvError("%s: %d行目の列の数が%dです（想定%d）" % (path, line_no, len(row), len(RAKUTEN_HEADER_EN)))
        dm = RE_ISO_DATE.match(row[0])
        if not dm:
            raise CsvError("%s: %d行目の日付「%s」が YYYY-MM-DD の形ではありません" % (path, line_no, row[0]))
        try:
            d = datetime.date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
        except ValueError:
            raise CsvError("%s: %d行目の日付「%s」が実在しません" % (path, line_no, row[0]))
        if (d.year, d.month) != (year, month):
            raise CsvError("%s: %d行目の日付 %s が対象月 %d.%02d に入りません" % (path, line_no, row[0], year, month))
        if d in days:
            raise CsvError("%s: %s の行が同じファイルに2つあります" % (path, d.isoformat()))
        days[d] = dict(zip(RAKUTEN_KEYS, [parse_number(c, path, line_no) for c in row[1:]]))
    return (year, month), days


def load_inputs(paths):
    """全ファイルを読み、取得元ごとにまとめる。食い違いがあれば CsvError。"""
    moshimo_days, moshimo_files, moshimo_dup = {}, [], set()
    rakuten_months, rakuten_files, rakuten_dup_months = {}, [], set()
    day_source = {}
    for path in paths:
        if not os.path.isfile(path):
            raise CsvError("%s: ファイルがありません" % path)
        with open(path, "rb") as f:
            data = f.read()
        try:
            kind, text, enc = detect_and_decode(path, data)
            parsed = parse_moshimo(path, text) if kind == "moshimo" else parse_rakuten(path, text)
        except csv.Error as e:
            raise CsvError("%s: CSVとして読めません（%s）" % (path, e))
        name = os.path.basename(path)
        if kind == "moshimo":
            days = parsed
            for d, vals in days.items():
                if d in moshimo_days:
                    if moshimo_days[d] != vals:
                        raise CsvError("もしも: %s の値が %s と %s で違います（どちらが正しいか推測しません。新しい方のファイルだけを渡してください）"
                                       % (d.isoformat(), day_source[d], name))
                    moshimo_dup.add(d)
                else:
                    moshimo_days[d] = vals
                    day_source[d] = name
            moshimo_files.append((name, enc, min(days), max(days)))
        else:
            ym, days = parsed
            if ym in rakuten_months:
                prev_name, prev_days = rakuten_months[ym]
                if prev_days != days:
                    raise CsvError("楽天: 対象月 %d.%02d のファイルが2つあり、中身が違います（%s・%s）。新しい方だけを渡してください"
                                   % (ym[0], ym[1], prev_name, name))
                rakuten_dup_months.add(ym)
            else:
                rakuten_months[ym] = (name, days)
            rakuten_files.append((name, enc, ym))
    return {
        "moshimo_days": moshimo_days, "moshimo_files": moshimo_files, "moshimo_dup": moshimo_dup,
        "rakuten_months": rakuten_months, "rakuten_files": rakuten_files,
        "rakuten_dup_months": rakuten_dup_months,
    }


# ---------------------------------------------------------------- 集計と出力

def date_range(since, until):
    d = since
    while d <= until:
        yield d
        d += datetime.timedelta(days=1)


def fmt_day(d, multi_year):
    return d.isoformat() if multi_year else d.strftime("%m-%d")


def fmt_ranges(days, multi_year):
    """連続する日をまとめ「10-26〜10-31（6日）」の形にする。"""
    days = sorted(days)
    parts = []
    i = 0
    while i < len(days):
        j = i
        while j + 1 < len(days) and days[j + 1] - days[j] == datetime.timedelta(days=1):
            j += 1
        if i == j:
            parts.append(fmt_day(days[i], multi_year))
        else:
            parts.append("%s〜%s" % (fmt_day(days[i], multi_year), fmt_day(days[j], multi_year)))
        i = j + 1
    return "・".join(parts) + "（%d日）" % len(days)


def breakdown(day_vals, key, multi_year, amount_key=None):
    items = []
    for d in sorted(day_vals):
        v = day_vals[d][key]
        if v == 0 and (amount_key is None or day_vals[d][amount_key] == 0):
            continue
        if amount_key:
            items.append("%s=%d件・%s円" % (fmt_day(d, multi_year), v, "{:,}".format(day_vals[d][amount_key])))
        else:
            items.append("%s=%d" % (fmt_day(d, multi_year), v))
    return "／".join(items)


def with_detail(text, detail):
    return "%s（%s）" % (text, detail) if detail else text


def yen(n):
    return "{:,}円".format(n)


def summarize(inputs, since, until, out):
    """集計を out に書き、未取得の日数 (もしも, 楽天) を返す。"""
    period = list(date_range(since, until))
    multi_year = since.year != until.year
    span = "%s〜%s（%d日）" % (since.isoformat(), until.isoformat(), len(period))

    out.append("対象期間: %s。もしもと楽天は合算しない（rules/weekly-report.md 4-1節）。" % span)
    for name, enc, first, last in inputs["moshimo_files"]:
        out.append("- 入力（もしも）: `%s`（%s・行のある日 %s〜%s）" % (name, enc, first.isoformat(), last.isoformat()))
    for name, enc, ym in inputs["rakuten_files"]:
        out.append("- 入力（楽天）: `%s`（%s・期間別成果: %d.%02d）" % (name, enc, ym[0], ym[1]))
    out.append("")

    # もしも
    md = inputs["moshimo_days"]
    got = {d: md[d] for d in period if d in md}
    missing_m = [d for d in period if d not in md]
    if got:
        tot = {k: sum(v[k] for v in got.values()) for k in MOSHIMO_KEYS}
        out.append("- もしも（取得済み %s）: クリック**%d件**／発生成果**%d件（%s）**／承認成果**%d件（%s）**／報酬額**%s**。"
                   % (fmt_ranges(list(got), multi_year), tot["clicks"], tot["occurred"], yen(tot["occurred_amount"]),
                      tot["approved"], yen(tot["approved_amount"]), yen(tot["payout"])))
        out.append("  - 日別（0以外の日のみ）: " + "　".join([s for s in [
            with_detail("クリック", breakdown(got, "clicks", multi_year)) if tot["clicks"] else "",
            with_detail("発生", breakdown(got, "occurred", multi_year, "occurred_amount")) if tot["occurred"] or tot["occurred_amount"] else "",
            with_detail("承認", breakdown(got, "approved", multi_year, "approved_amount")) if tot["approved"] or tot["approved_amount"] else "",
            with_detail("報酬額", "／".join("%s=%s" % (fmt_day(d, multi_year), yen(got[d]["payout"]))
                                            for d in sorted(got) if got[d]["payout"])) if tot["payout"] else "",
        ] if s] or ["なし（取得済みの日はすべて0）"]))
    elif inputs["moshimo_files"]:
        out.append("- もしも: 期間内に行のある日がありません。")
    else:
        out.append("- もしも: 入力なし。")
    if inputs["moshimo_dup"] & set(period):
        out.append("  - 複数のファイルに同じ値で出ていた日は1回だけ数えた: %s"
                   % fmt_ranges(list(inputs["moshimo_dup"] & set(period)), multi_year))
    if missing_m:
        out.append("- もしも **未取得**: %s" % fmt_ranges(missing_m, multi_year))

    # 楽天
    months = inputs["rakuten_months"]
    covered = [d for d in period if (d.year, d.month) in months]
    missing_r = [d for d in period if (d.year, d.month) not in months]
    if covered:
        rows = {}
        for d in covered:
            vals = months[(d.year, d.month)][1].get(d)
            if vals is not None:
                rows[d] = vals
        zero_days = [d for d in covered if d not in rows]
        tot = {k: sum(v[k] for v in rows.values()) for k in RAKUTEN_KEYS}
        cov_months = sorted({(d.year, d.month) for d in covered})
        out.append("- 楽天（対象月 %s・取得済み %s）: クリック**%d件**／成果（売上件数）**%d件**（売上金額%s・成果報酬%d）。確定は未確認（CSVに承認の列が無い）。"
                   % ("・".join("%d.%02d" % ym for ym in cov_months), fmt_ranges(covered, multi_year),
                      tot["clicks"], tot["sales"], yen(tot["amount"]), tot["rewards"]))
        if rows:
            out.append("  - 日別（行のある日）: " + "　".join([s for s in [
                with_detail("クリック", breakdown(rows, "clicks", multi_year)) if tot["clicks"] else "",
                with_detail("成果", "／".join("%s=%d件・売上%s・報酬%d" % (fmt_day(d, multi_year), rows[d]["sales"],
                                                                          yen(rows[d]["amount"]), rows[d]["rewards"])
                                               for d in sorted(rows) if rows[d]["sales"] or rows[d]["rewards"])) if tot["sales"] or tot["rewards"] else "",
            ] if s] or ["行はあるがすべて0"]))
        else:
            out.append("  - 期間内に行はありません。")
        if zero_days:
            out.append("  - 対象月の中で行の無い日は0とみなした: %s" % fmt_ranges(zero_days, multi_year))
            out.append("  - 楽天のCSVには取得日時が無いため、CSVを取得した日より後の日も0として数えている可能性がある。")
    elif inputs["rakuten_files"]:
        out.append("- 楽天: 期間内の日を含む対象月のファイルがありません。")
    else:
        out.append("- 楽天: 入力なし。")
    if missing_r:
        out.append("- 楽天 **未取得**: %s" % fmt_ranges(missing_r, multi_year))

    out.append("")
    if missing_m or missing_r:
        out.append("ASP_CSV_PARTIAL 未取得あり（もしも%d日・楽天%d日）。未取得の範囲をレポートに書き、オーナーへCSVを依頼する（rules/weekly-report.md 4節）。"
                   % (len(missing_m), len(missing_r)))
    else:
        out.append("ASP_CSV_COMPLETE 期間の全日が、もしも・楽天とも取得済み。")
    return len(missing_m), len(missing_r)


def parse_iso(s):
    m = RE_ISO_DATE.match(s or "")
    if not m:
        raise CsvError("日付「%s」は YYYY-MM-DD の形で指定してください" % s)
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        raise CsvError("日付「%s」が実在しません" % s)


def run(argv, write=print):
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--since")
    parser.add_argument("--until")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("files", nargs="*")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 1
    if args.self_test:
        return self_test(write)
    try:
        if not args.since or not args.until:
            raise CsvError("--since と --until を指定してください")
        since, until = parse_iso(args.since), parse_iso(args.until)
        if since > until:
            raise CsvError("--since（%s）が --until（%s）より後です" % (args.since, args.until))
        if not args.files:
            raise CsvError("CSVファイルを1つ以上渡してください")
        inputs = load_inputs(args.files)
        out = []
        miss_m, miss_r = summarize(inputs, since, until, out)
    except CsvError as e:
        write("ASP_CSV_ERROR %s" % e)
        return 1
    for line in out:
        write(line)
    return 2 if (miss_m or miss_r) else 0


# ---------------------------------------------------------------- 自己テスト

MOSHIMO_HEADER_LINE = ",".join(MOSHIMO_HEADER)


def _moshimo_csv(rows, header=MOSHIMO_HEADER_LINE):
    return (header + "\r\n" + "".join(r + "\r\n" for r in rows)).encode("cp932")


def _rakuten_csv(ym, rows, bom=True, header_ja=",".join(RAKUTEN_HEADER_JA)):
    text = '"期間別成果: %s"\n\n%s\n%s\n%s' % (ym, header_ja, ",".join(RAKUTEN_HEADER_EN), "".join(r + "\n" for r in rows))
    return (b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8")


def _sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def self_test(write=print):
    tmp = tempfile.mkdtemp(prefix="analyze-asp-csv-")
    results = []

    def put(name, data):
        p = os.path.join(tmp, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def call(argv):
        lines = []
        code = run(argv, write=lines.append)
        return code, "\n".join(lines)

    def check(label, ok, detail=""):
        results.append(ok)
        write("%s %s%s" % ("PASS" if ok else "FAIL", label, "" if ok else "\n    " + detail.replace("\n", "\n    ")))

    try:
        # 1. CP932 の円記号（\ と ￥）と桁区切りの金額
        yen_file = put("moshimo-yen.csv", _moshimo_csv([
            '2026年10月30日,5,3,\\0,1,"\\1,234",0,\\0,"\\1,234"',
            '2026年10月31日,0,1,\\0,1,"￥12,500",2,"\\2,000","￥2,000"',
        ]))
        inputs = load_inputs([yen_file])
        d30, d31 = datetime.date(2026, 10, 30), datetime.date(2026, 10, 31)
        check("CP932の円記号・桁区切りが数値になる",
              inputs["moshimo_days"][d30]["occurred_amount"] == 1234
              and inputs["moshimo_days"][d31]["occurred_amount"] == 12500
              and inputs["moshimo_days"][d31]["approved_amount"] == 2000
              and inputs["moshimo_days"][d31]["payout"] == 2000,
              repr(inputs["moshimo_days"]))
        code, text = call(["--since", "2026-10-30", "--until", "2026-10-31", yen_file])
        check("金額が桁区切りつきで出力される", "発生成果**2件（13,734円）**" in text and "報酬額**3,234円**" in text, text)

        # 2. 月をまたぐ期間・2ファイルの合算・重なった日は1回だけ
        m_oct = put("moshimo-oct.csv", _moshimo_csv([
            "2026年10月30日,0,2,\\0,0,\\0,0,\\0,\\0",
            "2026年10月31日,0,3,\\0,0,\\0,0,\\0,\\0",
        ]))
        m_nov = put("moshimo-nov.csv", _moshimo_csv([
            "2026年10月31日,0,3,\\0,0,\\0,0,\\0,\\0",
            "2026年11月01日,0,4,\\0,0,\\0,0,\\0,\\0",
            "2026年11月02日,0,5,\\0,0,\\0,0,\\0,\\0",
        ]))
        r_oct = put("monthly-oct.csv", _rakuten_csv("2026.10", ["2026-10-31,66,2,1,2200"], bom=True))
        r_nov = put("monthly-nov.csv", _rakuten_csv("2026.11", ["2026-11-01,0,7,0,0"], bom=False))
        code, text = call(["--since", "2026-10-30", "--until", "2026-11-02", m_oct, m_nov, r_oct, r_nov])
        check("月またぎ: もしもの2ファイルを合算し、重なった10-31を二重に数えない（2+3+4+5=14）",
              "クリック**14件**" in text and "1回だけ数えた: 10-31（1日）" in text, text)
        check("月またぎ: 楽天の2つの対象月を合算する（2+7=9・BOMあり/なし）",
              "対象月 2026.10・2026.11" in text and "クリック**9件**" in text and "成果（売上件数）**1件**" in text, text)
        check("月またぎ: 全日取得済みなら終了コード0", code == 0, "code=%d\n%s" % (code, text))

        m_conflict = put("moshimo-conflict.csv", _moshimo_csv(["2026年10月31日,0,9,\\0,0,\\0,0,\\0,\\0"]))
        code, text = call(["--since", "2026-10-30", "--until", "2026-10-31", m_oct, m_conflict])
        check("同じ日の値が食い違うと推測せず止まる（終了コード1）", code == 1 and "値が" in text, "code=%d\n%s" % (code, text))

        # 3. 見出しの列が想定と違うファイルは止まる
        bad_m = put("moshimo-bad.csv", _moshimo_csv(["2026年10月31日,0,3,\\0,0,\\0,0,\\0"],
                                                    header=",".join(MOSHIMO_HEADER[:-1])))
        code, text = call(["--since", "2026-10-31", "--until", "2026-10-31", bad_m])
        check("もしもの見出しが違うと止まる（終了コード1）", code == 1 and "見出しの列が想定と違います" in text, "code=%d\n%s" % (code, text))
        bad_r = put("monthly-bad.csv", _rakuten_csv("2026.10", ["2026-10-31,0,1,0,0"], header_ja="発生日,成果報酬,クリック数,売上件数"))
        code, text = call(["--since", "2026-10-31", "--until", "2026-10-31", bad_r])
        check("楽天の見出しが違うと止まる（終了コード1）", code == 1 and "見出しの列が想定と違います" in text, "code=%d\n%s" % (code, text))
        unknown = put("unknown.csv", "a,b,c\n1,2,3\n".encode("utf-8"))
        code, text = call(["--since", "2026-10-31", "--until", "2026-10-31", unknown])
        check("どちらの形でもないファイルは止まる（終了コード1）", code == 1 and "一致しません" in text, "code=%d\n%s" % (code, text))
        utf8_m = put("moshimo-utf8.csv", (MOSHIMO_HEADER_LINE + "\n2026年10月31日,0,3,\\0,0,\\0,0,\\0,\\0\n").encode("utf-8"))
        code, text = call(["--since", "2026-10-31", "--until", "2026-10-31", utf8_m])
        check("UTF-8で保存されたもしもは止まる（終了コード1）", code == 1 and "CP932ではなく" in text, "code=%d\n%s" % (code, text))

        # 4. 未取得の判定と終了コード2
        code, text = call(["--since", "2026-10-29", "--until", "2026-11-03", m_oct, r_nov])
        check("一部未取得なら集計を出して終了コード2",
              code == 2 and "もしも **未取得**: 10-29・11-01〜11-03（4日）" in text
              and "楽天 **未取得**: 10-29〜10-31（3日）" in text and "対象月の中で行の無い日は0とみなした: 11-02〜11-03（2日）" in text,
              "code=%d\n%s" % (code, text))
        m_zero = put("moshimo-zero.csv", _moshimo_csv(["2026年11月01日,0,0,\\0,0,\\0,0,\\0,\\0"]))
        code, text = call(["--since", "2026-11-01", "--until", "2026-11-01", m_zero, r_nov])
        check("すべて0の日は日別に「なし」と出る", "日別（0以外の日のみ）: なし（取得済みの日はすべて0）" in text, text)
        utf16 = put("utf16.csv", "﻿[.ShellClassInfo]\r\nLocalizedResourceName=x\r\n".encode("utf-16-le"))
        code, text = call(["--since", "2026-10-31", "--until", "2026-10-31", utf16])
        check("UTF-16など想定外の文字コードは止まる（終了コード1）", code == 1 and text.startswith("ASP_CSV_ERROR"), "code=%d\n%s" % (code, text))
        code, text = call(["--since", "2026-10-31", "--until", "2026-10-31", os.path.join(tmp, "nothing.csv")])
        check("ファイルが無いと終了コード1", code == 1, "code=%d\n%s" % (code, text))

        # 5. 入力ファイルが1バイトも書き換わらない
        all_files = [yen_file, m_oct, m_nov, r_oct, r_nov]
        before = {p: _sha256(p) for p in all_files}
        call(["--since", "2026-10-01", "--until", "2026-11-30"] + all_files)
        after = {p: _sha256(p) for p in all_files}
        check("実行の前後で入力ファイルのハッシュが同じ", before == after, "%r\n%r" % (before, after))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(1 for r in results if r)
    write("SELF_TEST %s %d/%d" % ("OK" if passed == len(results) else "NG", passed, len(results)))
    return 0 if passed == len(results) else 1


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
