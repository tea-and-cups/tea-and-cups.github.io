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
  growth-audit 全コンテンツの監査（週次=D-0251／評価範囲の週次・月次分離=2026-09-28／
               区切り実行への分割=D-0255・2026-09-28）。
               Codex は読み取り専用で動き、最終メッセージを --output-file へ保存する。
               引数: --prompt-file <まとめ用プロンプトのパス> --output-file <growth/outputs/ 配下のパス>
                     --mode weekly --since YYYY-MM-DD --until YYYY-MM-DD
                     または --mode monthly [--month YYYY-MM]
                     [--dry-run]（Codexを起動せず、区切りの実行計画だけを表示して終了する）
               実行: <codexの実体パス> exec -C <プロジェクトルート> -s read-only --json -o <出力先>
               （GROWTH_AUDIT_HARDENING_ARGS で外部遮断を上乗せし、windows.sandbox="elevated"・
               model_reasoning_effort・tool_output_token_limit=30000 を追加で渡す・2026-09-28）
               "codex"（PATH名）ではなく os.path.realpath(shutil.which("codex")) の実体パスで
               起動する（windows.sandbox="elevated" は実体パスでないと失敗するため・診断済み）。
               1回のCodex呼び出しで全対象を読ませるのをやめ、対象を「区切り」（weekly=
               生成ルール等のR-1..R-n＋記事単位のO-1..O-n／monthly=恒久アセットのS-1..S-n＋
               代表サンプルのP-1..P-n）に分け、区切りごとに1回ずつ Codex を呼んで
               growth/outputs/<label>/parts/<区切り名>.md（所見のみ）へ保存し、最後に
               全区切りの出力・監査スキル・ledger・入力数値・docs/tasks.md・docs/decisions.md
               を読む「まとめ」を1回だけ実行して --output-file へ保存する（D-0255）。
               区切りの本文はgateway が対象ファイルから機械的に組み立て、部分監査用の
               プロンプト（固定パス growth/prompts/weekly-audit-part.md・
               monthly-audit-part.md）の {{TARGETS}} へ差し込む。--prompt-file に渡す
               まとめ用プロンプトの {{TARGETS}} には、区切り出力ファイルの一覧を差し込む。
               既に有効な部分出力（## 所見・## 部分監査範囲の両節が揃っている）がある
               区切りは実行せず飛ばす（同じコマンドでの再開に対応）。
               1つの区切りの上限は本文合計 PARTITION_CHAR_CAP 字または画像
               PARTITION_IMAGE_CAP 枚（定数）。growth-audit の reasoning effort は
               config.toml を読まず、定数 GROWTH_AUDIT_EFFORT に固定する（D-0255）。
               プロンプトは標準入力で渡す（Windows のコマンドライン長上限 約3.2万文字を避けるため）。
               -o のファイルが書かれなかった場合は、--json の出力から最終の agent_message を
               gateway が取り出して出力先へ書く（Codex に書き込み権限は与えない）。
               成功時のJSONには truncated_outputs（rolloutの"Warning: truncated output"件数）・
               view_image_calls（同ロールアウトの画像閲覧呼び出し件数）・区切りごと/全体の
               トークン内訳（token_usage）を含める（いずれも全区切り＋まとめの合計・D-0255）。

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
  growth-audit の成功判定は、区切り・まとめの実行1回ごとに次の3つがすべて満たされる
  ことで行う（D-0255・2026-09-28）: (1) --json ログに turn.failed が無い (2) --json ログに
  type が error の行が無い (3) 出力ファイルが実行開始後に書かれ・空でなく・必須の節が
  揃っている（区切り=## 所見・## 部分監査範囲／まとめ=## 要約・## 改善指示・
  ## 前回採用した指示の遵守確認・## 評価できなかったもの・## 監査範囲）。
  いずれか1つでも欠けた区切り・まとめがあれば、その時点で全体を失敗とする
  （出力ファイルは削除しない・終了コードは成果物なしと同じ EXIT_ARTIFACT_MISSING）。

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
from datetime import datetime, timedelta
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
#   6) -c windows.sandbox="elevated" と -c model_reasoning_effort=<値> を追加で検証した
#      結果（2026-09-28・growth/outputs/diag-2026-09-27/）、"codex"（PATH解決名）で
#      起動すると windows.sandbox="elevated" 指定時に毎回
#      "windows sandbox: CreateProcessWithLogonW failed: 2" で失敗することを確認した
#      （cand-meta.json・no_iuc-meta.json）。原因はサンドボックスセットアップヘルパーが
#      ジャンクション経由のパス（PATHが指す codex.exe）からは見つからないためと推定される
#      （L043 の codex-resources PATH 追加とは別問題）。os.path.realpath(shutil.which(
#      "codex")) で解決した実体のパスから起動すると同じ引数で成功する（cand_real-meta.json・
#      rc=0・config.tomlハッシュ不変）。このためgrowth-auditの起動は実体のパスに限定する
#      （image-gen の run_exec() は "codex" のまま・未変更）。
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

# growth-audit の追加の締め付け（2026-09-28・完了条件1〜6）。出力の切り詰め上限の緩和。
GROWTH_AUDIT_TOOL_OUTPUT_TOKEN_LIMIT = 30000
CODEX_SESSIONS_DIR = HOME / ".codex" / "sessions"

# growth-audit の reasoning effort（D-0255・2026-09-28）。config.toml は読まず固定する
# （1回あたりの消費を抑えるため、区切り実行のどの回も同じ強さにする）。
GROWTH_AUDIT_EFFORT = "medium"

