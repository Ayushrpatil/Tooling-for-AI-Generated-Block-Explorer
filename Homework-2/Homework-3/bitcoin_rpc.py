from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class BitcoinRPCError(RuntimeError):
    """Raised when the Bitcoin JSON-RPC endpoint returns an error."""


def _json_loads(raw_text: str) -> Any:
    return json.loads(raw_text, parse_float=Decimal, parse_int=int)


@dataclass(slots=True)
class RPCConfig:
    url: str = "http://127.0.0.1:8332"
    rpc_user: str | None = None
    rpc_password: str | None = None
    rpc_cookie_file: str | None = None
    timeout_seconds: int = 120

    def credentials(self) -> tuple[str, str]:
        if self.rpc_cookie_file:
            cookie = Path(self.rpc_cookie_file)
            if not cookie.is_file():
                raise BitcoinRPCError(f"RPC cookie file not found: {cookie}")
            value = cookie.read_text(encoding="utf-8").strip()
            if ":" not in value:
                raise BitcoinRPCError(f"Invalid RPC cookie format in: {cookie}")
            user, password = value.split(":", 1)
            return user, password

        if self.rpc_user and self.rpc_password:
            return self.rpc_user, self.rpc_password

        raise BitcoinRPCError(
            "RPC credentials are missing. Provide --rpc-cookie-file or both "
            "--rpc-user and --rpc-password."
        )


class BitcoinRPC:
    def __init__(self, config: RPCConfig) -> None:
        self.config = config
        self._request_id = 0

    def _post(self, payload: bytes, label: str) -> Any:
        user, password = self.config.credentials()
        token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")

        request = Request(
            self.config.url,
            data=payload,
            headers={
                "Content-Type": "text/plain",
                "Authorization": f"Basic {token}",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                raw_text = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise BitcoinRPCError(f"HTTP {exc.code} calling {label}: {detail}") from exc
        except URLError as exc:
            raise BitcoinRPCError(f"Could not reach Bitcoin RPC at {self.config.url}: {exc}") from exc

        return _json_loads(raw_text)

    def call(self, method: str, params: list[Any] | None = None) -> Any:
        self._request_id += 1
        payload = json.dumps(
            {
                "jsonrpc": "1.0",
                "id": self._request_id,
                "method": method,
                "params": params or [],
            }
        ).encode("utf-8")

        message = self._post(payload, method)
        if message.get("error"):
            raise BitcoinRPCError(f"RPC error calling {method}: {message['error']}")
        return message["result"]

    def batch_call(self, calls: list[tuple[str, list[Any] | None]]) -> list[Any]:
        if not calls:
            return []

        requests: list[dict[str, Any]] = []
        id_to_index: dict[int, int] = {}
        id_to_method: dict[int, str] = {}

        for index, (method, params) in enumerate(calls):
            self._request_id += 1
            request_id = self._request_id
            id_to_index[request_id] = index
            id_to_method[request_id] = method
            requests.append(
                {
                    "jsonrpc": "1.0",
                    "id": request_id,
                    "method": method,
                    "params": params or [],
                }
            )

        payload = json.dumps(requests).encode("utf-8")
        messages = self._post(payload, "batch")
        if not isinstance(messages, list):
            raise BitcoinRPCError("RPC batch call returned a non-list response.")

        results: list[Any] = [None] * len(calls)
        for message in messages:
            request_id = message.get("id")
            if request_id not in id_to_index:
                raise BitcoinRPCError(f"RPC batch response returned an unknown id: {request_id}")
            if message.get("error"):
                method = id_to_method[request_id]
                raise BitcoinRPCError(f"RPC error calling {method}: {message['error']}")
            results[id_to_index[request_id]] = message["result"]

        return results
