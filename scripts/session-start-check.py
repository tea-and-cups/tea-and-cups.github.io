# -*- coding: utf-8 -*-
r"""SessionStartフックから呼ばれる呼び出し役スクリプト（D-0106）。

背景: CLAUDE.md 10節はセッション開始時に4本のスクリプト
（rotate-today-tasks.py / check-doc-governance.py / check-routine-due.py /
check-image-gen-needed-today.py）をAIが順に手動実行する運用だったが、
5節の起動フレーズ（「昨日までの実績を教えて」）と異なる言い回しでセッションが
始まった場合、AIがこの文章ルールを読み落として1本も実行しないことがあった。
本スクリプトはこの担保を文章ルールからSessionStartフック（ツール層）へ移し、
起動フレーズに依存せず必ず4本が実行される状態にする。

動作:
  - CHILD_SCRIPTS に並べた順序で必ず実行し、各スクリプトの標準出力をそのまま
    中継する（先頭4本の順序はD-0102の順序規定を維持する）。実行対象の正本は
    CHILD_SCRIPTS であり、この文章側に一覧を二重に持たない。
    各要素は (スクリプト名, 正常な終了コードの集合) か、固定引数を伴う
    (スクリプト名, 正常な終了コードの集合, 引数リスト) のどちらか（D-0235）。
  - 子スクリプトを起動する前にフック入力JSONから session_id を読み、
    環境変数 CLAUDE_HOOK_SESSION_ID として子へ渡す（D-0235）。子の標準入力は
    DEVNULL に固定する（フック入力JSONを子が二重に読んで固まるのを防ぐため）。
  - 各子スクリプトは cwd をプロジェクトルートに固定して起動する（D-0084と同型の予防）。
  - 子スクリプトは .py のみ対応で、sys.executable で起動する。パスは絶対パス・
    スラッシュ区切りに統一する（rules/command-execution.md 2 の形。クォートは
    リスト形式のsubprocessが担う）。.py 以外が登録された場合は起動を試みず
    明示的に失敗させる（D-0138）。
  - 子スクリプトが例外・非ゼロ終了・タイムアウト（1本30秒）した場合も無言で飛ばさず、
    「【エラー】<スクリプト名> が失敗しました（終了コード: N）」を出力し、残りの
    スクリプトは実行を続ける（silent failureを作らないため）。
  - 冒頭・末尾に固定文を印字する（AIの文脈に投入され、二重実行防止の指示として機能する）。

このスクリプト自体は既存4本のロジックを一切変更しない。呼び出し位置を移すのみ。

使い方:
  python site/scripts/session-start-check.py
"""

import json
import os
import subprocess
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS_DIR = os.path.join(ROOT, "site", "scripts")

# 各子スクリプト名と「正常とみなす終了コードの集合」をセットで持つ。
# 子スクリプトが増えたときもここだけ見れば済むようにするための一覧。
# check-doc-governance.py のみ 0/1 の両方を正常とする: このスクリプトは
# 警告を検出した場合に終了コード1を返す仕様（0=検出なし/1=警告検出）であり、
# 1は異常終了ではなく「警告あり」を表す正常な状態のため（2026-08-11実測・D-0107）。
# 他の3本は非ゼロ終了コードを異常とみなす通常の仕様のため 0 のみを正常とする。
CHILD_SCRIPTS = [
    ("rotate-today-tasks.py", {0}),
    ("check-doc-governance.py", {0, 1}),
    ("check-routine-due.py", {0}),
    # check-scheduled-items.py: 通知は常に終了コード0（add/done の失敗時のみ非ゼロだが
    # フック経由では引数なしの通知しか行わないため 0 のみを正常とする）。
    ("check-scheduled-items.py", {0}),
    ("check-image-gen-needed-today.py", {0}),
    ("list-latest-reports.py", {0}),
    ("check-pin-posting-status.py", {0}),
    # check-buffer-posting-status.py: 0=BUFFER_POSTING_OK、1=未投稿の組あり
    # （異常終了ではなく想定内の状態のためフック自体は失敗扱いにしない）。
    ("check-buffer-posting-status.py", {0, 1}),
    # check-pinterest-token.py: 0=期限余裕あり／リフレッシュ成功、1=期限接近でリフレッシュ失敗
    # （【警告】・異常ではなく想定内の状態のためフック自体は失敗扱いにしない）、
    # 2=リフレッシュトークン失効等で再認可が必要（正常集合外なので【エラー】として表示される）。
    ("check-pinterest-token.py", {0, 1}),
    # check-pinterest-boards-sync.py: 0=BOARDS_OK、1=【警告】検出（board_id不整合・
    # 選定規則とのボード名不一致・API到達失敗等。異常終了ではなく想定内の状態のため
    # フック自体は失敗扱いにしない）、2=想定外の例外（正常集合外なので【エラー】として表示される）。
    ("check-pinterest-boards-sync.py", {0, 1}),
    # check-published-pins-missing.py: 0=正常判定（検知の有無を問わない）。
    # 検知時は【警告】を本文に含めて出力する仕様のため、フック自体は失敗扱いにしない。
    ("check-published-pins-missing.py", {0}),
    # production-run.py open: このセッション＝1 production run の開始記録を作る
    # （D-0235）。正常時は何も出力しない。代理確定・区間の重なりがあった時だけ
    # 【警告】を1行出す。0=正常。
    ("production-run.py", {0}, ["open"]),
]

