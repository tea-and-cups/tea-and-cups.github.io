# -*- coding: utf-8 -*-
r"""Stopフック用: セッション終了時に check-doc-governance.py を実行し、
【警告】があれば1回だけ会話の継続を強制する。あわせて sync-to-gdrive.py で
運営5ファイルをGoogleドキュメントへ同期する（D-0064）。

Stopフックのcommandから、hook入力JSON（stdin）を受け取って呼ばれる想定。
stop_hook_active が true の場合（=このフック自身が直前に継続を強制した
2回目以降のStop発火）は無条件で停止を許可し、無限ループを避ける。

check-doc-governance.py は【警告】が1件でもあれば終了コード1、
それ以外（【通知】のみ・異常なし・初回実行）は終了コード0を返す
（同スクリプトのdocstring・sys.exit(1 if warnings else 0)を参照）。

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


def block(reason):
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}

    if payload.get("stop_hook_active"):
        sys.exit(0)

    child_env = dict(os.environ)
    child_env["PYTHONIOENCODING"] = "utf-8"

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
            reason = "\n".join(warnings)
        else:
            reason = (
                "check-doc-governance.pyが警告終了コード(%d)を返しましたが、"
                "【警告】行を特定できませんでした。標準出力: %s"
                % (result.returncode, result.stdout[:500])
            )
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
