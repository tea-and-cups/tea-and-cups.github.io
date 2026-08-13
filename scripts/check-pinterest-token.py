# -*- coding: utf-8 -*-
r"""Pinterestトークンの期限監視（session-start-check.py の子スクリプト・T4）。

挙動:
  - 残り7日以上: ネットワーク通信を一切行わずローカルの日付比較のみで判定し、
    「TOKEN_OK」相当の1行を出力して終了コード0
  - 残り7日未満: リフレッシュを試みる。成功したら成功した旨を出力し終了コード0。
    失敗したら【警告】を出力し終了コード1
  - リフレッシュトークン失効済み、または.envが無い・必要キーが空: 【エラー】を出力し
    終了コード2（再認可が必要である旨を明記）

どの経路でもトークンの値そのものは出力しない。
"""

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
from env_loader import EnvLoaderError  # noqa: E402
from pinterest_token import get_token_status, refresh_access_token, TokenError, TIMEOUT_SECONDS  # noqa: E402

THRESHOLD_DAYS = 7


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    try:
        status = get_token_status()
    except EnvLoaderError as e:
        print("【エラー】.envの読み込みに失敗しました（再認可が必要です）: %s" % e)
        sys.exit(2)

    if not status["access_token"] or not status["refresh_token"]:
        print("【エラー】アクセストークンまたはリフレッシュトークンが空です（再認可が必要です）。")
        sys.exit(2)

    refresh_days_left = status["refresh_days_left"]
    access_days_left = status["access_days_left"]

    if refresh_days_left is not None and refresh_days_left <= 0:
        print("【エラー】リフレッシュトークンが失効済みです（再認可が必要です）。")
        sys.exit(2)

    if access_days_left is None:
        print("【エラー】アクセストークンの有効期限が.envに記録されていません（再認可が必要です）。")
        sys.exit(2)

    if access_days_left >= THRESHOLD_DAYS:
        print("TOKEN_OK（アクセストークン残り約%.1f日）" % access_days_left)
        sys.exit(0)

    # 残り7日未満: リフレッシュを試みる
    try:
        new_status = refresh_access_token()
        print("TOKEN_REFRESHED（残り%.1f日を切ったためリフレッシュ成功・新しい有効期限まで約%.1f日）"
              % (access_days_left, new_status["access_days_left"]))
        sys.exit(0)
    except TokenError as e:
        print("【警告】アクセストークンの残りが%.1f日を切りましたが、リフレッシュに失敗しました: %s" % (access_days_left, e))
        sys.exit(1)


if __name__ == "__main__":
    main()
