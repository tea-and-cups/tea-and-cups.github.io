# -*- coding: utf-8 -*-
r"""投稿済みPinの「ピン単位 × 日次」実績をPinterest APIから取得し data/pin-daily-metrics.tsv へ差分保存する（D-0217）。

目的:
  Growth Agent が条件比較（4群・構図variation）を日次粒度で行えるようにするための
  素材を作る。集計・率の計算はここでは行わない（countのまま保存し、率は利用側で
  再計算する。丸めを二重にかけないため）。

設計方針:
  - Pinterest APIへのアクセスは pinterest_api.py の単一入口経由（GET系のみ）。
    トークンは pinterest_token.ensure_fresh() で用意する。
  - Pin母集団は output/Pin-images/ 配下の画像ファイル名から決める（_crop_ 始まりは除外）。
    命名が2系統（英数字系 pin-N-slug-NN.png / 日本語系「ピンNN 説明....png」）あるため
    両方を拾う。片方だけの正規表現では大半を取りこぼす。
  - identity（Pin番号→slug→article_seq）は analyze-pin-metrics.py の build_local_index() を
    そのまま import して使う。同じ処理を二重実装しない。
  - 4群（情報量条件 × CTA条件）は pick-image-variation.py の conditions_for_seq() を
    import して使う。これが唯一の定義元であり、余りの計算をここへ書き写さない。
  - 構図variation は data/image-variation.tsv（pick-image-variation.py の read_ledger()）から
    引く。台帳は直近8記事分しか保持しないため大半のピンでは取れない。取れないピンには
    付けない（空欄のまま。推測で埋めない）。
  - 除外（eligible_for_comparison=false）は「比較対象として不適格」の意味であり、
    レコードは必ず保持する。削除しない（Pinterest全体の実績集計には使うため）。

保存の適法性（前提確認・2026-09-12）:
  Pinterest Developer Guidelines「The basics」は API 経由で得た情報の保存を原則禁じるが、
  「Except for campaign analytics information accessed about your account」という例外を置く。
  本スクリプトが保存するのは自アカウント自身のピンのanalyticsのみで、この例外に該当する。
  同ガイドラインに保存期間の上限・削除期限の定めは無い。

処理の流れ:
  1. output/Pin-images/ からPin母集団（Pin番号の集合）を作る。
  2. build_local_index() で Pin番号 から slug / article_seq / slot を引き、
     conditions_for_seq() で4群を、image-variation.tsv で構図variationを付ける。
  3. ローカル画像の画素サイズを Pillow で読み、2:3から許容誤差を超えてずれていれば除外印を付ける。
  4. GET /v5/pins を全件取得し、pin_id と Pin番号を突き合わせる
     （第1経路: link の utm_content=pin{N} / 第2経路: slug + 作成順。
      analyze-pin-metrics.py と同じ2経路）。
     同一Pin番号に複数のpin_idが割り当たったら duplicate_detected を立てる。
  5. 各 pin_id について GET /v5/pins/{pin_id}/analytics を1件ずつ呼び、daily_metrics を読む
     （summary_metrics ではない）。呼び出し間隔は ANALYTICS_INTERVAL_SECONDS。
  6. 既存TSVへ pin_id と date の組をキーに差分マージし、一時ファイル経由で置き換える。

差分更新の対象（--full-refresh 指定時を除く）:
  (1) 保存ファイルに存在しないPin（新規ピン）… 取得可能な全期間
  (2) 全Pinの直近 RECENT_REFETCH_DAYS 日分 … PROCESSING が READY へ変わるため再取得する
  それ以前の確定済みの日は再取得しない。

使い方:
  python site/scripts/fetch-pin-daily-metrics.py              # 通常の差分更新
  python site/scripts/fetch-pin-daily-metrics.py --dry-run    # APIを呼ばず対象件数と分類のみ表示
  python site/scripts/fetch-pin-daily-metrics.py --limit 5    # 先頭5件のPinのみ処理（検証用）
  python site/scripts/fetch-pin-daily-metrics.py --full-refresh  # 差分更新せず全期間を取り直す

終了コード:
  0 = 成功（個別ピンの取得失敗を含む場合も、件数を表示したうえで0）
  1 = 実行不能（トークン取得失敗・保存先書き込み不可など）
"""

