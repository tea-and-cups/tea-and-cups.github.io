# -*- coding: utf-8 -*-
r"""読み取り専用: 指定日のセッションtranscriptからトークン消費の内訳を集計して表示する。

session-token-usage.py と同じ入力源（%USERPROFILE%\.claude\projects\<project-dir>\*.jsonl
および同ディレクトリの <session_id>\subagents\*.jsonl）を使う。新しい入力源は探しに行かない。

■ 「セッション」の定義
1つのtranscriptファイル（<session_id>.jsonl）= 1セッションとして扱う。
1ファイルが複数の日付（JST）にまたがる場合は、対象日に該当する行だけを集計対象にする
（トークン数はメッセージ単位の値なので、行のタイムスタンプの日付でメッセージを対象日に割り当てる）。

■ 日付の扱い
transcript内のtimestampはUTC（末尾Z）。日本時間（UTC+9）に変換した日付で対象日を判定する。
理由: reports/配下のレポートファイル名（YYYY-MM-DD）はJSTの日次ルーチンに対応しており、
UTCの日付でフィルタするとJST日次と1日ずれるケースがあるため（実測で確認済み）。

■ 重複カウント対策
assistantメッセージはストリーミング中に複数行へ分割記録される（同一message.id）。
message.id単位で重複排除してから集計する（session-token-usage.pyと同じ方式）。

■ 画像トークンの推定方法
tool_result内のbase64画像データがPNGまたはJPEGの場合、ヘッダ（IHDRチャンク／SOFマーカー）
からwidth/heightを実測し、公式の目安式 tokens ≈ (width × height) / 750 で推定する。
それ以外の形式・解析できない場合は「解析不可」として画像の出現回数のみカウントする
（トークン量は合算しない）。実測でtool_result内の画像はJPEGが大半だった（2026-08-15調査）。

■ 対象外・既知の制約（session-token-usage.pyと同じ）
- Remote Control経由・外部チャット窓口経由のセッションはtranscriptがローカルに
  無い場合があり対象外
- 取得できない項目は「取得不可」と明記する。推測値で埋めない

使い方:
  python site/scripts/analyze-session-cost.py [YYYY-MM-DD ...]
  引数省略時は直近3日（実行日を含む）を対象にする。

  python site/scripts/analyze-session-cost.py --chrome-detail <session_id> [区切り文言 ...]
  指定セッションのChrome関連ツール（mcp__claude-in-chrome__* / mcp__Claude_Browser__*）
  呼び出しを実測で集計する（D-0126・作業A）。区切り文言（例:「ダウンロードします」）を
  渡すと、その文言が最初に出現した行を境に何回のChrome呼び出しがあったかも出す
  （1回の画像生成にかかる実測往復数の把握用）。区切り文言を渡さない場合は(4)を省略する。
"""

import base64
import glob
import json
import os
import re
import struct
import sys
from datetime import datetime, timedelta, timezone

USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)

JST = timezone(timedelta(hours=9))

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))

SUBAGENT_NAMES = ("quality-reviewer", "researcher")


def slugify_path_to_project_dir(path):
    return re.sub(r"[^a-zA-Z0-9]", "-", path)


def jst_date(ts_str):
    """UTCのISO8601タイムスタンプ文字列からJSTの日付文字列(YYYY-MM-DD)を返す。取得不可ならNone。"""
    if not ts_str:
        return None
    try:
        ts = ts_str.rstrip("Z")
        dt = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
        return dt.astimezone(JST).strftime("%Y-%m-%d")
    except Exception:
        return None


