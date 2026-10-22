# -*- coding: utf-8 -*-
r"""未投稿ピンをPinterestへ実投稿する本体スクリプト（D-0120・D-0114）。

処理順序:
  (0) 緊急停止スイッチ確認。data/ 直下に「pin-auto-post-off」で始まる名前の
      ファイルが1つでも存在すれば（拡張子不問。従来の拡張子なしファイルも
      引き続き対象）即座に正常終了する（他のどの処理よりも先に判定する。
      rules/pinterest-api.md参照）。
  (1) 未投稿ピン番号の導出。check-pin-posting-status.py と同じ関数
      （extract_created_pins() / load_ledger()）をimportして再利用する
      （同じ判定を二重実装すると片方だけ直って食い違うため）。
  (1-2) 未審査のピンの保留。pin_review.is_reviewed() が False のピン（364以降で
      「- 審査: 公開可 YYYY-MM-DD」行が無いもの）は投稿対象から外し、
      「HELD_UNREVIEWED: 番号一覧」を1行出す。保留は失敗ではないため終了コードは
      変えない。未審査の差し替えピンは投稿されないので、旧ピンも削除されない。
  (2) 今回の投稿対象が50件を超える場合、1件も投稿せず件数のみ報告して終了する
      （オーナー承認済みの自主規制値）。
  (3) 各ピンファイルから ボード名・タイトル・説明文・誘導先URL・画像ファイルパス を
      読み取る。必須項目が1つでも欠ける／空ならスキップし理由を出力する。
  (4) ボード名を data/pinterest-boards.md と突き合わせて board_id を解決する。
      実在しなければスキップする（ボード名検証フックはWriteのみが対象でEdit経由を
      すり抜けるため、ここで二重化する）。
  (5) 誘導先URLへGETし200を確認する（タイムアウト10秒）。200以外なら30秒待って
      再確認し、最大5回まで再試行する。それでも200でなければスキップする
      （push直後のGitHub Pagesビルド待ちを考慮した猶予）。
  (6) 二重投稿防止の照合。GET /v5/pins を新しい順に最大250件取得し、誘導先URLと
      タイトルが両方一致する既存ピンが無いか確認する。存在すれば投稿せず
      「台帳への記録漏れの可能性」として報告する。250件に達しても照合が終わらない
      場合はその旨を明記した上で投稿を続行する。
  (7) POST /v5/pins を実行する（media_source は image_base64）。
  (8) 成功したら即座に data/pin-posted.md を1件ずつ追記更新する
      （3件まとめて最後に書かない）。
  (9) 次のピンとの間に3秒待機する（Standardのレート制限は1分あたり100リクエスト）。
  (10) 全件の結果を一覧で出力する。

エラー処理:
  - 1件の失敗が他のピンの処理を止めない。
  - APIエラーはHTTPステータスとレスポンス本文をそのまま記録する（握りつぶさない）。

production runのstep記録（D-0235）:
  (7) の成否ごとに、ピン番号・channel=pinterest・実際に送った本文payloadの
  正規化JSONのsha256を data/production-handoff/_steps/ へ1行追記する。
  記録の成否は投稿処理・標準出力・終了コードのいずれにも影響しない。

--dry-run:
  (7)(8) のみ行わない。それ以外（停止スイッチ・未投稿導出・ファイル解析・
  ボード解決・URL200確認・重複照合）はすべて実行して結果を一覧出力する。

--compact-ledger-only（D-0143）:
  data/pin-posted.md の圧縮（compact_ledger()）のみを実行して終了する。
  Pinterest APIへの投稿は一切行わない。圧縮を実投稿を伴わずに検証するための
  オプション。圧縮は (0) 緊急停止スイッチ判定より後・通常実行時は最初の
  Pinterest投稿より前に1回だけ実行される。

差し替えピンの旧ピン処理（D-0282）:
  (8) の直後、投稿したピンmdに「- 差し替え元ピン: N」行があれば process_replacement() で旧ピンNを
  処理する（失敗しても投稿の処理は止めず、結果は一覧に別の行で出す）。
    a. 旧 pin_id の引き当て: data/pin-daily-metrics.tsv で旧番号のIDが1件ならそれを候補にする。
       0件・複数なら GET /v5/pins の一覧から link の utm_content=pin<旧番号> を持ち、GET が200の
       ものがちょうど1件のときだけ候補にする。
    b. 新ピンの GET が200でなければ何もしない（次回に持ち越す）。
    c. 旧候補の GET が404なら「- 旧ピン処理: already_gone 日付 ID」を書く。200かつ link の
       utm_content が pin<旧番号> なら DELETE を1回だけ送り、続く GET が404なら「deleted」を書く。
    d. 候補が決まらない・link不一致・5xx・通信失敗は書かずに未完了のまま残し、理由と
       直リンク（IDが分からなければ記事URL・旧番号・ボード名）を出す。
    e. 401・403 ならその実行の以降の処理（DELETEを含む）を止める。
    f. DELETE は POST と同じ待機間隔（POST_INTERVAL_SECONDS）を空けて送る。

--apply-replacements [--dry-run]:
  未完了の差し替え（差し替え元ピン行があり旧ピン処理行が無いmd）のうち、投稿済みのものすべてに
  process_replacement() を実行する。--dry-run では DELETE も行の書き込みもしない。

--mark-manual <新ピン番号>:
  オーナーが旧ピンを手で消し、IDが引けない場合に「- 旧ピン処理: manual 日付 -」を書くだけ。
  APIは呼ばない。

使い方:
  python site/scripts/post-pins-to-pinterest.py --dry-run
  python site/scripts/post-pins-to-pinterest.py --compact-ledger-only
  python site/scripts/post-pins-to-pinterest.py
  python site/scripts/post-pins-to-pinterest.py --apply-replacements [--dry-run]
  python site/scripts/post-pins-to-pinterest.py --mark-manual <新ピン番号>
"""

