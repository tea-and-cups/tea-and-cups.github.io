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
                     [--render-only <出力先ディレクトリ>]（Codexを起動せず、全区切りの部分監査
                       プロンプトとまとめのプロンプトを置換済みで書き出して終了する・D-0265）
                     [--only-part <区切り名>]（その区切りだけ実行し、まとめは実行しない・D-0265）
                     [--skip-sns]（週次のみ。sns.md が全項目「未評価」でも Codex を呼ぶ前に止まらない・D-0272）
                     [--skip-pin-check]（週次のみ。対象週に PROCESSING の行が残っていても止まらない）
               実行: <codexの実体パス> exec -C <プロジェクトルート> -s read-only --json -o <出力先>
               （GROWTH_AUDIT_HARDENING_ARGS で外部遮断を上乗せし、windows.sandbox="elevated"・
               model_reasoning_effort・tool_output_token_limit=30000 を追加で渡す・2026-09-28）
               "codex"（PATH名）ではなく os.path.realpath(shutil.which("codex")) の実体パスで
               起動する（windows.sandbox="elevated" は実体パスでないと失敗するため・診断済み）。
               1回のCodex呼び出しで全対象を読ませるのをやめ、対象を「区切り」（weekly=
               期間内に変更があった生成ルール等のR-1..R-n＋記事単位のO-1..O-n（変更の無い
               生成ルールは区切りRに含めない）／monthly=当月の記事のA-1..A-n（新しい記事は全文・
               更新した記事は当月の差分）＋当月に変更があった生成ルールのG-1..G-n＋当月に変更した
               恒久アセットと検索表示の多いカテゴリページ1件のS-1..S-n＋見本3本までのP-1..P-n
               ・2026-11-01）に分け、
               区切りごとに1回ずつ Codex を呼んで
               growth/outputs/<label>/parts/<区切り名>.md（所見のみ）へ保存し、最後に
               全区切りの出力・監査スキル・入力数値（実験の状態を含む）・docs/tasks.md・docs/decisions.md
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
               成功時のJSONには truncated_outputs（rolloutの"Warning: truncated output (original token count: N)"行の件数・D-0265）・
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
  揃っている（区切り=## 所見・## 部分監査範囲／まとめ=## 要約・## 実験の判定・
  ## 新しい実験の提案・## 誠実さの重大な指摘・## 評価できなかったもの。月次のまとめは
  MONTHLY_ONLY_SECTIONS（## 到達数の振り返り・## 来月のチャネル配分・## 前月の作業キューの結果・
  ## 来月の作業キュー案・## サイト改善の提案・## 監査範囲）も必須（2026-11-01）。週次の ## 監査範囲 は
  gateway が書く・S-0027 ②）。
  いずれか1つでも欠けた区切り・まとめがあれば、その時点で全体を失敗とする
  （出力ファイルは削除しない・終了コードは成果物なしと同じ EXIT_ARTIFACT_MISSING）。

週次の入力の自動生成・監査範囲の機械集計・SNSチェック（D-0272・--mode weekly のみ）:
  Codex を呼ぶ前に、(1) sns.md が無い／全項目「未評価」なら終了コード2で止まる（--skip-sns で続行）、
  (1-2) growth-metrics.py の pins.daily_totals（終了日の34日前〜終了日・--compare-weeks 4）を呼び、
  対象週に data_status PROCESSING の行（DELETED・重複の行は除く）が残っていれば終了コード2で止まる
  （--skip-pin-check で続行）。止まらなければその標準出力を pins-daily-totals.json として加工せず保存する、
  (2) growth/inputs/<週>/ へ pins-summary.md・ga4-source-medium.md・ga4-source-landing.md・
  ga4-source-landing-compare.md（対象週・前週・直前4週の比較）・gsc-page-week.json・gsc-page-28d.json
  （GSC記事別・対象週／対象週の日曜で終わる28日）・buffer-summary.md・
  buffer-posts.json・buffer-aggregate.json（送信日時が対象期間のもの）を作り、site/scripts/
  build-site.sh で手元ビルドを1回行って、dist の記事ページ1件とカテゴリページ1件を区切りRの
  対象に加える。続けて experiments.py measure で experiments-status.json・pin-14d.json・sns-posts-7d.json
  を同じフォルダへ置く（失敗したら【注意】を出して空の形で置き、続行する・S-0027 ①）。監査の最後に audit.md の「## 監査範囲」節を、各区切り・まとめの実行ログから数えた
  値（truncated_outputs・view_image_calls・切り詰めたファイル・読めた対象/対象総数）の表で置き換える。
  --dry-run・--render-only の画面には英数字だけで JSON ファイルのパスと件数を出し、JSON の中身は
  tmp/codex-gateway/growth-audit-<週>-<dry-run|render-only>.json へ UTF-8 で保存する。

実験の入力と判定の自動記録（S-0027 ②）:
  採用済みの指示（GD）の遵守確認はしない。growth/ledger/adopted-directives.tsv は凍結し、読まない。
  月次も Codex を呼ぶ前に experiments.py measure（週末日=対象月の末日）と gsc-page-28d.json（対象月の
  末日で終わる28日）を growth/inputs/monthly-<対象月>/ へ置く。週次はまとめが「有効」と判定されたあとに
  experiments.py judge-due --week-end <--until> --status <入力の experiments-status.json> を呼び、
  結果（標準出力の行・RULE_REVERT_NEEDED の実験ID）を成功時 JSON の judge_due に載せる。judge-due が
  失敗しても監査の成否は変えない（【注意】を出し、judge_due.ok=false で返す）。
  まとめのプロンプトの {{SINCE}}／{{UNTIL}} には対象期間を入れる。

月次の入力の自動生成（2026-11-01・--mode monthly のみ）:
  区切りの計画を作る前に（--dry-run・--render-only でも）、_prepare_monthly_inputs が
  growth/inputs/monthly-<対象月>/ へ次を置く。実験の3つの JSON・gsc-page-28d.json・ga4-page-traffic.json
  （対象月・--limit 100。区切りPの見本選びが読む）・sns.md（直近の週次の複製）・article-diffs/<slug>.diff
  （更新した記事の当月の差分。区切りAが読む）と、MONTHLY_INPUT_FILES の md（reach-channels.md・
  reach-pages.md・ctr-candidates.md・query-gaps.md・prev-queue-results.md。1ファイル MONTHLY_INPUT_CHAR_CAP 字
  以内・合計は表の前）。prev-queue-results.md は台帳 data/monthly-queue.tsv（書き手は
  add-monthly-tasks.py --adopt だけ）の、前月の監査から採用した行を読む。字数は --dry-run と成功時 JSON の
  monthly_inputs に出す。

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
GROWTH_INPUTS_DIR = PROJECT_ROOT / "growth" / "inputs"
SITE_DIR = PROJECT_ROOT / "site"
SITE_DIST_DIR = SITE_DIR / "dist"

# 部分監査用プロンプトの固定パス（--prompt-file には渡さず、gateway が直接読む・D-0255）。
PART_PROMPT_PATHS = {
    "weekly": PROJECT_ROOT / "growth" / "prompts" / "weekly-audit-part.md",
    "monthly": PROJECT_ROOT / "growth" / "prompts" / "monthly-audit-part.md",
}
REQUIRED_PART_SECTIONS = ("## 所見", "## 部分監査範囲")
# まとめの必須節（S-0027 ②・実験中心の出力）。週次の「## 監査範囲」は gateway が実行ログから
# 書くため Codex の必須節に含めない（D-0272）。月次は週次の5節のあとに MONTHLY_ONLY_SECTIONS を
# この順で足す（2026-11-01・月次の作り直し）。
EXPERIMENT_SUMMARY_SECTIONS = ("## 要約", "## 実験の判定", "## 新しい実験の提案",
                               "## 誠実さの重大な指摘", "## 評価できなかったもの")
MONTHLY_ONLY_SECTIONS = ("## 到達数の振り返り", "## 来月のチャネル配分", "## 前月の作業キューの結果",
                         "## 来月の作業キュー案", "## サイト改善の提案", "## 監査範囲")
REQUIRED_SUMMARY_SECTIONS = EXPERIMENT_SUMMARY_SECTIONS + MONTHLY_ONLY_SECTIONS
REQUIRED_PART_SECTIONS_BY_MODE = {
    "weekly": REQUIRED_PART_SECTIONS,
    "monthly": REQUIRED_PART_SECTIONS,
}
REQUIRED_SUMMARY_SECTIONS_BY_MODE = {
    "weekly": EXPERIMENT_SUMMARY_SECTIONS,
    "monthly": REQUIRED_SUMMARY_SECTIONS,
}

# 生成ルール一式。週次は期間内に変更があったものだけをR区切りへ、月次は変更の有無に
# 関わらず全文をG区切りへ載せる（2026-09-28）。ルート直下は更新時刻、site/ 配下はgit logで
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
# Codex が出力を切り詰めたときの警告行（実測: "Warning: truncated output (original token count: N)"）。
# 文言だけの部分一致だと、ツール出力に載った別の文書中の同じ文字列を数えてしまうため、
# 件数付きの完全な形に一致する行だけを数える（D-0265）。
_TRUNCATED_OUTPUT_RE = re.compile(r"Warning: truncated output \(original token count: \d+\)")


def _count_truncated_lines(text):
    """text のうち _TRUNCATED_OUTPUT_RE に一致する行の数。"""
    return sum(1 for line in text.splitlines() if _TRUNCATED_OUTPUT_RE.search(line))


def _count_rollout_signals(thread_id):
    """thread_id の rollout（~/.codex/sessions 配下）を探し、
    (truncated_outputs, view_image_calls) を数える。見つからなければ (0, 0) を返す。

    truncated_outputs: custom_tool_call_output の出力テキストに含まれる
      _TRUNCATED_OUTPUT_RE に一致する行の件数（実測フォーマット確認済み・2026-09-28／D-0265）。
    view_image_calls: view_image という名前の直接のツール呼び出し、または
      exec 等のツール呼び出し内で view_image(...) を実行しているものの件数
      （実測で view_image は exec の JS コード内から呼ばれる形を確認・2026-09-28）。
    """
    scan = _scan_rollout(thread_id)
    return scan["truncated"], scan["view_image"]


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


def _generation_rule_root_files():
    """生成ルールのうちルート直下（rules/*.md・固定3ファイル）のPathリストを返す。"""
    files = sorted((PROJECT_ROOT / "rules").glob("*.md")) if (PROJECT_ROOT / "rules").is_dir() else []
    files += GENERATION_RULE_FILES_ROOT_FIXED
    return files


