# -*- coding: utf-8 -*-
r"""投稿済みPinの「型 × 実成果」を集計する（読み取り専用・手動実行のみ）。

目的:
  Pin画像の型（写真ヒーロー・比較グリッド等・D-0062）ごとに、実際の
  インプレッション／クリック／保存がどう違うかを実績で確認する。
  推測ではなく実測で設計判断するための材料を作る。

設計方針:
  - 日次ルーチン・セッション開始チェック・フックからは呼ばない（手動実行のみ）。
    Pinterest APIのレート制限（Standardは1分100リクエスト）と、記事数の増加に
    比例して処理量が増えることを避けるため。
  - Pinterest APIへのアクセスは pinterest_api.py の単一入口経由（GET系のみ）。
    POST/PATCH/DELETE は一切行わない。
  - 型の正本は output/pins/ 配下のピンファイルの「## 画像指示書」節の
    「- 型: ○○」行。data/image-variation.tsv は使わない（直近8記事で
    自動削除される仕様のため長期集計の正本にならない・D-0062関連）。
  - 出力先 data/pin-metrics.tsv はGit管理外。既存があれば上書きする。

処理の流れ:
  1. GET /v5/pins を bookmark ページングで全件取得する（pin_metrics付き）。
     created_at が実行日から WINDOW_DAYS 以内のものだけを対象にする。
     対象が MAX_PINS を超えたら集計を行わず件数のみ報告して終了する。
  2. 各ピンの「自前のPin番号」と「slug」を特定する。
     第1経路: link の utm_content=pin{N} / utm_campaign={slug}
     第2経路: link のURLパス /posts/{slug}/ から slug を取り、同一slug内で
              created_at 昇順に1枚目→pin1、2枚目→pin2、3枚目→pin3 と割り当て、
              ローカルのピンファイル索引から実際のPin番号を引く。
     どちらでも特定できないものは「特定不能」として除外する。
  3. 型をローカルのピンファイルから引く。
  4. 指標は手順1の pin_metrics を優先し、揃っていない場合のみ
     GET /v5/pins/{pin_id}/analytics を1件ずつ呼ぶ（間隔は ANALYTICS_INTERVAL_SECONDS）。
  5. data/pin-metrics.tsv へ出力し、標準出力に型別／スロット別／ボード別／文言件数別／
     4群別（情報量×CTA）の5表を出す（表4・表5はD-0152の条件比較用）。
     表5の群分けは記事連番（ピンファイルの「- 記事連番:」行）を4で割った余りで決め、
     実際の文言件数は「設計と一致しないピンの件数と割合」を併記する補助列にのみ使う（D-0158）。
     ただし CTA_START_DATE より前に作成されたピンは実際にはCTA帯が焼かれていないため、
     余りに関わらず群から外し「対象外（CTA運用開始前）」行に計上する（D-0159）。
     文言件数はピンファイルのプロンプト全文から実際に数えた件数で、数えられないピンは
     「不明」として別行に集計する。CTAの有無も同じくプロンプト全文にCTA文言
     （pick-image-variation.py の CTA_TEXTS）が含まれるかで判定する（意図ではなく実際の
     指示内容から判定するため）。CTA導入前（CTA_START_DATE より前に作成）のピンは
     「CTAなし」ではなく「不明」に寄せる（当時はCTAという選択肢自体が無く、条件の一方の
     群として扱えないため）。

--verify-saves オプション:
  上記の通常処理に加え、インプレッション上位5件について GET /v5/pins/{pin_id}/analytics
  を個別に呼び、lifetime_metrics（pin_metrics）側のSAVEが実測と一致するかを比較する。
  呼び出しはちょうど5件のみ（全件取得は行わない）。通常時の挙動・出力には影響しない。

使い方:
  python site/scripts/analyze-pin-metrics.py
  python site/scripts/analyze-pin-metrics.py --verify-saves
"""

import datetime
import os
import re
import sys
import time
import urllib.error
import urllib.parse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
from env_loader import require_env, EnvLoaderError  # noqa: E402
import pinterest_api  # noqa: E402

# 条件の定義（4群の振り分け・CTA文言）は pick-image-variation.py を唯一の定義元とする。
# ファイル名にハイフンを含むため通常のimportができず、importlibで読み込む（他スクリプトと同じ形）。
import importlib.util  # noqa: E402

_piv_spec = importlib.util.spec_from_file_location(
    "pick_image_variation", os.path.join(SCRIPT_DIR, "pick-image-variation.py")
)
piv = importlib.util.module_from_spec(_piv_spec)
_piv_spec.loader.exec_module(piv)

ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
PINS_DIR = os.path.join(ROOT, "output", "pins")
BOARDS_FILE = os.path.join(ROOT, "data", "pinterest-boards.md")
OUTPUT_TSV = os.path.join(ROOT, "data", "pin-metrics.tsv")

# --- 処理量の上限（記事数の増加に比例して処理が増えないよう1箇所に固定する） ---
MAX_PINS = 200        # 対象がこれを超えたら集計せず件数のみ報告して終了
WINDOW_DAYS = 90      # created_at がこの日数以内のピンだけを対象にする

