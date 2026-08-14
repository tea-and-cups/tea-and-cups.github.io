# -*- coding: utf-8 -*-
r"""Pinterest v5 APIへの全HTTPリクエストの単一入口（T1・boards:write追加に伴う新設）。

他スクリプト（pinterest-list-boards.py・generate-pinterest-boards.py・
今後のピン投稿処理）はここを経由してAPIを呼ぶ。requestsライブラリではなく
urllib.request を使う（本プロジェクトの既存スクリプト群と統一）。

ボード操作ガード（重要）:
  リクエスト先パスが /v5/boards で始まり、かつHTTPメソッドがGET以外の場合、
  実際のリクエスト送信前に BoardWriteBlockedError を送出し処理を止める。
  boards:write はピン投稿（PATCH /v5/pins のboard_id変更）のためだけに保有し、
  ボードの作成・改名・削除はオーナーの手作業とする（D-0117関連）。

  この判定はここ1箇所に集約する。各呼び出し元へ同じ判定をコピーしないこと
  （判定が分散すると、将来の実装で片方だけ通ってしまうリスクがあるため）。
"""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

API_BASE_URL = "https://api.pinterest.com/v5"
DEFAULT_TIMEOUT_SECONDS = 15


class PinterestApiError(Exception):
    """Pinterest APIがエラーを返した場合に送出する例外。"""

    def __init__(self, status_code, body):
        self.status_code = status_code
        self.body = body
        super().__init__("Pinterest APIがHTTP %s を返しました: %s" % (status_code, body))


class BoardWriteBlockedError(Exception):
    """ボード操作（GET以外）を/v5/boardsに対して呼ぼうとした場合に送出する例外。"""
    pass


def _board_path(path):
    """pathが/v5/boards配下かどうかを判定する（クエリ文字列・完全URLどちらでも可）。"""
    parsed = urllib.parse.urlparse(path)
    # pathがフルURL(https://api.pinterest.com/v5/boards...)でも、
    # 相対パス(/v5/boards...)でも、parsed.pathに正規化される。
    return parsed.path.startswith("/v5/boards")


def request(method, path, access_token, body=None, extra_headers=None, timeout=DEFAULT_TIMEOUT_SECONDS):
    """Pinterest v5 APIへリクエストを送る唯一の入口。

    引数:
      method: "GET" / "POST" / "PATCH" など
      path: "/boards" のような /v5 以下の相対パス、または /v5/... の絶対パス
      access_token: Bearerトークン文字列
      body: dict の場合はJSONエンコードして送信する。Noneならボディなし
      extra_headers: 追加ヘッダーのdict（Content-Type等はbody指定時に自動付与）
      timeout: 秒

    戻り値: レスポンスをJSONデコードしたもの（dict/list）
    例外:
      BoardWriteBlockedError: /v5/boards へのGET以外のリクエストだった場合
        （実際の送信は行わない）
      PinterestApiError: HTTPエラー応答だった場合
      urllib.error.URLError: 通信自体に失敗した場合
    """
    if path.startswith("http://") or path.startswith("https://"):
        url = path
    else:
        if not path.startswith("/"):
            path = "/" + path
        if path.startswith("/v5/"):
            url = "https://api.pinterest.com" + path
        else:
            url = API_BASE_URL + path

    method = method.upper()

    # --- ボード操作ガード（送信前に判定・ここ1箇所のみ） ---
    if _board_path(url) and method != "GET":
        raise BoardWriteBlockedError(
            "boards:write はピン投稿のためだけに保有しており、"
            "ボードの作成・改名・削除はオーナーの手作業とする（D-0117関連）。"
            "ブロックされたリクエスト: %s %s" % (method, url)
        )

    data = None
    headers = {"Authorization": "Bearer %s" % access_token}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if extra_headers:
        headers.update(extra_headers)

    req = urllib.request.Request(url, data=data, method=method)
    for k, v in headers.items():
        req.add_header(k, v)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise PinterestApiError(e.code, error_body)


def fetch_all_pages(path, access_token, page_size=100, timeout=DEFAULT_TIMEOUT_SECONDS):
    """bookmarkページングのあるGETエンドポイントを全件取得する（items配列を結合して返す）。"""
    all_items = []
    bookmark = None
    while True:
        url = path + ("&" if "?" in path else "?") + "page_size=%d" % page_size
        if bookmark:
            url += "&bookmark=" + urllib.parse.quote(bookmark)
        data = request("GET", url, access_token, timeout=timeout)
        items = data.get("items", [])
        all_items.extend(items)
        bookmark = data.get("bookmark")
        if not bookmark:
            break
    return all_items


if __name__ == "__main__":
    print("このモジュールは他スクリプトからimportして使う想定です（単体実行は非対応）。", file=sys.stderr)
    sys.exit(1)