import base64
import csv
import datetime
import importlib.util
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

from PIL import Image

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
PINS_DIR = os.path.join(ROOT, "output", "pins")
LEDGER_PATH = os.path.join(ROOT, "data", "pin-posted.md")
BOARDS_FILE = os.path.join(ROOT, "data", "pinterest-boards.md")
KILL_SWITCH_PATH = os.path.join(ROOT, "data", "pin-auto-post-off")
KILL_SWITCH_PREFIX = "pin-auto-post-off"
DATA_DIR = os.path.join(ROOT, "data")
METRICS_PATH = os.path.join(DATA_DIR, "pin-daily-metrics.tsv")

if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from env_loader import require_env  # noqa: E402
import pin_review  # noqa: E402
import pinterest_api  # noqa: E402

MAX_BATCH_SIZE = 50
URL_CHECK_TIMEOUT_SECONDS = 10
URL_CHECK_MAX_RETRIES = 5  # 初回確認とは別に、最大5回まで再確認する
URL_CHECK_RETRY_WAIT_SECONDS = 30
POST_INTERVAL_SECONDS = 3
DEDUPE_FETCH_LIMIT = 250
DEDUPE_PAGE_SIZE = 100

BOARD_LINE_RE = re.compile(r"^ボード:\s*(.+)$")
STATUS_LINE_RE = re.compile(r"^-\s*ステータス:.*?（(.+)）\s*$")
GUIDE_URL_RE = re.compile(r"^-\s*誘導先URL:\s*(.+)$")
TITLE_RE = re.compile(r"^タイトル:\s*(.+)$")
DESC_RE = re.compile(r"^説明文:\s*(.+)$")
# T3・D-0123: 投稿成功時に「投稿済み:」行とは別に日付つきの行を1件ずつ追記し、
# 当日の投稿件数を数えられるようにする。既存の「投稿済み:」行の書式・解釈
# （load_ledger/derive_unposted）は変更しない。
POSTED_DATE_LINE_RE = re.compile(r"^投稿日:\s*(\d{4}-\d{2}-\d{2})\s+(\d+)\s*$")


