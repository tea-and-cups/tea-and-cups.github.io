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

使い方:
  python site/scripts/check-pin-image-style.py <slug>
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

ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
PINS_DIR = os.path.join(ROOT, "output", "pins")

# 漢数字2文字以上＋単位。1文字（「一杯」「一枚」「十分」等の慣用表現）は誤検知の
# 主因だったため対象外にする（実測・reports/2026-08-15-5.md、D-0126）。
KANJI_QUANTITY_RE = re.compile(
    r"[〇一二三四五六七八九十百千]{2,}(?:ml|ミリリットル|cc|円|度|分|秒|個|枚|杯|人)"
)


def find_pin_files(slug):
    pattern = os.path.join(PINS_DIR, "*-%s-*.md" % slug)
    return sorted(glob.glob(pattern))


def check_kanji_quantity(slug):
    """Pin投稿文（「## 投稿文」節）の数量表記を検査する。戻り値: NGメッセージのリスト。"""
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

    if len(sys.argv) != 2:
        sys.exit("usage: check-pin-image-style.py <slug>")
    slug = sys.argv[1]

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
        # 低情報量条件では「直近2記事の除外」は適用しない（候補が4種しかなく枯れるため・D-0152）。
        # 代わりに、3つとも低密度プールに含まれているかを見る（make-image-prompt.pyと同じ判定関数）。
        high = [f"{s}={styles[s]}" for s in piv.PIN_SLOTS if not piv.is_low_density(styles[s])]
        if high:
            ng.append(f"低情報量条件のため型は低密度プール（{'／'.join(piv.LOW_INFO_STYLES)}）"
                      f"から選ぶ必要がありますが、高密度の型が指定されています: {'、'.join(high)}")
        else:
            print(f"  OK: pin1〜3の型は3つとも低密度プール（{'／'.join(piv.LOW_INFO_STYLES)}）に含まれる")
        print("  ※この条件では直近2記事との重複はチェックしません（候補が4種しかないため・D-0152）")
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
    kanji_quantity_ng = check_kanji_quantity(slug)
    ng.extend(kanji_quantity_ng)

    print()
    if ng:
        print(f"総合: NG（{len(ng)}件）")
        sys.exit(1)
    print("総合: OK" + ("（警告あり）" if warn else ""))


if __name__ == "__main__":
    main()
