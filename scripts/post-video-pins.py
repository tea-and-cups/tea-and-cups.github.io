# -*- coding: utf-8 -*-
r"""動画ピンを Pinterest へ投稿するスクリプト（動画ピンの第1段・投稿先は Pinterest のみ）。

動画md（output/videos/<slug>/video-<N>.md）を読み、quality-reviewer の公開可（sha256 付きの審査行）が
ある動画だけを投稿する。Buffer（X・Threads）へは post-video-to-buffer.py が送る（D-0298）。台帳は data/video-posted.md（画像ピンの
data/pin-posted.md とは別。動画の番号 N は画像ピンの連番に入らない）。

処理順序（1動画ずつ・最初に止まった項目でその動画を止める）:
  (1) 緊急停止スイッチ（data/ 直下の pin-auto-post-off*・画像ピンと共用）。あれば何もせず終了する。
  (2) 動画md を読む（動画ファイル・誘導先URL・ボード・ai_disclosures（任意）・カバー・タイトル・説明文・代替テキスト）。
      誘導先URLの utm_content が video<N> であること、文字数（タイトル100・説明文800・代替テキスト500・
      URL2048）を確かめる。
  (3) 保留・見送り（check_hold・D-0308）: 動画md に「- 保留:」の行がある、または制作側の output/videos/video-N/video-N.build.json の
      mode が test（投稿しないテスト）・dropped（見送り）なら止める。引数なしの一括でも1本ずつここで止まる。
      審査行「- 審査: 公開可 YYYY-MM-DD sha256:<64桁>」が無ければ止める（判定は pin_review.REVIEW_LINE_RE）。
      審査行の sha256 と現物の sha256 が違えば止める（審査後の差し替えを投稿しない）。
      動画 QA_GATE_START（2）以降は、続けて機械QA を見る（check_qa・D-0302）: 「- 機械QA: <qa.json>」行の
      qa.json（制作側 output/videos/video-N/video-N.qa.json）が在り、gate が全項目合格（passed があればそれも）で、
      mp4_sha256 が投稿する mp4 の現物と一致しなければ止める。post-video-to-buffer.py もこの check_review を通る。
      動画 TEXT_OVERLAP_START（3）以降は、続けて投稿文の重なりを見る（check_text_overlap・D-0306）: タイトル・説明文・X用説明文・
      Threads用文が、同じ slug の画像ピン（output/pins/）の投稿文と連続 TEXT_OVERLAP_MAX_RUN 字を超えて同じなら止める。
  (4) ffprobe で動画の要件（mp4/mov/m4v・H.264/H.265・4秒以上15分以下・2GB以下・縦横比 1:2〜1.91:1）を確かめる。
  (5) ボードを data/pinterest-boards.md で引き、通年のボードであることを確かめる。
  (6) 重複の照合（3重）: 台帳に同じ N がある／台帳に同じ sha256 がある／GET /v5/pins に
      link の utm_content=video<N> のピンがある、のどれかで止める。
  (6-2) 1日の上限（D-0302）: 当日すでに投稿した件数（画像ピン＋動画ピン・post-pins-to-pinterest.py の
      count_today_posted）＋1 が MAX_BATCH_SIZE（50）を超えるなら投稿しない（保留。失敗には数えない）。
      台帳の照合のあと、GET /v5/pins の照合の前に見る。
  (7) 誘導先URLの200を確かめる（post-pins-to-pinterest.py の check_url_ok）。
  -- --dry-run はここまで（登録・アップロード・作成・台帳への書き込みをしない）--
  (8) POST /v5/media で登録し、media_id を台帳の # 行へ書く。
      前回の # 行に media_id があり、GET /v5/media/<id> が succeeded なら (8)(9) を飛ばす。
  (9) upload_to_presigned_post で署名付きの送信先へ上げる（トークンなし）。
  (10) GET /v5/media/<id> を10秒間隔で確かめ、succeeded を待つ（上限15分）。failed なら止める。
      上限を超えたら media_id を # 行に残して「未完了」で止める（次回は (8) の再開から）。
  (11) POST /v5/pins（media_source は video_id・cover_image_key_frame_time）。
  (12) 成功の直後に台帳へ1行書く: 動画N | slug | 作成済み | 公開可 日付 | 作成日 | sha256 | pin_id
  (13) 結果を出す。

失敗時:
  - 401・403 を受けたら、その実行の以降の呼び出しをすべて止める。
  - POST /v5/pins が4xxなら台帳に書かず止める（HTTPステータスと本文をそのまま出す）。
  - POST /v5/pins が成否不明（通信失敗・タイムアウト・5xx）なら、その場で GET /v5/pins を照合し、
    見つかれば台帳に書いて終える。見つからなければ止める（再試行はしない）。再実行しても (6) の
    GET /v5/pins 照合から始まるため、同じ動画を二重に作らない。

使い方:
  python site/scripts/post-video-pins.py --dry-run
  python site/scripts/post-video-pins.py
  python site/scripts/post-video-pins.py --dry-run --md <動画mdのパス> [--ledger <台帳のパス>]
    （--md/--ledger は検証用。--md を付けると、その1本だけを対象にする）

終了コード: 止まった動画が無ければ0、1本でも止まれば1（停止スイッチでの終了は0）。
"""