def _load_check_pin_posting_status():
    """check-pin-posting-status.py をモジュールとして読み込む（ファイル名がハイフン
    を含みそのままimportできないため、pinterest_api.py 等と同じ
    importlib.util経由の読み込みに統一する）。"""
    path = os.path.join(SCRIPT_DIR, "check-pin-posting-status.py")
    spec = importlib.util.spec_from_file_location("check_pin_posting_status", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_kill_switch():
    """data/ 直下に「pin-auto-post-off」で始まる名前のファイルが1つでも
    存在すれば停止対象とみなす（拡張子は問わない。従来の拡張子なし
    ファイル data/pin-auto-post-off も引き続き対象に含まれる）。
    Windowsのエクスプローラーでは拡張子なしファイルを作成できないため、
    pin-auto-post-off.txt 等でも確実に検知できるようにする。
    戻り値: 検知したファイル名（存在しなければ None）"""
    if not os.path.isdir(DATA_DIR):
        return None
    try:
        names = os.listdir(DATA_DIR)
    except OSError:
        return None
    matches = sorted(
        n for n in names
        if n.startswith(KILL_SWITCH_PREFIX)
        and os.path.isfile(os.path.join(DATA_DIR, n))
    )
    return matches[0] if matches else None


def derive_unposted(mod):
    """check-pin-posting-status.py と同じ判定方式で未投稿ピン番号を導出する。
    戻り値: [(pin_num, file_name), ...]（昇順）"""
    posted = mod.load_ledger()
    if posted is None:
        posted = set()
    nums_map = mod.extract_created_pins()
    unposted_nums = sorted(set(nums_map.keys()) - posted)
    result = []
    for n in unposted_nums:
        files = nums_map[n]
        # 重複ファイルがある場合も1件目を代表として使う（重複自体は
        # check-pin-posting-status.py側の自己検査が別途【警告】で検出する）。
        result.append((n, files[0]))
    return result


def parse_pin_file(pin_num, file_name):
    """ピンファイルから必須項目を読み取る。
    戻り値: (fields_dict または None, スキップ理由 または None)"""
    path = os.path.join(PINS_DIR, file_name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError as e:
        return None, "ファイル読み込み失敗: %s" % e

    board = None
    image_rel_path = None
    guide_url = None
    title = None
    description = None

    for line in lines:
        stripped = line.strip()
        m = BOARD_LINE_RE.match(stripped)
        if m:
            board = m.group(1).strip()
            continue
        m = STATUS_LINE_RE.match(stripped)
        if m:
            image_rel_path = m.group(1).strip()
            continue
        m = GUIDE_URL_RE.match(stripped)
        if m:
            guide_url = m.group(1).strip()
            continue
        m = TITLE_RE.match(stripped)
        if m:
            title = m.group(1).strip()
            continue
        m = DESC_RE.match(stripped)
        if m:
            description = m.group(1).strip()
            continue

    missing = []
    if not board:
        missing.append("ボード")
    if not image_rel_path:
        missing.append("画像ファイルパス")
    if not guide_url:
        missing.append("誘導先URL")
    if not title:
        missing.append("タイトル")
    if not description:
        missing.append("説明文")
    if missing:
        return None, "必須項目が欠落/空です: %s" % ", ".join(missing)

    image_abs_path = os.path.join(ROOT, image_rel_path.replace("/", os.sep))
    if not os.path.isfile(image_abs_path):
        return None, "画像ファイルが見つかりません: %s" % image_rel_path

    return {
        "pin_num": pin_num,
        "file_name": file_name,
        "board": board,
        "image_path": image_abs_path,
        "guide_url": guide_url,
        "title": title,
        "description": description,
    }, None


def load_board_id_map():
    """data/pinterest-boards.md からボード名->{"board_id":..., "season":...} の
    対応を返す（状態不問）。「季節」列（T2-1・D-0123）が無い古い形式のファイルでは
    季節側は空文字になる（resolve_board_idが未設定として扱う）。"""
    mapping = {}
    if not os.path.isfile(BOARDS_FILE):
        return mapping
    with open(BOARDS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 2:
                continue
            if cells[0] in ("ボード名",) or set(cells[0]) <= {"-"}:
                continue
            season = cells[5] if len(cells) > 5 else ""
            mapping[cells[0]] = {"board_id": cells[1], "season": season}
    return mapping


def resolve_board_id(board_name, board_id_map):
    """戻り値: (board_id, season, エラー理由)。board_idがNoneならエラー理由が入る。"""
    entry = board_id_map.get(board_name)
    if not entry or not entry.get("board_id"):
        return None, None, "ボード名「%s」が data/pinterest-boards.md に見つかりません" % board_name
    season = entry.get("season")
    if season not in ("季節", "通年"):
        return None, None, (
            "ボード名「%s」の季節/通年列がdata/pinterest-boards.mdに記録されていません"
            "（正本の再生成が必要な可能性があります）" % board_name
        )
    return entry["board_id"], season, None


def check_url_ok(url):
    """誘導先URLへGETし200を確認する。最大5回まで再試行する。
    戻り値: (ok: bool, detail: str)"""
    attempt = 0
    last_detail = ""
    while True:
        attempt += 1
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=URL_CHECK_TIMEOUT_SECONDS) as resp:
                status = resp.getcode()
        except urllib.error.HTTPError as e:
            status = e.code
        except Exception as e:
            status = None
            last_detail = "通信エラー: %s" % e

        if status == 200:
            return True, "200 OK（試行%d回目）" % attempt
        if status is not None:
            last_detail = "HTTP %s" % status

        if attempt > URL_CHECK_MAX_RETRIES:
            return False, "最終結果: %s（計%d回試行）" % (last_detail, attempt)
        time.sleep(URL_CHECK_RETRY_WAIT_SECONDS)


def fetch_recent_own_pins(access_token, limit=DEDUPE_FETCH_LIMIT, page_size=DEDUPE_PAGE_SIZE):
    """GET /v5/pins を新しい順に最大limit件取得する。
    戻り値: (pins: list, truncated: bool) truncatedはlimitに達してもbookmarkが
    残っていた（＝全件照合できなかった）場合True。"""
    items = []
    bookmark = None
    truncated = False
    while len(items) < limit:
        path = "/pins?page_size=%d" % page_size
        if bookmark:
            path += "&bookmark=" + urllib.parse.quote(bookmark)
        data = pinterest_api.request("GET", path, access_token, timeout=15)
        page_items = data.get("items", [])
        items.extend(page_items)
        bookmark = data.get("bookmark")
        if not bookmark:
            break
    if len(items) > limit:
        if bookmark:
            truncated = True
        items = items[:limit]
    elif bookmark:
        truncated = True
    return items, truncated


def extract_slug_from_guide_url(url):
    """誘導先URLから記事slugを取り出す（T2-2）。/posts/{slug}/ のパスから優先的に
    取り出し、取れなければ utm_campaign クエリパラメータを使う。ピンファイル名の
    slug断片は記事slugと不一致な事例があるため使わない。"""
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if "posts" in parts:
        idx = parts.index("posts")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    qs = urllib.parse.parse_qs(parsed.query)
    campaign = qs.get("utm_campaign")
    if campaign and campaign[0]:
        return campaign[0]
    return None


def check_board_group_rules(items):
    """ボード選定規則（1枚目=主題ボード、2枚目・3枚目=季節ボードか1枚目と同じボード）の
    形式検査（T2-2）。itemsはslug抽出・ボード解決済みのfieldsのリスト。
    戻り値: {pin_num: 違反理由の文字列}（同一グループの全ピンに同じ理由文字列を入れる）。
    ちょうど3枚のグループのみ検査し、それ以外（1〜2枚・4枚以上）は検査対象外。"""
    groups = defaultdict(list)
    for f in items:
        if f.get("slug"):
            groups[f["slug"]].append(f)

    violations = {}
    for slug, group_items in groups.items():
        if len(group_items) != 3:
            continue
        ordered = sorted(group_items, key=lambda f: f["pin_num"])
        first, second, third = ordered

        problems = []
        if first["board_season"] == "季節":
            problems.append(
                "(1) 1枚目 pin%d のボード「%s」が季節ボードです"
                % (first["pin_num"], first["board"])
            )
        if second["board"] != third["board"]:
            problems.append(
                "(2) 2枚目 pin%d「%s」と3枚目 pin%d「%s」のボードが一致していません"
                % (second["pin_num"], second["board"], third["pin_num"], third["board"])
            )
        for label, item in (("2枚目", second), ("3枚目", third)):
            ok = (item["board"] == first["board"]) or (item["board_season"] == "季節")
            if not ok:
                problems.append(
                    "(3) %s pin%d「%s」が1枚目と同じボードでも季節ボードでもありません"
                    % (label, item["pin_num"], item["board"])
                )

        if problems:
            pins_desc = "、".join(
                "pin%d(%s)" % (f["pin_num"], f["board"]) for f in ordered
            )
            detail = (
                "ボード選定規則違反のためslug=%sの組（%s）を全件スキップ: %s"
                % (slug, pins_desc, " / ".join(problems))
            )
            for f in ordered:
                violations[f["pin_num"]] = detail

    return violations


def count_today_posted(today_str):
    """data/pin-posted.md の「投稿日: YYYY-MM-DD N」行から、today_strと一致する
    件数を数える（T3）。日付が無い既存行（過去の投稿）はカウントしない。"""
    if not os.path.isfile(LEDGER_PATH):
        return 0
    count = 0
    with open(LEDGER_PATH, encoding="utf-8") as f:
        for line in f:
            m = POSTED_DATE_LINE_RE.match(line.strip())
            if m and m.group(1) == today_str:
                count += 1
    return count


def find_duplicate(fields, recent_pins):
    for p in recent_pins:
        if p.get("link") == fields["guide_url"] and p.get("title") == fields["title"]:
            return p.get("id")
    return None


def guess_content_type(image_path):
    ctype, _ = mimetypes.guess_type(image_path)
    return ctype or "image/png"


def describe_image(image_path):
    """画像パス・ファイルサイズ(MB)・縦横ピクセル数を1行にまとめる。
    投稿前に目視で確認できるようdry-run/実投稿どちらの結果にも含める。"""
    size_mb = os.path.getsize(image_path) / (1024 * 1024)
    try:
        with Image.open(image_path) as img:
            w, h = img.size
        dim = "%dx%d" % (w, h)
    except Exception as e:
        dim = "取得失敗: %s" % e
    return "%s / %.2fMB / %s" % (image_path, size_mb, dim)


def build_pin_body(fields, board_id):
    """POST /v5/pins へ送る本文を組み立てる。

    post_pin() から切り出しただけで、組み立ての内容は一切変えていない
    （送信せずに本文だけを取り出せるようにするため・D-0235）。
    """
    with open(fields["image_path"], "rb") as f:
        raw = f.read()
    b64 = base64.b64encode(raw).decode("ascii")
    content_type = guess_content_type(fields["image_path"])
    return {
        "board_id": board_id,
        "title": fields["title"],
        "description": fields["description"],
        "link": fields["guide_url"],
        "media_source": {
            "source_type": "image_base64",
            "content_type": content_type,
            "data": b64,
        },
    }


def post_pin(access_token, fields, board_id, sent=None):
    """ピンを1件投稿する。

    sent に辞書を渡すと、実際に送った本文payloadを sent["body"] へ入れて返す
    （投稿の成否によらずpayloadを記録できるようにするため・D-0235）。
    送信する内容・戻り値・例外は sent の有無で変わらない。
    """
    body = build_pin_body(fields, board_id)
    if sent is not None:
        sent["body"] = body
    return pinterest_api.request("POST", "/pins", access_token, body=body, timeout=30)


def _load_production_run():
    path = os.path.join(SCRIPT_DIR, "production-run.py")
    spec = importlib.util.spec_from_file_location("production_run", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def record_post_step(pin_num, body, ok, detail):
    """production runのstep記録（D-0235）。投稿処理そのものには影響しない。
    identityは「実際にAPIへ送った本文payloadの正規化JSON」のsha256とする。
    記録の失敗で投稿を止めないため、例外はすべて握りつぶす。"""
    try:
        module = _load_production_run()
        digest = module.sha256_hex(module.canonical_json(body)) if body is not None else None
        module.record_step(
            "post",
            pin_num=pin_num,
            channel="pinterest",
            payload_sha256=digest,
            ok=bool(ok),
            detail=detail,
        )
    except Exception:
        pass


LEDGER_BACKUP_PATH = os.path.join(DATA_DIR, "pin-posted.md.bak")

# check-pin-posting-status.py のLEDGER_LINE_RE（「投稿済み:」行）と同じ判定を
# ここでも使い、「投稿済み:」または「投稿日:」のいずれかの行が最初に現れるまでを
# ヘッダー（冒頭のコメント説明文）とみなしてそのまま残す。


def _split_ledger_header(lines):
    """先頭から、最初に「投稿済み:」または「投稿日:」行が現れる直前までを
    ヘッダーとみなして (header_lines, rest_start_index) を返す。"""
    idx = 0
    while idx < len(lines):
        stripped = lines[idx].strip()
        if stripped.startswith("投稿済み:") or POSTED_DATE_LINE_RE.match(stripped):
            break
        idx += 1
    return lines[:idx], idx


def _ranges_to_line(nums):
    """昇順の番号集合を連続する範囲へ圧縮し「投稿済み: 1-3,5,7-9」形式の
    本文（1行）を返す。"""
    nums = sorted(nums)
    if not nums:
        return ""
    parts = []
    start = prev = nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        parts.append("%d" % start if start == prev else "%d-%d" % (start, prev))
        start = prev = n
    parts.append("%d" % start if start == prev else "%d-%d" % (start, prev))
    return "投稿済み: %s" % ",".join(parts)


def compact_ledger(today_str):
    """data/pin-posted.md を圧縮する。
    (1) 既存load_ledger()で投稿済み番号集合(before)を取得
    (2) data/pin-posted.md.bak へ上書きバックアップ（常にこの1ファイルのみ）
    (3) ヘッダーはそのまま残し、「投稿済み:」行を範囲圧縮した1行 + 当日分の
        「投稿日:」行のみに書き換えた新内容を組み立てる
    (4) 新内容を同じパーサで読み直しafterを取得
    (5) before==afterの場合のみ本ファイルを置き換える
    (6) 不一致なら元ファイルを変更せずexit 1する
    戻り値: None（正常終了）。不一致時はexitする。"""
    status_mod = _load_check_pin_posting_status()
    before = status_mod.load_ledger()
    if before is None:
        before = set()

    if not os.path.isfile(LEDGER_PATH):
        return

    with open(LEDGER_PATH, encoding="utf-8") as f:
        original_text = f.read()
    original_lines = original_text.splitlines()
    header_lines, rest_start = _split_ledger_header(original_lines)

    today_lines = []
    for line in original_lines[rest_start:]:
        m = POSTED_DATE_LINE_RE.match(line.strip())
        if m and m.group(1) == today_str:
            today_lines.append(line.strip())

    new_lines = list(header_lines)
    posted_line = _ranges_to_line(before)
    if posted_line:
        new_lines.append(posted_line)
    new_lines.extend(today_lines)
    new_text = "\n".join(new_lines) + "\n"

    tmp_path = LEDGER_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(new_text)

    # (4) 同じパーサで読み直してafterを取得する。一時的にLEDGER_PATHを
    # tmp_pathへ差し替えてload_ledger()を呼ぶ。
    orig_ledger_path = status_mod.LEDGER_PATH
    try:
        status_mod.LEDGER_PATH = tmp_path
        after = status_mod.load_ledger()
    finally:
        status_mod.LEDGER_PATH = orig_ledger_path
    if after is None:
        after = set()

    if before != after:
        only_before = sorted(before - after)
        only_after = sorted(after - before)
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        print("【エラー】台帳圧縮の整合性チェックに失敗しました。元ファイルは変更していません。")
        print("圧縮前のみに存在: %s" % only_before)
        print("圧縮後のみに存在: %s" % only_after)
        sys.exit(1)

    # (2) バックアップ（常にこの1ファイルのみを上書き）
    with open(LEDGER_BACKUP_PATH, "w", encoding="utf-8") as f:
        f.write(original_text)

    # (5) 一致したので置き換える
    os.replace(tmp_path, LEDGER_PATH)


def append_ledger(pin_num, today_str):
    """data/pin-posted.md の最後に「投稿済み:」行を1件追記する。
    既存の書式（範囲表記込みの1行）は壊さず、新しい行として素朴に追記する
    （範囲への統合はcheck-pin-posting-status.pyが読める形式であれば良く、
    無理に既存行を書き換えるより追記の方が安全なため）。
    あわせて「投稿日:」行（T3・D-0123）も1件追記し、当日投稿件数を数えられる
    ようにする。「投稿済み:」行の書式・解釈（load_ledger）には影響しない。"""
    with open(LEDGER_PATH, "a", encoding="utf-8") as f:
        f.write("投稿済み: %d\n" % pin_num)
        f.write("投稿日: %s %d\n" % (today_str, pin_num))


# --- 差し替えピンの旧ピン処理（D-0282） ------------------------------------------
PIN_PAGE_URL = "https://www.pinterest.com/pin/%s/"
AUTH_STOP_STATUSES = (401, 403)
UTM_PIN_VALUE_RE = re.compile(r"^pin0*(\d+)$")
LABEL_REPLACE_OPEN = "旧ピン未処理"

_PIV = []


def _load_piv():
    """pick-image-variation.py（差し替えピンの行の定義元）を読み込む。1プロセス1回。"""
    if not _PIV:
        path = os.path.join(SCRIPT_DIR, "pick-image-variation.py")
        spec = importlib.util.spec_from_file_location("pick_image_variation", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _PIV.append(mod)
    return _PIV[0]


class _AuthStop(Exception):
    """401・403 を受けた。その実行の以降の処理を止める合図。"""


def new_replacement_state():
    """1回の実行で共有する状態（ID一覧のキャッシュ・401/403の停止・DELETEの間隔）。"""
    return {"metrics": None, "listing": None, "auth_stop": False, "last_write": 0.0, "deleted": 0}


def utm_pin_number(link):
    """リンクの utm_content=pinN から N を返す（先頭の0は無視する）。無ければ None。"""
    try:
        query = urllib.parse.urlparse(link or "").query
    except ValueError:
        return None
    for value in urllib.parse.parse_qs(query).get("utm_content", []):
        m = UTM_PIN_VALUE_RE.match(value.strip())
        if m:
            return int(m.group(1))
    return None


def metrics_pin_ids(pin_num, state):
    """data/pin-daily-metrics.tsv にあるピン番号 pin_num の pin_id（重複を除いた出現順）。"""
    if state["metrics"] is None:
        state["metrics"] = {}
        if os.path.isfile(METRICS_PATH):
            with open(METRICS_PATH, encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f, delimiter="\t"):
                    num = (row.get("pin_number") or "").strip()
                    pin_id = (row.get("pin_id") or "").strip()
                    if num.isdigit() and pin_id:
                        ids = state["metrics"].setdefault(int(num), [])
                        if pin_id not in ids:
                            ids.append(pin_id)
    return state["metrics"].get(pin_num, [])


def get_pin(access_token, pin_id):
    """GET /v5/pins/<id>。戻り値: (HTTPステータス または None（通信失敗）, 本文 または None, 説明)。
    401・403 は _AuthStop を送出する。"""
    try:
        return 200, pinterest_api.request("GET", "/pins/%s" % pin_id, access_token, timeout=15), "HTTP 200"
    except pinterest_api.PinterestApiError as e:
        if e.status_code in AUTH_STOP_STATUSES:
            raise _AuthStop("GET /v5/pins/%s → HTTP %s: %s" % (pin_id, e.status_code, e.body))
        return e.status_code, None, "HTTP %s: %s" % (e.status_code, e.body)
    except Exception as e:
        return None, None, "通信失敗: %s" % e


def resolve_pin_id(access_token, pin_num, state):
    """ピン番号から pin_id を1件に決める。戻り値: (pin_id または None, 決まらない理由)。

    pin-daily-metrics.tsv にちょうど1件ならそれ。0件・複数なら GET /v5/pins の一覧を走査し、
    link の utm_content=pin<pin_num> を持ち GET が200のものがちょうど1件のときだけ返す。
    """
    ids = metrics_pin_ids(pin_num, state)
    if len(ids) == 1:
        return ids[0], None
    if state["listing"] is None:
        try:
            state["listing"] = pinterest_api.fetch_all_pages("/pins", access_token)
        except pinterest_api.PinterestApiError as e:
            if e.status_code in AUTH_STOP_STATUSES:
                raise _AuthStop("GET /v5/pins → HTTP %s: %s" % (e.status_code, e.body))
            return None, "GET /v5/pins の一覧を取得できません（HTTP %s）" % e.status_code
        except Exception as e:
            return None, "GET /v5/pins の一覧を取得できません（通信失敗: %s）" % e
    matches = [p.get("id") for p in state["listing"] if utm_pin_number(p.get("link")) == pin_num]
    alive = [pid for pid in matches if get_pin(access_token, pid)[0] == 200]
    if len(alive) == 1:
        return alive[0], None
    return None, ("pin_id を1件に決められません（pin-daily-metrics.tsv %d件／GET /v5/pins の一覧で"
                  "utm_content=pin%d かつ GET 200 が%d件）" % (len(ids), pin_num, len(alive)))


def read_replacement(file_name):
    """ピンmdの差し替えの記載（pick-image-variation.py の replacement_info()）。読めなければ None。"""
    try:
        with open(os.path.join(PINS_DIR, file_name), encoding="utf-8") as f:
            return _load_piv().replacement_info(f.read())
    except OSError:
        return None


def write_old_pin_result(file_name, kind, date_str, old_pin_id):
    """ピンmdの「差し替え元ピン」行の直後に「- 旧ピン処理: …」行を書く（既にあれば書かない）。"""
    piv = _load_piv()
    path = os.path.join(PINS_DIR, file_name)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if piv.OLD_PIN_RESULT_RE.search(text):
        return
    m = piv.REPLACE_FROM_LINE_RE.search(text)
    line = "%s%s %s %s" % (piv.OLD_PIN_RESULT_LABEL, kind, date_str, old_pin_id)
    text = text[:m.end()] + "\n" + line + text[m.end():]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def old_pin_hint(old_num, old_pin_id, new_file_name):
    """手で確かめるための手がかり。IDが分かれば直リンク、分からなければ記事URL・旧番号・ボード名。"""
    if old_pin_id:
        return "直リンク: " + PIN_PAGE_URL % old_pin_id
    piv = _load_piv()
    entries = piv.read_pin_entries(PINS_DIR)
    new = next((e for e in entries if e["file"] == new_file_name), None)
    old = next((e for e in entries if e["num"] == old_num), None)
    board = None
    if old:
        with open(os.path.join(PINS_DIR, old["file"]), encoding="utf-8") as f:
            m = piv.PIN_MD_BOARD_RE.search(f.read())
        board = m.group(1) if m else None
    slug = (new or old or {}).get("slug")
    article = "%s%s/" % (piv.SITE_POSTS_BASE, slug) if slug else "不明"
    return "記事URL: %s／旧ピン番号: %d／ボード: %s" % (article, old_num, board or "不明")


def process_replacement(access_token, file_name, new_num, new_pin_id, old_num, today_str, dry_run, state):
    """差し替えピン（新 new_num）の旧ピン old_num を処理する。戻り値: (結果の見出し, 説明)。

    new_pin_id が None なら新ピンのIDも resolve_pin_id() で引く。行の書き込みは
    already_gone・deleted のときだけで、それ以外は未完了のまま残す（次回に持ち越す）。
    """
    if state["auth_stop"]:
        return LABEL_REPLACE_OPEN, "この実行は401・403で処理を止めたため持ち越し（トークン失効または権限変更の疑い）"
    old_id = None
    try:
        if new_pin_id is None:
            new_pin_id, reason = resolve_pin_id(access_token, new_num, state)
            if new_pin_id is None:
                return LABEL_REPLACE_OPEN, "新ピン%dの%s。次回に持ち越し" % (new_num, reason)
        status, _body, detail = get_pin(access_token, new_pin_id)
        if status != 200:
            return LABEL_REPLACE_OPEN, "新ピン%d（%s）の GET が200ではないため何もしません（%s）。次回に持ち越し" % (
                new_num, new_pin_id, detail)

        old_id, reason = resolve_pin_id(access_token, old_num, state)
        if old_id is None:
            return LABEL_REPLACE_OPEN, "旧ピン%dの%s／%s" % (
                old_num, reason, old_pin_hint(old_num, None, file_name))
        status, body, detail = get_pin(access_token, old_id)
        if status == 404:
            if dry_run:
                return "旧ピンは既に無い(dry-run)", "旧ピン%d（%s）は GET 404。already_gone を書く見込み（DELETEは送らない）" % (
                    old_num, old_id)
            write_old_pin_result(file_name, "already_gone", today_str, old_id)
            return "旧ピン処理: already_gone", "旧ピン%d（%s）は GET 404（既に無い）。DELETEは送っていません" % (old_num, old_id)
        if status != 200:
            return LABEL_REPLACE_OPEN, "旧ピン%d の GET が200・404以外のため持ち越し（%s）／%s" % (
                old_num, detail, old_pin_hint(old_num, old_id, file_name))
        link = (body or {}).get("link")
        if utm_pin_number(link) != old_num:
            return LABEL_REPLACE_OPEN, "旧ピン候補 %s の link の utm_content が pin%d ではありません（link=%s）／%s" % (
                old_id, old_num, link, old_pin_hint(old_num, old_id, file_name))
        if dry_run:
            return "DELETE見込み(dry-run)", "旧ピン%d（%s）は GET 200・link一致。DELETE を1回送る見込み" % (old_num, old_id)

        wait = POST_INTERVAL_SECONDS - (time.time() - state["last_write"])
        if wait > 0:
            time.sleep(wait)
        try:
            pinterest_api.request("DELETE", "/pins/%s" % old_id, access_token, timeout=15)
        except pinterest_api.PinterestApiError as e:
            if e.status_code in AUTH_STOP_STATUSES:
                raise _AuthStop("DELETE /v5/pins/%s → HTTP %s: %s" % (old_id, e.status_code, e.body))
            return LABEL_REPLACE_OPEN, "旧ピン%d の DELETE が HTTP %s: %s／%s" % (
                old_num, e.status_code, e.body, old_pin_hint(old_num, old_id, file_name))
        except Exception as e:
            return LABEL_REPLACE_OPEN, "旧ピン%d の DELETE が通信失敗: %s／%s" % (
                old_num, e, old_pin_hint(old_num, old_id, file_name))
        finally:
            state["last_write"] = time.time()
        state["deleted"] += 1
        status, _body, detail = get_pin(access_token, old_id)
        if status == 404:
            write_old_pin_result(file_name, "deleted", today_str, old_id)
            return "旧ピン処理: deleted", "旧ピン%d（%s）を DELETE し、GET 404 を確認しました" % (old_num, old_id)
        return LABEL_REPLACE_OPEN, "旧ピン%d の DELETE 後の GET が404ではありません（%s）／%s" % (
            old_num, detail, old_pin_hint(old_num, old_id, file_name))
    except _AuthStop as e:
        state["auth_stop"] = True
        return LABEL_REPLACE_OPEN, "トークン失効または権限変更の疑い（%s）。この実行の以降の DELETE を止めました／%s" % (
            e, old_pin_hint(old_num, old_id, file_name))


def open_replacements():
    """未完了の差し替え（差し替え元ピン行があり旧ピン処理行が無いmd）を [(新番号, ファイル名, 旧番号, 行数)] で返す。"""
    piv = _load_piv()
    return [(e["num"], e["file"], e["replace_from"], e["replace_count"])
            for e in piv.read_pin_entries(PINS_DIR)
            if e["replace_from"] is not None and e["old_pin_result"] is None]


def apply_replacements(dry_run, today_str):
    """--apply-replacements: 投稿済みの未完了の差し替えすべてに process_replacement() を実行する。"""
    status_mod = _load_check_pin_posting_status()
    status_mod.LEDGER_PATH = LEDGER_PATH
    posted = status_mod.load_ledger() or set()
    targets = open_replacements()
    if not targets:
        print("未完了の差し替えピンはありません")
        return
    access_token = None
    state = new_replacement_state()
    print("新ピン番号 / 結果 / 旧ピン番号 / 説明")
    for new_num, file_name, old_num, count in targets:
        if count > 1:
            label, detail = "スキップ", "%s に差し替え元ピン行が%d行あります（1行にする）" % (file_name, count)
        elif new_num not in posted:
            label, detail = "対象外", "新ピンが未投稿のため（投稿時に post-pins-to-pinterest.py が処理する）"
        else:
            if access_token is None:
                access_token = require_env("PINTEREST_ACCESS_TOKEN")
            try:
                label, detail = process_replacement(access_token, file_name, new_num, None, old_num,
                                                    today_str, dry_run, state)
            except Exception as e:
                label, detail = LABEL_REPLACE_OPEN, "例外: %s（次回に持ち越し）" % e
        print("%d / %s / %d / %s" % (new_num, label, old_num, detail))
    print("DELETE送信: %d件%s" % (state["deleted"], "（--dry-run のため送っていません）" if dry_run else ""))


def mark_manual(new_num, today_str):
    """--mark-manual: 「- 旧ピン処理: manual 日付 -」を書くだけ（APIは呼ばない）。戻り値: 終了コード。"""
    match = [t for t in open_replacements() if t[0] == new_num]
    if not match:
        print("【エラー】ピン%d に未完了の差し替え（差し替え元ピン行があり旧ピン処理行が無いmd）がありません" % new_num)
        return 1
    _num, file_name, old_num, count = match[0]
    if count > 1:
        print("【エラー】%s に差し替え元ピン行が%d行あります（1行にしてから実行する）" % (file_name, count))
        return 1
    write_old_pin_result(file_name, "manual", today_str, "-")
    print("ピン%d（%s）に「%smanual %s -」を書きました（旧ピン%d・APIは呼んでいません）"
          % (new_num, file_name, _load_piv().OLD_PIN_RESULT_LABEL, today_str, old_num))
    return 0


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    argv = sys.argv[1:]
    dry_run = "--dry-run" in argv
    compact_only = "--compact-ledger-only" in argv

    # --- --mark-manual（D-0282）: APIを呼ばずmdに1行書くだけのため、停止スイッチより前に扱う ---
    if "--mark-manual" in argv:
        index = argv.index("--mark-manual")
        if index + 1 >= len(argv) or not argv[index + 1].isdigit():
            print("usage: post-pins-to-pinterest.py --mark-manual <新ピン番号>")
            sys.exit(1)
        sys.exit(mark_manual(int(argv[index + 1]), datetime.date.today().isoformat()))

    # --- (0) 緊急停止スイッチ ---
    kill_switch_file = check_kill_switch()
    if kill_switch_file:
        print("自動投稿は停止中（data/%s を検知しました）" % kill_switch_file)
        sys.exit(0)

    today_str = datetime.date.today().isoformat()

    # --- --apply-replacements（D-0282）: 投稿は行わず、未完了の差し替えの旧ピンだけを処理する ---
    if "--apply-replacements" in argv:
        apply_replacements(dry_run, today_str)
        sys.exit(0)

    # --- 台帳圧縮（D-0143）: 緊急停止スイッチ判定より後・最初のPinterest投稿より前に1回だけ ---
    compact_ledger(today_str)

    if compact_only:
        print("台帳圧縮のみ実行しました（--compact-ledger-only・Pinterest APIへの投稿は行っていません）")
        sys.exit(0)

    # --- (1) 未投稿ピン番号の導出 ---
    status_mod = _load_check_pin_posting_status()
    unposted = derive_unposted(status_mod)

    # --- (1-2) 未審査のピンは投稿しない（pin_review.py）。保留は失敗ではないため終了コードは変えない ---
    held = [n for n, f in unposted if not pin_review.is_reviewed_file(n, os.path.join(PINS_DIR, f))]
    if held:
        print(pin_review.held_line("HELD_UNREVIEWED", held))
        unposted = [(n, f) for n, f in unposted if n not in held]

    if not unposted:
        print("未投稿ピンはありません" + ("（未審査で保留したピンを除く）" if held else ""))
        sys.exit(0)

    # --- (2) 50件超の自主規制（T3・D-0123: 当日の累計で判定する） ---
    already_today = count_today_posted(today_str)
    total_if_posted = already_today + len(unposted)
    print("本日すでに投稿済み%d件 ＋ 今回の対象%d件 ＝ %d件（上限%d件）"
          % (already_today, len(unposted), total_if_posted, MAX_BATCH_SIZE))
    if total_if_posted > MAX_BATCH_SIZE:
        print("上限%d件を超えるため、1件も投稿せず終了します。" % MAX_BATCH_SIZE)
        sys.exit(0)

    access_token = require_env("PINTEREST_ACCESS_TOKEN")
    board_id_map = load_board_id_map()

    results = []  # (pin_num, result, board_name, detail)
    replacement_state = new_replacement_state()

    # --- (3)(4) ファイル解析・ボード解決を先に全件行う（T2-2のグループ検査に使うため） ---
    parsed_items = {}  # pin_num -> fields（slug・board_id・board_season込み）
    for pin_num, file_name in unposted:
        fields, reason = parse_pin_file(pin_num, file_name)
        if fields is None:
            results.append((pin_num, "スキップ", "-", reason))
            continue

        board_id, board_season, reason = resolve_board_id(fields["board"], board_id_map)
        if board_id is None:
            results.append((pin_num, "スキップ", fields["board"], reason))
            continue

        fields["board_id"] = board_id
        fields["board_season"] = board_season
        fields["slug"] = extract_slug_from_guide_url(fields["guide_url"])
        parsed_items[pin_num] = fields

    # --- T2-2: ボード選定規則の形式検査（記事slugごとに3枚1組で判定） ---
    group_violations = check_board_group_rules(list(parsed_items.values()))

    # --- 重複照合用に自分の最近のピンを取得 ---
    recent_pins, truncated = fetch_recent_own_pins(access_token)
    if truncated:
        print("【注意】GET /v5/pins が%d件の上限に達しても照合が終わりませんでした。"
              "以降の重複照合は取得できた範囲のみで行い、投稿は続行します。" % DEDUPE_FETCH_LIMIT)

    for pin_num, file_name in unposted:
        if pin_num not in parsed_items:
            continue  # 解析・ボード解決の時点で既にresultsへスキップ済み
        fields = parsed_items[pin_num]

        if pin_num in group_violations:
            results.append((pin_num, "スキップ", fields["board"], group_violations[pin_num]))
            continue

        board_id = fields["board_id"]

        url_ok, url_detail = check_url_ok(fields["guide_url"])
        if not url_ok:
            results.append((pin_num, "スキップ", fields["board"],
                             "誘導先URLが200を返しません（%s）" % url_detail))
            continue

        dup_id = find_duplicate(fields, recent_pins)
        if dup_id:
            results.append((pin_num, "スキップ", fields["board"],
                             "台帳への記録漏れの可能性（既存pin_id: %s）" % dup_id))
            continue

        image_detail = describe_image(fields["image_path"])

        if dry_run:
            results.append((pin_num, "成功見込み(dry-run)", fields["board"],
                             "URL確認OK・重複無し・board_id=%s / 画像: %s" % (board_id, image_detail)))
            continue

        sent = {}
        try:
            resp = post_pin(access_token, fields, board_id, sent=sent)
        except pinterest_api.PinterestApiError as e:
            record_post_step(pin_num, sent.get("body"), False, "HTTP %s" % e.status_code)
            results.append((pin_num, "失敗", fields["board"],
                             "HTTP %s: %s / 画像: %s" % (e.status_code, e.body, image_detail)))
            continue
        except Exception as e:
            record_post_step(pin_num, sent.get("body"), False, "例外: %s" % e)
            results.append((pin_num, "失敗", fields["board"],
                             "例外: %s / 画像: %s" % (e, image_detail)))
            continue

        pin_id = resp.get("id", "")
        record_post_step(pin_num, sent.get("body"), True, "pin_id: %s" % pin_id)
        append_ledger(pin_num, today_str)
        replacement_state["last_write"] = time.time()
        results.append((pin_num, "成功", fields["board"],
                         "pin_id: %s / 画像: %s" % (pin_id, image_detail)))

        # --- 差し替えピンなら旧ピンを処理する（D-0282）。失敗しても投稿の処理は止めない ---
        info = read_replacement(file_name)
        if info and info["replace_from"] is not None and info["old_pin_result"] is None:
            if info["replace_count"] > 1:
                label, detail = "スキップ", "差し替え元ピン行が%d行あります（1行にして --apply-replacements を実行する）" % info["replace_count"]
            else:
                try:
                    label, detail = process_replacement(
                        access_token, file_name, pin_num, pin_id or None, info["replace_from"],
                        today_str, False, replacement_state)
                except Exception as e:
                    label, detail = LABEL_REPLACE_OPEN, "例外: %s（--apply-replacements で再実行する）" % e
            results.append((pin_num, label, "旧ピン%d" % info["replace_from"], detail))
        time.sleep(POST_INTERVAL_SECONDS)

    results.sort(key=lambda r: r[0])  # 2パス構成のため構築順=昇順ではなくなった。出力はpin_num昇順に揃える
    print("ピン番号 / 結果 / ボード名 / pin_id またはスキップ・失敗の理由")
    for pin_num, result, board, detail in results:
        print("%d / %s / %s / %s" % (pin_num, result, board, detail))

    sys.exit(0)


if __name__ == "__main__":
    main()
