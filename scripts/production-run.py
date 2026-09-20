# -*- coding: utf-8 -*-
r"""production run（Claude Code側の1セッション＝1run）の成果物差分を
producer factとして data/production-handoff/ へ保存する（D-0235）。

目的:
  Growth Agentが「その日のproduction runで何が新しく生まれ、何が変わったか」を
  推測せずに受け取れるようにする。run境界は SessionStart（open）と
  SessionEnd（finalize）で閉じる。1 source run → 1 Growth Daily。

contract:
  出力JSONは growth-agent 側の production-daily-handoff/1 を対象にする。
  Growth側のpolicy欄（quality_route・relevant_criteria・evaluation_refs・
  assessment_refs・result_reuse_keys）は一切書かない。producer factだけを渡す。

保存先（data/ はGit管理外）:
  data/production-handoff/
    _runs.tsv                 追記専用。run_id / session_id / event / 時刻 / close_reason
    _open/<run>.json          開いているrunの開始記録
    _steps/<run>.jsonl        run単位のstep記録（他スクリプトが record_step() で追記）
    _steps/_unbound.jsonl     runを特定できなかったstep記録
    _errors.log               生成失敗の記録
    YYYY-MM-DD_<run>.json     確定済みhandoff（日付はrun開始日・JST）

  <run> はrun_idのコロンをハイフンに置換したもの（Windowsのファイル名に
  コロンを使えないため）。JSON本文の run_id はコロンのまま保持する。

run_id:
  claude-run:<session_id>:<連番>
  連番は _runs.tsv にある同じsession_idのopen行の数 + 1。

出力（人間・AI向け）:
  open     … 正常時は何も出力しない。代理確定・overlapがあった時だけ【警告】1行。
  finalize … 正常時は何も出力しない。書いたhandoffのpathだけを1行出す。
  backfill … --dry-run ならJSONを標準出力へ出すだけ。

既知の差異（2026-09-20時点・growth-agent側は読み取り専用のため変更していない）:
  growth_routine.py の PRODUCER_CHANGE_CLASSES は {"new","changed","unchanged"} で
  "deleted" を含まない。本スクリプトは削除をproducer factとして落とさないため
  change="deleted" を出力するが、その output を含む handoff は Growth側の
  validate_production_handoff() で拒否される。Growth側が deleted を受け入れるまで、
  削除を含むrunのhandoffはGrowth側で使えない（事実は保存される）。

使い方:
  python site/scripts/production-run.py open
  python site/scripts/production-run.py finalize
  python site/scripts/production-run.py finalize --session-id <id>   # 復旧用（下記）
  python site/scripts/production-run.py backfill --session-id <id> --base <sha> --head <sha> --opened-at YYYY-MM-DD [--dry-run]

復旧用の finalize --session-id:
  SessionEndが観測されないまま残ったrunを手で閉じる。次のセッションのopenが
  30分ルールで代理確定するのを待たずに閉じたい場合に使う。close_reason は
  既定で session_end_not_observed（--close-reason で変えられる）。
"""

import datetime
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import threading

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))

CONTRACT_VERSION = "production-daily-handoff/1"
TIMEZONE = "Asia/Tokyo"
JST = datetime.timezone(datetime.timedelta(hours=9), name=TIMEZONE)

# 差分の対象path（site からの相対）。ここに無いpathはpopulationに載せない。
ASSET_PREFIXES = (
    ("src/content/posts/", "article"),
    ("public/images/", "article_image"),
    ("public/pin-images/", "pin_image"),
)

# public/pin-images/ の削除は「転送用コピーの刈り込み」であり成果物の削除ではない。
PRUNE_ONLY_PREFIX = "public/pin-images/"

# 他sessionの開いているrunを「クラッシュした」とみなすまでの無操作時間。
STALE_MINUTES = 30

# _runs.tsv を読む範囲。記録が増えても処理量を一定に保つため。
RUNS_LOOKBACK_HOURS = 48

GIT_TIMEOUT = 120

RUNS_HEADER = "# run_id\tsession_id\tevent\ttimestamp\tclose_reason"


# --------------------------------------------------------------------------
# パスと小道具
# --------------------------------------------------------------------------

def handoff_dir(root=None):
    return os.path.join(root or PROJECT_ROOT, "data", "production-handoff")


def runs_path(root=None):
    return os.path.join(handoff_dir(root), "_runs.tsv")


def open_dir(root=None):
    return os.path.join(handoff_dir(root), "_open")


def steps_dir(root=None):
    return os.path.join(handoff_dir(root), "_steps")


def errors_path(root=None):
    return os.path.join(handoff_dir(root), "_errors.log")


def safe_run_id(run_id):
    """run_idをファイル名に使える形へ落とす（コロンはWindowsで使えない）。"""
    return re.sub(r"[^0-9A-Za-z._-]", "-", run_id)


def now_jst():
    return datetime.datetime.now(JST)