import datetime
import difflib
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
VIDEOS_DIR = os.path.join(ROOT, "output", "videos")
LEDGER_PATH = os.path.join(ROOT, "data", "video-posted.md")
PINS_DIR = os.path.join(ROOT, "output", "pins")

if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from env_loader import require_env  # noqa: E402
import pin_review  # noqa: E402
import pinterest_api  # noqa: E402

VIDEO_MD_RE = re.compile(r"^video-(\d+)\.md$")
VIDEO_FILE_RE = re.compile(r"^-\s*動画ファイル:\s*(.+)$")
AI_DISCLOSURES_RE = re.compile(r"^-\s*ai_disclosures:\s*(.+)$")
COVER_RE = re.compile(r"^-\s*cover_image_key_frame_time:\s*(.+)$")
ALT_RE = re.compile(r"^代替テキスト:\s*(.+)$")
DESC_HEAD_RE = re.compile(r"^説明文:\s*(.*)$")
REVIEW_SHA_RE = re.compile(r"^-\s*審査:\s*公開可\s+(\d{4}-\d{2}-\d{2})\s+sha256:([0-9a-f]{64})\s*$")
QA_LINE_RE = re.compile(r"^-\s*機械QA:\s*(.+)$")
HOLD_RE = re.compile(r"^-\s*保留:")   # 投稿しないテストの保留の行（make-video.py の HOLD_RE と同じ形・D-0308）
QA_GATE_START = 2   # 機械QA・X・Threads審査行の sha256 を必須にする最初の動画番号（動画1は対象外・D-0302）
TEXT_OVERLAP_START = 3     # 投稿文の重なりを見る最初の動画番号（動画1・2は対象外・D-0306）
TEXT_OVERLAP_MAX_RUN = 15  # 同じ記事の画像ピンと連続して共有してよい最大の字数（比較は句読点・記号・ハッシュタグ・URL を除く）。
#   動画2の最終版は最長 9字、直す前の文は 19字（reports/ の D-0306 の経緯）。話題の語（「勤労感謝の日の紅茶のプチギフト」15字）は共有してよい線
TEXT_PUNCT_RE = re.compile(r"[\s、。，．,.「」『』（）()・！？!?：:；;…～〜―｜|]")
X_TEXT_RE = re.compile(r"^-\s*X用説明文:\s*(.*)$")
THREADS_TEXT_RE = re.compile(r"^-\s*Threads用文:\s*(.*)$")
PIN_TEXT_RE = re.compile(r"^(?:-\s*)?(?:タイトル|説明文|X用説明文|Threads用問いかけ):\s*(.+)$")
LEDGER_N_RE = re.compile(r"^動画(\d+)$")
PROGRESS_RE = re.compile(r"^#\s*途中:\s*動画(\d+)\s+media=(\S+)\s+(\S+)\s+(\d{4}-\d{2}-\d{2})\s*$")

LEDGER_HEADER = (
    "# video-posted.md — Pinterest動画ピン台帳（post-video-pins.py が書く・手で編集しない）\n"
    "# 書式: 動画N | slug | 状態 | 審査 | 作成日 | sha256 | pin_id\n"
    "# 状態は「作成済み」だけ（pin_id が確定した行だけを書く）。日付は YYYY-MM-DD。\n"
    "# media_id などの途中経過は「# 途中: 動画N media=<id> <段階> <日付>」の形で、行頭 # の行にだけ書く。\n"
)

ALLOWED_AI_DISCLOSURES = ("AI_MODIFIED", "SYNTHETIC_PERFORMER")  # v5 の AiDisclosureItem の列挙
ALLOWED_EXTS = (".mp4", ".mov", ".m4v")
ALLOWED_CODECS = ("h264", "hevc")
MIN_SECONDS = 4
MAX_SECONDS = 15 * 60
MAX_BYTES = 2 * 1024 * 1024 * 1024
MIN_ASPECT = 1 / 2      # 幅/高さ（1:2 より細長くない）
MAX_ASPECT = 1.91       # 幅/高さ（1.91:1 より横長でない）
LIMITS = (("タイトル", "title", 100), ("説明文", "description", 800),
          ("代替テキスト", "alt_text", 500), ("誘導先URL", "guide_url", 2048))
POLL_INTERVAL_SECONDS = 10
POLL_LIMIT_SECONDS = 15 * 60
AUTH_STOP_STATUSES = (401, 403)