# analytics を個別に呼ぶ場合の呼び出し間隔（秒）。
# Standardのレート制限は1分100リクエスト。0.7秒間隔なら1分あたり約85件で余裕がある。
ANALYTICS_INTERVAL_SECONDS = 0.7

# --- --verify-saves オプション用（lifetime_metricsのSAVEが実測と一致するかの検証） ---
VERIFY_SAVES_FLAG = "--verify-saves"
VERIFY_SAVES_TOP_N = 5  # インプレッション上位何件を検証するか（ちょうどこの件数だけ呼ぶ）
VERIFY_SAVES_INTERVAL_SECONDS = 0.7
# インプレッションの「概ね一致」判定のしきい値（相対誤差）。これを超えたら食い違いとみなす。
VERIFY_SAVES_IMPRESSION_TOLERANCE = 0.10

API_TIMEOUT_SECONDS = 20

# 集計に使う4指標。キーは内部名、値は analytics の metric_types 名。
METRIC_KEYS = [
    ("impression", "IMPRESSION"),
    ("pin_click", "PIN_CLICK"),
    ("outbound_click", "OUTBOUND_CLICK"),
    ("save", "SAVE"),
]

# 型の正規化。ピンファイルの「- 型:」行は表記ゆれがあるため、
# pick-image-variation.py の IMAGE_STYLES に合わせて寄せる。
# ここに無い値は寄せずにそのまま別バケットとして扱う（勝手に統合しない）。
CANONICAL_STYLES = [
    "写真ヒーロー", "比較グリッド", "手順図解", "チェックリスト",
    "ビフォーアフター", "Q&A形式", "ポイント整理", "ランキング",
    "数字訴求型", "用語解説型", "シーン別ガイド", "相関図フローチャート",
]
# 語尾の「型」除去・括弧注記の除去では寄せられない表記だけを明示的に列挙する。
STYLE_ALIASES = {
    "質疑応答形式": "Q&A形式",
}

# 文言件数（D-0152）。make-image-prompt.py が出す「文言その一：「…」」の連番から数える。
# 意図（低情報量条件かどうか）ではなく、実際にプロンプトへ書いた件数を集計するため、
# 別途フラグを記録する方式は取らない。
TEXT_ITEM_RE = re.compile(r"文言その([一二三四五六七八九十]+)")
_KANJI_DIGITS = "〇一二三四五六七八九"
TEXT_COUNT_UNKNOWN = "不明"
TEXT_COUNT_LOW = "1〜2件"
TEXT_COUNT_HIGH = "3件以上"
TEXT_COUNT_NOTICE = (
    "文言件数を機械的に数えられるのは make-image-prompt.py 経由で作成したピンのみ。\n"
    "2026-08-22より前のピンはすべて不明に集計される。条件比較には不明行を使わないこと。"
)

# CTAの有無（D-0152）。ピンファイルに記録されたプロンプト全文にCTA文言が含まれるかで判定する。
# 「CTAを入れるつもりだったか」ではなく「実際にそう指示したか」を見るため、別途フラグは持たない。
CTA_UNKNOWN = "不明"
CTA_START_DATE = datetime.date(2026, 8, 23)  # CTA条件の運用開始日
CTA_NOTICE = (
    "TSVのCTA列（表5の群分類には使わない・D-0158）のCTAの有無は、ピンファイルの"
    "プロンプト全文にCTA文言（%s）が含まれるかで判定する。\n"
    "%s より前に作成されたピンはCTAという選択肢自体が無かったため、CTA列はすべて不明になり、"
    "表5でも群から外れて「対象外（CTA運用開始前）」行に入る。"
    % ("／".join(piv.CTA_TEXTS), CTA_START_DATE.isoformat())
)

# 表5（4群別）の行ラベル。群は記事連番（article_seq）から決めるため、
# pick-image-variation.py の条件名を表示用の言い方へ寄せるだけにする（D-0158）。
CONDITION_INFO_LABEL = {
    piv.CONDITION_LOW: "情報少なめ",
    piv.CONDITION_CURRENT: "情報多め",
}
CONDITION_GROUP_UNKNOWN = "不明"
# CTA運用開始前に作成されたピンの区分。記事連番の余りではCTAあり／なしの群に当たるが、
# 実際にはCTA帯が焼かれていないため、4群の比較対象から外してこの行に計上する。
CONDITION_GROUP_PRE_CTA = "対象外（CTA運用開始前）"

# 表5の補助列（実文言件数が設計と一致しないピンの件数と割合）の見出し。
DEVIATION_HEADER = "設計と不一致の文言件数"

GROUP_NOTICE = (
    "表5の群は記事連番（output/pins/*.md の「- 記事連番:」行）を4で割った余りで決まる"
    "（D-0158）。実際の文言件数は分類に使わず、設計との乖離の監視にのみ使う。\n"
    "記事連番の行が無いピンは「不明」行に入る。\n"
    "CTA運用開始（%s）より前に作成されたピンは、余りの上ではCTAあり／なしの群に当たっても"
    "実際にはCTA帯が焼かれていないため、群の集計から外して「%s」行に計上する（D-0159）。"
    % (CTA_START_DATE.isoformat(), CONDITION_GROUP_PRE_CTA)
)

