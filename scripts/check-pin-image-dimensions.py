"""output/Pin-images/ 配下のPin画像の寸法・カラーモードを確認し、横長ならエラーで止める。

Pinterest推奨比率（縦長2:3）通りに生成されているかの検査用。
表示専用ではなく「配置を止める判定器」である（D-0174）。copy-pin-image.sh が
cp の前にこのスクリプトを呼び、非ゼロ終了ならコピーせずに中止する。
閾値の正本はこのファイルの MIN_ASPECT_PIN 1箇所だけに置く（呼び出し側へ書き写さない）。

判定基準:
  高さ÷幅 が MIN_ASPECT_PIN（1.4）未満のものを「違反」とする。

使い方:
  python site/scripts/check-pin-image-dimensions.py <ファイル名> [<ファイル名> ...]
    ファイル名はそのまま存在すればそのパスを使い（絶対パス・cwd相対に対応）、
    存在しなければ output/Pin-images/ からの相対名として解決する
    （例: pin-48-xxx-01.png）

終了コード:
  0 = 対象全件が「高さ÷幅 ≥ 1.4」
  1 = 引数が0個／違反が1件以上／ファイルが見つからない・画像として開けない
"""

import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(ROOT, "output", "Pin-images")

# --- 横長ガード（D-0174） ---
# 数値 1.4 は hero-to-webp.py の MIN_ASPECT と同じだが、向きが逆である点に注意。
#   hero : 横長が正。幅÷高さ が 1.4 未満なら NG
#   Pin  : 縦長が正。高さ÷幅 が 1.4 未満なら NG（このファイル）
# 実測根拠: 正規のPin画像は 高さ÷幅 が 1.500〜1.502 に密集し、1.4〜1.5 の帯に
# 実ファイルは1件も存在しない。最も縦長の正常例は 941x1672（1.777）で、これは合格させる。
MIN_ASPECT_PIN = 1.4


def resolve(name):
    """引数の文字列を実ファイルパスへ解決する。

    a. そのままファイルとして存在すればそれを使う（絶対パス・cwd相対に対応）
    b. 存在しなければ output/Pin-images/<引数> として解決する（従来の呼び方）
    """
    if os.path.isfile(name):
        return name
    return os.path.join(SRC_DIR, name)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    violations = []
    errors = []

    for name in args:
        path = resolve(name)
        if not os.path.isfile(path):
            print(f"【エラー】{name:40} ファイルが見つかりません: {path}")
            errors.append(name)
            continue
        try:
            im = Image.open(path)
            w, h = im.size
        except Exception as exc:
            print(f"【エラー】{name:40} 画像として開けません: {exc}")
            errors.append(name)
            continue

        wh = w / h  # 幅÷高さ（従来から表示している値）
        hw = h / w  # 高さ÷幅（今回の判定に使う値）
        if hw < MIN_ASPECT_PIN:
            note = f"✕ 停止対象（高さ÷幅が{MIN_ASPECT_PIN}未満）"
            violations.append((name, w, h, hw))
        elif abs(wh - 2 / 3) < 0.03:
            note = "○ 縦長2:3に近い"
        else:
            note = "△ 2:3から外れている"
        print(
            f"{name:48} {w}x{h} mode={im.mode}  "
            f"幅÷高さ={wh:.3f} 高さ÷幅={hw:.3f}  {note}"
        )

    if violations:
        print()
        print(
            f"【中断】高さ÷幅が{MIN_ASPECT_PIN}未満の画像が{len(violations)}件あります。"
            "このままでは配置・投稿に進めません。"
        )
        print(
            "  Pinterestは縦長2:3（高さ÷幅=1.5）が推奨です。"
            "ChatGPTへ縦長（高さが幅の1.4倍以上）での作り直しを依頼してください。"
        )
    if violations or errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