def _load_post_pins():
    """post-pins-to-pinterest.py の部品（停止スイッチ・ボード・URL確認・slug抽出・正規表現）を読み込む。"""
    path = os.path.join(SCRIPT_DIR, "post-pins-to-pinterest.py")
    spec = importlib.util.spec_from_file_location("post_pins_to_pinterest", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Stop(Exception):
    """その動画を止める（理由を持つ）。"""


class _AuthStop(Exception):
    """401・403 を受けた。その実行の以降の呼び出しをすべて止める合図。"""


# --- 動画md ---------------------------------------------------------------------

def find_video_mds():
    """output/videos/<slug>/video-<N>.md を (N, パス) の昇順で返す（_ で始まるフォルダは試作のため除く）。"""
    found = []
    if not os.path.isdir(VIDEOS_DIR):
        return found
    for slug in sorted(os.listdir(VIDEOS_DIR)):
        folder = os.path.join(VIDEOS_DIR, slug)
        if slug.startswith("_") or not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            m = VIDEO_MD_RE.match(name)
            if m:
                found.append((int(m.group(1)), os.path.join(folder, name)))
    return sorted(found)


def parse_video_md(path, pp):
    """動画mdを読む。戻り値: fields（dict）。必須項目が欠ければ _Stop。"""
    m = VIDEO_MD_RE.match(os.path.basename(path))
    if not m:
        raise _Stop("ファイル名が video-<N>.md ではありません: %s" % path)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    fields = {"n": int(m.group(1)), "md_path": path, "md_text": text, "ai_disclosures": None, "cover": None}
    desc_lines = None
    for raw in text.splitlines():
        line = raw.strip()
        if desc_lines is not None:
            if not line or line.startswith("#") or ALT_RE.match(line) or pp.TITLE_RE.match(line):
                fields["description"] = "\n".join(desc_lines)
                desc_lines = None
            else:
                desc_lines.append(line)
                continue
        for key, regex in (("video_rel", VIDEO_FILE_RE), ("guide_url", pp.GUIDE_URL_RE),
                           ("board", pp.BOARD_LINE_RE), ("ai_disclosures", AI_DISCLOSURES_RE),
                           ("cover", COVER_RE), ("title", pp.TITLE_RE), ("alt_text", ALT_RE)):
            mm = regex.match(line)
            if mm:
                fields[key] = mm.group(1).strip()
                break
        else:
            mm = DESC_HEAD_RE.match(line)
            if mm:
                desc_lines = [mm.group(1).strip()] if mm.group(1).strip() else []
    if desc_lines is not None:
        fields["description"] = "\n".join(desc_lines)

    missing = [label for label, key in (("動画ファイル", "video_rel"), ("誘導先URL", "guide_url"),
                                        ("ボード", "board"),
                                        ("cover_image_key_frame_time", "cover"), ("タイトル", "title"),
                                        ("説明文", "description"), ("代替テキスト", "alt_text"))
               if not fields.get(key)]
    if missing:
        raise _Stop("必須項目が欠落/空です: %s" % ", ".join(missing))
    fields["video_path"] = os.path.join(ROOT, fields["video_rel"].replace("/", os.sep))
    return fields


def utm_content(url):
    try:
        values = urllib.parse.parse_qs(urllib.parse.urlparse(url or "").query).get("utm_content", [])
    except ValueError:
        return None
    return values[0].strip().lower() if values else None


def check_fields(fields, pp):
    """N・slug・文字数・ai_disclosures・カバーを確かめる。戻り値: 結果の行のリスト。"""
    n = fields["n"]
    if utm_content(fields["guide_url"]) != "video%d" % n:
        raise _Stop("誘導先URLの utm_content が video%d ではありません: %s" % (n, fields["guide_url"]))
    slug = pp.extract_slug_from_guide_url(fields["guide_url"])
    if not slug:
        raise _Stop("誘導先URLから記事slugを取れません: %s" % fields["guide_url"])
    folder = os.path.basename(os.path.dirname(os.path.abspath(fields["md_path"])))
    if os.path.dirname(os.path.abspath(fields["md_path"])).startswith(VIDEOS_DIR + os.sep) and folder != slug:
        raise _Stop("動画mdのフォルダ名（%s）と誘導先URLのslug（%s）が違います" % (folder, slug))
    fields["slug"] = slug
    lengths = []
    for label, key, limit in LIMITS:
        size = len(fields[key])
        if size > limit:
            raise _Stop("%sが%d字で上限%d字を超えています" % (label, size, limit))
        lengths.append("%s%d/%d" % (label, size, limit))
    values = []
    if fields["ai_disclosures"] is not None:  # 任意項目（D-0297）。行が無ければ送らない
        values = [v.strip() for v in fields["ai_disclosures"].split(",") if v.strip()]
        bad = [v for v in values if v not in ALLOWED_AI_DISCLOSURES]
        if not values or bad:
            raise _Stop("ai_disclosures の値が不正です: %s（使える値: %s）"
                        % (fields["ai_disclosures"], ", ".join(ALLOWED_AI_DISCLOSURES)))
    fields["ai_values"] = values
    if not fields["cover"].isdigit():
        raise _Stop("cover_image_key_frame_time は0以上の整数で書きます: %s" % fields["cover"])
    fields["cover_time"] = int(fields["cover"])
    return ["動画番号・slug: 動画%d / %s（utm_content=video%d）" % (n, slug, n),
            "文字数: %s" % "・".join(lengths),
            "ai_disclosures: %s / cover_image_key_frame_time: %d"
            % (", ".join(values) if values else "なし（送らない）", fields["cover_time"])]


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def check_hold(fields):
    """投稿しないテストの保留と見送り（D-0308）: 動画md に保留の行がある、または制作側の build.json の mode が
    test（保留中のテスト）・dropped（見送り）なら止める。外すのは make-video.py release（保留の行と mode をそろえて外す）。"""
    held = [l.strip() for l in fields["md_text"].splitlines() if HOLD_RE.match(l.strip())]
    if held:
        raise _Stop("保留の行があります（%s）。投稿は Sho の一言のあと make-video.py release video-%d で外してから"
                    % (held[0], fields["n"]))
    path = os.path.join(VIDEOS_DIR, "video-%d" % fields["n"], "video-%d.build.json" % fields["n"])
    try:
        with open(path, encoding="utf-8") as f:
            mode = json.load(f).get("mode")
    except FileNotFoundError:
        return ["保留: なし（build.json なし）"]
    except (OSError, ValueError) as e:
        raise _Stop("制作側の build.json を読めません: %s（%s）" % (path, e))
    if mode == "test":
        raise _Stop("動画%d は保留中のテストです（video-%d.build.json の mode=test）。保留の行を手で消しても投稿しない。"
                    "make-video.py release video-%d で外してから" % (fields["n"], fields["n"], fields["n"]))
    if mode == "dropped":
        raise _Stop("動画%d は見送りです（video-%d.build.json の mode=dropped）" % (fields["n"], fields["n"]))
    return ["保留: なし（mode=%s）" % (mode or "本番")]


def check_review(fields):
    """保留・見送りと、審査行と sha256 を確かめる。"""
    hold = check_hold(fields)
    if not os.path.isfile(fields["video_path"]):
        raise _Stop("動画ファイルが見つかりません: %s" % fields["video_rel"])
    if not pin_review.REVIEW_LINE_RE.search(fields["md_text"]):
        raise _Stop("審査行（- 審査: 公開可 YYYY-MM-DD sha256:…）がありません（未審査のため投稿しない）")
    reviews = [REVIEW_SHA_RE.match(l.strip()) for l in fields["md_text"].splitlines()
               if pin_review.REVIEW_LINE_RE.match(l.strip())]
    last = reviews[-1]
    if not last:
        raise _Stop("最後の審査行に sha256:<64桁> がありません")
    actual = file_sha256(fields["video_path"])
    if last.group(2) != actual:
        raise _Stop("sha256 が一致しません（審査行 %s / 現物 %s）。審査後に動画が変わっています"
                    % (last.group(2), actual))
    fields["review_date"] = last.group(1)
    fields["sha256"] = actual
    lines = hold + ["審査行: 公開可 %s" % last.group(1), "sha256: 審査行と現物が一致（%s）" % actual]
    if fields["n"] >= QA_GATE_START:
        lines += check_qa(fields)
    if fields["n"] >= TEXT_OVERLAP_START:
        lines += check_text_overlap(fields)
    return lines


def _plain(text):
    """重なりの比較用: ハッシュタグ・URL・空白・句読点と記号を除く。"""
    return TEXT_PUNCT_RE.sub("", re.sub(r"#\S+|https?://\S+", "", text))


def longest_common_run(a, b):
    """連続して同じ文字列の最長。戻り値: (長さ, その文字列)。"""
    m = difflib.SequenceMatcher(None, a, b, autojunk=False).find_longest_match(0, len(a), 0, len(b))
    return m.size, a[m.a:m.a + m.size]


def video_post_texts(fields):
    """動画md の投稿文。戻り値: [(項目名, 本文)]（タイトル・説明文・X用説明文・Threads用文）。"""
    texts = [("タイトル", fields["title"]), ("説明文", fields["description"])]
    for label, regex in (("X用説明文", X_TEXT_RE), ("Threads用文", THREADS_TEXT_RE)):
        for raw in fields["md_text"].splitlines():
            m = regex.match(raw.strip())
            if m and m.group(1).strip():
                texts.append((label, m.group(1).strip()))
    return texts


def pin_post_texts(slug, pins_dir):
    """同じ slug の画像ピン（output/pins/*-pin-<番号>-<slug>-<連番>.md）の投稿文。戻り値: {ファイル名: [本文…]}。"""
    out = {}
    if not os.path.isdir(pins_dir):
        return out
    name_re = re.compile(r"-pin-\d+-%s-\d+\.md$" % re.escape(slug))
    for name in sorted(os.listdir(pins_dir)):
        if not name_re.search(name):
            continue
        with open(os.path.join(pins_dir, name), encoding="utf-8") as f:
            out[name] = [m.group(1).strip() for m in (PIN_TEXT_RE.match(l.strip()) for l in f.read().splitlines()) if m]
    return out


def check_text_overlap(fields, pins_dir=None):
    """投稿文の重なり: 動画の投稿文が同じ slug の画像ピンの投稿文と、連続した同じ文字列を TEXT_OVERLAP_MAX_RUN 字を超えて
    共有していたら止める（動画 TEXT_OVERLAP_START 以降・D-0306）。同じ記事の別の入口に同じ言い回しを出さないため。
    戻り値: 結果の行のリスト。"""
    slug = fields.get("slug") or os.path.basename(os.path.dirname(os.path.abspath(fields["md_path"])))
    pins = pin_post_texts(slug, pins_dir or PINS_DIR)
    worst = (0, "", "", "")
    for label, text in video_post_texts(fields):
        a = _plain(text)
        for name, bodies in pins.items():
            size, run = longest_common_run(a, _plain("".join(bodies)))
            if size > worst[0]:
                worst = (size, run, label, name)
    if worst[0] > TEXT_OVERLAP_MAX_RUN:
        raise _Stop("投稿文が同じ記事の画像ピンと言い回しを共有しています（動画の%s と %s が連続 %d字・上限 %d字）: 「%s」"
                    "（言い回しを変えてから審査に出し直す）" % (worst[2], worst[3], worst[0], TEXT_OVERLAP_MAX_RUN, worst[1]))
    return ["投稿文の重なり: 同じ記事の画像ピン %d件との最長の共通 %d字（上限 %d字）" % (len(pins), worst[0], TEXT_OVERLAP_MAX_RUN)]


def check_qa(fields):
    """機械QA（D-0302・動画 QA_GATE_START 以降）: 「- 機械QA:」行の qa.json が在り、gate が全項目合格
    （passed があればそれも合格）で、qa.json の mp4_sha256 が投稿する mp4 の現物と一致すること。"""
    found = [m.group(1).strip() for m in (QA_LINE_RE.match(l.strip()) for l in fields["md_text"].splitlines()) if m]
    if len(found) != 1 or not found[0].endswith(".qa.json") or " " in found[0] or "・" in found[0]:
        raise _Stop("「- 機械QA: output/videos/video-N/video-N.qa.json」行がちょうど1行・qa.json 1つだけの形で"
                    "ありません（%s）" % ("、".join(found) or "行なし"))
    rel = found[0]
    path = os.path.join(ROOT, rel.replace("/", os.sep))
    if not os.path.isfile(path):
        raise _Stop("機械QA の qa.json がありません: %s（機械QA を通っていないため投稿しない）" % rel)
    try:
        with open(path, encoding="utf-8") as f:
            qa = json.load(f)
    except (OSError, ValueError) as e:
        raise _Stop("機械QA の qa.json を読めません: %s（%s）" % (rel, e))
    gate = qa.get("gate") if isinstance(qa, dict) else None
    if not isinstance(gate, dict) or not gate:
        raise _Stop("機械QA の qa.json に gate がありません: %s" % rel)
    bad = [k for k, v in gate.items() if v is not True]
    if bad:
        raise _Stop("機械QA の gate に不合格の項目があります: %s（%s）" % ("、".join(bad), rel))
    if "passed" in qa and qa["passed"] is not True:
        raise _Stop("機械QA の passed が合格ではありません（%s: %r）" % (rel, qa["passed"]))
    if qa.get("mp4_sha256") != fields["sha256"]:
        raise _Stop("機械QA の mp4_sha256 が現物と一致しません（qa.json %s / 現物 %s）。機械QA のあとに動画が変わっています"
                    % (qa.get("mp4_sha256"), fields["sha256"]))
    return ["機械QA: gate %d項目すべて合格・mp4_sha256 が現物と一致（%s）" % (len(gate), rel)]


def check_daily_limit(fields, pp, ledger_path, today_str):
    """1日の上限（D-0302）: 当日すでに Pinterest へ投稿した件数（画像ピン＋動画ピン・pp.count_today_posted）＋
    この1本が pp.MAX_BATCH_SIZE を超えるなら投稿しない。戻り値: (上限内か, 結果の行)。"""
    today_count = pp.count_today_posted(today_str, video_path=ledger_path)
    line = "1日の上限: 本日すでに投稿 %d件（画像ピン＋動画ピン）＋ この動画 1件 / 上限 %d件" % (
        today_count, pp.MAX_BATCH_SIZE)
    return today_count + 1 <= pp.MAX_BATCH_SIZE, line


def probe_video(fields):
    """ffprobe で動画の要件を確かめる。"""
    path = fields["video_path"]
    ext = os.path.splitext(path)[1].lower()
    if ext not in ALLOWED_EXTS:
        raise _Stop("拡張子 %s は対象外です（%s）" % (ext, "・".join(ALLOWED_EXTS)))
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                              "-show_entries", "stream=codec_name,width,height:format=duration,size",
                              "-of", "json", path], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise _Stop("ffprobe を実行できません: %s" % e)
    if out.returncode != 0:
        raise _Stop("ffprobe が失敗しました: %s" % out.stderr.strip())
    info = json.loads(out.stdout or "{}")
    streams = info.get("streams") or []
    if not streams:
        raise _Stop("映像のストリームがありません")
    codec = streams[0].get("codec_name", "")
    width, height = int(streams[0].get("width") or 0), int(streams[0].get("height") or 0)
    duration = float((info.get("format") or {}).get("duration") or 0)
    size = os.path.getsize(path)
    problems = []
    if codec not in ALLOWED_CODECS:
        problems.append("コーデック %s" % codec)
    if not (MIN_SECONDS <= duration <= MAX_SECONDS):
        problems.append("長さ %.2f秒" % duration)
    if size > MAX_BYTES:
        problems.append("サイズ %dバイト" % size)
    aspect = width / height if height else 0
    if not (MIN_ASPECT <= aspect <= MAX_ASPECT):
        problems.append("縦横比 %dx%d" % (width, height))
    if problems:
        raise _Stop("動画の要件を満たしません: %s" % "、".join(problems))
    return ["動画の要件: %s / %s / %dx%d / %.2f秒 / %.1fMB" % (ext, codec, width, height, duration, size / 1e6)]


