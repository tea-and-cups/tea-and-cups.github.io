"""Pin画像（pin1〜3）の「型」（image_style）を機械確認する（D-0062）。

確認内容:
  1. 記録漏れチェック（最優先）: 対象記事のpin1〜3のimage_style列が3つとも
     埋まっているか。1つでも空欄なら `--set-style` の実行忘れとしてエラーにする。
     （--set-styleは型を選定した後の別ステップのため、忘れても他の処理は正常に
     流れてしまい、台帳が空欄のままpushされる。空欄の行は次回以降の重複除外
     計算からも無視されるため、除外の仕組み自体が徐々に効かなくなる。
     よって空欄そのものを機械的に止める）
  2. 重複チェック（1を通過した場合のみ実施）:
     - 対象記事のpin1〜3の型が3つとも異なるか
     - 直近2記事（対象記事を含まない直前2記事・image_styleが空欄の行は
       計算対象外）で使われた型と重複していないか
     pick-image-variation.py 側で候補不足による緩和（直近1記事のみの除外／
     除外なし）が発生する状態の場合は、重複を警告のみに留めエラーにしない。
     緩和の有無は台帳の内容から同じロジックで再計算して判定する。
     条件（情報量×CTAの4群・D-0152）は piv.conditions_for_slug() から引く。判定に効くのは
     情報量条件だけで、CTAの有無は型の選定に影響しない（CTAありでもpin1〜3の3枚すべてに
     同じ帯を入れるため、型の重複判定は変わらない）。CTA条件は参考として出力に表示する。
  3. Pin投稿文の数量表記チェック（D-0126）: output/pins/配下の対象記事のPin
     投稿文ファイル（「## 投稿文」節）に、漢数字2文字以上＋単位（ml/ミリリットル/
     cc/円/度/分/秒/個/枚/杯/人）が直後に続く表記がないか検査する。
     検知したらNG（「五百ミリリットル」等、本来アラビア数字で書くべき数量表記）。
     漢数字1文字＋単位（「一杯」「一枚」「十分」等の慣用表現・数量の断定ではない
     ことが多い）は実測（reports/2026-08-15-5.md）で誤検知の主因だったため対象外
     とする。対象記事のPin投稿文ファイルが見つからない場合はこの節をスキップする
     （画像生成前などファイル未作成の段階でこのチェックを走らせるケースがあるため）。
  4. Pin先頭文言の疑問形チェック（GD-0036前半・ピン352以降）。
  5. Pin画像の「琥珀時間」合成チェック（GD-0036後半・D-0274・ピン352以降）:
     output/Pin-images/ の画像（PNG）に、後処理で合成した目印（tEXtチャンク）が
     入っているかを検査する。目印は copy-pin-image.sh が配置時に入れる。目印が無い・
     画像が見つからない場合はNG（生の cp で置いた、または配置前の可能性）。
     目印のキー名と読み取りは hero-to-webp.py を唯一の定義元とする。

先行ピンのモード（--advance-pin <ピン番号>・D-0256・D-0275）:
  先行ピン（ピンmdに「- 先行ピン作成日:」行があるもの）は既存記事へ足す1枚で、台帳に行を
  持たない。このモードは台帳の有無を見ず、その1枚だけに次を適用する: 型がピンmdに書かれ、
  その記事の他のピン・直近の先行ピンと重ならないこと／上の3・4・5（数量表記・先頭文言の
  疑問形・右下の合成の目印）。記事単位の検査（slug指定）は先行ピンのファイルを対象から外す。

使い方:
  python site/scripts/check-pin-image-style.py <slug>
  python site/scripts/check-pin-image-style.py --advance-pin <ピン番号>
"""

import glob
import importlib.util
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 型プール・台帳の読み書きロジックは pick-image-variation.py を唯一の定義元とする
# （ファイル名にハイフンを含むため通常のimportができず、importlibで読み込む）
_spec = importlib.util.spec_from_file_location(
    "pick_image_variation", os.path.join(SCRIPT_DIR, "pick-image-variation.py")
)
piv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(piv)

