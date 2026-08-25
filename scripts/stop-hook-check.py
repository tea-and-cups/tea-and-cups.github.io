# -*- coding: utf-8 -*-
r"""Stopフック用: セッション終了時に check-doc-governance.py を実行し、
【警告】があれば1回だけ会話の継続を強制する。あわせて sync-to-gdrive.py で
運営文書をGoogleドキュメントへ同期する（D-0064。対象一覧は sync-to-gdrive.py の
TARGET_FILES が正本）。同期の直前に generate-script-index.py で docs/script-index.md を
再生成する（D-0135。索引も同期対象のため、同期より前に最新化する必要がある）。

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

sync-to-gdrive.py が同期失敗を報告した場合（終了コード0以外・実行中の例外・
タイムアウト）は、その旨をblock()のreasonへ合流させ、会話の継続を1回だけ強制する
（D-0142）。旧実装はstderrへのprintのみで、AIの会話コンテキストにも固定サマリーにも
届かず、4セッション連続の同期停止が誰にも気づかれなかった（D-0141）。検知は
既に正しく動いていたため新しい検知は作らず、既にある情報の行き先をD-0082（未commit
検知）と同じ経路へ変えるだけとする。stderrへのprintはログとして残す。
継続強制の回数制御は既存の stop_hook_active 方式をそのまま使う（新しい制御は作らない）。
このため sync-to-gdrive.py・generate-script-index.py の実行位置は block() より前になる
（reasonの組み立てに同期結果が要るため）。generate-script-index.py の失敗は
従来どおりstderrへの警告のみで、reasonには載せない（索引は次回セッションで再生成される
ため、同期のように「静かに止まり続ける」性質を持たないため）。

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

■ 教訓リストの記録漏れ検知（D-0163）
record-lesson.py check を実行し、標準出力に LESSON_NOT_RECORDED が含まれる場合、
教訓の記録（add / bump / none）を促す文言を既存のreason統合へ合流させる。
日次セッションかどうかの判別はマーカー方式（data/lessons-session.txt に書かれた
セッションIDと現在の CLAUDE_CODE_SESSION_ID の一致）で行い、日次フローでしか
実行されないスクリプト（check-topic-duplicate.py・publish-article.py）がマーカーを作る。
改善・修正セッションではマーカーが作られないため、この検知は何も要求しない。
追加する子プロセスはこの1本のみで、処理はファイル1本の読み比べに留める。

■ 所要時間の記録（D-0136）
4つの子プロセス（governance判定・トークン集計・索引生成・Googleドライブ同期）それぞれの
所要秒数と結果を data/stop-hook-timing.tsv へ1セッション1行で追記する。目的は
①Stopフックの親タイムアウト（.claude/settings.local.json）に対して実測がどれだけ
余裕を持っているかを継続的に見えるようにすること、②将来「失敗の検知」を設計する際の
材料を貯めることの2点であり、この時点では検知・警告は行わず記録のみとする。
記録処理（write_timing_log）は全体をtry/exceptで包み、失敗してもフックの他の処理を
止めない。固定上限30行（ヘッダ行を除く）で、超えた分は古い行から捨てる。
data/配下はGit管理外（D-0043）のため、この位置に置いてよい。

■ block()の呼び出し規律（D-0082／D-0142で同期失敗を4項目目として追加）
ガバナンス警告・トークン未出力・未commit検知・同期失敗・教訓リスト未記録（D-0163）が
同時に成立しても、block()の
呼び出しは1回のみ・出力されるJSONも1つのみとし、reasonに全項目をまとめて含める。
継続強制の回数制御は既存の stop_hook_active 方式（1回だけ強制・2回目以降は無条件で
終了を許可）をそのまま使い、新しい制御方式は作らない。

使い方:
  python site/scripts/stop-hook-check.py < hook入力JSON
"""

import json
import os
import subprocess
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GOVERNANCE_SCRIPT = os.path.join(SCRIPT_DIR, "check-doc-governance.py")
SCRIPT_INDEX_SCRIPT = os.path.join(SCRIPT_DIR, "generate-script-index.py")
GDRIVE_SYNC_SCRIPT = os.path.join(SCRIPT_DIR, "sync-to-gdrive.py")
TOKEN_USAGE_SCRIPT = os.path.join(SCRIPT_DIR, "session-token-usage.py")
RECORD_LESSON_SCRIPT = os.path.join(SCRIPT_DIR, "record-lesson.py")
SITE_ROOT = os.path.dirname(SCRIPT_DIR)
# site/scripts -> site -> プロジェクトルート。__file__基準のためカレントディレクトリに依存しない。
PROJECT_ROOT = os.path.dirname(SITE_ROOT)

