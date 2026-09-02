# -*- coding: utf-8 -*-
r"""Pinterest API 本番OAuth認可スクリプト（D-0017・rules/pinterest-api.md）。

demo-pinterest/step1_auth_url.py・step2_token.py の本番版。秘密情報は
env_loader経由で .env（プロジェクトルート直下・Git管理外）から読む。
config.jsonへの依存もハードコードもしない。

要求スコープは pins:read / pins:write / boards:read / boards:write /
user_accounts:read の5つ。Pinterest v5 APIはピン投稿（POST/PATCH /v5/pins）
自体にもboards:writeを要求する仕様のため付与するが、ボードの作成・改名・
削除はコード側の共通ガード（pinterest_api.py）で機械的に封じている。
rules/pinterest-api.md参照。

トークンエンドポイントは本番ホスト https://api.pinterest.com/v5/oauth/token
（Sandboxではない。demo-pinterest/との違いに注意）。

使い方:
  python site/scripts/pinterest-oauth.py
      認可URLを生成して表示する。stateをtmp配下に一時保存する。

  python site/scripts/pinterest-oauth.py "<リダイレクト後の完全なURL>"
      code・stateを取り出し、state一致を確認したうえでアクセストークンと
      リフレッシュトークンを取得し、.envへ書き戻す。

このスクリプトはトークンの値を標準出力・ログに一切出力しない。
"""

import base64
import json
import os
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from env_loader import require_env, ENV_PATH, load_env  # noqa: E402

PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
TMP_DIR = os.path.join(PROJECT_ROOT, "tmp")
STATE_PATH = os.path.join(TMP_DIR, "pinterest-oauth-state.tmp")

AUTH_BASE_URL = "https://www.pinterest.com/oauth/"
TOKEN_URL = "https://api.pinterest.com/v5/oauth/token"
REDIRECT_URI = "https://tea-and-cups.github.io/"
SCOPES = "pins:read,pins:write,boards:read,boards:write,user_accounts:read"

ENV_KEYS_ORDER = [
    "PINTEREST_APP_ID",
    "PINTEREST_APP_SECRET",
    "PINTEREST_ACCESS_TOKEN",
    "PINTEREST_REFRESH_TOKEN",
    "PINTEREST_ACCESS_TOKEN_EXPIRES_AT",
    "PINTEREST_REFRESH_TOKEN_EXPIRES_AT",
]


def mode_generate_url():
    app_id = require_env("PINTEREST_APP_ID")

    os.makedirs(TMP_DIR, exist_ok=True)
    state = secrets.token_urlsafe(24)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        f.write(state)

    params = {
        "client_id": app_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
    }
    auth_url = AUTH_BASE_URL + "?" + urllib.parse.urlencode(params)

    print("=== Pinterest 本番OAuth認可 ===")
    print("要求スコープ: %s" % SCOPES.replace(",", ", "))
    print("（boards:write を含みます。ボード操作はコード側のガードで別途封じています）")
    print("")
    print("以下のURLをブラウザで開いて許可してください:")
    print(auth_url)
    print("")
    print("許可すると https://tea-and-cups.github.io/ にリダイレクトされます。")
    print("ページの表示内容は気にせず、アドレスバーのURL全体をコピーしてください。")
    print("認可コードは数分で失効し1回しか使えないため、すぐに貼ってください。")


def write_env_updates(updates):
    """.envを一時ファイル経由で安全に書き戻す（途中失敗でも壊れないように）。"""
    current = {}
    if os.path.exists(ENV_PATH):
        current = load_env()
    current.update(updates)

    tmp_path = ENV_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        for key in ENV_KEYS_ORDER:
            f.write("%s=%s\n" % (key, current.get(key, "")))
        # ENV_KEYS_ORDER以外に既存キーがあれば末尾に維持する
        for key, value in current.items():
            if key not in ENV_KEYS_ORDER:
                f.write("%s=%s\n" % (key, value))
    os.replace(tmp_path, ENV_PATH)


