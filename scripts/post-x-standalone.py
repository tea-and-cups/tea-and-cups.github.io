# -*- coding: utf-8 -*-
r"""X の「記事なし投稿」（記事リンクもピン画像も付けない投稿）を作る・検査する・予約する（S-0027 ③・D-0294）。

毎朝 8:00（日本時間）に1件ずつ、Buffer の createPost を時刻指定（mode=customScheduled）で予約する。
実験 x-standalone（data/experiments.tsv）として、ピン付き投稿の閲覧数が上がるかを前後比較で判定する。
いいね・フォロー・返信は自動化しない。書き手は「AIの紅茶案内人」（D-0245）で、体験は書かない。

本文の置き場所: output/x-posts/YYYY-MM-DD.md（週の初日＝月曜の日付・1ファイルに最大7件）
  ## XS-0001
  - 予定日: 2026-10-28
  - 材料: <記事slug> ＃<見出し>
  - 本文: <1行目>
    <2行目以降は行頭に半角スペース2つ>
  - 審査: 公開可 2026-10-27        （pin_review.REVIEW_LINE_RE と同じ書式。quality-reviewer の公開可のあとに足す）

台帳: data/x-standalone-posted.tsv（このスクリプトだけが書く。手で編集しない）
  列: ID／予定日時／dueAt／postId／本文ファイル／状態／記録日
  - 予定日時は日本時間（YYYY-MM-DD 08:00）、dueAt は createPost へ渡した UTC
  - 状態は 予約済み／失敗。二重予約の判定は「予約済み」の行だけを見る（失敗は次回に再試行される）
  - experiments.py は予約済みの postId を読み、記事なし投稿を X・Threads の集計から除く

使い方:
  python site/scripts/post-x-standalone.py --candidates 14
      材料の候補を出す。候補は公開済み記事の「よくある質問」の1問1答と、見出しに「選び方」「目安」を
      含む節の判定単位（check-fact-source.py の build_units）。check-fact-source.py の A〜G・体験表現
      （RE_EXPERIENCE）・型Y（型1〜10）・価格（円）に当たる単位、商品リンク・表の単位は除く。
      予定日が直近8週以内の件で材料に使った slug は除き、カテゴリが偏らないように順に並べる。
  python site/scripts/post-x-standalone.py --check <md>
      各件を検査する（下記）。審査行が無い件は【警告】（--post では送らない）。NG があれば終了コード1。
  python site/scripts/post-x-standalone.py --post <md> [--dry-run]
      検査に通り、審査済みで、台帳に予約済みが無い件を、予定日の 08:00（日本時間）に時刻指定で予約する。
      送らない件: 審査行が無い／台帳に予約済み／同じ予定日が予約済み／予定日時が過去。
      停止スイッチ（data/buffer-auto-post-off*・post-pins-to-buffer.py と共通）が有効なら何も送らない。
      1件でも createPost が拒否されたら、そこで止める（残りは送らない・代わりの方式は試さない）。
  python site/scripts/post-x-standalone.py --status
      読み取りだけ。Buffer のキュー（status=scheduled）を引き、台帳の予約済みの postId ごとに
      キューでの status・dueAt・画像の有無を出す。続けて post-pins-to-buffer.py の画像の掃除と同じ判定
      （fetch_scheduled_pin_numbers）を本物のキューにかけ、止まらないかを示す。

検査（--check・--post の前提）:
  - 文字数: check-x-post-length.py の x_weight と raw_length がともに 280 以下
  - URL が無い。ハッシュタグは2件以内
  - 体験表現（check-fact-source.py の RE_EXPERIENCE）・型Y（型1〜10）・A〜G（価格を含む）に当たらない
  - 健康の断定語（HEALTH_WORDS。「〜といわれる」の文中でも NG）に当たらない
  - ID（XS-NNNN）が他の件・他のファイルと重複しない。予定日がファイルの週（月〜日）に入る

終了コード: 0=正常（送らなかった件があっても理由つきで0）/ 1=検査NG・createPost の拒否・入力不備 / 2=使い方
"""

import argparse
import datetime as dt
import glob
import importlib.util
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
POSTS_DIR = os.path.join(ROOT, "site", "src", "content", "posts")
X_POSTS_DIR = os.path.join(ROOT, "output", "x-posts")
LEDGER = os.path.join(ROOT, "data", "x-standalone-posted.tsv")

