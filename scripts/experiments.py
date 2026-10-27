# -*- coding: utf-8 -*-
r"""Growth Agent の「元に戻せる実験」の台帳 data/experiments.tsv を扱う唯一の入口（S-0027 ①）。

台帳（タブ区切り・UTF-8・LF・1行目ヘッダー）の列（この順）:
  実験ID／状態／種別／対象／内容／設定キー／設定値／範囲／主指標／開始日／判定日／延長／判定／根拠／D番号
  - 状態: 実装待ち／実行中／標準／戻し／不採用
      実装待ち = 種別「ルール」で、窓口の指示文による実装を待っている
      標準     = 効いたので格上げした（種別「設定」の継続）。設定値は以後も有効
  - 範囲: 「pin>=NNN」「channel=twitter」「slug=a,b」などを「＋」でつないだ形。
    設定値の適用条件と集計の対象を、この1列で兼ねる。空欄は全体。
  - 延長: 判定日を7日延ばした回数（0 か 1）
  - 判定: 空欄／「継続 YYYY-MM-DD」／「戻し YYYY-MM-DD」
台帳はこのスクリプトだけが書く（手で編集しない）。

使い方:
  python site/scripts/experiments.py list
  python site/scripts/experiments.py adopt <audit.mdのパス> <提案番号...> [--dry-run] [--d D-NNNN]
  python site/scripts/experiments.py start <EX-NNNN>
  python site/scripts/experiments.py measure --week-end YYYY-MM-DD --out <ディレクトリ>
  python site/scripts/experiments.py judge <EX-NNNN> 継続|戻し|延長 --reason "<根拠>" [--d D-NNNN]

adopt: 監査の「## 新しい実験の提案」節の ```tsv ブロックから、指定した提案番号の行だけを台帳へ足す。
  ブロックの列（この順）: 提案番号(P-N)／種別／対象／内容／設定キー／設定値／範囲／主指標／判定までの日数
  開始日=採用日の翌日、判定日=開始日＋日数。種別「設定」は実行中で入る（設定キーが KEYS に無ければ拒否）。
  種別「ルール」は実装待ちで入る（日付は仮。start で付け直す）。判定までの日数は主指標ごとの下限
  （MIN_DAYS）未満を拒否する。
measure: experiments-status.json・pin-14d.json・sns-posts-7d.json を --out へ書く。
  Buffer は growth-metrics.py の buffer.sent_posts を1回だけ呼ぶ。GSC は gsc-ctr-28d の実行中の実験が
  あるときだけ growth-metrics.py の gsc.search_analytics_by_page を呼ぶ。ピンは data/pin-daily-metrics.tsv。
  比較は中央値: ピン=範囲内のピンと開始日より前の同じ枚数のピン／X・Threads=範囲内の投稿と開始前14日の
  投稿／CTR=同じページの開始前28日と開始後28日。
  判定案: 判定日に達し、後が前より上なら継続、以下なら戻し。対象が0件（または比べる前が0件）なら、
  延長0で延長・延長1で戻し。件数が少ないことは保留の理由にしない。判定日前は「途中」。
judge: 戻し=状態を戻しにする（設定値はその時点で無効）。継続=種別「設定」は標準にして設定値を残す／
  種別「ルール」は判定欄に継続と記録するだけ（標準化は窓口の指示で行う）。延長=判定日を7日延ばす（上限1回）。
  実装待ちの行に戻しを付けると不採用になる。

生成スクリプトから設定値を読む口は active_setting()（import して使う）。

終了コード: 0=正常 / 1=拒否・入力不備・書き込み失敗
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import statistics
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
LEDGER = os.path.join(PROJECT_ROOT, "data", "experiments.tsv")
PIN_DAILY_METRICS_TSV = os.path.join(PROJECT_ROOT, "data", "pin-daily-metrics.tsv")
PINS_DIR = os.path.join(PROJECT_ROOT, "output", "pins")
GROWTH_METRICS_SCRIPT = os.path.join(SCRIPT_DIR, "growth-metrics.py")

COLUMNS = ("実験ID", "状態", "種別", "対象", "内容", "設定キー", "設定値", "範囲", "主指標",
           "開始日", "判定日", "延長", "判定", "根拠", "D番号")
PROPOSAL_COLUMNS = ("提案番号", "種別", "対象", "内容", "設定キー", "設定値", "範囲", "主指標", "判定までの日数")
PROPOSAL_SECTION = "## 新しい実験の提案"

STATES = ("実装待ち", "実行中", "標準", "戻し", "不採用")
KINDS = ("設定", "ルール")
TARGETS = ("pin-hook", "image-style", "post-text", "x-standalone", "search-ctr")
# 主指標ごとの「判定までの日数」の下限（成果が出そろうまでの日数＋比べる期間）
MIN_DAYS = {"pin-impr-14d": 21, "x-impr-7d": 14, "threads-views-7d": 14, "gsc-ctr-28d": 28}
# 設定値を持てるキーの一覧。実験の採用時に足す（S-0027 ①では空）。
KEYS: tuple = ()

EXTEND_DAYS = 7
EXTEND_MAX = 1
ID_RE = re.compile(r"^EX-(\d{4})$")
RANGE_SEP_RE = re.compile(r"[＋+]")
RANGE_TERM_RE = re.compile(r"^(pin)(>=|<=|=)(\d+)$|^(channel|slug)=(.+)$")

# measure の窓
PIN_DAYS = 14                 # ピンは作成日から14日分の合計
PIN_CREATED_WEEKS = 4         # pin-14d.json は週末日までの直近4週に作成されたピン
SNS_MATURE_DAYS = 7           # X・Threads は送信から7日たった投稿だけを見る
SNS_BEFORE_DAYS = 14          # X・Threads の「前」= 開始前14日
CTR_DAYS = 28                 # CTR の「前」「後」= 開始前28日・開始後28日
BUFFER_MAX_SPAN = 90          # growth-metrics.py の --since/--until の上限
METRICS_TIMEOUT_SEC = 300
SITE_POSTS_RE = re.compile(r"/posts/([^/?#]+)/?")
PIN_FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-pin-(\d+)-")
JST = dt.timezone(dt.timedelta(hours=9))
METRIC_CHANNEL = {"x-impr-7d": "twitter", "threads-views-7d": "threads"}
VIEW_METRIC = {"twitter": "impressions", "threads": "views"}
REACTION_METRICS = ("reactions", "comments", "reposts", "quotes")


class ExperimentError(Exception):
    """拒否・入力不備（終了コード1）。"""


# --- 台帳 -----------------------------------------------------------------------


def load_ledger(path=None):
    path = path or LEDGER
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as handle:
        header = None
        for line in handle:
            line = line.rstrip("\r\n")
            if not line.strip():
                continue
            cells = line.split("\t")
            if header is None:
                header = cells
                if tuple(header) != COLUMNS:
                    raise ExperimentError("%s のヘッダーが想定と違います" % path)
                continue
            cells += [""] * (len(COLUMNS) - len(cells))
            rows.append(dict(zip(COLUMNS, cells)))
    return rows


def save_ledger(rows, path=None):
    path = path or LEDGER
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\t".join(COLUMNS) + "\n")
        for row in rows:
            handle.write("\t".join(_cell(row.get(c, "")) for c in COLUMNS) + "\n")
    os.replace(tmp, path)


def _cell(value):
    return str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ")


def _next_id(rows):
    numbers = [int(m.group(1)) for m in (ID_RE.match(r["実験ID"]) for r in rows) if m]
    return "EX-%04d" % (max(numbers, default=0) + 1)


def _find(rows, ex_id):
    for row in rows:
        if row["実験ID"] == ex_id:
            return row
    raise ExperimentError("台帳に %s がありません" % ex_id)


def _date(text):
    return dt.date.fromisoformat(text)


# --- 範囲 -----------------------------------------------------------------------


def parse_range(text):
    """範囲の文字列を [(次元, 演算子, 値)] にする。空欄・「全体」は []（すべてに当てはまる）。"""
    text = (text or "").strip()
    if text in ("", "-", "全体"):
        return []
    terms = []
    for part in RANGE_SEP_RE.split(text):
        part = part.strip()
        m = RANGE_TERM_RE.match(part)
        if not m:
            raise ExperimentError("範囲の書き方が不正です: %s（pin>=N・pin<=N・pin=N・channel=a,b・slug=a,b を＋でつなぐ）" % part)
        if m.group(1):
            terms.append(("pin", m.group(2), int(m.group(3))))
        else:
            values = tuple(v.strip() for v in m.group(5).split(",") if v.strip())
            if not values:
                raise ExperimentError("範囲の値が空です: %s" % part)
            terms.append((m.group(4), "=", values))
    return terms


def _term_ok(term, value):
    dim, op, want = term
    if dim == "pin":
        return op == ">=" and value >= want or op == "<=" and value <= want or op == "=" and value == want
    return value in want


def range_matches(text, pin=None, channel=None, slug=None, ignore_missing=False):
    """範囲に当てはまるか。値が与えられていない次元の条件は、ignore_missing=False なら不一致とする
    （設定値の適用は確かめられないものに広げない）。ignore_missing=True は集計用（ピンに channel は無い等）。"""
    given = {"pin": pin, "channel": channel, "slug": slug}
    for term in parse_range(text):
        value = given[term[0]]
        if value is None:
            if ignore_missing:
                continue
            return False
        if not _term_ok(term, value):
            return False
    return True


def _text_has_slug(text, terms):
    """投稿本文に slug= の条件のどれかの slug が含まれるか（slug の条件が無ければ True）。"""
    for dim, _op, values in terms:
        if dim == "slug" and not any(v in (text or "") for v in values):
            return False
    return True


# --- 取得の口 --------------------------------------------------------------------


def active_setting(key, pin=None, channel=None, slug=None, default=None):
    """状態が「実行中」（開始日を過ぎたもの）か「標準」で、範囲に当てはまる種別「設定」の行の設定値を返す。
    複数当てはまるときは実験IDの新しいものを優先する。無ければ default。"""
    today = dt.date.today()
    try:
        rows = load_ledger()
    except (OSError, ExperimentError):
        return default
    for row in sorted(rows, key=lambda r: r["実験ID"], reverse=True):
        if row["種別"] != "設定" or row["設定キー"] != key:
            continue
        if row["状態"] == "実行中":
            try:
                if _date(row["開始日"]) > today:
                    continue
            except ValueError:
                continue
        elif row["状態"] != "標準":
            continue
        try:
            if range_matches(row["範囲"], pin=pin, channel=channel, slug=slug):
                return row["設定値"]
        except ExperimentError:
            continue
    return default


# --- adopt ----------------------------------------------------------------------


def parse_proposals(audit_text):
    """監査の「## 新しい実験の提案」節の ```tsv ブロックを {提案番号: 行の辞書} にする。"""
    lines = audit_text.splitlines()
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == PROPOSAL_SECTION)
    except StopIteration:
        raise ExperimentError("「%s」節がありません" % PROPOSAL_SECTION)
    proposals = {}
    in_block = False
    for line in lines[start + 1:]:
        if not in_block and line.startswith("## "):
            break
        if line.strip().startswith("```"):
            if in_block:
                break
            in_block = line.strip() == "```tsv"
            continue
        if not in_block or not line.strip():
            continue
        cells = [c.strip() for c in line.split("\t")]
        if cells[0] == PROPOSAL_COLUMNS[0]:
            continue
        cells += [""] * (len(PROPOSAL_COLUMNS) - len(cells))
        row = dict(zip(PROPOSAL_COLUMNS, cells))
        proposals[row["提案番号"]] = row
    if not proposals:
        raise ExperimentError("「%s」節に ```tsv ブロックの行がありません" % PROPOSAL_SECTION)
    return proposals