# 区切り実行（D-0255・2026-09-28）。1区切りの上限（本文合計の字数／画像枚数、どちらか
# 先に超えた時点で次の区切りへ回す）。
PARTITION_CHAR_CAP = 40000
PARTITION_IMAGE_CAP = 8

# --mode weekly|monthly（2026-09-28・区切りの組み立て）で参照するパス。
CONTENT_POSTS_DIR = PROJECT_ROOT / "site" / "src" / "content" / "posts"
OUTPUT_PINS_DIR = PROJECT_ROOT / "output" / "pins"
OUTPUT_PIN_IMAGES_DIR = PROJECT_ROOT / "output" / "Pin-images"
GROWTH_LEDGER_PATH = PROJECT_ROOT / "growth" / "ledger" / "adopted-directives.tsv"
GROWTH_INPUTS_DIR = PROJECT_ROOT / "growth" / "inputs"
SITE_DIR = PROJECT_ROOT / "site"
SITE_DIST_DIR = SITE_DIR / "dist"

# 部分監査用プロンプトの固定パス（--prompt-file には渡さず、gateway が直接読む・D-0255）。
PART_PROMPT_PATHS = {
    "weekly": PROJECT_ROOT / "growth" / "prompts" / "weekly-audit-part.md",
    "monthly": PROJECT_ROOT / "growth" / "prompts" / "monthly-audit-part.md",
}
REQUIRED_PART_SECTIONS = ("## 所見", "## 部分監査範囲")
REQUIRED_SUMMARY_SECTIONS = ("## 要約", "## 改善指示", "## 前回採用した指示の遵守確認",
                              "## 評価できなかったもの", "## 監査範囲")

# 生成ルール（全文・週次のTARGETSに載せる）。ルート直下は更新時刻、site/ 配下はgit logで
# 期間内変更を判定する（ルート非Git・D-0043）。
GENERATION_RULE_FILES_ROOT_FIXED = [
    PROJECT_ROOT / "docs" / "strategy.md",
    PROJECT_ROOT / "CLAUDE.md",
    PROJECT_ROOT / ".claude" / "agents" / "quality-reviewer.md",
]
GENERATION_RULE_FILES_SITE = [
    "scripts/post-pins-to-buffer.py",
    "scripts/make-image-prompt.py",
]

# 恒久アセット（site/src のうち記事以外）の対象サブディレクトリ。
PERMANENT_ASSET_SUBDIRS = ["components", "layouts", "pages", "data", "styles"]

PIN_FILENAME_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-pin-(\d+)-")
# ピン投稿文ファイル名から記事slugを取り出す（例: 2026-09-26-pin-306-shoga-koucha-
# tsukurikata-03.md → shoga-koucha-tsukurikata）。週次の区切りを記事単位でまとめるため
# （D-0255・2026-09-28）。
PIN_TEXT_SLUG_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-pin-\d+-(.+)-\d{2}\.md$")
# Pin-images の命名は2系統ある（実測・2026-09-28）: 旧 "pin-NN-slug.png"、
# 新 "ピンNN <タイトル>（誘導先 …）.png"。どちらもピン番号で output/pins/ と対応させる。
PIN_IMAGE_NUMBER_RE = re.compile(r"^(?:pin-|ピン)(\d+)")

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


def _codex_real_exe():
    """PATH解決した codex の実体パスを返す（growth-audit専用・-s 6 の対策）。

    windows.sandbox="elevated" を "codex"（PATH名）のまま渡すとサンドボックスヘルパーが
    ジャンクション経由のパスから見つからず毎回失敗するため（診断済み）、実体を明示する。
    解決できなければ None を返す（呼び出し側が前提不備として扱う）。
    """
    exe = shutil.which("codex")
    if not exe:
        return None
    try:
        return str(Path(os.path.realpath(exe)))
    except OSError:
        return None


def _json_log_has_failure(stdout):
    """--json の出力に turn.failed または type=="error" の行があるか（D-0255・2026-09-28）。

    あれば (True, メッセージ) を返す。メッセージは turn.failed の error.message、
    無ければ error 行の message（無ければ行全体の文字列）。無ければ (False, None)。
    """
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        obj_type = obj.get("type")
        if obj_type == "turn.failed":
            error = obj.get("error")
            message = error.get("message") if isinstance(error, dict) else None
            return True, message or "turn.failed"
        if obj_type == "error":
            message = obj.get("message") or obj.get("error")
            return True, str(message) if message else line
    return False, None


