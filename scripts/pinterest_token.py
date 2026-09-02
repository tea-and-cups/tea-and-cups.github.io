# -*- coding: utf-8 -*-
r"""Pinterestアクセストークンの残り日数計算とリフレッシュ（D-0017・rules/pinterest-api.md）。

他スクリプトからimportして使う想定（アンダースコア名）。

役割:
  - .env から現在のトークンと有効期限を読む
  - 残り日数を計算する
  - 残り7日を切っていればリフレッシュを実行し、新しいトークンと期限を .env へ書き戻す
  - 書き戻しは一時ファイル経由のatomic置換（.envが壊れて再認可が必要になることを防ぐ）
  - ネットワーク通信のタイムアウトは15秒。失敗時は例外を握りつぶさず呼び出し元に伝える
"""

import base64
import datetime
import json
import os
import sys
import urllib.error
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
from env_loader import load_env, ENV_PATH, EnvLoaderError  # noqa: E402

TOKEN_URL = "https://api.pinterest.com/v5/oauth/token"
TIMEOUT_SECONDS = 15

ENV_KEYS_ORDER = [
    "PINTEREST_APP_ID",
    "PINTEREST_APP_SECRET",
    "PINTEREST_ACCESS_TOKEN",
    "PINTEREST_REFRESH_TOKEN",
    "PINTEREST_ACCESS_TOKEN_EXPIRES_AT",
    "PINTEREST_REFRESH_TOKEN_EXPIRES_AT",
]


class TokenError(Exception):
    """トークン状態の取得・リフレッシュに失敗したときに送出する例外。"""
    pass


def _parse_iso(value):
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value)
    except ValueError:
        return None


def get_token_status():
    """.envの現在状態を読み、各種残り日数を含む辞書を返す。

    戻り値:
      {
        "access_token": str, "refresh_token": str,
        "access_expires_at": datetime|None, "refresh_expires_at": datetime|None,
        "access_days_left": float|None, "refresh_days_left": float|None,
      }
    .env が無い・必須キーが空の場合は EnvLoaderError をそのまま送出する（呼び出し元で判定させる）。
    """
    values = load_env()
    access_token = values.get("PINTEREST_ACCESS_TOKEN", "")
    refresh_token = values.get("PINTEREST_REFRESH_TOKEN", "")
    access_expires_at = _parse_iso(values.get("PINTEREST_ACCESS_TOKEN_EXPIRES_AT"))
    refresh_expires_at = _parse_iso(values.get("PINTEREST_REFRESH_TOKEN_EXPIRES_AT"))

    now = datetime.datetime.now(datetime.timezone.utc)
    access_days_left = None
    refresh_days_left = None
    if access_expires_at is not None:
        access_days_left = (access_expires_at - now).total_seconds() / 86400.0
    if refresh_expires_at is not None:
        refresh_days_left = (refresh_expires_at - now).total_seconds() / 86400.0

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "access_expires_at": access_expires_at,
        "refresh_expires_at": refresh_expires_at,
        "access_days_left": access_days_left,
        "refresh_days_left": refresh_days_left,
    }


def refresh_access_token():
    """リフレッシュトークンで新しいアクセストークンを取得し、.envへ書き戻す。

    成功時は get_token_status() 相当の新しい状態辞書を返す。
    ネットワークエラー・APIエラーはTokenErrorとして送出する（握りつぶさない）。
    """
    try:
        values = load_env()
        app_id = values.get("PINTEREST_APP_ID", "")
        app_secret = values.get("PINTEREST_APP_SECRET", "")
        refresh_token = values.get("PINTEREST_REFRESH_TOKEN", "")
    except EnvLoaderError as e:
        raise TokenError(".env読み込みに失敗しました: %s" % e)

    if not app_id or not app_secret or not refresh_token:
        raise TokenError("PINTEREST_APP_ID / PINTEREST_APP_SECRET / PINTEREST_REFRESH_TOKEN のいずれかが空です。")

    basic_auth = base64.b64encode(("%s:%s" % (app_id, app_secret)).encode("utf-8")).decode("ascii")
    body = ("grant_type=refresh_token&refresh_token=%s" % refresh_token).encode("utf-8")

    req = urllib.request.Request(TOKEN_URL, data=body, method="POST")
    req.add_header("Authorization", "Basic %s" % basic_auth)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise TokenError("トークンリフレッシュAPIがHTTP %d を返しました: %s" % (e.code, error_body))
    except urllib.error.URLError as e:
        raise TokenError("トークンリフレッシュAPIへの通信に失敗しました: %s" % e)

    access_token = payload.get("access_token", "")
    new_refresh_token = payload.get("refresh_token") or refresh_token
    expires_in = payload.get("expires_in")
    refresh_expires_in = payload.get("refresh_token_expires_in")

    if not access_token:
        raise TokenError("リフレッシュ応答にaccess_tokenが含まれていません。")

    now = datetime.datetime.now(datetime.timezone.utc)
    access_expires_at = None
    refresh_expires_at = None
    if isinstance(expires_in, (int, float)):
        access_expires_at = (now + datetime.timedelta(seconds=expires_in)).isoformat()
    if isinstance(refresh_expires_in, (int, float)):
        refresh_expires_at = (now + datetime.timedelta(seconds=refresh_expires_in)).isoformat()

    _write_env_updates({
        "PINTEREST_ACCESS_TOKEN": access_token,
        "PINTEREST_REFRESH_TOKEN": new_refresh_token,
        "PINTEREST_ACCESS_TOKEN_EXPIRES_AT": access_expires_at or "",
        "PINTEREST_REFRESH_TOKEN_EXPIRES_AT": refresh_expires_at or values.get("PINTEREST_REFRESH_TOKEN_EXPIRES_AT", ""),
    })

    return get_token_status()


def _write_env_updates(updates):
    """.envを一時ファイル経由で安全に書き戻す（atomic replace）。"""
    current = {}
    if os.path.exists(ENV_PATH):
        current = load_env()
    current.update(updates)

    tmp_path = ENV_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        for key in ENV_KEYS_ORDER:
            f.write("%s=%s\n" % (key, current.get(key, "")))
        for key, value in current.items():
            if key not in ENV_KEYS_ORDER:
                f.write("%s=%s\n" % (key, value))
    os.replace(tmp_path, ENV_PATH)


def ensure_fresh(threshold_days=7):
    """残りaccess token日数がthreshold_days未満ならリフレッシュする。

    リフレッシュトークン自体が失効済み(refresh_days_left <= 0)の場合はTokenErrorを送出する。
    """
    status = get_token_status()
    if status["refresh_days_left"] is not None and status["refresh_days_left"] <= 0:
        raise TokenError("リフレッシュトークンが失効済みです。再認可（pinterest-oauth.py）が必要です。")

    if status["access_days_left"] is None or status["access_days_left"] < threshold_days:
        return refresh_access_token()
    return status