if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import pin_review  # noqa: E402  （審査行の書式の正本。.envもAPIも触らない）

LEDGER_COLUMNS = ("ID", "予定日時", "dueAt", "postId", "本文ファイル", "状態", "記録日")
STATE_RESERVED = "予約済み"
STATE_FAILED = "失敗"

JST = dt.timezone(dt.timedelta(hours=9))
POST_HOUR_JST = 8
MAX_ITEMS_PER_FILE = 7
HASHTAG_LIMIT = 2
MATERIAL_LOOKBACK_DAYS = 56   # 直近8週に材料に使った slug は候補から除く
MIN_UNIT_CHARS = 40           # これより短い判定単位は材料にしない（中身が薄いため）

# 健康の断定語。「〜といわれる」の文中でも NG（記事なし投稿は出典を付けられないため）
HEALTH_WORDS = (
    "効果", "効能", "予防", "改善", "治る", "治す", "治り", "痩せ", "やせる", "ダイエット", "免疫",
    "殺菌", "抗菌", "抗酸化", "脂肪", "血糖", "血圧", "デトックス", "美肌", "老化", "病気",
    "健康に良", "健康によ", "体に良", "体によ",
)

ID_RE = re.compile(r"^XS-(\d{4})$")
ITEM_HEAD_RE = re.compile(r"^##\s+(XS-\d{4})\s*$")
FIELD_RE = re.compile(r"^-\s*(予定日|材料|本文|審査):\s*(.*)$")
FILE_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")
URL_RE = re.compile(r"https?://|www\.|[A-Za-z0-9-]+\.(?:com|jp|net|org|io|co|me|ly|to)\b", re.I)
HASHTAG_RE = re.compile(r"[#＃][^\s#＃]+")
FAQ_HEADING_RE = re.compile(r"よくある質問|FAQ|Q&A|Q＆A")
GUIDE_HEADING_RE = re.compile(r"選び方|目安")
QUESTION_RE = re.compile(r"^(?:#{3,4}\s*)?(?:\*\*)?Q[.．]\s*(.+?)(?:\*\*)?\s*$")
H2_RE = re.compile(r"^##\s+(.+?)\s*$")
H23_RE = re.compile(r"^#{2,3}\s+(.+?)\s*$")
CATEGORY_RE = re.compile(r"^category:\s*(\S+)\s*$", re.M)

_CACHE = {}


def _load(file_name):
    """ハイフンを含むスクリプトをモジュールとして読み込む（1プロセスにつき1回）。"""
    if file_name not in _CACHE:
        spec = importlib.util.spec_from_file_location(
            file_name[:-3].replace("-", "_"), os.path.join(SCRIPT_DIR, file_name))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _CACHE[file_name] = mod
    return _CACHE[file_name]


def fact():
    return _load("check-fact-source.py")


def xlen():
    return _load("check-x-post-length.py")


def ppb():
    return _load("post-pins-to-buffer.py")


class XPostError(Exception):
    """入力不備・拒否（終了コード1）。"""


# --- 検査 -----------------------------------------------------------------------


def y_hits(text):
    """判定Y（型1〜10）の当たり。型8（gift記事の節単位）は文単位の投稿には当てはまらないため見ない。"""
    fs = fact()
    return fs.safety_advice_hits(text) + fs.food_storage_hits(text) + fs.care_hygiene_hits(text)


def text_problems(text):
    """投稿本文1件の問題点のリスト（空なら OK）。"""
    fs = fact()
    xl = xlen()
    problems = []
    weighted, raw = xl.x_weight(text), xl.raw_length(text)
    if weighted > xl.X_CHAR_LIMIT or raw > xl.X_CHAR_LIMIT:
        problems.append("文字数超過（X重み %d / 実文字数 %d / 上限 %d）" % (weighted, raw, xl.X_CHAR_LIMIT))
    if not text.strip():
        problems.append("本文が空")
    if URL_RE.search(text):
        problems.append("URL を含む（記事なし投稿には載せない）")
    tags = HASHTAG_RE.findall(text)
    if len(tags) > HASHTAG_LIMIT:
        problems.append("ハッシュタグが %d件（上限 %d件）" % (len(tags), HASHTAG_LIMIT))
    m = fs.RE_EXPERIENCE.search(text)
    if m:
        problems.append("体験表現「%s」" % m.group(0))
    for typ, words, _sentence in y_hits(text):
        problems.append("型Y %s（%s）" % (typ, "・".join(words)))
    cats = fs.match_categories(text)
    if "B" in cats:
        problems.append("価格（カテゴリB）")
    others = [c for c in cats if c != "B"]
    if others:
        problems.append("裏取りが要る記述（カテゴリ %s）" % "・".join(others))
    health = [w for w in HEALTH_WORDS if w in text]
    if health:
        problems.append("健康の断定語（%s）" % "・".join(health))
    return problems


