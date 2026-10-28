# -*- coding: utf-8 -*-
r"""動画ピンを Buffer 経由で X・Threads へ投稿するスクリプト（動画の第2段・D-0298）。

Buffer の createPost は動画ファイルを受け取らず、公開URLを渡す方式だけのため、動画は
サイトとは別の公開リポジトリ tea-and-cups/video-tmp（GitHub Pages）に一時的に置き、
両チャンネルとも送信済みになったら --cleanup で消す（マスターは output/videos/ に残る）。
video-tmp のクローンは C:\Claude\_runtime\video-tmp（このプロジェクトの親フォルダの _runtime\video-tmp）。

対象: data/video-posted.md（post-video-pins.py の台帳）で Pinterest へ投稿済みの動画のうち、
data/video-buffer-posted.tsv に X（twitter）・Threads の行がまだ無いもの。
Instagram は post-pins-to-buffer.py の PAUSED_CHANNELS（SERVICES）に従い送らない。
AI表示の項目（isAiGenerated・aiAssisted 等）は付けない（Sho 判断・読者にはエンドカードで示す）。

投稿文（動画md の行・1行ずつ）:
  - X用説明文: <答えの1行>          → 送る本文は「<この行>\n<誘導先URL（utm_source=x）>」
  - Threads用文: <説明文の①と③>    → 送る本文は「<この行>\n<誘導先URL（utm_source=threads）>」
  - X・Threads審査: 公開可 YYYY-MM-DD sha256:<64桁> （quality-reviewer の公開可のあとに足す。sha256 は
    動画2以降で必須・投稿する mp4 の現物と照合する。動画1は日付だけの行のまま・D-0302）
  誘導先URLは動画md の「- 誘導先URL:」の utm_source だけを post-pins-to-buffer.py の
  rewrite_utm_source で差し替えたもの（utm_medium=social・utm_campaign=<slug>・utm_content=videoN はそのまま）。

処理順序（1動画ずつ・最初に止まった項目でその動画を止める）:
  (1) 緊急停止スイッチ（data/ 直下の buffer-auto-post-off*・post-pins-to-buffer.py と共通）。あれば何もしない。
  (2) 動画md を読み、post-video-pins.py と同じ検査（項目・utm_content・文字数・審査行の sha256・
      動画2以降は機械QA の qa.json）を通す（check_review を共有）。
  (3) 投稿文の検査: 2行の存在、X は check-x-post-length.py の verdict（実文字数・X重みとも280以下）、
      Threads は実文字数500以下、UTM の4項目、「- X・Threads審査: 公開可」行（動画2以降は sha256 も照合）。
  (3-2) 1日の上限（D-0302）: 当日すでに送った件数（画像ピン＋動画・post-pins-to-buffer.py の
      count_today_posted）＋この動画の送信先の数が DAILY_LIMIT（30）を超えるなら、公開も createPost も
      しない（保留。失敗には数えない）。
  -- --dry-run はここまで（コピー・push・createPost・台帳への書き込みをしない）--
  (4) mp4 を video-tmp に <slug>-video-N.mp4 としてコピー（.nojekyll も置く）、commit・push。
  (5) 公開URLが 200・Content-Type video/mp4・転送なし・長さが現物と一致になるまで30秒間隔で確かめる（上限10分）。
      満たさなければ Buffer へ送らずに止める。
  (6) X・Threads の順に createPost（mode=shareNow・assets は video だけ）。成功の直後に台帳へ1行書く。
      拒否されたら、エラーの全文を出して止める（残りは送らない・別の置き場所は試さない）。
  --publish-only は (4)(5) までで止める（公開URLの事前確認用・createPost も台帳も触らない）。

--cleanup [--wait] [--dry-run]:
  台帳で削除日が空の動画ごとに、全行の postId を Buffer の post で引き、すべて status=sent なら
  video-tmp から git rm して commit・push し、URL が 404 を返すのを確かめてから台帳に削除日を書く。
  1件でも送信済みでなければ消さない。--wait を付けると、送信済みになるまで30秒間隔で確かめる（上限15分）。
  404 が上限（15分）内に確かめられなければ削除日を書かない（次回の --cleanup は404の確認から再開する）。

--status:
  読み取りだけ。台帳の postId ごとに Buffer の status・sentAt・添付の source を出し、
  post-pins-to-buffer.py の画像の掃除の判定（fetch_scheduled_pin_numbers）が、
  (a) その投稿がキューに残っているとき（実際の source の値で組み立てたキュー）と
  (b) 今の本物のキュー で止まるかどうかを出す。

video-tmp の .git が4GBを超えたら【注意】を出す（リポジトリを作り直す目安）。

台帳: data/video-buffer-posted.tsv（このスクリプトだけが書く。手で編集しない）
  列: 動画キー（<slug>-video-N）／service／postId／投稿日時（日本時間）／公開URL／削除日
  experiments.py はこの postId を読み、X・Threads の実験の集計（前・後）から除く。

使い方:
  python site/scripts/post-video-to-buffer.py --dry-run
  python site/scripts/post-video-to-buffer.py
  python site/scripts/post-video-to-buffer.py --publish-only
  python site/scripts/post-video-to-buffer.py --cleanup [--wait] [--dry-run]
  python site/scripts/post-video-to-buffer.py --status
    --md <動画mdのパス> [--ledger <台帳のパス>] は検証用（--md を付けると、その1本だけを対象にする）

終了コード: 0=正常（送らなかった動画があっても理由つきで0）/ 1=止まった動画がある・拒否・入力不備
"""

