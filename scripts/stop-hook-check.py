# -*- coding: utf-8 -*-
r"""Stopフック用: セッション終了時に check-doc-governance.py を実行し、
【警告】があれば1回だけ会話の継続を強制する。あわせて sync-to-gdrive.py で
運営5ファイルをGoogleドキュメントへ同期する（D-0064）。

さらに、直前のアシスタント応答（last_assistant_message）に固定サマリーの見出し
「【オーナーが今やること】」が含まれるのにトークン消費量の出力がまだ含まれていない
場合、session-token-usage.py を実行しその出力を強制的に追記する（D-0066）。
これによりAI自身がsession-token-usage.pyを手動実行する必要はなくなる
（CLAUDE.md 5節ステップ6参照）。

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

SUMMARY_HEADING = "【オーナーが今やること】"
TOKEN_OUTPUT_MARKER = "このセッションの使用トークン数"


def block(reason):
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))


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
            reason_parts.append("\n".join(warnings))
        else:
            reason_parts.append(
                "check-doc-governance.pyが警告終了コード(%d)を返しましたが、"
                "【警告】行を特定できませんでした。標準出力: %s"
                % (result.returncode, result.stdout[:500])
            )

    last_assistant_message = payload.get("last_assistant_message") or ""
    # 地の文中の言及（例:「〜という文言を含む応答」のような引用）で誤発火しないよう、
    # 単純な部分文字列一致ではなく「行頭に見出しとして出現しているか」で判定する（D-0067）。
    has_summary_heading = any(
        line.strip().startswith(SUMMARY_HEADING) for line in last_assistant_message.splitlines()
    )
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
                timeout=30,
            )
            token_output = token_result.stdout.strip() or token_result.stderr.strip()
        except Exception as exc:
            token_output = "session-token-usage.pyの実行中にエラーが発生しました: %s" % exc
        reason_parts.append(
            "固定サマリーにトークン消費量の表示が含まれていなかったため、"
            "Stopフックが自動的に追記します。\n%s" % token_output
        )

    if reason_parts:
        block("\n\n".join(reason_parts))

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