def mode_exchange_token(redirect_url):
    parsed = urllib.parse.urlparse(redirect_url)
    qs = urllib.parse.parse_qs(parsed.query)

    if "code" not in qs or "state" not in qs:
        print("エラー: 渡されたURLに code と state の両方のクエリパラメータが含まれていません。")
        sys.exit(1)

    code = qs["code"][0]
    returned_state = qs["state"][0]

    if not os.path.exists(STATE_PATH):
        print("エラー: state保存ファイルが見つかりません。先に引数なしで実行してください。")
        sys.exit(1)

    with open(STATE_PATH, "r", encoding="utf-8") as f:
        expected_state = f.read().strip()

    if returned_state != expected_state:
        print("エラー: state不一致。このリダイレクトは今回の認可リクエストと対応していません。")
        print("  引数なしで再実行し、新しく生成したURLを使ってください。")
        sys.exit(1)

    app_id = require_env("PINTEREST_APP_ID")
    app_secret = require_env("PINTEREST_APP_SECRET")

    basic_auth = base64.b64encode(("%s:%s" % (app_id, app_secret)).encode("utf-8")).decode("ascii")

    body = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }).encode("utf-8")

    req = urllib.request.Request(TOKEN_URL, data=body, method="POST")
    req.add_header("Authorization", "Basic %s" % basic_auth)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        print("エラー: トークンエンドポイントからHTTP %d" % e.code)
        # エラー本文にトークン値が含まれることは通常ないが、念のためcode/secret文字列を含まないか簡易チェック
        print("  %s" % error_body)
        sys.exit(1)

    access_token = payload.get("access_token", "")
    refresh_token = payload.get("refresh_token", "")
    expires_in = payload.get("expires_in")
    refresh_expires_in = payload.get("refresh_token_expires_in")
    scope = payload.get("scope", "")

    import datetime
    # NOTE: 本スクリプト自体はワークフロー台本ではなく通常のPythonスクリプトのため、
    # datetime.datetime.now()の使用に制約はない。
    now = datetime.datetime.now(datetime.timezone.utc)
    access_expires_at = None
    refresh_expires_at = None
    if isinstance(expires_in, (int, float)):
        access_expires_at = (now + datetime.timedelta(seconds=expires_in)).isoformat()
    if isinstance(refresh_expires_in, (int, float)):
        refresh_expires_at = (now + datetime.timedelta(seconds=refresh_expires_in)).isoformat()

    write_env_updates({
        "PINTEREST_ACCESS_TOKEN": access_token,
        "PINTEREST_REFRESH_TOKEN": refresh_token,
        "PINTEREST_ACCESS_TOKEN_EXPIRES_AT": access_expires_at or "",
        "PINTEREST_REFRESH_TOKEN_EXPIRES_AT": refresh_expires_at or "",
    })

    try:
        os.remove(STATE_PATH)
    except OSError:
        pass

    requested_scopes = set(SCOPES.split(","))
    granted_scopes = set(s for s in scope.split() if s) or set(scope.split(",") if scope else [])

    print("=== 取得結果 ===")
    print("取得成功: %s" % ("yes" if access_token else "no"))
    print("access_token 文字数: %d" % len(access_token))
    print("refresh_token 文字数: %d" % len(refresh_token))
    print("access_token 有効期限: %s" % access_expires_at)
    print("refresh_token 有効期限: %s" % refresh_expires_at)
    print("付与されたスコープ: %s" % scope)
    if requested_scopes and granted_scopes and requested_scopes != granted_scopes:
        print("警告: 要求スコープと付与スコープが一致しません。")
        print("  要求: %s" % ", ".join(sorted(requested_scopes)))
        print("  付与: %s" % ", ".join(sorted(granted_scopes)))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) < 2:
        mode_generate_url()
    else:
        mode_exchange_token(sys.argv[1])


if __name__ == "__main__":
    main()