def _generation_rule_targets(since_date, until_date):
    """生成ルール全文の対象リストを [(表示パス, 変更ありbool)] で返す（期間内変更の判定つき）。

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

    for p in _generation_rule_root_files():
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


def _all_generation_rule_files():
    """生成ルール一式（週次が変更判定に使う対象と同じ一覧）を表示パスのリストで返す
    （変更の有無を問わない。月次のG区切りで使う・2026-09-28）。
    """
    displays = [str(p.relative_to(PROJECT_ROOT)).replace("\\", "/")
                for p in _generation_rule_root_files()]
    displays += ["site/" + rel for rel in GENERATION_RULE_FILES_SITE]
    return displays


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


def _input_dir_for_output(target):
    """--output-file（growth/outputs/<label>/audit.md）と同じ <label> の
    growth/inputs/<label>/ を返す（既存の命名慣行に合わせる・新規の引数を増やさない）。
    """
    label = target.parent.name
    return GROWTH_INPUTS_DIR / label


# --- 週次の入力の自動生成・監査範囲の機械集計・SNSチェック（2026-10-11・D-0272）---------
# 週次の入力・監査範囲・SNSチェックは --mode weekly の中だけで動く。取得の下回り（_run_metrics・
# _payload_problem・_cap_text 等）は月次の入力の自動生成（_prepare_monthly_inputs・2026-11-01）も使う。

GROWTH_METRICS_SCRIPT = SITE_DIR / "scripts" / "growth-metrics.py"
BUILD_SITE_SCRIPT = SITE_DIR / "scripts" / "build-site.sh"
WEEKLY_INPUT_CHAR_CAP = 4000
BUILD_TIMEOUT_SEC = 900
METRICS_TIMEOUT_SEC = 300
# 切り詰めた呼び出しから、対象のファイル名を拾うための表現（ASCIIのパスだけ。日本語のパスは
# ログ上で壊れていることがあるため拾えなければ「不明」と書く）。
CALL_PATH_RE = re.compile(
    r"[A-Za-z0-9_./\\\[\]-]*[A-Za-z0-9_\]]\.(?:md|json|tsv|py|ts|css|html|txt|astro|mjs|js|png|yml|yaml|toml)\b")
SCOPE_NAMES_MAX = 6
SNS_VALUE_RE = re.compile(r"^\s*-\s*[^:：]+[:：]\s*(.*)$")


def _run_metrics(args):
    """growth-metrics.py を実行し (契約JSONの辞書, 標準出力そのまま, エラー文) を返す。
    status が error の契約JSONも辞書のまま返す（呼び出し側が status を見る）。
    """
    try:
        proc = subprocess.run(
            [sys.executable, str(GROWTH_METRICS_SCRIPT)] + [str(a) for a in args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=METRICS_TIMEOUT_SEC, cwd=str(PROJECT_ROOT))
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "", type(exc).__name__
    try:
        payload = json.loads(proc.stdout)
    except ValueError:
        return None, proc.stdout, "invalid JSON (rc=%s)" % proc.returncode
    return payload, proc.stdout, None


def _payload_problem(payload, err):
    """取得に失敗していれば理由の文字列、成功なら None。"""
    if err:
        return err
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        info = (payload or {}).get("error") if isinstance(payload, dict) else None
        if isinstance(info, dict):
            return "%s: %s" % (info.get("code"), info.get("message"))
        return "status is not ok"
    return None


def _cap_text(text, cap=WEEKLY_INPUT_CHAR_CAP):
    """text を cap 字（週次は WEEKLY_INPUT_CHAR_CAP・月次は MONTHLY_INPUT_CHAR_CAP）以内にする。
    超えた分は行単位で切り、省略した行数を明記する。"""
    if len(text) <= cap:
        return text
    lines = text.splitlines()
    kept = []
    size = 0
    for line in lines:
        if size + len(line) + 1 > cap - 100:
            break
        kept.append(line)
        size += len(line) + 1
    kept.append("（%d字の目安を超えたため、%d行を省略した）" % (cap, len(lines) - len(kept)))
    return "\n".join(kept) + "\n"


def _sns_unobserved(input_dir):
    """sns.md が無い、または観察項目がすべて「未評価」（空も含む）なら (True, 理由)。"""
    path = input_dir / "sns.md"
    if not path.is_file():
        return True, "sns.md がありません"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return True, "sns.md を読めません"
    values = []
    for line in text.splitlines():
        m = SNS_VALUE_RE.match(line)
        if m:
            values.append(m.group(1).strip())
    if not values:
        return True, "sns.md に観察項目の行がありません"
    if all((not v) or v.startswith("未評価") for v in values):
        return True, "sns.md の全項目が未評価です"
    return False, None


def _fmt_int(value):
    return "%d" % value if isinstance(value, int) else "-"


PIN_FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-pin-(\d+)-")
PIN_AGE_BUCKETS = (("0-6日", 0, 6), ("7-13日", 7, 13), ("14-20日", 14, 20), ("21日以上", 21, None))
PIN_METRIC_COLS = (("imp", "impressions"), ("out", "outbound_clicks"), ("pin", "pin_clicks"))


def _pin_created_dates():
    """output/pins のファイル名（YYYY-MM-DD-pin-<番号>-…）から {ピン番号(int): 作成日(date)} を作る。"""
    created = {}
    try:
        names = os.listdir(PROJECT_ROOT / "output" / "pins")
    except OSError:
        return created
    for name in names:
        m = PIN_FILE_RE.match(name)
        if not m:
            continue
        try:
            created[int(m.group(2))] = datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except ValueError:
            continue
    return created


PIN_DELETED_STATUS = "DELETED"


def _is_deleted_row(row):
    """削除済みピンの行（fetch-pin-daily-metrics.py が 404 で data_status を DELETED にした行）。"""
    return (row.get("data_status") or "") == PIN_DELETED_STATUS


def _row_int(row, col):
    try:
        return int(row.get(col) or 0)
    except ValueError:
        return 0


def _pins_age_tables(rows, start_date, since_date, until_date):
    """(1) 作成後の経過日数別の週合計（4週分）と、(2) 前週の上位10ピンの今週の値。
    duplicate_detected=true の行と DELETED の行は pins.daily_totals と同じく外す（週合計と一致させるため）。
    ピンの作成日は output/pins のファイル名の日付。経過日数 = 行の date - 作成日。
    """
    created = _pin_created_dates()
    rows = [r for r in rows if (r.get("duplicate_detected") or "").lower() != "true"
            and not _is_deleted_row(r)]

    def age_of(row):
        try:
            number = int(row.get("pin_number") or "")
            day = datetime.strptime(row.get("date") or "", "%Y-%m-%d").date()
        except ValueError:
            return None
        made = created.get(number)
        if made is None or day < made:
            return None
        return (day - made).days

    lines = ["", "## 作成後の経過日数別の週合計（セル=imp/out/pin・経過日数=その日-ファイル名の作成日・不明=対応ファイル無し・save省略）", "",
             "| 週 | " + " | ".join(b[0] for b in PIN_AGE_BUCKETS) + " | 作成日不明 | 合計imp |",
             "|---|" + "---|" * (len(PIN_AGE_BUCKETS) + 2)]
    first = datetime.strptime(start_date, "%Y-%m-%d").date()
    for i in range(4):
        w_start = first + timedelta(days=7 * i)
        w_end = w_start + timedelta(days=6)
        cells = [[0, 0, 0] for _ in range(len(PIN_AGE_BUCKETS) + 1)]
        for row in rows:
            day = row.get("date") or ""
            if not (w_start.isoformat() <= day <= w_end.isoformat()):
                continue
            age = age_of(row)
            idx = len(PIN_AGE_BUCKETS)
            if age is not None:
                for j, (_n, lo, hi) in enumerate(PIN_AGE_BUCKETS):
                    if age >= lo and (hi is None or age <= hi):
                        idx = j
                        break
            for k, (_n, col) in enumerate(PIN_METRIC_COLS):
                cells[idx][k] += _row_int(row, col)
        lines.append("| %s〜%s | %s | %d |" % (
            w_start.isoformat(), w_end.isoformat(),
            " | ".join("%d/%d/%d" % tuple(c) for c in cells), sum(c[0] for c in cells)))

    since = datetime.strptime(since_date, "%Y-%m-%d").date()
    prev_lo, prev_hi = (since - timedelta(days=7)).isoformat(), (since - timedelta(days=1)).isoformat()
    prev, cur = {}, {}
    for row in rows:
        day = row.get("date") or ""
        if prev_lo <= day <= prev_hi:
            target = prev
        elif since_date <= day <= until_date:
            target = cur
        else:
            continue
        key = row.get("pin_number") or "?"
        agg = target.setdefault(key, {"slug": row.get("article_slug") or "?", "imp": 0, "out": 0, "pin": 0})
        for name, col in PIN_METRIC_COLS:
            agg[name] += _row_int(row, col)
    ranked = sorted(prev.items(), key=lambda kv: (-kv[1]["imp"], kv[0]))[:10]
    lines += ["", "## 前週（%s〜%s）の上位10ピンの今週（%s〜%s）の値" % (prev_lo, prev_hi, since_date, until_date), "",
              "| ピン | 記事 | 作成日 | 前週imp | 今週imp | 今週out | 今週pin |", "|---|---|---|---|---|---|---|"]
    for number, agg in ranked:
        now = cur.get(number, {"imp": 0, "out": 0, "pin": 0})
        try:
            made = created.get(int(number))
        except ValueError:
            made = None
        lines.append("| %s | %s | %s | %d | %d | %d | %d |" % (
            number, agg["slug"], made.isoformat() if made else "不明", agg["imp"], now["imp"], now["out"], now["pin"]))
    return lines


def _build_pins_summary(since_date, until_date):
    """(a) ピン日次実績の要約。対象週と前3週の日別合計・週合計と、対象週のピン別上位10・下位10。"""
    until = datetime.strptime(until_date, "%Y-%m-%d")
    start = (until - timedelta(days=27)).strftime("%Y-%m-%d")
    lines = ["# ピン日次実績の要約（gateway が自動生成・対象期間 %s〜%s と、その前の3週）" % (since_date, until_date), ""]
    payload, _raw, err = _run_metrics(["pins", "--operation", "pins.daily_totals", "--since", start,
                                       "--until", until_date, "--compare-weeks", "3"])
    problem = _payload_problem(payload, err)
    if problem:
        lines.append("- 日別合計を取得できなかった: %s" % problem)
    else:
        series = payload["data"]["series"]
        lines += ["## 日別合計（imp=インプレッション・save=保存・out=アウトバウンドクリック・pin=ピンクリック。※は欠損日で一部の値）", "",
                  "| 日付 | imp | save | out | pin |", "|---|---|---|---|---|"]
        for rec in series:
            mark = "※" if rec.get("missing_flag") else ""
            lines.append("| %s%s | %s | %s | %s | %s |" % (
                rec["date"], mark, rec["impressions"], rec["saves"], rec["outbound_clicks"], rec["pin_clicks"]))
        lines += ["", "## 週合計（欠損日を含む・※の日があれば下限値）", "",
                  "| 週 | imp | save | out | pin | 欠損日数 |", "|---|---|---|---|---|---|"]
        for i in range(0, len(series), 7):
            chunk = series[i:i + 7]
            lines.append("| %s〜%s | %d | %d | %d | %d | %d |" % (
                chunk[0]["date"], chunk[-1]["date"],
                sum(r["impressions"] for r in chunk), sum(r["saves"] for r in chunk),
                sum(r["outbound_clicks"] for r in chunk), sum(r["pin_clicks"] for r in chunk),
                sum(1 for r in chunk if r.get("missing_flag"))))
    # ピン別（対象期間・インプレッション順）
    tsv = PROJECT_ROOT / "data" / "pin-daily-metrics.tsv"
    per_pin = {}
    window_rows = []  # 28日の窓（start〜until）の行。経過日数別・前週上位の表に使う
    try:
        with open(tsv, "r", encoding="utf-8") as fh:
            header = None
            for raw_line in fh:
                cells = raw_line.rstrip("\r\n").split("\t")
                if header is None:
                    header = cells
                    continue
                row = dict(zip(header, cells))
                if _is_deleted_row(row):
                    continue
                day = row.get("date") or ""
                if start <= day <= until_date:
                    window_rows.append(row)
                if not (since_date <= day <= until_date):
                    continue
                key = row.get("pin_id") or ""
                agg = per_pin.setdefault(key, {"pin_number": row.get("pin_number") or "?",
                                               "slug": row.get("article_slug") or "?",
                                               "imp": 0, "save": 0, "out": 0, "pin": 0})
                for name, col in (("imp", "impressions"), ("save", "saves"),
                                  ("out", "outbound_clicks"), ("pin", "pin_clicks")):
                    try:
                        agg[name] += int(row.get(col) or 0)
                    except ValueError:
                        pass
    except OSError:
        per_pin = {}
        window_rows = []
    lines += _pins_age_tables(window_rows, start, since_date, until_date)
    lines += ["", "## 対象期間のピン別（インプレッション順・全%d本中）" % len(per_pin)]
    if not per_pin:
        lines.append("- data/pin-daily-metrics.tsv に対象期間の行が無い")
    else:
        ranked = sorted(per_pin.values(), key=lambda a: (-a["imp"], a["pin_number"]))
        top = ranked[:10]
        bottom = [a for a in ranked[10:][-10:]]
        for title, group in (("上位10", top), ("下位10", bottom)):
            lines += ["", "### %s" % title, "", "| ピン | 記事 | imp | save | out | pin |", "|---|---|---|---|---|---|"]
            for a in group:
                lines.append("| %s | %s | %d | %d | %d | %d |" % (
                    a["pin_number"], a["slug"], a["imp"], a["save"], a["out"], a["pin"]))
    return _cap_text("\n".join(lines) + "\n")


def _build_ga4_source_summary(since_date, until_date):
    """(b) GA4の参照元（sessionSourceMedium）別の対象期間のセッション数。"""
    lines = ["# GA4 参照元別（gateway が自動生成・対象期間 %s〜%s・セッション数順）" % (since_date, until_date), ""]
    payload, _raw, err = _run_metrics(["ga4", "--operation", "ga4.source_medium", "--since", since_date,
                                       "--until", until_date, "--limit", "100"])
    problem = _payload_problem(payload, err)
    if problem:
        lines.append("- 取得できなかった: %s" % problem)
        return "\n".join(lines) + "\n"
    series = sorted(payload["data"]["series"], key=lambda r: -(r.get("sessions") or 0))
    totals = (payload["data"].get("totals") or {})
    lines += ["| 参照元 / メディア | sessions | users | PV |", "|---|---|---|---|"]
    for rec in series:
        lines.append("| %s | %s | %s | %s |" % (
            rec.get("session_source_medium") or "（不明）", _fmt_int(rec.get("sessions")),
            _fmt_int(rec.get("activeUsers")), _fmt_int(rec.get("screenPageViews"))))
    lines.append("")
    lines.append("- 行数 %d・合計 sessions %d%s" % (
        len(series), sum(r.get("sessions") or 0 for r in series),
        "（--limit に達しており下限値）" if totals.get("is_lower_bound") else ""))
    return _cap_text("\n".join(lines) + "\n")


SOURCE_LANDING_TOP_N = 30


def _build_ga4_source_landing_summary(since_date, until_date):
    """(b2) GA4の参照元×ランディングページ別の対象期間のセッション数（GD-0047）。
    合計は表の前に置く（4,000字の行単位の切り詰めで消えないように）。
    """
    lines = ["# GA4 参照元×ランディングページ別（gateway が自動生成・対象期間 %s〜%s・セッション数順の上位%d行）"
             % (since_date, until_date, SOURCE_LANDING_TOP_N), ""]
    payload, _raw, err = _run_metrics(["ga4", "--operation", "ga4.source_landing", "--since", since_date,
                                       "--until", until_date, "--limit", "100"])
    problem = _payload_problem(payload, err)
    if problem:
        lines.append("- 取得できなかった: %s" % problem)
        return "\n".join(lines) + "\n"
    series = sorted(payload["data"]["series"], key=lambda r: -(r.get("sessions") or 0))
    totals = (payload["data"].get("totals") or {})
    lines.append("- 合計（取得した全%d行）: sessions %s・users %s・PV %s%s" % (
        len(series), _fmt_int(sum(r.get("sessions") or 0 for r in series)),
        _fmt_int(sum(r.get("activeUsers") or 0 for r in series)),
        _fmt_int(sum(r.get("screenPageViews") or 0 for r in series)),
        "（--limit に達しており下限値）" if totals.get("is_lower_bound") else ""))
    lines += ["", "| 参照元 / メディア | ランディングページ | sessions | users | PV |", "|---|---|---|---|---|"]
    for rec in series[:SOURCE_LANDING_TOP_N]:
        lines.append("| %s | %s | %s | %s | %s |" % (
            rec.get("session_source_medium") or "（不明）", rec.get("landing_page") or "（不明）",
            _fmt_int(rec.get("sessions")), _fmt_int(rec.get("activeUsers")), _fmt_int(rec.get("screenPageViews"))))
    if len(series) > SOURCE_LANDING_TOP_N:
        lines.append("")
        lines.append("- 下位%d行は省略した（合計には含む）" % (len(series) - SOURCE_LANDING_TOP_N))
    return _cap_text("\n".join(lines) + "\n")


def _signed(value, fmt="%d"):
    return ("+" + fmt % value) if value > 0 else (fmt % value)


def _build_ga4_source_landing_compare(since_date, until_date):
    """(b3) GA4の参照元×ランディングページ別セッション数を、対象週・前週・直前4週（週平均）で突き合わせる。
    ga4.source_landing を3回呼ぶ。合計は表の前に置く（4,000字の行単位の切り詰めで消えないように）。
    """
    since = datetime.strptime(since_date, "%Y-%m-%d")
    before = (since - timedelta(days=1)).strftime("%Y-%m-%d")
    periods = (("対象週", since_date, until_date, 1),
               ("前週", (since - timedelta(days=7)).strftime("%Y-%m-%d"), before, 1),
               ("直前4週", (since - timedelta(days=28)).strftime("%Y-%m-%d"), before, 4))
    lines = ["# GA4 参照元×ランディングページ別の比較（gateway が自動生成・セッション数・%s）"
             % "・".join("%s %s〜%s" % (p[0], p[1], p[2]) for p in periods), ""]
    table = {}
    failed = set()
    for idx, (label, start, end, weeks) in enumerate(periods):
        payload, _raw, err = _run_metrics(["ga4", "--operation", "ga4.source_landing", "--since", start,
                                           "--until", end, "--limit", "100"])
        problem = _payload_problem(payload, err)
        if problem:
            failed.add(idx)
            lines.append("- %s（%s〜%s）を取得できなかった: %s" % (label, start, end, problem))
            continue
        series = payload["data"]["series"]
        lower = (payload["data"].get("totals") or {}).get("is_lower_bound")
        sessions = sum(r.get("sessions") or 0 for r in series)
        pv = sum(r.get("screenPageViews") or 0 for r in series)
        per_week = "（週平均 sessions %.1f・PV %.1f）" % (sessions / weeks, pv / weeks) if weeks > 1 else ""
        lines.append("- %s（%s〜%s）の合計: sessions %d・PV %d%s（取得した%d行%s）" % (
            label, start, end, sessions, pv, per_week, len(series),
            "・--limit に達しており下限値" if lower else ""))
        for rec in series:
            key = (rec.get("session_source_medium") or "（不明）", rec.get("landing_page") or "（不明）")
            table.setdefault(key, [0, 0, 0])[idx] += rec.get("sessions") or 0
    lines.append("- 各期間の上位100行（PV順）に無い組は0と表示する（その期間が下限値なら実際は0とは限らない）")

    def cell(values, idx, fmt="%d", div=1):
        return "-" if idx in failed else fmt % (values[idx] / div if div > 1 else values[idx])

    ranked = sorted(table.items(), key=lambda kv: (-max(kv[1][0], kv[1][1], kv[1][2] / 4.0), kv[0]))
    lines += ["", "| 参照元 / メディア | ランディングページ | 対象週 | 前週 | 直前4週の週平均 | 前週比 | 4週平均比 |",
              "|---|---|---|---|---|---|---|"]
    for (source, landing), v in ranked[:SOURCE_LANDING_TOP_N]:
        vs_prev = "-" if failed & {0, 1} else _signed(v[0] - v[1])
        vs_avg = "-" if failed & {0, 2} else _signed(v[0] - v[2] / 4.0, "%.1f")
        lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            source, landing, cell(v, 0), cell(v, 1), cell(v, 2, "%.1f", 4), vs_prev, vs_avg))
    if len(ranked) > SOURCE_LANDING_TOP_N:
        lines.append("")
        lines.append("- 3期間のいずれかで大きい順の上位%d組を載せた（残り%d組は省略・合計には含む）"
                     % (SOURCE_LANDING_TOP_N, len(ranked) - SOURCE_LANDING_TOP_N))
    return _cap_text("\n".join(lines) + "\n")


def _build_buffer_summary(posts_payload, agg_payload, since_date, until_date):
    """(c) Buffer の要約（生JSONは4,000字を大きく超えるため、読みやすい要約を添える）。"""
    lines = ["# Buffer 投稿の要約（gateway が自動生成・送信日時が %s〜%s の投稿のみ）" % (since_date, until_date), ""]
    problem = _payload_problem(posts_payload, None)
    if problem:
        lines.append("- 投稿一覧を取得できなかった: %s" % problem)
    else:
        series = posts_payload["data"]["series"]
        by_service = {}
        for rec in series:
            by_service[rec.get("service")] = by_service.get(rec.get("service"), 0) + 1
        lines.append("- 投稿数: %d（%s）" % (len(series), "・".join("%s %d" % kv for kv in sorted(by_service.items()))))
        lines += ["", "| 送信 | サービス | 本文（先頭30字） | 反応 |", "|---|---|---|---|"]
        for rec in sorted(series, key=lambda r: r.get("sent_at") or ""):
            text = (rec.get("text") or "").replace("\n", " ").replace("|", "/")[:30]
            metrics = "・".join("%s=%s" % (m.get("type"), m.get("value"))
                               for m in (rec.get("metrics") or []) if m.get("value"))
            lines.append("| %s | %s | %s | %s |" % ((rec.get("sent_at") or "")[:16], rec.get("service"), text, metrics or "-"))
    lines += ["", "## チャネル別の集計"]
    problem = _payload_problem(agg_payload, None)
    if problem:
        lines.append("- 取得できなかった: %s" % problem)
    else:
        for rec in agg_payload["data"]["series"]:
            lines.append("- %s: %s" % (rec.get("service"), "・".join(
                "%s=%s" % (m.get("type"), m.get("value")) for m in (rec.get("metrics") or [])) or "反応なし"))
    return _cap_text("\n".join(lines) + "\n")


def _build_bash_candidates():
    """Git for Windows の bash を優先する（System32 の bash.exe は WSL の起動口で使えない）。"""
    found = []
    for cand in ("C:/Program Files/Git/bin/bash.exe", "C:/Program Files/Git/usr/bin/bash.exe"):
        if os.path.isfile(cand):
            found.append(cand)
    which = shutil.which("bash")
    if which and "system32" not in which.lower():
        found.append(which)
    return found


def _build_site_for_audit():
    """site/scripts/build-site.sh で手元のビルドを1回行う（commit・push・デプロイはしない）。
    戻り値: {"ok": bool, "elapsed": 秒, "reason": 失敗理由 or None}
    """
    started = time.time()
    candidates = _build_bash_candidates()
    if not candidates:
        return {"ok": False, "elapsed": 0, "reason": "bash not found"}
    try:
        proc = subprocess.run([candidates[0], BUILD_SITE_SCRIPT.as_posix()], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=BUILD_TIMEOUT_SEC,
                              cwd=str(SITE_DIR))
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "elapsed": int(time.time() - started), "reason": type(exc).__name__}
    elapsed = int(time.time() - started)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or [""]
        return {"ok": False, "elapsed": elapsed, "reason": "rc=%d %s" % (proc.returncode, tail[0][:120])}
    return {"ok": True, "elapsed": elapsed, "reason": None}


def _dist_built_at():
    index = SITE_DIST_DIR / "index.html"
    try:
        return datetime.fromtimestamp(index.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    except OSError:
        return "不明（dist が無い）"


def _pick_dist_pages(since_date, until_date):
    """(d) GD-0005 の判定用。対象週に公開した最新の記事ページと、そのカテゴリのカテゴリページ。
    対象週に公開が無ければ全期間で最新の記事を使う。戻り値: (記事ページ, カテゴリページ, 選び方) の
    表示パス（site/ 起点）。公開記事が無ければ (None, None, 理由)。
    """
    entries = []
    for category, posts in _posts_by_category().items():
        for slug, _path, date_str in posts:
            entries.append((date_str or "", slug, category))
    if not entries:
        return None, None, "公開記事が見つからない"
    in_week = [e for e in entries if since_date <= e[0] <= until_date]
    pool = in_week or entries
    date_str, slug, category = max(pool, key=lambda e: (e[0], e[1]))
    how = "対象週（%s〜%s）に公開した最新の記事 date=%s" % (since_date, until_date, date_str) if in_week \
        else "対象週に公開が無いため全期間で最新の記事 date=%s" % date_str
    return "site/dist/posts/%s/index.html" % slug, "site/dist/category/%s/index.html" % category, how


# pins-daily-totals.json の期間（rules/weekly-report.md 3-2節 1-3: 終了日の34日前〜終了日・4週比較）
PINS_TOTALS_SPAN_DAYS = 35
PINS_TOTALS_COMPARE_WEEKS = 4
PIN_CHECK_MESSAGE = "fetch-pin-daily-metrics.py の完了を待ってから再実行する。確定待ちなら --skip-pin-check で続行"
# GSC の記事別（対象週と、対象週の日曜で終わる28日）
GSC_BY_PAGE_INPUTS = (("gsc-page-week.json", 7, "今週の入力・GSC記事別（対象週・契約JSONを加工せず保存）"),
                      ("gsc-page-28d.json", 28, "今週の入力・GSC記事別（対象週の日曜で終わる28日・契約JSONを加工せず保存）"))


def _pin_processing_days(payload, since_date, until_date):
    """pins.daily_totals の系列から、対象週で PROCESSING の行が残る日を [(日付, 行数)] で返す。
    DELETED の行・duplicate_detected=true の行は growth-metrics.py 側で processing_rows から外れている。
    """
    days = []
    for rec in (payload.get("data") or {}).get("series") or []:
        day = rec.get("date") or ""
        if since_date <= day <= until_date and (rec.get("processing_rows") or 0) > 0:
            days.append((day, rec["processing_rows"]))
    return days


def _prepare_pins_daily_totals(input_dir, since_date, until_date, skip_pin_check):
    """週次の取得完了の確認と pins-daily-totals.json の生成（Codex を呼ぶ前）。

    pins.daily_totals（終了日の34日前〜終了日・--compare-weeks 4）を呼び、対象週に PROCESSING の行が
    残っていれば止める（--skip-pin-check で続行）。止めなければ標準出力を加工せず保存する。
    戻り値: (停止理由 or None, 区切りRへ足す注記の行のリスト)
    """
    until = datetime.strptime(until_date, "%Y-%m-%d")
    start = (until - timedelta(days=PINS_TOTALS_SPAN_DAYS - 1)).strftime("%Y-%m-%d")
    payload, raw, err = _run_metrics(["pins", "--operation", "pins.daily_totals", "--since", start,
                                      "--until", until_date, "--compare-weeks", PINS_TOTALS_COMPARE_WEEKS])
    notes = []
    problem = _payload_problem(payload, err)
    if problem:
        notes.append("- （注）pins.daily_totals を取得できず、ピン日次の取得完了を確認できなかった: %s" % problem)
    else:
        days = _pin_processing_days(payload, since_date, until_date)
        if days:
            detail = "、".join("%s %d行" % d for d in days)
            if not skip_pin_check:
                return ("対象週に data_status が PROCESSING の行が残っています（%s）。%s"
                        % (detail, PIN_CHECK_MESSAGE)), []
            notes.append("- （注）対象週に PROCESSING の行が残ったまま --skip-pin-check で続行した（%s）。"
                         "pins-daily-totals.json の該当日は missing_flag で値は一部のみ" % detail)
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "pins-daily-totals.json").write_text(raw or "{}", encoding="utf-8")
    return None, notes


def _prepare_weekly_inputs(input_dir, since_date, until_date, pin_notes=None):
    """Codex を呼ぶ前に、週次の入力 (a)〜(e) を growth/inputs/<週>/ へ作る（D-0272）。
    pins-daily-totals.json は先に _prepare_pins_daily_totals() が作る（ここでは一覧に載せるだけ）。

    戻り値: {"items": 区切りRへ足す対象, "files": [{"path", "chars", "note"}], "dist": {...}}
    """
    input_dir.mkdir(parents=True, exist_ok=True)
    label = input_dir.name
    items = []
    files = []

    def display(name):
        return "growth/inputs/%s/%s" % (label, name)

    def add_item(path_display, abs_path, note, extra_lines=None):
        chars = _text_len(abs_path)
        lines = ["- %s（%s）" % (path_display, note)] + list(extra_lines or [])
        items.append({"path": path_display, "chars": chars, "images": 0, "lines": lines})
        files.append({"path": path_display, "chars": chars, "note": note})

    def add_file(path_display, abs_path, note):
        # まとめのプロンプト（weekly-audit.md）が直接読む JSON。区切りRの対象には足さない
        files.append({"path": path_display, "chars": _text_len(abs_path), "note": note})

    # (a0) ピン日次の日別合計と4週比較（_prepare_pins_daily_totals が作成済み）
    p = input_dir / "pins-daily-totals.json"
    if p.is_file():
        add_file(display("pins-daily-totals.json"), p,
                 "今週の入力・ピン日次の日別合計と4週比較（gateway が自動生成・契約JSONを加工せず保存）")
    if pin_notes:
        items.append({"path": "", "chars": 0, "images": 0, "lines": list(pin_notes)})

    # (a) ピン日次実績の要約
    p = input_dir / "pins-summary.md"
    p.write_text(_build_pins_summary(since_date, until_date), encoding="utf-8")
    add_item(display("pins-summary.md"), p, "今週の入力・ピン日次実績の要約（gateway が自動生成）")

    # (b) GA4 参照元別
    p = input_dir / "ga4-source-medium.md"
    p.write_text(_build_ga4_source_summary(since_date, until_date), encoding="utf-8")
    add_item(display("ga4-source-medium.md"), p, "今週の入力・GA4参照元別（gateway が自動生成）")

    # (b2) GA4 参照元×ランディングページ別（GD-0047）
    p = input_dir / "ga4-source-landing.md"
    p.write_text(_build_ga4_source_landing_summary(since_date, until_date), encoding="utf-8")
    add_item(display("ga4-source-landing.md"), p, "今週の入力・GA4参照元×ランディングページ別（gateway が自動生成）")

    # (b3) GA4 参照元×ランディングページ別の、前週・直前4週との比較
    p = input_dir / "ga4-source-landing-compare.md"
    p.write_text(_build_ga4_source_landing_compare(since_date, until_date), encoding="utf-8")
    add_item(display("ga4-source-landing-compare.md"), p,
             "今週の入力・GA4参照元×ランディングページ別の前週・直前4週との比較（gateway が自動生成）")

    # (e) GSC の記事別（対象週と、対象週の日曜で終わる28日。契約JSONを加工せず保存する）
    until = datetime.strptime(until_date, "%Y-%m-%d")
    for name, days, note in GSC_BY_PAGE_INPUTS:
        start = (until - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        _payload, raw, _err = _run_metrics(["gsc", "--operation", "gsc.search_analytics_by_page", "--since", start,
                                            "--until", until_date, "--limit", "100"])
        p = input_dir / name
        p.write_text(raw or "{}", encoding="utf-8")
        add_file(display(name), p, "%s・%s〜%s" % (note, start, until_date))

    # (c) Buffer（対象週の送信日時で絞る。生JSONは加工せず保存し、読みやすい要約を添える）
    posts_payload, posts_raw, posts_err = _run_metrics(
        ["buffer", "--operation", "buffer.sent_posts", "--since", since_date, "--until", until_date, "--limit", "25"])
    agg_payload, agg_raw, agg_err = _run_metrics(
        ["buffer", "--operation", "buffer.aggregated_metrics", "--since", since_date, "--until", until_date])
    (input_dir / "buffer-posts.json").write_text(posts_raw or "{}", encoding="utf-8")
    (input_dir / "buffer-aggregate.json").write_text(agg_raw or "{}", encoding="utf-8")
    summary = input_dir / "buffer-summary.md"
    summary.write_text(_build_buffer_summary(
        posts_payload if not posts_err else None, agg_payload if not agg_err else None,
        since_date, until_date), encoding="utf-8")
    add_item(display("buffer-summary.md"), summary, "今週の入力・Buffer投稿の要約（gateway が自動生成）")
    add_item(display("buffer-posts.json"), input_dir / "buffer-posts.json",
             "今週の入力・Buffer投稿（送信日時が対象期間のもの・契約JSONを加工せず保存）")
    add_item(display("buffer-aggregate.json"), input_dir / "buffer-aggregate.json",
             "今週の入力・Bufferチャネル別集計（契約JSONを加工せず保存）")

    # (d) GD-0005 の判定用: 手元のビルドを1回行い、記事ページ1件とカテゴリページ1件を対象に加える
    eprint("weekly input (d): building site/dist locally ...")
    build = _build_site_for_audit()
    built_at = _dist_built_at()
    article_page, category_page, how = _pick_dist_pages(since_date, until_date)
    dist = {"build_ok": build["ok"], "build_seconds": build["elapsed"], "build_reason": build["reason"],
            "dist_built_at": built_at, "article_page": article_page, "category_page": category_page}
    if build["ok"]:
        build_note = "site/dist は今回の手元ビルド（%s・%d秒）" % (built_at, build["elapsed"])
    else:
        build_note = "site/dist のビルドに失敗したため既存の dist を使う（dist のビルド日時 %s・ビルド失敗: %s）" % (
            built_at, build["reason"])
    first = True
    for page in (article_page, category_page):
        if not page:
            continue
        abs_path = SITE_DIR / page[len("site/"):]
        extra = ["  - （注）%s" % build_note] if first else []
        first = False
        if not abs_path.is_file():
            extra.append("  - （注）%s が dist に無い" % page)
        add_item(page, abs_path, "公開ページの現状確認用・%s" % how if page == article_page
                 else "公開ページの現状確認用・上の記事のカテゴリページ", extra)
    if not article_page:
        items.append({"path": "", "chars": 0, "images": 0,
                      "lines": ["- （注）判定用の dist ページを選べなかった: %s ／ %s" % (how, build_note)]})

    # (f) 実験の状態と途中指標（experiments.py measure・S-0027 ①）。まとめが直接読む JSON。区切りRには足さない
    for name, note in _prepare_experiment_inputs(input_dir, until_date):
        add_file(display(name), input_dir / name, note)
    return {"items": items, "files": files, "dist": dist}


EXPERIMENTS_SCRIPT = SITE_DIR / "scripts" / "experiments.py"
EXPERIMENT_INPUTS = (
    ("experiments-status.json", "今週の入力・実験の状態（実行中の実験の前後の中央値・判定案。experiments.py measure）",
     {"experiments": [], "pending_rules": []}),
    ("pin-14d.json", "今週の入力・ピン別の作成後14日合計インプレッション（直近4週に作成・14日分確定のもの）",
     {"pins": [], "pending": []}),
    ("sns-posts-7d.json", "今週の入力・X・Threads の送信7日後の投稿別指標（週末日の13〜7日前に送信）",
     {"posts": []}),
)


def _prepare_experiment_inputs(input_dir, until_date):
    """experiments.py measure で3つの JSON を input_dir へ書く。失敗した（または欠けた）ものは【注意】を出して
    空の形で置き、監査は続行する（入力の欠けで週次全体を止めない）。戻り値: [(ファイル名, 注記)]"""
    problem = None
    try:
        proc = subprocess.run(
            [sys.executable, str(EXPERIMENTS_SCRIPT), "measure", "--week-end", until_date, "--out", str(input_dir)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=METRICS_TIMEOUT_SEC, cwd=str(PROJECT_ROOT))
        if proc.returncode != 0:
            problem = "rc=%s %s" % (proc.returncode, (proc.stderr or proc.stdout).strip()[-300:])
    except (OSError, subprocess.SubprocessError) as exc:
        problem = type(exc).__name__
    result = []
    for name, note, empty in EXPERIMENT_INPUTS:
        path = input_dir / name
        reason = problem
        if not reason:
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                reason = "%s を読めない（%s）" % (name, type(exc).__name__)
        if reason:
            eprint("【注意】experiments.py measure が失敗したため %s を空の形で置きます: %s" % (name, reason))
            data = dict({"schema": 1, "week_end": until_date, "status": "unavailable", "reason": reason}, **empty)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            note += "・（注）取得失敗のため空"
        result.append((name, note))
    return result


def _month_end(year_month):
    year, month = (int(x) for x in year_month.split("-"))
    first_next = datetime(year + (month == 12), month % 12 + 1, 1)
    return (first_next - timedelta(days=1)).strftime("%Y-%m-%d")


# --- 月次の入力の自動生成（2026-11-01・月次の作り直し）-------------------------------------
# Codex を呼ぶ前に gateway が取得し、md の要約（1ファイル MONTHLY_INPUT_CHAR_CAP 字以内・合計は表の前）に
# して growth/inputs/monthly-<対象月>/ へ置く。--dry-run・--render-only でも作る（区切りの計画が
# ga4-page-traffic.json・gsc-page-28d.json を読むため）。

MONTHLY_INPUT_CHAR_CAP = 8000
MONTHLY_QUEUE_LEDGER = PROJECT_ROOT / "data" / "monthly-queue.tsv"
MONTHLY_QUEUE_COLUMNS = ("M番号", "採用日", "監査パス", "Q番号", "タグ", "slug", "対象指標", "基準値")
TASKS_MD_PATH = PROJECT_ROOT / "docs" / "tasks.md"
REACH_MONTHS = 3
REACH_PAGES_TOP_N = 15
REACH_SOURCES_TOP_N = 15
PIN_DROP_TOP_N = 5
# CTR改修の候補（D1）: 表示がしきい値以上・CTR がしきい値未満・平均順位がしきい値以内の記事ページ。
CTR_MIN_IMPRESSIONS = 30
CTR_MAX = 0.02
CTR_MAX_POSITION = 20
CTR_CANDIDATES_MAX = 10
# 新しい題材の材料（D2）: 語×ページの表から、表示がしきい値以上の語を表示の多い順に。
QUERY_GAPS_MIN_IMPRESSIONS = 2
QUERY_GAPS_MAX_ROWS = 60
# 前月の作業キューの結果（D5）: 完了日の前後で同じ日数の GSC ページ指標を比べる。
PREV_QUEUE_WINDOW_DAYS = 28
PREV_QUEUE_MIN_DAYS = 14
GSC_LAG_DAYS = 3
SITE_URL_PREFIX = "https://kohaku-jikan.com"
WEEK_LABEL_RE = re.compile(r"^(\d{4})-W(\d{2})$")
MONTH_ROW_SLUG_RE = re.compile(r"（([a-z0-9]+(?:-[a-z0-9]+)*)・(?:category:\s*)?[a-z0-9-]+）")
RANGE_SLUG_RE = re.compile(r"slug=([a-z0-9,-]+)")


def _monthly_period(year_month):
    """対象月の (月初, 末日) を返す。月の途中に実行したときは末日の代わりに前日までで切る
    （API が未来の日付を受け付けないため）。"""
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    return "%s-01" % year_month, min(_month_end(year_month), yesterday)


def _channel_of(source_medium):
    """GA4 の「参照元 / メディア」をチャネルへ寄せる（D7・チャネル単位）。"""
    source, _, medium = (source_medium or "").lower().partition(" / ")
    source, medium = source.strip(), medium.strip()
    if medium == "organic":
        return "検索"
    if "pinterest" in source:
        return "Pinterest"
    if "threads" in source:
        return "Threads"
    if source in ("x", "t.co", "twitter.com", "x.com", "twitter"):
        return "X"
    if source == "(direct)":
        return "直接"
    return "その他"


CHANNEL_ORDER = ("検索", "Pinterest", "Threads", "X", "直接", "その他")


def _series(payload):
    return ((payload or {}).get("data") or {}).get("series") or []


def _lower_bound(payload):
    return bool((((payload or {}).get("data") or {}).get("totals") or {}).get("is_lower_bound"))


def _pct(value):
    return "%.1f%%" % (value * 100) if isinstance(value, (int, float)) else "-"


def _slug_from_url(url):
    """GSC のページURL・GA4 のページパスから記事の slug を返す（記事ページでなければ None）。"""
    path = (url or "")
    if path.startswith(SITE_URL_PREFIX):
        path = path[len(SITE_URL_PREFIX):]
    return _slug_from_page_path(path)


def _build_reach_channels(year_month):
    """(a) reach-channels.md: チャネル×3か月の sessions と、Pinterest 口座全体の月別・週別・落ちた日。"""
    months = [year_month]
    while len(months) < REACH_MONTHS:
        months.insert(0, _previous_month(months[0]))
    lines = ["# 到達数のチャネル別推移（gateway が自動生成・%s〜%s）" % (months[0], months[-1]), ""]
    by_channel = {}
    sources = {}
    totals = {}
    notes = []
    for ym in months:
        start, end = _monthly_period(ym)
        payload, _raw, err = _run_metrics(["ga4", "--operation", "ga4.source_medium", "--since", start,
                                           "--until", end, "--limit", "100"])
        problem = _payload_problem(payload, err)
        if problem:
            notes.append("- %s の ga4.source_medium を取得できなかった: %s" % (ym, problem))
            continue
        if _lower_bound(payload):
            notes.append("- %s の ga4.source_medium は --limit に達しており下限値" % ym)
        for rec in _series(payload):
            sessions = rec.get("sessions") or 0
            channel = _channel_of(rec.get("session_source_medium"))
            by_channel.setdefault(channel, {})[ym] = by_channel.get(channel, {}).get(ym, 0) + sessions
            totals[ym] = totals.get(ym, 0) + sessions
            if ym == year_month:
                sources[rec.get("session_source_medium") or "（不明）"] = sessions

    lines.append("- 合計（GA4 sessions・全ページ）: %s" % " ／ ".join(
        "%s %s" % (ym, _fmt_int(totals.get(ym))) for ym in months))
    lines.append("- 取得: ga4.source_medium（月ごと・--limit 100）と pins.daily_totals（月ごと）。チャネルは"
                 "検索=*/organic・Pinterest=参照元に pinterest・Threads=参照元に threads・X=x/t.co・直接=(direct)")
    lines += notes
    lines += ["", "## チャネル別 sessions（GA4）", "",
              "| チャネル | %s | 前月比 |" % " | ".join(months), "|---|%s---|" % ("---|" * len(months))]
    for channel in CHANNEL_ORDER:
        values = by_channel.get(channel, {})
        cur, prev = values.get(months[-1], 0), values.get(months[-2], 0)
        lines.append("| %s | %s | %s |" % (channel, " | ".join("%d" % values.get(ym, 0) for ym in months),
                                          _signed(cur - prev)))

    lines += ["", "## Pinterest 口座全体（pins.daily_totals・未確定の日は値が一部のみ）", "",
              "| 月 | インプレッション | 外部クリック | ピンクリック | 保存 | 未確定の日 |", "|---|---|---|---|---|---|"]
    days = []
    for ym in months:
        start, end = _monthly_period(ym)
        payload, _raw, err = _run_metrics(["pins", "--operation", "pins.daily_totals", "--since", start,
                                           "--until", end])
        problem = _payload_problem(payload, err)
        if problem:
            lines.append("| %s | 取得できなかった: %s | | | | |" % (ym, problem))
            continue
        series = _series(payload)
        days += series
        lines.append("| %s | %d | %d | %d | %d | %d |" % (
            ym, sum(r.get("impressions") or 0 for r in series), sum(r.get("outbound_clicks") or 0 for r in series),
            sum(r.get("pin_clicks") or 0 for r in series), sum(r.get("saves") or 0 for r in series),
            sum(1 for r in series if r.get("missing_flag"))))

    imp_by_day = {r.get("date"): r.get("impressions") or 0 for r in days if r.get("date")}
    weeks = {}
    for day, imp in imp_by_day.items():
        monday = datetime.strptime(day, "%Y-%m-%d") - timedelta(days=datetime.strptime(day, "%Y-%m-%d").weekday())
        weeks.setdefault(monday.strftime("%Y-%m-%d"), []).append(imp)
    lines += ["", "## Pinterest 週別合計（月曜始まり・週の途中で期間が切れる週は日数が少ない）", "",
              "| 週の月曜 | 日数 | インプレッション | 前週比 |", "|---|---|---|---|"]
    prev_total = None
    for monday in sorted(weeks):
        total = sum(weeks[monday])
        lines.append("| %s | %d | %d | %s |" % (monday, len(weeks[monday]), total,
                                              "-" if prev_total is None else _signed(total - prev_total)))
        prev_total = total
    drops = []
    for day, imp in imp_by_day.items():
        week_ago = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
        if week_ago in imp_by_day:
            drops.append((imp - imp_by_day[week_ago], day, imp, imp_by_day[week_ago]))
    lines += ["", "## 7日前の同じ曜日から最も落ちた日（上位%d件）" % PIN_DROP_TOP_N, "",
              "| 日付 | インプレッション | 7日前 | 差 |", "|---|---|---|---|"]
    for diff, day, imp, before in sorted(drops)[:PIN_DROP_TOP_N]:
        lines.append("| %s | %d | %d | %s |" % (day, imp, before, _signed(diff)))

    top_sources = sorted(sources.items(), key=lambda kv: -kv[1])
    lines += ["", "## 対象月の参照元の内訳（sessions 上位%d）" % REACH_SOURCES_TOP_N, "",
              "| 参照元 / メディア | チャネル | sessions |", "|---|---|---|"]
    for name, sessions in top_sources[:REACH_SOURCES_TOP_N]:
        lines.append("| %s | %s | %d |" % (name, _channel_of(name), sessions))
    if len(top_sources) > REACH_SOURCES_TOP_N:
        lines.append("- 残り%d行は省略した（合計には含む）" % (len(top_sources) - REACH_SOURCES_TOP_N))
    return _cap_text("\n".join(lines) + "\n", MONTHLY_INPUT_CHAR_CAP)


def _gsc_by_page(start, end):
    """gsc.search_analytics_by_page（--limit 100）を呼び、(slug→行, 契約JSONそのまま, 問題 or None)。"""
    payload, raw, err = _run_metrics(["gsc", "--operation", "gsc.search_analytics_by_page", "--since", start,
                                      "--until", end, "--limit", "100"])
    problem = _payload_problem(payload, err)
    rows = {}
    if not problem:
        for rec in _series(payload):
            rows[rec.get("page") or ""] = rec
    return rows, payload, raw, problem


def _build_reach_pages(year_month, ga4_payload, gsc_rows, gsc_period):
    """(a) reach-pages.md: 記事別の GA4 sessions（対象月と前月）と GSC 記事別（28日と、その前の28日）。"""
    prev_month = _previous_month(year_month)
    p_start, p_end = _monthly_period(prev_month)
    lines = ["# 記事別の到達数（gateway が自動生成・GA4 は %s と %s、GSC は %s〜%s とその前の28日）"
             % (year_month, prev_month, gsc_period[0], gsc_period[1]), ""]
    prev_payload, _raw, err = _run_metrics(["ga4", "--operation", "ga4.page_traffic", "--since", p_start,
                                            "--until", p_end, "--limit", "100"])
    problems = [("当月", _payload_problem(ga4_payload, None)), ("前月", _payload_problem(prev_payload, err))]

    def sessions_by_slug(payload):
        result = {}
        for rec in _series(payload):
            slug = _slug_from_page_path(rec.get("page_path"))
            if slug:
                result[slug] = result.get(slug, 0) + (rec.get("sessions") or 0)
        return result

    cur = sessions_by_slug(ga4_payload) if not problems[0][1] else {}
    prev = sessions_by_slug(prev_payload) if not problems[1][1] else {}
    g_end = datetime.strptime(gsc_period[0], "%Y-%m-%d") - timedelta(days=1)
    g_prev_period = ((g_end - timedelta(days=27)).strftime("%Y-%m-%d"), g_end.strftime("%Y-%m-%d"))
    gsc_prev, _p, _r, gsc_prev_problem = _gsc_by_page(*g_prev_period)

    def gsc_by_slug(rows):
        return {_slug_from_url(page): rec for page, rec in rows.items() if _slug_from_url(page)}

    g_cur, g_prev = gsc_by_slug(gsc_rows), gsc_by_slug(gsc_prev)
    new_slugs = {slug for slug, _path, date_str in
                 [t for posts in _posts_by_category().values() for t in posts]
                 if date_str.startswith(year_month)}
    for label, problem in problems:
        if problem:
            lines.append("- GA4 %s の ga4.page_traffic を取得できなかった: %s" % (label, problem))
    if gsc_prev_problem:
        lines.append("- GSC の前の28日（%s〜%s）を取得できなかった: %s" % (g_prev_period + (gsc_prev_problem,)))
    lines.append("- 合計（GA4 /posts/ の sessions）: 当月 %d（%d記事）／前月 %d（%d記事）%s" % (
        sum(cur.values()), len(cur), sum(prev.values()), len(prev),
        "（--limit 100 に達しており下限値）" if _lower_bound(ga4_payload) or _lower_bound(prev_payload) else ""))
    lines.append("- 前月の行が無い記事: %d件（うち当月公開 %d件）" % (
        sum(1 for s in cur if s not in prev), sum(1 for s in cur if s not in prev and s in new_slugs)))
    lines.append("- 合計（GSC 記事ページ・上位100ページの範囲）: 表示 %d→%d・クリック %d→%d（前の28日→28日）" % (
        sum(r.get("impressions") or 0 for r in g_prev.values()), sum(r.get("impressions") or 0 for r in g_cur.values()),
        sum(r.get("clicks") or 0 for r in g_prev.values()), sum(r.get("clicks") or 0 for r in g_cur.values())))

    diffs = [(cur.get(s, 0) - prev.get(s, 0), s) for s in set(cur) | set(prev)]

    def table(title, ranked):
        out = ["", "## %s（GA4 sessions の前月比の差・上位%d）" % (title, REACH_PAGES_TOP_N), "",
               "| slug | 当月 | 前月 | 差 | GSC表示 28日 | 前の28日 | 当月公開 |", "|---|---|---|---|---|---|---|"]
        for diff, slug in ranked[:REACH_PAGES_TOP_N]:
            out.append("| %s | %d | %d | %s | %s | %s | %s |" % (
                slug, cur.get(slug, 0), prev.get(slug, 0), _signed(diff),
                _fmt_int((g_cur.get(slug) or {}).get("impressions")), _fmt_int((g_prev.get(slug) or {}).get("impressions")),
                "○" if slug in new_slugs else ""))
        return out

    lines += table("伸びた記事", sorted([d for d in diffs if d[0] > 0], key=lambda d: (-d[0], d[1])))
    lines += table("落ちた記事", sorted([d for d in diffs if d[0] < 0], key=lambda d: (d[0], d[1])))
    return _cap_text("\n".join(lines) + "\n", MONTHLY_INPUT_CHAR_CAP)


def _busy_slugs(input_dir):
    """実行中・実装待ちの実験の範囲にある slug（experiments-status.json の range の slug=）。"""
    try:
        status = json.loads((input_dir / "experiments-status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    slugs = set()
    for key in ("experiments", "pending_rules"):
        for exp in status.get(key) or []:
            if isinstance(exp, dict):
                for m in RANGE_SLUG_RE.finditer(exp.get("range") or ""):
                    slugs.update(s for s in m.group(1).split(",") if s)
    return slugs


def _open_month_slugs(tasks_path=TASKS_MD_PATH):
    """docs/tasks.md「## 今月」節の未完了行の slug（行末の「（slug・category）」）。"""
    try:
        lines = tasks_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    slugs, inside = set(), False
    for line in lines:
        if line.startswith("## "):
            inside = line.strip() == "## 今月"
            continue
        if inside and line.strip().startswith("- [ ]"):
            found = MONTH_ROW_SLUG_RE.findall(line)
            if found:
                slugs.add(found[-1])
    return slugs


