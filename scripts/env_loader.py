# -*- coding: utf-8 -*-
r"""プロジェクトルート直下の .env を読み込む素朴なローダー（D-0043）。

外部ライブラリに依存しない。.env はGit管理外のプロジェクトルート
（C:\Claude\Tea_TeaCut\.env）に置く前提（D-0043・ルート非Git設計）。

このモジュールは値を標準出力に表示する機能を持たない。他スクリプトから
`from env_loader import get_env, require_env` の形でimportして使う想定。

沈黙する失敗を作らないため、.env が存在しない・要求したキーが空文字の場合は
明確な例外(EnvLoaderError)を送出する。呼び出し側で握りつぶさないこと。
"""

import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")


class EnvLoaderError(Exception):
    """.env の読み込み・キー取得に失敗したときに送出する例外。"""
    pass


def _parse_env_file(path):
    """.envを1行ずつ素朴に解析する。KEY=VALUE形式のみ対応。

    - 空行・'#'始まりの行はコメントとして無視する
    - 値の前後の引用符（'...' または "..."）は1組だけ剥がす
    - '=' を含まない行は無視する（沈黙するが、これは書式エラーというより
      コメント的な行を許容する意図。KEY自体が期待通りに存在しない場合は
      呼び出し側のrequire_env側で例外になる）
    """
    values = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            values[key] = value
    return values


def load_env(path=None):
    """.envを読み込み、dictとして返す。存在しなければEnvLoaderErrorを送出する。"""
    target = path or ENV_PATH
    if not os.path.exists(target):
        raise EnvLoaderError(
            ".env が見つかりません（想定パス: %s）。"
            "site/scripts/env_loader.py の呼び出し元を確認してください。" % target
        )
    return _parse_env_file(target)


def get_env(key, default=None, path=None):
    """.envからキーを取得する。キーが存在しない場合はdefaultを返す（空文字は許容）。"""
    values = load_env(path)
    return values.get(key, default)


def require_env(key, path=None):
    """.envからキーを取得する。キーが存在しない、または値が空文字の場合は例外を送出する。"""
    values = load_env(path)
    value = values.get(key)
    if value is None or value == "":
        raise EnvLoaderError(
            ".env のキー '%s' が存在しないか空です。値を設定してから再実行してください。" % key
        )
    return value


def require_env_multi(*keys, path=None):
    """複数キーをまとめて必須取得する。1つでも欠けていれば例外を送出する。"""
    values = load_env(path)
    missing = [k for k in keys if not values.get(k)]
    if missing:
        raise EnvLoaderError(
            ".env に次のキーが存在しないか空です: %s" % ", ".join(missing)
        )
    return {k: values[k] for k in keys}