SUMMARY_HEADING = "【オーナーが今やること】"
TOKEN_OUTPUT_MARKER = "このセッションの使用トークン数"
LESSON_NOT_RECORDED_MARKER = "LESSON_NOT_RECORDED"

# reason冒頭の前置き文（D-0082補足／D-0096でガバナンス警告の経路にも適用対象を拡大）。
# トークン追記・未commit検知・ガバナンス警告の3箇所すべてがこの定数を参照する。
NO_RESUMMARY_PREFIX = (
    "固定サマリー全体を再出力しないこと。直前の応答に続けて、該当分のみを出力すること。"
    "【オーナーが今やること】等の固定サマリーの見出しを再掲してはならない。"
    "出力するのは以下の内容の行だけとする。\n"
)

# 記事published化・Pin/hero画像追加に伴う正常な一時差分は誤検知対象から除外する（D-0080）。
GIT_DIRTY_EXCLUDED_PREFIXES = ("src/content/posts/", "public/images/")

# 所要時間の記録（D-0136）。data/配下はGit管理外（D-0043）。
TIMING_LOG = os.path.join(PROJECT_ROOT, "data", "stop-hook-timing.tsv")
TIMING_MAX_ROWS = 30  # ヘッダ行を除いたデータ行の固定上限。超えたら古い行から捨てる。
# 記録対象の子プロセス。表示順＝TSVの列順であり、実行順に並べてある。
TIMING_KEYS = ("governance", "token", "script_index", "gdrive_sync")
TIMING_HEADER = (
    "日時",
    "governance秒", "token秒", "索引生成秒", "同期秒",
    "governance結果", "token結果", "索引生成結果", "同期結果",
)
TIMING_STATUS_SKIPPED = "スキップ"

# run_child() が {キー: (所要秒数, 結果)} を積む。未実行のキーはスキップ扱いになる。
_timings = {}


def run_child(key, argv, timeout, **kwargs):
    """子プロセスを実行し、所要秒数と結果を _timings へ記録する（D-0136）。
    返り値は (CompletedProcess or None, 発生した例外 or None)。
    結果は OK（終了コード0）／NG（0以外・例外）／タイムアウト の3種。
    governance判定の「NG」は終了コード1＝【警告】ありを意味し、スクリプトの
    異常終了とは限らない（check-doc-governance.pyのdocstring参照）。
    タイムアウト値そのものは呼び出し側が従来どおり個別に持つ（子側の値は個々の
    処理が異常に長引いたときに止める役割を担うため、親側の値と連動させない）。
    """
    start = time.perf_counter()
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            **kwargs
        )
    except subprocess.TimeoutExpired as exc:
        _timings[key] = (time.perf_counter() - start, "タイムアウト")
        return None, exc
    except Exception as exc:
        _timings[key] = (time.perf_counter() - start, "NG")
        return None, exc
    _timings[key] = (time.perf_counter() - start, "OK" if result.returncode == 0 else "NG")
    return result, None


def write_timing_log():
    """_timings の内容を data/stop-hook-timing.tsv へ1行追記する（D-0136）。
    この処理自体が失敗してもフックの他の処理を止めないため、全体をtry/exceptで包み、
    失敗はstderrへの警告のみに留める（stdoutへは書かない・D-0082のstdout規律）。
    """
    try:
        row = [time.strftime("%Y-%m-%d %H:%M:%S")]
        for key in TIMING_KEYS:
            seconds, _status = _timings.get(key, (None, TIMING_STATUS_SKIPPED))
            row.append("" if seconds is None else "%.2f" % seconds)
        for key in TIMING_KEYS:
            _seconds, status = _timings.get(key, (None, TIMING_STATUS_SKIPPED))
            row.append(status)

        rows = []
        if os.path.exists(TIMING_LOG):
            with open(TIMING_LOG, "r", encoding="utf-8") as f:
                rows = [line.rstrip("\n") for line in f if line.strip()]
            if rows and rows[0].split("\t")[0] == TIMING_HEADER[0]:
                rows = rows[1:]
        rows.append("\t".join(row))
        rows = rows[-TIMING_MAX_ROWS:]

        directory = os.path.dirname(TIMING_LOG)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        with open(TIMING_LOG, "w", encoding="utf-8", newline="\n") as f:
            f.write("\t".join(TIMING_HEADER) + "\n")
            for line in rows:
                f.write(line + "\n")
    except Exception as exc:
        print(
            "警告: stop-hook-timing.tsvの記録中にエラーが発生しました: %s" % exc,
            file=sys.stderr,
        )


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