def _post_title_desc(slug):
    fm = _read_frontmatter(CONTENT_POSTS_DIR / ("%s.md" % slug))
    return (fm.get("title") or "").strip("\"'"), (fm.get("description") or "").strip("\"'")


def _build_ctr_candidates(gsc_rows, gsc_period, input_dir):
    """(c) ctr-candidates.md: CTR改修の候補（D1）を機械で抽出する。"""
    busy, open_slugs = _busy_slugs(input_dir), _open_month_slugs()
    lines = ["# 検索CTR改修の候補（gateway が機械で抽出・gsc-page-28d.json %s〜%s）" % gsc_period, ""]
    matched = []
    for page, rec in gsc_rows.items():
        slug = _slug_from_url(page)
        ctr, pos, imp = rec.get("ctr"), rec.get("position"), rec.get("impressions") or 0
        if (slug and imp >= CTR_MIN_IMPRESSIONS and isinstance(ctr, (int, float)) and ctr < CTR_MAX
                and isinstance(pos, (int, float)) and pos <= CTR_MAX_POSITION):
            matched.append((slug, rec))
    kept = [(s, r) for s, r in matched if s not in busy and s not in open_slugs]
    lines.append("- 条件: 表示 %d 以上・CTR %s 未満・平均順位 %d 以内の記事ページ。該当 %d件（除外前 %d件）"
                 % (CTR_MIN_IMPRESSIONS, _pct(CTR_MAX), CTR_MAX_POSITION, len(kept), len(matched)))
    lines.append("- 除外した slug: 実行中の実験の範囲 %s ／ docs/tasks.md「## 今月」節の未完了行 %s" % (
        "・".join(sorted(busy & {s for s, _ in matched})) or "なし",
        "・".join(sorted(open_slugs & {s for s, _ in matched})) or "なし"))
    lines += ["", "| slug | 表示 | クリック | CTR | 順位 | 今の title ／ description |", "|---|---|---|---|---|---|"]
    for slug, rec in sorted(kept, key=lambda t: -(t[1].get("impressions") or 0))[:CTR_CANDIDATES_MAX]:
        title, desc = _post_title_desc(slug)
        lines.append("| %s | %d | %d | %s | %.1f | %s ／ %s |" % (
            slug, rec.get("impressions") or 0, rec.get("clicks") or 0, _pct(rec.get("ctr")),
            rec.get("position") or 0, title.replace("|", "/"), desc.replace("|", "/")))
    if len(kept) > CTR_CANDIDATES_MAX:
        lines.append("- 残り%d件は省略した（表示の少ない順）" % (len(kept) - CTR_CANDIDATES_MAX))
    return _cap_text("\n".join(lines) + "\n", MONTHLY_INPUT_CHAR_CAP)


