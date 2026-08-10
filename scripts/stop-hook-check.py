# -*- coding: utf-8 -*-
r"""Stopフック用: セッション終了時に check-doc-governance.py を実行し、
【警告】があれば1回だけ会話の継続を強制する。あわせて sync-to-gdrive.py で
運営5ファイルをGoogleドキュメントへ同期する（D-0064）。

さらに、直前のアシスタント応答（last_assistant_message）に固定サマリーの見出し
「【オーナーが今やること】」が含まれるのにトークン消費量の出力がまだ含まれていない
場合、session-token-usage.py を実行しその出力を強制的に追記する（D-0066）。
これによりAI自身がsession-token-usage.pyを手動実行する必要はなくなる
（CLAUDE.md 5節ステップ6参照）。見出し検知は has_summary_heading_in() が担い、
装飾記号（#・**等）の種類を問わない部分一致判定を行う（D-0081。経緯はD-0071参照）。
session-token-usage.py のサブプロセス起動時には cwd=PROJECT_ROOT を明示的に指定する
（D-0084）。同スクリプト自体もD-0084で__file__基準の絶対パス解決へ変更済みだが、
呼び出し側でも二重にcwdを固定し、将来的な変更で再びos.getcwd()等が使われても
影響を受けないようにする。

Stopフックのcommandから、hook入力JSON（stdin）を受け取って呼ばれる想定。
stop_hook_active が true の場合（=このフック自身が直前に継続を強制した
2回目以降のStop発火）は無条件で停止を許可し、無限ループを避ける。この判定は
governance判定・トークン追記判定のどちらよりも前に行う。

check-doc-governance.py は【警告】が1件でもあれば終了コード1、
それ以外（【通知】のみ・異常なし・初回実行）は終了コード0を返す
（同スクリプトのdocstring・sys.exit(1 if warnings else 0)を参照）。

governance警告とトークン追記条件が同一ターンで両方成立した場合、block()は1回のみ
呼び出し、reasonはgovernance警告の内容を先に、トークン消費量の内容を後ろに連結する。

sync-to-gdrive.py の失敗はStopフック自体を止めない（同期失敗で毎回
セッションが止まる事態を避けるため）。失敗時はコンソールに警告を出すのみ。

さらに、site/リポジトリに未commitの変更（変更・未追跡ファイル）が残っていないかを
`git status --porcelain` で検知する（D-0080）。記事のpublished化・Pin画像追加に伴う
正常な差分（site/src/content/posts/配下・site/public/images/配下）は誤検知を避けるため
対象から除外する。

D-0080は当初この検知結果をprint()で平文出力する「情報提供のみ」方式だったが、
①平文出力はAIの会話コンテキストへ届く経路がなく実際には機能していなかったこと、
②block()のJSONと同一stdoutに平文が混在するとトークン追記機構（D-0066・D-0081）の
JSONパースを壊すリスクがあることが判明したため、検知結果をblock()のreasonへ統合する
方式へ変更した（D-0082）。

■ stdout出力の規律（D-0082）
このスクリプトがstdoutへ書き出してよいのは block() による1本のJSONのみとする。
平文をstdoutへ出してはならない（人間向けの警告・エラーはすべてstderrへ出す）。
子プロセスの出力は subprocess.run(capture_output=True) で捕捉しており、
このスクリプトのstdoutへは素通ししない。

■ reason文言の規律（D-0082補足・2026-08-10／D-0096で対象を3箇所へ拡大）
Stopフックのblock()はAIの直前の応答を編集できず、新しいターンを差し込む仕組みである。
そのため「【未決定事項】欄に記載してください」等とだけ書くと、AIが固定サマリー全体を
書き直して2重表示になる（2026-08-10のpin100セッションで実測確認）。トークン追記・
未commit検知・ガバナンス警告のreasonは、いずれも冒頭で「固定サマリー全体を再出力しない
こと。直前の応答に続けて、該当分のみを出力すること」を明示する。この前置き文は
NO_RESUMMARY_PREFIX としてモジュール先頭で1箇所だけ定義し、3箇所すべてがそれを参照する
（D-0096。当初はトークン追記・未commit検知の2箇所にしか前置きが入っておらず、
ガバナンス警告が単独で成立した場合に元の2重表示問題が再発する欠陥があったため）。

■ block()の呼び出し規律（D-0082）
ガバナンス警告・トークン未出力・未commit検知が同時に成立しても、block()の呼び出しは
1回のみ・出力されるJSONも1つのみとし、reasonに全項目をまとめて含める。
継続強制の回数制御は既存の stop_hook_active 方式（1回だけ強制・2回目以降は無条件で
終了を許可）をそのまま使い、新しい制御方式は作らない。

使い方:
  python site/scripts/stop-hook-check.py < hook入力JSON
"""

