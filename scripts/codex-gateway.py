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

タイムアウトと救済について（L043・2026-09-08）:
  codex exec の本実行に EXEC_TIMEOUT_SEC（既定 300 秒）を設ける。子プロセスの
  PATH 先頭に codex-resources を足す根治（_codex_child_env）を入れているため
  正常時は数分以内に終わる。打ち切った場合でも generated_images 配下に成果物
  .png が既にあれば通常時と同じ経路でコピーし、status ok / 終了コード 0 で返す。
  そのとき標準出力の1行JSONに timeout_rescued: true を含める。成果物が無ければ
  従来どおり終了コード 5。終了コードの意味は追加も変更もしない。

標準出力には1行のJSONを出す。進捗・説明はすべて標準エラー出力へ出す。
唯一の例外として、実行前のキャッシュ正規化（ensure_models_cache_consistent）が
実際に動いたときだけ、JSONとは別行の告知を標準出力へ出す（D-0204）。
"""
import argparse
import json
import os
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

# codex exec の本実行タイムアウト（秒）。L043 の根治（子プロセス PATH に
# codex-resources を追加）が入っているため正常時は数分以内に終わる。打ち切っても
# 成果物 .png が既にあれば成功扱いで拾う（run_exec の TimeoutExpired 捕捉部）。
# 検証時のみ環境変数 CODEX_EXEC_TIMEOUT_SEC で上書きする（運用では設定しない）。
EXEC_TIMEOUT_SEC = 300
_env_timeout = os.environ.get("CODEX_EXEC_TIMEOUT_SEC")
if _env_timeout is not None and _env_timeout.strip():
    try:
        EXEC_TIMEOUT_SEC = int(_env_timeout)
    except ValueError:
        pass


def eprint(msg):
    sys.stderr.write(str(msg) + "\n")
    sys.stderr.flush()


def emit(status, purpose, method, artifact, source, message, extra=None):
    payload = {
        "status": status,
        "purpose": purpose,
        "method": method,
        "artifact": artifact,
        "source": source,
        "message": message,
    }
    if extra:
        payload.update(extra)
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


MODELS_CACHE_PATH = HOME / ".codex" / "models_cache.json"
DEBUG_MODELS_TIMEOUT_SEC = 60


def _codex_cli_version():
    """`codex --version` の出力からバージョン文字列を取り出す。取れなければ None。

    出力例: "codex-cli 0.145.0" → "0.145.0"
    """
    try:
        proc = subprocess.run(
            ["codex", "--version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = ((proc.stdout or "") + " " + (proc.stderr or "")).strip()
    for token in text.split():
        if token and token[0].isdigit():
            return token
    return None


def ensure_models_cache_consistent():
    """codex 実行前に models_cache.json の client_version を CLI と照合し、必要時のみ正規化する（D-0204）。

    新旧2つのCodexクライアントが同一の ~/.codex を共有すると、新側が書いた
    models_cache.json を旧側（0.145.0）が読めず exit 5 になる（L040・2026-09-06 実測）。
    一致していればネットワークを一切叩かずに戻る。不一致・欠損・破損・キー無しの
    いずれかなら `codex debug models` を1回だけ実行してキャッシュを再生成させる。

    この関数は新たな停止条件を増やさない。正規化に失敗しても告知だけして戻る。
    戻り値は「正規化を実行したか」の bool。
    """
    cli_version = _codex_cli_version()

    cached_version = None
    reason = None
    if cli_version is None:
        reason = "`codex --version` からバージョンを取得できなかった"
    elif not MODELS_CACHE_PATH.is_file():
        reason = "models_cache.json が存在しない"
    else:
        try:
            data = json.loads(MODELS_CACHE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            reason = "models_cache.json をJSONとして読めない"
        else:
            if not isinstance(data, dict) or "client_version" not in data:
                reason = "models_cache.json に client_version キーが無い"
            else:
                cached_version = data.get("client_version")
                if cached_version != cli_version:
                    reason = ("client_version 不一致（キャッシュ=%s／CLI=%s）"
                              % (cached_version, cli_version))

    if reason is None:
        # 一致。ネットワークを叩かず、標準出力にも何も足さない。
        eprint("models_cache.json の client_version は CLI と一致（%s）。正規化は不要。" % cli_version)
        return False

    print("[codex-gateway] models_cache.json を正規化します（理由: %s）。"
          "`codex debug models` を1回実行します。" % reason)
    sys.stdout.flush()
    try:
        proc = subprocess.run(
            ["codex", "debug", "models"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=DEBUG_MODELS_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        print("[codex-gateway] `codex debug models` が %d秒でタイムアウトしました。"
              "正規化せずに本実行へ進みます。" % DEBUG_MODELS_TIMEOUT_SEC)
        sys.stdout.flush()
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        print("[codex-gateway] `codex debug models` の実行に失敗しました（%s）。"
              "正規化せずに本実行へ進みます。" % exc)
        sys.stdout.flush()
        return True

    if proc.returncode != 0:
        print("[codex-gateway] `codex debug models` が rc=%d で終了しました。"
              "正規化できていない可能性がありますが本実行へ進みます。" % proc.returncode)
        sys.stdout.flush()
    else:
        print("[codex-gateway] `codex debug models` を実行しました（rc=0）。")
        sys.stdout.flush()
    return True


def _codex_child_env():
    """codex exec の子プロセスへ渡す環境を作る。PATH 先頭に codex-resources を足す（L043）。

    CLI 0.145.0 は Windows サンドボックスのセットアップヘルパ
    (codex-windows-sandbox-setup.exe) をファイル名だけで探し、見つからないと
    codex exec がリトライで無限にぶら下がる（2026-09-08 の対照実験で確認）。
    codex 実体と同じリリース配下の codex-resources を PATH に足すと正常終了する。
    実体解決や codex-resources が確認できなければ None を返し、既定の環境で動かす。
    システム・ユーザーの PATH は変更しない（親プロセス内の env コピーだけを書き換える）。
    """
    exe = shutil.which("codex")
    if not exe:
        return None
    try:
        real = Path(os.path.realpath(exe))
    except OSError:
        return None
    # <release>/bin/codex.exe → <release>/codex-resources
    resources = real.parent.parent / "codex-resources"
    if not resources.is_dir():
        return None
    env = os.environ.copy()
    env["PATH"] = str(resources) + os.pathsep + env.get("PATH", "")
    return env


def _kill_codex_tree(pid):
    """gateway が spawn した codex の PID ツリーだけを終了させる。

    プロセス名指定（taskkill /IM）は使わない。稼働中の常駐デスクトップ版
    codex.exe には介入しないため、必ず PID 指定 + /T でツリーを畳む。
    """
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def _run_codex_exec(cmd, env):
    """codex exec を実行し (stdout, stderr, returncode, timed_out) を返す。

    EXEC_TIMEOUT_SEC を超えたら gateway が起動した PID ツリーのみ終了させ、
    timed_out=True で戻る（成否は呼び出し側が成果物 .png の実在で判定する）。
    起動自体の失敗（OSError）はそのまま送出する。
    """
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    try:
        out, err = proc.communicate(timeout=EXEC_TIMEOUT_SEC)
        return out or "", err or "", proc.returncode, False
    except subprocess.TimeoutExpired:
        _kill_codex_tree(proc.pid)
        try:
            out, err = proc.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            out, err = "", ""
        return out or "", err or "", proc.returncode, True


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

    # (1-2) codex 実行前のキャッシュ正規化（D-0204・失敗しても止めない）
    ensure_models_cache_consistent()

    # (2) codex exec を非対話実行する
    # --skip-git-repo-check: このプロジェクトのルート直下は非Git管理（D-0043）のため、
    # これを付けないと codex exec が "Not inside a trusted directory" で即座に失敗する。
    cmd = ["codex", "exec", "--json", "-s", "read-only", "--skip-git-repo-check", prompt]
    child_env = _codex_child_env()
    if child_env is not None:
        eprint("codex exec の子プロセス PATH 先頭に codex-resources を追加します（L043 対策）。")
    else:
        eprint("codex-resources を解決できず。既定の環境で codex exec を実行します。")
    eprint("codex exec を開始します（-s read-only / --json / timeout=%d秒）: prompt %d 文字"
           % (EXEC_TIMEOUT_SEC, len(prompt)))
    try:
        stdout, stderr_text, returncode, timed_out = _run_codex_exec(cmd, child_env)
    except OSError as exc:
        return fail(EXIT_LAUNCH_FAILED, purpose, method,
                    "codex exec の起動に失敗しました: %s" % exc)

    # (3) --json の出力を全行ファイルへ保存し、thread.started 行からスレッドIDを取り出す
    log_path.write_text(stdout, encoding="utf-8")
    lines = stdout.splitlines()
    thread_id = extract_thread_id(lines)
    if timed_out:
        eprint("codex exec を %d秒で打ち切り、起動した PID ツリーを終了しました"
               "（rc=%s・成功判定には使わない）。ログ: %s" % (EXEC_TIMEOUT_SEC, returncode, log_path))
    else:
        eprint("codex exec 終了（rc=%s・成功判定には使わない）。ログ: %s" % (returncode, log_path))
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
        to_note = "（timeout %d秒で打ち切り後）" % EXEC_TIMEOUT_SEC if timed_out else ""
        return fail(EXIT_ARTIFACT_MISSING, purpose, method,
                    "成果物の .png を検出できませんでした%s。%s ／ codex rc=%s ／ stderr: %s"
                    % (to_note, base_message, returncode, stderr_text.strip()[:400]))

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
    extra = {"timeout_rescued": True} if timed_out else None
    tail = " ／ timeout %d秒で打ち切り後に成果物を救済" % EXEC_TIMEOUT_SEC if timed_out else ""
    emit("ok", purpose, method, str(dest), str(source),
         "%s ／ 古いディレクトリ削除: %d件%s" % (base_message, removed, tail),
         extra=extra)
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