def iso(dt):
    return dt.isoformat(timespec="seconds")


def ensure_dirs(root=None):
    os.makedirs(open_dir(root), exist_ok=True)
    os.makedirs(steps_dir(root), exist_ok=True)


def log_error(message, root=None):
    """_errors.log へ1行追記する。ここでの失敗は握りつぶす（記録の失敗で
    本来の処理を止めない）。"""
    try:
        os.makedirs(handoff_dir(root), exist_ok=True)
        with open(errors_path(root), "a", encoding="utf-8", newline="\n") as f:
            f.write("%s\t%s\n" % (iso(now_jst()), message.replace("\n", " ")))
    except Exception:
        pass


def write_json_atomic(path, payload):
    """一時ファイルへ書いてから rename する（途中で落ちた半端なJSONを残さない）。"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        f.write("\n")
    os.replace(tmp, path)


def sha256_hex(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def canonical_json(value):
    """payloadの正規化JSON（キー順固定・空白なし）。identityの元にする。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


# --------------------------------------------------------------------------
# session_id の解決
# --------------------------------------------------------------------------

def session_id_from_stdin(timeout_seconds=2.0):
    """フック入力JSONから session_id を読む。

    SessionEndフックは標準入力へJSONを渡す。ただしこのスクリプトは手動でも
    実行されるため、標準入力が閉じられない環境で読み込みが固まらないよう、
    別スレッドで読んでタイムアウトさせる。読めなければ None。
    """
    if sys.stdin is None or sys.stdin.closed:
        return None, None
    try:
        if sys.stdin.isatty():
            return None, None
    except Exception:
        return None, None

    box = {}

    def _read():
        try:
            box["raw"] = sys.stdin.buffer.read()
        except Exception:
            box["raw"] = b""

    thread = threading.Thread(target=_read, daemon=True)
    thread.start()
    thread.join(timeout_seconds)
    raw = box.get("raw")
    if not raw:
        return None, None
    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return None, None
    if not isinstance(payload, dict):
        return None, None
    sid = payload.get("session_id")
    reason = payload.get("reason") or payload.get("matcher") or payload.get("source")
    return (sid if isinstance(sid, str) and sid else None), (reason if isinstance(reason, str) else None)


def session_id_from_env():
    """環境変数から session_id を読む。

    CLAUDE_HOOK_SESSION_ID は session-start-check.py がフック入力JSONから
    取り出して子プロセスへ渡す値（フック経路の正）。
    CLAUDE_CODE_SESSION_ID は Bashツール経由の実行で設定される値
    （record-lesson.py:241 と同じ経路）。
    """
    for key in ("CLAUDE_HOOK_SESSION_ID", "CLAUDE_CODE_SESSION_ID"):
        value = os.environ.get(key)
        if value:
            return value
    return None


# --------------------------------------------------------------------------
# transcript
# --------------------------------------------------------------------------

def slugify_path_to_project_dir(path):
    """Claude Codeのプロジェクトディレクトリ命名規則（英数字以外を'-'に置換）。
    session-token-usage.py と同じ方式に揃える。"""
    return re.sub(r"[^a-zA-Z0-9]", "-", path)


def default_transcripts_dir(root=None):
    userprofile = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if not userprofile:
        return None
    base = root or PROJECT_ROOT
    return os.path.join(userprofile, ".claude", "projects", slugify_path_to_project_dir(base))


def transcript_mtime(session_id, root=None, transcripts_dir=None):
    """session_idに対応するtranscriptの最終更新時刻（JST）。無ければNone。"""
    base = transcripts_dir or default_transcripts_dir(root)
    if not base:
        return None
    path = os.path.join(base, session_id + ".jsonl")
    if not os.path.isfile(path):
        return None
    return datetime.datetime.fromtimestamp(os.path.getmtime(path), JST)


# --------------------------------------------------------------------------
# _runs.tsv
# --------------------------------------------------------------------------

def append_run_row(root, run_id, session_id, event, timestamp, close_reason=""):
    os.makedirs(handoff_dir(root), exist_ok=True)
    path = runs_path(root)
    new = not os.path.isfile(path)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        if new:
            f.write(RUNS_HEADER + "\n")
        f.write("%s\t%s\t%s\t%s\t%s\n" % (run_id, session_id, event, timestamp, close_reason))


def read_runs(root, since=None):
    """_runs.tsv を読む。since（datetime）以降の行だけを返す。"""
    path = runs_path(root)
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            while len(parts) < 5:
                parts.append("")
            try:
                ts = datetime.datetime.fromisoformat(parts[3])
            except ValueError:
                continue
            if since is not None and ts < since:
                continue
            rows.append({
                "run_id": parts[0],
                "session_id": parts[1],
                "event": parts[2],
                "timestamp": ts,
                "close_reason": parts[4],
            })
    return rows