def _validate_proposal(p):
    pid = p["提案番号"]
    if p["種別"] not in KINDS:
        raise ExperimentError("%s: 種別は %s のいずれか（%s）" % (pid, "／".join(KINDS), p["種別"]))
    if p["対象"] not in TARGETS:
        raise ExperimentError("%s: 対象は %s のいずれか（%s）" % (pid, "／".join(TARGETS), p["対象"]))
    if p["主指標"] not in MIN_DAYS:
        raise ExperimentError("%s: 主指標は %s のいずれか（%s）" % (pid, "／".join(MIN_DAYS), p["主指標"]))
    try:
        days = int(p["判定までの日数"])
    except ValueError:
        raise ExperimentError("%s: 判定までの日数が整数ではありません（%s）" % (pid, p["判定までの日数"]))
    if days < MIN_DAYS[p["主指標"]]:
        raise ExperimentError("%s: %s の判定までの日数は %d 日以上（%d）" % (pid, p["主指標"], MIN_DAYS[p["主指標"]], days))
    if p["種別"] == "設定" and p["設定キー"] not in KEYS:
        raise ExperimentError("%s: 設定キー「%s」は KEYS に未登録です（実験の採用時に experiments.py の KEYS へ足す）"
                              % (pid, p["設定キー"]))
    parse_range(p["範囲"])
    return days