# 旧仕様のまま作られたピンの注記（群からの除外はしない・D-0158）。
LEGACY_PIN_NOTICE = (
    "【注記】seq35（pin157〜159）は旧仕様（3枚とも同一のCTA文言・帯色が背景依存）で"
    "作成されたピンだが、群からは除外していない。"
)

# 記事連番の行（rules/image-generation-flow.md・書き漏れは check-pin-board.py が拒否する）。
ARTICLE_SEQ_RE = re.compile(r"^-\s*記事連番:\s*([0-9]+)\s*$")

TYPE_LINE_RE = re.compile(r"^-\s*型:\s*(.+)$")
GUIDE_URL_RE = re.compile(r"^-\s*誘導先URL:\s*(\S+)\s*$")
PIN_FILE_NUM_RE = re.compile(r"pin-(\d+)")
UTM_PIN_RE = re.compile(r"^pin(\d+)$")


# ---------------------------------------------------------------- ローカル索引

def normalize_style(raw):
    """ピンファイルの型表記を正規化する。戻り値: (正規化後, 元の表記から変えたか)。"""
    value = raw.strip()
    # 「ランキング（表現は非序列に変更・下記参照）」のような括弧注記を落とす
    value = re.split(r"[（(]", value, 1)[0].strip()
    if value in CANONICAL_STYLES:
        return value, value != raw.strip()
    if value in STYLE_ALIASES:
        return STYLE_ALIASES[value], True
    # 「写真ヒーロー型」→「写真ヒーロー」のような語尾の「型」を落とす
    if value.endswith("型") and value[:-1] in CANONICAL_STYLES:
        return value[:-1], True
    return value, value != raw.strip()


def kanji_to_int(value):
    """「三」「十二」等の漢数字を整数にする。解釈できなければ None。"""
    try:
        if value == "十":
            return 10
        if "十" in value:
            upper, lower = value.split("十", 1)
            tens = _KANJI_DIGITS.index(upper) if upper else 1
            ones = _KANJI_DIGITS.index(lower) if lower else 0
            return tens * 10 + ones
        return _KANJI_DIGITS.index(value)
    except ValueError:
        return None


def count_text_items(content):
    """ピンファイル全文から、そのPinに指定された文言の件数を数える（D-0152）。

    make-image-prompt.py（D-0148）は焼き込む文言を「文言その一：「…」」の形で連番付きに
    出力する。作り直しのたびに同じ連番が繰り返し現れるため、出現回数ではなく連番の最大値を
    件数とする。この形式を持たないピン（D-0148以前の手組みプロンプト）は None を返し、
    呼び出し側で「不明」として別に集計する。
    """
    indexes = set()
    for raw in TEXT_ITEM_RE.findall(content):
        n = kanji_to_int(raw)
        if n:
            indexes.add(n)
    return max(indexes) if indexes else None


def text_count_bucket(count):
    """文言件数を集計バケット名にする。"""
    if count is None:
        return TEXT_COUNT_UNKNOWN
    return TEXT_COUNT_LOW if count <= 2 else TEXT_COUNT_HIGH


def has_cta_text(content):
    """ピンファイル全文にCTA文言のいずれかが含まれるか（D-0152）。"""
    return any(t in content for t in piv.CTA_TEXTS)


def cta_bucket(cta_found, created_date):
    """CTAの有無を集計バケット名にする（あり／なし／不明・D-0152）。

    CTA_START_DATE より前に作成されたピンは、当時CTAという選択肢自体が無かったため
    「CTAなし」ではなく「不明」に寄せる（比較対象の群として扱えないため）。
    """
    if created_date is None or created_date < CTA_START_DATE or cta_found is None:
        return CTA_UNKNOWN
    return piv.CTA_YES if cta_found else piv.CTA_NONE


def created_before_cta(created_at):
    """作成日がCTA運用開始日より前か（判定できない場合は False＝除外しない）。

    created_at は rows の "created_at"（YYYY-MM-DD 文字列）。
    """
    if not created_at:
        return False
    try:
        return datetime.date.fromisoformat(created_at) < CTA_START_DATE
    except ValueError:
        return False


def condition_group(row):
    """情報量×CTAの4群のラベルを返す（D-0152・分類基準はD-0158で記事連番へ変更）。

    群は記事連番を4で割った余りだけで決まる（判定元は pick-image-variation.py の
    conditions_for_seq()。余りの計算はここに複製しない）。実際の文言件数・CTAの有無は
    分類に使わない。結果側の実績で群を決めると各群の件数が事前に読めず、低密度に
    振れたピンだけが情報少なめ群へ混入するため（D-0158）。
    記事連番が記録されていないピンは「不明」になる。
    CTA運用開始（CTA_START_DATE）より前に作成されたピンは、余りがCTAあり／なしの
    どちらに当たっても実際にはCTA帯が焼かれていないため、群の集計から外して
    CONDITION_GROUP_PRE_CTA に計上する。
    """
    if created_before_cta(row.get("created_at")):
        return CONDITION_GROUP_PRE_CTA
    seq = row.get("article_seq")
    if seq is None:
        return CONDITION_GROUP_UNKNOWN
    condition, cta = piv.conditions_for_seq(seq)
    info = CONDITION_INFO_LABEL.get(condition)
    if info is None:
        return CONDITION_GROUP_UNKNOWN
    return "%s・%s" % (info, cta)