def _rollout_last_token_usage(thread_id):
    """thread_id の rollout（~/.codex/sessions 配下）から、最後の token_count イベントの
    total_token_usage を (input/cached/output/reasoning) の辞書で返す（D-0255・2026-09-28）。
    見つからなければ None。
    """
    if not thread_id:
        return None
    matches = list(CODEX_SESSIONS_DIR.rglob("*-%s.jsonl" % thread_id))
    if not matches:
        return None
    rollout_path = matches[0]
    last = None
    try:
        with open(rollout_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                payload = obj.get("payload") if isinstance(obj, dict) else None
                if not isinstance(payload, dict) or payload.get("type") != "token_count":
                    continue
                info = payload.get("info")
                usage = info.get("total_token_usage") if isinstance(info, dict) else None
                if isinstance(usage, dict):
                    last = usage
    except OSError:
        return None
    if last is None:
        return None
    return {
        "tokens_input": last.get("input_tokens", 0),
        "tokens_cached": last.get("cached_input_tokens", 0),
        "tokens_output": last.get("output_tokens", 0),
        "tokens_reasoning": last.get("reasoning_output_tokens", 0),
    }


_VIEW_IMAGE_CALL_RE = re.compile(r"view_image\s*\(")


def _count_rollout_signals(thread_id):
    """thread_id の rollout（~/.codex/sessions 配下）を探し、
    (truncated_outputs, view_image_calls) を数える。見つからなければ (0, 0) を返す。

    truncated_outputs: custom_tool_call_output の出力テキストに含まれる
      "Warning: truncated output" の件数（実測フォーマット確認済み・2026-09-28）。
    view_image_calls: view_image という名前の直接のツール呼び出し、または
      exec 等のツール呼び出し内で view_image(...) を実行しているものの件数
      （実測で view_image は exec の JS コード内から呼ばれる形を確認・2026-09-28）。
    """
    if not thread_id:
        return 0, 0
    matches = list(CODEX_SESSIONS_DIR.rglob("*-%s.jsonl" % thread_id))
    if not matches:
        return 0, 0
    rollout_path = matches[0]
    truncated = 0
    view_image_calls = 0
    try:
        with open(rollout_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                payload = obj.get("payload") if isinstance(obj, dict) else None
                if not isinstance(payload, dict):
                    continue
                ptype = payload.get("type")
                if ptype == "custom_tool_call_output":
                    for item in payload.get("output") or []:
                        text = item.get("text") if isinstance(item, dict) else None
                        if isinstance(text, str):
                            truncated += text.count("Warning: truncated output")
                elif ptype in ("custom_tool_call", "function_call", "local_shell_call"):
                    name = payload.get("name") or ""
                    if name == "view_image":
                        view_image_calls += 1
                    else:
                        call_text = payload.get("input")
                        if not isinstance(call_text, str):
                            call_text = payload.get("arguments") or ""
                        if isinstance(call_text, str) and _VIEW_IMAGE_CALL_RE.search(call_text):
                            view_image_calls += 1
    except OSError:
        return 0, 0
    return truncated, view_image_calls


def _read_frontmatter(path):
    """記事frontmatter（--- で挟まれた単純な key: value 行）を辞書で返す。パース不能なら {}。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    result = {}
    for line in text[3:end].splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if key and key not in result:
            result[key] = value
    return result


def _git_log_changed_paths(pathspecs, since_date, until_date):
    """site/ を git log --name-only で調べ、[since_date, until_date]（両端含む）に変更が
    あったファイルの相対パス（site/ 起点）の集合を返す。取得できなければ空集合。
    """
    if not pathspecs:
        return set()
    try:
        proc = subprocess.run(
            ["git", "-C", str(SITE_DIR), "log",
             "--since=%s 00:00:00" % since_date, "--until=%s 23:59:59" % until_date,
             "--name-only", "--pretty=format:", "--"] + list(pathspecs),
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return set()
    return set(line.strip() for line in proc.stdout.splitlines() if line.strip())


def _posts_in_period(since_date, until_date):
    """date か updated が [since_date, until_date] に入る記事を (path, 理由) のリストで返す。"""
    matched = []
    if not CONTENT_POSTS_DIR.is_dir():
        return matched
    for p in sorted(CONTENT_POSTS_DIR.glob("*.md")):
        fm = _read_frontmatter(p)
        reasons = []
        date_str = fm.get("date")
        updated_str = fm.get("updated")
        if date_str and since_date <= date_str <= until_date:
            reasons.append("date=%s" % date_str)
        if updated_str and updated_str != date_str and since_date <= updated_str <= until_date:
            reasons.append("updated=%s" % updated_str)
        if reasons:
            matched.append((p, ", ".join(reasons)))
    return matched


def _pins_by_slug_in_period(since_date, until_date):
    """ファイル名の日付が [since_date, until_date] に入るピンを、記事slugごとに
    (投稿文リスト, 画像リスト) でまとめて返す（週次の区切りを記事単位にするため・D-0255）。
    """
    by_slug = {}
    if OUTPUT_PINS_DIR.is_dir():
        for p in sorted(OUTPUT_PINS_DIR.glob("*.md")):
            m = PIN_FILENAME_DATE_RE.match(p.name)
            if not m:
                continue
            date_str, pin_num = m.group(1), m.group(2)
            if not (since_date <= date_str <= until_date):
                continue
            sm = PIN_TEXT_SLUG_RE.match(p.name)
            if not sm:
                continue
            texts, pin_numbers = by_slug.setdefault(sm.group(1), ([], set()))
            texts.append(p)
            pin_numbers.add(pin_num)
    result = {}
    for slug, (texts, pin_numbers) in by_slug.items():
        images = []
        if OUTPUT_PIN_IMAGES_DIR.is_dir():
            for img in sorted(OUTPUT_PIN_IMAGES_DIR.glob("*.png")):
                m = PIN_IMAGE_NUMBER_RE.match(img.name)
                if m and m.group(1) in pin_numbers:
                    images.append(img)
        result[slug] = (sorted(texts), images)
    return result


def _generation_rule_targets(since_date, until_date):
    """生成ルール全文の対象リストを [(表示パス, 変更ありbool)] で返す。

    ルート直下（rules/*.md・docs/strategy.md・CLAUDE.md・quality-reviewer.md）は
    更新時刻、site/ 配下（post-pins-to-buffer.py・make-image-prompt.py）は git log で判定する。
    """
    out = []
    try:
        since_dt = datetime.strptime(since_date, "%Y-%m-%d")
        until_dt = datetime.strptime(until_date, "%Y-%m-%d") + timedelta(
            hours=23, minutes=59, seconds=59)
    except ValueError:
        since_dt = until_dt = None

    root_files = sorted((PROJECT_ROOT / "rules").glob("*.md")) if (PROJECT_ROOT / "rules").is_dir() else []
    root_files += GENERATION_RULE_FILES_ROOT_FIXED
    for p in root_files:
        changed = False
        if since_dt is not None and p.is_file():
            try:
                mtime = datetime.fromtimestamp(p.stat().st_mtime)
                changed = since_dt <= mtime <= until_dt
            except OSError:
                changed = False
        out.append((str(p.relative_to(PROJECT_ROOT)).replace("\\", "/"), changed))

    site_changed = _git_log_changed_paths(GENERATION_RULE_FILES_SITE, since_date, until_date)
    for rel in GENERATION_RULE_FILES_SITE:
        display = "site/" + rel
        out.append((display, rel in site_changed))
    return out


def _permanent_asset_changes(since_date, until_date):
    """site/src のうち記事以外（PERMANENT_ASSET_SUBDIRS）の期間内変更ファイルと、
    対応する site/dist のページ（テンプレート由来のため代表ページで近似）を返す。
    戻り値: [(src相対パス, [dist相対パスの候補, ...])]
    """
    pathspecs = ["src/%s" % d for d in PERMANENT_ASSET_SUBDIRS]
    changed = sorted(_git_log_changed_paths(pathspecs, since_date, until_date))
    representative_dist = [p for p in [
        "dist/index.html", "dist/about/index.html", "dist/category/index.html",
    ] if (SITE_DIR / p).is_file()]

    result = []
    for rel in changed:
        dist_candidates = []
        m = re.match(r"^src/pages/category/index\.astro$", rel)
        if m:
            dist_candidates = ["dist/category/index.html"]
        elif rel == "src/pages/index.astro" or re.match(r"^src/pages/\[\.\.\.page\]\.astro$", rel):
            dist_candidates = ["dist/index.html"]
        elif rel.startswith("src/pages/"):
            # ページ単位で対応が付かない動的ルート（[slug] 等）は代表ページで近似する
            dist_candidates = representative_dist
        else:
            # components・layouts・data・styles はテンプレート経由で全ページに波及するため
            # 個別対応ではなく代表ページ（トップ・about・カテゴリ一覧）で近似する
            dist_candidates = representative_dist
        result.append((rel, dist_candidates))
    return result


def _ledger_adopted_with_impl_date():
    """growth/ledger/adopted-directives.tsv のうち「採用」かつ実装日欄が埋まっている行を返す。"""
    rows = []
    if not GROWTH_LEDGER_PATH.is_file():
        return rows
    with open(GROWTH_LEDGER_PATH, "r", encoding="utf-8") as fh:
        header = None
        for line in fh:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            cells = line.split("\t")
            if header is None:
                header = cells
                continue
            row = dict(zip(header, cells))
            if row.get("採否") == "採用" and (row.get("実装日") or "").strip():
                rows.append(row)
    return rows


def _input_dir_for_output(target):
    """--output-file（growth/outputs/<label>/audit.md）と同じ <label> の
    growth/inputs/<label>/ を返す（既存の命名慣行に合わせる・新規の引数を増やさない）。
    """
    label = target.parent.name
    return GROWTH_INPUTS_DIR / label


def _format_generation_rule_lines(rule_targets):
    lines = []
    for display, changed in rule_targets:
        lines.append("- %s%s" % (display, "【変更あり】" if changed else ""))
    return lines


def _text_len(path):
    """テキストファイルの文字数。読めなければ0（区切りの上限判定に使う・D-0255）。"""
    try:
        return len(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return 0


def _rule_file_path(display):
    """_generation_rule_targets の表示パス（"rules/x.md" または "site/y.py"）から実パスへ。"""
    if display.startswith("site/"):
        return SITE_DIR / display[len("site/"):]
    return PROJECT_ROOT / display


def _weekly_r_items(since_date, until_date):
    """週次の区切りR（生成ルール全文・恒久アセットの変更・遵守確認の対象）の材料を、
    1ファイル（または遵守確認の対象一式）＝1アイテムで返す（D-0255）。
    """
    items = []
    rule_targets = _generation_rule_targets(since_date, until_date)
    for (display, _changed), line in zip(rule_targets, _format_generation_rule_lines(rule_targets)):
        items.append({"chars": _text_len(_rule_file_path(display)), "images": 0, "lines": [line]})

    asset_changes = _permanent_asset_changes(since_date, until_date)
    for rel, dist_candidates in asset_changes:
        lines = ["- site/%s" % rel]
        for d in dist_candidates:
            lines.append("  - 対応: site/%s" % d)
        items.append({"chars": _text_len(SITE_DIR / rel), "images": 0, "lines": lines})

    ledger_rows = _ledger_adopted_with_impl_date()
    ledger_lines = ["### 遵守確認の対象（ledger で「採用」かつ実装日のある行・%d件）" % len(ledger_rows)]
    for row in ledger_rows:
        ledger_lines.append("- %s（%s・実装D番号=%s・実装日=%s）" % (
            row.get("ID", ""), row.get("指示", ""), row.get("実装D番号", ""), row.get("実装日", "")))
    if not ledger_rows:
        ledger_lines.append("- 該当なし")
    items.append({"chars": sum(len(l) for l in ledger_lines), "images": 0, "lines": ledger_lines})
    return items


def _weekly_o_items(since_date, until_date):
    """週次の区切りO（生成物）の材料を、記事1本＝1アイテム（その記事のピン・画像込み）で
    返す（記事単位で同じ区切りに入れるため分割しない・D-0255）。
    """
    posts = _posts_in_period(since_date, until_date)
    pins_by_slug = _pins_by_slug_in_period(since_date, until_date)
    items = []
    for p, reason in posts:
        chars = _text_len(p)
        images = 0
        lines = ["- site/src/content/posts/%s（%s）" % (p.name, reason)]
        texts, imgs = pins_by_slug.pop(p.stem, ([], []))
        for t in texts:
            chars += _text_len(t)
            lines.append("  - output/pins/%s" % t.name)
        for im in imgs:
            images += 1
            lines.append("  - output/Pin-images/%s" % im.name)
        items.append({"chars": chars, "images": images, "lines": lines})

    # 対象期間の記事一覧（frontmatterのdate/updated基準）に見つからない残りのピンも、
    # ファイル名の日付が期間内である以上は取りこぼさず1アイテムとして計上する。
    for slug in sorted(pins_by_slug):
        texts, imgs = pins_by_slug[slug]
        chars = 0
        images = 0
        lines = ["- （対象期間の記事一覧に無い）slug=%s" % slug]
        for t in texts:
            chars += _text_len(t)
            lines.append("  - output/pins/%s" % t.name)
        for im in imgs:
            images += 1
            lines.append("  - output/Pin-images/%s" % im.name)
        items.append({"chars": chars, "images": images, "lines": lines})
    return items


def _pack_items(items, prefix):
    """items（各 {chars, images, lines}）を PARTITION_CHAR_CAP／PARTITION_IMAGE_CAP の
    上限で貪欲に詰め、区切り名 <prefix>-1.. を振って返す（アイテムは分割しない・D-0255）。
    """
    partitions = []
    cur_chars = 0
    cur_images = 0
    cur_lines = []
    cur_count = 0
    for item in items:
        if cur_count and (cur_chars + item["chars"] > PARTITION_CHAR_CAP
                           or cur_images + item["images"] > PARTITION_IMAGE_CAP):
            partitions.append({"chars": cur_chars, "images": cur_images,
                               "lines": cur_lines, "count": cur_count})
            cur_chars, cur_images, cur_lines, cur_count = 0, 0, [], 0
        cur_chars += item["chars"]
        cur_images += item["images"]
        cur_lines.extend(item["lines"])
        cur_count += 1
    if cur_count:
        partitions.append({"chars": cur_chars, "images": cur_images,
                           "lines": cur_lines, "count": cur_count})
    for i, part in enumerate(partitions, start=1):
        part["name"] = "%s-%d" % (prefix, i)
    return partitions


def _previous_month(year_month):
    year, month = (int(x) for x in year_month.split("-"))
    if month == 1:
        return "%04d-12" % (year - 1)
    return "%04d-%02d" % (year, month - 1)


def _rel(path):
    try:
        return str(Path(path).resolve().relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def _posts_by_category():
    """公開中（status: published）の記事を category ごとにまとめる。

    戻り値: {category: [(slug, path, date), ...]}
    """
    result = {}
    if not CONTENT_POSTS_DIR.is_dir():
        return result
    for p in sorted(CONTENT_POSTS_DIR.glob("*.md")):
        fm = _read_frontmatter(p)
        if fm.get("status") != "published":
            continue
        category = fm.get("category") or "（未分類）"
        slug = fm.get("slug") or p.stem
        date_str = fm.get("date") or ""
        result.setdefault(category, []).append((slug, p, date_str))
    return result


def _load_ga4_page_traffic_series(input_dir):
    """<input_dir>/ga4-page-traffic.json（M-1で保存した契約JSON）を読む。無ければ None。"""
    path = input_dir / "ga4-page-traffic.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if payload.get("status") != "ok":
        return None
    return ((payload.get("data") or {}).get("series")) or []


def _slug_from_page_path(page_path):
    m = re.match(r"^/posts/([^/]+)/?$", page_path or "")
    return m.group(1) if m else None


def _select_monthly_samples(posts_by_category, ga4_series):
    """カテゴリごとに最大2本（PV最多＋最古、PV不明なら最古＋最新）を選ぶ。最大12本。"""
    pv_by_slug = {}
    for row in ga4_series or []:
        slug = _slug_from_page_path(row.get("page_path"))
        if slug:
            pv_by_slug[slug] = pv_by_slug.get(slug, 0) + (row.get("screenPageViews") or 0)

    samples = []
    for category in sorted(posts_by_category):
        posts = posts_by_category[category]
        if not posts:
            continue
        category_pv = [(slug, pv_by_slug[slug]) for slug, _, _ in posts if slug in pv_by_slug]
        chosen = []
        if category_pv:
            top_slug = max(category_pv, key=lambda x: x[1])[0]
            oldest_slug = min(posts, key=lambda t: t[2] or "9999-99-99")[0]
            chosen.append((top_slug, "PV最多"))
            if oldest_slug != top_slug:
                chosen.append((oldest_slug, "公開日最古"))
        else:
            oldest_slug = min(posts, key=lambda t: t[2] or "9999-99-99")[0]
            newest_slug = max(posts, key=lambda t: t[2] or "0000-00-00")[0]
            chosen.append((oldest_slug, "最古（PVデータなし）"))
            if newest_slug != oldest_slug:
                chosen.append((newest_slug, "最新（PVデータなし）"))
        samples.append((category, chosen))
    return samples


def _monthly_s_items():
    """月次の区切りS（恒久アセットの全体）の材料を、1ファイル＝1アイテムで返す（D-0255）。"""
    items = []
    if SITE_DIST_DIR.is_dir():
        for p in sorted(SITE_DIST_DIR.rglob("index.html")):
            rel = p.relative_to(SITE_DIST_DIR).as_posix()
            if rel.startswith("posts/"):
                continue
            items.append({"chars": _text_len(p), "images": 0, "lines": ["- site/dist/%s" % rel]})
    cats = SITE_DIR / "src" / "data" / "categories.ts"
    if cats.is_file():
        items.append({"chars": _text_len(cats), "images": 0, "lines": ["- site/src/data/categories.ts"]})
    editorial = SITE_DIR / "src" / "data" / "editorial.ts"
    if editorial.is_file():
        items.append({"chars": _text_len(editorial), "images": 0, "lines": ["- site/src/data/editorial.ts"]})
    layouts_dir = SITE_DIR / "src" / "layouts"
    if layouts_dir.is_dir():
        for p in sorted(layouts_dir.glob("*")):
            if p.is_file():
                items.append({"chars": _text_len(p), "images": 0,
                             "lines": ["- site/src/layouts/%s" % p.name]})
    components_dir = SITE_DIR / "src" / "components"
    if components_dir.is_dir():
        for p in sorted(components_dir.rglob("*")):
            if p.is_file():
                rel = p.relative_to(components_dir).as_posix()
                items.append({"chars": _text_len(p), "images": 0,
                             "lines": ["- site/src/components/%s" % rel]})
    return items


def _monthly_p_items(target):
    """月次の区切りP（代表サンプル）の材料を、記事1本＝1アイテムで返す（D-0255）。"""
    input_dir = _input_dir_for_output(target)
    posts_by_category = _posts_by_category()
    ga4_series = _load_ga4_page_traffic_series(input_dir)
    samples = _select_monthly_samples(posts_by_category, ga4_series)
    items = []
    for category, chosen in samples:
        for slug, reason in chosen:
            p = CONTENT_POSTS_DIR / ("%s.md" % slug)
            items.append({
                "chars": _text_len(p), "images": 0,
                "lines": ["- [%s] %s（%s）: site/src/content/posts/%s.md" % (category, slug, reason, slug)],
            })
    return items


def _build_partitions(mode, since, until, month, target):
    """mode に応じて区切りの計画（各 {name, chars, images, lines, count}）を返す（D-0255）。"""
    if mode == "weekly":
        return (_pack_items(_weekly_r_items(since, until), "R")
                + _pack_items(_weekly_o_items(since, until), "O"))
    if mode == "monthly":
        return (_pack_items(_monthly_s_items(), "S")
                + _pack_items(_monthly_p_items(target), "P"))
    return []


def _has_sections(path, headers):
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return all(h in text for h in headers)


def _valid_partial_output(path):
    """区切りの出力が有効か（必須の2節が揃っているか）。再開時にこれが真の区切りは飛ばす。"""
    return _has_sections(path, REQUIRED_PART_SECTIONS)


def _format_parts_reference(parts_dir, partitions):
    """まとめ用プロンプトの {{TARGETS}} へ差し込む、部分監査の出力一覧。"""
    lines = ["## 部分監査の出力一覧（すべて読む・%d件）" % len(partitions)]
    for part in partitions:
        lines.append("- %s" % _rel(parts_dir / (part["name"] + ".md")))
    return "\n".join(lines)


def _emit_dry_run(purpose, method, target, parts_dir, partitions):
    plan = []
    for part in partitions:
        part_path = parts_dir / (part["name"] + ".md")
        plan.append({
            "name": part["name"], "target_count": part["count"],
            "chars": part["chars"], "images": part["images"],
            "skip": _valid_partial_output(part_path),
        })
    skip_names = [p["name"] for p in plan if p["skip"]]
    emit("dry_run", purpose, method, str(target), None,
         "区切り計画 %d件（スキップ%d件）: %s"
         % (len(plan), len(skip_names), "、".join(p["name"] for p in plan) or "なし"),
         extra={"partitions": plan, "skip": skip_names})
    return EXIT_OK


def _build_audit_cmd(real_exe, output_path, reasoning_effort, config_model):
    """growth-audit の codex exec 起動引数を組み立てる（区切り・まとめ共通・D-0255）。

    -s read-only のまま -o で最終メッセージを書かせ、GROWTH_AUDIT_HARDENING_ARGS で
    外部遮断を上乗せし、windows.sandbox="elevated"・model_reasoning_effort・
    tool_output_token_limit を追加で渡す。実行ファイルは実体パス（real_exe）に限定する
    （"codex" のままだと windows.sandbox="elevated" が失敗するため・診断済み）。
    --ignore-user-config で ~/.codex/config.toml を読み込ませないため、モデルは
    config_model（または --model 指定）を明示の -m で渡す。
    """
    def build_cmd(model):
        effective_model = model or config_model
        cmd = [real_exe, "exec", "--json", "-s", "read-only", "--skip-git-repo-check",
               "--ignore-user-config", "-C", str(PROJECT_ROOT), "-o", str(output_path)]
        cmd += GROWTH_AUDIT_HARDENING_ARGS
        cmd += ["-c", 'windows.sandbox="elevated"']
        cmd += ["-c", 'model_reasoning_effort="%s"' % reasoning_effort]
        cmd += ["-c", "tool_output_token_limit=%d" % GROWTH_AUDIT_TOOL_OUTPUT_TOKEN_LIMIT]
        if effective_model:
            cmd += ["-m", effective_model]
        cmd.append("-")
        return cmd
    return build_cmd


def _make_check(output_path, started_at, required_sections, state):
    """区切り・まとめ共通の成功判定（D-0255）。turn.failed／type=="error" があれば失敗、
    無ければ出力ファイルの書き出し（-o優先・無ければ最終agent_messageで代替）と
    必須の節が揃っているかを見る。state["written_by"] に書き出し経路を残す。
    """
    def check(stdout):
        failed, err_msg = _json_log_has_failure(stdout)
        if failed:
            return False, {"reason": "turn_failed", "message": err_msg}
        if _fresh_nonempty(output_path, started_at):
            state["written_by"] = "codex -o"
        else:
            message = _last_agent_message(stdout)
            if message is not None:
                output_path.write_text(message, encoding="utf-8")
                state["written_by"] = "gateway（--json の最終 agent_message）"
            if not _fresh_nonempty(output_path, started_at):
                return False, {"reason": "no_output", "message": None}
        if not _has_sections(output_path, required_sections):
            return False, {"reason": "missing_sections", "message": None}
        return True, {"reason": "ok", "message": None}
    return check


def _run_one_audit_step(build_cmd, prompt_text, output_path, model_override, config_model,
                        child_env, required_sections, log_label):
    """区切り・まとめ共通の1回の codex exec 実行（D-0255）。起動自体の失敗（OSError）は
    呼び出し側へそのまま送出する。
    """
    started_at = time.time()
    stamp = datetime.fromtimestamp(started_at).strftime("%Y%m%d-%H%M%S")
    log_path = LOG_DIR / ("%s-growth-audit-%s.jsonl" % (stamp, log_label))
    state = {"written_by": None}
    check = _make_check(output_path, started_at, required_sections, state)
    result = _exec_with_model_fallback(build_cmd, model_override, config_model, child_env,
                                       log_path, AUDIT_TIMEOUT_SEC, check,
                                       input_text=prompt_text, prompt_len=len(prompt_text))
    thread_id = extract_thread_id(result["stdout"].splitlines())
    truncated, view_calls = _count_rollout_signals(thread_id)
    token_usage = _rollout_last_token_usage(thread_id)
    ok, info = result["info"]
    return {
        "ok": ok, "info": info, "elapsed": int(time.time() - started_at),
        "log_path": result["log_path"], "model": result["model"],
        "timed_out": result["timed_out"], "truncated_outputs": truncated,
        "view_image_calls": view_calls, "token_usage": token_usage,
        "stderr": result["stderr"], "returncode": result["returncode"],
        "written_by": state["written_by"],
    }


_STEP_FAILURE_REASONS = {
    "no_output": "--output-file が作られないか空です",
    "missing_sections": "必須の節が揃っていません",
}


def _step_failure_message(step):
    reason = step["info"].get("reason")
    if reason == "turn_failed":
        return step["info"].get("message") or "turn.failed"
    return _STEP_FAILURE_REASONS.get(reason, "不明な失敗")


def run_growth_audit(purpose, prompt_file, output_file, model_override=None,
                      mode=None, since=None, until=None, month=None, dry_run=False):
    """全コンテンツの監査（D-0251）。区切りごとの部分監査を順に実行し、最後にまとめを
    1回実行する（D-0255）。Codex は常に -s read-only のまま、各回の最終メッセージを
    保存する。
    """
    method = "exec"

    target = _resolve_audit_output(output_file)
    if target is None:
        return fail(EXIT_NOT_IMPLEMENTED, purpose, method,
                    "--output-file は %s 配下だけを許可しています: %s"
                    % (AUDIT_OUTPUTS_DIR, output_file))

    if mode not in ("weekly", "monthly"):
        return fail(EXIT_PRECONDITION, purpose, method,
                    "--mode は weekly か monthly が必須です: %s" % mode)
    if mode == "weekly" and (not since or not until):
        return fail(EXIT_PRECONDITION, purpose, method,
                    "--mode weekly には --since と --until（YYYY-MM-DD）が必要です。")
    effective_month = month
    if mode == "monthly" and not effective_month:
        effective_month = _previous_month(datetime.now().strftime("%Y-%m"))

    partitions = _build_partitions(mode, since, until, effective_month, target)
    parts_dir = target.parent / "parts"

    if dry_run:
        return _emit_dry_run(purpose, method, target, parts_dir, partitions)

    prompt, err_code = _read_prompt(purpose, method, prompt_file)
    if prompt is None:
        return err_code

    part_prompt_path = PART_PROMPT_PATHS[mode]
    try:
        part_prompt_template = part_prompt_path.read_text(encoding="utf-8")
    except OSError as exc:
        return fail(EXIT_PRECONDITION, purpose, method,
                    "部分監査プロンプトを読み込めません: %s（%s）" % (part_prompt_path, exc))

    real_exe = _codex_real_exe()
    if real_exe is None:
        return fail(EXIT_PRECONDITION, purpose, method,
                    "codex の実体パスを解決できませんでした（shutil.which/realpath失敗）。")

    target.parent.mkdir(parents=True, exist_ok=True)
    parts_dir.mkdir(parents=True, exist_ok=True)

    ensure_models_cache_consistent()
    child_env = _codex_child_env()
    if child_env is not None:
        eprint("codex exec の子プロセス PATH 先頭に codex-resources を追加します（L043 対策）。")
    config_model = _config_model()
    reasoning_effort = GROWTH_AUDIT_EFFORT

    overall_started = time.time()
    part_reports = []
    truncated_total = 0
    view_image_total = 0
    token_totals = {"tokens_input": 0, "tokens_cached": 0, "tokens_output": 0, "tokens_reasoning": 0}
    token_by_part = {}
    any_timed_out = False

    for part in partitions:
        part_path = parts_dir / (part["name"] + ".md")
        if _valid_partial_output(part_path):
            eprint("区切り %s は有効な出力が既にあるため飛ばします: %s" % (part["name"], part_path))
            part_reports.append({"name": part["name"], "status": "skipped"})
            continue

        part_prompt = (part_prompt_template
                       .replace("{{PART_NAME}}", part["name"])
                       .replace("{{TARGETS}}", "\n".join(part["lines"])))
        build_cmd = _build_audit_cmd(real_exe, part_path, reasoning_effort, config_model)
        try:
            step = _run_one_audit_step(build_cmd, part_prompt, part_path, model_override,
                                       config_model, child_env, REQUIRED_PART_SECTIONS,
                                       "part-%s" % part["name"])
        except OSError as exc:
            return fail(EXIT_LAUNCH_FAILED, purpose, method,
                        "区切り %s の codex exec 起動に失敗しました: %s" % (part["name"], exc))

        truncated_total += step["truncated_outputs"]
        view_image_total += step["view_image_calls"]
        if step["token_usage"]:
            token_by_part[part["name"]] = step["token_usage"]
            for k in token_totals:
                token_totals[k] += step["token_usage"].get(k, 0)
        any_timed_out = any_timed_out or step["timed_out"]

        if not step["ok"]:
            return fail(EXIT_ARTIFACT_MISSING, purpose, method,
                        "区切り %s が失敗しました: %s ／ codexログ: %s ／ 所要 %d秒 ／ stderr: %s"
                        % (part["name"], _step_failure_message(step), step["log_path"],
                           step["elapsed"], step["stderr"].strip()[:400]))
        part_reports.append({"name": part["name"], "status": "ok", "elapsed_sec": step["elapsed"]})

    # 最後のまとめ（1回）: 全区切りの出力一覧を {{TARGETS}} へ差し込む。
    summary_prompt = prompt.replace("{{TARGETS}}", _format_parts_reference(parts_dir, partitions))
    build_cmd = _build_audit_cmd(real_exe, target, reasoning_effort, config_model)
    try:
        summary_step = _run_one_audit_step(build_cmd, summary_prompt, target, model_override,
                                           config_model, child_env, REQUIRED_SUMMARY_SECTIONS,
                                           "summary")
    except OSError as exc:
        return fail(EXIT_LAUNCH_FAILED, purpose, method,
                    "まとめの codex exec 起動に失敗しました: %s" % exc)

    truncated_total += summary_step["truncated_outputs"]
    view_image_total += summary_step["view_image_calls"]
    if summary_step["token_usage"]:
        token_by_part["summary"] = summary_step["token_usage"]
        for k in token_totals:
            token_totals[k] += summary_step["token_usage"].get(k, 0)
    any_timed_out = any_timed_out or summary_step["timed_out"]
    elapsed_total = int(time.time() - overall_started)

    if not summary_step["ok"]:
        return fail(EXIT_ARTIFACT_MISSING, purpose, method,
                    "まとめが失敗しました: %s ／ codexログ: %s ／ 所要 %d秒（全体） ／ stderr: %s"
                    % (_step_failure_message(summary_step), summary_step["log_path"],
                       elapsed_total, summary_step["stderr"].strip()[:400]))

    ok_parts = sum(1 for r in part_reports if r["status"] == "ok")
    skipped_parts = sum(1 for r in part_reports if r["status"] == "skipped")
    emit("ok", purpose, method, str(target), None,
         "codexログ(まとめ): %s ／ 所要 %d秒（全体） ／ 使用モデル: %s ／ reasoning effort: %s"
         " ／ 区切り: %d件（実行%d・スキップ%d） ／ truncated_outputs: %d ／ view_image_calls: %d"
         % (summary_step["log_path"], elapsed_total, summary_step["model"] or "不明",
            reasoning_effort, len(part_reports), ok_parts, skipped_parts,
            truncated_total, view_image_total),
         extra={"elapsed_sec": elapsed_total, "model": summary_step["model"],
                "written_by": summary_step["written_by"], "timed_out": any_timed_out,
                "truncated_outputs": truncated_total, "view_image_calls": view_image_total,
                "reasoning_effort": reasoning_effort,
                "token_usage": {"total": token_totals, "parts": token_by_part},
                "parts": part_reports})
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
    parser.add_argument("--mode", default=None, choices=["weekly", "monthly"],
                        help="growth-audit: 評価範囲。weekly は --since/--until と併用、"
                             "monthly は --month（省略時は前月）")
    parser.add_argument("--since", default=None,
                        help="growth-audit --mode weekly: 対象期間の開始日 YYYY-MM-DD")
    parser.add_argument("--until", default=None,
                        help="growth-audit --mode weekly: 対象期間の終了日 YYYY-MM-DD")
    parser.add_argument("--month", default=None,
                        help="growth-audit --mode monthly: 対象年月 YYYY-MM（省略時は前月）")
    parser.add_argument("--dry-run", action="store_true",
                        help="growth-audit: Codexを起動せず、区切りの実行計画（対象・字数・"
                             "画像枚数・スキップ有無）だけを表示して終了する（D-0255）")
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
        return run_growth_audit(purpose, args.prompt_file, args.output_file, args.model,
                                mode=args.mode, since=args.since, until=args.until,
                                month=args.month, dry_run=args.dry_run)
    return run_exec(purpose, args.prompt_file, args.out_name, args.model)


if __name__ == "__main__":
    sys.exit(main())
