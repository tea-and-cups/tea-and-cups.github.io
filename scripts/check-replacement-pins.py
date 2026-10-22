# -*- coding: utf-8 -*-
r"""差し替えピン（改修で古くなった既投稿ピンを新番号で作り直したもの・D-0282）の未完了を出し、1件を検査する。

背景:
  差し替えピンは「新ピンの投稿」と「旧ピンの削除」の2段で完了する。旧ピンの削除は
  post-pins-to-pinterest.py が新ピンの投稿時（または --apply-replacements）に API で行うが、
  画像の作り直し上限などで途中で打ち切った差し替えは、AIの注意に任せると忘れられる。
  そこで毎セッションの開始時（session-start-check.py）に未完了を必ず出す。

入力:
  output/pins/*.md     「- 差し替え元ピン: N」行のあるmd＝差し替えピン。「- 旧ピン処理: …」行が
                       あれば完了（行の定義は pick-image-variation.py が正本）。
  output/Pin-images/   「ピン{番号} …（誘導先 …）」形式の画像。
  data/pin-posted.md   投稿済みのピン番号。

使い方:
  python site/scripts/check-replacement-pins.py
      未完了の差し替えを1件1行で出す。無ければ REPLACEMENT_NONE。終了コードは常に0。
        REPLACEMENT_OPEN pin=<新> old=<旧> 状態=画像なし|未投稿|旧ピン未処理 経過<N>日 次の操作=<一言>
  python site/scripts/check-replacement-pins.py --verify <新ピン番号>
      差し替えピン1件の検査（枝番 -04 以降・重複なし／画像1件／誘導先が公開中の記事（category不問）／
      旧番号のmdが実在／型の重複・数量表記・先頭文言・合成の目印（check-pin-image-style.py の
      先行ピンのモード）／check-x-post-length.py）。合格0・不合格1。
      先行ピンの検査（check-advance-pin-today.py --verify）は差し替えピンに使わない。
"""

import contextlib
import datetime
import importlib.util
import io
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

MARK_OPEN = "REPLACEMENT_OPEN"
MARK_NONE = "REPLACEMENT_NONE"
STATE_NO_IMAGE = "画像なし"
STATE_UNPOSTED = "未投稿"
STATE_OLD_OPEN = "旧ピン未処理"
NEXT_MAKE = "画像生成→審査→投稿"
NEXT_APPLY = "post-pins-to-pinterest.py --apply-replacements を実行"
FILE_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-")

_CAP = []