def build_governance_reason(returncode, stdout):
    """check-doc-governance.pyの実行結果からreason文字列を組み立てる（D-0096）。
    【警告】が1件でもある場合の経路・警告行を特定できなかった場合のフォールバック
    経路の両方で、冒頭に NO_RESUMMARY_PREFIX を付ける。返り値はcheck_git_dirty()と
    同じく前置き込みの完成形の文字列（またはNone）とし、呼び出し側はそのまま
    reason_partsへappendするだけでよい形に揃える。
    returncode == 0（警告なし）ならNoneを返す。
    """
    if returncode == 0:
        return None
    warnings = [line for line in stdout.splitlines() if line.startswith("【警告】")]
    if warnings:
        governance_message = "\n".join(warnings)
    else:
        governance_message = (
            "check-doc-governance.pyが警告終了コード(%d)を返しましたが、"
            "【警告】行を特定できませんでした。標準出力: %s"
            % (returncode, stdout[:500])
        )
    return NO_RESUMMARY_PREFIX + governance_message


def build_token_reason(token_output):
    """トークン追記のreason文字列を組み立てる（D-0096でgovernance・未commit検知と
    同じNO_RESUMMARY_PREFIX参照に統一）。"""
    return (
        NO_RESUMMARY_PREFIX +
        "固定サマリーにトークン消費量の表示が含まれていなかったため、"
        "Stopフックが自動的に追記します。\n%s" % token_output
    )


def build_lesson_reason(lesson_result, lesson_exc):
    """教訓リストの記録漏れ（record-lesson.py check）をreason文字列へ組み立てる（D-0163）。
    check は日次フローのマーカー（data/lessons-session.txt）が現在のセッションIDと
    一致するときだけ LESSON_NOT_RECORDED を出力する。改善・修正セッションでは
    マーカーが作られないため何も出力されず、この関数もNoneを返す（＝誤爆しない）。
    check は仕様上 exit 1 を使わないため、判定は標準出力のマーカー文字列のみで行う。
    返り値は他の系統と同じくNO_RESUMMARY_PREFIX込みの完成形とする。
    """
    if lesson_result is None:
        print(
            "警告: record-lesson.py checkの実行中にエラーが発生しました: %s" % lesson_exc,
            file=sys.stderr,
        )
        return None
    if LESSON_NOT_RECORDED_MARKER not in (lesson_result.stdout or ""):
        return None
    return (
        NO_RESUMMARY_PREFIX +
        "教訓リストが未記録です。record-lesson.py list で既存項目を確認し、"
        "add / bump / none のいずれかを実行してください"
        "（python site/scripts/record-lesson.py list ／ "
        "add --category <カテゴリ> --summary \"<40字以内>\" ／ bump --id <L番号> ／ none）。"
    )