def next_sequence(root, session_id):
    """同じsession_idの過去のopen行の数 + 1。"""
    count = 0
    path = runs_path(root)
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 3 and parts[1] == session_id and parts[2] == "open":
                    count += 1
    return count + 1


# --------------------------------------------------------------------------
# _open
# --------------------------------------------------------------------------

def open_record_path(root, run_id):
    return os.path.join(open_dir(root), safe_run_id(run_id) + ".json")


def list_open_records(root):
    records = []
    directory = open_dir(root)
    if not os.path.isdir(directory):
        return records
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(directory, name)
        try:
            with open(path, encoding="utf-8") as f:
                record = json.load(f)
        except Exception:
            log_error("開始記録を読めませんでした: %s" % path, root)
            continue
        if isinstance(record, dict) and record.get("run_id"):
            records.append(record)
    return records


def find_open_record(root, session_id):
    for record in list_open_records(root):
        if record.get("session_id") == session_id:
            return record
    return None


# --------------------------------------------------------------------------
# git
# --------------------------------------------------------------------------

def git(root, *args):
    site = os.path.join(root or PROJECT_ROOT, "site")
    return subprocess.run(
        ["git", "-C", site] + list(args),
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=GIT_TIMEOUT,
    )


def git_head(root):
    result = git(root, "rev-parse", "HEAD")
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def git_blob(root, rev, path):
    result = git(root, "rev-parse", "%s:%s" % (rev, path))
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value if re.fullmatch(r"[0-9a-f]{40}", value) else None


def git_commits_for_path(root, base, head, path):
    result = git(root, "log", "--format=%H", "--reverse", "%s..%s" % (base, head), "--", path)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def git_commits_in_range(root, base, head):
    result = git(root, "log", "--format=%H", "--reverse", "%s..%s" % (base, head))
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def git_commit_time(root, sha):
    result = git(root, "log", "-1", "--format=%cI", sha)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def git_name_status(root, base, head):
    """(status, path) の一覧。対象prefix外は落とす。"""
    result = git(root, "diff", "--no-renames", "--name-status", "%s..%s" % (base, head))
    if result.returncode != 0:
        raise RuntimeError("git diff に失敗しました: %s" % (result.stderr or result.stdout).strip())
    entries = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0].strip()[:1]
        path = parts[-1].strip()
        if not any(path.startswith(prefix) for prefix, _ in ASSET_PREFIXES):
            continue
        entries.append((status, path))
    entries.sort(key=lambda e: e[1])
    return entries


def asset_class_for(path):
    for prefix, asset_class in ASSET_PREFIXES:
        if path.startswith(prefix):
            return asset_class
    return None


# --------------------------------------------------------------------------
# 台帳（既存スクリプトの関数を流用する）
# --------------------------------------------------------------------------

def _load_module(file_name, module_name):
    path = os.path.join(SCRIPT_DIR, file_name)
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_pin_status_module(root=None):
    """check-pin-posting-status.py を読み込み、パス定数を root に向け直す。

    判定ロジック（load_ledger / extract_created_pins）はあちらが正本で、
    ここには写さない。テストで別rootを見せるためにパス定数だけ差し替える。
    """
    module = _load_module("check-pin-posting-status.py", "check_pin_posting_status")
    base = root or PROJECT_ROOT
    module.PINS_DIR = os.path.join(base, "output", "pins")
    module.LEDGER_PATH = os.path.join(base, "data", "pin-posted.md")
    return module


def load_buffer_module():
    """post-pins-to-buffer.py を読み込む（module直下で通信・.env読み込みをしない）。"""
    return _load_module("post-pins-to-buffer.py", "post_pins_to_buffer")


def pin_ledger_numbers(root=None):
    module = load_pin_status_module(root)
    posted = module.load_ledger()
    return sorted(posted or set())


def buffer_ledger_pairs(root=None):
    module = load_buffer_module()
    path = os.path.join(root or PROJECT_ROOT, "data", "buffer-posted.md")
    return sorted("%d\t%s" % (num, service) for num, service in module.load_posted_pairs(path=path))


def buffer_services():
    return tuple(load_buffer_module().SERVICES)


# --------------------------------------------------------------------------
# step記録
# --------------------------------------------------------------------------

def steps_path(root, run_id):
    return os.path.join(steps_dir(root), safe_run_id(run_id) + ".jsonl")


def unbound_steps_path(root):
    return os.path.join(steps_dir(root), "_unbound.jsonl")


