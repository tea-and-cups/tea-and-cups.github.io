# -*- coding: utf-8 -*-
r"""Buffer経由のSNS投稿（X・Instagram・Threads）で未投稿の組を検知する
（引数なし・読み取り専用・API通信を一切行わない）。

判定材料:
  - output/pins/ のファイル名から抽出したピン番号のうち BUFFER_START_PIN 以上
  - サービスは post-pins-to-buffer.py の SERVICES（twitter / instagram / threads）
  - 台帳 data/buffer-posted.md の「投稿済み:」行

ピン番号の抽出・開始番号・サービス一覧・台帳の読み方は
post-pins-to-buffer.py からimportして再利用する（同じ判定を二重実装すると
片方だけ直って食い違うため）。このファイルには独自の判定を持たせない。

出力:
  - 未投稿0件: "BUFFER_POSTING_OK" の1行だけを出して終了コード0。
  - 未投稿あり: "BUFFER_UNPOSTED: " に続けて件数を出し、ピン番号ごとに
    未投稿のサービスを1行ずつ列挙して終了コード1。

使い方:
  python site/scripts/check-buffer-posting-status.py
"""

import importlib.util
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_post_pins_to_buffer():
    """post-pins-to-buffer.py をモジュールとして読み込む
    （ファイル名がハイフンを含み、そのままではimportできないため）。

    あちらは module 直下で .env もAPIも触らない（緊急停止スイッチより先に
    読み込まないよう、buffer_api / env_loader は main() の中でimportしている）。
    そのため読み込むだけでは通信は発生しない。
    """
    path = os.path.join(SCRIPT_DIR, "post-pins-to-buffer.py")
    spec = importlib.util.spec_from_file_location("post_pins_to_buffer", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    ppb = _load_post_pins_to_buffer()
    check_mod = ppb._load_check_pin_posting_status()

    created_map = check_mod.extract_created_pins()
    posted_pairs = ppb.load_posted_pairs()
    targets, _excluded = ppb.derive_targets(created_map, posted_pairs)

    if not targets:
        print("BUFFER_POSTING_OK")
        return 0

    unit_count = sum(len(services) for _, _, services in targets)
    print("BUFFER_UNPOSTED: %d組（%dピン・ピン番号%d以降が対象）"
          % (unit_count, len(targets), ppb.BUFFER_START_PIN))
    for pin_num, file_name, services in targets:
        print("  ピン%d: %s — %s" % (pin_num, ", ".join(services), file_name))
    return 1


if __name__ == "__main__":
    sys.exit(main())