# --- 本文ファイルの読み取り -------------------------------------------------------


def parse_x_posts(path):
    """output/x-posts/YYYY-MM-DD.md を読み、件のリストを返す。

    戻り値: [{"id", "date"(date or None), "date_raw", "material", "text", "reviewed", "line"}]
    """
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    items = []
    cur = None
    in_body = False
    for lineno, line in enumerate(lines, 1):
        head = ITEM_HEAD_RE.match(line.strip())
        if head:
            cur = {"id": head.group(1), "date": None, "date_raw": "", "material": "", "body": [],
                   "block": [], "line": lineno}
            items.append(cur)
            in_body = False
            continue
        if cur is None:
            continue
        cur["block"].append(line)
        field = FIELD_RE.match(line)
        if field:
            name, value = field.group(1), field.group(2).strip()
            in_body = name == "本文"
            if name == "予定日":
                cur["date_raw"] = value
                try:
                    cur["date"] = dt.date.fromisoformat(value)
                except ValueError:
                    cur["date"] = None
            elif name == "材料":
                cur["material"] = value
            elif name == "本文":
                cur["body"].append(value)
            continue
        if in_body and line.startswith("  ") and line.strip():
            cur["body"].append(line[2:].rstrip())
            continue
        in_body = False
    for item in items:
        item["text"] = "\n".join(item.pop("body")).strip()
        item["reviewed"] = bool(pin_review.REVIEW_LINE_RE.search("\n".join(item.pop("block"))))
    return items


def all_x_post_files(directory=None):
    return sorted(glob.glob(os.path.join(directory or X_POSTS_DIR, "*.md")))


def check_items(path, items, directory=None):
    """ファイル1つの件を検査する。戻り値: {ID: [問題点]}（問題が無い件は空リスト）と、ファイル全体の問題点。"""
    file_problems = []
    name = os.path.basename(path)
    m = FILE_NAME_RE.match(name)
    week_start = None
    if not m:
        file_problems.append("ファイル名は YYYY-MM-DD.md（週の初日＝月曜の日付）にする: %s" % name)
    else:
        week_start = dt.date.fromisoformat(m.group(1))
        if week_start.weekday() != 0:
            file_problems.append("ファイル名の日付 %s が月曜ではありません" % week_start)
    if not items:
        file_problems.append("件（## XS-NNNN）がありません")
    if len(items) > MAX_ITEMS_PER_FILE:
        file_problems.append("1ファイルの件数が %d件（上限 %d件）" % (len(items), MAX_ITEMS_PER_FILE))

    others = {}
    for other in all_x_post_files(directory):
        if os.path.abspath(other) == os.path.abspath(path):
            continue
        for item in parse_x_posts(other):
            others.setdefault(item["id"], os.path.basename(other))

    result = {}
    seen_ids, seen_dates = set(), set()
    for item in items:
        problems = []
        if item["id"] in seen_ids:
            problems.append("ID がこのファイル内で重複")
        if item["id"] in others:
            problems.append("ID が %s と重複" % others[item["id"]])
        seen_ids.add(item["id"])
        if item["date"] is None:
            problems.append("予定日が YYYY-MM-DD ではありません（%s）" % (item["date_raw"] or "空"))
        else:
            if week_start and not (week_start <= item["date"] <= week_start + dt.timedelta(days=6)):
                problems.append("予定日 %s がファイルの週（%s〜）に入りません" % (item["date"], week_start))
            if item["date"] in seen_dates:
                problems.append("予定日 %s がこのファイル内で重複（1日1件）" % item["date"])
            seen_dates.add(item["date"])
        if not item["material"]:
            problems.append("「- 材料:」行がありません")
        problems.extend(text_problems(item["text"]))
        result[item["id"]] = problems
    return result, file_problems