def record_step(kind, root=None, **fields):
    """現在のrunへstepを1行追記する。

    記録の失敗で呼び出し元の本来の処理を止めない（例外は外へ出さない）。
    runを1つに特定できない場合は _unbound.jsonl と _errors.log に残す。
    """
    try:
        base = root or PROJECT_ROOT
        entry = {"kind": kind, "ts": iso(now_jst())}
        entry.update(fields)

        session_id = session_id_from_env()
        if not session_id:
            entry["unbound_reason"] = "session_idを取得できませんでした（環境変数が未設定）"
            _append_unbound(base, entry)
            return False

        entry["session_id"] = session_id
        record = find_open_record(base, session_id)
        if record is None:
            entry["unbound_reason"] = "session_id %s に対応する開いているrunがありません" % session_id
            _append_unbound(base, entry)
            return False

        entry["run_id"] = record["run_id"]
        os.makedirs(steps_dir(base), exist_ok=True)
        with open(steps_path(base, record["run_id"]), "a", encoding="utf-8", newline="\n") as f:
            f.write(canonical_json(entry) + "\n")
        return True
    except Exception as e:  # 記録の失敗は本来の処理より軽い
        try:
            log_error("step記録に失敗しました（kind=%s）: %s" % (kind, e), root)
        except Exception:
            pass
        return False


def _append_unbound(root, entry):
    os.makedirs(steps_dir(root), exist_ok=True)
    with open(unbound_steps_path(root), "a", encoding="utf-8", newline="\n") as f:
        f.write(canonical_json(entry) + "\n")
    log_error("step記録をrunへ結び付けられませんでした: %s" % entry.get("unbound_reason"), root)


def read_steps(root, run_id):
    path = steps_path(root, run_id)
    steps = []
    if not os.path.isfile(path):
        return steps
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except Exception:
                continue
            if isinstance(value, dict):
                steps.append(value)
    return steps


# --------------------------------------------------------------------------
# open
# --------------------------------------------------------------------------

def open_run(root=None, session_id=None, now=None, transcripts_dir=None):
    """runを開く。戻り値: (開始記録 または None, 【警告】行のリスト)"""
    base = root or PROJECT_ROOT
    warnings = []
    session_id = session_id or session_id_from_env()
    if not session_id:
        log_error("open: session_idを取得できないためrunを開けませんでした", base)
        return None, warnings

    ensure_dirs(base)
    now = now or now_jst()

    # 他sessionの開いているrunの始末を先につける（自分のrunの overlap_with を
    # 確定させてから自分の開始記録を書くため）。
    overlap_with = []
    for other in list_open_records(base):
        if other.get("session_id") == session_id:
            continue
        mtime = transcript_mtime(other["session_id"], base, transcripts_dir)
        stale = mtime is None or (now - mtime) >= datetime.timedelta(minutes=STALE_MINUTES)
        if stale:
            try:
                path = finalize_run(
                    base, other["session_id"], close_reason="session_end_not_observed", now=now,
                    transcripts_dir=transcripts_dir,
                )
            except Exception as e:
                # 代理確定の失敗で自分のrunを開けなくなる方が損失が大きい。
                log_error("代理確定に失敗しました（run_id=%s）: %s" % (other["run_id"], e), base)
                path = None
            warnings.append(
                "【警告】終了が観測されなかったrun %s を代理確定しました（handoff: %s）"
                % (other["run_id"], path or "なし（成果物の差分・step記録ともに無し）")
            )
        else:
            overlap_with.append(other["run_id"])

    existing = find_open_record(base, session_id)
    if existing is not None:
        # resume等で同じsessionのopenが再度呼ばれても開始記録を上書きしない。
        if overlap_with:
            changed = _merge_overlap(base, existing, overlap_with)
            if changed:
                warnings.append(
                    "【警告】run %s は他のrun（%s）と区間が重なっています"
                    % (existing["run_id"], ", ".join(overlap_with))
                )
        return existing, warnings

    run_id = "claude-run:%s:%d" % (session_id, next_sequence(base, session_id))
    record = {
        "run_id": run_id,
        "session_id": session_id,
        "opened_at": iso(now),
        "opened_date": now.date().isoformat(),
        "site_head": git_head(base),
        "pin_ledger": pin_ledger_numbers(base),
        "buffer_ledger": buffer_ledger_pairs(base),
        "overlap_with": sorted(overlap_with),
    }
    write_json_atomic(open_record_path(base, run_id), record)
    append_run_row(base, run_id, session_id, "open", iso(now))

    if overlap_with:
        for other in list_open_records(base):
            if other["run_id"] in overlap_with:
                _merge_overlap(base, other, [run_id])
        warnings.append(
            "【警告】run %s は他のrun（%s）と区間が重なっています"
            % (run_id, ", ".join(overlap_with))
        )
    return record, warnings


def _merge_overlap(root, record, run_ids):
    current = set(record.get("overlap_with") or [])
    merged = current | set(run_ids)
    if merged == current:
        return False
    record["overlap_with"] = sorted(merged)
    write_json_atomic(open_record_path(root, record["run_id"]), record)
    return True


# --------------------------------------------------------------------------
# population
# --------------------------------------------------------------------------

