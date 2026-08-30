# -*- coding: utf-8 -*-
r"""未投稿ピンをBuffer経由でX・Instagram・Threadsへ送る本体スクリプト（ラウンド2）。

処理順序（この順を崩さない）:
  (0) 緊急停止スイッチ。data/ 直下に「buffer-auto-post-off」で始まる名前の
      ファイルが1つでもあれば、ファイル名を表示して何もせず正常終了する。
      **他のどの処理よりも先に判定する**（.env読み込みもAPI通信も行わない）。
      Pinterest側の pin-auto-post-off とは別ファイルにしてある。
      片方だけ止められるようにするため（Pinterestは動かしたいがSNSは止めたい、
      あるいはその逆、という状態を作れるようにする）。
  (1) APIキーの期限確認。.env の BUFFER_API_KEY_EXPIRES_AT をローカルの
      日付比較だけで判定する（通信しない）。Bufferの個人APIキーには
      リフレッシュの仕組みが無く、期限が来たら設定画面で発行し直すしかない
      （https://developers.buffer.com/guides/authentication.html）。
      期限切れ → 再発行手順を表示して終了コード2。
      残り30日未満 → 【警告】を出したうえで処理は続行する。
  (2) チャンネル解決。data/buffer-channels.tsv を読み、instagram / threads /
      twitter の3つが揃っていなければ終了コード2で止める。APIから毎回引かない
      のは参照系クエリもレート制限（24時間250リクエスト）を消費するため。
  (3) 未投稿の導出。台帳は data/buffer-posted.md。「ピン番号 × サービス」の
      組を単位にする。ピン番号の抽出は check-pin-posting-status.py の
      extract_created_pins() をimportして再利用する（同じ判定を二重実装すると
      片方だけ直って食い違うため）。
  (4) 上限判定。「当日すでに投稿した件数 ＋ 今回の対象件数」が
      DAILY_LIMIT（30件＝10ピン×3チャンネル）を超えるなら、1件も投稿せず
      件数だけ報告して終了する。
  (5) 本文の組み立て。送信先で構成が違う。
      Instagram・Threads … 説明文＋誘導文＋誘導先URL（従来どおり）。誘導文は
        固定3種からピン番号の3で割った余りで機械的に選ぶ（自由入力は受け付けない）。
      X … ピンmdの「- X用説明文: 」行＋改行＋誘導先URL。誘導文は付けない。
        共通の説明文はXの数え方だと必ず280を超えるため、Xだけ専用の短い本文を
        持たせる（書式は rules/pinterest-api.md「X向けの説明文」節が正本）。
        この行が無い／空／2行以上あるピンは **X投稿だけ** を理由つきでスキップし、
        Instagram・Threadsへの投稿はそのまま続ける。
  (6) X向けの文字数判定。X重み（全角=2 / 半角=1 / URLは長さに関わらず23）と
      実文字数（Bufferの入力検証が見る）の**両方**が280以下でなければ
      **そのピンのX投稿だけ**をスキップする。自動切り詰めはしない
      （文末が途中で切れた投稿が公開されるのを防ぐため）。
      数え方・上限・本文の組み立ての正本は check-x-post-length.py。
  (7) 画像の公開。publish-pin-images.py の変換処理をimportして呼び、
      site/public/pin-images/pin{番号}.jpg を作る。続けて site/ リポジトリで
      add・commit・push まで本スクリプト内で完結させる（変換だけしてcommitして
      いない状態を作らないため、この3つは分離しない）。pushは窓口が事前承認済み
      （D-0079）。その後、公開URLがHTTP 200かつ Content-Type が image/jpeg で
      返ることを初回＋最大5回・各30秒待ちで確認する。200にならない画像は
      そのピンを全チャンネルスキップする。
  (8) 投稿。buffer_api.py 経由で createPost を呼ぶ。
      mode: addToQueue / schedulingType: automatic / dueAt は指定しない。
      = Bufferのキューへ入れ、各チャンネルの投稿枠で順に公開される。
      shareNow（即時公開）は使わない（3チャンネルが同時刻に並ぶのを避けるため）。
      1件ごとに POST_INTERVAL_SECONDS 待つ。失敗は握りつぶさず、ピン番号・
      サービス・エラー内容を出力して次へ進む。
  (9) 成功のつど台帳へ1行追記する（3チャンネル分をまとめて最後に書かない。
      1つ失敗したときに再試行で二重投稿になるため）。
 (10) 公開画像の刈り込み。**投稿処理がすべて終わってから**、
      publish-pin-images.py の KEEP_LIMIT（番号降順で60件）まで
      site/public/pin-images/ を刈り込み、削除分をcommit・pushする。
      ただし削除前に参照系クエリで Buffer のキュー（status=scheduled）に
      残っている投稿を引き、その本文の utm_content=pin{番号} が指すピン番号は
      件数上限を超えていても削除対象から除外する（公開前に画像URLが消えると
      投稿が壊れるため。今の運用では60件を超えないが、超えないことを人が
      覚えている設計にしない）。キューを読めなかったときは1件も削除しない。

公式ドキュメントで確認した点（2026-08-30）:
  - createPost の戻り値は union で、成功は PostActionSuccess、失敗は
    MutationError（message を持つ）。**GraphQLの errors 配列に出ない
    「typed mutation error」がある**ため、data 側の __typename も必ず見る
    （https://developers.buffer.com/guides/error-handling.html）。
  - レート制限は 15分100 / 24時間250 / 30日3,000リクエスト。超過は HTTP 429。
    本スクリプトの1回の実行が使うのは「対象件数＋0」リクエストで、
    上限30件でも24時間枠の250に収まる。
  - assets は image / video / document / link のどれか1つだけを持つ要素の配列。
    画像URLは「投稿が公開されるまで」到達可能である必要がある（作成時点だけでは
    足りない・https://developers.buffer.com/guides/hosting-media.html）。
  - Xの文字数はUTF-16コード単位で数え、URLは23・絵文字は2として重み付けされる
    （https://developers.buffer.com/guides/character-limits.html）。

ドキュメントと実挙動が食い違った点（いずれも2026-08-30にピン198で実測）:
  - **XのURL重み付けは createPost の入力検証には適用されない。**
    23で数えて203文字（URL実長込みで338文字）の本文が
    「Twitter / X posts cannot exceed 280 characters.」で弾かれた。
    → 判定はX重みと実文字数の両方で行う（check-x-post-length.py が正本）。
    さらに、日本語の全角文字はX側で1文字あたり2として数えられるため、
    Pinterest向けの説明文（200字前後）はどうやってもXには載らない。
    → Xだけ「- X用説明文: 」行の専用本文を使う（(5) 参照）。
  - **Instagramは metadata.instagram が必須。**
    reference.html の createPost の例（examples/create-image-post.html）は
    metadata を省いているが、Instagramチャンネルへ送ると
    「Instagram posts require a type (post, story, or reel).」で弾かれた。
    → SERVICE_METADATA で type=post / shouldShareToFeed=true を添える。

オプション:
  --dry-run          画像変換・commit・push・投稿を一切行わず、対象一覧と
                     組み立てた本文（3サービス分）を表示するだけ。
  --only <ピン番号>  指定した番号のみを対象にする。

使い方:
  python site/scripts/post-pins-to-buffer.py --dry-run --only 198
  python site/scripts/post-pins-to-buffer.py --only 198
  python site/scripts/post-pins-to-buffer.py
"""

