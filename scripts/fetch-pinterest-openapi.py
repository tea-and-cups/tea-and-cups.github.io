# -*- coding: utf-8 -*-
r"""Pinterest API v5 のOpenAPI仕様を取得し、必要箇所だけを抽出するスクリプト（常設・D-0017）。

背景: developers.pinterest.com はJavaScript描画のSPAでWebFetchでは読めない。
pinterest/api-description リポジトリがGitHub上でOpenAPI仕様を公開しているため、
raw.githubusercontent.com からダウンロードして抽出する。仕様ファイルは数MB規模
のため、ダウンロード後にファイル全体をReadツールで読むのではなく、このスクリプト
側で該当セクションだけを抽出して標準出力に出す。

保存先: C:\Claude\Tea_TeaCut\tmp\ 配下（site/配下には置かない）。
再確認のたびに同じ手順で使えるよう、使い捨てではなく常設スクリプトとする。

使い方:
    python site/scripts/fetch-pinterest-openapi.py            # ダウンロード＋全項目抽出
    python site/scripts/fetch-pinterest-openapi.py --keep     # tmp配下の仕様ファイルを削除せず残す
"""

import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP_DIR = os.path.join(ROOT, "tmp")

REPO = "pinterest/api-description"
CANDIDATE_PATHS = [
    ("main", "v5/openapi.yaml"),
    ("main", "v5/openapi.json"),
    ("master", "v5/openapi.yaml"),
    ("master", "v5/openapi.json"),
]

RAW_BASE = "https://raw.githubusercontent.com/{repo}/{branch}/{path}"
TREE_API = "https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1"


def http_get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "tea-and-cups-pinterest-fetch"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def try_download():
    for branch, path in CANDIDATE_PATHS:
        url = RAW_BASE.format(repo=REPO, branch=branch, path=path)
        try:
            data = http_get(url)
            print("[fetch] OK: %s (branch=%s, path=%s, %d bytes)" % (url, branch, path, len(data)))
            return data, path
        except urllib.error.HTTPError as e:
            print("[fetch] miss: %s -> HTTP %d" % (url, e.code))
        except Exception as e:
            print("[fetch] miss: %s -> %s" % (url, e))
    return None, None


def discover_via_tree():
    for branch in ("main", "master"):
        url = TREE_API.format(repo=REPO, branch=branch)
        try:
            data = http_get(url, headers={
                "User-Agent": "tea-and-cups-pinterest-fetch",
                "Accept": "application/vnd.github+json",
            })
            tree = json.loads(data.decode("utf-8"))
        except Exception as e:
            print("[tree] miss: %s -> %s" % (url, e))
            continue
        candidates = [
            item["path"] for item in tree.get("tree", [])
            if "v5" in item["path"] and item["path"].endswith((".yaml", ".yml", ".json"))
            and "openapi" in item["path"].lower()
        ]
        if candidates:
            print("[tree] branch=%s candidates: %s" % (branch, candidates))
            return branch, candidates
        print("[tree] branch=%s: v5 openapi候補ファイルが見つからない" % branch)
    return None, []


def load_yaml_or_json(raw_bytes, path):
    text = raw_bytes.decode("utf-8")
    if path.endswith(".json"):
        return json.loads(text)
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except ImportError:
        print("[warn] PyYAMLが無いため簡易パースは行わず、テキスト検索のみで抽出します。")
        return None


def find_by_pointer(doc, *keys):
    cur = doc
    for k in keys:
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(k)
        elif isinstance(cur, list) and isinstance(k, int):
            cur = cur[k]
        else:
            return None
    return cur