import json
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GOVERNANCE_SCRIPT = os.path.join(SCRIPT_DIR, "check-doc-governance.py")
GDRIVE_SYNC_SCRIPT = os.path.join(SCRIPT_DIR, "sync-to-gdrive.py")
TOKEN_USAGE_SCRIPT = os.path.join(SCRIPT_DIR, "session-token-usage.py")
SITE_ROOT = os.path.dirname(SCRIPT_DIR)
# site/scripts -> site -> プロジェクトルート。__file__基準のためカレントディレクトリに依存しない。
PROJECT_ROOT = os.path.dirname(SITE_ROOT)

SUMMARY_HEADING = "【オーナーが今やること】"
TOKEN_OUTPUT_MARKER = "このセッションの使用トークン数"

# reason冒頭の前置き文（D-0082補足／D-0096でガバナンス警告の経路にも適用対象を拡大）。
# トークン追記・未commit検知・ガバナンス警告の3箇所すべてがこの定数を参照する。
NO_RESUMMARY_PREFIX = (
    "固定サマリー全体を再出力しないこと。直前の応答に続けて、該当分のみを出力すること。\n"
)

# 記事published化・Pin/hero画像追加に伴う正常な一時差分は誤検知対象から除外する（D-0080）。
GIT_DIRTY_EXCLUDED_PREFIXES = ("src/content/posts/", "public/images/")


def block(reason):
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))


def has_summary_heading_in(message):
    """last_assistant_messageに固定サマリー見出し「【オーナーが今やること】」が
    含まれているかを判定する（D-0081）。
    行の中にマーカー文字列が含まれているかの部分一致判定とし、装飾記号
    （#・**・__・絵文字付き等）の種類を問わない。装飾記号を都度列挙して剥がす
    方式は、未対応の記法が出るたびに検知漏れを繰り返した（D-0071の`#`限定修正が
    `**`太字記法で再発）ため廃止した。
    地の文中の言及（例:「〜という文言を含む応答」）でも行内に文字列が含まれれば
    Trueになるが、判定を緩めることによる誤検知（無駄にトークン追記が走るだけ）は、
    判定を厳しくすることによる検知漏れ（D-0066が機能しない）より実害が小さいため
    許容する。
    """
    return any(SUMMARY_HEADING in line for line in message.splitlines())


def build_reason(*parts):
    """検知結果（ガバナンス警告・トークン未出力・未commit）を1本のreason文字列へ
    統合する（D-0082）。空の項目は捨て、1件も無ければNoneを返す。
    呼び出し側はNoneでなければblock()を「1回だけ」呼ぶ。この関数を経由することで、
    検知が何件同時に成立してもblock()の呼び出しとJSON出力が1つに保たれる。
    """
    filled = [p for p in parts if p]
    if not filled:
        return None
    return "\n\n".join(filled)