def text_count_matches_design(row):
    """実際の文言件数が、記事連番から決まる設計上の件数と一致するか。

    戻り値: True（一致）／False（不一致）／None（判定不可＝記事連番か文言件数が無い）。
    低情報量条件は piv.LOW_INFO_TEXT_MIN〜MAX 件、現行条件はそれを超える件数を設計とする。
    """
    seq = row.get("article_seq")
    count = row.get("text_count")
    if seq is None or count is None:
        return None
    if piv.condition_for_seq(seq) == piv.CONDITION_LOW:
        return piv.LOW_INFO_TEXT_MIN <= count <= piv.LOW_INFO_TEXT_MAX
    return count > piv.LOW_INFO_TEXT_MAX


def deviation_summary(rows):
    """表5の補助列。群ごとに「実文言件数が設計と一致しないピン」の件数と割合を作る。

    文言件数を数えられないピン（make-image-prompt.py 以前の手組み）は分母に入れない。
    """
    stats = {}
    for row in rows:
        s = stats.setdefault(condition_group(row), {"judged": 0, "mismatch": 0})
        verdict = text_count_matches_design(row)
        if verdict is None:
            continue
        s["judged"] += 1
        if not verdict:
            s["mismatch"] += 1
    summary = {}
    for key, s in stats.items():
        if s["judged"] == 0:
            summary[key] = "判定不可（文言件数を数えられるピンなし）"
        else:
            summary[key] = "%d件/%d件（%.0f%%）" % (
                s["mismatch"], s["judged"], s["mismatch"] * 100.0 / s["judged"])
    return summary


def parse_pin_file(path):
    """1ピンファイルから 型 / 誘導先URL / 記事連番 / 文言件数 / CTAの有無 を読む。戻り値: dict。"""
    style_raw = None
    guide_url = None
    article_seq = None
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return None
    for line in content.split("\n"):
        stripped = line.strip()
        if style_raw is None:
            m = TYPE_LINE_RE.match(stripped)
            if m:
                style_raw = m.group(1).strip()
                continue
        if guide_url is None:
            m = GUIDE_URL_RE.match(stripped)
            if m:
                guide_url = m.group(1).strip()
                continue
        if article_seq is None:
            m = ARTICLE_SEQ_RE.match(stripped)
            if m:
                article_seq = int(m.group(1))
    return {
        "style_raw": style_raw,
        "guide_url": guide_url,
        "article_seq": article_seq,
        "text_count": count_text_items(content),
        "cta_found": has_cta_text(content),
    }


def slug_from_url(url):
    """URLから記事slugを取り出す。/posts/{slug}/ を優先し、無ければ utm_campaign。"""
    if not url:
        return None
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


def pin_num_from_url(url):
    """URLの utm_content=pin{N} からPin番号を取り出す。取れなければ None。"""
    if not url:
        return None
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return None
    content = urllib.parse.parse_qs(parsed.query).get("utm_content")
    if not content:
        return None
    m = UTM_PIN_RE.match(content[0].strip())
    return int(m.group(1)) if m else None


def build_local_index():
    """output/pins/ を読み、Pin番号 -> {style, slug, slot} の索引を作る。

    slot は同一slug内のPin番号昇順で 1,2,3... を割り当てたもの。
    型が記載されていないピン（型導入前のpin1〜83）も索引には入れるが style は None。
    """
    by_num = {}
    if not os.path.isdir(PINS_DIR):
        return by_num, {}

    for name in sorted(os.listdir(PINS_DIR)):
        if not name.endswith(".md"):
            continue
        m = PIN_FILE_NUM_RE.search(name)
        if not m:
            continue
        pin_num = int(m.group(1))
        parsed = parse_pin_file(os.path.join(PINS_DIR, name))
        if parsed is None:
            continue
        style = None
        style_changed = False
        if parsed["style_raw"]:
            style, style_changed = normalize_style(parsed["style_raw"])
        by_num[pin_num] = {
            "pin_num": pin_num,
            "file_name": name,
            "style": style,
            "style_raw": parsed["style_raw"],
            "style_normalized": style_changed,
            "slug": slug_from_url(parsed["guide_url"]),
            "article_seq": parsed["article_seq"],
            "text_count": parsed["text_count"],
            "cta_found": parsed["cta_found"],
        }

    # slug ごとに Pin番号昇順で slot を振る
    by_slug = {}
    for info in by_num.values():
        if info["slug"]:
            by_slug.setdefault(info["slug"], []).append(info)
    for slug, infos in by_slug.items():
        infos.sort(key=lambda x: x["pin_num"])
        for i, info in enumerate(infos, start=1):
            info["slot"] = i

    for info in by_num.values():
        info.setdefault("slot", None)

    return by_num, by_slug