def build_git_outputs(root, base_rev, head_rev):
    """Git差分から (outputs, 対象になったpath一覧) を作る。"""
    outputs = []
    entries = git_name_status(root, base_rev, head_rev)
    for status, path in entries:
        if status == "D" and path.startswith(PRUNE_ONLY_PREFIX):
            # 転送用コピーの刈り込み。成果物の削除ではないので載せない。
            continue
        commits = git_commits_for_path(root, base_rev, head_rev, path)
        item = {
            "entity_id": path,
            "asset_class": asset_class_for(path),
            "channel": None,
            "evidence_refs": commits or [head_rev],
            "published_at": None,
            "external_identity": None,
        }
        if status == "A":
            blob = git_blob(root, head_rev, path)
            item["change"] = "new"
            item["content_identity"] = "git-blob:%s" % blob if blob else None
            item["previous_content_identity"] = None
            if item["asset_class"] == "article" and commits:
                item["published_at"] = git_commit_time(root, commits[0])
        elif status == "M":
            blob = git_blob(root, head_rev, path)
            previous = git_blob(root, base_rev, path)
            item["change"] = "changed"
            item["content_identity"] = "git-blob:%s" % blob if blob else None
            item["previous_content_identity"] = "git-blob:%s" % previous if previous else None
        elif status == "D":
            previous = git_blob(root, base_rev, path)
            item["change"] = "deleted"
            item["content_identity"] = None
            item["previous_content_identity"] = "git-blob:%s" % previous if previous else None
        else:
            continue
        outputs.append(item)
    return outputs


def build_step_outputs(root, steps, opened_pin_ledger, opened_buffer_ledger, run_id):
    """step記録の投稿成功からPin投稿文のoutputを作る。

    開始時点で既に台帳に載っていた番号の再投稿は previous を証明できないため
    outputs に入れず unresolved へ回す。
    戻り値: (outputs, unresolved)
    """
    outputs = []
    unresolved = []
    pin_ledger = set(opened_pin_ledger or [])
    buffer_ledger = set(opened_buffer_ledger or [])
    steps_ref = os.path.relpath(steps_path(root, run_id), root).replace(os.sep, "/")

    for step in steps:
        if step.get("kind") != "post" or not step.get("ok"):
            continue
        pin_num = step.get("pin_num")
        channel = step.get("channel")
        digest = step.get("payload_sha256")
        if pin_num is None or not channel or not digest:
            continue

        if channel == "pinterest":
            already = pin_num in pin_ledger
        else:
            already = ("%d\t%s" % (pin_num, channel)) in buffer_ledger
        if already:
            unresolved.append(
                "pin-text:%d:%s は開始時点で既に台帳に載っていたため、"
                "直前の内容（previous_content_identity）を証明できません" % (pin_num, channel)
            )
            continue

        outputs.append({
            "entity_id": "pin-text:%d:%s" % (pin_num, channel),
            "asset_class": "social_post_text",
            "channel": channel,
            "content_identity": "sha256:%s" % digest,
            "change": "new",
            "previous_content_identity": None,
            "evidence_refs": [steps_ref],
            "published_at": step.get("ts"),
            "external_identity": None,
        })
    return outputs, unresolved


# --------------------------------------------------------------------------
# status判定
# --------------------------------------------------------------------------

def article_slugs(outputs, change="new"):
    slugs = []
    for item in outputs:
        if item.get("asset_class") != "article" or item.get("change") != change:
            continue
        name = os.path.basename(item["entity_id"])
        if name.endswith(".md"):
            slugs.append(name[: -len(".md")])
    return slugs


def pins_for_slug(root, slug):
    """記事slugに対応するピン番号の集合を返す。

    誘導先URLからのslug抽出は post-pins-to-pinterest.py の
    extract_slug_from_guide_url() が正本で、ここには写さない。
    読み込めない場合は None を返し、呼び出し側で「判定できなかった」として扱う。
    """
    try:
        module = _load_module("post-pins-to-pinterest.py", "post_pins_to_pinterest")
        extract = module.extract_slug_from_guide_url
    except Exception as e:
        log_error("post-pins-to-pinterest.py を読み込めませんでした: %s" % e, root)
        return None

    status_module = load_pin_status_module(root)
    pins_dir = status_module.PINS_DIR
    guide_re = re.compile(r"^-\s*誘導先URL:\s*(.+)$")
    found = set()
    if not os.path.isdir(pins_dir):
        return found
    for pin_num, file_names in status_module.extract_created_pins().items():
        path = os.path.join(pins_dir, file_names[0])
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.read().splitlines()
        except OSError:
            continue
        for line in lines:
            m = guide_re.match(line.strip())
            if not m:
                continue
            if extract(m.group(1).strip()) == slug:
                found.add(pin_num)
            break
    return found


