# -*- coding: utf-8 -*-
"""Claude Code から Codex を呼ぶ唯一の入口（D-0199）。

用途（--purpose）ごとに呼び出し方式をルーティング表で決め、方式ごとの処理へ振り分ける。
将来の用途追加は PURPOSE_METHOD に1行足すだけで済む形にしてある。

現在実装済みの方式は "exec"（codex exec の非対話実行）のみ。
"mcp" / "app-server" は未実装であり、呼ばれた時点で終了コード3で停止する
（未実装であることを文章ではなく実行時の停止で示すため）。

用途:
  image-gen    画像1枚を生成し ~/Downloads/<--out-name> へコピーする（D-0199）。
               引数: --prompt-file <パス> --out-name <ファイル名>
  growth-audit 全コンテンツの週次監査（D-0251）。Codex は読み取り専用で動き、
               最終メッセージを --output-file へ保存する。
               引数: --prompt-file <パス> --output-file <growth/outputs/ 配下のパス>
               実行: codex exec -C <プロジェクトルート> -s read-only --json -o <output-file>
               （GROWTH_AUDIT_HARDENING_ARGS で外部遮断を上乗せする・D-0253）
               プロンプトは標準入力で渡す（Windows のコマンドライン長上限 約3.2万文字を避けるため）。
               -o のファイルが書かれなかった場合は、--json の出力から最終の agent_message を
               gateway が取り出して --output-file へ書く（Codex に書き込み権限は与えない）。

終了コード:
  0 = 成功（image-gen: ~/Downloads へのコピーまで完了／growth-audit: --output-file が実在し空でない）
  2 = 前提不備（codex が見つからない／未ログイン／generated_images に到達できない／
      必須引数・プロンプトファイルの不備）
  3 = 方式未実装（mcp / app-server）／未登録の用途／
      growth-audit の --output-file が growth/outputs/ 配下でない
  4 = codex exec の起動自体に失敗した
  5 = 成果物を検出できなかった（image-gen: .png の検出またはコピーに失敗／
      growth-audit: --output-file が作られない、または空）

成功判定について:
  codex exec の終了コードは成功判定に使わない。内部のPowerShell実行が失敗しても
  codex exec 全体は 0 を返すことが実測されているため（設計調査 第2便 D-1-3）。
  image-gen の成功判定は「~/Downloads に --out-name のファイルが実在すること」で行う。
  growth-audit の成功判定は「--output-file が実行開始後に書かれ、空でないこと」で行う。

タイムアウトと救済について（L043・2026-09-08）:
  codex exec の本実行に EXEC_TIMEOUT_SEC（既定 300 秒・growth-audit は
  AUDIT_TIMEOUT_SEC 既定 3600 秒）を設ける。どちらも環境変数 CODEX_EXEC_TIMEOUT_SEC で上書きできる。
  以下の救済は image-gen の説明。子プロセスの
  PATH 先頭に codex-resources を足す根治（_codex_child_env）を入れているため
  正常時は数分以内に終わる。打ち切った場合でも generated_images 配下に成果物
  .png が既にあれば通常時と同じ経路でコピーし、status ok / 終了コード 0 で返す。
  そのとき標準出力の1行JSONに timeout_rescued: true を含める。成果物が無ければ
  従来どおり終了コード 5。終了コードの意味は追加も変更もしない。

モデル非対応の自動切替について（D-0243・2026-09-27）:
  ~/.codex/config.toml の model が Codex CLI の対応範囲より先に進むと、codex exec が
  「The '<model>' model requires a newer version of Codex」（HTTP 400）で失敗する。
  gateway はまず従来どおり config のモデル（--model 指定時はそのモデル）で実行し、
  成果物が無く、かつ出力が MODEL_UNSUPPORTED_RE に一致した場合に限り、FALLBACK_MODEL を
  -m で明示して1回だけ再試行する。再試行した回は標準出力へ【注意】の1行を出す。
  利用上限・認証・ネットワーク等のそれ以外の失敗では再試行せず、従来の終了コードで返す。
  共有設定（~/.codex/config.toml）と Codex CLI 本体は変更しない。

標準出力には1行のJSONを出す。進捗・説明はすべて標準エラー出力へ出す。
唯一の例外として、実行前のキャッシュ正規化（ensure_models_cache_consistent）が
実際に動いたときだけ、JSONとは別行の告知を標準出力へ出す（D-0204）。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
from datetime import datetime
from pathlib import Path

# --- 用途 → 方式のルーティング表（将来の用途追加はここへ1行足す） ---
PURPOSE_METHOD = {
    "image-gen": "exec",
    "growth-audit": "exec",
}

IMPLEMENTED_METHODS = {"exec"}

HOME = Path.home()
GENERATED_IMAGES_DIR = HOME / ".codex" / "generated_images"
DOWNLOADS_DIR = HOME / "Downloads"
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOG_DIR = PROJECT_ROOT / "tmp" / "codex-gateway"
# growth-audit の --output-file に許可する唯一の置き場（D-0251）
AUDIT_OUTPUTS_DIR = PROJECT_ROOT / "growth" / "outputs"

# growth-audit 専用の外部遮断（D-0253）。起動引数・子プロセス環境変数だけで完結させ、
# ~/.codex/config.toml・Codexアプリ側の設定・image-gen の起動内容は一切変えない。
# growth-audit の実行時だけ、次を無効にする: ネットワーク（シェル・Web検索）／
# アプリ連携（MCPコネクタ・プラグイン経由の computer-use を含む）／ブラウザ操作・
# computer-use／画像生成／サブエージェントの起動。ローカルファイル・ローカル画像の
# 閲覧は無効にしない（対象外）。
#
# 実測の経緯（2026-09-27・growth/outputs/probe-hardening.md）:
#   1) `-s read-only` 単体はシェルからのネットワーク到達を遮断しない
#      （reports/2026-09-27-7.md で既知）。`-c features.network_proxy.enabled=true`
#      （domains 未指定で全拒否を期待）も効果が無く、HTTP 200 が通った。
#   2) growth-audit を実行するだけで ~/.codex/config.toml のハッシュが変わることを
#      確認した（Codexアプリ全体で共有される、他プロジェクトの trust_level 追記等が
#      入るファイルのため）。このファイルには browser/computer-use/chrome 等の
#      プラグイン登録・mcp_servers.node_repl（computer-use を提供する MCP サーバ）・
#      approval_policy="on-request"+approvals_reviewer="guardian_subagent"
#      （非対話実行でも自動承認されてしまう設定）が入っている。
#   3) `--ignore-user-config` でこのファイルを読み込ませないようにしたところ、
#      ハッシュ不変・プラグイン一式の不登録（apps/browser/computer-use が実際に
#      「ツール無し」になった）に加え、副次効果としてシェルの HTTP コマンドが
#      Codex 自身の実行前チェックにより `rejected: blocked by policy` で拒否される
#      ようになった（承認者不在時の既定ポリシーに戻ったため）。狙って作った経路では
#      ないため、他のシェルコマンドの書き方で素通りする余地が残る可能性がある
#      （断定しない・残課題として補足に書く）。
#   4) Web検索は `[features].web_search` ではなく、トップレベルの `web_search`
#      （"live"/"indexed"/"cached"/"disabled"）で制御することが、1回目の実行時の
#      非推奨警告（`--json` ログ）から判明した。`web_search="disabled"` を使う。
#   5) computer-use 系プラグイン向けの --disable は (3) の --ignore-user-config で
#      冗長になった可能性が高いが、多重防御として残す。
GROWTH_AUDIT_HARDENING_ARGS = [
    "-c", 'web_search="disabled"',
    "--disable", "apps",
    "--disable", "browser_use",
    "--disable", "browser_use_external",
    "--disable", "browser_use_full_cdp_access",
    "--disable", "computer_use",
    "--disable", "in_app_browser",
    "--disable", "plugins",
    "--disable", "remote_plugin",
    "--disable", "plugin_sharing",
    "--disable", "image_generation",
    "--disable", "multi_agent",
    # シェルが起動する子プロセス（PowerShell 等）だけにプロキシ環境変数を注入する
    # （shell_environment_policy.set は codex 自身の通信には影響しない・
    # codex 自身の env を直接書き換えると wss://chatgpt.com への接続まで
    # 塞いでしまうことを実測で確認したため、この経路に切り替えた）。
    # 誰も listen していないループバックポートへ向け、接続を即時拒否させる
    # （(3) のガード拒否をすり抜けた場合の多重防御）。
    "-c", 'shell_environment_policy.set.HTTP_PROXY="http://127.0.0.1:1"',
    "-c", 'shell_environment_policy.set.HTTPS_PROXY="http://127.0.0.1:1"',
    "-c", 'shell_environment_policy.set.http_proxy="http://127.0.0.1:1"',
    "-c", 'shell_environment_policy.set.https_proxy="http://127.0.0.1:1"',
    "-c", 'shell_environment_policy.set.ALL_PROXY="http://127.0.0.1:1"',
    "-c", 'shell_environment_policy.set.NO_PROXY=""',
    "-c", 'shell_environment_policy.set.no_proxy=""',
]

# 容量対策（実行時間が蓄積量に比例しないよう、1回の実行での削除数に上限を置く）
PRUNE_AGE_DAYS = 30
PRUNE_MAX_DIRS = 20

# モデル非対応の自動切替（D-0243）。予備モデルは Codex CLI 0.145.0 で実際に成功した実績のある
# モデル（2026-09-26 05:11〜05:15 の gateway 実行4回・セッション記録の model=gpt-5.6-sol）。
FALLBACK_MODEL = "gpt-5.6-sol"
# 「モデル非対応」の判別文字列（2026-09-06・2026-09-27 の gateway ログ／L070 で同一文言を確認）:
#   "The 'gpt-6-astra' model requires a newer version of Codex. Please upgrade ..."
# 利用上限・認証・ネットワーク等の他の失敗にはこの文言が出ないため、再試行の対象にならない。
MODEL_UNSUPPORTED_RE = re.compile(r"model requires a newer version of codex", re.IGNORECASE)
CONFIG_TOML_PATH = HOME / ".codex" / "config.toml"

EXIT_OK = 0
EXIT_PRECONDITION = 2
EXIT_NOT_IMPLEMENTED = 3
EXIT_LAUNCH_FAILED = 4
EXIT_ARTIFACT_MISSING = 5

# codex exec の本実行タイムアウト（秒）。L043 の根治（子プロセス PATH に
# codex-resources を追加）が入っているため正常時は数分以内に終わる。打ち切っても
# 成果物 .png が既にあれば成功扱いで拾う（run_exec の TimeoutExpired 捕捉部）。
# 検証時のみ環境変数 CODEX_EXEC_TIMEOUT_SEC で上書きする（運用では設定しない）。
def _timeout_from_env(default):
    value = os.environ.get("CODEX_EXEC_TIMEOUT_SEC")
    if value is not None and value.strip():
        try:
            return int(value)
        except ValueError:
            pass
    return default


EXEC_TIMEOUT_SEC = _timeout_from_env(300)
# growth-audit は全コンテンツを読むため長い（D-0251）。上書きは同じ環境変数で行う。
AUDIT_TIMEOUT_SEC = _timeout_from_env(3600)


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


def _run_codex_exec(cmd, env, timeout, input_text=None):
    """codex exec を実行し (stdout, stderr, returncode, timed_out) を返す。

    timeout 秒を超えたら gateway が起動した PID ツリーのみ終了させ、
    timed_out=True で戻る（成否は呼び出し側が成果物の実在で判定する）。
    input_text を渡すとプロンプトとして標準入力へ流す（growth-audit）。
    起動自体の失敗（OSError）はそのまま送出する。
    """
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    try:
        out, err = proc.communicate(input=input_text, timeout=timeout)
        return out or "", err or "", proc.returncode, False
    except subprocess.TimeoutExpired:
        _kill_codex_tree(proc.pid)
        try:
            out, err = proc.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            out, err = "", ""
        return out or "", err or "", proc.returncode, True


def _config_model():
    """~/.codex/config.toml のトップレベル model を読む（読み取りのみ）。取れなければ None。"""
    try:
        with open(CONFIG_TOML_PATH, "rb") as fh:
            value = tomllib.load(fh).get("model")
    except (OSError, ValueError):
        return None
    return value if isinstance(value, str) and value else None


def _is_model_unsupported(*texts):
    """出力（stdout の --json 全行・stderr）に「モデル非対応」の文言があるか。"""
    return any(MODEL_UNSUPPORTED_RE.search(t or "") for t in texts)


def _read_prompt(purpose, method, prompt_file):
    """--prompt-file を読む。戻り値は (prompt or None, 失敗時の終了コード or None)。"""
    if shutil.which("codex") is None:
        return None, fail(EXIT_PRECONDITION, purpose, method,
                          "codex コマンドが見つかりません（PATH未設定または未インストール）。")
    prompt_path = Path(prompt_file)
    if not prompt_path.is_file():
        return None, fail(EXIT_PRECONDITION, purpose, method,
                          "--prompt-file が存在しません: %s" % prompt_path)
    prompt = prompt_path.read_text(encoding="utf-8")
    if not prompt.strip():
        return None, fail(EXIT_PRECONDITION, purpose, method,
                          "--prompt-file の内容が空です: %s" % prompt_path)
    return prompt, None


def _prepare_exec(purpose, model_override):
    """用途共通の実行準備。戻り値は (started_at, log_path, child_env, config_model)。

    キャッシュ正規化（D-0204）と codex-resources の PATH 追加（L043）はここで行う。
    """
    started_at = time.time()
    stamp = datetime.fromtimestamp(started_at).strftime("%Y%m%d-%H%M%S")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / ("%s-%s.jsonl" % (stamp, purpose))

    # codex 実行前のキャッシュ正規化（D-0204・失敗しても止めない）
    ensure_models_cache_consistent()

    child_env = _codex_child_env()
    if child_env is not None:
        eprint("codex exec の子プロセス PATH 先頭に codex-resources を追加します（L043 対策）。")
    else:
        eprint("codex-resources を解決できず。既定の環境で codex exec を実行します。")

    config_model = _config_model()
    primary_model = model_override or config_model
    eprint("使用モデル（1回目）: %s（%s）"
           % (primary_model or "不明", "--model 指定" if model_override else "config.toml の値"))
    return started_at, log_path, child_env, config_model


def _exec_with_model_fallback(build_cmd, model_override, config_model, child_env,
                              log_path, timeout, check, input_text=None, prompt_len=0):
    """codex exec を実行し、モデル非対応のときだけ予備モデルで1回再試行する（D-0243・用途共通）。

    build_cmd(model) は -m を含むコマンド配列を返す（model が None なら -m を付けない）。
    check(stdout) は (成功したか, 付随情報) を返す。成功しなかった場合に限り再試行を判定する。
    戻り値は dict（stdout / stderr / returncode / timed_out / log_path / info / model / retried）。
    起動自体の失敗（OSError）はそのまま送出する。
    """
    attempt_model = model_override  # None なら -m を付けず config の値に従う（従来どおり）
    retried = False
    while True:
        cmd = build_cmd(attempt_model)
        eprint("codex exec を開始します（-s read-only / --json / timeout=%d秒）: prompt %d 文字"
               % (timeout, prompt_len))
        stdout, stderr_text, returncode, timed_out = _run_codex_exec(
            cmd, child_env, timeout, input_text)

        # --json の出力を全行ファイルへ保存する（再試行時は1回目のログを上書きしないよう別ファイルにする）
        if retried:
            log_path = log_path.with_name(log_path.stem + "-retry" + log_path.suffix)
        log_path.write_text(stdout, encoding="utf-8")
        if timed_out:
            eprint("codex exec を %d秒で打ち切り、起動した PID ツリーを終了しました"
                   "（rc=%s・成功判定には使わない）。ログ: %s" % (timeout, returncode, log_path))
        else:
            eprint("codex exec 終了（rc=%s・成功判定には使わない）。ログ: %s" % (returncode, log_path))

        ok, info = check(stdout)

        # 成果物が無く、出力がモデル非対応の文言に一致し、まだ再試行しておらず、
        # 予備モデルが1回目と別のときだけ、予備モデルを明示して1回だけ再試行する。
        effective = attempt_model or config_model
        if (not ok and not retried and effective != FALLBACK_MODEL
                and _is_model_unsupported(stdout, stderr_text)):
            print("[codex-gateway]【注意】モデル非対応のため予備モデルで再試行しました"
                  "（config のモデル=%s／予備モデル=%s／Codex CLI=%s）。"
                  "config.toml の model 指定の見直しまたは Codex CLI の更新を検討してください。"
                  % (effective or "不明", FALLBACK_MODEL, _codex_cli_version() or "不明"))
            sys.stdout.flush()
            eprint("使用モデル（2回目・予備）: %s" % FALLBACK_MODEL)
            attempt_model = FALLBACK_MODEL
            retried = True
            continue
        return {
            "stdout": stdout, "stderr": stderr_text, "returncode": returncode,
            "timed_out": timed_out, "log_path": log_path, "info": info,
            "model": effective, "retried": retried,
        }


def run_exec(purpose, prompt_file, out_name, model_override=None):
    method = "exec"

    prompt, err_code = _read_prompt(purpose, method, prompt_file)
    if prompt is None:
        return err_code

    if not DOWNLOADS_DIR.is_dir():
        return fail(EXIT_PRECONDITION, purpose, method,
                    "~/Downloads が存在しません: %s" % DOWNLOADS_DIR)

    # (1) 実行開始時刻の記録・キャッシュ正規化・子プロセス環境の準備
    started_at, log_path, child_env, config_model = _prepare_exec(purpose, model_override)

    # (2) codex exec を非対話実行する（モデル非対応のときだけ予備モデルで1回再試行する・D-0243）
    # --skip-git-repo-check: このプロジェクトのルート直下は非Git管理（D-0043）のため、
    # これを付けないと codex exec が "Not inside a trusted directory" で即座に失敗する。
    def build_cmd(model):
        cmd = ["codex", "exec", "--json", "-s", "read-only", "--skip-git-repo-check"]
        if model:
            cmd += ["-m", model]
        cmd.append(prompt)
        return cmd

    def check(stdout):
        # (3) thread.started 行からスレッドIDを取り出し、(4) 成果物を検出する
        thread_id = extract_thread_id(stdout.splitlines())
        eprint("thread.started のID: %s" % (thread_id or "取得できず"))
        if GENERATED_IMAGES_DIR.is_dir():
            source, how = find_artifact(thread_id, started_at)
        else:
            source, how = None, "検出できず"
        return source is not None, (thread_id, source, how)

    try:
        result = _exec_with_model_fallback(build_cmd, model_override, config_model, child_env,
                                           log_path, EXEC_TIMEOUT_SEC, check,
                                           prompt_len=len(prompt))
    except OSError as exc:
        return fail(EXIT_LAUNCH_FAILED, purpose, method,
                    "codex exec の起動に失敗しました: %s" % exc)
    stderr_text = result["stderr"]
    returncode = result["returncode"]
    timed_out = result["timed_out"]
    log_path = result["log_path"]
    thread_id, source, how = result["info"]

    if not GENERATED_IMAGES_DIR.is_dir():
        return fail(EXIT_PRECONDITION, purpose, method,
                    "generated_images に到達できません: %s ／ codexログ: %s ／ stderr: %s"
                    % (GENERATED_IMAGES_DIR, log_path, stderr_text.strip()[:400]))

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


def _resolve_audit_output(output_file):
    """--output-file を解決し、growth/outputs/ 配下なら Path、それ以外なら None を返す。"""
    try:
        target = Path(output_file).resolve()
        base = AUDIT_OUTPUTS_DIR.resolve()
    except OSError:
        return None
    if target == base or base not in target.parents:
        return None
    return target


def _last_agent_message(stdout):
    """--json の出力から最後の agent_message の本文を取り出す。無ければ None。"""
    last = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        item = obj.get("item") if isinstance(obj, dict) else None
        if (isinstance(item, dict) and obj.get("type") == "item.completed"
                and item.get("type") == "agent_message"
                and isinstance(item.get("text"), str) and item["text"].strip()):
            last = item["text"]
    return last


def _fresh_nonempty(path, started_at):
    """path が実行開始後に書かれ、空でないか。"""
    try:
        st = path.stat()
    except OSError:
        return False
    return st.st_size > 0 and st.st_mtime >= started_at - 1


def run_growth_audit(purpose, prompt_file, output_file, model_override=None):
    """全コンテンツの週次監査（D-0251）。Codex は -s read-only のまま、最終メッセージを保存する。"""
    method = "exec"

    target = _resolve_audit_output(output_file)
    if target is None:
        return fail(EXIT_NOT_IMPLEMENTED, purpose, method,
                    "--output-file は %s 配下だけを許可しています: %s"
                    % (AUDIT_OUTPUTS_DIR, output_file))

    prompt, err_code = _read_prompt(purpose, method, prompt_file)
    if prompt is None:
        return err_code

    target.parent.mkdir(parents=True, exist_ok=True)
    started_at, log_path, child_env, config_model = _prepare_exec(purpose, model_override)

    # プロンプトは標準入力で渡す（"-"）。-C でプロジェクトルートを作業ルートにし、
    # -s read-only のまま -o で最終メッセージを書かせる（-o は Codex CLI 本体が書く）。
    # --ignore-user-config: ~/.codex/config.toml を読み込ませない（D-0253）。
    #   実測で、growth-audit を実行するだけで ~/.codex/config.toml のハッシュが
    #   変わることを確認した（他プロジェクトの trust_level 追記等、Codexアプリ全体で
    #   共有されるファイルのため）。このファイルには browser/computer-use/chrome 等の
    #   プラグインと mcp_servers.node_repl の登録も入っており、読み込ませないことで
    #   ハッシュ不変とアプリ連携遮断を同時に満たす。認証は CODEX_HOME 側で別管理のため
    #   影響しない。モデルは config.toml に頼れなくなるため、このプロセス自身が読んだ
    #   config_model を明示の -m で渡す（--model 未指定時の既定動作を変えないため、
    #   model_override が無ければ config_model を使う）。
    def build_cmd(model):
        effective_model = model or config_model
        cmd = ["codex", "exec", "--json", "-s", "read-only", "--skip-git-repo-check",
               "--ignore-user-config",
               "-C", str(PROJECT_ROOT), "-o", str(target)]
        cmd += GROWTH_AUDIT_HARDENING_ARGS
        if effective_model:
            cmd += ["-m", effective_model]
        cmd.append("-")
        return cmd

    def check(stdout):
        if _fresh_nonempty(target, started_at):
            return True, "codex -o"
        return _last_agent_message(stdout) is not None, "gateway（--json の最終 agent_message）"

    try:
        result = _exec_with_model_fallback(build_cmd, model_override, config_model, child_env,
                                           log_path, AUDIT_TIMEOUT_SEC, check,
                                           input_text=prompt, prompt_len=len(prompt))
    except OSError as exc:
        return fail(EXIT_LAUNCH_FAILED, purpose, method,
                    "codex exec の起動に失敗しました: %s" % exc)

    elapsed = int(time.time() - started_at)
    log_path = result["log_path"]
    written_by = result["info"]
    if not _fresh_nonempty(target, started_at):
        message = _last_agent_message(result["stdout"])
        if message is not None:
            target.write_text(message, encoding="utf-8")
            written_by = "gateway（--json の最終 agent_message）"
            eprint("-o の出力が無かったため、--json の最終メッセージを書き出しました: %s" % target)

    to_note = "（timeout %d秒で打ち切り後）" % AUDIT_TIMEOUT_SEC if result["timed_out"] else ""
    base_message = ("codexログ: %s ／ 所要 %d秒%s ／ 使用モデル: %s%s"
                    % (log_path, elapsed, to_note, result["model"] or "不明",
                       "（予備モデルで再試行）" if result["retried"] else ""))
    if not _fresh_nonempty(target, started_at):
        return fail(EXIT_ARTIFACT_MISSING, purpose, method,
                    "--output-file が作られないか空です: %s ／ %s ／ codex rc=%s ／ stderr: %s"
                    % (target, base_message, result["returncode"], result["stderr"].strip()[:400]))

    emit("ok", purpose, method, str(target), None,
         "%s ／ 書き出し: %s" % (base_message, written_by),
         extra={"elapsed_sec": elapsed, "model": result["model"], "written_by": written_by,
                "timed_out": result["timed_out"]})
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
    parser.add_argument("--out-name", default=None,
                        help="image-gen: ~/Downloads に置く最終ファイル名（image-gen では必須）")
    parser.add_argument("--output-file", default=None,
                        help="growth-audit: 監査結果の保存先（growth/outputs/ 配下のみ・必須）")
    parser.add_argument("--model", default=None,
                        help="1回目に使うモデルを上書きする（検証用・既定は config.toml の値・D-0243）")
    args = parser.parse_args()
    # image-gen の --out-name 必須は従来どおり argparse のエラー（終了コード2）で止める
    if args.purpose == "image-gen" and not args.out_name:
        parser.error("the following arguments are required: --out-name")

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

    if purpose == "growth-audit":
        if not args.output_file:
            return fail(EXIT_PRECONDITION, purpose, method, "--output-file が指定されていません。")
        return run_growth_audit(purpose, args.prompt_file, args.output_file, args.model)
    return run_exec(purpose, args.prompt_file, args.out_name, args.model)


if __name__ == "__main__":
    sys.exit(main())