def cmd_check(path, out=print, directory=None):
    items = parse_x_posts(path)
    result, file_problems = check_items(path, items, directory)
    xl = xlen()
    ng = len(file_problems)
    for problem in file_problems:
        out("[NG] %s: %s" % (os.path.basename(path), problem))
    for item in items:
        problems = result[item["id"]]
        tags = len(HASHTAG_RE.findall(item["text"]))
        summary = "X重み %d / 実文字数 %d / ハッシュタグ %d" % (
            xl.x_weight(item["text"]), xl.raw_length(item["text"]), tags)
        if problems:
            ng += 1
            out("[NG] %s %s  %s" % (item["id"], item["date_raw"], summary))
            for problem in problems:
                out("       %s" % problem)
        else:
            out("[OK] %s %s  %s" % (item["id"], item["date_raw"], summary))
        if not item["reviewed"]:
            out("       【警告】審査行（- 審査: 公開可 YYYY-MM-DD）がありません（--post では送りません）")
    out("X_STANDALONE_CHECK_%s %d件中 NG %d件" % ("NG" if ng else "OK", len(items), ng))
    return 1 if ng else 0


# --- 台帳 -----------------------------------------------------------------------


def load_ledger(path=None):
    path = path or LEDGER
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, encoding="utf-8") as f:
        header = None
        for line in f:
            line = line.rstrip("\r\n")
            if not line.strip():
                continue
            cells = line.split("\t")
            if header is None:
                header = cells
                if tuple(header) != LEDGER_COLUMNS:
                    raise XPostError("%s のヘッダーが想定と違います" % path)
                continue
            cells += [""] * (len(LEDGER_COLUMNS) - len(cells))
            rows.append(dict(zip(LEDGER_COLUMNS, cells)))
    return rows


def append_ledger(row, path=None):
    """1件ごとに追記する（まとめ書きしない。途中で止まっても予約済みの件を取りこぼさないため）。"""
    path = path or LEDGER
    exists = os.path.isfile(path)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        if not exists:
            f.write("\t".join(LEDGER_COLUMNS) + "\n")
        f.write("\t".join(str(row.get(c, "")).replace("\t", " ").replace("\n", " ")
                          for c in LEDGER_COLUMNS) + "\n")


def reserved_rows(rows):
    return [r for r in rows if r["状態"] == STATE_RESERVED]


# --- 予約 -----------------------------------------------------------------------


def due_at_utc(date):
    """予定日の 08:00（日本時間）を UTC の ISO 8601（Buffer の例と同じ ...000Z 形式）で返す。"""
    local = dt.datetime(date.year, date.month, date.day, POST_HOUR_JST, 0, tzinfo=JST)
    return local.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def build_input(channel_id, text, due_at):
    """createPost の入力。mode=customScheduled は Buffer の仕様書
    （https://developers.buffer.com/examples/create-scheduled-post.html）の時刻指定の値。"""
    return {
        "channelId": channel_id,
        "text": text,
        "mode": "customScheduled",
        "schedulingType": "automatic",
        "dueAt": due_at,
        "assets": [],
    }


def create_post(graphql, payload):
    """createPost を1回呼ぶ。戻り値: (成功したか, postId, dueAt, 説明)。
    GraphQL の errors に出ない typed mutation error（MutationError）があるため __typename も見る。"""
    data = graphql(ppb().CREATE_POST_MUTATION, {"input": payload}, operation_name="CreatePost")
    result = (data or {}).get("createPost") or {}
    if result.get("__typename") == "PostActionSuccess":
        post = result.get("post") or {}
        if post.get("id"):
            return True, post.get("id"), post.get("dueAt"), "status=%s" % post.get("status")
        return False, None, None, "PostActionSuccess だが post.id がありません: %s" % result
    return False, None, None, "%s: %s" % (result.get("__typename") or "(型不明)", result.get("message") or result)


def plan_items(items, rows, now):
    """送る件と送らない件（理由つき）に分ける。戻り値: ([item], [(item, 理由)])"""
    reserved = reserved_rows(rows)
    reserved_ids = {r["ID"] for r in reserved}
    reserved_dates = {r["予定日時"][:10] for r in reserved}
    send, skipped = [], []
    for item in sorted(items, key=lambda i: (i["date"] or dt.date.max, i["id"])):
        if item["id"] in reserved_ids:
            skipped.append((item, "台帳に予約済み"))
        elif not item["reviewed"]:
            skipped.append((item, "審査行が無い（quality-reviewer の公開可が必要）"))
        elif item["date"].isoformat() in reserved_dates:
            skipped.append((item, "同じ予定日 %s に別の件が予約済み" % item["date"]))
        elif dt.datetime.fromisoformat(due_at_utc(item["date"]).replace(".000Z", "+00:00")) <= now:
            skipped.append((item, "予定日時が過去（%s 08:00 日本時間）" % item["date"]))
        else:
            send.append(item)
            reserved_dates.add(item["date"].isoformat())
    return send, skipped


