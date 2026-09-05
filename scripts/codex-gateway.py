# -*- coding: utf-8 -*-
"""Claude Code から Codex を呼ぶ唯一の入口（D-0199）。

用途（--purpose）ごとに呼び出し方式をルーティング表で決め、方式ごとの処理へ振り分ける。
将来の用途追加は PURPOSE_METHOD に1行足すだけで済む形にしてある。

現在実装済みの方式は "exec"（codex exec の非対話実行）のみ。
"mcp" / "app-server" は未実装であり、呼ばれた時点で終了コード3で停止する
（未実装であることを文章ではなく実行時の停止で示すため）。

終了コード:
  0 = 成功（~/Downloads へのコピーまで完了）
  2 = 前提不備（codex が見つからない／未ログイン／generated_images に到達できない）
  3 = 方式未実装（mcp / app-server）／未登録の用途
  4 = codex exec の起動自体に失敗した
  5 = 成果物の .png を検出できなかった、またはコピーに失敗した

成功判定について:
  codex exec の終了コードは成功判定に使わない。内部のPowerShell実行が失敗しても
  codex exec 全体は 0 を返すことが実測されているため（設計調査 第2便 D-1-3）。
  成功判定は「~/Downloads に --out-name のファイルが実在すること」で行う。

標準出力には1行のJSONのみを出す。進捗・説明はすべて標準エラー出力へ出す。
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# --- 用途 → 方式のルーティング表（将来の用途追加はここへ1行足す） ---
PURPOSE_METHOD = {
    "image-gen": "exec",
}

IMPLEMENTED_METHODS = {"exec"}

HOME = Path.home()
GENERATED_IMAGES_DIR = HOME / ".codex" / "generated_images"
DOWNLOADS_DIR = HOME / "Downloads"
LOG_DIR = Path(__file__).resolve().parent.parent.parent / "tmp" / "codex-gateway"

# 容量対策（実行時間が蓄積量に比例しないよう、1回の実行での削除数に上限を置く）
PRUNE_AGE_DAYS = 30
PRUNE_MAX_DIRS = 20

EXIT_OK = 0
EXIT_PRECONDITION = 2
EXIT_NOT_IMPLEMENTED = 3
EXIT_LAUNCH_FAILED = 4
EXIT_ARTIFACT_MISSING = 5


def eprint(msg):
    sys.stderr.write(str(msg) + "\n")
    sys.stderr.flush()


def emit(status, purpose, method, artifact, source, message):
    payload = {
        "status": status,
        "purpose": purpose,
        "method": method,
        "artifact": artifact,
        "source": source,
        "message": message,
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code, purpose, method, message):
    emit("error", purpose, method, None, None, message)
    return code


def extract_thread_id(log_lines):
    """--json の出力から thread.started のスレッドIDを取り出す。見つからなければ None。"""
    for line in log_lines:
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        kind = obj.get("type") or obj.get("event") or ""
        if "thread.started" not in str(kind):
            continue
        for key in ("thread_id", "threadId", "id"):
            val = obj.get(key)
            if isinstance(val, str) and val:
                return val
        thread = obj.get("thread")
        if isinstance(thread, dict):
            for key in ("id", "thread_id"):
                val = thread.get(key)
                if isinstance(val, str) and val:
                    return val
    return None


def find_artifact(thread_id, started_at):
    """成果物の .png を探す。戻り値は (Path or None, 検出経路の説明文字列)。

    主: generated_images/<スレッドID>/ 配下の .png
    副: 主が空または存在しない場合のみ、generated_images 配下全体から開始時刻より新しい .png
    """
    if thread_id:
        primary_dir = GENERATED_IMAGES_DIR / thread_id
        if primary_dir.is_dir():
            pngs = sorted(primary_dir.glob("*.png"), key=lambda p: p.stat().st_mtime)
            if pngs:
                return pngs[-1], "主（generated_images/<thread_id>/ 配下）"

    candidates = []
    for png in GENERATED_IMAGES_DIR.rglob("*.png"):
        try:
            if png.stat().st_mtime >= started_at:
                candidates.append(png)
        except OSError:
            continue
    if candidates:
        candidates.sort(key=lambda p: p.stat().st_mtime)
        return candidates[-1], "副（generated_images 配下・開始時刻より新しい .png）"
    return None, "検出できず"


def prune_old_dirs():
    """generated_images 配下の古いディレクトリを削除する（最大 PRUNE_MAX_DIRS 件で打ち切る）。"""
    if not GENERATED_IMAGES_DIR.is_dir():
        return 0
    cutoff = time.time() - PRUNE_AGE_DAYS * 86400
    removed = 0
    for child in GENERATED_IMAGES_DIR.iterdir():
        if removed >= PRUNE_MAX_DIRS:
            break
        if not child.is_dir():
            continue
        try:
            if child.stat().st_mtime >= cutoff:
                continue
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
        except OSError:
            continue
    return removed


def run_exec(purpose, prompt_file, out_name):
    method = "exec"

    if shutil.which("codex") is None:
        return fail(EXIT_PRECONDITION, purpose, method,
                    "codex コマンドが見つかりません（PATH未設定または未インストール）。")

    prompt_path = Path(prompt_file)
    if not prompt_path.is_file():
        return fail(EXIT_PRECONDITION, purpose, method,
                    "--prompt-file が存在しません: %s" % prompt_path)
    prompt = prompt_path.read_text(encoding="utf-8")
    if not prompt.strip():
        return fail(EXIT_PRECONDITION, purpose, method,
                    "--prompt-file の内容が空です: %s" % prompt_path)

    if not DOWNLOADS_DIR.is_dir():
        return fail(EXIT_PRECONDITION, purpose, method,
                    "~/Downloads が存在しません: %s" % DOWNLOADS_DIR)

    # (1) 実行開始時刻を記録する
    started_at = time.time()
    stamp = datetime.fromtimestamp(started_at).strftime("%Y%m%d-%H%M%S")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / ("%s-%s.jsonl" % (stamp, purpose))

    # (2) codex exec を非対話実行する
    # --skip-git-repo-check: このプロジェクトのルート直下は非Git管理（D-0043）のため、
    # これを付けないと codex exec が "Not inside a trusted directory" で即座に失敗する。
    cmd = ["codex", "exec", "--json", "-s", "read-only", "--skip-git-repo-check", prompt]
    eprint("codex exec を開始します（-s read-only / --json）: prompt %d 文字" % len(prompt))
    try:
        proc = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        return fail(EXIT_LAUNCH_FAILED, purpose, method,
                    "codex exec の起動に失敗しました: %s" % exc)

    # (3) --json の出力を全行ファイルへ保存し、thread.started 行からスレッドIDを取り出す
    stdout = proc.stdout or ""
    stderr_text = proc.stderr or ""
    log_path.write_text(stdout, encoding="utf-8")
    lines = stdout.splitlines()
    thread_id = extract_thread_id(lines)
    eprint("codex exec 終了（rc=%d・成功判定には使わない）。ログ: %s" % (proc.returncode, log_path))
    eprint("thread.started のID: %s" % (thread_id or "取得できず"))

    if not GENERATED_IMAGES_DIR.is_dir():
        return fail(EXIT_PRECONDITION, purpose, method,
                    "generated_images に到達できません: %s ／ codexログ: %s ／ stderr: %s"
                    % (GENERATED_IMAGES_DIR, log_path, stderr_text.strip()[:400]))

    # (4) 成果物の検出
    source, how = find_artifact(thread_id, started_at)
    base_message = ("codexログ: %s ／ thread.started ID: %s ／ 検出経路: %s"
                    % (log_path, thread_id or "取得できず", how))
    if source is None:
        prune_old_dirs()
        return fail(EXIT_ARTIFACT_MISSING, purpose, method,
                    "成果物の .png を検出できませんでした。%s ／ codex rc=%d ／ stderr: %s"
                    % (base_message, proc.returncode, stderr_text.strip()[:400]))

    # (5) ~/Downloads へコピー
    dest = DOWNLOADS_DIR / out_name
    try:
        shutil.copy2(source, dest)
    except OSError as exc:
        prune_old_dirs()
        return fail(EXIT_ARTIFACT_MISSING, purpose, method,
                    "コピーに失敗しました（%s → %s）: %s ／ %s" % (source, dest, exc, base_message))

    # 成功判定はファイルの実在で行う（codex exec の終了コードは使わない）
    if not dest.is_file():
        prune_old_dirs()
        return fail(EXIT_ARTIFACT_MISSING, purpose, method,
                    "コピー後に %s が実在しません。%s" % (dest, base_message))

    removed = prune_old_dirs()

    # (6) 結果を出力する
    emit("ok", purpose, method, str(dest), str(source),
         "%s ／ 古いディレクトリ削除: %d件" % (base_message, removed))
    return EXIT_OK


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Claude Code から Codex を呼ぶ唯一の入口（D-0199）")
    parser.add_argument("--purpose", required=True, help="用途名（ルーティング表のキー）")
    parser.add_argument("--prompt-file", required=True, help="プロンプト本文のファイルパス")
    parser.add_argument("--out-name", required=True, help="~/Downloads に置く最終ファイル名")
    args = parser.parse_args()

    purpose = args.purpose
    method = PURPOSE_METHOD.get(purpose)
    if method is None:
        eprint("未登録の用途です: %s（登録済み: %s）"
               % (purpose, "／".join(sorted(PURPOSE_METHOD))))
        return fail(EXIT_NOT_IMPLEMENTED, purpose, None,
                    "未登録の用途です。PURPOSE_METHOD に方式を登録してください。")

    if method not in IMPLEMENTED_METHODS:
        eprint("方式 %s は未実装です（用途: %s）。" % (method, purpose))
        return fail(EXIT_NOT_IMPLEMENTED, purpose, method,
                    "方式 %s は未実装のため実行しません。" % method)

    return run_exec(purpose, args.prompt_file, args.out_name)


if __name__ == "__main__":
    sys.exit(main())