def cmd_adopt(audit_path, numbers, dry_run=False, d_number="", today=None):
    today = today or dt.date.today()
    with open(audit_path, "r", encoding="utf-8") as handle:
        proposals = parse_proposals(handle.read())
    rows = load_ledger()
    source = os.path.relpath(os.path.abspath(audit_path), PROJECT_ROOT).replace("\\", "/")
    new_rows = []
    for number in numbers:
        p = proposals.get(number)
        if p is None:
            raise ExperimentError("提案番号 %s がブロックにありません（あるもの: %s）" % (number, "・".join(proposals)))
        tag = "採用: %s %s" % (source, number)
        if any(r["根拠"].startswith(tag + "（") or r["根拠"] == tag for r in rows):
            raise ExperimentError("%s は採用済みです" % tag)
        days = _validate_proposal(p)
        start = today + dt.timedelta(days=1)
        row = {c: "" for c in COLUMNS}
        row.update({
            "実験ID": _next_id(rows + new_rows),
            "状態": "実行中" if p["種別"] == "設定" else "実装待ち",
            "種別": p["種別"], "対象": p["対象"], "内容": p["内容"],
            "設定キー": p["設定キー"], "設定値": p["設定値"], "範囲": p["範囲"], "主指標": p["主指標"],
            "開始日": start.isoformat(), "判定日": (start + dt.timedelta(days=days)).isoformat(),
            "延長": "0", "判定": "", "根拠": "%s（%s採用）" % (tag, today.isoformat()), "D番号": d_number,
        })
        new_rows.append(row)
    for row in new_rows:
        print("%s%s\t%s" % ("（dry-run・書き込まない）" if dry_run else "", row["実験ID"],
                            "\t".join(row[c] for c in COLUMNS[1:])))
    if not dry_run:
        save_ledger(rows + new_rows)
    return 0


