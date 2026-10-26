# -*- coding: utf-8 -*-
r""".claude/hooks/block-ask-in-scheduled-daily.py の判定テスト。

スケジュール実行の日次（オーナー不在）と、添付を除いて30字以内の週次・月次の一言で始まる
セッションで AskUserQuestion・wrap_up の ask を拒否し、それ以外は許可することを確かめる。ダミーの jsonl と入力 JSON を一時フォルダに
作り、フックをサブプロセスとして起動して、標準出力の JSON（deny の有無）で判定する。
ダミーの user 行の形は、実際の transcript（日次・窓口指示・週次）で確認した形に合わせている。
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PROJECT_DIR = Path(__file__).resolve().parents[2]
HOOK = PROJECT_DIR / ".claude" / "hooks" / "block-ask-in-scheduled-daily.py"

DAILY_FIRST = {
    "type": "user",
    "origin": {"kind": "task-notification", "subkind": "scheduled-trigger"},
    "message": {"role": "user", "content": '<scheduled-task name="daily-routine" file="C:\\x\\SKILL.md">\n今日の記事書いてください。'},
}


def user(text, **extra):
    d = {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}
    d.update(extra)
    return d


def tool_result():
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}}


def assistant():
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "作業します"}]}}


STOP_FEEDBACK = user("Stop hook feedback:\n固定サマリー全体を再出力しないこと。", isMeta=True)
TASK_NOTIFICATION = user("<task-notification>\n<task-id>abc</task-id>", origin={"kind": "task-notification"})
PEER = user('Another Claude session sent a message: <agent-message from="a1">', isMeta=True, origin={"kind": "peer"})
CSV2 = '@"C:\\Users\\shash\\Downloads\\report-payment-daily-20261024081549.csv" @"C:\\Users\\shash\\Downloads\\monthly (1).csv"'
WEEKLY_MARK = "確認せず推奨案で進め"
WINDOW_MARK = "窓口の指示文の実行中は、選択肢でオーナーに質問しない"
CRITERIA = ("(1) 食い違いが場所・方法・名称・文言の違い", "(2) 目的・完了条件・変更範囲が変わる場合", "迷う場合は (2)")
OWNER = user("上限をリセットして先行ピン360の画像生成を再開してください。", origin={"kind": "human"})

ASK = ("AskUserQuestion", {"questions": [{"question": "どちらにしますか？"}]})
WRAP_ASK = ("mcp__ccd_turn__wrap_up", {"recap": "済み", "ask": "ピンを削除しますか？", "actions": []})
WRAP_NO_ASK = ("mcp__ccd_turn__wrap_up", {"recap": "済み"})


def run_hook(stdin_text):
    env = dict(os.environ, BLOCK_ASK_LOG=str(Path(tempfile.gettempdir()) / "test-block-ask.log"))
    r = subprocess.run([sys.executable, str(HOOK)], input=stdin_text, capture_output=True,
                       text=True, encoding="utf-8", timeout=10, env=env)
    out = (r.stdout or "").strip()
    reason = ""
    decision = "allow"
    if out:
        o = json.loads(out)["hookSpecificOutput"]
        decision = o["permissionDecision"]
        reason = o["permissionDecisionReason"]
    return r.returncode, decision, reason, r.stderr


def case(tmp, name, entries, tool, transcript="write", raw_stdin=None):
    path = Path(tmp) / (name + ".jsonl")
    if transcript == "write":
        path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n", encoding="utf-8")
    elif transcript == "broken":
        path.write_text("{これはJSONではない\n", encoding="utf-8")
    data = {"session_id": "s", "hook_event_name": "PreToolUse", "tool_name": tool[0], "tool_input": tool[1]}
    if transcript != "none":
        data["transcript_path"] = str(path)
    return run_hook(raw_stdin if raw_stdin is not None else json.dumps(data, ensure_ascii=False))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        cases = [
            ("日次・オーナー発言なし・AskUserQuestion → 拒否", "deny", None,
             case(tmp, "c1", [DAILY_FIRST, assistant(), tool_result(), STOP_FEEDBACK], ASK)),
            ("日次・オーナー発言なし・wrap_up ask あり → 拒否（ask を外して）", "deny", "ask を外して",
             case(tmp, "c2", [DAILY_FIRST, assistant(), tool_result()], WRAP_ASK)),
            ("日次・オーナー発言なし・wrap_up ask なし → 許可", "allow", None,
             case(tmp, "c3", [DAILY_FIRST, assistant(), tool_result()], WRAP_NO_ASK)),
            ("日次・wrap_up ask が空白だけ → 許可", "allow", None,
             case(tmp, "c3b", [DAILY_FIRST], ("mcp__ccd_turn__wrap_up", {"recap": "済み", "ask": "  "}))),
            ("日次・途中でオーナー手入力あり・AskUserQuestion → 許可", "allow", None,
             case(tmp, "c4", [DAILY_FIRST, STOP_FEEDBACK, PEER, OWNER, tool_result()], ASK)),
            ("日次・Stop hook feedback・task-notification・他セッションだけ → 拒否", "deny", None,
             case(tmp, "c5", [DAILY_FIRST, STOP_FEEDBACK, TASK_NOTIFICATION, PEER, tool_result()], ASK)),
            ("最初の発言が pasted_content の【実行環境】（窓口指示）・wrap_up ask あり → 拒否", "deny", "ask を外して",
             case(tmp, "c6", [user('  <pasted_content id="4417">\n【実行環境】新セッション', origin={"kind": "human"})], WRAP_ASK)),
            ("最初の発言が「週次しよう」→ 拒否（週次・月次）", "deny", WEEKLY_MARK,
             case(tmp, "c7", [user("週次しよう", origin={"kind": "human"})], ASK)),
            ("10-24の形（添付2件＋改行＋「週次して」）・wrap_up ask あり → 拒否（ask を外して）", "deny", "ask を外して",
             case(tmp, "c7b", [user(CSV2 + "\n週次して", origin={"kind": "human"}), assistant(), tool_result()], WRAP_ASK)),
            ("10-24の形（content が文字列）・wrap_up ask あり → 拒否", "deny", WEEKLY_MARK,
             case(tmp, "c7b2", [{"type": "user", "origin": {"kind": "human"},
                                 "message": {"role": "user", "content": CSV2 + "\n週次して"}}], WRAP_ASK)),
            ("「月次して」→ 拒否", "deny", WEEKLY_MARK,
             case(tmp, "c7c", [user("月次して", origin={"kind": "human"})], ASK)),
            ("週次・途中でオーナー手入力あり・AskUserQuestion → 拒否", "deny", WEEKLY_MARK,
             case(tmp, "c7d", [user("週次して", origin={"kind": "human"}), STOP_FEEDBACK, OWNER, tool_result()], ASK)),
            ("引用符なしの @パス ＋「週次して」→ 拒否", "deny", WEEKLY_MARK,
             case(tmp, "c7e", [user("@C:\\Users\\shash\\Downloads\\a.csv\n週次して", origin={"kind": "human"})], ASK)),
            ("週次・wrap_up ask なし → 許可", "allow", None,
             case(tmp, "c7f", [user("週次して", origin={"kind": "human"})], WRAP_NO_ASK)),
            ("【実行環境】で始まり本文に「週次」を含む（短い）→ 週次扱いにはならず窓口指示として拒否", "deny", WINDOW_MARK,
             case(tmp, "c7g", [user("【実行環境】週次の件", origin={"kind": "human"})], ASK)),
            ("pasted_content の【実行環境】で本文に「週次」を含む（短い）→ 週次扱いにはならず窓口指示として拒否", "deny", WINDOW_MARK,
             case(tmp, "c7h", [user('\n\n<pasted_content id="1">\n【実行環境】週次\n</pasted_content id="1">\n', origin={"kind": "human"})], WRAP_ASK)),
            ("添付を除いても30字を超える週次の発言 → 許可", "allow", None,
             case(tmp, "c7i", [user(CSV2 + "\nおはよう。週次ルーチンをやる前に、まず昨日の続きの状況を教えてください。", origin={"kind": "human"})], ASK)),
            ("「週次」「月次」を含まない短い発言 → 許可", "allow", None,
             case(tmp, "c7j", [user("おはよう", origin={"kind": "human"})], ASK)),
            ("窓口指示・AskUserQuestion → 拒否・理由文に判断基準", "deny", WINDOW_MARK,
             case(tmp, "w1", [user('<pasted_content id="1">\n【実行環境】新セッション\n</pasted_content id="1">', origin={"kind": "human"}), assistant(), tool_result()], ASK)),
            ("窓口指示・wrap_up ask あり → 拒否・ask を外して", "deny", "ask を外して",
             case(tmp, "w2", [user("【実行環境】新セッション ／ 本文", origin={"kind": "human"}), assistant(), tool_result(), STOP_FEEDBACK], WRAP_ASK)),
            ("窓口指示・wrap_up ask なし → 許可", "allow", None,
             case(tmp, "w3", [user("【実行環境】新セッション", origin={"kind": "human"})], WRAP_NO_ASK)),
            ("窓口指示＋【途中確認あり】・AskUserQuestion → 許可", "allow", None,
             case(tmp, "w4", [user("【実行環境】新セッション\n【途中確認あり】", origin={"kind": "human"}), tool_result()], ASK)),
            ("窓口指示＋【途中確認あり】・wrap_up ask あり → 許可", "allow", None,
             case(tmp, "w5", [user("【実行環境】新セッション\n【途中確認あり】", origin={"kind": "human"})], WRAP_ASK)),
            ("窓口指示のあとに【実行環境】なしのオーナー手入力・AskUserQuestion → 許可", "allow", None,
             case(tmp, "w6", [user("【実行環境】新セッション", origin={"kind": "human"}), assistant(), tool_result(), OWNER, tool_result()], ASK)),
            ("窓口指示のあとに【実行環境】なしのオーナー手入力・wrap_up ask あり → 許可", "allow", None,
             case(tmp, "w7", [user("【実行環境】新セッション", origin={"kind": "human"}), OWNER], WRAP_ASK)),
            ("通常の会話の途中で新しい窓口指示（最後が【実行環境】）→ 拒否", "deny", WINDOW_MARK,
             case(tmp, "w8", [user("おはよう", origin={"kind": "human"}), OWNER, user("【実行環境】新セッション", origin={"kind": "human"}), tool_result()], ASK)),
            ("窓口指示の後ろに system-reminder・Stop hook・peer だけ → 拒否のまま", "deny", WINDOW_MARK,
             case(tmp, "w9", [user("【実行環境】新セッション", origin={"kind": "human"}), user("<system-reminder>x</system-reminder>"), STOP_FEEDBACK, PEER, TASK_NOTIFICATION], ASK)),
            ("【途中確認あり】が窓口指示より前の発言にだけある → 拒否", "deny", WINDOW_MARK,
             case(tmp, "w10", [user("【実行環境】前の指示\n【途中確認あり】", origin={"kind": "human"}), user("【実行環境】次の指示", origin={"kind": "human"})], ASK)),
            ("日次の途中で窓口指示風の発言（手入力あり）→ 日次の判定どおり許可", "allow", None,
             case(tmp, "w11", [DAILY_FIRST, user("【実行環境】新セッション", origin={"kind": "human"})], ASK)),
            ("最初の発言が【フック発火テスト】で始まる → 拒否", "deny", None,
             case(tmp, "c8", [user("【フック発火テスト】AskUserQuestion を1回呼び…", origin={"kind": "human"})], ASK)),
            ("transcript_path が無い → 許可", "allow", None,
             case(tmp, "c9", [], ASK, transcript="none")),
            ("transcript の JSON が壊れている → 許可", "allow", None,
             case(tmp, "c10", [], ASK, transcript="broken")),
            ("入力 JSON が壊れている → 許可", "allow", None,
             case(tmp, "c11", [], ASK, raw_stdin="{壊れた")),
            ("transcript のファイルが存在しない → 許可", "allow", None,
             case(tmp, "c12", [], ASK, transcript="missing")),
        ]

    failures = []
    for desc, expected, must_contain, (code, decision, reason, err) in cases:
        ok = code == 0 and decision == expected
        if ok and expected == "deny":
            ok = ("質問しないでください" in reason or WEEKLY_MARK in reason or WINDOW_MARK in reason) and (must_contain is None or must_contain in reason)
        if ok and expected == "deny" and must_contain is None:
            ok = "ask を外して" not in reason
        if ok and expected == "deny" and must_contain == WINDOW_MARK:
            ok = all(c in reason for c in CRITERIA)
        print("[%s] %s%s" % ("OK" if ok else "NG", desc,
                             "" if ok else " — code=%s decision=%s reason=%s stderr=%s" % (code, decision, reason[:40], err.strip())))
        if not ok:
            failures.append(desc)

    if failures:
        print("\n失敗: %d件 / 全%d件" % (len(failures), len(cases)))
        sys.exit(1)
    print("\n全%d件のテストにパスしました。" % len(cases))


if __name__ == "__main__":
    main()