# 合成済みの目印（キー名・読み取り）は hero-to-webp.py を唯一の定義元とする（D-0274）
_spec_h2w = importlib.util.spec_from_file_location(
    "hero_to_webp", os.path.join(SCRIPT_DIR, "hero-to-webp.py")
)
h2w = importlib.util.module_from_spec(_spec_h2w)
_spec_h2w.loader.exec_module(h2w)

ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
PINS_DIR = os.path.join(ROOT, "output", "pins")
PIN_IMAGES_DIR = os.path.join(ROOT, "output", "Pin-images")
ADVANCE_PIN_OPT = "--advance-pin"

# 漢数字2文字以上＋単位。1文字（「一杯」「一枚」「十分」等の慣用表現）は誤検知の
# 主因だったため対象外にする（実測・reports/2026-08-15-5.md、D-0126）。
KANJI_QUANTITY_RE = re.compile(
    r"[〇一二三四五六七八九十百千]{2,}(?:ml|ミリリットル|cc|円|度|分|秒|個|枚|杯|人)"
)


# Pinの先頭文言＝画像指示書「- テキストオーバーレイ:」行の最初の「…」（GD-0036・前半）。
# 末尾が「？」「?」の疑問形はNG。既存ピンを止めないため、ピン352以降だけを対象にする。
HEAD_QUESTION_FROM_PIN = 352
RE_PIN_NUMBER = re.compile(r"-pin-(\d+)-")
RE_OVERLAY_LINE = re.compile(r"^- テキストオーバーレイ:\s*(.*)$", re.M)
RE_FIRST_QUOTED = re.compile(r"「([^」]*)」")


def head_text_of(content):
    """ピンmdの先頭文言（最初の「…」の中身）を返す。無ければ None。"""
    m = RE_OVERLAY_LINE.search(content)
    if not m:
        return None
    q = RE_FIRST_QUOTED.search(m.group(1))
    return q.group(1).strip() if q else None


def is_head_question(text):
    return text is not None and text.endswith(("？", "?"))


def check_head_question(slug, files=None):
    """ピン352以降の先頭文言が疑問形でないかを検査する。戻り値: NGメッセージのリスト。

    files を渡すと、slug から探す代わりにそのファイルだけを検査する（先行ピンのモード用）。
    """
    if files is None:
        files = find_pin_files(slug)
    ng_messages = []
    checked = 0
    for path in files:
        name = os.path.basename(path)
        m = RE_PIN_NUMBER.search(name)
        if not m or int(m.group(1)) < HEAD_QUESTION_FROM_PIN:
            continue
        checked += 1
        with open(path, encoding="utf-8") as f:
            head = head_text_of(f.read())
        if is_head_question(head):
            print("  [NG] %s: 先頭文言「%s」が疑問形です（答えの文言にする・GD-0036）" % (name, head))
            ng_messages.append("%s: 先頭文言「%s」が疑問形" % (name, head))
    if not ng_messages:
        print("  OK: ピン%d以降の対象%d件に疑問形の先頭文言なし" % (HEAD_QUESTION_FROM_PIN, checked))
    return ng_messages


# Pin画像のファイル名「ピン{番号} …」（rules/image-generation-flow.md 1-2）から番号を取る。
RE_PIN_IMAGE_NUMBER = re.compile(r"^ピン(\d+)")
COPY_PIN_IMAGE_CMD = 'bash "C:/Claude/Tea_TeaCut/site/scripts/copy-pin-image.sh" <Downloads内のファイル名> <配置後のファイル名>'


