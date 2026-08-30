# -*- coding: utf-8 -*-
r"""Buffer に連携済みのチャンネル一覧を表示する（読み取り専用）。

`python site/scripts/buffer-list-channels.py`          … 表示のみ（ファイルを書かない）
`python site/scripts/buffer-list-channels.py --save`   … 表示に加えて台帳を書き出す

やること:
  1. account { organizations { id name } } で組織IDを取得する
  2. 各組織について channels(input:{organizationId}) を引き、
     チャンネルID・サービス名・アカウント名を表示する
  3. --save を付けたときだけ data/buffer-channels.tsv を生成する

--save について:
  post-pins-to-buffer.py はチャンネルIDをAPIから毎回引かず、この台帳から読む
  （投稿のたびに参照系クエリを消費しないため。Bufferのレート制限は24時間250
  リクエスト・https://developers.buffer.com/guides/api-limits.html）。
  書式は1行1チャンネルのタブ区切りで、列は service / channel_id / name。
  1行目はヘッダー。**引数なしの挙動は従来どおりで、ファイルは一切書かない。**

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

ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
CHANNELS_TSV_PATH = os.path.join(ROOT, "data", "buffer-channels.tsv")
CHANNELS_TSV_HEADER = ("service", "channel_id", "name")


def save_channels_tsv(channels, path=CHANNELS_TSV_PATH):
    """チャンネル一覧を data/buffer-channels.tsv へ書き出す。戻り値は書いた行数。

    service / channel_id / name のどれかが空のチャンネルは書かない
    （読み手が「3サービス揃っている」と誤認する行を作らないため）。
    """
    rows = []
    for ch in channels:
        service = str(ch.get("service") or "").strip().lower()
        channel_id = str(ch.get("id") or "").strip()
        name = str(ch.get("name") or ch.get("displayName") or "").strip()
        if not service or not channel_id or not name:
            continue
        rows.append((service, channel_id, name))
    rows.sort()

    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(CHANNELS_TSV_HEADER) + "\n")
        for row in rows:
            f.write("\t".join(row) + "\n")
    return len(rows)


def main(save=False):
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

    if save:
        written = save_channels_tsv(all_channels)
        print()
        print("=== 台帳の書き出し（--save） ===")
        print("  %s へ %d 件（列: %s）"
              % (CHANNELS_TSV_PATH, written, " / ".join(CHANNELS_TSV_HEADER)))
    return 0


def parse_args(argv):
    """受け付ける引数は --save だけ。それ以外は使い方を出して None を返す。"""
    save = False
    for arg in argv:
        if arg == "--save":
            save = True
        else:
            sys.stderr.write(
                "不明な引数です: %s\n"
                "使い方: python site/scripts/buffer-list-channels.py [--save]\n" % arg
            )
            return None
    return save


if __name__ == "__main__":
    _save = parse_args(sys.argv[1:])
    if _save is None:
        sys.exit(2)
    try:
        sys.exit(main(save=_save))
    except (BufferApiError, BufferGuardError, EnvLoaderError) as exc:
        sys.stderr.write("エラー: %s\n" % exc)
        sys.exit(1)