def _build_query_gaps(gsc_period, page_impressions_total):
    """(c) query-gaps.md: 語ごとの最上位のページ・順位・表示（D2・新しい題材の材料）。"""
    lines = ["# 検索語と最上位のページ（gateway が自動生成・gsc.search_analytics_by_query_page %s〜%s）"
             % gsc_period, ""]
    payload, _raw, err = _run_metrics(["gsc", "--operation", "gsc.search_analytics_by_query_page",
                                       "--since", gsc_period[0], "--until", gsc_period[1], "--limit", "100"])
    problem = _payload_problem(payload, err)
    if problem:
        lines.append("- 取得できなかった: %s" % problem)
        return "\n".join(lines) + "\n"
    series = _series(payload)
    by_query = {}
    for rec in series:
        q = rec.get("query") or ""
        agg = by_query.setdefault(q, {"impressions": 0, "clicks": 0, "top": None})
        agg["impressions"] += rec.get("impressions") or 0
        agg["clicks"] += rec.get("clicks") or 0
        if agg["top"] is None or (rec.get("impressions") or 0) > (agg["top"].get("impressions") or 0):
            agg["top"] = rec
    shown = sum(a["impressions"] for a in by_query.values())
    lines.append("- 合計: 取得 %d行・語 %d件・表示 %d（記事ページ別の表示合計 %d の %s。匿名化された語は API に出ない）%s" % (
        len(series), len(by_query), shown, page_impressions_total,
        _pct(shown / page_impressions_total) if page_impressions_total else "-",
        "・--limit に達しており下限値" if _lower_bound(payload) else ""))
    lines.append("- 表示 %d 以上の語を表示の多い順に最大%d語。最上位のページ＝その語で表示が最も多いページ。"
                 "記事一覧（slug と title）は rg -n \"^title:\" site/src/content/posts で読む"
                 % (QUERY_GAPS_MIN_IMPRESSIONS, QUERY_GAPS_MAX_ROWS))
    lines += ["", "| 語 | 表示 | クリック | 最上位のページ | 順位 | 記事ページか |", "|---|---|---|---|---|---|"]
    ranked = sorted(((q, a) for q, a in by_query.items() if a["impressions"] >= QUERY_GAPS_MIN_IMPRESSIONS),
                    key=lambda t: (-t[1]["impressions"], t[0]))
    for q, a in ranked[:QUERY_GAPS_MAX_ROWS]:
        page = (a["top"].get("page") or "").replace(SITE_URL_PREFIX, "")
        lines.append("| %s | %d | %d | %s | %.1f | %s |" % (
            q.replace("|", "/"), a["impressions"], a["clicks"], page, a["top"].get("position") or 0,
            "記事" if _slug_from_url(page) else "記事以外"))
    if len(ranked) > QUERY_GAPS_MAX_ROWS:
        lines.append("- 残り%d語は省略した" % (len(ranked) - QUERY_GAPS_MAX_ROWS))
    return _cap_text("\n".join(lines) + "\n", MONTHLY_INPUT_CHAR_CAP)


