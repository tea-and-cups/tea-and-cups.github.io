# -*- coding: utf-8 -*-
r"""Growth Agent 用の外部数値 read-only ブローカー（GA4 / GSC / Buffer の参照のみ・親スクリプト非変更）。

Growth Agent（別セッションのサブ運用）が外部の数値を取得するときの唯一の入口。
Codex からシェル実行される前提で、標準出力に契約JSONを1個だけ出す。

方針:
  - 読み取り専用。書き込み系の引数・API・GraphQL mutation は一切持たない。
  - 呼べる操作は ALLOWED_OPERATIONS に列挙した固定クエリのみ。許可外は exit 1。
  - パラメータ範囲外（lookback-days 1..90 / limit 1..100 以外）は丸めず exit 1。
    丸めると Growth Agent 側が「要求と結果の差」に気づけなくなるため。
  - data/google-token.json は読むだけ。refresh はメモリ内のみで、ファイルへ書き戻さない
    （書き戻しは親スクリプト fetch-ga4-metrics.py の責務。ここは触らない）。
  - 出力予定の文字列は emit() 内の assert_no_secrets() を必ず通す。資格情報の実値が
    混ざっていたらマスクせず即停止し、一致文字列そのものは出力しない。

使い方:
  python site/scripts/growth-metrics.py ga4 --operation ga4.daily_traffic --lookback-days 7
  python site/scripts/growth-metrics.py gsc --operation gsc.search_analytics --lookback-days 28 --limit 28
  python site/scripts/growth-metrics.py buffer --operation buffer.account

終了コード: 0=正常（status ok）/ 1=エラー（status error・許可外・範囲外・secretガード作動）
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
TOKEN_PATH = os.path.join(PROJECT_ROOT, "data", "google-token.json")

if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

SCHEMA_VERSION = 1

GA4_PROPERTY_ID = "547119508"  # 「琥珀時間」・親スクリプト fetch-ga4-metrics.py と同一
GA4_SOURCE = "google_analytics_data_api_v1beta"
GA4_ENTITY_ID = "properties/%s" % GA4_PROPERTY_ID
GA4_METRICS = ("sessions", "activeUsers", "screenPageViews")

# GSC（Search Console）・親スクリプト check-gsc-status.py の SITE_URL と同一。
# URLプレフィックス型プロパティの登録文字列（末尾スラッシュあり）。
GSC_SITE_URL = "https://kohaku-jikan.com/"
GSC_SOURCE = "google_search_console_searchanalytics_v1"
GSC_ENTITY_ID = GSC_SITE_URL
# searchanalytics.query が date 次元で返す指標。clicks/impressions は整数、
# ctr/position は小数として格納する。
GSC_INT_METRICS = ("clicks", "impressions")
GSC_FLOAT_METRICS = ("ctr", "position")

BUFFER_SOURCE = "buffer_graphql"

LOOKBACK_MIN, LOOKBACK_MAX = 1, 90
LIMIT_MIN, LIMIT_MAX = 1, 100
DEFAULT_LOOKBACK_DAYS = 7

# observe_buffer_readonly.py の ACCOUNT_QUERY と同一（読み取り専用・変数なし・1コール）。
BUFFER_ACCOUNT_QUERY = """
query BufferObservationAccount {
  account {
    id
    organizations { id name }
  }
}
"""

# Buffer 側で「呼んでよい read クエリ」の明示リスト。buffer_api.assert_operation_allowed()
# とは別に、broker 自身がもう一段チェックする（二重チェック）。
BUFFER_READ_ALLOWED = frozenset(["BufferObservationAccount"])


class BrokerError(Exception):
    """許可外操作・範囲外パラメータ・取得失敗をまとめて表す。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class SecretLeak(Exception):
    """出力予定の文字列に資格情報の実値が混ざっていたときに送出する。"""


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


# --- secret ガード -----------------------------------------------------------

_ISO_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]?\d{0,2}:?\d{0,2}")
_MIN_SECRET_LEN = 12


