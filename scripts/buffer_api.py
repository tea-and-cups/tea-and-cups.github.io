# -*- coding: utf-8 -*-
r"""Buffer 現行GraphQL API（https://api.buffer.com）への単一入口（内部ライブラリ）。

直接実行しない。他スクリプトから `from buffer_api import graphql` の形で使う。

前提（公式ドキュメント https://developers.buffer.com/ で確認・2026-08-30）:
  - エンドポイントは https://api.buffer.com（POST・単一URL）
  - 認証は個人APIキーの Bearer 方式（`Authorization: Bearer <key>`）。
    OAuthのリフレッシュトークンに相当する仕組みは無く、キーは
    https://publish.buffer.com/settings/api で発行する。
  - 旧REST API（api.bufferapp.com/1/）は本モジュールの対象外。

【操作ガードについて】
送信するGraphQL文字列を送信前に検査し、許可した操作以外は例外で止める。
許可するのは参照系クエリ（ALLOWED_QUERY_FIELDS）と createPost のみで、
投稿の更新・削除に相当する editPost / deletePost 等は許可しない。
**この判定は本ファイル1箇所に集約する。呼び出し元へコピーしないこと。**
（誤って破壊的操作を送る経路を最初から作らないための構造的な制約であり、
呼び出し元の「気をつけて書く」に依存させない）

このモジュールはAPIキーの値を標準出力へ出す機能を持たない。
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from env_loader import require_env  # noqa: E402

ENDPOINT = "https://api.buffer.com"
TIMEOUT_SECONDS = 15

# 参照系（読み取り専用）の root Query フィールド。
# 正本: https://developers.buffer.com/reference.html の Query 一覧。
ALLOWED_QUERY_FIELDS = frozenset([
    "account",
    "channel",
    "channels",
    "post",
    "posts",
    "aggregatedPostMetrics",
    "dailyPostingLimits",
    "postTemplate",
    "postTemplates",
    "ideaGroups",
    "ideas",
])

# 許可する root Mutation フィールドはこれだけ。
# reference.html には editPost / deletePost / movePostInQueue 等も存在するが、
# 本プロジェクトからは意図的に到達させない。
ALLOWED_MUTATION_FIELDS = frozenset(["createPost"])


class BufferApiError(Exception):
    """Buffer APIの呼び出しに失敗したときに送出する（HTTPエラー・GraphQLエラー）。"""
    pass


class BufferGuardError(Exception):
    """許可していないGraphQL操作を送ろうとしたときに送出する（送信前に止める）。"""
    pass


def _strip_noise(document):
    """ガード判定の前処理。コメントと文字列リテラルを空白へ潰す。

    文字列の中に 'mutation' や 'deletePost' が書かれていても判定が
    引きずられないようにするため、先に無害化する。
    """
    out = []
    i = 0
    n = len(document)
    while i < n:
        ch = document[i]
        if ch == "#":
            while i < n and document[i] != "\n":
                i += 1
            continue
        if document.startswith('"""', i):
            end = document.find('"""', i + 3)
            i = n if end == -1 else end + 3
            out.append(" ")
            continue
        if ch == '"':
            i += 1
            while i < n and document[i] != '"':
                if document[i] == "\\":
                    i += 1
                i += 1
            i += 1
            out.append(" ")
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _root_selection(cleaned, brace_index):
    """`{` の位置から対応する `}` までを取り出し、深さ1のフィールド名を返す。"""
    depth = 0
    start = brace_index + 1
    end = None
    parts = []
    i = brace_index
    n = len(cleaned)
    while i < n:
        ch = cleaned[i]
        if ch == "{":
            depth += 1
            if depth == 1:
                start = i + 1
            elif depth == 2:
                parts.append(cleaned[start:i])
        elif ch == "}":
            depth -= 1
            if depth == 1:
                start = i + 1
            elif depth == 0:
                parts.append(cleaned[start:i])
                end = i
                break
        i += 1
    if end is None:
        raise BufferGuardError("GraphQL文字列の波括弧が閉じていません。")

    # 深さ1に現れるトークンのうち、引数リスト `( ... )` を除いた部分から
    # フィールド名（エイリアスがあれば `:` の右側）を拾う。
    flat = " ".join(parts)
    flat = re.sub(r"\([^()]*\)", " ", flat)
    while "(" in flat:
        reduced = re.sub(r"\([^()]*\)", " ", flat)
        if reduced == flat:
            break
        flat = reduced

    fields = []
    for token in re.finditer(r"\.\.\.\s*(?:on\s+)?\w*|[A-Za-z_][A-Za-z0-9_]*\s*:?", flat):
        text = token.group(0).strip()
        if text.startswith("..."):
            fields.append("...")
            continue
        if text.endswith(":"):
            # エイリアス。実フィールド名は次のトークンなので読み飛ばす。
            continue
        fields.append(text)
    return fields, end