TIMEOUT_SECONDS = 30

HEADER = (
    "=== セッション開始時チェック（SessionStartフック・自動実行） ===\n"
    "以下は自動実行された開始時チェックの結果です。CLAUDE.md 10節のセッション開始時チェックは"
    "ここで実行済みのため、AIが同じものを改めて手動実行しないでください（二重報告防止）。\n"
    "【警告】【エラー】ROUTINE_NONE・SCHEDULED_NONE以外の出力・NEEDED判定のいずれかが含まれる場合は、"
    "その内容を通常の作業に入る前に最初にオーナーへ報告してください。"
    "NEEDEDの場合の対応はCLAUDE.md 10節の記載に従ってください。"
)

FOOTER = "=== セッション開始時チェック ここまで ==="


def build_argv(script_name, args=None):
    """起動コマンドを組み立てる。対応するのは .py のみ（D-0138）。
    パスは絶対パス・スラッシュ区切りに統一する（rules/command-execution.md 2）。
    固定の引数はCHILD_SCRIPTSの第3要素で渡す（D-0235でサブコマンド付きの
    子スクリプトが必要になったため追加した。動的に変わる値は渡さない）。

    .py 以外は起動を試みず例外にする。フック起動時のPATHにbashが無いため
    .sh は WinError 2 で必ず失敗する環境であり（D-0137の実装3で発覚・D-0138で
    check-doc-governance.py へ移植して置き換え済み）、将来また .sh 等を
    CHILD_SCRIPTS に登録して同じ穴に落ちることを機械的に防ぐ。
    """
    if not script_name.endswith(".py"):
        raise ValueError(
            "フック経由の子スクリプトは .py のみ対応です（%s は起動できません）。"
            "シェルスクリプトはフック起動時のPATHにbashが無く必ず失敗するため、"
            "検査ロジックはPythonスクリプト側へ実装してください（D-0138）。" % script_name
        )
    script_path = os.path.join(SCRIPTS_DIR, script_name).replace("\\", "/")
    return [sys.executable, script_path] + list(args or [])


def read_hook_session_id():
    """フック入力JSONから session_id を取り出して環境変数へ置く（D-0235）。

    子スクリプト（production-run.py open）がこのセッションのrunを特定するために使う。
    公式ドキュメント上 CLAUDE_CODE_SESSION_ID という環境変数は保証されていないため、
    フック入力JSONを一次情報とし、環境変数は子スクリプト側のfallbackに留める。

    標準入力が閉じられない環境でフック全体が固まらないよう、別スレッドで読んで
    短くタイムアウトさせる。読めなくても何もせず先へ進む（開始時チェックを
    止めてはいけない）。
    """
    try:
        if sys.stdin is None or sys.stdin.closed or sys.stdin.isatty():
            return
    except Exception:
        return

    box = {}

    def _read():
        try:
            box["raw"] = sys.stdin.buffer.read()
        except Exception:
            box["raw"] = b""

    thread = threading.Thread(target=_read, daemon=True)
    thread.start()
    thread.join(2.0)
    raw = box.get("raw")
    if not raw:
        return
    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return
    session_id = payload.get("session_id") if isinstance(payload, dict) else None
    if isinstance(session_id, str) and session_id:
        os.environ["CLAUDE_HOOK_SESSION_ID"] = session_id


def run_child(script_name, ok_codes, args=None):
    print("--- %s ---" % script_name)
    try:
        result = subprocess.run(
            build_argv(script_name, args),
            cwd=ROOT,
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        print("【エラー】%s が失敗しました（終了コード: タイムアウト %d秒）" % (script_name, TIMEOUT_SECONDS))
        return
    except Exception as e:
        print("【エラー】%s が失敗しました（終了コード: 例外 %s）" % (script_name, e))
        return

    stdout_text = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
    stderr_text = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""

    if stdout_text:
        print(stdout_text.rstrip("\n"))

    if result.returncode not in ok_codes:
        print("【エラー】%s が失敗しました（終了コード: %d）" % (script_name, result.returncode))
        if stderr_text:
            print(stderr_text.rstrip("\n"))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    # 子スクリプトを起動する前に読む（起動後は標準入力を子へ渡さないため）。
    read_hook_session_id()

    print(HEADER)
    print("")

    for entry in CHILD_SCRIPTS:
        script_name, ok_codes = entry[0], entry[1]
        args = entry[2] if len(entry) > 2 else None
        run_child(script_name, ok_codes, args)
        print("")

    print(FOOTER)
    sys.exit(0)


if __name__ == "__main__":
    main()