def missing_pin_coverage(root, slugs):
    """new記事のslugについて、Pin台帳・Buffer台帳が揃っていない箇所を列挙する。"""
    problems = []
    if not slugs:
        return problems
    posted_pins = set(pin_ledger_numbers(root))
    buffer_module = load_buffer_module()
    buffer_pairs = buffer_module.load_posted_pairs(
        path=os.path.join(root, "data", "buffer-posted.md")
    )
    services = buffer_module.SERVICES
    start_pin = buffer_module.BUFFER_START_PIN

    for slug in slugs:
        pins = pins_for_slug(root, slug)
        if pins is None:
            problems.append("記事 %s のピン番号を解決できませんでした" % slug)
            continue
        if not pins:
            problems.append("記事 %s に対応するピンが output/pins/ にありません" % slug)
            continue
        for pin_num in sorted(pins):
            if pin_num not in posted_pins:
                problems.append("ピン%d（記事 %s）がPinterest台帳に未記載です" % (pin_num, slug))
            if pin_num < start_pin:
                continue
            for service in services:
                if (pin_num, service) not in buffer_pairs:
                    problems.append(
                        "ピン%d / %s（記事 %s）がBuffer台帳に未記載です" % (pin_num, service, slug)
                    )
    return problems


def failed_post_steps(steps):
    """最後まで成功しなかった投稿stepを列挙する。"""
    last = {}
    for step in steps:
        if step.get("kind") != "post":
            continue
        key = (step.get("pin_num"), step.get("channel"))
        last[key] = bool(step.get("ok"))
    return ["ピン%s / %s の投稿が成功していません" % (k[0], k[1]) for k, ok in sorted(
        last.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))) if not ok]


# --------------------------------------------------------------------------
# handoff の組み立て
# --------------------------------------------------------------------------

COVERAGE_ALWAYS = (
    "outputs はこのrunの差分population（new / changed / deleted）であり、"
    "変化しなかった成果物（unchanged）は意図的に列挙していない。",
    "public/pin-images/ の削除は転送用コピーの刈り込みのため deleted から除外している。",
    "external_identity（投稿先で採番されたID等）は収集していない。",
)


def build_handoff(root, record, close_reason, now, head_rev=None,
                  extra_unresolved=None, extra_coverage=None,
                  extra_run_evidence=None, overlap_run_ids=None,
                  proxy_finalized=False):
    """1つのrunのhandoff辞書を作る。差分もstepも無い場合は None を返す。"""
    run_id = record["run_id"]
    base_rev = record.get("site_head")
    head_rev = head_rev or git_head(root)
    steps = read_steps(root, run_id)
    unresolved = list(extra_unresolved or [])
    coverage_notes = list(COVERAGE_ALWAYS) + list(extra_coverage or [])

    git_outputs = []
    if base_rev and head_rev:
        git_outputs = build_git_outputs(root, base_rev, head_rev)
    elif not base_rev:
        unresolved.append("run開始時点のsite HEADを記録できていないため、Git差分を確定できません")

    step_outputs, step_unresolved = build_step_outputs(
        root, steps, record.get("pin_ledger"), record.get("buffer_ledger"), run_id
    )
    unresolved.extend(step_unresolved)

    has_activity = bool(steps) or bool(git_outputs)
    if not has_activity and not unresolved:
        return None

    overlap_run_ids = sorted(set(overlap_run_ids or []))
    overlap = bool(overlap_run_ids) or proxy_finalized

    if overlap and git_outputs:
        for item in git_outputs:
            unresolved.append(
                "%s（%s）は区間の重なるrunがあるため、どのrunの成果物か確定できません"
                % (item["entity_id"], item["change"])
            )
        outputs = list(step_outputs)
    else:
        outputs = git_outputs + step_outputs

    # --- status ---
    publish_attempts = [s for s in steps if s.get("kind") == "publish_attempt"]
    topic_checks = [s for s in steps if s.get("kind") == "topic_check"]
    post_failures = failed_post_steps(steps)

    partial_reasons = []
    if overlap_run_ids:
        partial_reasons.append(
            "区間の重なるrun（%s）があるため、成果物の帰属を確定できません" % ", ".join(overlap_run_ids)
        )
    if proxy_finalized:
        partial_reasons.append("SessionEndを観測できず代理確定したため、runの終端が正確ではありません")

    new_slugs = article_slugs(outputs, "new")
    partial_reasons.extend(missing_pin_coverage(root, new_slugs))
    partial_reasons.extend(post_failures)
    if topic_checks and not publish_attempts:
        partial_reasons.append("題材の重複確認は行われましたが、公開の試行記録がありません")

    failure_reason = None
    if publish_attempts and publish_attempts[-1].get("result") == "NG" and not outputs:
        status = "failed"
        last = publish_attempts[-1]
        failure_reason = "publish-article.py が失敗しました（slug=%s / dry_run=%s / 失敗したチェック=%s）" % (
            last.get("slug"), last.get("dry_run"), last.get("failed_check") or "（特定できず）"
        )
    elif partial_reasons:
        status = "partial"
        failure_reason = " / ".join(partial_reasons)
    else:
        status = "completed"

    # --- coverage ---
    if unresolved:
        coverage_state = "partial"
    else:
        coverage_state = "complete"
    if status != "completed":
        coverage_notes.append("このrunは %s である: %s" % (status, failure_reason))

    # --- run_evidence_refs ---
    run_evidence = []
    if base_rev and head_rev:
        run_evidence.extend(git_commits_in_range(root, base_rev, head_rev))
    path = steps_path(root, run_id)
    if os.path.isfile(path):
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        run_evidence.append("%s#sha256:%s" % (rel, sha256_file(path)))
    run_evidence.extend(extra_run_evidence or [])
    if not run_evidence:
        rel = os.path.relpath(open_record_path(root, run_id), root).replace(os.sep, "/")
        run_evidence.append(rel)

    return {
        "contract_version": CONTRACT_VERSION,
        "target_date": record.get("opened_date"),
        "timezone": TIMEZONE,
        "run_id": run_id,
        "status": status,
        "failure_reason": failure_reason,
        "coverage": {"state": coverage_state, "reason": " ".join(coverage_notes)},
        "unresolved": unresolved,
        "run_evidence_refs": run_evidence,
        "outputs": outputs,
        "producer": {
            "session_id": record.get("session_id"),
            "opened_at": record.get("opened_at"),
            "closed_at": iso(now),
            "close_reason": close_reason,
            "site_head_base": base_rev,
            "site_head_final": head_rev,
        },
    }