def assert_operation_allowed(document):
    """送信予定のGraphQL文字列を検査する。許可外なら BufferGuardError を送出する。

    許可条件:
      - query（無名の `{ ... }` を含む）の root フィールドがすべて
        ALLOWED_QUERY_FIELDS に含まれること
      - mutation の root フィールドがすべて ALLOWED_MUTATION_FIELDS
        （= createPost のみ）に含まれること
      - subscription は一切許可しない
      - mutation の root にフラグメント展開（`...`）を書かない
        （中身を静的に検証できないため）
      - `on Mutation` のフラグメント定義を含まないこと
    """
    if not document or not document.strip():
        raise BufferGuardError("空のGraphQL文字列は送信できません。")

    cleaned = _strip_noise(document)

    if re.search(r"\bsubscription\b", cleaned):
        raise BufferGuardError("subscription は許可していません。")
    if re.search(r"\bfragment\b[^{]*\bon\s+Mutation\b", cleaned):
        raise BufferGuardError(
            "Mutation 型へのフラグメント定義は許可していません（操作名を静的に検証できないため）。"
        )

    operations = []  # (種別, `{` の位置)
    for match in re.finditer(r"\b(query|mutation)\b", cleaned):
        brace = cleaned.find("{", match.end())
        if brace == -1:
            raise BufferGuardError("操作定義に選択セットがありません。")
        operations.append((match.group(1), brace))

    if not operations:
        # 無名クエリ（ショートハンド）。先頭の `{` を選択セットとみなす。
        brace = cleaned.find("{")
        if brace == -1:
            raise BufferGuardError("GraphQLの操作定義が見つかりません。")
        # `fragment X on Y { ... }` だけの文書は操作ではないので拒否する。
        if re.match(r"\s*fragment\b", cleaned):
            raise BufferGuardError("フラグメント定義のみの文書は送信できません。")
        operations.append(("query", brace))

    for kind, brace in operations:
        fields, _ = _root_selection(cleaned, brace)
        if not fields:
            raise BufferGuardError("%s の root フィールドを特定できませんでした。" % kind)
        allowed = ALLOWED_MUTATION_FIELDS if kind == "mutation" else ALLOWED_QUERY_FIELDS
        for field in fields:
            if field == "...":
                if kind == "mutation":
                    raise BufferGuardError(
                        "mutation の root にフラグメント展開は書けません（操作名を静的に検証できないため）。"
                    )
                continue
            if field not in allowed:
                raise BufferGuardError(
                    "許可していない %s 操作です: '%s'（許可: %s）"
                    % (kind, field, ", ".join(sorted(allowed)))
                )
    return True


def graphql(document, variables=None, operation_name=None):
    """Buffer GraphQL APIへPOSTし、`data` を返す。

    失敗（HTTPエラー・GraphQLの errors）は握りつぶさず例外で呼び出し元へ伝える。
    """
    assert_operation_allowed(document)

    payload = {"query": document}
    if variables:
        payload["variables"] = variables
    if operation_name:
        payload["operationName"] = operation_name

    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer %s" % require_env("BUFFER_API_KEY"),
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:2000]
        raise BufferApiError("Buffer API がHTTP %s を返しました: %s" % (exc.code, detail))
    except urllib.error.URLError as exc:
        raise BufferApiError("Buffer API へ接続できません: %s" % exc.reason)

    try:
        parsed = json.loads(body)
    except ValueError:
        raise BufferApiError("Buffer API の応答をJSONとして解析できません: %s" % body[:2000])

    if parsed.get("errors"):
        raise BufferApiError(
            "Buffer API がGraphQLエラーを返しました: %s"
            % json.dumps(parsed["errors"], ensure_ascii=False)[:2000]
        )
    if "data" not in parsed:
        raise BufferApiError("Buffer API の応答に data がありません: %s" % body[:2000])
    return parsed["data"]


if __name__ == "__main__":
    sys.stderr.write(
        "buffer_api.py は内部ライブラリです。直接実行せず、import して使ってください。\n"
    )
    sys.exit(1)