# --- start / judge ----------------------------------------------------------------


def cmd_start(ex_id, today=None):
    today = today or dt.date.today()
    rows = load_ledger()
    row = _find(rows, ex_id)
    if row["状態"] != "実装待ち":
        raise ExperimentError("%s は実装待ちではありません（%s）" % (ex_id, row["状態"]))
    days = (_date(row["判定日"]) - _date(row["開始日"])).days
    start = today + dt.timedelta(days=1)
    row.update({"状態": "実行中", "開始日": start.isoformat(),
                "判定日": (start + dt.timedelta(days=days)).isoformat()})
    save_ledger(rows)
    print("%s を実行中にしました（開始日 %s・判定日 %s）" % (ex_id, row["開始日"], row["判定日"]))
    return 0


def cmd_judge(ex_id, verdict, reason, d_number="", today=None):
    today = today or dt.date.today()
    if not reason.strip():
        raise ExperimentError("--reason が空です")
    rows = load_ledger()
    row = _find(rows, ex_id)
    note = "%s: %s（%s）" % (verdict, reason.strip(), today.isoformat())
    if verdict == "戻し" and row["状態"] == "実装待ち":
        row["状態"] = "不採用"
    elif row["状態"] != "実行中" or row["判定"].startswith("継続"):
        raise ExperimentError("%s は判定できる状態ではありません（%s %s）" % (ex_id, row["状態"], row["判定"]))
    elif verdict == "延長":
        extended = int(row["延長"] or 0)
        if extended >= EXTEND_MAX:
            raise ExperimentError("%s は延長済みです（上限 %d 回）" % (ex_id, EXTEND_MAX))
        row["延長"] = str(extended + 1)
        row["判定日"] = (_date(row["判定日"]) + dt.timedelta(days=EXTEND_DAYS)).isoformat()
    elif verdict == "戻し":
        row["状態"] = "戻し"
        row["判定"] = "戻し %s" % today.isoformat()
    elif verdict == "継続":
        if row["種別"] == "設定":
            row["状態"] = "標準"
        row["判定"] = "継続 %s" % today.isoformat()
    else:
        raise ExperimentError("判定は 継続・戻し・延長 のいずれか（%s）" % verdict)
    row["根拠"] = ("%s；%s" % (row["根拠"], note)) if row["根拠"] else note
    if d_number:
        row["D番号"] = ("%s・%s" % (row["D番号"], d_number)) if row["D番号"] else d_number
    save_ledger(rows)
    print("%s\t%s\t判定日 %s\t延長 %s\t%s" % (ex_id, row["状態"], row["判定日"], row["延長"], row["判定"] or "-"))
    return 0


# --- list -------------------------------------------------------------------------


def cmd_list(today=None):
    today = today or dt.date.today()
    rows = load_ledger()
    shown = 0
    for row in rows:
        if row["状態"] == "実装待ち":
            mark = "実装待ち"
        elif row["状態"] == "実行中" and row["判定"].startswith("継続"):
            mark = "継続判定済み・標準化待ち"
        elif row["状態"] == "実行中":
            mark = "判定日到来" if _date(row["判定日"]) <= today else "実行中"
        else:
            continue
        shown += 1
        print("%s\t%s\t%s\t%s\t%s\t範囲=%s\t主指標=%s\t開始 %s\t判定日 %s\t延長 %s" % (
            row["実験ID"], mark, row["種別"], row["対象"], row["内容"], row["範囲"] or "全体",
            row["主指標"], row["開始日"], row["判定日"], row["延長"]))
    if not shown:
        print("EXPERIMENTS_NONE（実行中・実装待ちの実験なし・台帳 %d 行）" % len(rows))
    return 0