def _collect_secret_values() -> list[str]:
    """出力に現れてはいけない資格情報の実値を集める。

    - .env の値のうち、長さ十分でISO日時ではないもの（トークン・シークレット類）
    - data/google-token.json の token / refresh_token / client_secret の実値
    失敗しても握りつぶさず、取れた分だけで検査する（取得失敗自体は上位で扱う）。
    """
    values: list[str] = []

    try:
        from env_loader import load_env

        for raw in load_env().values():
            if not isinstance(raw, str):
                continue
            candidate = raw.strip()
            if len(candidate) < _MIN_SECRET_LEN:
                continue
            if _ISO_DATETIME_RE.match(candidate):
                continue
            values.append(candidate)
    except Exception:
        pass

    try:
        with open(TOKEN_PATH, "r", encoding="utf-8") as handle:
            token = json.load(handle)
        for key in ("token", "refresh_token", "client_secret"):
            candidate = token.get(key)
            if isinstance(candidate, str) and len(candidate) >= _MIN_SECRET_LEN:
                values.append(candidate.strip())
    except Exception:
        pass

    # 重複排除（順序は問わない）
    return sorted(set(v for v in values if v))


def assert_no_secrets(text: str) -> None:
    """text に資格情報の実値が部分一致で含まれていたら SecretLeak を送出する。

    例外メッセージには一致した文字列そのものを載せない（漏洩経路を作らないため）。
    """
    for secret in _collect_secret_values():
        if secret and secret in text:
            raise SecretLeak(
                "potential credential material detected in the output payload; aborting"
            )


# --- 出力 contract ---------------------------------------------------------


def _base_payload(service: str, operation: str, params: dict) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "service": service,
        "operation": operation,
        "status": "ok",
        "generated_at": iso_now(),
        "params": params,
        "coverage": {"state": "unknown", "reason": ""},
        "warnings": [],
        "data": {"series": [], "snapshot": {}},
    }


def emit(payload: dict, exit_code: int) -> None:
    """標準出力へ契約JSONを1個だけ出して終了する。唯一の出力関門。

    - assert_no_secrets() を通してから出す。
    - secretガード作動時は、資格情報を含まない固定のエラーJSONを1個だけ出して exit 1。
    - 例外経路もすべてこの関数を通す（生文字列が出るのを防ぐ）。
    """
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    try:
        assert_no_secrets(text)
    except SecretLeak:
        safe = {
            "schema_version": SCHEMA_VERSION,
            "service": payload.get("service"),
            "operation": payload.get("operation"),
            "status": "error",
            "generated_at": iso_now(),
            "params": {},
            "coverage": {
                "state": "unknown",
                "reason": "aborted before coverage could be evaluated",
            },
            "warnings": [],
            "data": {"series": [], "snapshot": {}},
            "error": {
                "code": "secret_guard_tripped",
                "message": (
                    "potential credential material detected in output; "
                    "emission aborted without disclosing the match"
                ),
            },
        }
        sys.stdout.write(json.dumps(safe, ensure_ascii=False, sort_keys=True) + "\n")
        raise SystemExit(1)
    sys.stdout.write(text + "\n")
    raise SystemExit(exit_code)


def emit_error(service, operation, params, code: str, message: str) -> None:
    payload = _base_payload(service or None, operation or None, params or {})
    payload["status"] = "error"
    payload["coverage"]["reason"] = "not evaluated because the request failed before fetch"
    payload["error"] = {"code": code, "message": message}
    emit(payload, 1)


# --- パラメータ検証 -------------------------------------------------------