def check_brand_stamp(slug, files=None):
    """ピン352以降のPin画像に「琥珀時間」の合成済みの目印があるかを検査する（GD-0036後半・D-0274）。

    境界は先頭文言の疑問形チェックと同じ HEAD_QUESTION_FROM_PIN を使う。戻り値: NGメッセージのリスト。
    files を渡すと、slug から探す代わりにそのファイルだけを検査する（先行ピンのモード用）。
    """
    if files is None:
        files = find_pin_files(slug)
    targets = []
    for path in files:
        m = RE_PIN_NUMBER.search(os.path.basename(path))
        if m and int(m.group(1)) >= HEAD_QUESTION_FROM_PIN:
            targets.append(int(m.group(1)))

    images = {}
    if os.path.isdir(PIN_IMAGES_DIR):
        for name in sorted(os.listdir(PIN_IMAGES_DIR)):
            m = RE_PIN_IMAGE_NUMBER.match(name)
            if m and os.path.isfile(os.path.join(PIN_IMAGES_DIR, name)):
                images.setdefault(int(m.group(1)), []).append(name)

    ng_messages = []
    for num in targets:
        names = images.get(num, [])
        if not names:
            print("  [NG] ピン%d: output/Pin-images/ に画像が見つかりません（「%s」の合成を確認できません）"
                  % (num, h2w.BRAND_TEXT))
            ng_messages.append("ピン%d: Pin画像が見つからない" % num)
            continue
        for name in names:
            if h2w.pin_has_brand_stamp(os.path.join(PIN_IMAGES_DIR, name)):
                continue
            print("  [NG] %s: 「%s」の合成済みの目印がありません" % (name, h2w.BRAND_TEXT))
            ng_messages.append("%s: 「%s」の合成済みの目印がない" % (name, h2w.BRAND_TEXT))
    if ng_messages:
        print("       合成前の原本（~/Downloads）から、次のスクリプトで配置し直してください"
              "（生の cp では合成されません）:")
        print("       " + COPY_PIN_IMAGE_CMD)
    else:
        print("  OK: ピン%d以降の対象%d件すべてに合成済みの目印あり" % (HEAD_QUESTION_FROM_PIN, len(targets)))
    return ng_messages


def find_pin_files(slug):
    pattern = os.path.join(PINS_DIR, "*-%s-*.md" % slug)
    return sorted(glob.glob(pattern))


def is_advance_pin_file(path):
    """ピンmdが先行ピン（「- 先行ピン作成日:」行あり・D-0256）か。目印の定義は piv が正本。"""
    try:
        with open(path, encoding="utf-8") as f:
            return piv.advance_pin_date(f.read()) is not None
    except OSError:
        return False


def check_advance_pin(pin_num):
    """先行ピン1枚（ピン番号 pin_num）の検査。戻り値: NGメッセージのリスト（空なら合格）。

    先行ピンは既存記事へ足す1枚で、4枚セット用の台帳（data/image-variation.tsv）に行を持たない。
    そのため台帳の有無は見ず、型はピンmdの「- 型:」行で確かめる。数量表記・先頭文言の疑問形・
    右下の合成の目印は、通常のピンと同じ関数でこの1ファイルだけを検査する。
    """
    entries = piv.read_pin_entries(PINS_DIR)
    entry = next((e for e in entries if e["num"] == pin_num), None)
    if entry is None:
        print("  [NG] ピン%d の投稿文ファイルが output/pins/ にありません" % pin_num)
        return ["ピン%d: 投稿文ファイルが無い" % pin_num]
    name = entry["file"]
    path = os.path.join(PINS_DIR, name)
    print("対象: %s（先行ピン）" % name)
    if not entry["advance_date"]:
        print("  [NG] 「%s」行がありません（先行ピンのモードは先行ピンだけを検査します）"
              % piv.ADVANCE_PIN_LABEL.strip())
        return ["%s: 先行ピン作成日の行が無い" % name]

    ng = []
    print()
    print("=== 1. 型（ピンmdの「- 型:」行・台帳は見ない） ===")
    style = entry["style"]
    article_styles, previous = piv.advance_style_exclusions(entry["slug"], pin_num, entries)
    if style not in piv.IMAGE_STYLES:
        print("  [NG] 型「%s」は型候補プールにありません。指定できる型: %s"
              % (style or "（行なし）", "／".join(piv.IMAGE_STYLES)))
        ng.append("%s: 型が候補プールに無い" % name)
    else:
        problems = []
        if style in article_styles:
            problems.append("この記事の他のピンと同じ型です")
        if previous and previous["style"] == style:
            problems.append("直近の先行ピン（ピン%d）と同じ型です" % previous["num"])
        # 避ける型を除くと候補が残らない場合は、選ぶ側（piv.advance_pin_plan）と同じく重複を許す。
        excluded = set(article_styles)
        if previous and previous["style"] in piv.IMAGE_STYLES:
            excluded.add(previous["style"])
        if problems and len(excluded) < len(piv.IMAGE_STYLES):
            for p in problems:
                print("  [NG] 型「%s」: %s" % (style, p))
                ng.append("%s: %s" % (name, p))
        else:
            print("  OK: 型=%s（この記事の他のピン: %s／直近の先行ピン: %s）"
                  % (style, "／".join(sorted(article_styles)) or "型の記録なし",
                     "%s（ピン%d）" % (previous["style"], previous["num"]) if previous else "なし"))

    print()
    print("=== 2. Pin投稿文の数量表記チェック（漢数字＋単位・D-0126） ===")
    ng.extend(check_kanji_quantity(entry["slug"], files=[path]))
    print()
    print("=== 3. Pin先頭文言の疑問形チェック（GD-0036・ピン%d以降） ===" % HEAD_QUESTION_FROM_PIN)
    ng.extend(check_head_question(entry["slug"], files=[path]))
    print()
    print("=== 4. Pin画像の「%s」合成チェック（GD-0036・D-0274・ピン%d以降） ==="
          % (h2w.BRAND_TEXT, HEAD_QUESTION_FROM_PIN))
    ng.extend(check_brand_stamp(entry["slug"], files=[path]))
    return ng