def cmd_post(path, dry_run=False, out=print, graphql=None, now=None, ledger_path=None, directory=None,
             channels=None, today=None):
    # 停止スイッチ（post-pins-to-buffer.py と共通の data/buffer-auto-post-off*）。他のどの処理よりも先。
    switch = ppb().check_kill_switch()
    if switch:
        out("緊急停止スイッチが有効です: data/%s" % switch)
        out("X単独投稿の予約は行いません。")
        return 0

    items = parse_x_posts(path)
    result, file_problems = check_items(path, items, directory)
    ng = file_problems + ["%s: %s" % (i, "／".join(p)) for i, p in result.items() if p]
    if ng:
        for problem in ng:
            out("[NG] %s" % problem)
        out("検査に通らない件があるため、1件も予約しません（--check で確認してください）。")
        return 1

    now = now or dt.datetime.now(dt.timezone.utc)
    rows = load_ledger(ledger_path)
    send, skipped = plan_items(items, rows, now)
    held = [i["id"] for i, reason in skipped if reason.startswith("審査行")]
    if held:
        out("HELD_UNREVIEWED: %s" % ", ".join(held))
    for item, reason in skipped:
        out("SKIP %s %s — %s" % (item["id"], item["date_raw"], reason))
    if not send:
        out("予約する件はありません。")
        return 0

    rel = os.path.relpath(os.path.abspath(path), ROOT).replace("\\", "/")
    if dry_run:
        for item in send:
            payload = build_input("<twitter の channelId>", item["text"], due_at_utc(item["date"]))
            out("DRY_RUN %s %s 08:00 JST → dueAt=%s mode=%s schedulingType=%s assets=%s"
                % (item["id"], item["date"], payload["dueAt"], payload["mode"], payload["schedulingType"],
                   payload["assets"]))
            out("  本文: %s" % item["text"].replace("\n", " / "))
        out("--dry-run のため createPost は呼びません（予約予定 %d件）。" % len(send))
        return 0

    if graphql is None:
        from env_loader import get_env, EnvLoaderError  # noqa: E402
        from buffer_api import graphql as real_graphql  # noqa: E402
        try:
            state, messages = ppb().check_key_expiry(dt.date.today(), get_env)
        except EnvLoaderError as e:
            out("【エラー】%s" % e)
            return 1
        for line in messages:
            out(line)
        if state in ("expired", "invalid"):
            return 1
        graphql = real_graphql
    channels = channels if channels is not None else ppb().load_channels()
    if "twitter" not in channels:
        out("【エラー】data/buffer-channels.tsv に twitter のチャンネルがありません。")
        return 1
    channel_id = channels["twitter"][0]
    record_day = (today or dt.date.today()).isoformat()

    from buffer_api import BufferApiError, BufferGuardError  # noqa: E402
    for item in send:
        due = due_at_utc(item["date"])
        payload = build_input(channel_id, item["text"], due)
        try:
            ok, post_id, returned_due, detail = create_post(graphql, payload)
        except (BufferApiError, BufferGuardError) as e:
            ok, post_id, returned_due, detail = False, None, None, "%s: %s" % (type(e).__name__, e)
        row = {"ID": item["id"], "予定日時": "%s %02d:00" % (item["date"], POST_HOUR_JST), "dueAt": due,
               "postId": post_id or "-", "本文ファイル": rel, "状態": STATE_RESERVED if ok else STATE_FAILED,
               "記録日": record_day}
        append_ledger(row, ledger_path)
        if not ok:
            out("REJECTED %s %s — %s" % (item["id"], item["date"], detail))
            out("createPost が拒否されたため、残り %d件は送らずに止めます（台帳には「失敗」を記録）。"
                % (len(send) - send.index(item) - 1))
            return 1
        out("RESERVED %s %s 08:00 JST postId=%s dueAt=%s（返却 %s）%s"
            % (item["id"], item["date"], post_id, due, returned_due, detail))
    out("予約 %d件（台帳 data/x-standalone-posted.tsv へ1件ずつ記録）" % len(send))
    return 0


# --- 予約の確認（読み取りだけ） ----------------------------------------------------