# --- measure：データの読み込み ----------------------------------------------------------


def _pin_created_from_files():
    """output/pins のファイル名（YYYY-MM-DD-pin-<番号>-…）から {ピン番号: 作成日}（created_at が空のときの予備）。"""
    created = {}
    try:
        names = os.listdir(PINS_DIR)
    except OSError:
        return created
    for name in names:
        m = PIN_FILE_RE.match(name)
        if m:
            try:
                created[int(m.group(2))] = _date(m.group(1))
            except ValueError:
                continue
    return created


def load_pins(path=None):
    """data/pin-daily-metrics.tsv をピンごとにまとめる。
    戻り値: {ピン番号: {"pin_id", "slug", "created", "created_source", "days": {日付: (状態, imp)},
                         "deleted", "duplicate"}}"""
    path = path or PIN_DAILY_METRICS_TSV
    pins = {}
    if not os.path.exists(path):
        return pins
    fallback = None
    with open(path, "r", encoding="utf-8") as handle:
        header = None
        for line in handle:
            line = line.rstrip("\r\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            cells = line.split("\t")
            if header is None:
                header = cells
                continue
            r = dict(zip(header, cells))
            try:
                number = int(r.get("pin_number") or "")
                day = _date(r.get("date") or "")
            except ValueError:
                continue
            pin = pins.setdefault(number, {"pin_id": r.get("pin_id") or "", "slug": r.get("article_slug") or "",
                                           "created": None, "created_source": "", "days": {},
                                           "deleted": False, "duplicate": False})
            if pin["created"] is None and r.get("created_at"):
                try:
                    pin["created"] = _date(r["created_at"][:10])
                    pin["created_source"] = "created_at"
                except ValueError:
                    pass
            status = r.get("data_status") or ""
            if status == "DELETED":
                pin["deleted"] = True
            if (r.get("duplicate_detected") or "").lower() == "true":
                pin["duplicate"] = True
            try:
                imp = int(r.get("impressions") or 0)
            except ValueError:
                imp = 0
            pin["days"][day] = (status, imp)
    for number, pin in pins.items():
        if pin["created"] is None:
            if fallback is None:
                fallback = _pin_created_from_files()
            if number in fallback:
                pin["created"] = fallback[number]
                pin["created_source"] = "output/pins のファイル名"
    return pins


def pin_14d(pin, as_of):
    """作成日から14日分が as_of までにすべて READY なら14日合計のインプレッション、そうでなければ None。
    削除済み（DELETED）・重複（duplicate_detected）のピンは None。"""
    if pin["created"] is None or pin["deleted"] or pin["duplicate"]:
        return None
    days = [pin["created"] + dt.timedelta(days=i) for i in range(PIN_DAYS)]
    if days[-1] > as_of:
        return None
    total = 0
    for day in days:
        status, imp = pin["days"].get(day, ("", 0))
        if status != "READY":
            return None
        total += imp
    return total


def _pin_pending_reason(pin, as_of):
    if pin["created"] is None:
        return "作成日不明"
    if pin["deleted"]:
        return "DELETED"
    if pin["duplicate"]:
        return "duplicate_detected"
    if pin["created"] + dt.timedelta(days=PIN_DAYS - 1) > as_of:
        return "14日経過前"
    return "14日分に READY でない日がある（PROCESSING・欠損）"


def _run_metrics(args):
    """growth-metrics.py を1回実行し (契約JSON, 問題の文字列 or None) を返す。"""
    try:
        proc = subprocess.run([sys.executable, GROWTH_METRICS_SCRIPT] + [str(a) for a in args],
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=METRICS_TIMEOUT_SEC, cwd=PROJECT_ROOT)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, type(exc).__name__
    try:
        payload = json.loads(proc.stdout)
    except ValueError:
        return None, "invalid JSON (rc=%s)" % proc.returncode
    if payload.get("status") != "ok":
        info = payload.get("error") or {}
        return payload, "%s: %s" % (info.get("code"), info.get("message"))
    return payload, None


def fetch_sent_posts(since, until):
    """buffer.sent_posts（送信日時が since〜until・日本時間）を1回取得する。戻り値: (投稿のリスト, 問題 or None)"""
    payload, problem = _run_metrics(["buffer", "--operation", "buffer.sent_posts",
                                     "--since", since.isoformat(), "--until", until.isoformat(), "--limit", "100"])
    if problem:
        return [], problem
    warnings = payload.get("warnings") or []
    return (payload.get("data") or {}).get("series") or [], ("; ".join(warnings) if warnings else None)


def fetch_gsc_by_page(since, until):
    """gsc.search_analytics_by_page（since〜until・上位100ページ）。戻り値: ({slug: 行}, 問題 or None)"""
    payload, problem = _run_metrics(["gsc", "--operation", "gsc.search_analytics_by_page",
                                     "--since", since.isoformat(), "--until", until.isoformat(), "--limit", "100"])
    if problem:
        return {}, problem
    pages = {}
    for rec in (payload.get("data") or {}).get("series") or []:
        m = SITE_POSTS_RE.search(rec.get("page") or "")
        if m:
            pages[m.group(1)] = rec
    return pages, None


def _sent_date(post):
    try:
        sent = dt.datetime.fromisoformat((post.get("sent_at") or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if sent.tzinfo is None:
        sent = sent.replace(tzinfo=dt.timezone.utc)
    return sent.astimezone(JST).date()


def _post_metrics(post):
    values = {}
    for m in post.get("metrics") or []:
        try:
            values[m.get("type")] = float(m.get("value") or 0)
        except (TypeError, ValueError):
            continue
    service = post.get("service") or ""
    views = values.get(VIEW_METRIC.get(service, ""), 0.0)
    reactions = sum(values.get(k, 0.0) for k in REACTION_METRICS)
    return {"views": _num(views), "reactions": _num(reactions), "clicks": _num(values.get("clicks", 0.0)),
            "raw": {k: _num(v) for k, v in values.items()}}


def _num(value):
    return int(value) if float(value).is_integer() else round(value, 4)


def _median(values):
    return _num(statistics.median(values)) if values else None


# --- measure：実験ごとの比較と判定案 -------------------------------------------------------


def _proposal(row, week_end, before, after):
    """判定案（継続／戻し／延長／途中）と理由。"""
    if week_end < _date(row["判定日"]):
        return "途中", "判定日（%s）前" % row["判定日"]
    extended = int(row["延長"] or 0)
    if not after or not before:
        what = "対象が0件" if not after else "比べる前の対象が0件"
        if extended < EXTEND_MAX:
            return "延長", "%s・延長%d回" % (what, extended)
        return "戻し", "%s・延長済み" % what
    b, a = statistics.median(before), statistics.median(after)
    if a > b:
        return "継続", "後の中央値 %s ＞ 前の中央値 %s" % (_num(a), _num(b))
    return "戻し", "後の中央値 %s ≦ 前の中央値 %s" % (_num(a), _num(b))


def _measure_pin(row, pins, week_end):
    start = _date(row["開始日"])
    after, after_ids, candidates = [], [], set()
    for number, pin in sorted(pins.items()):
        if pin["created"] is None or pin["created"] < start:
            continue
        if not range_matches(row["範囲"], pin=number, slug=pin["slug"], ignore_missing=True):
            continue
        candidates.add(number)
        value = pin_14d(pin, week_end)
        if value is not None:
            after.append(value)
            after_ids.append(number)
    before_pool = sorted(((pin["created"], number, pin_14d(pin, week_end)) for number, pin in pins.items()
                          if number not in candidates and pin["created"] is not None and pin["created"] < start),
                         reverse=True)
    before_pool = [(c, n, v) for c, n, v in before_pool if v is not None][:len(after)]
    before = [v for _c, _n, v in before_pool]
    return {"unit": "ピン（作成から14日合計のインプレッション）",
            "before": {"median": _median(before), "count": len(before), "pins": sorted(n for _c, n, _v in before_pool)},
            "after": {"median": _median(after), "count": len(after), "pins": after_ids,
                      "pending": len(candidates) - len(after)}}, before, after


def _measure_posts(row, posts, week_end):
    channel = METRIC_CHANNEL[row["主指標"]]
    terms = parse_range(row["範囲"])
    start = _date(row["開始日"])
    mature_end = week_end - dt.timedelta(days=SNS_MATURE_DAYS)
    before_lo = start - dt.timedelta(days=SNS_BEFORE_DAYS)
    before, after = [], []
    for post in posts:
        if post.get("service") != channel:
            continue
        day = _sent_date(post)
        if day is None:
            continue
        views = _post_metrics(post)["views"]
        if before_lo <= day < start:
            before.append(views)
        elif start <= day <= mature_end:
            if not range_matches(row["範囲"], channel=channel, ignore_missing=True):
                continue
            if _text_has_slug(post.get("text"), terms):
                after.append(views)
    return {"unit": "%s の投稿1件の%s（取得時点の値）" % (channel, VIEW_METRIC[channel]),
            "before": {"median": _median(before), "count": len(before),
                       "window": [before_lo.isoformat(), (start - dt.timedelta(days=1)).isoformat()]},
            "after": {"median": _median(after), "count": len(after),
                      "window": [start.isoformat(), mature_end.isoformat()]}}, before, after


def _measure_ctr(row, week_end, gsc_cache, warnings):
    start = _date(row["開始日"])
    windows = ((start - dt.timedelta(days=CTR_DAYS), start - dt.timedelta(days=1)),
               (start, min(start + dt.timedelta(days=CTR_DAYS - 1), week_end)))
    fetched = []
    for lo, hi in windows:
        if hi < lo:
            fetched.append({})
            continue
        if (lo, hi) not in gsc_cache:
            gsc_cache[(lo, hi)] = fetch_gsc_by_page(lo, hi)
        pages, problem = gsc_cache[(lo, hi)]
        if problem:
            warnings.append("%s: GSC %s〜%s を取得できなかった: %s" % (row["実験ID"], lo, hi, problem))
        fetched.append(pages)
    before_pages, after_pages = fetched
    slugs = [s for s in after_pages if s in before_pages and range_matches(row["範囲"], slug=s, ignore_missing=True)]
    before = [float(before_pages[s].get("ctr") or 0) for s in slugs]
    after = [float(after_pages[s].get("ctr") or 0) for s in slugs]
    return {"unit": "ページごとのCTR（同じページの前後・GSC 上位100ページの範囲）",
            "before": {"median": _median(before), "count": len(before),
                       "window": [windows[0][0].isoformat(), windows[0][1].isoformat()]},
            "after": {"median": _median(after), "count": len(after),
                      "window": [windows[1][0].isoformat(), windows[1][1].isoformat()], "pages": slugs}}, before, after


def build_status(rows, week_end, pins, posts, warnings):
    experiments = []
    gsc_cache = {}
    for row in rows:
        if row["状態"] != "実行中" or row["判定"].startswith("継続"):
            continue
        entry = {"id": row["実験ID"], "kind": row["種別"], "target": row["対象"], "content": row["内容"],
                 "key": row["設定キー"], "value": row["設定値"], "range": row["範囲"], "metric": row["主指標"],
                 "start": row["開始日"], "judge_date": row["判定日"], "extended": int(row["延長"] or 0)}
        if _date(row["開始日"]) > week_end:
            entry.update({"proposal": "途中", "reason": "開始日（%s）が週末日より後" % row["開始日"]})
            experiments.append(entry)
            continue
        metric = row["主指標"]
        if metric == "pin-impr-14d":
            detail, before, after = _measure_pin(row, pins, week_end)
        elif metric in METRIC_CHANNEL:
            detail, before, after = _measure_posts(row, posts, week_end)
        else:
            detail, before, after = _measure_ctr(row, week_end, gsc_cache, warnings)
        proposal, reason = _proposal(row, week_end, before, after)
        entry.update(detail)
        entry.update({"proposal": proposal, "reason": reason})
        experiments.append(entry)
    pending_rules = [r["実験ID"] for r in rows if r["状態"] == "実装待ち"]
    return experiments, pending_rules


def build_pin_14d(pins, week_end):
    lo = week_end - dt.timedelta(days=7 * PIN_CREATED_WEEKS - 1)
    confirmed, pending = [], []
    for number, pin in sorted(pins.items()):
        if pin["created"] is None or not (lo <= pin["created"] <= week_end):
            continue
        value = pin_14d(pin, week_end)
        if value is None:
            pending.append({"pin_number": number, "slug": pin["slug"], "created": pin["created"].isoformat(),
                            "reason": _pin_pending_reason(pin, week_end)})
        else:
            confirmed.append({"pin_number": number, "pin_id": pin["pin_id"], "slug": pin["slug"],
                              "created": pin["created"].isoformat(), "created_source": pin["created_source"],
                              "impressions_14d": value})
    return {"created_window": [lo.isoformat(), week_end.isoformat()],
            "rule": "作成日から14日分（作成日〜作成日+13日）が週末日までにすべて READY のピンだけを載せる。"
                    "DELETED・duplicate_detected のピンは除く。作成日は created_at（空なら output/pins のファイル名）",
            "pins": confirmed, "pending": pending}


def build_sns_posts(posts, week_end):
    hi = week_end - dt.timedelta(days=SNS_MATURE_DAYS)
    lo = hi - dt.timedelta(days=6)
    out = []
    for post in sorted(posts, key=lambda p: p.get("sent_at") or ""):
        day = _sent_date(post)
        if day is None or not (lo <= day <= hi):
            continue
        metrics = _post_metrics(post)
        out.append({"service": post.get("service"), "sent_at": post.get("sent_at"),
                    "text_head": (post.get("text") or "").replace("\r", " ").replace("\n", " ")[:40],
                    "views": metrics["views"], "reactions": metrics["reactions"], "clicks": metrics["clicks"],
                    "metrics": metrics["raw"]})
    return {"sent_window": [lo.isoformat(), hi.isoformat()],
            "rule": "送信日（日本時間）が週末日の13日前〜7日前の X・Threads 投稿。値は取得時点のもの"
                    "（views=X は impressions・Threads は views／reactions=reactions+comments+reposts+quotes）",
            "posts": out}


def cmd_measure(week_end, out_dir, pin_tsv=None):
    rows = load_ledger()
    generated_at = dt.datetime.now(JST).isoformat(timespec="seconds")
    warnings = []
    pins = load_pins(pin_tsv)
    if not pins:
        warnings.append("data/pin-daily-metrics.tsv が無いか空")

    active = [r for r in rows if r["状態"] == "実行中" and not r["判定"].startswith("継続")
              and _date(r["開始日"]) <= week_end]
    sns_lo = week_end - dt.timedelta(days=SNS_MATURE_DAYS + 6)
    lo = min([sns_lo] + [_date(r["開始日"]) - dt.timedelta(days=SNS_BEFORE_DAYS)
                         for r in active if r["主指標"] in METRIC_CHANNEL])
    if (week_end - lo).days + 1 > BUFFER_MAX_SPAN:
        lo = week_end - dt.timedelta(days=BUFFER_MAX_SPAN - 1)
        warnings.append("Buffer の取得期間を %d 日に切り詰めた（%s〜）" % (BUFFER_MAX_SPAN, lo))
    posts, problem = fetch_sent_posts(lo, week_end)   # Buffer はこの1回だけ
    buffer_source = {"operation": "buffer.sent_posts", "since": lo.isoformat(), "until": week_end.isoformat(),
                     "posts": len(posts), "problem": problem}
    if problem:
        warnings.append("Buffer: %s" % problem)

    experiments, pending_rules = build_status(rows, week_end, pins, posts, warnings)
    common = {"schema": 1, "week_end": week_end.isoformat(), "generated_at": generated_at}
    outputs = {
        "experiments-status.json": dict(common, ledger="data/experiments.tsv", experiments=experiments,
                                        pending_rules=pending_rules, buffer=buffer_source, warnings=warnings),
        "pin-14d.json": dict(common, **build_pin_14d(pins, week_end)),
        "sns-posts-7d.json": dict(common, buffer=buffer_source, **build_sns_posts(posts, week_end)),
    }
    os.makedirs(out_dir, exist_ok=True)
    for name, data in outputs.items():
        with open(os.path.join(out_dir, name), "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=1)
            handle.write("\n")
    print("MEASURE_OK week_end=%s experiments=%d pins_14d=%d sns_posts=%d warnings=%d" % (
        week_end, len(experiments), len(outputs["pin-14d.json"]["pins"]),
        len(outputs["sns-posts-7d.json"]["posts"]), len(warnings)))
    return 0


# --- main -------------------------------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(description="Growth Agent の実験台帳（data/experiments.tsv）")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    p = sub.add_parser("adopt")
    p.add_argument("audit")
    p.add_argument("numbers", nargs="+")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--d", default="", help="D番号（任意）")
    p = sub.add_parser("start")
    p.add_argument("ex_id")
    p = sub.add_parser("measure")
    p.add_argument("--week-end", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("judge")
    p.add_argument("ex_id")
    p.add_argument("verdict", choices=["継続", "戻し", "延長"])
    p.add_argument("--reason", required=True)
    p.add_argument("--d", default="", help="D番号（任意）")
    return parser


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        if args.command == "list":
            return cmd_list()
        if args.command == "adopt":
            return cmd_adopt(args.audit, args.numbers, args.dry_run, args.d)
        if args.command == "start":
            return cmd_start(args.ex_id)
        if args.command == "measure":
            try:
                week_end = _date(args.week_end)
            except ValueError:
                raise ExperimentError("--week-end は YYYY-MM-DD: %s" % args.week_end)
            return cmd_measure(week_end, args.out)
        if args.command == "judge":
            return cmd_judge(args.ex_id, args.verdict, args.reason, args.d)
    except (ExperimentError, OSError, ValueError) as exc:
        print("【エラー】%s" % exc, file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
