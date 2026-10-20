# -*- coding: utf-8 -*-
r""".claude/hooks/block-ask-in-scheduled-daily.py の判定テスト。

スケジュール実行の日次（オーナー不在）で AskUserQuestion・wrap_up の ask を
拒否し、それ以外は許可することを確かめる。ダミーの jsonl と入力 JSON を一時フォルダに
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
            ("最初の発言が pasted_content の【実行環境】（窓口指示）→ 許可", "allow", None,
             case(tmp, "c6", [user('  <pasted_content id="4417">\n【実行環境】新セッション', origin={"kind": "human"})], WRAP_ASK)),
            ("最初の発言が「週次しよう」→ 許可", "allow", None,
             case(tmp, "c7", [user("週次しよう", origin={"kind": "human"})], ASK)),
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
            ok = "質問しないでください" in reason and (must_contain is None or must_contain in reason)
        if ok and expected == "deny" and must_contain is None:
            ok = "ask を外して" not in reason
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