import datetime as dt
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
LEDGER_PATH = os.path.join(ROOT, "data", "video-buffer-posted.tsv")
VIDEO_TMP_DIR = os.path.join(os.path.dirname(ROOT), "_runtime", "video-tmp")
PUBLIC_URL_BASE = "https://kohaku-jikan.com/video-tmp"

if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

LEDGER_COLUMNS = ("動画キー", "service", "postId", "投稿日時", "公開URL", "削除日")

X_TEXT_RE = re.compile(r"^-\s*X用説明文:\s*(.*)$")
THREADS_TEXT_RE = re.compile(r"^-\s*Threads用文:\s*(.*)$")
SNS_REVIEW_RE = re.compile(r"^-\s*X・Threads審査:\s*公開可\s+(\d{4}-\d{2}-\d{2})(?!\d)"
                           r"(?:\s+sha256:([0-9a-f]{64})(?![0-9a-f]))?", re.M)

THREADS_CHAR_LIMIT = 500
JST = dt.timezone(dt.timedelta(hours=9))
URL_POLL_INTERVAL_SECONDS = 30
URL_POLL_LIMIT_SECONDS = 10 * 60
GONE_POLL_LIMIT_SECONDS = 15 * 60   # Pages の配信キャッシュ（max-age=600）が切れるまでを含める
SENT_POLL_INTERVAL_SECONDS = 30
SENT_POLL_LIMIT_SECONDS = 15 * 60
URL_TIMEOUT_SECONDS = 30
GIT_TIMEOUT = 600
GIT_SIZE_WARN_BYTES = 4 * 1024 ** 3
STATUS_SENT = "sent"

POST_QUERY = """
query VideoPost($id: PostId!) {
  post(input: {id: $id}) { id status sentAt dueAt channelId assets { source } }
}
"""

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


def pvp():
    return _load("post-video-pins.py")


def ppb():
    return _load("post-pins-to-buffer.py")


def xlen():
    return _load("check-x-post-length.py")


class _Stop(Exception):
    """その動画を止める（理由を持つ）。"""


# --- 投稿文 ---------------------------------------------------------------------


def video_key(fields):
    return "%s-video-%d" % (fields["slug"], fields["n"])


def public_url(key):
    return "%s/%s.mp4" % (PUBLIC_URL_BASE, key)