import datetime
import importlib.util
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
SITE = os.path.join(ROOT, "site")
DATA_DIR = os.path.join(ROOT, "data")
PINS_DIR = os.path.join(ROOT, "output", "pins")
LEDGER_PATH = os.path.join(DATA_DIR, "buffer-posted.md")
CHANNELS_TSV_PATH = os.path.join(DATA_DIR, "buffer-channels.tsv")

KILL_SWITCH_PREFIX = "buffer-auto-post-off"

if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# 1日の上限（10ピン × 3チャンネル）。引数では変えない。
DAILY_LIMIT = 30

# APIキーの残日数がこれを下回ったら【警告】を出す（処理は止めない）。
KEY_EXPIRY_WARN_DAYS = 30

# 送信先サービス。台帳・TSV・Buffer側の service 名はすべてこの表記で揃える。
SERVICES = ("twitter", "instagram", "threads")

# サービス名 → 誘導先URLの utm_source に入れる値。X は utm_source=x にする
# （Buffer側の service 名は twitter のままなので、両者を取り違えないよう
#  変換表をここ1箇所に置く）。
UTM_SOURCE_BY_SERVICE = {
    "twitter": "x",
    "instagram": "instagram",
    "threads": "threads",
}

# 誘導文はこの3つだけ。ピン番号を3で割った余りで機械的に選ぶ。
# 自由入力を受け付けないのは、投稿ごとに文言がぶれるのを防ぐため。
CTA_LINES = (
    "👇詳しい手順はブログで公開中☕️",
    "👇続きはブログにまとめています☕️",
    "👇詳しくはブログでどうぞ☕️",
)

# Xの文字数の数え方・上限・X用説明文の扱いは check-x-post-length.py が正本で、
# ここでは書き写さない（同じ判定を二重実装すると片方だけ直って食い違うため）。
#
# 判定は2つの上限を同時に見る。
#   ・X側の数え方（全角=2 / 半角=1 / URLは長さに関わらず23）
#   ・Buffer の createPost の入力検証（全角・半角を区別せず、URLも実長のまま数える）
# 2026-08-30の実測: 23で数えると203文字の本文（URLの実長を含めると338）が
# 「Twitter / X posts cannot exceed 280 characters.」で弾かれた。
# どちらか一方でも超えたら**そのピンのX投稿だけ**をスキップする。切り詰めは行わない。

# サービスごとに createPost へ添える metadata。
# Instagramは metadata.instagram の type（PostType!）と shouldShareToFeed（Boolean!）が
# 必須で、省くと InvalidInputError
# 「Instagram posts require a type (post, story, or reel).」で弾かれる
# （2026-08-30実測。https://developers.buffer.com/reference.html の
#  InstagramPostMetadataInput）。フィード投稿として送るので type=post とする。
# twitter / threads は metadata なしで通る（同日実測）。
SERVICE_METADATA = {
    "instagram": {"instagram": {"type": "post", "shouldShareToFeed": True}},
}

POST_INTERVAL_SECONDS = 3
URL_CHECK_TIMEOUT_SECONDS = 15
URL_CHECK_MAX_RETRIES = 5
URL_CHECK_RETRY_WAIT_SECONDS = 30
GIT_TIMEOUT = 180