def cap():
    """check-advance-pin-today.py（読み込み先のディレクトリ・画像・投稿済み・各検査の入口）。1プロセス1回。"""
    if not _CAP:
        spec = importlib.util.spec_from_file_location(
            "check_advance_pin_today", os.path.join(SCRIPT_DIR, "check-advance-pin-today.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _CAP.append(module)
    return _CAP[0]


def replacement_entries():
    """差し替えピン（差し替え元ピン行のあるmd）の一覧をピン番号の昇順で返す。"""
    return [e for e in cap().piv().read_pin_entries(cap().PINS_DIR) if e["replace_from"] is not None]


def elapsed_days(file_name, today):
    m = FILE_DATE_RE.match(file_name)
    try:
        return (today - datetime.date.fromisoformat(m.group(1))).days if m else None
    except ValueError:
        return None


def open_lines(today=None):
    """未完了の差し替えを REPLACEMENT_OPEN の行で返す（無ければ空）。"""
    today = today or cap().today_jst()
    posted = cap().posted_pins()
    lines = []
    for e in replacement_entries():
        if e["old_pin_result"] is not None:
            continue
        if not cap().pin_images(e["num"]):
            state, action = STATE_NO_IMAGE, NEXT_MAKE
        elif e["num"] not in posted:
            state, action = STATE_UNPOSTED, NEXT_MAKE
        else:
            state, action = STATE_OLD_OPEN, NEXT_APPLY
        days = elapsed_days(e["file"], today)
        note = "（差し替え元ピン行が%d行・1行にする）" % e["replace_count"] if e["replace_count"] > 1 else ""
        lines.append("%s pin=%d old=%d 状態=%s 経過%s日 次の操作=%s%s" % (
            MARK_OPEN, e["num"], e["replace_from"], state, "?" if days is None else days, action, note))
    return lines


def verify(pin_num, out):
    """差し替えピン1件の検査。戻り値: NGの説明のリスト（空なら合格）。"""
    c = cap()
    piv = c.piv()
    entries = piv.read_pin_entries(c.PINS_DIR)
    entry = next((e for e in entries if e["num"] == pin_num), None)
    if entry is None:
        out("[NG] ピン%d のmdが output/pins/ にありません" % pin_num)
        return ["ピン%d: mdが無い" % pin_num]
    name = entry["file"]
    out("対象: ピン%d %s（差し替え元ピン %s）" % (pin_num, name, entry["replace_from"]))
    if entry["replace_from"] is None:
        out("[NG] 「%s」行がありません（差し替えピンの検査は差し替えピンだけが対象）" % piv.REPLACE_FROM_LABEL.strip())
        return ["%s: 差し替え元ピン行が無い" % name]
    with open(os.path.join(c.PINS_DIR, name), encoding="utf-8") as f:
        text = f.read()

    ng = []
    out("")
    out("=== 1. 命名（枝番 -%02d 以降・重複なし）・画像1件 ===" % piv.ADVANCE_PIN_MIN_BRANCH)
    naming_ng = []
    if entry["replace_count"] > 1:
        naming_ng.append("差し替え元ピン行が%d行あります（1行にする）" % entry["replace_count"])
    m = c.PIN_FILE_RE.match(name)
    if not m:
        naming_ng.append("ファイル名が「YYYY-MM-DD-pin-<番号>-<slug>-<枝番2桁>.md」の形ではありません")
    else:
        if m.group(3) != entry["slug"]:
            naming_ng.append("ファイル名のslug（%s）が誘導先URLのslug（%s）と違います" % (m.group(3), entry["slug"]))
        if int(m.group(4)) < piv.ADVANCE_PIN_MIN_BRANCH:
            naming_ng.append("枝番が -%s です（差し替えピンは -%02d 以降）" % (m.group(4), piv.ADVANCE_PIN_MIN_BRANCH))
        same = [e["file"] for e in entries if e["slug"] == entry["slug"] and e["num"] != pin_num
                and e["branch"] == int(m.group(4))]
        if same:
            naming_ng.append("同じ記事に同じ枝番のピンがあります（%s）" % "・".join(same))
    utm = c.UTM_PIN_RE.search(text)
    if not utm or int(utm.group(1)) != pin_num:
        naming_ng.append("誘導先URLの utm_content がピン番号（pin%d）と一致しません" % pin_num)
    images = c.pin_images(pin_num)
    if len(images) != 1:
        naming_ng.append("output/Pin-images/ に「ピン%d …（誘導先 …）」形式の画像が%d件あります（1件にする）"
                         % (pin_num, len(images)))
    for message in naming_ng:
        out("  [NG] %s" % message)
    if not naming_ng:
        out("  OK: %s ／ 画像: %s" % (name, images[0]))
    ng.extend(naming_ng)

    out("")
    out("=== 2. 誘導先（公開中の記事・category は問わない） ===")
    post = c.published_posts().get(entry["slug"])
    if post:
        out("  OK: %s（category: %s）" % (entry["slug"], post["category"]))
    else:
        message = "誘導先（%s）が公開中の記事ではありません" % entry["slug"]
        out("  [NG] %s" % message)
        ng.append(message)

    out("")
    out("=== 3. 旧ピン%d のmd ===" % entry["replace_from"])
    old = next((e for e in entries if e["num"] == entry["replace_from"] and e["num"] != pin_num), None)
    if old:
        out("  OK: %s" % old["file"])
    else:
        message = "旧ピン%d のmdが output/pins/ にありません" % entry["replace_from"]
        out("  [NG] %s" % message)
        ng.append(message)

    out("")
    out("=== 4. check-pin-image-style.py --advance-pin %d（型の重複・数量表記・先頭文言・合成の目印） ===" % pin_num)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        style_ng = c.style_checker().check_advance_pin(pin_num)
    for line in buffer.getvalue().splitlines():
        out("  " + line)
    ng.extend(style_ng)

    out("")
    out("=== 5. check-x-post-length.py（このピンの投稿文） ===")
    if not c.x_checker().check_file(name, out):
        ng.append("%s: X向け本文・Threads用問いかけの検査がNG" % name)
    return ng


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    if argv[:1] == ["--verify"]:
        if len(argv) != 2 or not argv[1].isdigit():
            sys.stderr.write("usage: check-replacement-pins.py --verify <新ピン番号>\n")
            return 2
        ng = verify(int(argv[1]), print)
        print()
        if ng:
            print("REPLACEMENT_VERIFY_NG（%d件）" % len(ng))
            return 1
        print("REPLACEMENT_VERIFY_OK")
        return 0
    if argv:
        sys.stderr.write("不明な引数です: %s\n" % " ".join(argv))
        return 2

    lines = open_lines()
    for line in lines:
        print(line)
    if not lines:
        print(MARK_NONE)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