def read_sns_lines(text):
    """動画md の X用説明文・Threads用文（各1行）と、最後の審査行の (審査日, sha256 か空文字) を返す。"""
    found = {"x": [], "threads": []}
    for raw in text.splitlines():
        line = raw.strip()
        for key, regex in (("x", X_TEXT_RE), ("threads", THREADS_TEXT_RE)):
            m = regex.match(line)
            if m:
                found[key].append(m.group(1).strip())
    review = SNS_REVIEW_RE.findall(text)
    return found, (review[-1] if review else None)


def check_utm(url, service, fields):
    expected = {"utm_source": ppb().UTM_SOURCE_BY_SERVICE[service], "utm_medium": "social",
                "utm_campaign": fields["slug"], "utm_content": "video%d" % fields["n"]}
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    bad = ["%s=%s（期待 %s）" % (k, (query.get(k) or ["(なし)"])[0], v)
           for k, v in expected.items() if (query.get(k) or [None])[0] != v]
    if bad:
        raise _Stop("%s の誘導先URLの UTM が違います: %s" % (service, "・".join(bad)))


def build_texts(fields, require_review=True):
    """(3) の検査。戻り値: ({service: 本文}, 結果の行のリスト)。満たさなければ _Stop。
    require_review=False（--publish-only）は審査行を見ない（createPost を呼ばないため）。"""
    found, review = read_sns_lines(fields["md_text"])
    review_date, review_sha = review if review else (None, "")
    lines = []
    for key, label in (("x", "X用説明文"), ("threads", "Threads用文")):
        if len(found[key]) != 1 or not found[key][0]:
            raise _Stop("「- %s:」行がちょうど1行・空でない状態ではありません（%d行）" % (label, len(found[key])))
    texts = {}
    x_url = ppb().rewrite_utm_source(fields["guide_url"], "twitter")
    check_utm(x_url, "twitter", fields)
    ok, text, raw, weighted = xlen().verdict(found["x"][0], x_url)
    if not ok:
        raise _Stop("X の本文が上限を超えます（実文字数 %d / X重み %d / 上限 %d）"
                    % (raw, weighted, xlen().X_CHAR_LIMIT))
    texts["twitter"] = text
    lines.append("X: 実文字数 %d / X重み %d / 上限 %d" % (raw, weighted, xlen().X_CHAR_LIMIT))
    th_url = ppb().rewrite_utm_source(fields["guide_url"], "threads")
    check_utm(th_url, "threads", fields)
    text = "%s\n%s" % (found["threads"][0], th_url)
    raw = xlen().raw_length(text)
    if raw > THREADS_CHAR_LIMIT:
        raise _Stop("Threads の本文が %d字で上限 %d字を超えます" % (raw, THREADS_CHAR_LIMIT))
    texts["threads"] = text
    lines.append("Threads: 実文字数 %d / 上限 %d" % (raw, THREADS_CHAR_LIMIT))
    if not review_date:
        if not require_review:
            lines.append("X・Threads審査: なし（--publish-only のため見ない）")
            return texts, lines
        raise _Stop("「- X・Threads審査: 公開可 YYYY-MM-DD」行がありません（未審査のため投稿しない）")
    if fields["n"] < pvp().QA_GATE_START:
        lines.append("X・Threads審査: 公開可 %s" % review_date)
        return texts, lines
    # 動画 QA_GATE_START 以降は審査行に sha256 を必須にし、現物（check_review が出した fields["sha256"]）と照合する
    if not review_sha:
        raise _Stop("最後の「- X・Threads審査:」行に sha256:<64桁> がありません（動画%d 以降は必須）"
                    % pvp().QA_GATE_START)
    if review_sha != fields["sha256"]:
        raise _Stop("X・Threads審査行の sha256 が一致しません（審査行 %s / 現物 %s）。審査後に動画が変わっています"
                    % (review_sha, fields["sha256"]))
    lines.append("X・Threads審査: 公開可 %s・sha256 が現物と一致" % review_date)
    return texts, lines


# --- 台帳 -----------------------------------------------------------------------


