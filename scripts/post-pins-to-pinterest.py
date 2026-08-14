# -*- coding: utf-8 -*-
r"""未投稿ピンをPinterestへ実投稿する本体スクリプト（フェーズD・T2・D-0120）。

処理順序:
  (0) 緊急停止スイッチ確認。data/pin-auto-post-off が存在すれば即座に正常終了する
      （他のどの処理よりも先に判定する。rules/pinterest-api.md参照）。
  (1) 未投稿ピン番号の導出。check-pin-posting-status.py と同じ関数
      （extract_created_pins() / load_ledger()）をimportして再利用する
      （同じ判定を二重実装すると片方だけ直って食い違うため）。
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

--dry-run:
  (7)(8) のみ行わない。それ以外（停止スイッチ・未投稿導出・ファイル解析・
  ボード解決・URL200確認・重複照合）はすべて実行して結果を一覧出力する。

使い方:
  python site/scripts/post-pins-to-pinterest.py --dry-run
  python site/scripts/post-pins-to-pinterest.py
"""

import base64
import importlib.util
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
PINS_DIR = os.path.join(ROOT, "output", "pins")
LEDGER_PATH = os.path.join(ROOT, "data", "pin-posted.md")
BOARDS_FILE = os.path.join(ROOT, "data", "pinterest-boards.md")
KILL_SWITCH_PATH = os.path.join(ROOT, "data", "pin-auto-post-off")

if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from env_loader import require_env  # noqa: E402
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
    return os.path.isfile(KILL_SWITCH_PATH)


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
    """data/pinterest-boards.md からボード名->board_id の対応を返す（状態不問）。"""
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
            mapping[cells[0]] = cells[1]
    return mapping


def resolve_board_id(board_name, board_id_map):
    board_id = board_id_map.get(board_name)
    if not board_id:
        return None, "ボード名「%s」が data/pinterest-boards.md に見つかりません" % board_name
    return board_id, None


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


def find_duplicate(fields, recent_pins):
    for p in recent_pins:
        if p.get("link") == fields["guide_url"] and p.get("title") == fields["title"]:
            return p.get("id")
    return None


def guess_content_type(image_path):
    ctype, _ = mimetypes.guess_type(image_path)
    return ctype or "image/png"


def post_pin(access_token, fields, board_id):
    with open(fields["image_path"], "rb") as f:
        raw = f.read()
    b64 = base64.b64encode(raw).decode("ascii")
    content_type = guess_content_type(fields["image_path"])
    body = {
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
    return pinterest_api.request("POST", "/pins", access_token, body=body, timeout=30)


def append_ledger(pin_num):
    """data/pin-posted.md の最後の「投稿済み:」行に1件だけ番号を追記する。
    既存の書式（範囲表記込みの1行）は壊さず、新しい行として素朴に追記する
    （範囲への統合はcheck-pin-posting-status.pyが読める形式であれば良く、
    無理に既存行を書き換えるより追記の方が安全なため）。"""
    with open(LEDGER_PATH, "a", encoding="utf-8") as f:
        f.write("投稿済み: %d\n" % pin_num)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    dry_run = "--dry-run" in sys.argv[1:]

    # --- (0) 緊急停止スイッチ ---
    if check_kill_switch():
        print("自動投稿は停止中（data/pin-auto-post-off が存在します）")
        sys.exit(0)

    # --- (1) 未投稿ピン番号の導出 ---
    status_mod = _load_check_pin_posting_status()
    unposted = derive_unposted(status_mod)

    if not unposted:
        print("未投稿ピンはありません")
        sys.exit(0)

    # --- (2) 50件超の自主規制 ---
    if len(unposted) > MAX_BATCH_SIZE:
        print("投稿対象が%d件あり、上限%d件を超えています。1件も投稿せず終了します。" % (
            len(unposted), MAX_BATCH_SIZE))
        sys.exit(0)

    access_token = require_env("PINTEREST_ACCESS_TOKEN")
    board_id_map = load_board_id_map()

    # --- 重複照合用に自分の最近のピンを取得 ---
    recent_pins, truncated = fetch_recent_own_pins(access_token)
    if truncated:
        print("【注意】GET /v5/pins が%d件の上限に達しても照合が終わりませんでした。"
              "以降の重複照合は取得できた範囲のみで行い、投稿は続行します。" % DEDUPE_FETCH_LIMIT)

    results = []  # (pin_num, result, board_name, detail)

    for pin_num, file_name in unposted:
        fields, reason = parse_pin_file(pin_num, file_name)
        if fields is None:
            results.append((pin_num, "スキップ", "-", reason))
            continue

        board_id, reason = resolve_board_id(fields["board"], board_id_map)
        if board_id is None:
            results.append((pin_num, "スキップ", fields["board"], reason))
            continue

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

        if dry_run:
            results.append((pin_num, "成功見込み(dry-run)", fields["board"],
                             "URL確認OK・重複無し・board_id=%s" % board_id))
            continue

        try:
            resp = post_pin(access_token, fields, board_id)
        except pinterest_api.PinterestApiError as e:
            results.append((pin_num, "失敗", fields["board"],
                             "HTTP %s: %s" % (e.status_code, e.body)))
            continue
        except Exception as e:
            results.append((pin_num, "失敗", fields["board"], "例外: %s" % e))
            continue

        pin_id = resp.get("id", "")
        append_ledger(pin_num)
        results.append((pin_num, "成功", fields["board"], "pin_id: %s" % pin_id))
        time.sleep(POST_INTERVAL_SECONDS)

    print("ピン番号 / 結果 / ボード名 / pin_id またはスキップ・失敗の理由")
    for pin_num, result, board, detail in results:
        print("%d / %s / %s / %s" % (pin_num, result, board, detail))

    sys.exit(0)


if __name__ == "__main__":
    main()