def check_board(fields, pp, board_id_map):
    board_id, season, reason = pp.resolve_board_id(fields["board"], board_id_map)
    if board_id is None:
        raise _Stop(reason)
    if season != "通年":
        raise _Stop("ボード「%s」は季節ボードです（動画は通年の主題ボードに置く）" % fields["board"])
    fields["board_id"] = board_id
    return ["ボード: %s（board_id=%s・通年）" % (fields["board"], board_id)]


# --- 台帳 -----------------------------------------------------------------------

def load_ledger(path):
    """台帳を読む。戻り値: {"rows": {N: {"slug":…, "created":…, "sha256":…, "pin_id":…}}, "progress": {N: [(media_id, 段階, 日付)]}}"""
    rows, progress = {}, {}
    if not os.path.isfile(path):
        return {"rows": rows, "progress": progress}
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#"):
                m = PROGRESS_RE.match(line)
                if m:
                    progress.setdefault(int(m.group(1)), []).append((m.group(2), m.group(3), m.group(4)))
                continue
            cells = [c.strip() for c in line.split("|")]
            m = LEDGER_N_RE.match(cells[0]) if cells else None
            if not m:
                continue
            rows[int(m.group(1))] = {"slug": cells[1] if len(cells) > 1 else "",
                                     "created": cells[4] if len(cells) > 4 else "",
                                     "sha256": cells[5] if len(cells) > 5 else "",
                                     "pin_id": cells[6] if len(cells) > 6 else ""}
    return {"rows": rows, "progress": progress}