QUEUE_QUERY = """
query XStandaloneQueue($organizationId: OrganizationId!) {
  posts(input: {organizationId: $organizationId, filter: {status: scheduled}}, first: 100) {
    pageInfo { hasNextPage }
    edges { node { id status dueAt channelId assets { source } } }
  }
}
"""


def cmd_status(out=print, graphql=None, ledger_path=None):
    if graphql is None:
        from buffer_api import graphql  # noqa: E402
    rows = reserved_rows(load_ledger(ledger_path))
    data = graphql(ppb().ACCOUNT_QUERY, operation_name="Account")
    orgs = ((data or {}).get("account") or {}).get("organizations") or []
    queue = {}
    truncated = False
    for org in orgs:
        posts = (graphql(QUEUE_QUERY, {"organizationId": org["id"]}, operation_name="XStandaloneQueue")
                 or {}).get("posts") or {}
        truncated = truncated or bool((posts.get("pageInfo") or {}).get("hasNextPage"))
        for edge in posts.get("edges") or []:
            node = edge.get("node") or {}
            queue[node.get("id")] = node
    out("Buffer のキュー（status=scheduled）: %d件%s" % (len(queue), "（1ページに収まらず一部のみ）" if truncated else ""))
    missing = 0
    for row in rows:
        node = queue.get(row["postId"])
        if node is None:
            missing += 1
            out("NOT_IN_QUEUE %s postId=%s 予定 %s（公開済みか取り消し済みの可能性）"
                % (row["ID"], row["postId"], row["予定日時"]))
            continue
        images = sum(1 for a in node.get("assets") or [] if (a or {}).get("source"))
        out("QUEUED %s postId=%s status=%s dueAt=%s 台帳dueAt=%s 一致=%s 画像=%d"
            % (row["ID"], node.get("id"), node.get("status"), node.get("dueAt"), row["dueAt"],
               "はい" if (node.get("dueAt") or "")[:19] == row["dueAt"][:19] else "いいえ", images))
    numbers, note = ppb().fetch_scheduled_pin_numbers(graphql)
    out("画像の掃除の判定（post-pins-to-buffer.py の fetch_scheduled_pin_numbers）: %s — %s"
        % ("止まらない" if numbers is not None else "止まる（削除しない）", note))
    return 0


# --- 候補 -----------------------------------------------------------------------


def article_units(path):
    """公開済み記事1本の材料候補。戻り値: [{"slug","category","title","heading","kind","text"}]"""
    fs = fact()
    text = fs.io_read(path)
    front, body = fs.split_frontmatter(text)
    if not re.search(r"^status:\s*published\s*$", front, re.M):
        return []
    slug = os.path.splitext(os.path.basename(path))[0]
    cat = CATEGORY_RE.search(front)
    category = cat.group(1).strip("'\"") if cat else "(なし)"
    lines = fs.strip_code_blocks(body.splitlines())
    units = []

    # よくある質問: 1問1答を単位にする
    faq = False
    current = None
    for line in lines + ["## (終わり)"]:
        h2 = H2_RE.match(line)
        if h2:
            if current:
                units.append(current)
                current = None
            faq = bool(FAQ_HEADING_RE.search(h2.group(1)))
            continue
        if not faq:
            continue
        q = QUESTION_RE.match(line.strip())
        if q:
            if current:
                units.append(current)
            current = {"heading": "よくある質問「%s」" % q.group(1).strip("*"), "kind": "faq", "lines": [line]}
        elif current is not None:
            current["lines"].append(line)

    # 選び方・目安: 見出しに「選び方」「目安」を含む節（次の同じ階層以上の見出しまで）の判定単位
    for start, end, heading in fs.heading_sections(lines):
        if heading.startswith("**") or FAQ_HEADING_RE.search(heading) or not GUIDE_HEADING_RE.search(heading):
            continue
        section = "\n".join(lines[start + 1:end])
        for unit in fs.build_units(section, start + 2):
            units.append({"heading": heading.lstrip("#").strip(), "kind": "guide",
                          "lines": [l for _, l in unit]})

    out = []
    for unit in units:
        body_text = "\n".join(unit.pop("lines")).strip()
        unit.update({"slug": slug, "category": category, "text": body_text})
        out.append(unit)
    return out


