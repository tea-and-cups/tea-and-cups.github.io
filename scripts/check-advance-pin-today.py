# -*- coding: utf-8 -*-
r"""先行ピン（既存の seasons・gift 記事へ足す季節のピン・1件/日）を、その日に作るべきか・作り終えたかを判定する（D-0275）。

背景:
  日次ノルマは「新規記事のピン3枚＋先行ピン1件/日」（D-0256）だが、先行ピンを作るかどうかを
  AIの注意に任せていたため作られない日が続いた（GD-0035）。候補の有無と完了を機械で判定し、
  開始時の出力（session-start-check.py）と終了時の強制（stop-hook-check.py）の両方から使う。
  候補が無い日の免除も、このスクリプトが ADVANCE_PIN_NONE を出した場合だけとする。

入力:
  data/advance-pin-calendar.tsv  記事ごとの季節の山（slug / peaks / 根拠）。公開中の seasons・gift
                                 の記事を1行ずつ持つ。peaks は MM-DD のカンマ区切り、山が無ければ「-」。
  output/pins/*.md               「- 先行ピン作成日: YYYY-MM-DD」行のあるピンmd＝先行ピン。
                                 この行の定義と読み取りは pick-image-variation.py が正本。
  output/Pin-images/             先行ピンの画像（copy-pin-image.sh が配置・合成したもの）。
  data/pin-posted.md             Pinterestへ投稿済みのピン番号（post-pins-to-pinterest.py は
                                 終了コードで成否を区別しないため、投稿済みの判定はこの台帳だけで行う）。

判定（対象日ごとに次のどれか1行）:
  ADVANCE_PIN_DONE pin=<番号>            対象日の先行ピンがあり、画像が配置済み・--verify 相当に合格・
                                         data/pin-posted.md に記載あり。
  ADVANCE_PIN_INCOMPLETE pin=<番号> 理由 対象日の先行ピンのmdはあるが、上の3つのどれかが欠けている。
  ADVANCE_PIN_NEXT slug=<slug> peak=MM-DD 残りn日
                                         対象日の先行ピンが無く、候補がある。先頭の1件を示す。
  ADVANCE_PIN_NONE 理由                  対象日の先行ピンが無く、候補も無い（この日は作らなくてよい）。

候補:
  台帳に山があり、公開中で category が seasons か gift、公開日が対象日より前の記事のうち、
  対象日から次の山（今年の山が過ぎていれば翌年）までの日数が WINDOW_MIN_DAYS〜WINDOW_MAX_DAYS の
  もの。対象日の前 COOLDOWN_DAYS 日以内に先行ピンを作った記事は除く。
  並び順は、山が近い順 → 先行ピンが少ない順 → slug の昇順。

あわせて、公開中の seasons・gift の記事で台帳に行が無いものがあれば
ADVANCE_PIN_CALENDAR_MISSING を1行出す（山を決められず、候補から漏れるため）。

使い方:
  python site/scripts/check-advance-pin-today.py
      日本時間の今日を判定する。
  python site/scripts/check-advance-pin-today.py --date YYYY-MM-DD
      対象日を差し替える（検証用・週次監査用）。
  python site/scripts/check-advance-pin-today.py --since YYYY-MM-DD --until YYYY-MM-DD
      期間の各日を「日付 判定」で1行ずつ出し、最後に NEXT・INCOMPLETE の日数を1行出す。
  python site/scripts/check-advance-pin-today.py --verify [--date YYYY-MM-DD]
      対象日の先行ピンを検査する: 枝番を含む命名／誘導先が公開中の seasons・gift の既存記事／
      check-pin-image-style.py の先行ピンのモード／check-x-post-length.py。
  python site/scripts/check-advance-pin-today.py --require-row <slug>
      category が seasons・gift の記事で、台帳に行が無ければ終了コード1（publish-article.py の
      新規公開の公開前チェック。`<slug> --require-row` の順でも受け付ける）。

終了コード:
  判定（引数なし・--date・--since/--until）は常に0。--verify と --require-row は合格0・不合格1。
  引数の誤りは2。
"""