def load_ledger(path=None):
    path = path or LEDGER_PATH
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
                if tuple(cells) != LEDGER_COLUMNS:
                    raise ValueError("%s のヘッダーが想定と違います" % path)
                header = cells
                continue
            cells += [""] * (len(LEDGER_COLUMNS) - len(cells))
            rows.append(dict(zip(LEDGER_COLUMNS, cells)))
    return rows


def _write_rows(rows, path):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(LEDGER_COLUMNS) + "\n")
        for row in rows:
            f.write("\t".join(str(row.get(c, "")).replace("\t", " ").replace("\n", " ")
                              for c in LEDGER_COLUMNS) + "\n")


def append_ledger(row, path=None):
    """1件ごとに追記する（途中で止まっても投稿済みの件を取りこぼさないため）。"""
    path = path or LEDGER_PATH
    exists = os.path.isfile(path)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        if not exists:
            f.write("\t".join(LEDGER_COLUMNS) + "\n")
        f.write("\t".join(str(row.get(c, "")).replace("\t", " ").replace("\n", " ")
                          for c in LEDGER_COLUMNS) + "\n")


def set_deleted(key, day, path=None):
    path = path or LEDGER_PATH
    rows = load_ledger(path)
    for row in rows:
        if row["動画キー"] == key and not row["削除日"]:
            row["削除日"] = day
    _write_rows(rows, path)


def posted_services(rows, key):
    return {r["service"] for r in rows if r["動画キー"] == key}


# --- video-tmp（git） -------------------------------------------------------------


def git(*args):
    return subprocess.run(["git", "-C", VIDEO_TMP_DIR] + list(args), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=GIT_TIMEOUT)


def _git_ok(result, what):
    if result.returncode != 0:
        raise _Stop("git %s に失敗しました: %s" % (what, (result.stderr or result.stdout).strip()))
    return result


def git_dir_size_warning(out):
    total = 0
    for base, _dirs, files in os.walk(os.path.join(VIDEO_TMP_DIR, ".git")):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                pass
    out("video-tmp の .git: %.1fMB" % (total / 1e6))
    if total > GIT_SIZE_WARN_BYTES:
        out("【注意】video-tmp の .git が4GBを超えました（%.2fGB）。リポジトリの作り直しを検討してください"
            % (total / 1024 ** 3))


def commit_and_push(paths, message, out):
    """paths を add して commit・push する。paths が空なら add しない（git rm で既にステージ済みのとき）。"""
    if paths:
        _git_ok(git("add", "--all", "--", *paths), "add")
    staged = git("diff", "--cached", "--quiet")
    if staged.returncode == 1:
        _git_ok(git("commit", "-m", message), "commit")
        out("git commit: %s" % message)
    elif staged.returncode != 0:
        raise _Stop("git diff --cached の判定に失敗しました: %s" % (staged.stderr or staged.stdout).strip())
    ahead = git("rev-list", "--count", "@{u}..HEAD")
    if ahead.returncode == 0 and ahead.stdout.strip() == "0":
        out("git push は差分なしのためスキップ")
        return
    _git_ok(git("push"), "push")
    out("git push 完了")


def stage_video(fields, key, out):
    """(4) mp4 と .nojekyll を video-tmp に置き、commit・push する。"""
    if not os.path.isdir(os.path.join(VIDEO_TMP_DIR, ".git")):
        raise _Stop("video-tmp のクローンがありません: %s" % VIDEO_TMP_DIR)
    _git_ok(git("pull", "--ff-only"), "pull")
    name = "%s.mp4" % key
    dest = os.path.join(VIDEO_TMP_DIR, name)
    if not (os.path.isfile(dest) and pvp().file_sha256(dest) == fields["sha256"]):
        shutil.copyfile(fields["video_path"], dest)
        out("コピー: %s → video-tmp/%s" % (fields["video_rel"], name))
    nojekyll = os.path.join(VIDEO_TMP_DIR, ".nojekyll")
    if not os.path.isfile(nojekyll):
        open(nojekyll, "w").close()
    commit_and_push([name, ".nojekyll"], "add: %s" % name, out)
    git_dir_size_warning(out)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None   # 転送を追わず、3xx をそのまま HTTPError として受け取る