def build_sync_reason(sync_result, sync_exc):
    """sync-to-gdrive.py の同期失敗をreason文字列へ組み立てる（D-0142）。
    成功（終了コード0）ならNoneを返す。返り値はcheck_git_dirty()等と同じく
    NO_RESUMMARY_PREFIX 込みの完成形とし、呼び出し側はreason_partsへappendするだけでよい。
    再認可はオーナーのブラウザ操作を伴うため、AIが自己判断で実行しないことを明記する。
    """
    if sync_result is not None and sync_result.returncode == 0:
        return None

    if sync_result is None:
        detail = "sync-to-gdrive.pyの実行自体に失敗しました: %s" % sync_exc
    else:
        output = (sync_result.stdout or sync_result.stderr or "").strip()
        detail = "sync-to-gdrive.py の終了コード=%d / 出力の要点:\n%s" % (
            sync_result.returncode,
            output[-800:] if output else "（出力なし）",
        )

    return (
        NO_RESUMMARY_PREFIX +
        "【警告】Googleドキュメントへの同期が失敗しました（sync-to-gdrive.py・D-0142）。\n"
        + detail + "\n"
        "復旧にはオーナーのブラウザ操作（Google OAuthの再認可）が必要になる場合があります"
        "（過去にリフレッシュトークン失効で発生・D-0141）。\n"
        "取るべき行動: 同期が失敗したことを（既に出力済みの）固定サマリーの【未決定事項】欄に"
        "相当する追記として記載し、オーナーへ報告してください。"
        "オーナーへ報告し、指示があるまで再認可（sync-to-gdrive.py --init やブラウザでの認可操作）を"
        "AIの自己判断で実行してはなりません。"
    )


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

    result, exc = run_child(
        "governance", [sys.executable, GOVERNANCE_SCRIPT], 30, env=child_env
    )
    if result is None:
        block("check-doc-governance.pyの実行中にエラーが発生しました: %s" % exc)
        write_timing_log()
        sys.exit(0)

    reason_parts.append(build_governance_reason(result.returncode, result.stdout))

    last_assistant_message = payload.get("last_assistant_message") or ""
    # 判定ロジック本体は has_summary_heading_in() に切り出し、
    # test-stop-hook-check.py から同じ関数を直接呼べるようにしてある（D-0081）。
    # 詳細は同関数のdocstring参照。
    has_summary_heading = has_summary_heading_in(last_assistant_message)
    has_token_output = TOKEN_OUTPUT_MARKER in last_assistant_message

    if has_summary_heading and not has_token_output:
        token_result, token_exc = run_child(
            "token",
            [sys.executable, TOKEN_USAGE_SCRIPT],
            30,
            env=child_env,
            cwd=PROJECT_ROOT,
        )
        if token_result is None:
            token_output = (
                "session-token-usage.pyの実行中にエラーが発生しました: %s" % token_exc
            )
        else:
            token_output = token_result.stdout.strip() or token_result.stderr.strip()
        reason_parts.append(build_token_reason(token_output))

    # 未commit差分の検知結果もreason_partsへ統合する（D-0082）。
    # 旧実装はここでprint()による平文出力を行っていたが、AIの会話コンテキストへ
    # 届く経路がなく機能しておらず、かつblock()のJSONと同一stdoutに平文が混在して
    # トークン追記機構のJSONパースを壊すリスクがあったため取りやめた。
    reason_parts.append(check_git_dirty(SITE_ROOT))

    # 教訓リストの記録漏れ検知（D-0163）。子プロセスはこの1本のみで、判定は
    # data/lessons-session.txt の読み比べだけの軽い処理である。
    # 所要時間TSV（D-0136）の列は既存4本のまま変えないため、_timingsのキー"lesson"は
    # TIMING_KEYSに含めず記録対象外とする（列構成を変えると過去行と食い違うため）。
    lesson_result, lesson_exc = run_child(
        "lesson", [sys.executable, RECORD_LESSON_SCRIPT, "check"], 15, env=child_env
    )
    reason_parts.append(build_lesson_reason(lesson_result, lesson_exc))

    # 索引生成・同期は block() より前に実行する（D-0142）。同期の失敗をreasonへ
    # 合流させるため、block()を呼ぶ時点で同期結果が確定している必要がある。
    # docs/script-index.md を再生成する。sync-to-gdrive.py より前に実行することで、
    # 同期対象へ追加した索引が同じセッションの最新状態で同期される。
    # 索引生成の失敗は従来どおりreasonへ載せず、stderrへの警告のみとする。
    index_result, index_exc = run_child(
        "script_index", [sys.executable, SCRIPT_INDEX_SCRIPT], 60, env=child_env
    )
    if index_result is None:
        print(
            "警告: generate-script-index.pyの実行中にエラーが発生しました: %s" % index_exc,
            file=sys.stderr,
        )
    elif index_result.returncode != 0:
        print(
            "警告: generate-script-index.pyが索引の生成失敗を報告しました。\n%s"
            % (index_result.stdout or index_result.stderr),
            file=sys.stderr,
        )

    sync_result, sync_exc = run_child(
        "gdrive_sync", [sys.executable, GDRIVE_SYNC_SCRIPT], 60, env=child_env
    )
    if sync_result is None:
        print(
            "警告: sync-to-gdrive.pyの実行中にエラーが発生しました: %s" % sync_exc,
            file=sys.stderr,
        )
    elif sync_result.returncode != 0:
        print(
            "警告: sync-to-gdrive.pyが同期失敗を報告しました。\n%s"
            % (sync_result.stdout or sync_result.stderr),
            file=sys.stderr,
        )

    # 上のstderr出力はログとして残したうえで、同じ検知結果をreasonへも合流させる（D-0142）。
    reason_parts.append(build_sync_reason(sync_result, sync_exc))

    # block()の呼び出しは1回のみ・出力されるJSONも1つのみ（D-0082）。
    reason = build_reason(*reason_parts)
    if reason:
        block(reason)

    # 記録のみ・検知や警告は行わない（D-0136）。失敗してもここで止まらない。
    write_timing_log()

    sys.exit(0)


if __name__ == "__main__":
    main()