def check_ledger(fields, ledger):
    n = fields["n"]
    if n in ledger["rows"]:
        row = ledger["rows"][n]
        raise _Stop("台帳に同じ番号 動画%d があります（slug=%s・pin_id=%s）" % (n, row["slug"], row["pin_id"]))
    for other, row in ledger["rows"].items():
        if row["sha256"] == fields["sha256"]:
            raise _Stop("台帳に同じ sha256 の動画があります（動画%d・pin_id=%s）" % (other, row["pin_id"]))
    return ["台帳: 同じ番号・同じ sha256 なし（作成済み%d件）" % len(ledger["rows"])]


def _ensure_ledger(path):
    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(LEDGER_HEADER)


def append_progress(path, n, media_id, stage, today_str):
    _ensure_ledger(path)
    with open(path, "a", encoding="utf-8") as f:
        f.write("# 途中: 動画%d media=%s %s %s\n" % (n, media_id, stage, today_str))


def append_row(path, fields, today_str, pin_id):
    _ensure_ledger(path)
    with open(path, "a", encoding="utf-8") as f:
        f.write("動画%d | %s | 作成済み | 公開可 %s | %s | %s | %s\n"
                % (fields["n"], fields["slug"], fields["review_date"], today_str, fields["sha256"], pin_id))