def _int_in_range(label: str, value, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise BrokerError("param_out_of_range", "%s must be an integer" % label)
    if parsed < low or parsed > high:
        raise BrokerError(
            "param_out_of_range",
            "%s must be within %d..%d (got %s); values are not rounded" % (label, low, high, value),
        )
    return parsed


# --- GA4 ------------------------------------------------------------------


def _format_ga4_date(raw) -> str | None:
    text = str(raw) if raw is not None else ""
    if len(text) == 8 and text.isdigit():
        return "%s-%s-%s" % (text[:4], text[4:6], text[6:])
    return None


def run_ga4_daily_traffic(params: dict) -> dict:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    lookback_days = params["lookback_days"]
    limit = params["limit"]

    end_date = dt.date.today()
    start_date = end_date - dt.timedelta(days=lookback_days - 1)
    params["period"] = {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()}

    if not os.path.exists(TOKEN_PATH):
        raise BrokerError("token_missing", "data/google-token.json not found")

    try:
        creds = Credentials.from_authorized_user_file(TOKEN_PATH)
    except (OSError, ValueError) as exc:
        raise BrokerError("token_unreadable", "could not load google-token.json: %s" % exc)

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())  # メモリ内のみ。ファイルへ書き戻さない。
            except Exception as exc:  # noqa: BLE001 - refresh 失敗は人手対応が必要
                raise BrokerError("token_refresh_failed", "OAuth refresh failed: %s" % exc)
        else:
            raise BrokerError("token_invalid", "stored credential is not usable and cannot be refreshed")

    body = {
        "dateRanges": [{"startDate": params["period"]["start_date"], "endDate": params["period"]["end_date"]}],
        "dimensions": [{"name": "date"}],
        "metrics": [{"name": name} for name in GA4_METRICS],
        "orderBys": [{"dimension": {"dimensionName": "date"}}],
        "keepEmptyRows": True,
        "limit": str(limit),
    }

    try:
        service = build("analyticsdata", "v1beta", credentials=creds, cache_discovery=False)
        response = service.properties().runReport(property=GA4_ENTITY_ID, body=body).execute()
    except HttpError as exc:
        raise BrokerError("ga4_api_error", "GA4 runReport failed: HTTP %s" % getattr(exc, "status_code", "?"))
    except Exception as exc:  # noqa: BLE001
        raise BrokerError("ga4_transport_error", "GA4 request failed: %s" % type(exc).__name__)

    fetched_at = iso_now()
    rows = response.get("rows") or []
    series: list[dict] = []
    returned_dates: set[str] = set()

    for row in rows:
        dim_values = row.get("dimensionValues") or []
        metric_values = row.get("metricValues") or []
        date_str = _format_ga4_date(dim_values[0].get("value") if dim_values else None)
        reasons: list[str] = []
        record = {
            "source": GA4_SOURCE,
            "fetched_at": fetched_at,
            "entity_id": GA4_ENTITY_ID,
        }
        if date_str:
            record["date"] = date_str
            record["observed_at"] = date_str + "T00:00:00+00:00"
            returned_dates.add(date_str)
        else:
            record["observed_at"] = fetched_at
            reasons.append("GA4 row had a missing or invalid date dimension")
        for index, name in enumerate(GA4_METRICS):
            value = None
            if index < len(metric_values):
                try:
                    value = int(metric_values[index].get("value"))
                except (TypeError, ValueError, AttributeError):
                    value = None
            if value is None:
                reasons.append("%s was missing or not an integer" % name)
            else:
                record[name] = value
        record["unknown_reason"] = "; ".join(reasons) if reasons else None
        series.append(record)

    warnings: list[str] = []
    expected_dates = {
        (start_date + dt.timedelta(days=offset)).isoformat()
        for offset in range(lookback_days)
    }
    missing_dates = sorted(expected_dates - returned_dates)
    if missing_dates:
        warnings.append(
            "%d of %d requested dates were absent from the response (e.g. %s)"
            % (len(missing_dates), lookback_days, ", ".join(missing_dates[:3]))
        )
    if limit < lookback_days:
        warnings.append(
            "limit=%d is below the %d-day window; the series may be truncated by the API"
            % (limit, lookback_days)
        )

    payload = _base_payload("ga4", "ga4.daily_traffic", params)
    payload["generated_at"] = fetched_at
    payload["warnings"] = warnings
    payload["coverage"]["reason"] = (
        "GA4 Data API v1beta runReport exposes no data-finality field; the most recent "
        "day may be intraday and this is not machine-distinguishable"
    )
    payload["data"]["series"] = series
    payload["data"]["snapshot"] = {}
    return payload


# --- GSC (Search Console) --------------------------------------------------