def extract_sections(doc, raw_text):
    print("\n===== OpenAPI仕様の抽出結果 =====")

    # (a) POST /v5/pins media_source
    print("\n--- (a) POST /v5/pins media_source ---")
    if doc:
        media_source = None
        for schema_name in ("media_source", "MediaSource", "PinMediaSource"):
            s = find_by_pointer(doc, "components", "schemas", schema_name)
            if s:
                media_source = s
                break
        if media_source:
            print(json.dumps(media_source, ensure_ascii=False, indent=2)[:4000])
        else:
            print("仕様書に記載なし（components.schemas内にmedia_source系スキーマが見つからない）")
    else:
        print("仕様書に記載なし（パーサ未使用のためテキスト抽出は非対応）")

    # (b) 画像制約
    print("\n--- (b) 画像の形式・サイズ・解像度の制約 ---")
    lowered = raw_text.lower()
    if doc:
        img_schema = None
        for schema_name in ("PinMediaSourceImageBase64", "PinMediaSourceImageURL"):
            s = find_by_pointer(doc, "components", "schemas", schema_name)
            if s:
                print("--- schema: %s ---" % schema_name)
                print(json.dumps(s, ensure_ascii=False, indent=2)[:2000])
                img_schema = s
        if img_schema is None:
            print("仕様書に記載なし（PinMediaSourceImage系スキーマが見つからない）")
    keywords = ["maximum size", "max size", "megapixel", "resolution", "aspect ratio", "file size"]
    hit_keywords = [kw for kw in keywords if kw in lowered]
    print("本文中の制約系キーワード出現: %s（該当なしは仕様書に記載なしとみなす）" % (hit_keywords or "なし"))

    # (c) PATCH /v5/pins/{pin_id}
    print("\n--- (c) PATCH /v5/pins/{pin_id} 更新可能フィールド ---")
    if doc:
        patch_op = find_by_pointer(doc, "paths", "/pins/{pin_id}", "patch")
        if patch_op:
            body_schema = find_by_pointer(patch_op, "requestBody", "content", "application/json", "schema")
            print(json.dumps(body_schema or patch_op, ensure_ascii=False, indent=2)[:4000])
        else:
            print("仕様書に記載なし（paths./pins/{pin_id}.patchが見つからない）")
    else:
        print("仕様書に記載なし（パーサ未使用）")

    # (d) GET /v5/boards レスポンスフィールド
    print("\n--- (d) GET /v5/boards レスポンスフィールド ---")
    if doc:
        get_op = find_by_pointer(doc, "paths", "/boards", "get")
        if get_op:
            resp_schema = find_by_pointer(get_op, "responses", "200", "content", "application/json", "schema")
            print(json.dumps(resp_schema or get_op, ensure_ascii=False, indent=2)[:4000])
        else:
            print("仕様書に記載なし（paths./boards.getが見つからない）")
    else:
        print("仕様書に記載なし（パーサ未使用）")

    # (e) リフレッシュトークンでの再発行
    print("\n--- (e) POST /v5/oauth/token リフレッシュ時のリクエスト形式 ---")
    if doc:
        token_op = find_by_pointer(doc, "paths", "/oauth/token", "post")
        if token_op:
            print(json.dumps(token_op, ensure_ascii=False, indent=2)[:4000])
        else:
            print("仕様書に記載なし（paths./oauth/token.postが見つからない）")
    else:
        print("仕様書に記載なし（パーサ未使用）")

    # (f) securitySchemes oauth2
    print("\n--- (f) securitySchemes.oauth2 (authorizationUrl/tokenUrl/scopes) ---")
    if doc:
        sec = find_by_pointer(doc, "components", "securitySchemes")
        if sec:
            print(json.dumps(sec, ensure_ascii=False, indent=2)[:4000])
        else:
            print("仕様書に記載なし（components.securitySchemesが見つからない）")
    else:
        print("仕様書に記載なし（パーサ未使用）")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    keep = "--keep" in sys.argv
    os.makedirs(TMP_DIR, exist_ok=True)

    data, path = try_download()
    if data is None:
        print("[fetch] mainブランチ・masterブランチとも既定パスで失敗。tree APIでファイル一覧を検索します。")
        branch, candidates = discover_via_tree()
        if not candidates:
            print("結論: 仕様ファイルを特定できなかった。手動確認が必要。")
            return
        for cand in candidates:
            url = RAW_BASE.format(repo=REPO, branch=branch, path=cand)
            try:
                data = http_get(url)
                path = cand
                print("[fetch] OK: %s (%d bytes)" % (url, len(data)))
                break
            except Exception as e:
                print("[fetch] miss: %s -> %s" % (url, e))
        if data is None:
            print("結論: tree APIで候補は見つかったがダウンロードに失敗した。")
            return

    local_path = os.path.join(TMP_DIR, "pinterest-openapi-v5" + os.path.splitext(path)[1])
    with open(local_path, "wb") as f:
        f.write(data)
    print("[save] %s" % local_path)

    doc = load_yaml_or_json(data, path)
    raw_text = data.decode("utf-8", errors="replace")

    extract_sections(doc, raw_text)

    if keep:
        print("\n[cleanup] --keep指定のため %s は残します。" % local_path)
    else:
        try:
            os.remove(local_path)
            print("\n[cleanup] %s を削除しました。" % local_path)
        except Exception as e:
            print("\n[cleanup] 削除に失敗: %s" % e)


if __name__ == "__main__":
    main()