import contextlib
import datetime
import importlib.util
import io
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
CALENDAR_PATH = os.path.join(ROOT, "data", "advance-pin-calendar.tsv")
PINS_DIR = os.path.join(ROOT, "output", "pins")
PIN_IMAGES_DIR = os.path.join(ROOT, "output", "Pin-images")
POSTED_LEDGER_PATH = os.path.join(ROOT, "data", "pin-posted.md")
POSTS_DIR = os.path.join(ROOT, "site", "src", "content", "posts")
DRAFTS_DIR = os.path.join(ROOT, "output", "articles")

# 候補にする山までの日数（3〜約8.5週先）と、同じ記事へ続けて作らない日数。
WINDOW_MIN_DAYS = 21
WINDOW_MAX_DAYS = 60
COOLDOWN_DAYS = 14

TARGET_CATEGORIES = ("seasons", "gift")
NO_PEAK = "-"
RULE_SECTION = "rules/image-generation-flow.md 1-4節"

MARK_NEXT = "ADVANCE_PIN_NEXT"
MARK_INCOMPLETE = "ADVANCE_PIN_INCOMPLETE"
MARK_DONE = "ADVANCE_PIN_DONE"
MARK_NONE = "ADVANCE_PIN_NONE"
MARK_MISSING = "ADVANCE_PIN_CALENDAR_MISSING"
MARK_PERIOD = "ADVANCE_PIN_PERIOD"

PEAK_RE = re.compile(r"^(\d{2})-(\d{2})$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PIN_FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-pin-(\d+)-(.+)-(\d{2})\.md$")
UTM_PIN_RE = re.compile(r"utm_content=pin(\d+)\b")
FRONTMATTER_KEY_RE = re.compile(r"^(category|date|status):\s*(\S+)\s*$")
FRONTMATTER_HEAD_LINES = 30
PEAK_FALLBACK_YEAR = 2000  # 月日の妥当性を見るためのうるう年

_MODULES = {}