# --- API ------------------------------------------------------------------------

def call(method, path, token, body=None):
    """pinterest_api.request の薄い包み。401・403 は _AuthStop にする。"""
    try:
        return pinterest_api.request(method, path, token, body=body, timeout=30)
    except pinterest_api.PinterestApiError as e:
        if e.status_code in AUTH_STOP_STATUSES:
            raise _AuthStop("%s %s → HTTP %s: %s" % (method, path, e.status_code, e.body))
        raise


def find_existing_pin(n, listing):
    for p in listing:
        if utm_content(p.get("link")) == "video%d" % n:
            return p.get("id")
    return None


def fetch_listing(token):
    try:
        return pinterest_api.fetch_all_pages("/pins", token)
    except pinterest_api.PinterestApiError as e:
        if e.status_code in AUTH_STOP_STATUSES:
            raise _AuthStop("GET /v5/pins → HTTP %s: %s" % (e.status_code, e.body))
        raise _Stop("GET /v5/pins の一覧を取得できません（HTTP %s: %s）" % (e.status_code, e.body))
    except Exception as e:
        raise _Stop("GET /v5/pins の一覧を取得できません（通信失敗: %s）" % e)


def media_status(token, media_id):
    data = call("GET", "/media/%s" % media_id, token)
    return (data or {}).get("status")


