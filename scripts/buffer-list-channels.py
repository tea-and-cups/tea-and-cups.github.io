# -*- coding: utf-8 -*-
r"""Buffer に連携済みのチャンネル一覧を表示する（引数なし・読み取り専用）。

`python site/scripts/buffer-list-channels.py`

やること:
  1. account { organizations { id name } } で組織IDを取得する
  2. 各組織について channels(input:{organizationId}) を引き、
     チャンネルID・サービス名・アカウント名を表示する

ファイルへの書き込みは一切行わない（チャンネルIDの保存先はラウンド2で決める）。
送信は site/scripts/buffer_api.py の graphql() 経由のみで、
参照系クエリ以外は同ファイルのガードが送信前に止める。
"""

import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from buffer_api import graphql, BufferApiError, BufferGuardError  # noqa: E402
from env_loader import EnvLoaderError  # noqa: E402

ORGANIZATIONS_QUERY = """
query GetOrganizations {
  account {
    id
    organizations {
      id
      name
    }
  }
}
"""

CHANNELS_QUERY = """
query GetChannels($organizationId: OrganizationId!) {
  channels(input: { organizationId: $organizationId }) {
    id
    name
    displayName
    service
    serviceId
    isDisconnected
    isQueuePaused
  }
}
"""

# 疎通確認で存在を確かめたいサービス（小文字で比較する）。
EXPECTED_SERVICES = ("twitter", "instagram", "threads")


def main():
    print("=== 送信したGraphQLクエリ（1本目・組織一覧） ===")
    print(ORGANIZATIONS_QUERY.strip())
    print()

    data = graphql(ORGANIZATIONS_QUERY)
    account = data.get("account") or {}
    organizations = account.get("organizations") or []
    if not organizations:
        print("組織が0件でした。Bufferアカウントの状態を確認してください。")
        return 1

    print("=== 組織一覧 ===")
    for org in organizations:
        print("  organizationId=%s  name=%s" % (org.get("id"), org.get("name")))
    print()

    print("=== 送信したGraphQLクエリ（2本目・チャンネル一覧） ===")
    print(CHANNELS_QUERY.strip())
    print('  variables: {"organizationId": "<上記の組織ID>"}')
    print()

    all_channels = []
    for org in organizations:
        org_id = org.get("id")
        channels = graphql(CHANNELS_QUERY, {"organizationId": org_id}).get("channels") or []
        print("=== チャンネル一覧（organizationId=%s） ===" % org_id)
        if not channels:
            print("  （0件）")
        for ch in channels:
            print(
                "  channelId=%s  service=%s  name=%s  displayName=%s  disconnected=%s  queuePaused=%s"
                % (
                    ch.get("id"),
                    ch.get("service"),
                    ch.get("name"),
                    ch.get("displayName"),
                    ch.get("isDisconnected"),
                    ch.get("isQueuePaused"),
                )
            )
            all_channels.append(ch)
        print()

    found = {str(ch.get("service") or "").lower() for ch in all_channels}
    print("=== 期待サービスの充足確認 ===")
    missing = []
    for service in EXPECTED_SERVICES:
        ok = service in found
        print("  %-10s : %s" % (service, "取得できた" if ok else "見つからない"))
        if not ok:
            missing.append(service)
    print("  合計チャンネル数: %d" % len(all_channels))

    if missing:
        print()
        print(
            "未取得のサービスがあります: %s "
            "（Buffer側の連携状況、またはサービス名の表記を確認してください）" % ", ".join(missing)
        )
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (BufferApiError, BufferGuardError, EnvLoaderError) as exc:
        sys.stderr.write("エラー: %s\n" % exc)
        sys.exit(1)