def _load(file_name):
    """site/scripts/ のスクリプトをモジュールとして読み込む（ハイフン入りの名前のため）。1プロセス1回。"""
    if file_name not in _MODULES:
        path = os.path.join(SCRIPT_DIR, file_name)
        spec = importlib.util.spec_from_file_location(file_name[:-3].replace("-", "_"), path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _MODULES[file_name] = module
    return _MODULES[file_name]


def piv():
    """先行ピンの行の定義・ピンmdの読み取りの正本（pick-image-variation.py）。"""
    return _load("pick-image-variation.py")


def style_checker():
    """check-pin-image-style.py。読み込み先のディレクトリをこのスクリプトの値にそろえて返す。"""
    module = _load("check-pin-image-style.py")
    module.PINS_DIR = PINS_DIR
    module.PIN_IMAGES_DIR = PIN_IMAGES_DIR
    return module


def x_checker():
    module = _load("check-x-post-length.py")
    module.PINS_DIR = PINS_DIR
    return module


def naming_checker():
    return _load("check-pin-image-naming.py")


def posted_pins():
    """data/pin-posted.md の投稿済みピン番号の集合（読み取りは check-pin-posting-status.py が正本）。"""
    module = _load("check-pin-posting-status.py")
    original = module.LEDGER_PATH
    module.LEDGER_PATH = POSTED_LEDGER_PATH
    try:
        return module.load_ledger() or set()
    finally:
        module.LEDGER_PATH = original


def today_jst():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date()


def parse_date(text):
    """YYYY-MM-DD を date にする。形式・日付が不正なら None。"""
    if not text or not DATE_RE.match(text):
        return None
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        return None


# --- 入力の読み取り -------------------------------------------------------------


def load_calendar(path=None):
    """季節の山の台帳を読む。戻り値: ({slug: {"peaks": [(月, 日), ...], "basis": 根拠}}, 問題の行の説明のリスト)。"""
    path = path or CALENDAR_PATH
    calendar = {}
    problems = []
    if not os.path.isfile(path):
        return calendar, ["台帳 %s がありません" % os.path.relpath(path, ROOT).replace("\\", "/")]
    with open(path, encoding="utf-8") as f:
        for number, raw in enumerate(f, 1):
            line = raw.rstrip("\r\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            cells = [c.strip() for c in line.split("\t")]
            if cells[0] == "slug":
                continue
            if len(cells) < 2 or not cells[0] or not cells[1]:
                problems.append("%d行目: 「slug<TAB>peaks<TAB>根拠」の形ではありません" % number)
                continue
            slug, peaks_text = cells[0], cells[1]
            if slug in calendar:
                problems.append("%d行目: slug が重複しています（%s）" % (number, slug))
                continue
            peaks = []
            if peaks_text != NO_PEAK:
                for token in peaks_text.split(","):
                    m = PEAK_RE.match(token.strip())
                    try:
                        datetime.date(PEAK_FALLBACK_YEAR, int(m.group(1)), int(m.group(2)))
                    except (AttributeError, ValueError):
                        problems.append("%d行目: peaks を MM-DD として読めません（%s）" % (number, token.strip()))
                        peaks = None
                        break
                    peaks.append((int(m.group(1)), int(m.group(2))))
                if peaks is None:
                    continue
            calendar[slug] = {"peaks": peaks, "basis": cells[2] if len(cells) > 2 else ""}
    return calendar, problems


def read_frontmatter_head(path):
    """記事の先頭から category・date・status を読む（本文は読まない）。読めなければ空の辞書。"""
    result = {}
    try:
        with open(path, encoding="utf-8") as f:
            for number, line in enumerate(f):
                if number >= FRONTMATTER_HEAD_LINES:
                    break
                m = FRONTMATTER_KEY_RE.match(line.rstrip("\r\n"))
                if m and m.group(1) not in result:
                    result[m.group(1)] = m.group(2)
    except OSError:
        pass
    return result


def published_posts():
    """公開中の記事を {slug: {"category": ..., "date": ...}} で返す。"""
    posts = {}
    if not os.path.isdir(POSTS_DIR):
        return posts
    for name in sorted(os.listdir(POSTS_DIR)):
        if not name.endswith(".md"):
            continue
        head = read_frontmatter_head(os.path.join(POSTS_DIR, name))
        if head.get("status", "published") != "published":
            continue
        posts[name[:-3]] = {"category": head.get("category"), "date": head.get("date")}
    return posts


def advance_pins():
    """先行ピン（「- 先行ピン作成日:」行のあるピンmd）の一覧をピン番号の昇順で返す。"""
    return [e for e in piv().read_pin_entries(PINS_DIR) if e["advance_date"]]


def pin_images(pin_num):
    """output/Pin-images/ の「ピン{番号} …」形式の画像ファイル名（命名規則に合うものだけ）。"""
    if not os.path.isdir(PIN_IMAGES_DIR):
        return []
    naming = naming_checker()
    names = []
    for name in sorted(os.listdir(PIN_IMAGES_DIR)):
        m = naming.NEW_FORMAT_RE.match(name)
        if m and int(m.group("num")) == pin_num:
            names.append(name)
    return names


# --- 候補 -----------------------------------------------------------------------


def next_peak(peaks, target):
    """対象日以降で最も近い山の日付を返す（今年の山が過ぎていれば翌年）。"""
    best = None
    for month, day in peaks:
        for year in (target.year, target.year + 1):
            try:
                peak = datetime.date(year, month, day)
            except ValueError:  # うるう年でない年の 02-29
                peak = datetime.date(year, month, day - 1)
            if peak >= target:
                if best is None or peak < best:
                    best = peak
                break
    return best


def find_candidates(target, calendar, posts, pins):
    """対象日の候補を並び順どおりに返す。戻り値: (候補のリスト, 候補が無いときの理由)。"""
    target_text = target.isoformat()
    cooldown_from = (target - datetime.timedelta(days=COOLDOWN_DAYS)).isoformat()
    counts = {}
    recent = set()
    for pin in pins:
        if pin["advance_date"] >= target_text or not pin["slug"]:
            continue
        counts[pin["slug"]] = counts.get(pin["slug"], 0) + 1
        if pin["advance_date"] >= cooldown_from:
            recent.add(pin["slug"])

    in_window = []
    nearest = None
    for slug, entry in calendar.items():
        post = posts.get(slug)
        if not entry["peaks"] or not post or post["category"] not in TARGET_CATEGORIES:
            continue
        if not post["date"] or post["date"] >= target_text:
            continue  # 対象日に公開した記事・まだ公開していない記事は「既存記事」ではない
        peak = next_peak(entry["peaks"], target)
        days = (peak - target).days
        item = {"slug": slug, "peak": peak, "days": days, "count": counts.get(slug, 0)}
        if nearest is None or (days, slug) < (nearest["days"], nearest["slug"]):
            nearest = item
        if WINDOW_MIN_DAYS <= days <= WINDOW_MAX_DAYS:
            in_window.append(item)

    candidates = sorted((c for c in in_window if c["slug"] not in recent),
                        key=lambda c: (c["days"], c["count"], c["slug"]))
    if candidates:
        return candidates, None
    if in_window:
        return [], "山が%d〜%d日先の記事%d件は、すべて直近%d日以内に先行ピンを作成済み（%s）" % (
            WINDOW_MIN_DAYS, WINDOW_MAX_DAYS, len(in_window), COOLDOWN_DAYS,
            "・".join(sorted(c["slug"] for c in in_window)))
    if nearest:
        return [], "山が%d〜%d日先に来る記事がありません（最も近い山: slug=%s peak=%s 残り%d日）" % (
            WINDOW_MIN_DAYS, WINDOW_MAX_DAYS, nearest["slug"],
            nearest["peak"].strftime("%m-%d"), nearest["days"])
    return [], "台帳に山のある公開中の記事がありません"


# --- 先行ピン1件の検査（--verify） ----------------------------------------------


def verify_pin(pin, posts, out):
    """先行ピン1件を検査する。戻り値: NGの説明のリスト（空なら合格）。詳細は out へ出す。"""
    ng = []
    name = pin["file"]
    with open(os.path.join(PINS_DIR, name), encoding="utf-8") as f:
        text = f.read()

    out("=== 1. 命名（枝番を含む） ===")
    naming_ng = []
    min_branch = piv().ADVANCE_PIN_MIN_BRANCH
    m = PIN_FILE_RE.match(name)
    if not m:
        naming_ng.append("ファイル名が「YYYY-MM-DD-pin-<番号>-<slug>-<枝番2桁>.md」の形ではありません")
    else:
        if m.group(1) != pin["advance_date"]:
            naming_ng.append("ファイル名の日付（%s）が先行ピン作成日（%s）と違います" % (m.group(1), pin["advance_date"]))
        if m.group(3) != pin["slug"]:
            naming_ng.append("ファイル名のslug（%s）が誘導先URLのslug（%s）と違います" % (m.group(3), pin["slug"]))
        if int(m.group(4)) < min_branch:
            naming_ng.append("枝番が -%s です（先行ピンは -%02d 以降）" % (m.group(4), min_branch))
        same_branch = [e["file"] for e in piv().read_pin_entries(PINS_DIR)
                       if e["slug"] == pin["slug"] and e["num"] != pin["num"]
                       and e["branch"] == int(m.group(4))]
        if same_branch:
            naming_ng.append("同じ記事に同じ枝番のピンがあります（%s）" % "・".join(same_branch))
    utm = UTM_PIN_RE.search(text)
    if not utm or int(utm.group(1)) != pin["num"]:
        naming_ng.append("誘導先URLの utm_content がピン番号（pin%d）と一致しません" % pin["num"])
    images = pin_images(pin["num"])
    if len(images) != 1:
        naming_ng.append("output/Pin-images/ に「ピン%d …（誘導先 …）」形式の画像が%d件あります（1件にする）"
                         % (pin["num"], len(images)))
    for message in naming_ng:
        out("  [NG] %s" % message)
    if not naming_ng:
        out("  OK: %s ／ 画像: %s" % (name, images[0]))
    ng.extend(naming_ng)

    out("")
    out("=== 2. 誘導先（公開中の seasons・gift の既存記事） ===")
    post = posts.get(pin["slug"])
    if not post:
        message = "誘導先（%s）が公開中の記事ではありません" % pin["slug"]
    elif post["category"] not in TARGET_CATEGORIES:
        message = "誘導先の category が %s です（先行ピンの対象は %s）" % (
            post["category"], "・".join(TARGET_CATEGORIES))
    elif not post["date"] or post["date"] >= pin["advance_date"]:
        message = "誘導先の公開日（%s）が先行ピン作成日より前ではありません（先行ピンは既存記事へ足す）" % post["date"]
    else:
        message = None
    if message:
        out("  [NG] %s" % message)
        ng.append(message)
    else:
        out("  OK: %s（category: %s・公開日 %s）" % (pin["slug"], post["category"], post["date"]))

    out("")
    out("=== 3. check-pin-image-style.py --advance-pin %d ===" % pin["num"])
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        style_ng = style_checker().check_advance_pin(pin["num"])
    for line in buffer.getvalue().splitlines():
        out("  " + line)
    ng.extend(style_ng)

    out("")
    out("=== 4. check-x-post-length.py（このピンの投稿文） ===")
    if not x_checker().check_file(name, out):
        ng.append("%s: X向け本文・Threads用問いかけの検査がNG" % name)
    return ng


def pin_shortfalls(pin, posts, posted):
    """対象日の先行ピン1件について、完了に足りないものを返す（空なら完了）。"""
    reasons = []
    if not pin_images(pin["num"]):
        reasons.append("画像が未配置")
    if verify_pin(pin, posts, lambda _line="": None):
        reasons.append("検査がNG（--verify で内容を確認する）")
    if pin["num"] not in posted:
        reasons.append("Pinterestへ未投稿（data/pin-posted.md に記載なし）")
    return reasons


# --- 判定 -----------------------------------------------------------------------


def judge(target, calendar, posts, pins, posted):
    """対象日の判定を1行で返す。"""
    target_text = target.isoformat()
    todays = [p for p in pins if p["advance_date"] == target_text]
    if todays:
        for pin in todays:
            reasons = pin_shortfalls(pin, posts, posted)
            if reasons:
                return "%s pin=%d %s（手順 %s）" % (MARK_INCOMPLETE, pin["num"], "・".join(reasons), RULE_SECTION)
        return "%s pin=%s" % (MARK_DONE, ",".join(str(p["num"]) for p in todays))
    candidates, reason = find_candidates(target, calendar, posts, pins)
    if candidates:
        first = candidates[0]
        return "%s slug=%s peak=%s 残り%d日（日次を行う日は先行ピンを1件作る・手順 %s）" % (
            MARK_NEXT, first["slug"], first["peak"].strftime("%m-%d"), first["days"], RULE_SECTION)
    return "%s %s" % (MARK_NONE, reason)


def missing_calendar_rows(calendar, posts):
    """公開中の seasons・gift の記事のうち、台帳に行が無い slug を昇順で返す。"""
    return sorted(slug for slug, post in posts.items()
                  if post["category"] in TARGET_CATEGORIES and slug not in calendar)


def require_row(slug):
    """--require-row: seasons・gift の記事に台帳の行があるかを確かめる。合格なら0。"""
    category = None
    for directory in (DRAFTS_DIR, POSTS_DIR):
        path = os.path.join(directory, "%s.md" % slug)
        if os.path.isfile(path):
            category = read_frontmatter_head(path).get("category")
            break
    else:
        print("[NG] %s の記事ファイルが output/articles/・site/src/content/posts/ のどちらにもありません" % slug)
        return 1
    if category not in TARGET_CATEGORIES:
        print("OK: %s は category: %s のため、季節の山の台帳の対象外です" % (slug, category))
        return 0
    calendar, problems = load_calendar()
    for problem in problems:
        print("【警告】data/advance-pin-calendar.tsv %s" % problem)
    if slug in calendar:
        entry = calendar[slug]
        peaks = ",".join("%02d-%02d" % p for p in entry["peaks"]) or NO_PEAK
        print("OK: %s の行があります（peaks: %s）" % (slug, peaks))
        return 0
    print("[NG] %s（category: %s）の行が data/advance-pin-calendar.tsv にありません。" % (slug, category))
    print("     公開前に1行足してください: %s<TAB>peaks<TAB>根拠" % slug)
    print("     peaks は記事のタイトル・本文に明記された行事・季節の月日（MM-DD・カンマ区切り）。")
    print("     季節の山が無い記事は peaks を「%s」にする（書き方は台帳の冒頭を参照）。" % NO_PEAK)
    return 1


def parse_args(argv):
    """戻り値: 辞書 または None（使い方の誤り）。"""
    opts = {"date": None, "since": None, "until": None, "verify": False, "require_row": None}
    positional = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--date", "--since", "--until"):
            if i + 1 >= len(argv) or parse_date(argv[i + 1]) is None:
                sys.stderr.write("%s には YYYY-MM-DD を指定してください。\n" % arg)
                return None
            opts[arg[2:]] = parse_date(argv[i + 1])
            i += 1
        elif arg == "--verify":
            opts["verify"] = True
        elif arg == "--require-row":
            opts["require_row"] = True
        elif arg.startswith("-"):
            sys.stderr.write("不明な引数です: %s\n" % arg)
            return None
        else:
            positional.append(arg)
        i += 1
    if opts["require_row"]:
        if len(positional) != 1:
            sys.stderr.write("--require-row には slug を1つ指定してください。\n")
            return None
        opts["require_row"] = positional[0]
    elif positional:
        sys.stderr.write("不明な引数です: %s\n" % " ".join(positional))
        return None
    if (opts["since"] is None) != (opts["until"] is None):
        sys.stderr.write("--since と --until は両方指定してください。\n")
        return None
    if opts["since"] and opts["since"] > opts["until"]:
        sys.stderr.write("--since は --until 以前の日付にしてください。\n")
        return None
    return opts


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    opts = parse_args(argv)
    if opts is None:
        sys.stderr.write("使い方は python site/scripts/check-advance-pin-today.py の冒頭の説明を参照。\n")
        return 2
    if opts["require_row"]:
        return require_row(opts["require_row"])

    calendar, problems = load_calendar()
    posts = published_posts()
    pins = advance_pins()
    target = opts["date"] or today_jst()

    if opts["verify"]:
        todays = [p for p in pins if p["advance_date"] == target.isoformat()]
        if not todays:
            print("[NG] %s 付の先行ピン（「%s%s」行のあるピンmd）が output/pins/ にありません"
                  % (target.isoformat(), piv().ADVANCE_PIN_LABEL, target.isoformat()))
            return 1
        total = []
        for pin in todays:
            print("対象: ピン%d %s（先行ピン作成日 %s）" % (pin["num"], pin["file"], pin["advance_date"]))
            total.extend(verify_pin(pin, posts, print))
            print()
        if total:
            print("ADVANCE_PIN_VERIFY_NG（%d件）" % len(total))
            return 1
        print("ADVANCE_PIN_VERIFY_OK")
        return 0

    for problem in problems:
        print("【警告】data/advance-pin-calendar.tsv %s" % problem)
    posted = posted_pins()

    if opts["since"]:
        day = opts["since"]
        total = 0
        open_days = 0
        while day <= opts["until"]:
            line = judge(day, calendar, posts, pins, posted)
            print("%s %s" % (day.isoformat(), line))
            total += 1
            if line.startswith((MARK_NEXT, MARK_INCOMPLETE)):
                open_days += 1
            day += datetime.timedelta(days=1)
        print("%s %s〜%s NEXT・INCOMPLETEの日: %d日／%d日" % (
            MARK_PERIOD, opts["since"].isoformat(), opts["until"].isoformat(), open_days, total))
        return 0

    print(judge(target, calendar, posts, pins, posted))
    missing = missing_calendar_rows(calendar, posts)
    if missing:
        print("%s slug=%s（data/advance-pin-calendar.tsv に行を足す。山が無ければ peaks を %s にする）"
              % (MARK_MISSING, ",".join(missing), NO_PEAK))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