DESC_RE = re.compile(r"^説明文:\s*(.+)$")
GUIDE_URL_RE = re.compile(r"^-\s*誘導先URL:\s*(.+)$")
# X（twitter）だけに使う短い専用本文。0行または1行。
# 共通の説明文はXの数え方だと必ず280を超えるため、Xだけ別の本文を持たせる
# （書式・目的は rules/pinterest-api.md「X向けの説明文」節が正本）。
X_DESC_RE = re.compile(r"^-\s*X用説明文:\s*(.*)$")

# 台帳の書式。
# 「投稿済み: {ピン番号} {service}」  … 二重投稿防止の判定に使う（日付を持たない）
# 「投稿日: YYYY-MM-DD {ピン番号} {service}」 … 当日件数を数えるために併記する
POSTED_LINE_RE = re.compile(r"^投稿済み:\s*(\d+)\s+([A-Za-z]+)\s*$")
POSTED_DATE_LINE_RE = re.compile(r"^投稿日:\s*(\d{4}-\d{2}-\d{2})\s+(\d+)\s+([A-Za-z]+)\s*$")

CREATE_POST_MUTATION = """
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    __typename
    ... on PostActionSuccess {
      post {
        id
        status
        dueAt
        text
      }
    }
    ... on MutationError {
      message
    }
  }
}
"""


# --- (0) 緊急停止スイッチ -------------------------------------------------------


def check_kill_switch():
    """data/ 直下に「buffer-auto-post-off」で始まるファイルがあればその名前を返す。

    拡張子は問わない（Windowsのエクスプローラーでは拡張子なしファイルを作れないため、
    buffer-auto-post-off.txt でも確実に検知できるようにする）。
    Pinterest側の pin-auto-post-off とは独立で、片方だけ止められる。
    """
    if not os.path.isdir(DATA_DIR):
        return None
    try:
        names = os.listdir(DATA_DIR)
    except OSError:
        return None
    matches = sorted(
        n for n in names
        if n.startswith(KILL_SWITCH_PREFIX) and os.path.isfile(os.path.join(DATA_DIR, n))
    )
    return matches[0] if matches else None


# --- (1) APIキーの期限 ----------------------------------------------------------


REISSUE_INSTRUCTIONS = (
    "  1. https://publish.buffer.com/settings/api を開き、既存のAPIキーを失効させて\n"
    "     新しいキーを発行する（Bufferの個人APIキーにはリフレッシュの仕組みが無い）\n"
    "  2. プロジェクトルートの .env の次の2行を書き換える\n"
    "       BUFFER_API_KEY=<新しいキー>\n"
    "       BUFFER_API_KEY_EXPIRES_AT=<新しい期限日 YYYY-MM-DD>\n"
    "  3. python site/scripts/buffer-list-channels.py で疎通を確認する"
)


def check_key_expiry(today, get_env_func):
    """APIキーの期限をローカルの日付比較だけで判定する（通信しない）。

    戻り値: (状態, メッセージ行のリスト)
      状態は "ok" / "warn" / "expired" / "invalid" のいずれか。
    """
    raw = get_env_func("BUFFER_API_KEY_EXPIRES_AT")
    if not raw:
        return "invalid", [
            "【エラー】.env に BUFFER_API_KEY_EXPIRES_AT がありません（または空です）。",
            "キーの期限日（YYYY-MM-DD）を設定してから再実行してください。",
        ]
    try:
        expires = datetime.date(*(int(x) for x in raw.strip().split("-")))
    except (ValueError, TypeError):
        return "invalid", [
            "【エラー】BUFFER_API_KEY_EXPIRES_AT が YYYY-MM-DD 形式ではありません: %s" % raw,
        ]

    remaining = (expires - today).days
    if remaining < 0:
        return "expired", [
            "【エラー】Buffer APIキーの期限が切れています（期限 %s・%d日経過）。"
            % (expires.isoformat(), -remaining),
            "投稿は行いません。次の手順でキーを再発行してください:",
            REISSUE_INSTRUCTIONS,
        ]
    if remaining < KEY_EXPIRY_WARN_DAYS:
        return "warn", [
            "【警告】Buffer APIキーの残り日数が %d日です（期限 %s）。"
            % (remaining, expires.isoformat()),
            "期限内に再発行してください:",
            REISSUE_INSTRUCTIONS,
        ]
    return "ok", [
        "APIキー期限: %s（残り %d日）" % (expires.isoformat(), remaining)
    ]


# --- (2) チャンネル解決 ---------------------------------------------------------


def load_channels(path=CHANNELS_TSV_PATH):
    """data/buffer-channels.tsv を読み {service: (channel_id, name)} を返す。

    ファイルが無い場合も空dictを返す（呼び出し元が「揃っていない」として扱う）。
    """
    channels = {}
    if not os.path.isfile(path):
        return channels
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.rstrip("\n").rstrip("\r")
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            service, channel_id, name = parts[0].strip().lower(), parts[1].strip(), parts[2].strip()
            if lineno == 1 and service == "service":
                continue  # ヘッダー行
            if not service or not channel_id:
                continue
            channels[service] = (channel_id, name)
    return channels


# --- (3) 未投稿の導出 -----------------------------------------------------------