def load_board_names():
    """data/pinterest-boards.md から board_id -> ボード名 の辞書を作る。"""
    mapping = {}
    if not os.path.isfile(BOARDS_FILE):
        return mapping
    with open(BOARDS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 2:
                continue
            if not cells[1].isdigit():
                continue
            mapping[cells[1]] = cells[0]
    return mapping


# ---------------------------------------------------------------- API取得

def parse_created_at(value):
    """Pinterestの created_at（ISO8601）を aware datetime にする。失敗時 None。"""
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def extract_pin_metrics(pin_metrics):
    """GET /v5/pins の pin_metrics から4指標を取り出す。

    Pinterest v5 の pin_metrics は集計期間ごとの入れ子（all_time / 90d 等）に
    なっている。期間名は将来変わりうるため、キー名を決め打ちせず
    「4指標のうち最も多く揃っている入れ子」を採用する。
    戻り値: (指標dict, 採用した期間名) / 取れなければ (None, None)。
    """
    if not isinstance(pin_metrics, dict):
        return None, None

    wanted = [k for k, _ in METRIC_KEYS]

    def pick(d):
        if not isinstance(d, dict):
            return None
        lowered = {str(k).lower(): v for k, v in d.items()}
        found = {}
        for key in wanted:
            if key in lowered and isinstance(lowered[key], (int, float)):
                found[key] = lowered[key]
        return found or None

    candidates = []
    direct = pick(pin_metrics)
    if direct:
        candidates.append(("(直下)", direct))
    for period, sub in pin_metrics.items():
        got = pick(sub)
        if got:
            candidates.append((str(period), got))
    if not candidates:
        return None, None

    # 「all_time」系を優先しつつ、揃っている指標数が多いものを採る
    def score(item):
        period, found = item
        preferred = 1 if "all" in period.lower() or "life" in period.lower() else 0
        return (len(found), preferred)

    period, found = max(candidates, key=score)
    return found, period


def fetch_analytics(pin_id, access_token, created_at, now):
    """GET /v5/pins/{id}/analytics で4指標のサマリを取る。失敗時 (None, 理由)。"""
    earliest = (now - datetime.timedelta(days=WINDOW_DAYS - 1)).date()
    start = max(created_at.date(), earliest) if created_at else earliest
    end = now.date()
    if start > end:
        start = end
    params = urllib.parse.urlencode({
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "metric_types": ",".join(m for _, m in METRIC_KEYS),
    })
    path = "/pins/%s/analytics?%s" % (urllib.parse.quote(str(pin_id)), params)
    try:
        data = pinterest_api.request("GET", path, access_token, timeout=API_TIMEOUT_SECONDS)
    except pinterest_api.PinterestApiError as e:
        return None, "HTTP %s" % e.status_code
    except urllib.error.URLError as e:
        return None, "通信失敗: %s" % e

    section = data.get("all") if isinstance(data, dict) else None
    summary = section.get("summary_metrics") if isinstance(section, dict) else None
    if not isinstance(summary, dict):
        return None, "summary_metrics が取得できませんでした"

    result = {}
    for key, api_name in METRIC_KEYS:
        value = summary.get(api_name)
        result[key] = value if isinstance(value, (int, float)) else 0
    return result, None


# ---------------------------------------------------------------- 集計・出力

def aggregate(rows, key_func):
    """rows を key_func 単位で集計する。戻り値: [(キー, 集計dict), ...]。"""
    buckets = {}
    for row in rows:
        key = key_func(row)
        b = buckets.setdefault(key, {
            "count": 0, "days": 0.0,
            "impression": 0.0, "pin_click": 0.0,
            "outbound_click": 0.0, "save": 0.0,
        })
        b["count"] += 1
        b["days"] += row["elapsed_days"]
        for metric, _ in METRIC_KEYS:
            b[metric] += row[metric]
    return sorted(buckets.items(), key=lambda kv: -kv[1]["impression"])


def format_table(title, header, buckets, extra_header=None, extra_values=None):
    """集計表を組み立てる。extra_header を渡した表だけ右端に補助列を1つ足す（D-0158）。"""
    width = 78 if extra_header is None else 108
    lines = ["", title, "-" * width]
    head = "%-22s %5s %10s %9s %9s %9s" % (
        header, "件数", "imp/日", "クリック率", "外部率", "保存率")
    if extra_header is not None:
        head += "  %s" % extra_header
    lines.append(head)
    total_count = 0
    for key, b in buckets:
        imp = b["impression"]
        per_day = imp / b["days"] if b["days"] > 0 else 0.0
        click_rate = (b["pin_click"] / imp * 100) if imp > 0 else 0.0
        out_rate = (b["outbound_click"] / imp * 100) if imp > 0 else 0.0
        save_rate = (b["save"] / imp * 100) if imp > 0 else 0.0
        line = "%-22s %5d %10.2f %8.2f%% %8.2f%% %8.2f%%" % (
            key[:22], b["count"], per_day, click_rate, out_rate, save_rate)
        if extra_header is not None:
            line += "  %s" % (extra_values or {}).get(key, "")
        lines.append(line)
        total_count += b["count"]
    lines.append("-" * width)
    lines.append("対象件数合計: %d件" % total_count)
    return lines


def run_verify_saves(rows, access_token, now):
    """--verify-saves 用: インプレッション上位 VERIFY_SAVES_TOP_N 件について
    GET /v5/pins/{pin_id}/analytics を個別に呼び、lifetime_metrics（GET /v5/pins の
    pin_metrics）側のSAVEが実測（analytics）と一致するかを比較する。

    呼び出しはちょうど VERIFY_SAVES_TOP_N 件のみ（全件取得は行わない）。
    """
    scored = []
    for row in rows:
        found, _period = extract_pin_metrics(row["pin_metrics"])
        lifetime_impression = found.get("impression") if found else None
        lifetime_save = found.get("save") if found else None
        scored.append((row, lifetime_impression, lifetime_save))
    scored = [s for s in scored if s[1] is not None]
    scored.sort(key=lambda s: -s[1])
    top = scored[:VERIFY_SAVES_TOP_N]

    print("")
    print("=== --verify-saves: インプレッション上位%d件のSAVE実測比較（GET系のみ） ===" % VERIFY_SAVES_TOP_N)

    if not top:
        print("比較対象（lifetime_metricsにインプレッションがあるピン）が見つかりませんでした。")
        verdict = "SAVE_METRIC_UNRELIABLE（lifetime_metricsのSAVEは信頼できない）"
        print("")
        print(verdict)
        return verdict

    table_rows = []
    for i, (row, lifetime_impression, lifetime_save) in enumerate(top):
        if i > 0:
            time.sleep(VERIFY_SAVES_INTERVAL_SECONDS)
        created = datetime.datetime.fromisoformat(row["created_at"]).replace(
            tzinfo=datetime.timezone.utc)
        found, reason = fetch_analytics(row["pin_id"], access_token, created, now)
        if found is None:
            print("  【警告】pin%d の analytics 取得に失敗: %s" % (row["pin_num"], reason))
            analytics_impression = None
            analytics_save = None
        else:
            analytics_impression = found["impression"]
            analytics_save = found["save"]
        table_rows.append({
            "pin_num": row["pin_num"],
            "pin_id": row["pin_id"],
            "lifetime_impression": lifetime_impression,
            "analytics_impression": analytics_impression,
            "lifetime_save": lifetime_save,
            "analytics_save": analytics_save,
        })

    def fmt(v):
        return "-" if v is None else str(int(v))

    print("")
    print("%-10s %-22s %10s %10s %8s %8s" % (
        "pin番号", "pin_id", "lt_imp", "an_imp", "lt_save", "an_save"))
    print("-" * 74)
    for t in table_rows:
        print("%-10s %-22s %10s %10s %8s %8s" % (
            "pin%d" % t["pin_num"], t["pin_id"],
            fmt(t["lifetime_impression"]), fmt(t["analytics_impression"]),
            fmt(t["lifetime_save"]), fmt(t["analytics_save"])))

    # --- 判定（機械的・表示のみ・終了コードには反映しない） ---
    valid = [t for t in table_rows if t["analytics_impression"] is not None]

    def impression_close(t):
        lt, an = t["lifetime_impression"], t["analytics_impression"]
        if lt is None or an is None:
            return False
        if lt == 0:
            return an == 0
        return abs(lt - an) / lt <= VERIFY_SAVES_IMPRESSION_TOLERANCE

    any_analytics_save_nonzero = any((t["analytics_save"] or 0) > 0 for t in valid)
    all_impressions_match = bool(valid) and all(impression_close(t) for t in valid)

    if valid and not any_analytics_save_nonzero and all_impressions_match:
        verdict = "SAVE_CONFIRMED_ZERO（保存は実際に発生していない）"
    else:
        verdict = "SAVE_METRIC_UNRELIABLE（lifetime_metricsのSAVEは信頼できない）"

    print("")
    print(verdict)
    return verdict


NOTICE = (
    "型別の差はスロット位置・ボードと交絡している可能性がある。表1だけで判断せず表2・表3と併読すること。\n"
    "保存数が全体で少ない場合、保存率の型別比較は判断材料にならない。"
)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    verify_saves = VERIFY_SAVES_FLAG in sys.argv[1:]

    try:
        access_token = require_env("PINTEREST_ACCESS_TOKEN")
    except EnvLoaderError as e:
        print("エラー: アクセストークンを読み込めませんでした: %s" % e)
        sys.exit(1)

    now = datetime.datetime.now(datetime.timezone.utc)
    local_by_num, local_by_slug = build_local_index()
    board_names = load_board_names()

    print("=== Pin 型×成果 集計（読み取り専用・GET系のみ） ===")
    print("上限設定: MAX_PINS=%d / WINDOW_DAYS=%d" % (MAX_PINS, WINDOW_DAYS))

    # --- 1. GET /v5/pins 全件取得 ---
    try:
        all_pins = pinterest_api.fetch_all_pages(
            "/pins?pin_metrics=true", access_token, timeout=API_TIMEOUT_SECONDS)
    except pinterest_api.PinterestApiError as e:
        print("エラー: GET /v5/pins がHTTP %s を返しました: %s" % (e.status_code, e.body))
        sys.exit(1)
    except urllib.error.URLError as e:
        print("エラー: GET /v5/pins への通信に失敗しました: %s" % e)
        sys.exit(1)

    cutoff = now - datetime.timedelta(days=WINDOW_DAYS)
    in_window = []
    no_created_at = 0
    for pin in all_pins:
        created = parse_created_at(pin.get("created_at"))
        if created is None:
            no_created_at += 1
            continue
        if created >= cutoff:
            pin["_created"] = created
            in_window.append(pin)

    print("APIから取得: %d件 / うち直近%d日以内: %d件" % (len(all_pins), WINDOW_DAYS, len(in_window)))
    if no_created_at:
        print("【注意】created_at を解釈できなかったピン: %d件（対象外）" % no_created_at)

    if len(in_window) > MAX_PINS:
        print("")
        print("対象が上限 MAX_PINS=%d を超えました（%d件）。集計は行いません。"
              % (MAX_PINS, len(in_window)))
        print("上限を変えるにはスクリプト冒頭の MAX_PINS / WINDOW_DAYS を調整してください。")
        sys.exit(0)

    # --- 2. Pin番号・slug の特定 ---
    resolved = []
    unresolved = []
    route1 = 0
    route2 = 0

    # 第1経路で決まらなかったものを slug ごとにまとめ、created_at 昇順で slot を振る
    pending = []
    for pin in in_window:
        link = pin.get("link") or ""
        pin_num = pin_num_from_url(link)
        slug = slug_from_url(link)
        if pin_num is not None and slug:
            resolved.append({"pin": pin, "pin_num": pin_num, "slug": slug, "route": "UTM"})
            route1 += 1
        else:
            pending.append({"pin": pin, "slug": slug, "link": link})

    pending_by_slug = {}
    for item in pending:
        if item["slug"]:
            pending_by_slug.setdefault(item["slug"], []).append(item)
        else:
            unresolved.append((item["link"], "URLからslugを取り出せませんでした"))

    # 第1経路で既にPin番号が確定した分は、第2経路の割当候補から除く
    # （同一slug内でUTM有り・無しが混在した場合に同じPin番号を二重に割り当てないため）。
    claimed_by_slug = {}
    for item in resolved:
        claimed_by_slug.setdefault(item["slug"], set()).add(item["pin_num"])

    for slug, items in pending_by_slug.items():
        items.sort(key=lambda x: x["pin"]["_created"])
        claimed = claimed_by_slug.get(slug, set())
        local_infos = [i for i in sorted(local_by_slug.get(slug, []),
                                         key=lambda x: x["pin_num"])
                       if i["pin_num"] not in claimed]
        for idx, item in enumerate(items, start=1):
            if idx <= len(local_infos):
                resolved.append({
                    "pin": item["pin"],
                    "pin_num": local_infos[idx - 1]["pin_num"],
                    "slug": slug,
                    "route": "作成順",
                })
                route2 += 1
            else:
                unresolved.append((
                    item["link"],
                    "slug「%s」の未割当ローカルピンファイルが%d件しかなく%d枚目に対応するPin番号がありません"
                    % (slug, len(local_infos), idx)))

    print("特定経路の内訳: UTM経路 %d件 / 作成順経路 %d件 / 特定不能 %d件"
          % (route1, route2, len(unresolved)))

    # 同じPin番号に2件以上のピンが割り当たっていないかを検査する（沈黙させない）
    seen_nums = {}
    for item in resolved:
        seen_nums.setdefault(item["pin_num"], []).append(item)
    duplicates = {n: v for n, v in seen_nums.items() if len(v) > 1}
    if duplicates:
        print("【警告】同一Pin番号に複数のピンが割り当たりました（集計が二重計上になります）:")
        for pin_num in sorted(duplicates):
            print("  pin%d: %d件（%s）"
                  % (pin_num, len(duplicates[pin_num]),
                     ", ".join(d["route"] for d in duplicates[pin_num])))

    # --- 3. 型を引く（型が無いピン＝型導入前は集計対象外） ---
    rows = []
    no_style = 0
    normalized_styles = {}
    for item in resolved:
        info = local_by_num.get(item["pin_num"])
        if info is None or not info.get("style"):
            no_style += 1
            continue
        if info.get("style_normalized"):
            normalized_styles[info["style_raw"]] = info["style"]
        pin = item["pin"]
        created = pin["_created"]
        elapsed = max(1.0, (now - created).total_seconds() / 86400.0)
        rows.append({
            "pin_num": item["pin_num"],
            "slug": item["slug"],
            "slot": "pin%d" % info["slot"] if info.get("slot") else "不明",
            "style": info["style"],
            "article_seq": info.get("article_seq"),
            "text_count": info.get("text_count"),
            "text_count_bucket": text_count_bucket(info.get("text_count")),
            "cta_bucket": cta_bucket(info.get("cta_found"), created.date()),
            "board": board_names.get(str(pin.get("board_id", "")), str(pin.get("board_id", ""))),
            "created_at": created.date().isoformat(),
            "elapsed_days": elapsed,
            "route": item["route"],
            "pin_id": pin.get("id", ""),
            "pin_metrics": pin.get("pin_metrics"),
        })

    print("型が記録されているピン: %d件 / 型なし（型導入前等・対象外）: %d件" % (len(rows), no_style))

    # ローカルに型があるのにAPI側に見つからなかったピンを明示する
    # （Pinterest側で削除された等。黙って件数が減ると集計の母数を誤解するため）。
    api_nums = set(item["pin_num"] for item in resolved)
    local_styled = set(n for n, i in local_by_num.items() if i.get("style"))
    missing_from_api = sorted(local_styled - api_nums)
    if missing_from_api:
        print("【注意】型がローカルに記録されているがAPIの取得結果に見つからなかったピン %d件: %s"
              % (len(missing_from_api),
                 ", ".join("pin%d" % n for n in missing_from_api)))
        print("       （Pinterest側で削除された可能性がある。集計の母数から外れている）")

    if normalized_styles:
        print("型の表記ゆれを正規化した対応: %s"
              % ", ".join("%s→%s" % (k, v) for k, v in sorted(normalized_styles.items())))

    if not rows:
        print("集計対象が0件のため終了します。")
        sys.exit(0)

    # --- 4. 指標の取得 ---
    metrics_ok = 0
    periods = set()
    for row in rows:
        found, period = extract_pin_metrics(row["pin_metrics"])
        if found and len(found) == len(METRIC_KEYS):
            for metric, _ in METRIC_KEYS:
                row[metric] = found[metric]
            metrics_ok += 1
            periods.add(period)

    if metrics_ok == len(rows):
        source = "GET /v5/pins の pin_metrics（期間: %s）" % ", ".join(sorted(periods))
        print("")
        print("■ 指標の取得経路: %s" % source)
        print("  4指標すべてが pin_metrics に揃っていたため analytics の個別呼び出しは行っていません。")
    else:
        source = "GET /v5/pins/{pin_id}/analytics（個別呼び出し）"
        print("")
        print("■ 指標の取得経路: %s" % source)
        print("  pin_metrics に4指標が揃っていたのは %d/%d件のみだったため、"
              "%d件について analytics を個別に呼びます（間隔%.1f秒）。"
              % (metrics_ok, len(rows), len(rows), ANALYTICS_INTERVAL_SECONDS))
        failures = []
        for i, row in enumerate(rows):
            if i > 0:
                time.sleep(ANALYTICS_INTERVAL_SECONDS)
            created = datetime.datetime.fromisoformat(row["created_at"]).replace(
                tzinfo=datetime.timezone.utc)
            found, reason = fetch_analytics(row["pin_id"], access_token, created, now)
            if found is None:
                failures.append((row["pin_num"], reason))
                for metric, _ in METRIC_KEYS:
                    row[metric] = 0
            else:
                for metric, _ in METRIC_KEYS:
                    row[metric] = found[metric]
        if failures:
            print("  【警告】analytics取得に失敗したピン %d件（指標0として集計）:" % len(failures))
            for pin_num, reason in failures:
                print("    pin%d: %s" % (pin_num, reason))

    # --- 5. TSV出力 ---
    header = ["pin_id", "pin番号", "slug", "スロット", "型", "文言件数", "CTA", "ボード名",
              "created_at", "経過日数", "インプレッション", "ピンクリック",
              "アウトバウンドクリック", "保存", "特定経路"]
    rows.sort(key=lambda r: r["pin_num"])
    with open(OUTPUT_TSV, "w", encoding="utf-8", newline="") as f:
        f.write("\t".join(header) + "\n")
        for row in rows:
            f.write("\t".join([
                str(row["pin_id"]), str(row["pin_num"]), row["slug"], row["slot"],
                row["style"],
                TEXT_COUNT_UNKNOWN if row["text_count"] is None else str(row["text_count"]),
                row["cta_bucket"],
                row["board"],
                row["created_at"], "%.1f" % row["elapsed_days"],
                str(int(row["impression"])), str(int(row["pin_click"])),
                str(int(row["outbound_click"])), str(int(row["save"])), row["route"],
            ]) + "\n")
    print("")
    print("出力: %s（%d行）" % (os.path.relpath(OUTPUT_TSV, ROOT).replace(os.sep, "/"), len(rows)))

    # --- 6. 5つの集計表 ---
    out = []
    out += format_table("【表1】型別", "型", aggregate(rows, lambda r: r["style"]))
    out += format_table("【表2】スロット別", "スロット", aggregate(rows, lambda r: r["slot"]))
    out += format_table("【表3】ボード別", "ボード名", aggregate(rows, lambda r: r["board"]))
    # 「不明」行は集計から除外せず必ず出す（何件を見て判断したのかを後から追えるようにするため・D-0152）
    out += format_table("【表4】文言件数別（1〜2件／3件以上）", "文言件数",
                        aggregate(rows, lambda r: r["text_count_bucket"]))
    out.append(TEXT_COUNT_NOTICE)
    # 表5はD-0152の4群（情報量×CTA）の比較用。群分けは記事連番基準（D-0158）。
    # ここも「不明」行を必ず出す。
    out += format_table("【表5】4群別（情報量×CTA・記事連番基準）", "条件の群",
                        aggregate(rows, condition_group),
                        extra_header=DEVIATION_HEADER,
                        extra_values=deviation_summary(rows))
    out.append(GROUP_NOTICE)
    out.append(CTA_NOTICE)
    out.append(LEGACY_PIN_NOTICE)
    print("\n".join(out))

    # --- 7. 固定の注意書き ---
    print("")
    print("【読み方の注意】")
    print(NOTICE)

    if unresolved:
        print("")
        print("【特定不能だったピン（%d件）】" % len(unresolved))
        for link, reason in unresolved:
            print("  %s : %s" % (link, reason))

    # --- 8. --verify-saves（付けた場合のみ・既存挙動には影響しない） ---
    if verify_saves:
        run_verify_saves(rows, access_token, now)


if __name__ == "__main__":
    main()