def handoff_path(root, record):
    return os.path.join(
        handoff_dir(root),
        "%s_%s.json" % (record.get("opened_date"), safe_run_id(record["run_id"])),
    )


# --------------------------------------------------------------------------
# finalize
# --------------------------------------------------------------------------

def overlapping_run_ids(root, record, now):
    """_runs.tsv（直近48時間）から、自分の[open, close]区間と重なるrunを探す。"""
    since = now - datetime.timedelta(hours=RUNS_LOOKBACK_HOURS)
    rows = read_runs(root, since)
    intervals = {}
    for row in rows:
        entry = intervals.setdefault(row["run_id"], {"open": None, "close": None})
        if row["event"] == "open" and entry["open"] is None:
            entry["open"] = row["timestamp"]
        elif row["event"] == "close":
            entry["close"] = row["timestamp"]

    try:
        my_open = datetime.datetime.fromisoformat(record["opened_at"])
    except (KeyError, ValueError):
        return []
    my_close = now

    result = []
    for run_id, entry in intervals.items():
        if run_id == record["run_id"] or entry["open"] is None:
            continue
        other_close = entry["close"] or now
        if entry["open"] < my_close and my_open < other_close:
            result.append(run_id)
    result.extend(record.get("overlap_with") or [])
    return sorted(set(result))


def finalize_run(root=None, session_id=None, close_reason="session_end", now=None,
                 transcripts_dir=None):
    """自分のsession_idの開いているrunを確定する。戻り値: 書いたhandoffのpath or None"""
    base = root or PROJECT_ROOT
    session_id = session_id or session_id_from_env()
    if not session_id:
        log_error("finalize: session_idを取得できませんでした", base)
        return None

    record = find_open_record(base, session_id)
    if record is None:
        return None

    now = now or now_jst()
    proxy = close_reason == "session_end_not_observed"
    path = None
    try:
        overlap = overlapping_run_ids(base, record, now)
        document = build_handoff(
            base, record, close_reason, now,
            overlap_run_ids=overlap, proxy_finalized=proxy,
        )
        if document is not None:
            path = handoff_path(base, record)
            write_json_atomic(path, document)
    except Exception as e:
        log_error("finalize に失敗しました（run_id=%s）: %s" % (record["run_id"], e), base)
        try:
            document = {
                "contract_version": CONTRACT_VERSION,
                "target_date": record.get("opened_date"),
                "timezone": TIMEZONE,
                "run_id": record["run_id"],
                "status": "failed",
                "failure_reason": "handoffの生成に失敗したため、成果物を確定できませんでした: %s" % e,
                "coverage": {
                    "state": "unknown",
                    "reason": " ".join(COVERAGE_ALWAYS)
                    + " handoffの生成そのものが失敗したため、このrunのpopulationは未確定である。",
                },
                "unresolved": ["このrunの成果物population全体が未確定です"],
                "run_evidence_refs": [
                    os.path.relpath(open_record_path(base, record["run_id"]), base).replace(os.sep, "/")
                ],
                "outputs": [],
                "producer": {
                    "session_id": record.get("session_id"),
                    "opened_at": record.get("opened_at"),
                    "closed_at": iso(now),
                    "close_reason": close_reason,
                    "site_head_base": record.get("site_head"),
                    "site_head_final": None,
                },
            }
            path = handoff_path(base, record)
            write_json_atomic(path, document)
        finally:
            _close_out(base, record, now, close_reason)
        raise

    _close_out(base, record, now, close_reason)
    return path