def check_git_dirty(site_root):
    """site/リポジトリの未commit差分を検知する（D-0080）。
    記事ファイル・pin/hero画像ファイルの差分は正常な公開作業中の一時状態として除外する。
    検知できない場合（gitコマンド失敗等）はNoneを返し、何も警告しない。
    """
    try:
        result = subprocess.run(
            ["git", "-C", site_root, "status", "--porcelain"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None

    def _path_of(line):
        # porcelain短縮形式: "XY path" または "XY orig -> new"（リネーム）
        path = line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        return path.replace("\\", "/")

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    remaining = [
        line for line in lines if not _path_of(line).startswith(GIT_DIRTY_EXCLUDED_PREFIXES)
    ]
    if not remaining:
        return None
    return (
        NO_RESUMMARY_PREFIX +
        "【警告】site/リポジトリに未commitの変更があります（D-0080）。\n"
        "取るべき行動: 未commitの差分があることを（既に出力済みの）固定サマリーの【未決定事項】欄に相当する追記として記載し、"
        "オーナーへ報告してください。AIの自己判断でcommit・pushを行ってはなりません"
        "（未commit状態の差分は書きかけの作業や実験的な変更である可能性があり、"
        "内容を確認せず自動的に確定させることを防ぐためです）。\n"
        "対象:\n" + "\n".join(remaining)
    )


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")

    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}

    if payload.get("stop_hook_active"):
        sys.exit(0)

    child_env = dict(os.environ)
    child_env["PYTHONIOENCODING"] = "utf-8"

    reason_parts = []

    try:
        result = subprocess.run(
            [sys.executable, GOVERNANCE_SCRIPT],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=child_env,
            timeout=30,
        )
    except Exception as exc:
        block("check-doc-governance.pyの実行中にエラーが発生しました: %s" % exc)
        sys.exit(0)

    if result.returncode != 0:
        warnings = [line for line in result.stdout.splitlines() if line.startswith("【警告】")]
        if warnings:
            governance_message = "\n".join(warnings)
        else:
            governance_message = (
                "check-doc-governance.pyが警告終了コード(%d)を返しましたが、"
                "【警告】行を特定できませんでした。標準出力: %s"
                % (result.returncode, result.stdout[:500])
            )
        reason_parts.append(NO_RESUMMARY_PREFIX + governance_message)

    last_assistant_message = payload.get("last_assistant_message") or ""
    # 判定ロジック本体は has_summary_heading_in() に切り出し、
    # test-stop-hook-check.py から同じ関数を直接呼べるようにしてある（D-0081）。
    # 詳細は同関数のdocstring参照。
    has_summary_heading = has_summary_heading_in(last_assistant_message)
    has_token_output = TOKEN_OUTPUT_MARKER in last_assistant_message

    if has_summary_heading and not has_token_output:
        try:
            token_result = subprocess.run(
                [sys.executable, TOKEN_USAGE_SCRIPT],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=child_env,
                cwd=PROJECT_ROOT,
                timeout=30,
            )
            token_output = token_result.stdout.strip() or token_result.stderr.strip()
        except Exception as exc:
            token_output = "session-token-usage.pyの実行中にエラーが発生しました: %s" % exc
        reason_parts.append(
            NO_RESUMMARY_PREFIX +
            "固定サマリーにトークン消費量の表示が含まれていなかったため、"
            "Stopフックが自動的に追記します。\n%s" % token_output
        )

    # 未commit差分の検知結果もreason_partsへ統合する（D-0082）。
    # 旧実装はここでprint()による平文出力を行っていたが、AIの会話コンテキストへ
    # 届く経路がなく機能しておらず、かつblock()のJSONと同一stdoutに平文が混在して
    # トークン追記機構のJSONパースを壊すリスクがあったため取りやめた。
    reason_parts.append(check_git_dirty(SITE_ROOT))

    # block()の呼び出しは1回のみ・出力されるJSONも1つのみ（D-0082）。
    reason = build_reason(*reason_parts)
    if reason:
        block(reason)

    try:
        sync_result = subprocess.run(
            [sys.executable, GDRIVE_SYNC_SCRIPT],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=child_env,
            timeout=60,
        )
        if sync_result.returncode != 0:
            print(
                "警告: sync-to-gdrive.pyが同期失敗を報告しました。\n%s"
                % (sync_result.stdout or sync_result.stderr),
                file=sys.stderr,
            )
    except Exception as exc:
        print("警告: sync-to-gdrive.pyの実行中にエラーが発生しました: %s" % exc, file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