def check_kanji_quantity(slug, files=None):
    """Pin投稿文（「## 投稿文」節）の数量表記を検査する。戻り値: NGメッセージのリスト。

    files を渡すと、slug から探す代わりにそのファイルだけを検査する（先行ピンのモード用）。
    """
    if files is None:
        files = find_pin_files(slug)
    if not files:
        print("  （対象のPin投稿文ファイルが見つかりません。未作成の段階の場合はスキップ）")
        return []

    ng_messages = []
    any_hit = False
    for path in files:
        with open(path, encoding="utf-8") as f:
            content = f.read()
        m = re.search(r"## 投稿文\n(.*?)(?:\n## |\Z)", content, re.S)
        if not m:
            continue
        section = m.group(1)
        base_offset = m.start(1)
        for mm in KANJI_QUANTITY_RE.finditer(section):
            any_hit = True
            # 該当箇所を含む行番号を出す
            line_no = content.count("\n", 0, base_offset + mm.start()) + 1
            name = os.path.basename(path)
            print("  [NG] %s 行%d: 「%s」（漢数字表記の数量はアラビア数字にする）" % (name, line_no, mm.group()))
            ng_messages.append("%s 行%d: %s" % (name, line_no, mm.group()))
    if not any_hit:
        print("  OK: 検査対象%d件のPin投稿文ファイルに漢数字の数量表記なし" % len(files))
    return ng_messages


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) == 3 and sys.argv[1] == ADVANCE_PIN_OPT and sys.argv[2].isdigit():
        ng = check_advance_pin(int(sys.argv[2]))
        print()
        if ng:
            print(f"総合: NG（{len(ng)}件）")
            sys.exit(1)
        print("総合: OK")
        return

    if len(sys.argv) != 2 or sys.argv[1].startswith("-"):
        sys.exit("usage: check-pin-image-style.py <slug>\n"
                 "       check-pin-image-style.py %s <ピン番号>" % ADVANCE_PIN_OPT)
    slug = sys.argv[1]

    # 先行ピンは台帳に行を持たず、--advance-pin のモードで1枚ずつ検査する。
    # 記事単位の検査（3〜5）からは外す（作成途中の先行ピンで新規記事の公開前チェックを止めないため）。
    pin_files = [p for p in find_pin_files(slug) if not is_advance_pin_file(p)]

    rows = piv.read_ledger()
    target = {r["image_type"]: r for r in rows if r["slug"] == slug and r["image_type"] in piv.PIN_SLOTS}

    print(f"対象記事: {slug}")
    print()
    print("=== 1. 型の記録漏れチェック（--set-styleの実行忘れ） ===")

    missing_rows = [s for s in piv.PIN_SLOTS if s not in target]
    if missing_rows:
        print(f"  [NG] 台帳に {slug} の行がありません: {'・'.join(missing_rows)}")
        print("       先に python site/scripts/pick-image-variation.py <slug> を実行する")
        print()
        print("総合: NG")
        sys.exit(1)

    styles = {s: target[s]["image_style"].strip() for s in piv.PIN_SLOTS}
    blanks = [s for s in piv.PIN_SLOTS if not styles[s]]
    if blanks:
        print(f"  [NG] image_styleが空欄です: {'・'.join(blanks)}")
        print("       型を選定したら必ず次を実行して台帳に記録する:")
        print(f'       python site/scripts/pick-image-variation.py --set-style {slug} "pin1=<型名>" "pin2=<型名>" "pin3=<型名>"')
        print()
        print("総合: NG")
        sys.exit(1)

    unknown = [f"{s}={styles[s]}" for s in piv.PIN_SLOTS if styles[s] not in piv.IMAGE_STYLES]
    if unknown:
        print(f"  [NG] 型候補プールに無い値が記録されています: {'、'.join(unknown)}")
        print("       指定できる型: " + "／".join(piv.IMAGE_STYLES))
        print()
        print("総合: NG")
        sys.exit(1)

    print("  OK: " + "、".join(f"{s}={styles[s]}" for s in piv.PIN_SLOTS))

    print()
    print("=== 2. 型の重複チェック ===")

    conditions = piv.conditions_for_slug(slug, rows) or (piv.CONDITION_CURRENT, piv.CTA_NONE)
    condition, cta = conditions
    _candidates, used, lookback = piv.available_styles(rows, exclude_slug=slug, condition=condition)
    low_info = condition == piv.CONDITION_LOW
    relaxed = (not low_info) and lookback < piv.STYLE_LOOKBACK
    used_ref = piv.recent_style_usage(rows, exclude_slug=slug, lookback=piv.STYLE_LOOKBACK)

    ng = []
    warn = []

    # CTAの有無は型の重複判定に影響しない（3枚すべてに同じ帯を入れるため）。参考として表示だけする。
    print(f"  条件: {condition}／{cta}（D-0152）")

    values = [styles[s] for s in piv.PIN_SLOTS]
    if len(set(values)) != len(values):
        dupes = sorted({v for v in values if values.count(v) > 1})
        ng.append(f"記事内でpin1〜3の型が重複しています: {'／'.join(dupes)}")
    else:
        print("  OK: pin1〜3の型は3つとも異なる")

    if low_info:
        # 低情報量条件では「直近2記事の除外」は適用しない（候補が数種しかなく枯れるため・D-0152）。
        # 代わりに、3つとも低密度プールに含まれているかを見る（make-image-prompt.pyと同じ判定関数）。
        high = [f"{s}={styles[s]}" for s in piv.PIN_SLOTS if not piv.is_low_density(styles[s])]
        if high:
            ng.append(f"低情報量条件のため型は低密度プール（{'／'.join(piv.LOW_INFO_STYLES)}）"
                      f"から選ぶ必要がありますが、高密度の型が指定されています: {'、'.join(high)}")
        else:
            print(f"  OK: pin1〜3の型は3つとも低密度プール（{'／'.join(piv.LOW_INFO_STYLES)}）に含まれる")
        print(f"  ※この条件では直近2記事との重複はチェックしません（候補が{len(piv.LOW_INFO_STYLES)}種しかないため・D-0152）")
    else:
        overlap = sorted(set(values) & used_ref)
        if overlap:
            message = f"直近{piv.STYLE_LOOKBACK}記事で使用済みの型と重複しています: {'／'.join(overlap)}"
            if relaxed:
                warn.append(message)
            else:
                ng.append(message)
        else:
            print(f"  OK: 直近{piv.STYLE_LOOKBACK}記事で使用済みの型（{'／'.join(sorted(used_ref)) if used_ref else '記録なし'}）と重複なし")

        if relaxed:
            detail = "直近1記事のみの除外" if lookback == 1 else "除外なし（プール全体）"
            print(f"  ※緩和適用中（{detail}）: 候補が3個未満になるため、直近記事との重複は警告のみとしエラーにしません")

    print()
    for m in warn:
        print(f"  [警告] {m}")
    for m in ng:
        print(f"  [NG] {m}")

    print()
    print("=== 3. Pin投稿文の数量表記チェック（漢数字＋単位・D-0126） ===")
    kanji_quantity_ng = check_kanji_quantity(slug, files=pin_files)
    ng.extend(kanji_quantity_ng)

    print()
    print("=== 4. Pin先頭文言の疑問形チェック（GD-0036・ピン352以降） ===")
    ng.extend(check_head_question(slug, files=pin_files))

    print()
    print("=== 5. Pin画像の「琥珀時間」合成チェック（GD-0036・D-0274・ピン352以降） ===")
    ng.extend(check_brand_stamp(slug, files=pin_files))

    print()
    if ng:
        print(f"総合: NG（{len(ng)}件）")
        sys.exit(1)
    print("総合: OK" + ("（警告あり）" if warn else ""))


if __name__ == "__main__":
    main()