def _load_check_pin_posting_status():
    """check-pin-posting-status.py をモジュールとして読み込む
    （ファイル名がハイフンを含み、そのままではimportできないため）。"""
    path = os.path.join(SCRIPT_DIR, "check-pin-posting-status.py")
    spec = importlib.util.spec_from_file_location("check_pin_posting_status", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_publish_pin_images():
    """publish-pin-images.py をモジュールとして読み込む（同上）。"""
    path = os.path.join(SCRIPT_DIR, "publish-pin-images.py")
    spec = importlib.util.spec_from_file_location("publish_pin_images", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_XCHECK_CACHE = []


def _load_check_x_post_length():
    """check-x-post-length.py をモジュールとして読み込む（1プロセスにつき1回）。

    module直下で読まず関数の中で読むのは、あちらが module 直下でこのファイルを
    読み込むため（相互に module 直下で読むと循環する）。X の数え方・上限・本文の
    組み立てはあちらが正本であり、ここへ書き写さない。
    """
    if _XCHECK_CACHE:
        return _XCHECK_CACHE[0]
    path = os.path.join(SCRIPT_DIR, "check-x-post-length.py")
    spec = importlib.util.spec_from_file_location("check_x_post_length", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _XCHECK_CACHE.append(mod)
    return mod


def load_posted_pairs(path=LEDGER_PATH):
    """台帳から投稿済みの (ピン番号, service) の集合を返す。ファイルが無ければ空集合。"""
    posted = set()
    if not os.path.isfile(path):
        return posted
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = POSTED_LINE_RE.match(line.strip())
            if m:
                posted.add((int(m.group(1)), m.group(2).lower()))
    return posted


def count_today_posted(today_str, path=LEDGER_PATH):
    """台帳の「投稿日: YYYY-MM-DD N service」行のうち today_str と一致する件数。"""
    if not os.path.isfile(path):
        return 0
    count = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = POSTED_DATE_LINE_RE.match(line.strip())
            if m and m.group(1) == today_str:
                count += 1
    return count


def append_ledger(pin_num, service, today_str, path=LEDGER_PATH):
    """投稿成功1件を台帳へ追記する（2行1組）。まとめ書きはしない。"""
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    exists = os.path.isfile(path)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        if not exists:
            f.write("# Buffer経由でSNSへ投稿済みのピン（post-pins-to-buffer.pyが自動追記する）\n")
            f.write("# 「投稿済み:」行が二重投稿防止の判定に使われる。手で並べ替えない。\n\n")
        f.write("投稿済み: %d %s\n" % (pin_num, service))
        f.write("投稿日: %s %d %s\n" % (today_str, pin_num, service))


def derive_targets(created_map, posted_pairs, only=None):
    """「作成済みピン番号 × 3サービス」から台帳の組を引いた差集合を返す。

    戻り値: [(pin_num, file_name, [service, ...]), ...]（ピン番号の昇順）
    """
    targets = []
    for pin_num in sorted(created_map.keys()):
        if only is not None and pin_num != only:
            continue
        pending = [s for s in SERVICES if (pin_num, s) not in posted_pairs]
        if not pending:
            continue
        targets.append((pin_num, created_map[pin_num][0], pending))
    return targets


# --- (5) 本文の組み立て ---------------------------------------------------------


def parse_pin_file(file_name):
    """ピンファイルから説明文・X用説明文・誘導先URLを読む。

    戻り値: (dict または None, 理由)
    x_description は0行のとき None（X投稿だけをスキップする材料になる。
    Instagram・Threadsは同じピンでも投稿を続ける）。
    """
    path = os.path.join(PINS_DIR, file_name)
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError as e:
        return None, "ファイル読み込み失敗: %s" % e

    description = None
    guide_url = None
    x_descriptions = []
    for line in lines:
        stripped = line.strip()
        if description is None:
            m = DESC_RE.match(stripped)
            if m:
                description = m.group(1).strip()
        if guide_url is None:
            m = GUIDE_URL_RE.match(stripped)
            if m:
                guide_url = m.group(1).strip()
        m = X_DESC_RE.match(stripped)
        if m:
            x_descriptions.append(m.group(1).strip())

    if not description:
        return None, "「説明文:」行が見つからないか空です"
    if not guide_url:
        return None, "「- 誘導先URL:」行が見つからないか空です"

    # 2行以上あるとどれを送るかが決まらないため、Xだけ見送る材料として None にする。
    x_description = x_descriptions[0] if len(x_descriptions) == 1 else None
    x_reason = None
    if not x_descriptions:
        x_reason = "「- X用説明文: 」行がありません"
    elif len(x_descriptions) > 1:
        x_reason = "「- X用説明文: 」行が%d本あります（1ファイルにつき0行または1行）" % len(x_descriptions)
    elif not x_description:
        x_description = None
        x_reason = "「- X用説明文: 」行が空です"

    return {
        "description": description,
        "guide_url": guide_url,
        "x_description": x_description,
        "x_reason": x_reason,
    }, None


def pick_cta(pin_num):
    """ピン番号を3で割った余りで誘導文を選ぶ（自由入力は受け付けない）。"""
    return CTA_LINES[pin_num % len(CTA_LINES)]


def rewrite_utm_source(url, service):
    """誘導先URLの utm_source だけを送信先に応じて差し替える。

    utm_medium / utm_campaign / utm_content とクエリの並び順は変えない
    （Pinterest向けの計測設計をそのまま引き継ぐため）。
    """
    new_source = UTM_SOURCE_BY_SERVICE[service]
    parts = urllib.parse.urlsplit(url)
    pairs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    if any(k == "utm_source" for k, _ in pairs):
        pairs = [(k, new_source if k == "utm_source" else v) for k, v in pairs]
    else:
        pairs.append(("utm_source", new_source))
    query = urllib.parse.urlencode(pairs)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def build_text(pin_num, fields, service):
    """投稿本文を組み立てる。戻り値: (本文, 差し替え後のURL) または (None, 理由)

    Instagram・Threads … 説明文 ＋ 空行 ＋ 誘導文 ＋ 改行 ＋ 誘導先URL（従来どおり）
    X（twitter）        … X用説明文 ＋ 改行 ＋ 誘導先URL（誘導文は付けない）

    X に誘導文を付けないのは、280という上限に対して誘導文が固定で
    十数文字（X重みでは倍）を占め、本文に載せられる情報が削れるため。
    """
    url = rewrite_utm_source(fields["guide_url"], service)
    if service == "twitter":
        if not fields.get("x_description"):
            return None, fields.get("x_reason") or "X用説明文がありません"
        xcheck = _load_check_x_post_length()
        return xcheck.build_x_text(fields["x_description"], url), url
    body = "%s\n\n%s\n%s" % (fields["description"], pick_cta(pin_num), url)
    return body, url


# --- (6) Xの文字数判定（数え方の正本は check-x-post-length.py） -----------------


def x_length_verdict(text, url):
    """X向け本文の長さを判定する。戻り値: (送ってよいか, X重み, 実文字数)"""
    xcheck = _load_check_x_post_length()
    raw = xcheck.raw_length(text)
    weighted = xcheck.x_weighted_length(text, url)
    limit = xcheck.X_CHAR_LIMIT
    return (weighted <= limit and raw <= limit), weighted, raw


# --- (7) 画像の公開 -------------------------------------------------------------


def git(*args):
    return subprocess.run(
        ["git", "-C", SITE] + list(args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=GIT_TIMEOUT,
    )


def publish_images(pin_nums, out):
    """対象ピンのJPEGを site/public/pin-images/ に生成する。

    戻り値: (公開URLの dict {pin_num: url}, 変換できなかった {pin_num: 理由})
    """
    mod = _load_publish_pin_images()
    if not os.path.isdir(mod.OUTPUT_DIR):
        os.makedirs(mod.OUTPUT_DIR)

    urls = {}
    failed = {}
    for pin_num in pin_nums:
        source_path, matches = mod.find_source(pin_num)
        if source_path is None:
            reason = "正本PNGが0件" if not matches else "正本PNGが%d件で特定できない" % len(matches)
            failed[pin_num] = reason
            continue
        dest_path = os.path.join(mod.OUTPUT_DIR, "pin%d.jpg" % pin_num)
        try:
            src_size, out_size, size_bytes = mod.convert(source_path, dest_path)
        except (ValueError, OSError) as e:
            failed[pin_num] = "変換失敗: %s" % e
            continue
        urls[pin_num] = "%s/pin%d.jpg" % (mod.PUBLIC_URL_BASE, pin_num)
        out("  ピン%d: %dx%d → %dx%d  %d bytes  %s"
            % (pin_num, src_size[0], src_size[1], out_size[0], out_size[1], size_bytes, urls[pin_num]))
    return urls, failed


def commit_and_push_images(out, message="publish: pin images for SNS"):
    """site/public/pin-images/ をadd・commit・pushする。

    変換だけしてcommitしていない状態を作らないため、変換の直後に必ず呼ぶ。
    刈り込み（削除）の反映にも同じ関数を使う（`git add <ディレクトリ>` は
    追跡済みファイルの削除もステージするため、追加と削除で処理を分けない）。
    戻り値: (成功したか, メッセージ)
    """
    result = git("add", "--", "public/pin-images")
    if result.returncode != 0:
        return False, "git add に失敗しました: %s" % (result.stderr or result.stdout).strip()

    staged = git("diff", "--cached", "--quiet", "--", "public/pin-images")
    if staged.returncode == 0:
        out("  ステージ対象に差分が無いため commit はスキップ（画像は既に公開済み）")
    elif staged.returncode == 1:
        result = git("commit", "-m", message)
        if result.returncode != 0:
            return False, "git commit に失敗しました: %s" % (result.stderr or result.stdout).strip()
        out("  git commit: %s" % message)
    else:
        return False, "git diff --cached の判定に失敗しました: %s" % (staged.stderr or staged.stdout).strip()

    ahead = git("rev-list", "--count", "@{u}..HEAD")
    if ahead.returncode == 0 and ahead.stdout.strip() == "0":
        out("  git push は差分なしのためスキップ（origin/main と同一）")
        return True, ""
    result = git("push")
    if result.returncode != 0:
        return False, "git push に失敗しました: %s" % (result.stderr or result.stdout).strip()
    out("  git push 完了")
    return True, ""


def wait_for_image(url, out):
    """公開URLが200かつ Content-Type が image/jpeg で返るまで待つ。

    初回確認 ＋ 最大 URL_CHECK_MAX_RETRIES 回・各 30秒待ち。
    戻り値: (到達できたか, 最後の状態を表す文字列)
    """
    last = ""
    for attempt in range(URL_CHECK_MAX_RETRIES + 1):
        if attempt > 0:
            out("    %d秒待って再確認します（%d/%d回目）"
                % (URL_CHECK_RETRY_WAIT_SECONDS, attempt, URL_CHECK_MAX_RETRIES))
            time.sleep(URL_CHECK_RETRY_WAIT_SECONDS)
        try:
            request = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(request, timeout=URL_CHECK_TIMEOUT_SECONDS) as response:
                status = response.status
                ctype = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                response.read(1024)
            last = "HTTP %s / Content-Type %s" % (status, ctype or "(なし)")
            if status == 200 and ctype == "image/jpeg":
                return True, last
        except urllib.error.HTTPError as e:
            last = "HTTP %s" % e.code
        except urllib.error.URLError as e:
            last = "接続失敗: %s" % e.reason
        out("    %s" % last)
    return False, last


# --- (8) 投稿 -------------------------------------------------------------------


def build_create_post_input(channel_id, text, image_url, service):
    """createPost に渡す CreatePostInput を組み立てる。

    mode=addToQueue / schedulingType=automatic / dueAt なし で、Bufferの
    キューへ入れる（各チャンネルの投稿枠で順に公開される）。
    shareNow は使わない（3チャンネルが同時刻に並ぶのを避けるため）。
    """
    payload = {
        "channelId": channel_id,
        "text": text,
        "mode": "addToQueue",
        "schedulingType": "automatic",
        "assets": [{"image": {"url": image_url}}],
    }
    metadata = SERVICE_METADATA.get(service)
    if metadata:
        payload["metadata"] = metadata
    return payload


def create_post(graphql, payload):
    """createPost を1回呼ぶ。戻り値: (成功したか, 説明文字列)

    GraphQLの errors 配列に出ない typed mutation error（MutationError）が
    あるため、data 側の __typename も必ず見る。
    """
    data = graphql(CREATE_POST_MUTATION, {"input": payload}, operation_name="CreatePost")
    result = (data or {}).get("createPost") or {}
    typename = result.get("__typename")
    if typename == "PostActionSuccess":
        post = result.get("post") or {}
        return True, "postId=%s status=%s dueAt=%s" % (
            post.get("id"), post.get("status"), post.get("dueAt"))
    return False, "%s: %s" % (typename or "(型不明)", result.get("message") or result)


# --- (10) 公開画像の刈り込み（キューに残る投稿の参照分は除外） ------------------


# 誘導先URLの utm_content からピン番号を取り出す。
# 投稿本文に残る唯一の機械可読なピン番号がこれで、UTMの構成は変えない約束
# （rules/pinterest-api.md・GA4の計測をPinterestと揃えるため）なので当てにできる。
PIN_UTM_RE = re.compile(r"utm_content=pin(\d+)")

ACCOUNT_QUERY = """
query Account {
  account { organizations { id } }
}
"""

# キューに残っている（まだ公開されていない）投稿。status は enum で、
# 値は scheduled（2026-08-30に PostStatus enum を実測して確認）。
SCHEDULED_POSTS_QUERY = """
query ScheduledPosts($organizationId: OrganizationId!) {
  posts(input: {organizationId: $organizationId, filter: {status: scheduled}}) {
    pageInfo { hasNextPage }
    edges { node { id status dueAt channelId text } }
  }
}
"""


def fetch_scheduled_pin_numbers(graphql):
    """Bufferのキュー（status=scheduled）に残る投稿が参照するピン番号の集合を返す。

    戻り値: (集合 または None, 説明文字列)
    None は「取得できなかった」を表す。取得できなかったときに空集合を返すと
    「除外すべき番号が無い」と区別できず、公開前の画像を消してしまうため。
    """
    data = graphql(ACCOUNT_QUERY, operation_name="Account")
    orgs = ((data or {}).get("account") or {}).get("organizations") or []
    if not orgs:
        return None, "組織IDを取得できませんでした"

    numbers = set()
    truncated = False
    for org in orgs:
        data = graphql(
            SCHEDULED_POSTS_QUERY,
            {"organizationId": org["id"]},
            operation_name="ScheduledPosts",
        )
        posts = (data or {}).get("posts") or {}
        if ((posts.get("pageInfo") or {}).get("hasNextPage")):
            truncated = True
        for edge in posts.get("edges") or []:
            text = (edge.get("node") or {}).get("text") or ""
            for match in PIN_UTM_RE.finditer(text):
                numbers.add(int(match.group(1)))
    if truncated:
        # 続きのページを読まないまま「除外対象はこれだけ」と決めると
        # 読めていない投稿の画像を消しうるので、取得できなかった扱いにする。
        return None, "キューが1ページに収まらず全件を読めませんでした"
    return numbers, "キューに残る投稿が参照するピン番号: %s" % (
        ", ".join(str(n) for n in sorted(numbers)) if numbers else "なし")


def prune_published_images(graphql, out):
    """公開画像を KEEP_LIMIT 件まで刈り込む。キューが参照する番号は残す。

    件数上限を超えていても、まだ公開されていない投稿が参照している画像を
    消すとその投稿が壊れるため、削除対象から必ず除外する。
    """
    # buffer_api は main() と同じく関数の中で読む（module直下で読むと
    # 緊急停止スイッチの判定より先に .env を読みに行くため）。
    from buffer_api import BufferApiError, BufferGuardError  # noqa: E402

    mod = _load_publish_pin_images()
    if not os.path.isdir(mod.OUTPUT_DIR):
        out("  公開先ディレクトリがまだありません。刈り込みは行いません。")
        return

    try:
        protected, note = fetch_scheduled_pin_numbers(graphql)
    except (BufferApiError, BufferGuardError) as e:
        protected, note = None, "キューの取得に失敗しました: %s" % e
    out("  %s" % note)
    if protected is None:
        out("  除外すべき番号を確定できないため、削除は1件も行いません。")
        return

    doomed = mod.select_files_to_delete(os.listdir(mod.OUTPUT_DIR))
    kept = []
    to_delete = []
    for name in doomed:
        match = mod.OUTPUT_NAME_RE.match(name)
        number = int(match.group(1)) if match else None
        if number is not None and number in protected:
            kept.append(number)
            continue
        to_delete.append(name)

    if kept:
        out("  上限超過だがキューが参照しているため残した番号: %s"
            % ", ".join(str(n) for n in sorted(kept)))
    if not to_delete:
        out("  削除なし（上限 %d件・現在 %d件）" % (
            mod.KEEP_LIMIT,
            len([n for n in os.listdir(mod.OUTPUT_DIR) if mod.OUTPUT_NAME_RE.match(n)]),
        ))
        return

    for name in to_delete:
        os.remove(os.path.join(mod.OUTPUT_DIR, name))
        out("  削除: %s" % name)
    ok, message = commit_and_push_images(out, message="prune: pin images for SNS")
    if not ok:
        out("  【警告】削除のcommit・pushに失敗しました: %s" % message)
        out("  ファイルは既に削除済みです。site/ で手動commitしてください。")


# --- メイン ---------------------------------------------------------------------


def parse_args(argv):
    """戻り値: (dict または None)。None は使い方エラー。"""
    opts = {"dry_run": False, "only": None}
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--dry-run":
            opts["dry_run"] = True
        elif arg == "--only":
            if i + 1 >= len(argv) or not argv[i + 1].isdigit():
                sys.stderr.write("--only にはピン番号（正の整数）を指定してください。\n")
                return None
            opts["only"] = int(argv[i + 1])
            i += 1
        else:
            sys.stderr.write(
                "不明な引数です: %s\n"
                "使い方: python site/scripts/post-pins-to-buffer.py "
                "[--dry-run] [--only <ピン番号>]\n" % arg
            )
            return None
        i += 1
    return opts


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    def out(msg=""):
        print(msg)

    opts = parse_args(argv)
    if opts is None:
        return 2

    # (0) 緊急停止スイッチ。他のどの処理よりも先。
    switch = check_kill_switch()
    if switch:
        out("緊急停止スイッチが有効です: data/%s" % switch)
        out("Buffer経由の投稿は行いません（Pinterest側の pin-auto-post-off とは独立です）。")
        return 0

    from env_loader import get_env, EnvLoaderError  # noqa: E402
    from buffer_api import graphql, BufferApiError, BufferGuardError  # noqa: E402

    today = datetime.date.today()
    today_str = today.isoformat()

    # (1) APIキーの期限
    out("=== APIキー期限の確認（通信せずローカル比較のみ） ===")
    try:
        state, messages = check_key_expiry(today, get_env)
    except EnvLoaderError as e:
        out("【エラー】%s" % e)
        return 2
    for line in messages:
        out(line)
    if state in ("expired", "invalid"):
        return 2
    out()

    # (2) チャンネル解決
    out("=== チャンネルの解決（data/buffer-channels.tsv） ===")
    channels = load_channels()
    missing = [s for s in SERVICES if s not in channels]
    if missing:
        out("【エラー】台帳に次のサービスがありません: %s" % ", ".join(missing))
        out("python site/scripts/buffer-list-channels.py --save を実行してください。")
        return 2
    for service in SERVICES:
        channel_id, name = channels[service]
        out("  %-10s channelId=%s  name=%s" % (service, channel_id, name))
    out()

    # (3) 未投稿の導出
    check_mod = _load_check_pin_posting_status()
    created_map = check_mod.extract_created_pins()
    posted_pairs = load_posted_pairs()
    targets = derive_targets(created_map, posted_pairs, only=opts["only"])

    out("=== 対象の導出（output/pins のピン番号 × 3サービス − 台帳） ===")
    out("  作成済みピン: %d件 / 台帳の投稿済み: %d組" % (len(created_map), len(posted_pairs)))
    if opts["only"] is not None:
        out("  --only %d が指定されています" % opts["only"])
        if opts["only"] not in created_map:
            out("【エラー】ピン%d の投稿文ファイルが output/pins/ にありません。" % opts["only"])
            return 2
    if not targets:
        out("  投稿対象は0件です（すべて投稿済み）。")
        return 0
    unit_count = sum(len(services) for _, _, services in targets)
    for pin_num, file_name, services in targets:
        out("  ピン%d: %s → %s" % (pin_num, ", ".join(services), file_name))
    out("  対象件数: %d件（%dピン）" % (unit_count, len(targets)))
    out()

    # (4) 上限
    today_count = count_today_posted(today_str)
    out("=== 1日の上限の確認（上限 %d件） ===" % DAILY_LIMIT)
    out("  本日すでに投稿: %d件 ＋ 今回の対象: %d件 = %d件"
        % (today_count, unit_count, today_count + unit_count))
    if today_count + unit_count > DAILY_LIMIT:
        out("  上限 %d件 を超えるため、1件も投稿せず終了します。" % DAILY_LIMIT)
        return 0
    out("  上限内です。")
    out()

    # (5)(6) 本文の組み立てと、Xの文字数見積もり
    out("=== 投稿本文の組み立て ===")
    xcheck = _load_check_x_post_length()
    plans = []  # [(pin_num, [(service, text, url), ...])]
    for pin_num, file_name, services in targets:
        fields, reason = parse_pin_file(file_name)
        if fields is None:
            out("  スキップ: ピン%d — %s" % (pin_num, reason))
            continue
        entries = []
        for service in services:
            text, url = build_text(pin_num, fields, service)
            if text is None:
                # X用説明文が無い／複数ある場合。X投稿だけを見送り、
                # Instagram・Threadsは同じピンでもそのまま投稿する。
                out("  スキップ: ピン%d の X 投稿 — %s" % (pin_num, url))
                out("            書式: 「%s<%d字以内の本文>」（rules/pinterest-api.md）"
                    % (xcheck.X_DESC_LABEL, xcheck.X_DESC_TARGET_CHARS))
                out("            Instagram・Threadsへは投稿します。")
                continue
            if service == "twitter":
                ok, weighted, raw = x_length_verdict(text, url)
                if not ok:
                    _rw, _ww, need_fw, need_hw = xcheck.shortfall(raw, weighted)
                    out("  スキップ: ピン%d の X 投稿 — 上限 %d文字を超えます"
                        % (pin_num, xcheck.X_CHAR_LIMIT))
                    out("            X重み（全角=2 / URLは%d）: %d文字"
                        % (xcheck.X_URL_WEIGHT, weighted))
                    out("            実文字数（Bufferの検証がこちらを見る）: %d文字" % raw)
                    out("            あと 全角なら%d文字 / 半角なら%d文字 削れば両方を満たします"
                        % (need_fw, need_hw))
                    out("            自動切り詰めは行いません。Instagram・Threadsへは投稿します。")
                    continue
            entries.append((service, text, url))
        if entries:
            plans.append((pin_num, entries))

    if not plans:
        out("  投稿できる本文がありません。")
        return 0

    for pin_num, entries in plans:
        for service, text, url in entries:
            out()
            out("  --- ピン%d / %s（誘導先 utm_source=%s） ---"
                % (pin_num, service, UTM_SOURCE_BY_SERVICE[service]))
            out(text)
            if service == "twitter":
                _ok, weighted, raw = x_length_verdict(text, url)
                out("  [Xの文字数: X重み %d（全角=2・URLは%d）/ 実文字数 %d / 上限 %d]"
                    % (weighted, xcheck.X_URL_WEIGHT, raw, xcheck.X_CHAR_LIMIT))
    out()

    if opts["dry_run"]:
        out("=== --dry-run のため、画像変換・commit・push・投稿はいずれも行いません ===")
        out("  投稿予定: %d件" % sum(len(e) for _, e in plans))
        out("  createPost へ渡す予定の入力値（画像URLは変換後に確定する）:")
        out("    mode=addToQueue / schedulingType=automatic / dueAt=指定しない")
        out("    → Bufferのキューへ入り、各チャンネルの投稿枠で順に公開される")
        out("    assets=[{image:{url: <上記の公開URL>}}]")
        for service in SERVICES:
            out("    metadata（%s）= %s" % (service, SERVICE_METADATA.get(service) or "添えない"))
        return 0

    # (7) 画像の公開
    out("=== 画像の変換・commit・push ===")
    pin_nums = [pin_num for pin_num, _ in plans]
    image_urls, image_failed = publish_images(pin_nums, out)
    for pin_num, reason in image_failed.items():
        out("  スキップ: ピン%d — %s" % (pin_num, reason))
    ok, message = commit_and_push_images(out)
    if not ok:
        out("【エラー】%s" % message)
        out("画像が公開されていないため、投稿は1件も行いません。")
        return 1
    out()

    out("=== 公開画像の到達確認（HTTP 200 かつ Content-Type: image/jpeg） ===")
    reachable = {}
    for pin_num in pin_nums:
        if pin_num not in image_urls:
            continue
        out("  ピン%d: %s" % (pin_num, image_urls[pin_num]))
        ok, last = wait_for_image(image_urls[pin_num], out)
        if ok:
            out("    到達確認OK（%s）" % last)
            reachable[pin_num] = image_urls[pin_num]
        else:
            out("    スキップ: ピン%d は全チャンネル見送り（最後の応答: %s）" % (pin_num, last))
    out()

    # (8)(9) 投稿
    out("=== Bufferへの投稿（mode=addToQueue / schedulingType=automatic） ===")
    succeeded = 0
    failed = 0
    skipped = 0
    first = True
    for pin_num, entries in plans:
        if pin_num not in reachable:
            skipped += len(entries)
            continue
        for service, text, _url in entries:
            if not first:
                time.sleep(POST_INTERVAL_SECONDS)
            first = False
            channel_id = channels[service][0]
            payload = build_create_post_input(channel_id, text, reachable[pin_num], service)
            try:
                ok, detail = create_post(graphql, payload)
            except (BufferApiError, BufferGuardError) as e:
                out("  失敗: ピン%d / %s — %s" % (pin_num, service, e))
                failed += 1
                continue
            if ok:
                append_ledger(pin_num, service, today_str)
                out("  成功: ピン%d / %s — %s（台帳へ1行追記）" % (pin_num, service, detail))
                succeeded += 1
            else:
                out("  失敗: ピン%d / %s — %s" % (pin_num, service, detail))
                failed += 1

    # (10) 投稿処理がすべて終わってから公開画像を刈り込む。
    # 投稿より先に消すと、これから送る投稿の画像URLが消えるため順序を入れ替えない。
    out()
    out("=== 公開画像の刈り込み（上限 %d件・キューが参照する番号は除外） ==="
        % _load_publish_pin_images().KEEP_LIMIT)
    prune_published_images(graphql, out)

    out()
    out("=== 結果 ===")
    out("  成功 %d件 / 失敗 %d件 / 画像未到達によるスキップ %d件" % (succeeded, failed, skipped))
    if failed or skipped:
        out("  失敗・スキップ分は台帳に記録していないため、次回の実行で再試行されます。")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