def unit_exclusion(unit):
    """材料にしない理由（無ければ None）。"""
    fs = fact()
    text = unit["text"]
    plain = fs.RE_URL.sub(" ", text)
    if fs.has_affiliate(text):
        return "商品リンク"
    if sum(1 for l in text.splitlines() if l.lstrip().startswith("|")) >= 2:
        return "表"
    cats = fs.match_categories(text)
    if cats:
        return "A〜G（%s）" % "・".join(cats)
    if fs.RE_EXPERIENCE.search(plain):
        return "体験表現"
    for sub in fs.safety_sub_units([(0, l) for l in text.splitlines()]):
        if y_hits(fs.unit_text(sub)):
            return "型Y"
    if "円" in plain:
        return "価格"
    if len(re.sub(r"\s", "", plain)) < MIN_UNIT_CHARS:
        return "短すぎる"
    return None


def recent_material_slugs(today, directory=None):
    """予定日が today の8週前以降の件で、材料に使った slug の集合。"""
    lo = today - dt.timedelta(days=MATERIAL_LOOKBACK_DAYS)
    used = set()
    for path in all_x_post_files(directory):
        for item in parse_x_posts(path):
            if item["date"] and item["date"] >= lo and item["material"]:
                used.add(item["material"].split()[0])
    return used


def next_id(directory=None, ledger_path=None):
    numbers = []
    for path in all_x_post_files(directory):
        numbers += [int(ID_RE.match(i["id"]).group(1)) for i in parse_x_posts(path)]
    numbers += [int(m.group(1)) for m in (ID_RE.match(r["ID"]) for r in load_ledger(ledger_path)) if m]
    return "XS-%04d" % (max(numbers, default=0) + 1)


def interleave(units):
    """カテゴリが偏らないように並べる。同じカテゴリ内は記事ごとに1件ずつ先に出す（slug 順）。"""
    by_cat = {}
    for unit in units:
        by_cat.setdefault(unit["category"], []).append(unit)
    queues = {}
    for cat, cat_units in by_cat.items():
        rounds = {}
        for unit in cat_units:
            rounds.setdefault(unit["slug"], []).append(unit)
        ordered = []
        depth = 0
        while any(len(v) > depth for v in rounds.values()):
            ordered += [rounds[s][depth] for s in sorted(rounds) if len(rounds[s]) > depth]
            depth += 1
        queues[cat] = ordered
    out = []
    while any(queues.values()):
        for cat in sorted(queues):
            if queues[cat]:
                out.append(queues[cat].pop(0))
    return out


def collect_candidates(today, posts_dir=None, directory=None):
    used = recent_material_slugs(today, directory)
    kept, excluded = [], {}
    for path in sorted(glob.glob(os.path.join(posts_dir or POSTS_DIR, "*.md"))):
        for unit in article_units(path):
            if unit["slug"] in used:
                reason = "直近8週に材料に使った slug"
            else:
                reason = unit_exclusion(unit)
            if reason:
                key = reason.split("（")[0]
                excluded[key] = excluded.get(key, 0) + 1
                continue
            kept.append(unit)
    return interleave(kept), excluded, used


def cmd_candidates(n, out=print, today=None, posts_dir=None, directory=None, ledger_path=None):
    today = today or dt.date.today()
    candidates, excluded, used = collect_candidates(today, posts_dir, directory)
    out("X単独投稿の材料候補（上位 %d件・全 %d件・除外 %s・直近8週に使った slug %d本）" % (
        min(n, len(candidates)), len(candidates),
        "／".join("%s %d" % kv for kv in sorted(excluded.items())) or "なし", len(used)))
    for k, unit in enumerate(candidates[:n], 1):
        out("CANDIDATE %d\t[%s]\t%s\t%s" % (k, unit["category"], unit["slug"], unit["heading"]))
        out("  %s" % re.sub(r"\s*\n\s*", " / ", unit["text"])[:200])
    out("NEXT_ID %s" % next_id(directory, ledger_path))
    return 0


# --- main -----------------------------------------------------------------------


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="X の記事なし投稿（S-0027 ③）")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--candidates", type=int, metavar="N")
    group.add_argument("--check", metavar="MD")
    group.add_argument("--post", metavar="MD")
    group.add_argument("--status", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.status:
            return cmd_status()
        if args.candidates is not None:
            return cmd_candidates(args.candidates)
        if args.check:
            return cmd_check(args.check)
        return cmd_post(args.post, dry_run=args.dry_run)
    except (XPostError, OSError, ValueError) as exc:
        print("【エラー】%s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