def probe_url(url):
    """戻り値: (HTTPステータス, Content-Type, Content-Length, Location)。通信失敗はステータス None。"""
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, method="HEAD", headers={"Cache-Control": "no-cache"})
    try:
        with opener.open(request, timeout=URL_TIMEOUT_SECONDS) as response:
            headers = response.headers
            status = response.status
    except urllib.error.HTTPError as e:
        headers, status = e.headers, e.code
    except (urllib.error.URLError, OSError) as e:
        return None, "接続失敗: %s" % e, None, None
    ctype = (headers.get("Content-Type") or "").split(";")[0].strip().lower()
    return status, ctype, headers.get("Content-Length"), headers.get("Location")


def describe(probe):
    status, ctype, length, location = probe
    return "HTTP %s / Content-Type %s / Content-Length %s / 転送先 %s" % (
        status, ctype or "(なし)", length or "(なし)", location or "なし")


def wait_public(url, size, out, sleep=time.sleep):
    """(5) 200・video/mp4・転送なし・長さ一致になるまで待つ。戻り値: 最後の状態の説明。満たさなければ _Stop。"""
    deadline = time.time() + URL_POLL_LIMIT_SECONDS
    while True:
        probe = probe_url(url)
        status, ctype, length, location = probe
        out("公開URLの確認: %s → %s" % (url, describe(probe)))
        if status == 200 and ctype == "video/mp4" and not location and str(length) == str(size):
            return describe(probe)
        if status in (301, 302, 303, 307, 308):
            raise _Stop("公開URLが転送されます（%s）。Buffer へは送りません" % describe(probe))
        if status == 200 and ctype and ctype != "video/mp4":
            raise _Stop("公開URLの Content-Type が video/mp4 ではありません（%s）。Buffer へは送りません"
                        % describe(probe))
        if time.time() >= deadline:
            raise _Stop("%d分待っても公開URLが条件を満たしません（%s）。Buffer へは送りません"
                        % (URL_POLL_LIMIT_SECONDS // 60, describe(probe)))
        sleep(URL_POLL_INTERVAL_SECONDS)


def wait_gone(url, out, sleep=time.sleep):
    deadline = time.time() + GONE_POLL_LIMIT_SECONDS
    while True:
        probe = probe_url(url)
        out("削除後の確認: %s → %s" % (url, describe(probe)))
        if probe[0] == 404:
            return True
        if time.time() >= deadline:
            return False
        sleep(URL_POLL_INTERVAL_SECONDS)


# --- Buffer ---------------------------------------------------------------------


def build_input(channel_id, text, video_url):
    """createPost の入力。mode=shareNow（即時）・assets は video だけ。AI表示の項目は付けない。"""
    return {
        "channelId": channel_id,
        "text": text,
        "mode": "shareNow",
        "schedulingType": "automatic",
        "assets": [{"video": {"url": video_url}}],
    }


def create_post(graphql, payload):
    """戻り値: (成功したか, postId, 説明)。MutationError（data 側の型付きエラー）も見る。"""
    data = graphql(ppb().CREATE_POST_MUTATION, {"input": payload}, operation_name="CreatePost")
    result = (data or {}).get("createPost") or {}
    if result.get("__typename") == "PostActionSuccess":
        post = result.get("post") or {}
        if post.get("id"):
            return True, post["id"], "status=%s dueAt=%s" % (post.get("status"), post.get("dueAt"))
        return False, None, "PostActionSuccess だが post.id がありません: %r" % result
    return False, None, "%s: %r" % (result.get("__typename") or "(型不明)", result)


def fetch_post(graphql, post_id):
    return ((graphql(POST_QUERY, {"id": post_id}, operation_name="VideoPost") or {}).get("post")) or {}


def _real_graphql(out):
    """APIキーの期限を確かめ、buffer_api.graphql を返す（期限切れ・不正なら None）。"""
    from env_loader import get_env, EnvLoaderError  # noqa: E402
    from buffer_api import graphql  # noqa: E402
    try:
        state, messages = ppb().check_key_expiry(dt.date.today(), get_env)
    except EnvLoaderError as e:
        out("【エラー】%s" % e)
        return None
    for line in messages:
        out(line)
    return None if state in ("expired", "invalid") else graphql


# --- 投稿 -----------------------------------------------------------------------


def targets_from(md_path, video_ledger_path):
    pinned = pvp().load_ledger(video_ledger_path)["rows"]
    if md_path:
        return [md_path], pinned
    return [path for n, path in pvp().find_video_mds() if n in pinned], pinned


def prepare(path, pinned, rows, out, require_review=True):
    """(2)(3)。戻り値: (fields, 送るサービスのリスト, 本文)。"""
    pp = pvp()._load_post_pins()
    fields = pvp().parse_video_md(path, pp)
    out.append("動画md: %s" % path)
    out += pvp().check_fields(fields, pp)
    if fields["n"] not in pinned:
        raise _Stop("data/video-posted.md に動画%d がありません（Pinterest への投稿が先）" % fields["n"])
    out += pvp().check_review(fields)
    key = video_key(fields)
    done = posted_services(rows, key)
    services = [s for s in ppb().SERVICES if s not in done]
    texts, lines = build_texts(fields, require_review)
    out += lines
    out.append("送信先: %s（台帳に投稿済み: %s・一時停止中: %s）" % (
        "・".join(services) or "なし", "・".join(sorted(done)) or "なし",
        "・".join(sorted(ppb().PAUSED_CHANNELS)) or "なし"))
    return fields, services, texts


def cmd_post(md_path=None, ledger_path=None, video_ledger_path=None, dry_run=False, publish_only=False,
             out=print, graphql=None, channels=None, now=None, stage=None, wait=None):
    switch = ppb().check_kill_switch()
    if switch:
        out("緊急停止スイッチが有効です: data/%s" % switch)
        out("動画の Buffer 投稿は行いません。")
        return 0
    ledger_path = ledger_path or LEDGER_PATH
    targets, pinned = targets_from(md_path, video_ledger_path or pvp().LEDGER_PATH)
    if not targets:
        out("Pinterest へ投稿済みの動画がありません")
        return 0
    stage = stage or stage_video
    wait = wait or wait_public
    stopped = 0
    for path in targets:
        lines = []
        try:
            fields, services, texts = prepare(path, pinned, load_ledger(ledger_path), lines,
                                              require_review=not publish_only)
            key = video_key(fields)
            url = public_url(key)
            if not services and not publish_only:
                for line in lines:
                    out("  [OK] %s" % line)
                out("%s / スキップ（X・Threads とも台帳に投稿済み）" % key)
                continue
            if not publish_only:
                day = (now or dt.datetime.now(JST)).astimezone(JST).date().isoformat()
                today_count = ppb().count_today_posted(day, video_path=ledger_path)
                lines.append("1日の上限: 本日すでに送信 %d件（画像ピン＋動画）＋ この動画 %d件 / 上限 %d件"
                             % (today_count, len(services), ppb().DAILY_LIMIT))
                if today_count + len(services) > ppb().DAILY_LIMIT:
                    for line in lines:
                        out("  [OK] %s" % line)
                    out("%s / 保留（1日の上限を超えるため、公開・createPost をしない。失敗には数えない）" % key)
                    continue
            if dry_run:
                for line in lines:
                    out("  [OK] %s" % line)
                for service in services:
                    payload = build_input("<%s の channelId>" % service, texts[service], url)
                    out("DRY_RUN %s %s mode=%s schedulingType=%s assets=%s"
                        % (key, service, payload["mode"], payload["schedulingType"], payload["assets"]))
                    out("  本文: %s" % texts[service].replace("\n", " / "))
                out("%s / 成功見込み(dry-run・コピー・push・createPost・台帳への書き込みをしない)" % key)
                continue
            if graphql is None and not publish_only:
                graphql = _real_graphql(out)
                if graphql is None:
                    return 1
            stage(fields, key, lines.append)
            lines.append("公開URL: %s" % wait(url, os.path.getsize(fields["video_path"]), lines.append))
            if publish_only:
                for line in lines:
                    out("  [OK] %s" % line)
                out("%s / 公開のみ（--publish-only・createPost は呼ばない）" % key)
                continue
            chans = channels if channels is not None else ppb().load_channels()
            from buffer_api import BufferApiError, BufferGuardError  # noqa: E402
            for service in services:
                if service not in chans:
                    raise _Stop("data/buffer-channels.tsv に %s のチャンネルがありません" % service)
                payload = build_input(chans[service][0], texts[service], url)
                try:
                    ok, post_id, detail = create_post(graphql, payload)
                except (BufferApiError, BufferGuardError) as e:
                    ok, post_id, detail = False, None, "%s: %s" % (type(e).__name__, e)
                if not ok:
                    raise _Stop("createPost（%s）が拒否されました。別の置き場所は試さずに止めます。"
                                "エラーの全文: %s" % (service, detail))
                stamp = (now or dt.datetime.now(JST)).astimezone(JST).isoformat(timespec="seconds")
                append_ledger({"動画キー": key, "service": service, "postId": post_id, "投稿日時": stamp,
                               "公開URL": url, "削除日": ""}, ledger_path)
                lines.append("createPost（%s）: postId=%s %s（台帳に記録）" % (service, post_id, detail))
            label = "成功"
        except (_Stop, pvp()._Stop) as e:   # post-video-pins.py の検査（check_review 等）の停止も同じ扱い
            stopped += 1
            for line in lines:
                out("  [OK] %s" % line)
            out("  [NG] %s" % e)
            out("%s / 停止" % os.path.basename(path))
            continue
        for line in lines:
            out("  [OK] %s" % line)
        out("%s / %s" % (key, label))
    return 1 if stopped else 0


# --- 掃除 -----------------------------------------------------------------------


def post_states(graphql, rows):
    """戻り値: [(row, status, sentAt)]"""
    states = []
    for row in rows:
        post = fetch_post(graphql, row["postId"])
        states.append((row, post.get("status"), post.get("sentAt")))
    return states


def cmd_cleanup(ledger_path=None, dry_run=False, wait=False, out=print, graphql=None, today=None,
                sleep=time.sleep, remove=None, gone=None):
    ledger_path = ledger_path or LEDGER_PATH
    rows = load_ledger(ledger_path)
    keys = []
    for row in rows:
        if not row["削除日"] and row["動画キー"] not in keys:
            keys.append(row["動画キー"])
    if not keys:
        out("削除待ちの動画はありません")
        return 0
    if graphql is None:
        graphql = _real_graphql(out)
        if graphql is None:
            return 1
    remove = remove or remove_video
    gone = gone or wait_gone
    day = (today or dt.date.today()).isoformat()
    result = 0
    for key in keys:
        mine = [r for r in rows if r["動画キー"] == key]
        deadline = time.time() + (SENT_POLL_LIMIT_SECONDS if wait else 0)
        while True:
            states = post_states(graphql, mine)
            for row, status, sent_at in states:
                out("%s %s postId=%s status=%s sentAt=%s" % (key, row["service"], row["postId"], status, sent_at))
            pending = [r for r, status, sent_at in states if status != STATUS_SENT or not sent_at]
            if not pending or time.time() >= deadline:
                break
            out("送信済みでない投稿が %d件。%d秒後に再確認します" % (len(pending), SENT_POLL_INTERVAL_SECONDS))
            sleep(SENT_POLL_INTERVAL_SECONDS)
        if pending:
            out("%s / 消さない（送信済みでない投稿: %s）" % (key, "・".join(r["service"] for r in pending)))
            continue
        url = mine[0]["公開URL"] or public_url(key)
        if dry_run:
            out("%s / 削除見込み(dry-run・git rm・push・台帳への書き込みをしない) %s" % (key, url))
            continue
        try:
            remove(key, out)
        except _Stop as e:
            out("  [NG] %s" % e)
            result = 1
            continue
        if gone(url, out, sleep):
            set_deleted(key, day, ledger_path)
            out("%s / 削除済み（404 を確認・台帳に削除日 %s）" % (key, day))
        else:
            out("【注意】%s を video-tmp から消しましたが、%d分以内に404を確かめられませんでした。"
                "台帳の削除日は空のままです（次回の --cleanup で404の確認から再開します）"
                % (key, GONE_POLL_LIMIT_SECONDS // 60))
            result = 1
    return result


def remove_video(key, out):
    if not os.path.isdir(os.path.join(VIDEO_TMP_DIR, ".git")):
        raise _Stop("video-tmp のクローンがありません: %s" % VIDEO_TMP_DIR)
    _git_ok(git("pull", "--ff-only"), "pull")
    name = "%s.mp4" % key
    if git("ls-files", "--error-unmatch", "--", name).returncode == 0:
        _git_ok(git("rm", "--quiet", "--", name), "rm")
        out("git rm: %s" % name)
    commit_and_push([], "remove: %s" % name, out)
    git_dir_size_warning(out)


# --- 状態の確認（読み取りだけ） ----------------------------------------------------


def cmd_status(ledger_path=None, out=print, graphql=None):
    if graphql is None:
        from buffer_api import graphql  # noqa: E402
    rows = load_ledger(ledger_path or LEDGER_PATH)
    if not rows:
        out("台帳に行がありません")
    for row in rows:
        post = fetch_post(graphql, row["postId"])
        sources = [(a or {}).get("source") for a in post.get("assets") or []]
        out("%s %s postId=%s status=%s sentAt=%s 削除日=%s source=%s" % (
            row["動画キー"], row["service"], row["postId"], post.get("status"), post.get("sentAt"),
            row["削除日"] or "(空)", sources))
        node = {"id": post.get("id") or row["postId"], "assets": post.get("assets") or []}

        def queued(document, variables=None, operation_name=None, _node=node):
            if operation_name == "Account":
                return {"account": {"organizations": [{"id": "org"}]}}
            return {"posts": {"pageInfo": {"hasNextPage": False}, "edges": [{"node": _node}]}}

        numbers, note = ppb().fetch_scheduled_pin_numbers(queued)
        out("  キューに残っているときの画像の掃除: %s — %s" % (
            "止まらない" if numbers is not None else "止まる（削除しない）", note))
    numbers, note = ppb().fetch_scheduled_pin_numbers(graphql)
    out("今のキューでの画像の掃除: %s — %s" % ("止まらない" if numbers is not None else "止まる（削除しない）", note))
    return 0


# --- main -----------------------------------------------------------------------


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    argv = list(sys.argv[1:] if argv is None else argv)
    usage = ("usage: post-video-to-buffer.py [--dry-run | --publish-only] [--md <動画md>] [--ledger <台帳>]\n"
             "       post-video-to-buffer.py --cleanup [--wait] [--dry-run] [--ledger <台帳>]\n"
             "       post-video-to-buffer.py --status [--ledger <台帳>]")
    known = {"--dry-run", "--publish-only", "--cleanup", "--wait", "--status", "--md", "--ledger"}
    opts = {}
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg not in known:
            print(usage)
            return 1
        if arg in ("--md", "--ledger"):
            if i + 1 >= len(argv):
                print(usage)
                return 1
            opts[arg] = os.path.abspath(argv[i + 1])
            i += 2
            continue
        opts[arg] = True
        i += 1
    try:
        if opts.get("--status"):
            return cmd_status(opts.get("--ledger"))
        if opts.get("--cleanup"):
            return cmd_cleanup(opts.get("--ledger"), dry_run=bool(opts.get("--dry-run")),
                               wait=bool(opts.get("--wait")))
        return cmd_post(opts.get("--md"), opts.get("--ledger"), dry_run=bool(opts.get("--dry-run")),
                        publish_only=bool(opts.get("--publish-only")))
    except (ValueError, OSError) as e:
        print("【エラー】%s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