def prepare_media(fields, token, ledger_path, ledger, today_str, out):
    """(8)〜(10): media_id を用意し、処理が succeeded になるまで待つ。戻り値: media_id。"""
    n = fields["n"]
    for media_id, _stage, _date in reversed(ledger["progress"].get(n, [])):
        try:
            status = media_status(token, media_id)
        except pinterest_api.PinterestApiError as e:
            out.append("前回の media=%s を確かめられません（HTTP %s）。新しく登録します" % (media_id, e.status_code))
            break
        except (urllib.error.URLError, OSError) as e:
            raise _Stop("前回の media=%s の状態を確かめられません（通信失敗: %s）" % (media_id, e))
        if status == "succeeded":
            out.append("前回の media=%s が succeeded のため、登録とアップロードを飛ばします" % media_id)
            return media_id
        if status == "processing":
            out.append("前回の media=%s が処理中のため、続きを待ちます" % media_id)
            return wait_media(fields, token, ledger_path, media_id, today_str, out)
        out.append("前回の media=%s は %s のため使いません。新しく登録します" % (media_id, status))
        break

    try:
        reg = call("POST", "/media", token, body={"media_type": "video"})
    except pinterest_api.PinterestApiError as e:
        raise _Stop("POST /v5/media が失敗しました（HTTP %s: %s）" % (e.status_code, e.body))
    except Exception as e:
        raise _Stop("POST /v5/media が通信で失敗しました（%s）。登録の有無は GET /v5/media で確かめられます" % e)
    media_id = str(reg.get("media_id") or "")
    if not media_id or not reg.get("upload_url"):
        raise _Stop("POST /v5/media の応答に media_id か upload_url がありません: %s" % reg)
    append_progress(ledger_path, n, media_id, "registered", today_str)
    out.append("登録: media=%s" % media_id)

    try:
        status, _body = pinterest_api.upload_to_presigned_post(
            reg["upload_url"], reg.get("upload_parameters") or {}, fields["video_path"])
    except Exception as e:
        append_progress(ledger_path, n, media_id, "upload_failed", today_str)
        raise _Stop("アップロードが失敗しました（%s）。再実行すると登録からやり直します" % e)
    append_progress(ledger_path, n, media_id, "uploaded", today_str)
    out.append("アップロード: HTTP %s" % status)
    return wait_media(fields, token, ledger_path, media_id, today_str, out)