def _read_queue_ledger(path):
    """data/monthly-queue.tsv（書き手は add-monthly-tasks.py --adopt だけ・D5）を行の辞書のリストで返す。
    無ければ None。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    rows = [line.split("\t") for line in text.splitlines() if line.strip()]
    if not rows:
        return []
    header = rows[0]
    return [dict(zip(header, r)) for r in rows[1:] if len(r) == len(header)]


def _queue_done_date(row):
    """作業キューの行の完了日（D5・台帳には書かず導き出す）。新規記事執筆は記事の date（published のとき）、
    それ以外は site/ の git log で、その記事を採用日以後に初めて変えたコミットの日。無ければ None。"""
    slug, adopted = row.get("slug") or "", row.get("採用日") or ""
    path = CONTENT_POSTS_DIR / ("%s.md" % slug)
    if row.get("タグ") == "新規記事執筆":
        fm = _read_frontmatter(path)
        return fm.get("date") if fm.get("status") == "published" else None
    try:
        proc = subprocess.run(
            ["git", "-C", str(SITE_DIR), "log", "--reverse", "--since=%s 00:00:00" % adopted,
             "--format=%ad", "--date=short", "--", "src/content/posts/%s.md" % slug],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    dates = [l.strip() for l in proc.stdout.splitlines() if l.strip() >= adopted]
    return dates[0] if dates else None


def _fmt_page_metrics(rec):
    if rec is None:
        return "上位100ページ外"
    return "表示%d・クリック%d・CTR %s・順位%.1f" % (rec.get("impressions") or 0, rec.get("clicks") or 0,
                                               _pct(rec.get("ctr")), rec.get("position") or 0)


def _build_prev_queue_results(year_month, ledger_path=None, today=None):
    """(e) prev-queue-results.md: 前月の監査から採用した作業キューの、完了日と前後の GSC ページ指標（D5）。
    対象は監査パスが growth/outputs/monthly-<対象月の前月>/audit.md の行。完了日の前後に同じ日数
    （PREV_QUEUE_WINDOW_DAYS まで）をとり、完了後の日数が PREV_QUEUE_MIN_DAYS に満たなければ判定不能とする。"""
    ledger_path = ledger_path or MONTHLY_QUEUE_LEDGER
    prev_month = _previous_month(year_month)
    audit_rel = "growth/outputs/monthly-%s/audit.md" % prev_month
    lines = ["# 前月の作業キューの結果（gateway が自動生成・台帳 %s・対象は監査パス %s の行）"
             % (_rel(ledger_path), audit_rel), ""]
    rows = _read_queue_ledger(ledger_path)
    if not rows:
        lines.append("- 対象なし（台帳開始前）")
        return "\n".join(lines) + "\n"
    targets = [r for r in rows if r.get("監査パス") == audit_rel]
    if not targets:
        lines.append("- 対象なし（前月の採用なし・台帳 %d行）" % len(rows))
        return "\n".join(lines) + "\n"
    today_dt = datetime.strptime(today, "%Y-%m-%d") if today else datetime.now()
    data_end = today_dt - timedelta(days=GSC_LAG_DAYS)
    lines.append("- 指標は gsc.search_analytics_by_page（--limit 100）の、その記事ページの行。完了日の前後に同じ日数"
                 "（最大%d日・GSC の遅れを見て %s まで）をとる。完了後が%d日に満たない・未完了なら判定不能"
                 % (PREV_QUEUE_WINDOW_DAYS, data_end.strftime("%Y-%m-%d"), PREV_QUEUE_MIN_DAYS))
    lines += ["", "| M番号 | タグ | slug | 対象指標 | 採用日 | 完了日 | 期間 | 前 | 後 | 判定の材料 |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for row in targets:
        done = _queue_done_date(row)
        head = "| %s | %s | %s | %s | %s | %s |" % (row.get("M番号"), row.get("タグ"), row.get("slug"),
                                                  row.get("対象指標"), row.get("採用日"), done or "未完了")
        if not done:
            lines.append("%s - | - | - | 判定不能（未完了） |" % head)
            continue
        done_dt = datetime.strptime(done, "%Y-%m-%d")
        span = min(PREV_QUEUE_WINDOW_DAYS, (data_end - done_dt).days)
        if span < PREV_QUEUE_MIN_DAYS:
            lines.append("%s 完了後%d日 | - | - | 判定不能（期間不足・%d日に満たない） |"
                         % (head, max(span, 0), PREV_QUEUE_MIN_DAYS))
            continue
        before = ((done_dt - timedelta(days=span)).strftime("%Y-%m-%d"), (done_dt - timedelta(days=1)).strftime("%Y-%m-%d"))
        after = ((done_dt + timedelta(days=1)).strftime("%Y-%m-%d"), (done_dt + timedelta(days=span)).strftime("%Y-%m-%d"))
        page = "%s/posts/%s/" % (SITE_URL_PREFIX, row.get("slug"))
        recs, problems = [], []
        for start, end in (before, after):
            got, _p, _r, problem = _gsc_by_page(start, end)
            recs.append(got.get(page))
            if problem:
                problems.append("%s〜%s 取得失敗: %s" % (start, end, problem))
        new_article = row.get("タグ") == "新規記事執筆"
        note = "；".join(problems) or ("新規記事（前は公開前）" if new_article else "前後の差を対象指標で見る")
        lines.append("%s 前後各%d日（前 %s〜%s／後 %s〜%s） | %s | %s | %s |" % (
            head, span, before[0], before[1], after[0], after[1],
            "-" if new_article else _fmt_page_metrics(recs[0]), _fmt_page_metrics(recs[1]), note))
    return _cap_text("\n".join(lines) + "\n", MONTHLY_INPUT_CHAR_CAP)


def _latest_weekly_sns(month_end):
    """週の開始日が month_end 以前の週次入力のうち、sns.md がある最新の週のパス（D8）。無ければ None。"""
    found = []
    for d in GROWTH_INPUTS_DIR.iterdir() if GROWTH_INPUTS_DIR.is_dir() else []:
        m = WEEK_LABEL_RE.match(d.name)
        if not m or not (d / "sns.md").is_file():
            continue
        monday = datetime.strptime("%s-W%s-1" % (m.group(1), m.group(2)), "%G-W%V-%u").strftime("%Y-%m-%d")
        if monday <= month_end:
            found.append((monday, d / "sns.md"))
    return max(found)[1] if found else None


MONTHLY_INPUT_FILES = ("reach-channels.md", "reach-pages.md", "ctr-candidates.md", "query-gaps.md",
                       "prev-queue-results.md")


def _prepare_monthly_inputs(input_dir, year_month):
    """月次の入力を growth/inputs/monthly-<対象月>/ へ置く（失敗しても続行する）。
    - 実験の状態（S-0027 ②）: experiments.py measure の3つの JSON（週末日=対象月の末日）
    - gsc-page-28d.json（対象月の末日で終わる28日・契約JSONを加工せず保存）
    - ga4-page-traffic.json（対象月のページ別・--limit 100。区切りPのサンプル選びが読む・D8）
    - sns.md（直近の週次の複製・D8。無ければ置かない）
    - MONTHLY_INPUT_FILES の md（(a) 到達数・(c) CTR改修の候補と題材の材料・(e) 前月の作業キューの結果）
    戻り値: [{"path", "chars"}]（新しい md の字数。--dry-run と成功時 JSON に載せる）"""
    input_dir.mkdir(parents=True, exist_ok=True)
    month_start, month_end = _monthly_period(year_month)
    _prepare_experiment_inputs(input_dir, month_end)
    gsc_start = (datetime.strptime(month_end, "%Y-%m-%d") - timedelta(days=27)).strftime("%Y-%m-%d")
    gsc_rows, _payload, raw, problem = _gsc_by_page(gsc_start, month_end)
    if problem:
        eprint("【注意】gsc-page-28d.json（%s〜%s）の取得に問題があります: %s" % (gsc_start, month_end, problem))
    (input_dir / "gsc-page-28d.json").write_text(raw or "{}", encoding="utf-8")
    ga4_payload, ga4_raw, ga4_err = _run_metrics(["ga4", "--operation", "ga4.page_traffic", "--since", month_start,
                                                  "--until", month_end, "--limit", "100"])
    if _payload_problem(ga4_payload, ga4_err):
        eprint("【注意】ga4-page-traffic.json の取得に問題があります: %s" % _payload_problem(ga4_payload, ga4_err))
    (input_dir / "ga4-page-traffic.json").write_text(ga4_raw or "{}", encoding="utf-8")
    sns = _latest_weekly_sns(month_end)
    if sns is not None:
        shutil.copyfile(sns, input_dir / "sns.md")
    elif (input_dir / "sns.md").is_file():
        (input_dir / "sns.md").unlink()

    _write_article_diffs(input_dir, year_month)

    page_total = sum(r.get("impressions") or 0 for p, r in gsc_rows.items() if _slug_from_url(p))
    texts = {
        "reach-channels.md": _build_reach_channels(year_month),
        "reach-pages.md": _build_reach_pages(year_month, ga4_payload if not ga4_err else None,
                                             gsc_rows, (gsc_start, month_end)),
        "ctr-candidates.md": _build_ctr_candidates(gsc_rows, (gsc_start, month_end), input_dir),
        "query-gaps.md": _build_query_gaps((gsc_start, month_end), page_total),
        "prev-queue-results.md": _build_prev_queue_results(year_month),
    }
    files = []
    for name in MONTHLY_INPUT_FILES:
        path = input_dir / name
        path.write_text(texts[name], encoding="utf-8")
        files.append({"path": _rel(path), "chars": len(texts[name])})
    files.append({"path": _rel(input_dir / "sns.md"), "chars": _text_len(input_dir / "sns.md"),
                  "note": "複製元 %s" % (_rel(sns) if sns else "なし（直近の週次に sns.md が無い）")})
    return files


def _run_judge_due(until_date, status_path):
    """experiments.py judge-due を呼び、結果を成功時 JSON の judge_due 用に返す（S-0027 ②）。
    失敗しても監査の成否は変えない（【注意】を出して ok=false で返す）。"""
    cmd = [sys.executable, str(EXPERIMENTS_SCRIPT), "judge-due", "--week-end", until_date]
    if status_path.is_file():
        cmd += ["--status", str(status_path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=METRICS_TIMEOUT_SEC, cwd=str(PROJECT_ROOT))
    except (OSError, subprocess.SubprocessError) as exc:
        eprint("【注意】experiments.py judge-due を実行できませんでした: %s" % type(exc).__name__)
        return {"ok": False, "returncode": None, "lines": [], "rule_revert_needed": [],
                "error": type(exc).__name__}
    lines = [l for l in (proc.stdout or "").splitlines() if l.strip()]
    result = {"ok": proc.returncode == 0, "returncode": proc.returncode, "lines": lines,
              "rule_revert_needed": [l.split()[1] for l in lines
                                     if l.startswith("RULE_REVERT_NEEDED ") and len(l.split()) > 1]}
    if proc.returncode != 0:
        result["error"] = (proc.stderr or "").strip()[-300:]
        eprint("【注意】experiments.py judge-due が失敗しました（rc=%s）: %s" % (proc.returncode, result["error"]))
    return result


# --- 監査範囲の機械集計（ロールアウトログから数える）---------------------------------


def _scan_rollout(thread_id):
    """thread_id の rollout を読み、truncated・view_image・切り詰めた呼び出しのパス・呼び出し一覧を返す。
    数え方は従来の _count_rollout_signals と同じ（そちらはこの関数の結果から数を返すだけ）。
    """
    result = {"found": False, "truncated": 0, "view_image": 0, "truncated_files": [],
              "truncated_call_idx": [], "calls": []}
    if not thread_id:
        return result
    matches = list(CODEX_SESSIONS_DIR.rglob("*-%s.jsonl" % thread_id))
    if not matches:
        return result
    result["found"] = True
    calls = {}
    try:
        with open(matches[0], "r", encoding="utf-8", errors="replace") as fh:
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
                    count = 0
                    for item in payload.get("output") or []:
                        text = item.get("text") if isinstance(item, dict) else None
                        if isinstance(text, str):
                            count += _count_truncated_lines(text)
                    if count:
                        result["truncated"] += count
                        call = calls.get(payload.get("call_id"))
                        if call is not None:
                            call["truncated"] = True
                            result["truncated_files"].append(_paths_in_call(call["text"]))
                            result["truncated_call_idx"].append(call["idx"])
                        else:
                            result["truncated_files"].append([])
                            result["truncated_call_idx"].append(None)
                elif ptype in ("custom_tool_call", "function_call", "local_shell_call"):
                    name = payload.get("name") or ""
                    call_text = payload.get("input")
                    if not isinstance(call_text, str):
                        call_text = payload.get("arguments") or ""
                    if not isinstance(call_text, str):
                        call_text = ""
                    if name == "view_image" or _VIEW_IMAGE_CALL_RE.search(call_text):
                        result["view_image"] += 1
                    entry = {"text": call_text, "truncated": False, "idx": len(result["calls"])}
                    calls[payload.get("call_id")] = entry
                    result["calls"].append(entry)
    except OSError:
        return {"found": False, "truncated": 0, "view_image": 0, "truncated_files": [],
                "truncated_call_idx": [], "calls": []}
    return result


def _paths_in_call(call_text):
    """呼び出しの文字列から、拡張子つきのASCIIパスを重複なしで返す（二重にエスケープされた \\ は / に直す）。"""
    text = call_text.replace("\\\\", "/").replace("\\", "/")
    seen = []
    for m in CALL_PATH_RE.finditer(text):
        path = m.group(0).strip("./")
        if path and path not in seen:
            seen.append(path)
    return seen


def _part_target_paths(part):
    """区切りの対象一覧（lines）から、対象のパス（行頭の "- " 直後から、空白・「【」・全角の「（」の手前まで）を返す。"""
    paths = []
    for line in part.get("lines") or []:
        m = re.match(r"^\s*-\s+([^\s【（]+)", line)
        if m and "/" in m.group(1):
            paths.append(m.group(1))
    return paths


def _scope_row(name, scan, part=None):
    """区切り1つ分の監査範囲の行。scan が None（ログなし）なら不明の行。"""
    if scan is None or not scan["found"]:
        return {"name": name, "known": False}
    names = []
    call_idx = scan.get("truncated_call_idx") or [None] * len(scan["truncated_files"])
    for group, idx in zip(scan["truncated_files"], call_idx):
        for p in group:
            if p in names:
                continue
            # 切り詰めのあとに、切り詰めの無い呼び出しに同じパスが現れたら、読み直して全文を読めたとみなして外す
            reread = idx is not None and any(
                not call["truncated"] and call["idx"] > idx
                and p in call["text"].replace("\\\\", "/").replace("\\", "/")
                for call in scan["calls"])
            if not reread:
                names.append(p)
    unknown_count = sum(1 for g in scan["truncated_files"] if not g)
    read = total = None
    if part is not None:
        targets = _part_target_paths(part)
        total = len(targets)
        read = 0
        for t in targets:
            base = t.replace("\\", "/")
            for call in scan["calls"]:
                text = call["text"].replace("\\\\", "/").replace("\\", "/")
                if not call["truncated"] and base in text:
                    read += 1
                    break
    return {"name": name, "known": True, "truncated": scan["truncated"], "view_image": scan["view_image"],
            "files": names, "unknown_calls": unknown_count, "read": read, "total": total}


def _thread_id_from_log(log_path):
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                tid = extract_thread_id([line])
                if tid:
                    return tid
    except OSError:
        return None
    return None


def _find_step_log(label, ref_path):
    """実行ログ（tmp/codex-gateway/*-growth-audit-<label>.jsonl）のうち、出力ファイル ref_path の
    書き込み時刻より後（120秒の余裕）に終わっていない最新のものを返す。見つからなければ None。
    """
    try:
        ref_mtime = ref_path.stat().st_mtime
    except OSError:
        return None
    best = None
    for cand in sorted(LOG_DIR.glob("*-growth-audit-%s.jsonl" % label)):
        try:
            if cand.stat().st_mtime <= ref_mtime + 120:
                best = cand
        except OSError:
            continue
    return best


def _scan_from_log(label, ref_path):
    log_path = _find_step_log(label, ref_path)
    if log_path is None:
        return None
    return _scan_rollout(_thread_id_from_log(log_path))


def _scope_rows_from_logs(partitions, parts_dir, target):
    """実行ログだけから全区切り＋まとめの行を作る（render-only・スキップした区切り用）。"""
    rows = []
    for part in partitions:
        scan = _scan_from_log("part-%s" % part["name"], parts_dir / (part["name"] + ".md"))
        rows.append(_scope_row(part["name"], scan, part))
    rows.append(_scope_row("まとめ", _scan_from_log("summary", target)))
    return rows


def _format_scope_section(rows, sns_unobserved):
    """audit.md の「## 監査範囲」節（gateway が書く）。"""
    lines = ["## 監査範囲", "",
             "gateway が各区切り・まとめの実行ログ（Codex のロールアウト）から機械集計した。"
             "Codex の自己申告ではない。", "",
             "| 区切り | 読めた対象/対象総数 | truncated_outputs | view_image_calls | 切り詰めたファイル |",
             "|---|---|---|---|---|"]
    t_total = v_total = r_total = n_total = 0
    unknown_rows = []
    for row in rows:
        if not row["known"]:
            lines.append("| %s | 不明 | 不明 | 不明 | 不明（実行ログなし） |" % row["name"])
            unknown_rows.append(row["name"])
            continue
        t_total += row["truncated"]
        v_total += row["view_image"]
        if row["total"] is None:
            counted = "—"
        else:
            counted = "%d/%d" % (row["read"], row["total"])
            r_total += row["read"]
            n_total += row["total"]
        if row["truncated"] == 0:
            names = "なし"
        else:
            shown = row["files"][:SCOPE_NAMES_MAX]
            names = "、".join(shown) if shown else ""
            if len(row["files"]) > SCOPE_NAMES_MAX:
                names += " ほか%d件" % (len(row["files"]) - SCOPE_NAMES_MAX)
            if row["unknown_calls"]:
                names += ("、" if names else "") + "不明（%d呼び出し）" % row["unknown_calls"]
            if not names:
                names = "なし（切り詰めた分はすべて読み直して全文を読めた）"
        lines.append("| %s | %s | %d | %d | %s |" % (row["name"], counted, row["truncated"], row["view_image"], names))
    lines.append("| 合計 | %d/%d | %d | %d | |" % (r_total, n_total, t_total, v_total))
    lines += ["",
              "- 「読めた対象」は、ログ上でその対象のパスが、切り詰めの無い呼び出しに現れた件数。日本語のパスは"
              "ログ上で壊れて一致しないことがあり、その場合は読めていないと数える。",
              "- 切り詰めたファイルは、切り詰めの出た呼び出しのパスから拾い、そのあとに切り詰めの無い呼び出しへ"
              "現れたパス（読み直して全文を読めたもの）は外す。拾えないものは「不明」と書く。"]
    if unknown_rows:
        lines.append("- 実行ログが見つからず集計できなかった区切り: %s（合計に含めない）" % "・".join(unknown_rows))
    if sns_unobserved:
        lines.append("- SNSプロフィール未観察: sns.md の全項目が未評価のまま --skip-sns で続行した"
                     "（Pinterest・Threads・X のプロフィールは評価していない）")
    return "\n".join(lines) + "\n"


def _replace_scope_section(audit_text, section_text):
    """audit_text の「## 監査範囲」節を section_text に置き換える（無ければ末尾へ足す）。"""
    lines = audit_text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == "## 監査範囲":
            start = i
            break
    if start is None:
        return audit_text.rstrip("\n") + "\n\n" + section_text
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    head = "\n".join(lines[:start]).rstrip("\n")
    tail = "\n".join(lines[end:])
    out = (head + "\n\n" if head else "") + section_text
    if tail:
        out = out.rstrip("\n") + "\n\n" + tail + "\n"
    return out


def _write_weekly_artifact(payload_extra, kind, label, status, message, ascii_extra):
    """週次の dry-run・render-only: JSON の中身を tmp/codex-gateway/ へ UTF-8 で保存し、
    画面には英数字だけでファイルのパスと件数を出す（cp932 のコンソールで文字化けさせない）。
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    out_path = LOG_DIR / ("growth-audit-%s-%s.json" % (label, kind))
    body = {"status": status, "purpose": "growth-audit", "method": "exec", "message": message}
    body.update(payload_extra)
    out_path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    line = {"status": status, "kind": kind, "json_path": str(out_path)}
    line.update(ascii_extra)
    sys.stdout.write(json.dumps(line, ensure_ascii=True) + "\n")
    sys.stdout.flush()
    return out_path


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


def _weekly_r_items(since_date, until_date, input_items=None):
    """週次の区切りR（期間内に変更があった生成ルール・恒久アセットの変更・週次の入力）の材料を、
    1ファイル＝1アイテムで返す（D-0255・変更分のみに絞る扱いは2026-09-28）。変更の無い生成ルールは
    ここに入れない。
    """
    items = []
    rule_targets = [(display, changed) for display, changed
                     in _generation_rule_targets(since_date, until_date) if changed]
    for (display, _changed), line in zip(rule_targets, _format_generation_rule_lines(rule_targets)):
        items.append({"chars": _text_len(_rule_file_path(display)), "images": 0, "lines": [line]})

    asset_changes = _permanent_asset_changes(since_date, until_date)
    for rel, dist_candidates in asset_changes:
        lines = ["- site/%s" % rel]
        for d in dist_candidates:
            lines.append("  - 対応: site/%s" % d)
        items.append({"chars": _text_len(SITE_DIR / rel), "images": 0, "lines": lines})

    # 週次の入力（gateway が自動生成・D-0272）
    items.extend(input_items or [])
    return items


def _pin_objects(texts):
    """ピン投稿文ファイルの一覧から、照合用の生成物 [{kind, number, date, label}] を作る。"""
    objects = []
    for t in texts:
        m = PIN_FILENAME_DATE_RE.match(t.name)
        if not m:
            continue
        objects.append({"kind": "Pin", "number": int(m.group(2)), "date": m.group(1),
                        "label": "ピン%s（%s）" % (m.group(2), m.group(1))})
    return objects


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

    def close():
        partitions.append({"chars": cur_chars, "images": cur_images, "lines": cur_lines, "count": cur_count})

    for item in items:
        if cur_count and (cur_chars + item["chars"] > PARTITION_CHAR_CAP
                          or cur_images + item["images"] > PARTITION_IMAGE_CAP):
            close()
            cur_chars, cur_images, cur_lines, cur_count = 0, 0, [], 0
        cur_chars += item["chars"]
        cur_images += item["images"]
        cur_lines.extend(item["lines"])
        cur_count += 1
    if cur_count:
        close()
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


def _load_input_series(input_dir, name):
    """<input_dir>/<name>（gateway が保存した契約JSON）の series を読む。無い・status が ok でなければ None。"""
    path = input_dir / name
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if payload.get("status") != "ok":
        return None
    return ((payload.get("data") or {}).get("series")) or []


def _load_ga4_page_traffic_series(input_dir):
    """<input_dir>/ga4-page-traffic.json（gateway が月次の入力として保存した契約JSON・D8）を読む。"""
    return _load_input_series(input_dir, "ga4-page-traffic.json")


def _slug_from_page_path(page_path):
    m = re.match(r"^/posts/([^/]+)/?$", page_path or "")
    return m.group(1) if m else None


# 月次の区切り（2026-11-01・D9）: A=当月の記事（新しい記事は全文・更新した記事は当月の差分）、
# G=当月に変更があった生成ルール、S=当月に変更した恒久アセット＋検索表示の多いカテゴリページ1件、
# P=見本 MONTHLY_SAMPLE_MAX 本。品質の確認はこの範囲に絞り、公開前チェックが見ていることは
# 所見にしない（monthly-audit-part.md）。
MONTHLY_SAMPLE_MAX = 3
ARTICLE_DIFFS_DIRNAME = "article-diffs"


def _git_rev_before(stamp):
    try:
        proc = subprocess.run(["git", "-C", str(SITE_DIR), "rev-list", "-1", "--before=%s" % stamp, "HEAD"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout.strip()


def _monthly_article_split(year_month):
    """当月の記事（_posts_in_period）を (新しい記事, 更新した記事) の [(path, 理由)] に分ける。"""
    month_start, month_end = _monthly_period(year_month)
    new, updated = [], []
    for p, reason in _posts_in_period(month_start, month_end):
        (new if reason.startswith("date=") else updated).append((p, reason))
    return new, updated


def _write_article_diffs(input_dir, year_month):
    """更新した記事の、当月の差分（月初直前のコミット→末日までの最後のコミット）を
    <input_dir>/article-diffs/<slug>.diff へ書く。区切りAが読む。"""
    month_start, month_end = _monthly_period(year_month)
    out_dir = input_dir / ARTICLE_DIFFS_DIRNAME
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.diff"):
        old.unlink()
    base = _git_rev_before("%s 00:00:00" % month_start)
    last = _git_rev_before("%s 23:59:59" % month_end)
    for p, _reason in _monthly_article_split(year_month)[1]:
        text = ""
        if base and last:
            try:
                proc = subprocess.run(
                    ["git", "-C", str(SITE_DIR), "diff", "-U2", base, last, "--", "src/content/posts/%s" % p.name],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
                text = proc.stdout
            except (OSError, subprocess.SubprocessError):
                text = ""
        (out_dir / ("%s.diff" % p.stem)).write_text(text, encoding="utf-8")


def _monthly_a_items(target, year_month):
    """月次の区切りA（当月の記事）の材料を、記事1本＝1アイテムで返す。"""
    diffs_dir = _input_dir_for_output(target) / ARTICLE_DIFFS_DIRNAME
    new, updated = _monthly_article_split(year_month)
    items = []
    for p, reason in new:
        items.append({"chars": _text_len(p), "images": 0,
                      "lines": ["- site/src/content/posts/%s（新しい記事・%s・全文を読む）" % (p.name, reason)]})
    for p, reason in updated:
        diff = diffs_dir / ("%s.diff" % p.stem)
        chars = _text_len(diff)
        note = "当月の差分を読む。差分の前後の文脈が要るときだけ本文 site/src/content/posts/%s を開く" % p.name
        if not chars:
            note = "当月の差分が取れなかった（コミットに変更なし）。本文 site/src/content/posts/%s を読む" % p.name
            chars = _text_len(p)
        items.append({"chars": chars, "images": 0,
                      "lines": ["- %s（更新した記事・%s・%s）" % (_rel(diff), reason, note)]})
    return items


def _monthly_g_items(year_month):
    """月次の区切りG（当月に変更があった生成ルール）の材料を、1ファイル＝1アイテムで返す。"""
    month_start, month_end = _monthly_period(year_month)
    items = []
    for display, changed in _generation_rule_targets(month_start, month_end):
        if changed:
            items.append({"chars": _text_len(_rule_file_path(display)), "images": 0,
                          "lines": ["- %s【当月に変更あり・全文を読む】" % display]})
    return items


def _top_category_page(input_dir):
    """gsc-page-28d.json で表示が最も多いカテゴリページの dist のパス（site/ 起点）と、その理由。
    カテゴリページの行が無ければ、表示が最も多い記事のカテゴリのページ。"""
    series = _load_input_series(input_dir, "gsc-page-28d.json") or []
    best = None
    for rec in series:
        path = (rec.get("page") or "").replace(SITE_URL_PREFIX, "")
        m = re.match(r"^/category/([a-z0-9-]+)/(?:(\d+)/)?$", path)
        if m and (best is None or (rec.get("impressions") or 0) > best[0]):
            best = (rec.get("impressions") or 0, m.group(1), m.group(2))
    if best:
        sub = "%s/" % best[2] if best[2] else ""
        return "dist/category/%s/%sindex.html" % (best[1], sub), "gsc-page-28d.json で表示が最多のカテゴリページ（表示%d）" % best[0]
    for rec in sorted(series, key=lambda r: -(r.get("impressions") or 0)):
        slug = _slug_from_url(rec.get("page"))
        category = _read_frontmatter(CONTENT_POSTS_DIR / ("%s.md" % slug)).get("category") if slug else None
        if category:
            return "dist/category/%s/index.html" % category, "表示が最多の記事（%s）のカテゴリページ" % slug
    return None, "gsc-page-28d.json に使える行が無い"


def _monthly_s_items(target, year_month):
    """月次の区切りS（当月に変更した恒久アセット＋検索表示の多いカテゴリページ1件）の材料。"""
    month_start, month_end = _monthly_period(year_month)
    items = []
    for rel, dist_candidates in _permanent_asset_changes(month_start, month_end):
        lines = ["- site/%s【当月に変更あり】" % rel]
        for d in dist_candidates:
            lines.append("  - 対応: site/%s" % d)
        items.append({"chars": _text_len(SITE_DIR / rel), "images": 0, "lines": lines})
    page, how = _top_category_page(_input_dir_for_output(target))
    if page:
        lines = ["- site/%s（%s）" % (page, how), "  - （注）site/dist のビルド日時 %s" % _dist_built_at()]
        if not (SITE_DIR / page).is_file():
            lines.append("  - （注）site/%s が dist に無い" % page)
        items.append({"chars": _text_len(SITE_DIR / page), "images": 0, "lines": lines})
    return items


def _select_monthly_samples(posts_by_category, ga4_series, gsc_series=None, exclude=()):
    """見本を最大 MONTHLY_SAMPLE_MAX 本選ぶ（PV最多・検索表示最多・公開日最古の順。区切りAの記事は除く）。
    戻り値: [(category, slug, 理由)]"""
    exclude = set(exclude)
    category_of = {slug: category for category, posts in posts_by_category.items() for slug, _p, _d in posts}
    dates = {slug: date_str for posts in posts_by_category.values() for slug, _p, date_str in posts}

    def ranked(series, key, metric):
        totals = {}
        for row in series or []:
            slug = _slug_from_url(row.get(key))
            if slug in category_of:
                totals[slug] = totals.get(slug, 0) + (row.get(metric) or 0)
        return sorted(totals, key=lambda s: (-totals[s], s)), totals

    pv_order, pv = ranked(ga4_series, "page_path", "screenPageViews")
    imp_order, imp = ranked(gsc_series, "page", "impressions")
    oldest = sorted(category_of, key=lambda s: (dates.get(s) or "9999-99-99", s))
    picks = []
    for order, reason in ((pv_order, lambda s: "PV最多（%d）" % pv[s]),
                          (imp_order, lambda s: "検索表示最多（%d）" % imp[s]),
                          (oldest, lambda s: "公開日最古（%s）" % dates.get(s))):
        slug = next((s for s in order if s not in exclude and s not in {p[1] for p in picks}), None)
        if slug and len(picks) < MONTHLY_SAMPLE_MAX:
            picks.append((category_of[slug], slug, reason(slug)))
    return picks


def _monthly_p_items(target, year_month):
    """月次の区切りP（見本）の材料を、記事1本＝1アイテムで返す。"""
    input_dir = _input_dir_for_output(target)
    new, updated = _monthly_article_split(year_month)
    samples = _select_monthly_samples(_posts_by_category(), _load_ga4_page_traffic_series(input_dir),
                                      _load_input_series(input_dir, "gsc-page-28d.json"),
                                      exclude=[p.stem for p, _r in new + updated])
    return [{"chars": _text_len(CONTENT_POSTS_DIR / ("%s.md" % slug)), "images": 0,
             "lines": ["- [%s] %s（%s）: site/src/content/posts/%s.md" % (category, slug, reason, slug)]}
            for category, slug, reason in samples]


def _build_partitions(mode, since, until, month, target, weekly_inputs=None):
    """mode に応じて区切りの計画（各 {name, chars, images, lines, count}）を返す（D-0255）。"""
    if mode == "weekly":
        input_items = weekly_inputs["items"] if weekly_inputs else None
        return (_pack_items(_weekly_r_items(since, until, input_items), "R")
                + _pack_items(_weekly_o_items(since, until), "O"))
    if mode == "monthly":
        return (_pack_items(_monthly_a_items(target, month), "A")
                + _pack_items(_monthly_g_items(month), "G")
                + _pack_items(_monthly_s_items(target, month), "S")
                + _pack_items(_monthly_p_items(target, month), "P"))
    return []


def _has_sections(path, headers):
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return all(h in text for h in headers)


def _valid_partial_output(path, required_sections=REQUIRED_PART_SECTIONS):
    """区切りの出力が有効か（必須の節が揃っているか）。再開時にこれが真の区切りは飛ばす。"""
    return _has_sections(path, required_sections)


def _format_parts_reference(parts_dir, partitions):
    """まとめ用プロンプトの {{TARGETS}} へ差し込む、部分監査の出力一覧。"""
    lines = ["## 部分監査の出力一覧（すべて読む・%d件）" % len(partitions)]
    for part in partitions:
        lines.append("- %s" % _rel(parts_dir / (part["name"] + ".md")))
    return "\n".join(lines)


def _build_summary_prompt(prompt, parts_dir, partitions, since=None, until=None):
    """まとめのプロンプトを組み立てる。{{TARGETS}} には区切りの出力一覧、週次は対象期間を
    {{SINCE}}／{{UNTIL}} へ差し込む。
    """
    text = prompt.replace("{{TARGETS}}", _format_parts_reference(parts_dir, partitions))
    if since and until:
        text = text.replace("{{SINCE}}", since).replace("{{UNTIL}}", until)
    return text


def _emit_dry_run(purpose, method, target, parts_dir, partitions, mode="monthly",
                  weekly_inputs=None, sns_unobserved=False, monthly_inputs=None):
    plan = []
    part_sections = REQUIRED_PART_SECTIONS_BY_MODE.get(mode, REQUIRED_PART_SECTIONS)
    for part in partitions:
        part_path = parts_dir / (part["name"] + ".md")
        entry = {
            "name": part["name"], "target_count": part["count"],
            "chars": part["chars"], "images": part["images"],
            "skip": _valid_partial_output(part_path, part_sections),
        }
        if mode in ("weekly", "monthly"):
            entry["targets"] = list(part["lines"])
        plan.append(entry)
    skip_names = [p["name"] for p in plan if p["skip"]]
    extra = {"partitions": plan, "skip": skip_names}
    if mode == "monthly":
        extra["monthly_inputs"] = monthly_inputs or []
    if mode == "weekly":
        # 週次は JSON の中身を tmp/ へ UTF-8 で保存し、画面には英数字だけを出す（D-0272）。
        extra["artifact"] = str(target)
        extra["weekly_inputs"] = weekly_inputs["files"] if weekly_inputs else []
        extra["dist"] = weekly_inputs["dist"] if weekly_inputs else None
        extra["sns_unobserved_skipped"] = bool(sns_unobserved)
        _write_weekly_artifact(
            extra, "dry-run", target.parent.name, "dry_run",
            "区切り計画 %d件（スキップ%d件）: %s"
            % (len(plan), len(skip_names), "、".join(p["name"] for p in plan) or "なし"),
            {"partitions": len(plan), "skipped": len(skip_names), "inputs": len(extra["weekly_inputs"]),
             "targets": sum(len(p["targets"]) for p in plan), "skip_sns": bool(sns_unobserved)})
        return EXIT_OK
    emit("dry_run", purpose, method, str(target), None,
         "区切り計画 %d件（スキップ%d件）: %s"
         % (len(plan), len(skip_names), "、".join(p["name"] for p in plan) or "なし"),
         extra=extra)
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
    scan = _scan_rollout(thread_id)
    truncated, view_calls = scan["truncated"], scan["view_image"]
    token_usage = _rollout_last_token_usage(thread_id)
    ok, info = result["info"]
    return {
        "ok": ok, "info": info, "elapsed": int(time.time() - started_at),
        "log_path": result["log_path"], "model": result["model"],
        "timed_out": result["timed_out"], "truncated_outputs": truncated,
        "view_image_calls": view_calls, "token_usage": token_usage,
        "stderr": result["stderr"], "returncode": result["returncode"],
        "written_by": state["written_by"], "scan": scan,
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


def _render_part_prompt(template, part):
    return (template
            .replace("{{PART_NAME}}", part["name"])
            .replace("{{TARGETS}}", "\n".join(part["lines"])))


def _emit_render_only(purpose, method, target, render_dir, files, extra_info=None):
    extra = {"render_dir": str(render_dir), "files": files}
    if extra_info:
        extra.update(extra_info)
    emit("rendered", purpose, method, str(target), None,
         "プロンプトを %d件書き出しました（Codexは起動していません）: %s"
         % (len(files), render_dir),
         extra=extra)
    return EXIT_OK


def _render_audit_prompts(purpose, method, prompt_file, mode, target, parts_dir,
                          partitions, render_dir, weekly_inputs=None,
                          sns_unobserved=False, since=None, until=None):
    """全区切りの部分監査プロンプトと、まとめのプロンプトを置換済みで render_dir へ書く。

    Codex を起動しない（codex の有無も見ない）。区切りの出力ファイルが既にあるかどうかに
    関わらず全区切りを書く（growth/outputs/ へは何も書かない）。
    """
    prompt_path = Path(prompt_file)
    if not prompt_path.is_file():
        return fail(EXIT_PRECONDITION, purpose, method,
                    "--prompt-file が存在しません: %s" % prompt_path)
    prompt = prompt_path.read_text(encoding="utf-8")
    if not prompt.strip():
        return fail(EXIT_PRECONDITION, purpose, method,
                    "--prompt-file の内容が空です: %s" % prompt_path)
    part_prompt_path = PART_PROMPT_PATHS[mode]
    try:
        part_prompt_template = part_prompt_path.read_text(encoding="utf-8")
    except OSError as exc:
        return fail(EXIT_PRECONDITION, purpose, method,
                    "部分監査プロンプトを読み込めません: %s（%s）" % (part_prompt_path, exc))
    out_dir = Path(render_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for part in partitions:
        path = out_dir / ("part-%s.md" % part["name"])
        path.write_text(_render_part_prompt(part_prompt_template, part), encoding="utf-8")
        files.append(str(path))
    summary_path = out_dir / "summary.md"
    summary_path.write_text(
        _build_summary_prompt(prompt, parts_dir, partitions, since, until),
        encoding="utf-8")
    files.append(str(summary_path))
    if mode == "weekly":
        # 監査範囲は gateway が実行ログから機械集計する（D-0272）。Codex を起動しないこのモードでは、
        # 節だけの audit-scope.md と、target があればその「## 監査範囲」節を置き換えた
        # audit-with-scope.md を render_dir へ書く（growth/outputs/ へは何も書かない）。
        rows = _scope_rows_from_logs(partitions, parts_dir, target)
        section = _format_scope_section(rows, sns_unobserved)
        scope_path = out_dir / "audit-scope.md"
        scope_path.write_text(section, encoding="utf-8")
        files.append(str(scope_path))
        if target.is_file():
            replaced = out_dir / "audit-with-scope.md"
            replaced.write_text(_replace_scope_section(target.read_text(encoding="utf-8"), section),
                                encoding="utf-8")
            files.append(str(replaced))
        extra = {"artifact": str(target), "render_dir": str(out_dir), "files": files,
                 "weekly_inputs": weekly_inputs["files"] if weekly_inputs else [],
                 "dist": weekly_inputs["dist"] if weekly_inputs else None,
                 "sns_unobserved_skipped": bool(sns_unobserved), "scope_rows": rows}
        _write_weekly_artifact(
            extra, "render-only", target.parent.name, "rendered",
            "プロンプトを %d件書き出しました（Codexは起動していません）: %s" % (len(files), out_dir),
            {"files": len(files), "render_dir": str(out_dir),
             "inputs": len(extra["weekly_inputs"]), "skip_sns": bool(sns_unobserved)})
        return EXIT_OK
    return _emit_render_only(purpose, method, target, out_dir, files)


def run_growth_audit(purpose, prompt_file, output_file, model_override=None,
                      mode=None, since=None, until=None, month=None, dry_run=False,
                      render_only=None, only_part=None, skip_sns=False, skip_pin_check=False):
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
    if render_only and (dry_run or only_part):
        return fail(EXIT_PRECONDITION, purpose, method,
                    "--render-only は --dry-run・--only-part と同時に指定できません。")
    if dry_run and only_part:
        return fail(EXIT_PRECONDITION, purpose, method,
                    "--dry-run と --only-part は同時に指定できません。")
    effective_month = month
    if mode == "monthly" and not effective_month:
        effective_month = _previous_month(datetime.now().strftime("%Y-%m"))

    # 週次だけ（D-0272）: sns.md が未観察なら Codex を呼ぶ前に止まる（--skip-sns で続行し、
    # 監査範囲に記録する）。続けて入力 (a)〜(d) を gateway が作る。月次には何もしない。
    weekly_inputs = None
    sns_unobserved = False
    if mode == "weekly":
        input_dir = _input_dir_for_output(target)
        sns_unobserved, sns_reason = _sns_unobserved(input_dir)
        if sns_unobserved and not skip_sns:
            return fail(EXIT_PRECONDITION, purpose, method,
                        "SNSプロフィールが未観察のため Codex を呼ぶ前に停止しました（%s: %s）。"
                        "Chrome でプロフィールを観察して sns.md を更新するか、--skip-sns を付けて再実行してください。"
                        % (_rel(input_dir / "sns.md"), sns_reason))
        # ピン日次の取得完了の確認（対象週に PROCESSING の行が残れば止まる・--skip-pin-check で続行）
        pin_stop, pin_notes = _prepare_pins_daily_totals(input_dir, since, until, skip_pin_check)
        if pin_stop:
            return fail(EXIT_PRECONDITION, purpose, method,
                        "ピン日次の取得が終わっていないため Codex を呼ぶ前に停止しました。%s" % pin_stop)
        weekly_inputs = _prepare_weekly_inputs(input_dir, since, until, pin_notes)

    monthly_inputs = None
    if mode == "monthly":
        # 月次の入力（実験の状態・GSC・GA4・sns.md・到達数などの md）を区切りの計画より先に作る。
        # 区切りの計画が ga4-page-traffic.json・gsc-page-28d.json を読むため、--dry-run でも作る（2026-11-01）。
        monthly_inputs = _prepare_monthly_inputs(_input_dir_for_output(target), effective_month)

    partitions = _build_partitions(mode, since, until, effective_month, target, weekly_inputs)
    parts_dir = target.parent / "parts"
    part_sections = REQUIRED_PART_SECTIONS_BY_MODE[mode]
    summary_sections = REQUIRED_SUMMARY_SECTIONS_BY_MODE[mode]

    if dry_run:
        return _emit_dry_run(purpose, method, target, parts_dir, partitions, mode,
                             weekly_inputs, sns_unobserved, monthly_inputs)

    if render_only:
        return _render_audit_prompts(purpose, method, prompt_file, mode, target, parts_dir,
                                     partitions, render_only, weekly_inputs,
                                     sns_unobserved, since, until)

    if only_part:
        names = [p["name"] for p in partitions]
        if only_part not in names:
            return fail(EXIT_PRECONDITION, purpose, method,
                        "--only-part の区切り名が計画にありません: %s（計画: %s）"
                        % (only_part, "、".join(names) or "なし"))

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
    scan_by_part = {}

    run_partitions = [p for p in partitions if not only_part or p["name"] == only_part]
    for part in run_partitions:
        part_path = parts_dir / (part["name"] + ".md")
        # --only-part は明示指定なので、有効な出力が既にあっても実行して上書きする。
        if not only_part and _valid_partial_output(part_path, part_sections):
            eprint("区切り %s は有効な出力が既にあるため飛ばします: %s" % (part["name"], part_path))
            part_reports.append({"name": part["name"], "status": "skipped"})
            continue

        part_prompt = _render_part_prompt(part_prompt_template, part)
        build_cmd = _build_audit_cmd(real_exe, part_path, reasoning_effort, config_model)
        try:
            step = _run_one_audit_step(build_cmd, part_prompt, part_path, model_override,
                                       config_model, child_env, part_sections,
                                       "part-%s" % part["name"])
        except OSError as exc:
            return fail(EXIT_LAUNCH_FAILED, purpose, method,
                        "区切り %s の codex exec 起動に失敗しました: %s" % (part["name"], exc))

        truncated_total += step["truncated_outputs"]
        view_image_total += step["view_image_calls"]
        scan_by_part[part["name"]] = step["scan"]
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

    if only_part:
        # 区切り1つだけの実行（まとめは実行しない）。
        elapsed_total = int(time.time() - overall_started)
        emit("ok", purpose, method, str(parts_dir / (only_part + ".md")), None,
             "区切り %s のみ実行しました（まとめは実行していません） ／ 所要 %d秒 ／ reasoning effort: %s"
             " ／ truncated_outputs: %d ／ view_image_calls: %d"
             % (only_part, elapsed_total, reasoning_effort, truncated_total, view_image_total),
             extra={"elapsed_sec": elapsed_total, "timed_out": any_timed_out,
                    "truncated_outputs": truncated_total, "view_image_calls": view_image_total,
                    "reasoning_effort": reasoning_effort,
                    "token_usage": {"total": token_totals, "parts": token_by_part},
                    "parts": part_reports, "only_part": only_part})
        return EXIT_OK

    # 最後のまとめ（1回）: 全区切りの出力一覧を {{TARGETS}} へ、週次は対象期間も差し込む。
    summary_prompt = _build_summary_prompt(prompt, parts_dir, partitions, since, until)
    build_cmd = _build_audit_cmd(real_exe, target, reasoning_effort, config_model)
    try:
        summary_step = _run_one_audit_step(build_cmd, summary_prompt, target, model_override,
                                           config_model, child_env, summary_sections,
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

    if mode == "weekly":
        # 監査範囲の節は gateway が実行ログから書く。Codex が書いた節は置き換える（D-0272）。
        rows = []
        for part in partitions:
            scan = scan_by_part.get(part["name"])
            if scan is None:
                scan = _scan_from_log("part-%s" % part["name"], parts_dir / (part["name"] + ".md"))
            rows.append(_scope_row(part["name"], scan, part))
        rows.append(_scope_row("まとめ", summary_step["scan"]))
        section = _format_scope_section(rows, sns_unobserved)
        target.write_text(_replace_scope_section(target.read_text(encoding="utf-8"), section),
                          encoding="utf-8")

    # 週次は監査が有効と判定されたあとに、判定日が来た実験の判定案を台帳へ記録する（S-0027 ②）。
    judge_due = None
    if mode == "weekly":
        judge_due = _run_judge_due(until, _input_dir_for_output(target) / "experiments-status.json")

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
                "parts": part_reports, "judge_due": judge_due,
                **({"monthly_inputs": monthly_inputs} if mode == "monthly" else {})})
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
    parser.add_argument("--render-only", default=None, metavar="OUT_DIR",
                        help="growth-audit: Codexを起動せず、全区切りの部分監査プロンプトと"
                             "まとめのプロンプトを置換済みの状態で OUT_DIR へ書き出して終了する"
                             "（part-<区切り名>.md と summary.md・D-0265）")
    parser.add_argument("--skip-sns", action="store_true",
                        help="growth-audit --mode weekly: sns.md が全項目「未評価」でも止まらず続行する。"
                             "監査範囲に「SNSプロフィール未観察」と記録する（D-0272）")
    parser.add_argument("--skip-pin-check", action="store_true",
                        help="growth-audit --mode weekly: 対象週に data_status PROCESSING の行が残っていても"
                             "止まらず続行する。区切りRの入力一覧に注記を残す")
    parser.add_argument("--only-part", default=None, metavar="NAME",
                        help="growth-audit: 指定した区切り（例 R-1・O-2）だけを実行し、"
                             "まとめは実行しない。有効な出力が既にあっても実行して上書きする（D-0265）")
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
                                month=args.month, dry_run=args.dry_run,
                                render_only=args.render_only, only_part=args.only_part,
                                skip_sns=args.skip_sns, skip_pin_check=args.skip_pin_check)
    return run_exec(purpose, args.prompt_file, args.out_name, args.model)


if __name__ == "__main__":
    sys.exit(main())
