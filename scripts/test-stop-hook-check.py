# -*- coding: utf-8 -*-
r"""stop-hook-check.py の固定サマリー見出し検出ロジックの再発防止テスト（D-0071・D-0081）。

D-0071で発覚したバグ: 実際の固定サマリー出力は
"## 【オーナーが今やること】" のようにMarkdown見出し記法（# の連続）を伴うが、
検出ロジックが line.strip().startswith(SUMMARY_HEADING) のみで# を除去して
いなかったため、常にFalse判定になりトークン消費量の追記（D-0066）が一度も
機能していなかった。

D-0081で発覚したバグ: D-0071の修正は#の除去にしか対応しておらず、実際のセッション
transcriptを実測したところ "**【オーナーが今やること】**" のような太字（**）記法
でも出力されていることが判明した（過去セッションで多数実測・c3e43d4eセッション等）。
装飾記号を都度列挙して剥がす方式は、未対応の記法が出るたびに同種の検知漏れを
繰り返す構造的な脆さを持つと判断し、行の中にマーカー文字列が含まれているかの
部分一致判定（has_summary_heading_in()）に置き換えた。

D-0082で追加した検証: 未commit検知（D-0080）の結果をblock()のreasonへ統合したことに
伴い、「検知が何件同時に成立してもblock()の呼び出しは1回・stdoutへ出るJSONも1つだけで、
平文が混在しない」ことを検証する（build_reason()＋block()のstdout実測）。
あわせて check_git_dirty() が「報告のみ・AIの自己判断でcommit/pushしない」旨の
行動指示を含むこと、除外パス（記事・画像）の判定が維持されていることを検証する。

D-0096で追加した検証: NO_RESUMMARY_PREFIX（「固定サマリー全体を再出力しないこと」の
前置き文）をガバナンス警告・トークン追記・未commit検知の3箇所すべてが参照している
ことを機械的に検証する。前置き文はテスト側にベタ書きせず、stop-hook-check.py側の
NO_RESUMMARY_PREFIX 定数をimportして比較する（ベタ書きすると、本体と一緒にテストも
書き換えられた場合に検知漏れが起きるため）。ガバナンス警告経路は
build_governance_reason()、トークン追記経路は build_token_reason() へそれぞれ
切り出し済みで、単体テストから直接呼べる（元はmain()内にインライン実装されており
テストできなかった）。

D-0096補強で追加した検証（main()結線テスト）: 上記2件は「切り出した関数が正しい
文字列を返すこと」までしか見ておらず、「main()がその関数を正しく呼び、複数条件が
同時成立してもblock()が1回・JSONが1本に集約されること」（D-0082の要件）は未検証
だった。切り出し時に呼び出し側の結線を間違えていても既存25件は全パスしてしまう。
run_main_integration_cases() は main() をサブプロセスとしてではなく関数として直接
呼び出し、GOVERNANCE_SCRIPT・TOKEN_USAGE_SCRIPT・GDRIVE_SYNC_SCRIPT・SITE_ROOT を
テスト用のダミースクリプト・一時gitリポジトリへ一時的に差し替えたうえで、
標準入力（stdin）にhook入力JSONを、標準出力（stdout）の捕捉にcontextlib.redirect_stdout
を使い、main()実行後は差し替えた属性をすべて元に戻す（他のテストケースやテスト
プロセス自体への副作用を残さないため）。

本テストは stop-hook-check.py の関数を直接インポートして検証する（テスト側で
ロジックを再実装しない。再実装すると、本体側だけ直してテスト側が古いロジックのまま
残る＝検知しない、という事態を招くため）。
stop-hook-check.py はハイフンを含むモジュール名のため importlib で読み込む。

副作用のないテストのみで構成する（本物のsite/リポジトリは触らず、git検知の検証には
一時ディレクトリのテスト用リポジトリを使う。main()の全体実行は
sync-to-gdrive.py による実際のGoogleドキュメント書き込みを伴うため、ここでは行わない）。

使い方:
  python site/scripts/test-stop-hook-check.py
"""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(SCRIPT_DIR, "stop-hook-check.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("stop_hook_check", TARGET)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _emit(module, *reason_parts):
    """main()と同じ経路（build_reason → 成立時のみblock()を1回）でstdoutへ出力し、
    その内容を捕捉して返す（D-0082）。テスト側でJSON整形を再実装しないため、
    本体のbuild_reason()・block()をそのまま呼ぶ。
    """
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        reason = module.build_reason(*reason_parts)
        if reason:
            module.block(reason)
    return buffer.getvalue()


def _assert_single_json(captured):
    """stdoutがJSON1本のみ（平文の混在なし）であることを検証し、
    (ok, 説明, パース済みオブジェクト) を返す（D-0082）。
    """
    lines = [line for line in captured.splitlines() if line.strip()]
    if len(lines) != 1:
        return False, "stdoutの行数が1ではない（実際=%d行）: %r" % (len(lines), captured[:200]), None
    try:
        obj = json.loads(lines[0])
    except Exception as exc:
        return False, "stdoutがJSONとしてパースできない（平文混在の疑い）: %s" % exc, None
    if obj.get("decision") != "block":
        return False, 'decisionが"block"ではない: %r' % obj.get("decision"), None
    return True, "stdoutはJSON1本のみ", obj


def _make_dirty_repo(tmpdir, relpath):
    """一時ディレクトリにテスト用gitリポジトリを作り、relpathへ未追跡ファイルを1つ置く。
    本物のsite/リポジトリには一切触れない（D-0082のテストは副作用を持たせない）。

    注意: relpathの親ディレクトリに追跡済みファイルを1つ作って初回commitしておく。
    `git status --porcelain` は「配下が丸ごと未追跡のディレクトリ」を親ディレクトリ1行
    （例: `?? src/`）へ畳んで報告するため、追跡済みファイルが1つも無いリポジトリでは
    フルパスが得られず、除外パス判定を実環境どおりに再現できない。本物のsite/では
    src/content/posts/・public/images/ とも追跡済みファイルを含むため、新規ファイルは
    `?? src/content/posts/xxx.md` とフルパスで報告される（実測確認済み）。
    """
    subprocess.run(
        ["git", "init", "-q", tmpdir], capture_output=True, text=True, timeout=15
    )
    target = os.path.join(tmpdir, relpath.replace("/", os.sep))
    os.makedirs(os.path.dirname(target), exist_ok=True)

    keep = os.path.join(os.path.dirname(target), ".keep")
    with open(keep, "w", encoding="utf-8") as f:
        f.write("")
    subprocess.run(
        ["git", "-C", tmpdir, "add", "-A"], capture_output=True, text=True, timeout=15
    )
    subprocess.run(
        [
            "git", "-C", tmpdir,
            "-c", "user.email=test@example.invalid",
            "-c", "user.name=test",
            "commit", "-q", "-m", "init",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )

    with open(target, "w", encoding="utf-8") as f:
        f.write("test\n")
    return tmpdir


def run_git_and_reason_cases(module):
    """D-0082: 未commit検知の内容と、block()呼び出し・JSON出力の単一性を検証する。
    戻り値は (説明, 成否, 補足) のリスト。
    """
    results = []
    token_part = (
        "固定サマリーにトークン消費量の表示が含まれていなかったため、"
        "Stopフックが自動的に追記します。\nトークン使用量: (テスト値)"
    )

    # --- check_git_dirty(): 未commit差分の検知内容 ---
    tmpdir = tempfile.mkdtemp(prefix="stophook_test_")
    try:
        _make_dirty_repo(tmpdir, "scripts/_dummy_dirty.txt")
        warning = module.check_git_dirty(tmpdir)
        ok = bool(warning) and "_dummy_dirty.txt" in warning
        results.append(("check_git_dirty: 未commit差分を検知する", ok, ""))

        has_action = bool(warning) and (
            "【未決定事項】" in warning
            and "オーナーへ報告" in warning
            and "commit・pushを行ってはなりません" in warning
        )
        results.append(
            (
                "check_git_dirty: reasonに「【未決定事項】へ記載・報告」「AI自己判断でcommit/push禁止」が含まれる",
                has_action,
                "",
            )
        )
        git_part = warning
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # --- 除外パス（D-0080・今回変更しないことの確認） ---
    tmpdir2 = tempfile.mkdtemp(prefix="stophook_test_excl_")
    try:
        _make_dirty_repo(tmpdir2, "src/content/posts/dummy-article.md")
        excluded = module.check_git_dirty(tmpdir2)
        results.append(
            ("除外パス維持: 記事ファイルのみの差分は検知しない（Noneを返す）", excluded is None, "")
        )
    finally:
        shutil.rmtree(tmpdir2, ignore_errors=True)

    # --- a. 未commit差分のみ ---
    captured = _emit(module, None, None, git_part)
    ok, detail, obj = _assert_single_json(captured)
    if ok:
        ok = "未commitの変更があります" in obj["reason"] and (
            "commit・pushを行ってはなりません" in obj["reason"]
        )
        detail = "reasonに未commit警告と自動commit禁止が含まれる" if ok else "reason内容が不足"
    results.append(("a. 未commit差分のみ → block()1回・JSON1本", ok, detail))

    # --- b. トークン未出力のみ ---
    captured = _emit(module, None, token_part, None)
    ok, detail, obj = _assert_single_json(captured)
    if ok:
        ok = "トークン消費量" in obj["reason"] and "未commit" not in obj["reason"]
        detail = "reasonはトークン追記のみ" if ok else "reason内容が想定外"
    results.append(("b. トークン未出力のみ → block()1回・JSON1本", ok, detail))

    # --- c. トークン未出力＋未commit差分の同時発生 ---
    captured = _emit(module, None, token_part, git_part)
    ok, detail, obj = _assert_single_json(captured)
    if ok:
        ok = "トークン消費量" in obj["reason"] and "未commitの変更があります" in obj["reason"]
        detail = "1本のreasonに両方の内容が含まれる" if ok else "両方の内容が揃っていない"
    results.append(("c. トークン未出力＋未commit同時 → block()1回・JSON1本に両方", ok, detail))

    # --- c-2. ガバナンス警告も加えた3件同時 ---
    captured = _emit(module, "【警告】テスト用ガバナンス警告", token_part, git_part)
    ok, detail, obj = _assert_single_json(captured)
    if ok:
        ok = (
            "テスト用ガバナンス警告" in obj["reason"]
            and "トークン消費量" in obj["reason"]
            and "未commitの変更があります" in obj["reason"]
        )
        detail = "1本のreasonに3件すべてが含まれる" if ok else "3件が揃っていない"
    results.append(("c-2. 3件同時（ガバナンス＋トークン＋未commit） → JSON1本に集約", ok, detail))

    # --- d. 何も検知されない通常ケース ---
    captured = _emit(module, None, None, None)
    ok = captured == ""
    results.append(
        ("d. 検知なし → block()を呼ばずstdoutは空", ok, "stdout=%r" % captured[:100])
    )

    return results


def _write_dummy_script(path, exit_code, stdout_text=""):
    """main()が subprocess.run([sys.executable, ...]) で呼ぶ先を差し替えるための
    使い捨てダミースクリプトを書く。指定した終了コード・標準出力を返すだけの
    最小のPythonスクリプト（実際のcheck-doc-governance.py等は一切呼ばない）。
    """
    with open(path, "w", encoding="utf-8") as f:
        f.write("import sys\n")
        if stdout_text:
            f.write("print(%r)\n" % stdout_text)
        f.write("sys.exit(%d)\n" % exit_code)


def _run_main(module, payload, overrides):
    """module.main() を関数として直接呼び出し、標準出力を捕捉して返す。

    main()内部が参照する GOVERNANCE_SCRIPT・TOKEN_USAGE_SCRIPT・GDRIVE_SYNC_SCRIPT・
    SITE_ROOT 等のモジュールグローバルを overrides で一時的に差し替えたうえで実行し、
    実行後は必ず元の値へ戻す（try/finallyで保証。他のテストケースやテストプロセス
    自体に副作用を残さないため）。標準入力は payload（dict）をJSON化してio.StringIOで
    差し替える。main()はsys.exit(0)/(1)で終了するため、SystemExitを捕捉する。
    """
    original = {key: getattr(module, key) for key in overrides}
    for key, value in overrides.items():
        setattr(module, key, value)

    original_stdin = sys.stdin
    sys.stdin = io.StringIO(json.dumps(payload, ensure_ascii=False))

    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            try:
                module.main()
            except SystemExit:
                pass
    finally:
        sys.stdin = original_stdin
        for key, value in original.items():
            setattr(module, key, value)

    return buffer.getvalue()


def run_main_integration_cases(module):
    """D-0096補強: main()を実際に呼び出し、①block()の呼び出しが1回・出力JSONが
    1本に集約されること②reasonに3条件すべての内容が含まれること③reasonの冒頭が
    NO_RESUMMARY_PREFIXで始まり、かつ重複して2回以上現れないこと④3条件とも
    不成立の場合にblock()を呼ばず正常終了すること、を検証する。
    戻り値は (説明, 成否, 補足) のリスト。
    """
    results = []
    prefix = module.NO_RESUMMARY_PREFIX
    heading = module.SUMMARY_HEADING

    workdir = tempfile.mkdtemp(prefix="stophook_test_main_")
    try:
        governance_script = os.path.join(workdir, "dummy_governance.py")
        token_script = os.path.join(workdir, "dummy_token.py")
        sync_script = os.path.join(workdir, "dummy_sync.py")
        _write_dummy_script(sync_script, 0)

        # --- 1〜3. 3条件（ガバナンス警告・トークン追記・未commit検知）が同時成立 ---
        dirty_repo = os.path.join(workdir, "dirty_repo")
        os.makedirs(dirty_repo, exist_ok=True)
        _make_dirty_repo(dirty_repo, "scripts/_dummy_dirty_main.txt")
        _write_dummy_script(governance_script, 1, "【警告】テスト用ガバナンス警告(main結線)")
        _write_dummy_script(token_script, 0, "トークン使用量: (main結線テスト値)")

        payload = {
            "stop_hook_active": False,
            "last_assistant_message": "## %s\n本文" % heading,  # トークン出力マーカーは含めない
        }
        captured = _run_main(
            module,
            payload,
            {
                "GOVERNANCE_SCRIPT": governance_script,
                "TOKEN_USAGE_SCRIPT": token_script,
                "GDRIVE_SYNC_SCRIPT": sync_script,
                "SITE_ROOT": dirty_repo,
            },
        )

        ok, detail, obj = _assert_single_json(captured)
        results.append(("D-0096-5. main()結線: 3条件同時成立でもJSONが1本のみ", ok, detail))

        if ok:
            reason = obj["reason"]
            has_all = (
                "テスト用ガバナンス警告(main結線)" in reason
                and "main結線テスト値" in reason
                and "未commitの変更があります" in reason
            )
            results.append(
                ("D-0096-6. main()結線: reasonに3条件すべての内容が含まれる", has_all, "")
            )

            starts_ok = reason.startswith(prefix)
            # build_reason()は各条件のreasonを"\n\n"で連結する（D-0082）。3条件それぞれが
            # 自分の担当分にのみ前置きを1回付ける設計のため、連結後のreason全体には
            # 前置き文が3回（条件の数だけ）現れるのが正しい姿であり、それ自体は異常では
            # ない。ここで検知したいのは「冒頭で前置き文が連続して二重に貼られていないか」
            # （例: prefix+prefix+本文、のような結線ミス）であり、それを duplicate_at_head で見る。
            duplicate_at_head = reason.startswith(prefix + prefix)
            expected_occurrences = 3  # ガバナンス・トークン・未commitの3条件分
            occurrence_ok = reason.count(prefix) == expected_occurrences
            results.append(
                (
                    "D-0096-7. main()結線: reasonの冒頭がNO_RESUMMARY_PREFIXで始まり、冒頭で二重貼りされていない",
                    starts_ok and not duplicate_at_head,
                    "starts_ok=%s duplicate_at_head=%s" % (starts_ok, duplicate_at_head),
                )
            )
            results.append(
                (
                    "D-0096-7b. main()結線: reason全体の前置き出現回数が条件数（3）と一致（不足=結線漏れ／超過=二重付与の疑い）",
                    occurrence_ok,
                    "実際の出現回数=%d" % reason.count(prefix),
                )
            )
        else:
            results.append(("D-0096-6. main()結線: reasonに3条件すべての内容が含まれる", False, "前段が失敗したため未検証"))
            results.append(("D-0096-7. main()結線: reasonの冒頭がNO_RESUMMARY_PREFIXで始まり、冒頭で二重貼りされていない", False, "前段が失敗したため未検証"))
            results.append(("D-0096-7b. main()結線: reason全体の前置き出現回数が条件数（3）と一致（不足=結線漏れ／超過=二重付与の疑い）", False, "前段が失敗したため未検証"))

        # --- 4. 3条件とも不成立 ---
        clean_repo = os.path.join(workdir, "clean_repo")
        os.makedirs(clean_repo, exist_ok=True)
        subprocess.run(["git", "init", "-q", clean_repo], capture_output=True, text=True, timeout=15)
        _write_dummy_script(governance_script, 0, "異常なし")

        payload_clean = {
            "stop_hook_active": False,
            "last_assistant_message": "特に見出しを含まない通常の応答本文です。",
        }
        captured_clean = _run_main(
            module,
            payload_clean,
            {
                "GOVERNANCE_SCRIPT": governance_script,
                "TOKEN_USAGE_SCRIPT": token_script,
                "GDRIVE_SYNC_SCRIPT": sync_script,
                "SITE_ROOT": clean_repo,
            },
        )
        ok_clean = captured_clean == ""
        results.append(
            (
                "D-0096-8. main()結線: 3条件とも不成立ならblock()を呼ばず正常終了（stdout空）",
                ok_clean,
                "stdout=%r" % captured_clean[:200],
            )
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    return results


def run_prefix_consistency_cases(module):
    """D-0096: ガバナンス警告【のみ】・トークン追記【のみ】・未commit検知【のみ】の
    それぞれで、build()されたreasonの冒頭がNO_RESUMMARY_PREFIX定数と一致することを
    検証する。定数はテスト側にベタ書きせず本体からimportして比較する（本体と
    テストが一緒に書き換えられて検知漏れが起きることを防ぐため）。
    戻り値は (説明, 成否, 補足) のリスト。
    """
    results = []
    prefix = module.NO_RESUMMARY_PREFIX

    # --- 1. ガバナンス警告のみ（警告行を特定できる経路） ---
    reason = module.build_governance_reason(1, "【警告】テスト用ガバナンス警告\n")
    ok = bool(reason) and reason.startswith(prefix)
    results.append(
        ("D-0096-1. ガバナンス警告のみ（警告行あり） → reasonの冒頭がNO_RESUMMARY_PREFIX", ok, "")
    )

    # --- 2. ガバナンス警告のみ（警告行を特定できないフォールバック経路） ---
    reason_fallback = module.build_governance_reason(1, "【警告】を含まない予期しない標準出力")
    ok = bool(reason_fallback) and reason_fallback.startswith(prefix)
    results.append(
        ("D-0096-2. ガバナンス警告のみ（フォールバック経路） → reasonの冒頭がNO_RESUMMARY_PREFIX", ok, "")
    )

    # returncode == 0（警告なし）ではNoneを返すことも併せて確認する（誤検知防止）
    ok = module.build_governance_reason(0, "異常なし") is None
    results.append(("D-0096-2b. ガバナンス警告なし（returncode=0） → build_governance_reason()はNone", ok, ""))

    # --- 3. トークン追記のみ ---
    token_reason = module.build_token_reason("トークン使用量: (テスト値)")
    ok = bool(token_reason) and token_reason.startswith(prefix)
    results.append(
        ("D-0096-3. トークン追記のみ → reasonの冒頭がNO_RESUMMARY_PREFIX", ok, "")
    )

    # --- 4. 未commit検知のみ ---
    tmpdir = tempfile.mkdtemp(prefix="stophook_test_prefix_")
    try:
        _make_dirty_repo(tmpdir, "scripts/_dummy_dirty_prefix.txt")
        git_reason = module.check_git_dirty(tmpdir)
        ok = bool(git_reason) and git_reason.startswith(prefix)
        results.append(
            ("D-0096-4. 未commit検知のみ → reasonの冒頭がNO_RESUMMARY_PREFIX", ok, "")
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return results


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    module = _load_module()
    heading = module.SUMMARY_HEADING
    detect = module.has_summary_heading_in

    cases = [
        # (説明, 入力メッセージ, 期待結果)
        ("無装飾（D-0080指示の1）: 「- 見出し」", "- %s\n本文" % heading, True),
        ("素の見出し行（装飾なし）", "%s\n本文" % heading, True),
        ("#見出し（D-0080指示の2）: ## 見出し", "## %s\n- 項目1\n- 項目2" % heading, True),
        ("### 見出し（#の個数違い）", "### %s\n本文" % heading, True),
        ("# 見出し（1個）", "# %s" % heading, True),
        (
            "太字（D-0080指示の3・実際にc3e43d4eセッションで発生した形）: **見出し**",
            "---\n\n**%s**\n- 項目1" % heading,
            True,
        ),
        ("__見出し__（アンダースコア太字）", "__%s__\n本文" % heading, True),
        ("見出しの前後に空白を含む ##見出し", "##  %s  \n本文" % heading, True),
        ("絵文字付き見出し: ## 📋 見出し", "## 📋 %s" % heading, True),
        (
            "地の文中の言及（行内に含まれる・意図的に緩めた判定のため今はTrue）",
            "この応答には「%s」という文言を含む応答が必要です。" % heading,
            True,
        ),
        ("見出しが存在しない", "## 【AIが今日やったこと／明日やること】\n本文", False),
        ("空文字列", "", False),
    ]

    failures = []
    total = 0

    print("=== 固定サマリー見出しの検知（D-0071・D-0081） ===")
    for description, message, expected in cases:
        total += 1
        actual = detect(message)
        status = "OK" if actual == expected else "NG"
        if actual != expected:
            failures.append(description)
        print("[%s] %s (expected=%s, actual=%s)" % (status, description, expected, actual))

    print("\n=== 未commit検知とblock()出力の単一性（D-0080・D-0082） ===")
    for description, ok, detail in run_git_and_reason_cases(module):
        total += 1
        status = "OK" if ok else "NG"
        if not ok:
            failures.append(description)
        suffix = " — %s" % detail if detail else ""
        print("[%s] %s%s" % (status, description, suffix))

    print("\n=== NO_RESUMMARY_PREFIXの3箇所一致（D-0096） ===")
    for description, ok, detail in run_prefix_consistency_cases(module):
        total += 1
        status = "OK" if ok else "NG"
        if not ok:
            failures.append(description)
        suffix = " — %s" % detail if detail else ""
        print("[%s] %s%s" % (status, description, suffix))

    print("\n=== main()の結線検証（D-0096補強・block()1回集約） ===")
    for description, ok, detail in run_main_integration_cases(module):
        total += 1
        status = "OK" if ok else "NG"
        if not ok:
            failures.append(description)
        suffix = " — %s" % detail if detail else ""
        print("[%s] %s%s" % (status, description, suffix))

    if failures:
        print("\n失敗: %d件 / 全%d件" % (len(failures), total))
        for description in failures:
            print("  - %s" % description)
        sys.exit(1)
    else:
        print("\n全%d件のテストにパスしました。" % total)
        sys.exit(0)


if __name__ == "__main__":
    main()