def wait_media(fields, token, ledger_path, media_id, today_str, out):
    deadline = time.time() + POLL_LIMIT_SECONDS
    status = None
    while True:
        try:
            status = media_status(token, media_id)
        except pinterest_api.PinterestApiError as e:
            status = "HTTP %s" % e.status_code
        except Exception as e:
            status = "通信失敗: %s" % e
        if status == "succeeded":
            append_progress(ledger_path, fields["n"], media_id, "succeeded", today_str)
            out.append("処理: succeeded（media=%s）" % media_id)
            return media_id
        if status == "failed":
            append_progress(ledger_path, fields["n"], media_id, "failed", today_str)
            raise _Stop("動画の処理が failed になりました（media=%s）" % media_id)
        if time.time() >= deadline:
            raise _Stop("未完了: %d分待っても処理が終わりません（最後の状態 %s・media=%s）。"
                        "再実行すると、この media の状態確認から再開します"
                        % (POLL_LIMIT_SECONDS // 60, status, media_id))
        time.sleep(POLL_INTERVAL_SECONDS)


def build_pin_body(fields, media_id):
    body = {
        "board_id": fields["board_id"],
        "title": fields["title"],
        "description": fields["description"],
        "link": fields["guide_url"],
        "alt_text": fields["alt_text"],
        "media_source": {"source_type": "video_id", "media_id": media_id,
                         "cover_image_key_frame_time": fields["cover_time"]},
    }
    if fields["ai_values"]:
        body["ai_disclosures"] = {"values": fields["ai_values"]}
    return body


def create_pin(fields, token, media_id):
    return call("POST", "/pins", token, body=build_pin_body(fields, media_id))


# --- 本体 -----------------------------------------------------------------------

def process(fields_path, pp, ctx, out):
    """1本を処理する。通った項目を out へ足していく。戻り値: 結果ラベル。止めるときは _Stop。"""
    fields = parse_video_md(fields_path, pp)
    out.append("動画md: %s" % fields_path)
    out += check_fields(fields, pp)
    out += check_review(fields)
    out += probe_video(fields)
    out += check_board(fields, pp, ctx["board_id_map"])
    out += check_ledger(fields, ctx["ledger"])
    ok, line = check_daily_limit(fields, pp, ctx["ledger_path"], ctx["today"])
    out.append(line)
    if not ok:
        out.append("上限を超えるため、この動画は投稿しません（画像ピンの上限超えと同じく失敗には数えない）")
        return "保留(1日の上限)"
    if ctx["listing"] is None:
        ctx["listing"] = fetch_listing(ctx["token"])
    dup = find_existing_pin(fields["n"], ctx["listing"])
    if dup:
        raise _Stop("GET /v5/pins に utm_content=video%d のピンがあります（pin_id=%s・台帳への記録漏れの可能性）"
                    % (fields["n"], dup))
    out.append("GET /v5/pins: utm_content=video%d のピンなし（%d件を照合）" % (fields["n"], len(ctx["listing"])))
    ok, detail = pp.check_url_ok(fields["guide_url"])
    if not ok:
        raise _Stop("誘導先URLが200を返しません（%s）" % detail)
    out.append("誘導先URL: %s" % detail)
    if ctx["dry_run"]:
        return "成功見込み(dry-run)"

    media_id = prepare_media(fields, ctx["token"], ctx["ledger_path"], ctx["ledger"], ctx["today"], out)
    try:
        resp = create_pin(fields, ctx["token"], media_id)
    except pinterest_api.PinterestApiError as e:
        if 400 <= e.status_code < 500:
            raise _Stop("POST /v5/pins が失敗しました（HTTP %s: %s）。台帳には書いていません" % (e.status_code, e.body))
        out.append("POST /v5/pins が HTTP %s（成否不明）: %s" % (e.status_code, e.body))
        resp = None
    except Exception as e:
        out.append("POST /v5/pins が通信で失敗（成否不明）: %s" % e)
        resp = None
    if resp is None:
        found = find_existing_pin(fields["n"], fetch_listing(ctx["token"]))
        if not found:
            raise _Stop("成否不明のまま止めます。GET /v5/pins に utm_content=video%d は見つかりません"
                        "（再実行すると照合から始まります）" % fields["n"])
        out.append("GET /v5/pins の照合で作成済みを確認: pin_id=%s" % found)
        resp = {"id": found}
    pin_id = str(resp.get("id") or "")
    append_row(ctx["ledger_path"], fields, ctx["today"], pin_id)
    out.append("台帳に記録: 動画%d pin_id=%s" % (fields["n"], pin_id))
    return "成功"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    argv = sys.argv[1:]
    dry_run = "--dry-run" in argv

    def opt(name):
        if name in argv:
            i = argv.index(name)
            if i + 1 < len(argv):
                return os.path.abspath(argv[i + 1])
            print("usage: post-video-pins.py [--dry-run] [--md <動画md>] [--ledger <台帳>]")
            sys.exit(1)
        return None

    md_path, ledger_path = opt("--md"), opt("--ledger") or LEDGER_PATH

    pp = _load_post_pins()
    kill = pp.check_kill_switch()
    if kill:
        print("自動投稿は停止中（data/%s を検知しました）" % kill)
        sys.exit(0)

    ledger = load_ledger(ledger_path)
    if md_path:
        targets = [md_path]
    else:
        targets = []
        for n, path in find_video_mds():
            if n in ledger["rows"]:
                print("動画%d / 投稿済み（台帳） / pin_id: %s" % (n, ledger["rows"][n]["pin_id"]))
            else:
                targets.append(path)
    if not targets:
        print("未投稿の動画はありません")
        sys.exit(0)

    ctx = {"dry_run": dry_run, "token": require_env("PINTEREST_ACCESS_TOKEN"),
           "board_id_map": pp.load_board_id_map(), "ledger": ledger, "ledger_path": ledger_path,
           "listing": None, "today": datetime.date.today().isoformat()}
    print("モード: %s / 台帳: %s" % ("dry-run（登録・アップロード・作成・台帳への書き込みをしない）" if dry_run else "投稿",
                                   ledger_path))
    stopped = 0
    for path in targets:
        lines = []
        try:
            label = process(path, pp, ctx, lines)
        except _AuthStop as e:
            for line in lines:
                print("  [OK] %s" % line)
            print("停止 / 401・403 を受けたため、以降の呼び出しをすべて止めます: %s" % e)
            sys.exit(1)
        except _Stop as e:
            stopped += 1
            label = "停止"
            lines.append(None)
            stop_reason = str(e)
        print("%s / %s" % (os.path.basename(path), label))
        for line in lines:
            print("  [NG] %s" % stop_reason if line is None else "  [OK] %s" % line)
    sys.exit(1 if stopped else 0)


if __name__ == "__main__":
    main()
