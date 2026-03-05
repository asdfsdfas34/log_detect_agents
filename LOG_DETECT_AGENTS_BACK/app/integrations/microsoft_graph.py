"""Microsoft Graph API integration helper."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib import error, parse, request


def call_microsoft_graph_api(
    *,
    endpoint: str,
    method: str = "GET",
    token: str | None = None,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    timeout_s: float = 15.0,
) -> dict[str, Any]:
    """Call Microsoft Graph API and return JSON-like dict response."""

    access_token = (token or os.getenv("MS_GRAPH_API_TOKEN", "")).strip()
    if not access_token:
        raise ValueError("Microsoft Graph API token is required.")

    normalized_endpoint = endpoint.strip()
    if not normalized_endpoint:
        raise ValueError("Microsoft Graph endpoint is required.")

    if normalized_endpoint.startswith("https://"):
        url = normalized_endpoint
    else:
        base = os.getenv("MS_GRAPH_API_BASE_URL", "https://graph.microsoft.com/v1.0").rstrip("/")
        normalized_endpoint = normalized_endpoint.lstrip("/")
        url = f"{base}/{normalized_endpoint}"

    if params:
        query_string = parse.urlencode({k: str(v) for k, v in params.items()}, doseq=True)
        url = f"{url}?{query_string}"

    payload = None
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(url=url, method=method.upper(), headers=headers, data=payload)
    try:
        with request.urlopen(req, timeout=timeout_s) as response:
            raw = response.read().decode("utf-8")
            if not raw:
                return {"status": response.status}
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"status": response.status, "raw": raw}
    except error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="ignore") if exc.fp else ""
        try:
            details = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            details = {"raw": payload}
        raise RuntimeError(
            f"Microsoft Graph API HTTP error: status={exc.code}, reason={exc.reason}, details={details}"
        ) from exc