def run_gsc_search_analytics(params: dict) -> dict:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    lookback_days = params["lookback_days"]
    limit = params["limit"]

    end_date = dt.date.today()
    start_date = end_date - dt.timedelta(days=lookback_days - 1)
    params["period"] = {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()}

    if not os.path.exists(TOKEN_PATH):
        raise BrokerError("token_missing", "data/google-token.json not found")

    try:
        creds = Credentials.from_authorized_user_file(TOKEN_PATH)
    except (OSError, ValueError) as exc:
        raise BrokerError("token_unreadable", "could not load google-token.json: %s" % exc)

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())  # メモリ内のみ。ファイルへ書き戻さない。
            except Exception as exc:  # noqa: BLE001 - refresh 失敗は人手対応が必要
                raise BrokerError("token_refresh_failed", "OAuth refresh failed: %s" % exc)
        else:
            raise BrokerError("token_invalid", "stored credential is not usable and cannot be refreshed")

    body = {
        "startDate": params["period"]["start_date"],
        "endDate": params["period"]["end_date"],
        "dimensions": ["date"],
        "rowLimit": limit,
        "dataState": "all",
    }

    try:
        service = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
        response = (
            service.searchanalytics()
            .query(siteUrl=GSC_SITE_URL, body=body)
            .execute()
        )
    except HttpError as exc:
        raise BrokerError(
            "gsc_api_error",
            "GSC searchanalytics.query failed: HTTP %s" % getattr(exc, "status_code", "?"),
        )
    except Exception as exc:  # noqa: BLE001
        raise BrokerError("gsc_transport_error", "GSC request failed: %s" % type(exc).__name__)

    fetched_at = iso_now()
    rows = response.get("rows") or []
    series: list[dict] = []
    returned_dates: set[str] = set()

    for row in rows:
        keys = row.get("keys") or []
        date_str = str(keys[0]) if keys and keys[0] else None
        # date 次元は "YYYY-MM-DD" 文字列。書式が違えば日付なし扱い。
        if date_str and not _ISO_DATETIME_RE.match(date_str):
            date_str = None
        reasons: list[str] = []
        record = {
            "source": GSC_SOURCE,
            "fetched_at": fetched_at,
            "entity_id": GSC_ENTITY_ID,
        }
        if date_str:
            record["date"] = date_str
            record["observed_at"] = date_str + "T00:00:00+00:00"
            returned_dates.add(date_str)
        else:
            record["observed_at"] = fetched_at
            reasons.append("GSC row had a missing or invalid date key")
        for name in GSC_INT_METRICS:
            raw = row.get(name)
            try:
                record[name] = int(round(float(raw)))
            except (TypeError, ValueError):
                reasons.append("%s was missing or not numeric" % name)
        for name in GSC_FLOAT_METRICS:
            raw = row.get(name)
            try:
                record[name] = float(raw)
            except (TypeError, ValueError):
                reasons.append("%s was missing or not numeric" % name)
        record["unknown_reason"] = "; ".join(reasons) if reasons else None
        series.append(record)

    warnings: list[str] = []
    expected_dates = {
        (start_date + dt.timedelta(days=offset)).isoformat()
        for offset in range(lookback_days)
    }
    missing_dates = sorted(expected_dates - returned_dates)
    if missing_dates:
        warnings.append(
            "%d of %d requested dates were absent from the response (e.g. %s); "
            "GSC omits zero-traffic days and lags the most recent 2-3 days"
            % (len(missing_dates), lookback_days, ", ".join(missing_dates[:3]))
        )
    if limit < lookback_days:
        warnings.append(
            "limit=%d is below the %d-day window; the series is truncated by rowLimit"
            % (limit, lookback_days)
        )

    payload = _base_payload("gsc", "gsc.search_analytics", params)
    payload["generated_at"] = fetched_at
    payload["warnings"] = warnings
    payload["coverage"]["reason"] = (
        "Search Console reporting is delayed by a few days and searchanalytics.query "
        "exposes no per-row finality flag; whether a given day is fully settled cannot "
        "be determined from the API (反映遅延の有無をAPIから判定できない)"
    )
    payload["data"]["series"] = series
    payload["data"]["snapshot"] = {}
    return payload


# --- Buffer ------------------------------------------------------------------


def run_buffer_account(params: dict) -> dict:
    try:
        from buffer_api import (
            BufferApiError,
            BufferGuardError,
            assert_operation_allowed,
            graphql,
        )
        from env_loader import EnvLoaderError
    except Exception as exc:  # noqa: BLE001
        raise BrokerError("buffer_import_error", "could not import buffer_api: %s" % exc)

    # 二重チェック: (1) broker 自身の read 許可リスト (2) buffer_api のガード
    if "BufferObservationAccount" not in BUFFER_READ_ALLOWED:
        raise BrokerError("buffer_not_allowed", "operation is not in the broker read allow-list")
    if "mutation" in BUFFER_ACCOUNT_QUERY.lower():
        raise BrokerError("buffer_not_read_only", "refusing: query text contains 'mutation'")
    try:
        assert_operation_allowed(BUFFER_ACCOUNT_QUERY)
    except BufferGuardError as exc:
        raise BrokerError("buffer_guard_error", "buffer_api rejected the query: %s" % exc)

    try:
        data = graphql(BUFFER_ACCOUNT_QUERY, {})  # API 呼び出しはこの1回のみ
    except BufferApiError as exc:
        raise BrokerError("buffer_api_error", "Buffer API call failed: %s" % exc)
    except EnvLoaderError as exc:
        raise BrokerError("buffer_env_error", "Buffer credential unavailable: %s" % exc)
    except Exception as exc:  # noqa: BLE001
        raise BrokerError("buffer_transport_error", "Buffer request failed: %s" % type(exc).__name__)

    fetched_at = iso_now()
    account = (data or {}).get("account") or {}
    account_id = account.get("id")
    organizations = [
        {"id": org.get("id"), "name": org.get("name")}
        for org in (account.get("organizations") or [])
    ]

    reasons = [
        "observed_at falls back to fetched_at because the Buffer account query exposes "
        "no server-side observation timestamp"
    ]
    if account_id is None:
        reasons.append("account id was absent from the Buffer response")

    snapshot = {
        "source": BUFFER_SOURCE,
        "fetched_at": fetched_at,
        "observed_at": fetched_at,
        "entity_id": account_id or "buffer:account",
        "unknown_reason": "; ".join(reasons),
        "account_id": account_id,
        "organization_count": len(organizations),
        "organizations": organizations,
    }

    payload = _base_payload("buffer", "buffer.account", params)
    payload["generated_at"] = fetched_at
    payload["coverage"]["reason"] = (
        "the Buffer GraphQL account query returns no coverage or completeness metadata"
    )
    payload["data"]["series"] = []
    payload["data"]["snapshot"] = snapshot
    return payload