def _close_out(root, record, now, close_reason):
    try:
        os.remove(open_record_path(root, record["run_id"]))
    except OSError:
        pass
    append_run_row(root, record["run_id"], record["session_id"], "close", iso(now), close_reason)


# --------------------------------------------------------------------------
# サブコマンド
# --------------------------------------------------------------------------

def cmd_open(argv):
    session_id, _reason = session_id_from_stdin()
    if not session_id:
        session_id = session_id_from_env()
    _record, warnings = open_run(session_id=session_id)
    for line in warnings:
        print(line)
    return 0


def cmd_finalize(argv):
    """SessionEndフックから起動される。

    --session-id / --close-reason は復旧用（SessionEndが観測されないまま残った
    runを手で閉じるため）。フック経由ではどちらも渡さない。
    """
    override_id = None
    override_reason = None
    i = 0
    while i < len(argv):
        if argv[i] == "--session-id":
            i += 1
            override_id = argv[i]
        elif argv[i] == "--close-reason":
            i += 1
            override_reason = argv[i]
        else:
            print("不明な引数です: %s" % argv[i])
            return 1
        i += 1

    if override_id:
        session_id = override_id
        close_reason = override_reason or "session_end_not_observed"
    else:
        session_id, reason = session_id_from_stdin()
        if not session_id:
            session_id = session_id_from_env()
        close_reason = "session_end:%s" % reason if reason else "session_end"

    try:
        path = finalize_run(session_id=session_id, close_reason=close_reason)
    except Exception:
        return 1
    if path:
        print(os.path.relpath(path, PROJECT_ROOT).replace(os.sep, "/"))
    return 0


BACKFILL_COVERAGE = (
    "run_id は data/lessons-session.txt（mtime 2026-09-20 05:18:45 +0900）から"
    "推定したsession_idに基づく。SessionStart / SessionEnd の実記録は存在しない。",
    "このrunのピン投稿文について、実際にAPIへ送った本文payloadが記録されていないため、"
    "投稿文のcontent_identityを確定できない。",
)


def cmd_backfill(argv):
    session_id = None
    base_rev = None
    head_rev = None
    opened_at = None
    dry_run = False
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--session-id":
            i += 1
            session_id = argv[i]
        elif arg == "--base":
            i += 1
            base_rev = argv[i]
        elif arg == "--head":
            i += 1
            head_rev = argv[i]
        elif arg == "--opened-at":
            i += 1
            opened_at = argv[i]
        elif arg == "--dry-run":
            dry_run = True
        else:
            print("不明な引数です: %s" % arg)
            return 1
        i += 1

    if not (session_id and base_rev and head_rev and opened_at):
        print("--session-id / --base / --head / --opened-at はすべて必須です")
        return 1

    root = PROJECT_ROOT
    opened_date = datetime.date.fromisoformat(opened_at)
    record = {
        "run_id": "claude-run:%s:1" % session_id,
        "session_id": session_id,
        "opened_at": iso(datetime.datetime.combine(opened_date, datetime.time(0, 0), JST)),
        "opened_date": opened_date.isoformat(),
        "site_head": base_rev,
        "pin_ledger": [],
        "buffer_ledger": [],
        "overlap_with": [],
    }

    # step記録が無いため、このrunで投稿したピンの投稿文は unresolved に置く。
    pin_numbers = sorted({
        int(m.group(1))
        for status, path in git_name_status(root, base_rev, head_rev)
        if status == "A" and (m := re.search(r"/pin(\d+)\.jpg$", path))
    })
    channels = ["pinterest"] + list(buffer_services())
    unresolved = [
        "pin-text:%d:%s の送信payloadが記録されていないため、content_identityを確定できません"
        % (pin_num, channel)
        for pin_num in pin_numbers
        for channel in channels
    ]

    report = os.path.join(root, "reports", "%s.md" % opened_date.isoformat())
    extra_evidence = []
    if os.path.isfile(report):
        extra_evidence.append("reports/%s.md#sha256:%s" % (opened_date.isoformat(), sha256_file(report)))

    document = build_handoff(
        root, record, "backfill", now_jst(), head_rev=head_rev,
        extra_unresolved=unresolved, extra_coverage=BACKFILL_COVERAGE,
        extra_run_evidence=extra_evidence,
    )
    if document is None:
        print("差分もstep記録も無いため、handoffは作成しません")
        return 0

    if dry_run:
        print(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    os.makedirs(handoff_dir(root), exist_ok=True)
    path = handoff_path(root, record)
    write_json_atomic(path, document)
    append_run_row(root, record["run_id"], session_id, "open", record["opened_at"])
    append_run_row(root, record["run_id"], session_id, "close", iso(now_jst()), "backfill")
    print(os.path.relpath(path, root).replace(os.sep, "/"))
    return 0


COMMANDS = {
    "open": cmd_open,
    "finalize": cmd_finalize,
    "backfill": cmd_backfill,
}


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if not argv or argv[0] not in COMMANDS:
        print(__doc__)
        return 1
    return COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