def png_dimensions(raw):
    try:
        if raw[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        width, height = struct.unpack(">II", raw[16:24])
        return width, height
    except Exception:
        return None


def jpeg_dimensions(raw):
    """JPEGバイト列からSOFマーカーを走査してwidth/heightを実測する。失敗時はNone。"""
    try:
        if raw[0:2] != b"\xff\xd8":
            return None
        i = 2
        n = len(raw)
        sof_markers = set(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
        while i + 9 < n:
            if raw[i] != 0xFF:
                i += 1
                continue
            marker = raw[i + 1]
            if marker in sof_markers:
                height, width = struct.unpack(">HH", raw[i + 5:i + 9])
                return width, height
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            seg_len = struct.unpack(">H", raw[i + 2:i + 4])[0]
            i += 2 + seg_len
        return None
    except Exception:
        return None


def image_dimensions(b64data, media_type):
    """先頭一定バイトをデコードして画像の寸法を実測する。PNG/JPEGのみ対応。"""
    try:
        # SOF/IHDRがヘッダ直後の広めの範囲に来る想定で余裕を持ってデコードする
        # (EXIF等が入るJPEGでも足りるよう先頭64000文字=約48000バイト分をデコード)
        chunk = b64data[:64000]
        chunk = chunk[: len(chunk) - (len(chunk) % 4)]
        raw = base64.b64decode(chunk, validate=False)
    except Exception:
        return None
    if "png" in media_type:
        return png_dimensions(raw)
    if "jpeg" in media_type or "jpg" in media_type:
        return jpeg_dimensions(raw)
    return None


def list_project_jsonl_files():
    project_dir = slugify_path_to_project_dir(PROJECT_ROOT)
    userprofile = os.environ.get("USERPROFILE")
    if not userprofile:
        return None, []
    base_dir = os.path.join(userprofile, ".claude", "projects", project_dir)
    if not os.path.isdir(base_dir):
        return base_dir, []
    files = []
    for path in glob.glob(os.path.join(base_dir, "*.jsonl")):
        if path.endswith(".ccr-tip.json"):
            continue
        files.append(path)
    return base_dir, files


class SessionStats(object):
    def __init__(self, session_id):
        self.session_id = session_id
        self.main_totals = {k: 0 for k in USAGE_KEYS}
        self.sub_totals = {k: 0 for k in USAGE_KEYS}
        self.msg_count = 0
        self.sub_msg_count = 0
        self.tool_counts = {}
        self.image_count = 0
        self.image_tokens_known = 0
        self.image_unresolved = 0
        self.subagent_launches = {name: 0 for name in SUBAGENT_NAMES}
        self.turns = []  # list of (total_tokens, tool_names, kind)

    def total(self, totals):
        return sum(totals[k] for k in USAGE_KEYS)


def process_main_file(path, target_date, stats):
    """1つのメインtranscriptを処理する。

    注意（実測で確認済み・2026-08-15調査）: 同一message.idのassistant行は
    「ストリーミング途中の増分スナップショット」ではなく、1つの論理メッセージの
    contentブロック（thinking/tool_use等）が複数行に分割されて記録されたもの。
    usage値は各行で同一（重複）だが、contentブロックは行ごとに異なる。
    そのため単純な「message.id単位で最初の1行だけ採用」という重複排除では
    tool_use等のブロックを取りこぼす（analyze-session-cost.py開発時に発見）。
    ここでは message.id ごとにcontentブロックを結合してから集計する。
    """
    assistant_groups = {}
    order = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            otype = obj.get("type")
            message = obj.get("message") or {}

            if otype == "assistant":
                msg_id = message.get("id")
                if msg_id is None:
                    continue
                grp = assistant_groups.get(msg_id)
                if grp is None:
                    grp = {"timestamp": obj.get("timestamp"), "usage": {}, "content": []}
                    assistant_groups[msg_id] = grp
                    order.append(msg_id)
                grp["content"].extend(message.get("content") or [])
                usage = message.get("usage")
                if usage:
                    grp["usage"] = usage

            elif otype == "user":
                ts_date = jst_date(obj.get("timestamp"))
                if ts_date != target_date:
                    continue
                content = message.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") != "tool_result":
                        continue
                    inner = block.get("content")
                    if not isinstance(inner, list):
                        continue
                    for item in inner:
                        if isinstance(item, dict) and item.get("type") == "image":
                            stats.image_count += 1
                            source = item.get("source") or {}
                            data = source.get("data")
                            media_type = source.get("media_type", "")
                            dims = None
                            if data:
                                dims = image_dimensions(data, media_type)
                            if dims:
                                w, h = dims
                                stats.image_tokens_known += int((w * h) / 750)
                            else:
                                stats.image_unresolved += 1

    for msg_id in order:
        grp = assistant_groups[msg_id]
        ts_date = jst_date(grp["timestamp"])
        if ts_date != target_date:
            continue
        stats.msg_count += 1
        usage = grp["usage"]
        turn_total = 0
        for k in USAGE_KEYS:
            v = usage.get(k, 0) or 0
            stats.main_totals[k] += v
            turn_total += v
        tool_names = []
        for block in grp["content"]:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                name = block.get("name") or "unknown"
                tool_names.append(name)
                stats.tool_counts[name] = stats.tool_counts.get(name, 0) + 1
                if name == "Agent":
                    sub_type = (block.get("input") or {}).get("subagent_type")
                    if sub_type in stats.subagent_launches:
                        stats.subagent_launches[sub_type] += 1
        kind = "tool:" + ",".join(tool_names) if tool_names else "text/thinking"
        stats.turns.append((turn_total, kind))


def process_subagent_file(path, target_date, stats):
    """このサブエージェントtranscriptに対象日の行が1件でもあればTrueを返す。"""
    seen_ids = set()
    matched = False
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("type") != "assistant":
                continue
            ts_date = jst_date(obj.get("timestamp"))
            if ts_date != target_date:
                continue
            matched = True
            message = obj.get("message") or {}
            msg_id = message.get("id")
            if msg_id is None or msg_id in seen_ids:
                continue
            seen_ids.add(msg_id)
            stats.sub_msg_count += 1
            usage = message.get("usage") or {}
            for k in USAGE_KEYS:
                stats.sub_totals[k] += usage.get(k, 0) or 0
    return matched


def collect_stats_for_date(base_dir, files, target_date):
    result = []
    for path in files:
        session_id = os.path.basename(path)[:-len(".jsonl")]
        stats = SessionStats(session_id)
        # 注意: transcript内のtimestampはUTCだが対象日はJST基準のため、
        # 単純な文字列一致による事前フィルタは使えない（日付がずれる）。
        # 全行を読んでJST変換した上で対象日を判定する。
        process_main_file(path, target_date, stats)
        if stats.msg_count == 0 and stats.image_count == 0:
            # timestampのJST変換結果が対象日と一致する行が実際には無かった
            continue
        # サブエージェント起動回数(d)は process_main_file 側でAgentツール呼び出しの
        # subagent_type引数から集計済み（このsubagents_dir走査はトークン集計のみ行う）。
        subagents_dir = os.path.join(base_dir, session_id, "subagents")
        if os.path.isdir(subagents_dir):
            for sub_path in glob.glob(os.path.join(subagents_dir, "*.jsonl")):
                process_subagent_file(sub_path, target_date, stats)
        result.append(stats)
    return result


def fmt_totals(totals):
    return "input=%d output=%d cache_write=%d cache_read=%d" % (
        totals["input_tokens"],
        totals["output_tokens"],
        totals["cache_creation_input_tokens"],
        totals["cache_read_input_tokens"],
    )


def print_session(stats):
    lines = []
    main_total = sum(stats.main_totals.values())
    sub_total = sum(stats.sub_totals.values())
    lines.append("[session %s]" % stats.session_id)
    lines.append("  (a) main: %s (計%d, msg=%d件)" % (fmt_totals(stats.main_totals), main_total, stats.msg_count))
    if stats.sub_msg_count:
        lines.append("      sub : %s (計%d, msg=%d件)" % (fmt_totals(stats.sub_totals), sub_total, stats.sub_msg_count))

    top_tools = sorted(stats.tool_counts.items(), key=lambda x: -x[1])[:10]
    if top_tools:
        lines.append("  (b) ツール呼び出し上位: " + ", ".join("%s=%d" % (n, c) for n, c in top_tools))
    else:
        lines.append("  (b) ツール呼び出し: 0件")

    if stats.image_count:
        if stats.image_unresolved:
            lines.append(
                "  (c) 画像%d件（推定%dトークン, うち%d件は寸法解析不可のため未算入）"
                % (stats.image_count, stats.image_tokens_known, stats.image_unresolved)
            )
        else:
            lines.append("  (c) 画像%d件（推定%dトークン）" % (stats.image_count, stats.image_tokens_known))
    else:
        lines.append("  (c) 画像: 0件")

    sub_launch_parts = ["%s=%d" % (k, v) for k, v in stats.subagent_launches.items() if v]
    if sub_launch_parts:
        lines.append("  (d) サブエージェント起動: " + ", ".join(sub_launch_parts))
    else:
        lines.append("  (d) サブエージェント起動: 0件")

    top_turns = sorted(stats.turns, key=lambda x: -x[0])[:5]
    if top_turns:
        lines.append("  (e) トークン消費上位ターン:")
        for total, kind in top_turns:
            lines.append("      %d tok - %s" % (total, kind))
    else:
        lines.append("  (e) トークン消費上位ターン: 取得不可（対象メッセージなし）")

    for l in lines[:20]:
        print(l)
    if len(lines) > 20:
        print("  ...(出力を20行に制限。超過分%d行を省略)" % (len(lines) - 20))


def default_dates():
    today = datetime.now(JST).date()
    return [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(2, -1, -1)]


def is_chrome_tool(name):
    n = (name or "").lower()
    return "chrome" in n or "browser" in n


def chrome_detail_report(session_id, boundary_markers=None):
    """指定セッションのChrome関連ツール呼び出しを実測で時系列集計する（読み取り専用）。

    boundary_markers: 「ダウンロードします」等、1回の画像生成完了の目印となる
    テキスト断片のリスト。省略時は自動検出しない（機械的に確実な区切りが無い
    限り推測で区切らないため、呼び出し側が既知の文言を渡す運用とする）。

    出力する集計はすべて記録から機械的に求まる値のみ。推測でラベル付けしない。
    """
    base_dir, files = list_project_jsonl_files()
    if base_dir is None:
        print("集計不可: 環境変数USERPROFILEが取得できません")
        return
    target = None
    for path in files:
        if os.path.basename(path) == session_id + ".jsonl":
            target = path
            break
    if target is None:
        print("集計不可: セッション%sのtranscriptが見つかりません（%s配下）" % (session_id, base_dir))
        return

    tool_use_events = []  # (lineno, id, name, input)
    result_events = []  # (lineno, tool_use_id, has_image)
    text_events = []  # (lineno, text) — assistantのtext/thinking（連続run直前の文脈表示用）
    raw_line_text = {}  # (lineno -> 行全体の生JSON文字列) — 区切り文言検索用（tool_result内の文言も拾う）
    total_lines = 0
    with open(target, encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            total_lines = lineno
            line = line.strip()
            if not line:
                continue
            raw_line_text[lineno] = line
            try:
                obj = json.loads(line)
            except Exception:
                continue
            otype = obj.get("type")
            message = obj.get("message") or {}
            if otype == "assistant":
                for b in message.get("content") or []:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_use":
                        tool_use_events.append((lineno, b.get("id"), b.get("name") or "", b.get("input") or {}))
                    elif b.get("type") == "text":
                        t = (b.get("text") or "").strip().replace("\n", " ")
                        if t:
                            text_events.append((lineno, t))
                    elif b.get("type") == "thinking":
                        t = (b.get("thinking") or "").strip().replace("\n", " ")
                        if t:
                            text_events.append((lineno, t))
            elif otype == "user":
                content = message.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_result":
                        continue
                    inner = block.get("content")
                    has_image = isinstance(inner, list) and any(
                        isinstance(x, dict) and x.get("type") == "image" for x in inner
                    )
                    result_events.append((lineno, block.get("tool_use_id"), has_image))

    chrome_calls = [(ln, tid, name, inp) for (ln, tid, name, inp) in tool_use_events if is_chrome_tool(name)]

    print("=== セッション %s のChrome関連ツール呼び出し実測 ===" % session_id)
    print("transcript総行数: %d" % total_lines)
    print("Chrome関連tool_use件数: %d" % len(chrome_calls))
    print()

    # (1) ツール名別の回数
    name_counts = {}
    for _ln, _tid, name, _inp in chrome_calls:
        name_counts[name] = name_counts.get(name, 0) + 1
    print("--- (1) ツール名別の回数 ---")
    for name, cnt in sorted(name_counts.items(), key=lambda x: -x[1]):
        print("  %-45s %d" % (name, cnt))
    print()

    # computerツールのaction内訳（chrome系のcomputerのみ）
    action_counts = {}
    for _ln, _tid, name, inp in chrome_calls:
        if name.endswith("computer"):
            a = inp.get("action") or "(不明)"
            action_counts[a] = action_counts.get(a, 0) + 1
    if action_counts:
        print("--- computerツールのaction内訳 ---")
        for a, cnt in sorted(action_counts.items(), key=lambda x: -x[1]):
            print("  %-20s %d" % (a, cnt))
        print()

    # (2) 同一/類似操作の連続（同一ツール名の連続run）上位5件
    runs = []
    i = 0
    last_text_by_line = None
    # 直前のtext/thinkingを引くための補助（行番号でソート済み前提）
    text_events_sorted = sorted(text_events, key=lambda x: x[0])

    def context_before(lineno):
        ctx = None
        for tln, t in text_events_sorted:
            if tln < lineno:
                ctx = t
            else:
                break
        return ctx

    while i < len(chrome_calls):
        j = i
        while j + 1 < len(chrome_calls) and chrome_calls[j + 1][2] == chrome_calls[i][2]:
            j += 1
        run_len = j - i + 1
        ctx = context_before(chrome_calls[i][0])
        runs.append((run_len, chrome_calls[i][2], ctx))
        i = j + 1

    print("--- (2) 同一ツールの連続呼び出し 上位5件 ---")
    for run_len, name, ctx in sorted(runs, key=lambda x: -x[0])[:5]:
        ctx_disp = (ctx[:60] if ctx else "取得不可")
        print("  %d回連続 - %s - 直前: %s" % (run_len, name, ctx_disp))
    print()

    # (3) 画像を伴うtool_resultの位置（前半/中盤/後半、transcript全体の行位置基準）
    chrome_ids = {tid for (_ln, tid, _name, _inp) in chrome_calls}
    id_to_name = {tid: name for (_ln, tid, name, _inp) in tool_use_events}
    image_results = [(ln, tid) for (ln, tid, has_image) in result_events if has_image]
    third = total_lines / 3.0
    zenhan = chuban = kouhan = 0
    by_tool = {}
    for ln, tid in image_results:
        name = id_to_name.get(tid, "(取得不可)")
        by_tool[name] = by_tool.get(name, 0) + 1
        if ln < third:
            zenhan += 1
        elif ln < 2 * third:
            chuban += 1
        else:
            kouhan += 1
    print("--- (3) 画像を伴うtool_result（スクリーンショット等）の位置 ---")
    print("  件数=%d（前半=%d 中盤=%d 後半=%d、いずれもtranscript全体の行位置基準）" % (
        len(image_results), zenhan, chuban, kouhan
    ))
    if by_tool:
        print("  発生元ツール内訳: " + "、".join("%s=%d" % (k, v) for k, v in by_tool.items()))
    chrome_screenshot_calls = sum(
        1 for (_ln, _tid, name, inp) in chrome_calls if name.endswith("computer") and inp.get("action") == "screenshot"
    )
    print("  うちcomputer{action:screenshot}呼び出し件数: %d" % chrome_screenshot_calls)
    print()

    # (4) boundary_markersが与えられた場合のみ、区切りごとのChrome呼び出し件数を出す
    if boundary_markers:
        print("--- (4) 指定した区切り文言ごとのChrome呼び出し件数（1回の画像生成の実測往復数） ---")
        # 行の生JSON文字列全体を対象に検索する（assistantのtext/thinkingに限らず、
        # tool_result内の文言（get_page_text等の抽出結果）も拾うため）。
        # マーカーは「1回の完了ごとに出現する文言」を想定し、出現行すべてを区切りとして使う
        # （最初の1回だけを拾うと区切りが1個しか取れず、画像枚数分に分割できない）。
        boundary_lines = sorted(
            {ln for ln, raw in raw_line_text.items() for marker in boundary_markers if marker in raw}
        )
        if not boundary_lines:
            print("  該当する区切り文言が見つかりませんでした（取得不可）: %s" % "、".join(boundary_markers))
        else:
            prev = 0
            segs = []
            for bl in boundary_lines:
                seg = [ln for (ln, _tid, _name, _inp) in chrome_calls if prev < ln <= bl]
                segs.append(len(seg))
                prev = bl
            tail = [ln for (ln, _tid, _name, _inp) in chrome_calls if ln > prev]
            for idx, s in enumerate(segs, start=1):
                print("  区切り%d: Chrome呼び出し%d回" % (idx, s))
            if tail:
                print("  区切り後（末尾）: Chrome呼び出し%d回" % len(tail))
            if segs:
                print("  平均（末尾を除く）: %.1f回/区切り" % (sum(segs) / len(segs)))
        print()


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) >= 3 and sys.argv[1] == "--chrome-detail":
        session_id = sys.argv[2]
        markers = sys.argv[3:] if len(sys.argv) > 3 else None
        chrome_detail_report(session_id, boundary_markers=markers)
        return

    dates = sys.argv[1:]
    if not dates:
        dates = default_dates()
        print("(引数省略のため直近3日を対象: %s)" % ", ".join(dates))

    base_dir, files = list_project_jsonl_files()
    if base_dir is None:
        print("集計不可: 環境変数USERPROFILEが取得できません")
        return
    if not files:
        print("集計不可: transcriptディレクトリが見つかりません: %s" % base_dir)
        return

    for date in dates:
        print("=" * 60)
        print("対象日: %s (JST)" % date)
        sessions = collect_stats_for_date(base_dir, files, date)
        if not sessions:
            print("  該当セッションなし")
            continue

        date_total = {k: 0 for k in USAGE_KEYS}
        date_sub_total = {k: 0 for k in USAGE_KEYS}
        for s in sessions:
            for k in USAGE_KEYS:
                date_total[k] += s.main_totals[k]
                date_sub_total[k] += s.sub_totals[k]
        print(
            "  日合計(main): %s (計%d) / セッション数=%d"
            % (fmt_totals(date_total), sum(date_total.values()), len(sessions))
        )
        if sum(date_sub_total.values()):
            print("  日合計(sub) : %s (計%d)" % (fmt_totals(date_sub_total), sum(date_sub_total.values())))

        for s in sessions:
            print_session(s)


if __name__ == "__main__":
    main()