# --- 操作テーブル ---------------------------------------------------------

ALLOWED_OPERATIONS = {
    "ga4.daily_traffic": {
        "service": "ga4",
        "description": "GA4 daily sessions / activeUsers / screenPageViews over a trailing window",
        "accepts": frozenset(["lookback_days", "limit"]),
        "handler": run_ga4_daily_traffic,
    },
    "gsc.search_analytics": {
        "service": "gsc",
        "description": "GSC daily clicks / impressions / ctr / position over a trailing window",
        "accepts": frozenset(["lookback_days", "limit"]),
        "handler": run_gsc_search_analytics,
    },
    "buffer.account": {
        "service": "buffer",
        "description": "Buffer account id and organizations via one read-only GraphQL call",
        "accepts": frozenset(),
        "handler": run_buffer_account,
    },
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only broker for Growth Agent external metrics (GA4 / GSC / Buffer)."
    )
    parser.add_argument("service", help="ga4, gsc or buffer")
    parser.add_argument("--operation", required=True, help="one of ALLOWED_OPERATIONS")
    parser.add_argument("--lookback-days", type=str, default=None, help="integer 1..90")
    parser.add_argument("--limit", type=str, default=None, help="integer 1..100")
    return parser


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = build_parser().parse_args()
    service = args.service
    operation = args.operation

    try:
        if service not in ("ga4", "gsc", "buffer"):
            raise BrokerError("unknown_service", "service must be 'ga4', 'gsc' or 'buffer'")

        spec = ALLOWED_OPERATIONS.get(operation)
        if spec is None:
            raise BrokerError(
                "operation_not_allowed",
                "operation '%s' is not in ALLOWED_OPERATIONS (%s)"
                % (operation, ", ".join(sorted(ALLOWED_OPERATIONS))),
            )
        if spec["service"] != service:
            raise BrokerError(
                "operation_service_mismatch",
                "operation '%s' belongs to service '%s', not '%s'"
                % (operation, spec["service"], service),
            )

        accepts = spec["accepts"]
        params: dict = {}
        warnings: list[str] = []

        if args.lookback_days is not None:
            value = _int_in_range("--lookback-days", args.lookback_days, LOOKBACK_MIN, LOOKBACK_MAX)
            if "lookback_days" in accepts:
                params["lookback_days"] = value
            else:
                warnings.append("--lookback-days is ignored by operation '%s'" % operation)
        if args.limit is not None:
            value = _int_in_range("--limit", args.limit, LIMIT_MIN, LIMIT_MAX)
            if "limit" in accepts:
                params["limit"] = value
            else:
                warnings.append("--limit is ignored by operation '%s'" % operation)

        if "lookback_days" in accepts and "lookback_days" not in params:
            params["lookback_days"] = DEFAULT_LOOKBACK_DAYS
        if "limit" in accepts and "limit" not in params:
            params["limit"] = min(params.get("lookback_days", DEFAULT_LOOKBACK_DAYS), LIMIT_MAX)

        payload = spec["handler"](params)
        payload["params"] = params
        payload["warnings"] = list(payload.get("warnings") or []) + warnings
        payload["status"] = "ok"
        emit(payload, 0)

    except BrokerError as exc:
        emit_error(service, operation, {}, exc.code, exc.message)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - すべての例外を契約JSONに変換する
        emit_error(service, operation, {}, "unexpected_error", "%s: %s" % (type(exc).__name__, exc))


if __name__ == "__main__":
    main()