import argparse
import datetime
import importlib.util
import os
import re
import sys
import time
import urllib.error
import urllib.parse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
import pinterest_api  # noqa: E402
import pinterest_token  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
PIN_IMAGES_DIR = os.path.join(ROOT, "output", "Pin-images")
OUTPUT_TSV = os.path.join(ROOT, "data", "pin-daily-metrics.tsv")


def _load_module(nickname, filename):
    """ファイル名にハイフンを含むスクリプトを importlib で読み込む（他スクリプトと同じ形）。"""
    spec = importlib.util.spec_from_file_location(
        nickname, os.path.join(SCRIPT_DIR, filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# identity と4群の判定は必ずこの2本の既存実装を通す（判定元をここに複製しない）。
apm = _load_module("analyze_pin_metrics", "analyze-pin-metrics.py")
piv = _load_module("pick_image_variation", "pick-image-variation.py")

# --- Pin母集団を決める2系統の命名（output/Pin-images/）。片方だけでは取りこぼす ---
PIN_NUM_ASCII_RE = re.compile(r"^pin-(\d+)-")     # pin-30-raikyaku-motenashi-icetea-01.png
PIN_NUM_JA_RE = re.compile(r"^ピン\s*(\d+)\D")     # ピン79 TWG Tea缶を....png
CROP_PREFIX = "_crop_"                             # 部分切り出し画像。母集団に含めない

# --- 品質フラグ ---
# Pinterest推奨の縦長2:3（幅÷高さ = 0.6667）からのずれの許容誤差。
# 既存の check-pin-image-dimensions.py が「2:3通り」と表示する判定と同じ 0.03 を採る
# （プロジェクト内で「2:3への近さ」の基準を2つ持たないため）。
TARGET_ASPECT_RATIO = 2.0 / 3.0
ASPECT_RATIO_TOLERANCE = 0.03

EXCLUSION_ASPECT = "aspect_ratio_not_2_3"
EXCLUSION_IDENTITY = "identity_unavailable"
EXCLUSION_DUPLICATE = "duplicate_detected"
EXCLUSION_REASONS = [EXCLUSION_ASPECT, EXCLUSION_IDENTITY, EXCLUSION_DUPLICATE]

# --- API ---
# GET /v5/pins/{id}/analytics のレート制限カテゴリは公式ドキュメント上で特定できなかったため、
# 厳しい方（org_write = 1分100リクエスト）を前提とする。0.7秒間隔なら1分あたり約85件で
# その制限に対し約85%の余裕がある。analyze-pin-metrics.py と同じ値を採る。
ANALYTICS_INTERVAL_SECONDS = 0.7
API_TIMEOUT_SECONDS = 20

# Pinterest analytics を日次で遡る範囲の上限（日）。これより古い日は取得しない。
MAX_LOOKBACK_DAYS = 90
# 差分更新で必ず取り直す直近日数（PROCESSING が READY へ確定するのを拾うため）。
RECENT_REFETCH_DAYS = 7

METRIC_TYPES = ["IMPRESSION", "SAVE", "OUTBOUND_CLICK", "PIN_CLICK"]
# TSVの列名 と APIのmetric名の対応
METRIC_COLUMNS = [
    ("impressions", "IMPRESSION"),
    ("saves", "SAVE"),
    ("outbound_clicks", "OUTBOUND_CLICK"),
    ("pin_clicks", "PIN_CLICK"),
]

COLUMNS = [
    "pin_id", "pin_number", "pin_url", "board_name", "created_at", "date", "fetched_at",
    "data_status", "impressions", "saves", "outbound_clicks", "pin_clicks",
    "article_slug", "article_seq", "group_info_density", "group_cta",
    "variation_angle", "variation_framing", "variation_text_position", "variation_background",
    "eligible_for_comparison", "exclusion_reason", "duplicate_detected",
]


# ---------------------------------------------------------------- Pin母集団

def collect_pin_population():
    """output/Pin-images/ から Pin番号 と画像パスの対応を作る（_crop_ 始まりは除外）。

    戻り値: (by_num, skipped_crop, unmatched)
      by_num: Pin番号 をキー、画像の絶対パスを値とする辞書
      unmatched: どちらの命名にも当てはまらなかったファイル名のリスト
    """
    by_num = {}
    skipped_crop = 0
    unmatched = []
    if not os.path.isdir(PIN_IMAGES_DIR):
        return by_num, skipped_crop, unmatched
    for name in sorted(os.listdir(PIN_IMAGES_DIR)):
        if name.startswith(CROP_PREFIX):
            skipped_crop += 1
            continue
        path = os.path.join(PIN_IMAGES_DIR, name)
        if not os.path.isfile(path):
            continue
        m = PIN_NUM_ASCII_RE.match(name) or PIN_NUM_JA_RE.match(name)
        if not m:
            unmatched.append(name)
            continue
        by_num.setdefault(int(m.group(1)), path)
    return by_num, skipped_crop, unmatched


def aspect_ratio_of(path):
    """画像の 幅÷高さ を返す。開けなければ None（欠落として扱い、値を捏造しない）。"""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(path) as im:
            width, height = im.size
    except Exception:
        return None
    if not height:
        return None
    return width / float(height)


def aspect_ratio_ok(ratio):
    """2:3から許容誤差以内かどうか。ratio が None（読めなかった）なら False。"""
    if ratio is None:
        return False
    return abs(ratio - TARGET_ASPECT_RATIO) <= ASPECT_RATIO_TOLERANCE


# ---------------------------------------------------------------- identity

def build_variation_index():
    """image-variation.tsv を (slug, image_type) をキーとする構図variationの辞書にする。

    台帳の読み込みは pick-image-variation.py の read_ledger() に任せる（形式の正本はあちら）。
    """
    index = {}
    try:
        rows = piv.read_ledger()
    except Exception:
        return index
    for row in rows:
        slug = (row.get("slug") or "").strip()
        image_type = (row.get("image_type") or "").strip()
        if not slug or not image_type:
            continue
        index[(slug, image_type)] = {
            "angle": (row.get("angle") or "").strip(),
            "framing": (row.get("framing") or "").strip(),
            "text_position": (row.get("text_position") or "").strip(),
            "background": (row.get("background") or "").strip(),
        }
    return index


def build_identity(pin_numbers, local_by_num, variation_index):
    """Pin番号ごとに identity（slug / article_seq / 4群 / 構図variation）を組み立てる。

    取れない項目は空文字のままにする（0 や "unknown" で埋めない）。
    """
    identity = {}
    for pin_num in pin_numbers:
        info = local_by_num.get(pin_num) or {}
        slug = info.get("slug") or ""
        article_seq = info.get("article_seq")
        slot = info.get("slot")

        info_density = ""
        cta = ""
        if article_seq is not None:
            # 4群の判定は pick-image-variation.py が唯一の定義元（余りの計算を書き写さない）
            info_density, cta = piv.conditions_for_seq(article_seq)

        variation = {}
        if slug and slot:
            variation = variation_index.get((slug, "pin%d" % slot), {})

        identity[pin_num] = {
            "article_slug": slug,
            "article_seq": "" if article_seq is None else str(article_seq),
            "group_info_density": info_density,
            "group_cta": cta,
            "variation_angle": variation.get("angle", ""),
            "variation_framing": variation.get("framing", ""),
            "variation_text_position": variation.get("text_position", ""),
            "variation_background": variation.get("background", ""),
        }
    return identity


def identity_available(identity_row):
    """4群を再計算できる identity かどうか（article_seq から両条件が引けたか）。"""
    return bool(identity_row.get("group_info_density")) and bool(identity_row.get("group_cta"))


# ---------------------------------------------------------------- 品質フラグ

def evaluate_quality(identity_row, image_path, assigned_pins):
    """比較対象としての適格性を判定する（判定ロジックはこの1関数に閉じる）。

    Growth Agent 側で同じ条件を再現できるよう、除外理由はここで決めた固定文字列を
    そのままTSVへ書く。除外はレコードを消すことを意味しない（行は必ず保持する）。

    引数:
      identity_row: build_identity() の1件
      image_path: ローカル画像のパス（無ければ None）
      assigned_pins: このPin番号に割り当たったAPI側ピンのリスト（重複検出に使う）
    戻り値: (eligible: bool, reasons: list, duplicate: bool)
    """
    reasons = []

    if not aspect_ratio_ok(aspect_ratio_of(image_path) if image_path else None):
        reasons.append(EXCLUSION_ASPECT)

    if not identity_available(identity_row):
        reasons.append(EXCLUSION_IDENTITY)

    duplicate = len(assigned_pins) > 1
    if duplicate:
        reasons.append(EXCLUSION_DUPLICATE)

    return (not reasons), reasons, duplicate


# ---------------------------------------------------------------- 既存TSVの読み書き

def read_existing():
    """既存TSVを読み、pin_id と date の組をキーとする行の辞書にする。無ければ空。"""
    rows = {}
    if not os.path.isfile(OUTPUT_TSV):
        return rows
    with open(OUTPUT_TSV, "r", encoding="utf-8") as f:
        header = None
        for line in f:
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            cells = line.split("\t")
            if header is None:
                header = cells
                continue
            row = dict(zip(header, cells))
            key = (row.get("pin_id", ""), row.get("date", ""))
            if key[0] and key[1]:
                rows[key] = row
    return rows


def write_atomic(rows):
    """一時ファイルへ書いてから置き換える。

    途中で失敗しても既存ファイルが壊れないようにするため必須
    （data/ はGit管理外で復旧手段がない）。
    """
    directory = os.path.dirname(OUTPUT_TSV)
    if not os.path.isdir(directory):
        os.makedirs(directory)
    tmp_path = OUTPUT_TSV + ".tmp"
    ordered = sorted(
        rows.values(),
        key=lambda r: (int(r.get("pin_number") or 0), r.get("date") or ""),
    )
    with open(tmp_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(COLUMNS) + "\n")
        for row in ordered:
            f.write("\t".join(str(row.get(c, "")) for c in COLUMNS) + "\n")
    os.replace(tmp_path, OUTPUT_TSV)


# ---------------------------------------------------------------- API取得

def fetch_daily(pin_id, access_token, start, end):
    """GET /v5/pins/{id}/analytics の daily_metrics を日付ごとの辞書で返す。

    値は (data_status, 指標の辞書)。失敗時は (None, 理由)。
    summary_metrics は使わない（日次の粒度が必要なため）。
    """
    params = urllib.parse.urlencode({
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "metric_types": ",".join(METRIC_TYPES),
    })
    path = "/pins/%s/analytics?%s" % (urllib.parse.quote(str(pin_id)), params)
    try:
        payload = pinterest_api.request(
            "GET", path, access_token, timeout=API_TIMEOUT_SECONDS)
    except pinterest_api.PinterestApiError as e:
        return None, "HTTP %s" % e.status_code
    except urllib.error.URLError as e:
        return None, "通信失敗: %s" % e

    daily = None
    if isinstance(payload, dict):
        if isinstance(payload.get("daily_metrics"), list):
            daily = payload["daily_metrics"]
        else:
            for value in payload.values():
                if isinstance(value, dict) and isinstance(value.get("daily_metrics"), list):
                    daily = value["daily_metrics"]
                    break
    if daily is None:
        # 推測で空を返さない（沈黙する失敗を作らないため）
        return None, "daily_metrics が取得できませんでした"

    day_map = {}
    for entry in daily:
        if not isinstance(entry, dict):
            continue
        date_key = entry.get("date")
        if not date_key:
            continue
        metrics = entry.get("metrics") or entry.get("metric") or {}
        day_map[date_key] = (entry.get("data_status") or "", metrics)
    return day_map, None


def resolve_pin_ids(all_pins, local_by_slug):
    """APIのピン一覧とローカルのPin番号を突き合わせる。

    analyze-pin-metrics.py と同じ2経路（第1: utm_content=pin{N} / 第2: slug + 作成順）。
    戻り値: (Pin番号ごとのピンのリスト, 特定不能件数)
    """
    by_num = {}
    unresolved = 0
    pending_by_slug = {}

    for pin in all_pins:
        link = pin.get("link") or ""
        pin_num = apm.pin_num_from_url(link)
        slug = apm.slug_from_url(link)
        pin["_created"] = apm.parse_created_at(pin.get("created_at"))
        if pin_num is not None and slug:
            by_num.setdefault(pin_num, []).append(pin)
        elif slug:
            pending_by_slug.setdefault(slug, []).append(pin)
        else:
            unresolved += 1

    # 第1経路で既にPin番号が確定した分は、第2経路の割当候補から除く
    # （同一slug内でUTM有り・無しが混在した場合に同じPin番号を二重に割り当てないため）。
    claimed_by_slug = {}
    for pin_num, pins in by_num.items():
        for pin in pins:
            slug = apm.slug_from_url(pin.get("link") or "")
            if slug:
                claimed_by_slug.setdefault(slug, set()).add(pin_num)

    for slug, pins in pending_by_slug.items():
        pins.sort(key=lambda p: (p["_created"] is None, p["_created"]))
        claimed = claimed_by_slug.get(slug, set())
        candidates = [i for i in sorted(local_by_slug.get(slug, []),
                                        key=lambda x: x["pin_num"])
                      if i["pin_num"] not in claimed]
        for idx, pin in enumerate(pins):
            if idx < len(candidates):
                by_num.setdefault(candidates[idx]["pin_num"], []).append(pin)
            else:
                unresolved += 1

    return by_num, unresolved


# ---------------------------------------------------------------- 主処理

def parse_args():
    parser = argparse.ArgumentParser(
        description="投稿済みPinのピン単位・日次実績を取得し data/pin-daily-metrics.tsv へ差分保存する")
    parser.add_argument("--dry-run", action="store_true",
                        help="APIを呼ばず、対象件数と分類だけを表示する")
    parser.add_argument("--limit", type=int, default=None,
                        help="先頭N件のPinのみ処理する（検証用）")
    parser.add_argument("--full-refresh", action="store_true",
                        help="差分更新せず全期間を取り直す（初回・保存ファイル破損時の復旧用）")
    return parser.parse_args()


def summary_line(target_total, identity_total, excluded_total, ok, fail):
    """Growth Agent が coverage として使う最終行（形式を変えないこと）。"""
    return ("対象Pin総数 %s / identity利用可能 %s / 除外件数 %s / 取得成功件数 %s / 失敗件数 %s"
            % (target_total, identity_total, excluded_total, ok, fail))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()

    print("=== Pin日次実績の取得（読み取り専用・GET系のみ） ===")

    # --- 1. Pin母集団 ---
    population, skipped_crop, unmatched = collect_pin_population()
    all_pin_numbers = sorted(population.keys())
    if not all_pin_numbers:
        print("【エラー】Pin母集団が0件です（%s を確認してください）。" % PIN_IMAGES_DIR)
        return 1
    print("Pin母集団: %d件（_crop_ 除外 %d件 / 命名不一致 %d件）"
          % (len(all_pin_numbers), skipped_crop, len(unmatched)))
    if unmatched:
        print("【注意】どちらの命名にも当てはまらないファイル: %s" % ", ".join(unmatched[:5]))
    missing = [n for n in range(1, max(all_pin_numbers) + 1) if n not in population]
    if missing:
        print("【注意】1〜%d のうち欠番: %s" % (max(all_pin_numbers), missing))

    # --- 2. identity ---
    local_by_num, local_by_slug = apm.build_local_index()
    variation_index = build_variation_index()
    identity = build_identity(all_pin_numbers, local_by_num, variation_index)

    pin_numbers = all_pin_numbers
    if args.limit is not None:
        pin_numbers = all_pin_numbers[:args.limit]
        print("--limit %d 指定のため先頭%d件のPinのみ処理します。"
              % (args.limit, len(pin_numbers)))

    identity_ok = [n for n in pin_numbers if identity_available(identity[n])]
    variation_ok = [n for n in pin_numbers if identity[n]["variation_angle"]]
    print("identity付与可能: %d件 / 構図variation付与可能: %d件"
          % (len(identity_ok), len(variation_ok)))

    # --- 3. 品質フラグ（重複はAPI取得後に確定するため、ここでは重複なしで仮判定する） ---
    preview = {}
    for pin_num in pin_numbers:
        preview[pin_num] = evaluate_quality(identity[pin_num], population.get(pin_num), [])

    excluded = [n for n in pin_numbers if not preview[n][0]]
    by_reason = {}
    for pin_num in excluded:
        for reason in preview[pin_num][1]:
            by_reason.setdefault(reason, []).append(pin_num)
    print("除外対象: %d件" % len(excluded))
    for reason in EXCLUSION_REASONS:
        nums = by_reason.get(reason, [])
        detail = ("（例: %s）" % nums[:5]) if nums else ""
        print("  %s: %d件%s" % (reason, len(nums), detail))

    if args.dry_run:
        print("")
        print("--dry-run のためAPIは呼びません（duplicate_detected は実取得時に確定します）。")
        print(summary_line(len(pin_numbers), len(identity_ok), len(excluded), "-", "-"))
        return 0

    # --- 4. トークンとピン一覧 ---
    try:
        status = pinterest_token.ensure_fresh()
        access_token = status["access_token"]
    except Exception as e:
        print("【エラー】Pinterestアクセストークンの準備に失敗しました: %s" % e)
        return 1

    try:
        all_pins = pinterest_api.fetch_all_pages(
            "/pins", access_token, timeout=API_TIMEOUT_SECONDS)
    except pinterest_api.PinterestApiError as e:
        print("【エラー】GET /v5/pins がHTTP %s を返しました: %s" % (e.status_code, e.body))
        return 1
    except urllib.error.URLError as e:
        print("【エラー】GET /v5/pins への通信に失敗しました: %s" % e)
        return 1

    pins_by_num, unresolved = resolve_pin_ids(all_pins, local_by_slug)
    print("APIのピン: %d件 / Pin番号に紐付いた番号数: %d / 特定不能: %d"
          % (len(all_pins), len(pins_by_num), unresolved))

    board_names = apm.load_board_names()
    rows = read_existing()
    known_pin_ids = set(pin_id for pin_id, _ in rows.keys())
    print("既存TSV: %d行（既知のpin_id %d件）" % (len(rows), len(known_pin_ids)))

    today = datetime.date.today()
    earliest_allowed = today - datetime.timedelta(days=MAX_LOOKBACK_DAYS - 1)
    fetched_at = datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()

    ok_count = 0
    fail_count = 0
    written_rows = 0
    duplicate_numbers = []

    for pin_num in pin_numbers:
        assigned = pins_by_num.get(pin_num) or []
        if not assigned:
            continue
        if len(assigned) > 1:
            duplicate_numbers.append(pin_num)

        eligible, reasons, duplicate = evaluate_quality(
            identity[pin_num], population.get(pin_num), assigned)

        for pin in assigned:
            pin_id = str(pin.get("id") or "")
            if not pin_id:
                continue
            created = pin.get("_created")
            created_date = created.date() if created else earliest_allowed

            if args.full_refresh or pin_id not in known_pin_ids:
                start = max(created_date, earliest_allowed)
            else:
                # 既知のピンは直近 RECENT_REFETCH_DAYS 日だけ取り直す
                # （それ以前の確定済みの日は再取得しない）
                start = max(created_date, earliest_allowed,
                            today - datetime.timedelta(days=RECENT_REFETCH_DAYS - 1))
            if start > today:
                start = today

            day_map, error = fetch_daily(pin_id, access_token, start, today)
            time.sleep(ANALYTICS_INTERVAL_SECONDS)
            if day_map is None:
                fail_count += 1
                print("  Pin%d (%s): 取得失敗 - %s" % (pin_num, pin_id, error))
                continue
            ok_count += 1

            for date_key in sorted(day_map.keys()):
                data_status, metrics = day_map[date_key]
                row = {
                    "pin_id": pin_id,
                    "pin_number": pin_num,
                    "pin_url": "https://www.pinterest.com/pin/%s/" % pin_id,
                    "board_name": board_names.get(str(pin.get("board_id") or ""), ""),
                    "created_at": created.date().isoformat() if created else "",
                    "date": date_key,
                    "fetched_at": fetched_at,
                    "data_status": data_status,
                    "eligible_for_comparison": "true" if eligible else "false",
                    "exclusion_reason": ";".join(reasons),
                    "duplicate_detected": "true" if duplicate else "false",
                }
                row.update(identity[pin_num])
                for column, api_name in METRIC_COLUMNS:
                    value = metrics.get(api_name)
                    # 値が取れない列は空欄にする
                    # （0 で埋めると「欠落」と「値が0」を利用側が区別できなくなる）
                    row[column] = str(int(value)) if isinstance(value, (int, float)) else ""
                rows[(pin_id, date_key)] = row
                written_rows += 1

    if duplicate_numbers:
        print("【注意】同一Pin番号に複数のピンが割り当たりました: %s" % duplicate_numbers)

    try:
        write_atomic(rows)
    except OSError as e:
        print("【エラー】保存先に書き込めませんでした（%s）: %s" % (OUTPUT_TSV, e))
        return 1

    print("保存: %s（総 %d行 / 今回の書き込み・更新 %d行）"
          % (os.path.relpath(OUTPUT_TSV, ROOT), len(rows), written_rows))
    print(summary_line(len(pin_numbers), len(identity_ok), len(excluded),
                       ok_count, fail_count))
    return 0


if __name__ == "__main__":
    sys.exit(main())
