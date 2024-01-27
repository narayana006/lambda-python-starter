"""Typed views of the events Lambda passes to a handler.

Only the fields the handlers use are modelled. The shapes are the API
Gateway HTTP API payload format 2.0 and the SQS event source mapping batch.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any, Protocol


class LambdaContext(Protocol):
    """The parts of the Lambda context object used by this project."""

    aws_request_id: str
    function_name: str

    def get_remaining_time_in_millis(self) -> int: ...


class BadRequest(ValueError):
    """The caller sent something the handler cannot use; becomes an HTTP 400."""


@dataclass(frozen=True)
class HttpRequest:
    method: str
    path: str
    route_key: str
    path_parameters: dict[str, str] = field(default_factory=dict)
    query: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    body: str | None = None
    request_id: str | None = None

    @classmethod
    def from_event(cls, event: dict) -> "HttpRequest":
        try:
            http = event["requestContext"]["http"]
            method, path = http["method"].upper(), event.get("rawPath") or http["path"]
        except (KeyError, TypeError, AttributeError):
            raise BadRequest("not an HTTP API (payload format 2.0) event") from None
        body = event.get("body")
        if body is not None and event.get("isBase64Encoded"):
            try:
                body = base64.b64decode(body, validate=True).decode("utf-8")
            except ValueError:
                raise BadRequest("body is not valid base64-encoded UTF-8") from None
        return cls(
            method=method,
            path=path,
            route_key=event.get("routeKey") or f"{method} {path}",
            path_parameters=dict(event.get("pathParameters") or {}),
            query=dict(event.get("queryStringParameters") or {}),
            headers={name.lower(): value for name, value in (event.get("headers") or {}).items()},
            body=body,
            request_id=event["requestContext"].get("requestId"),
        )

    def json(self) -> Any:
        if not self.body:
            raise BadRequest("request body is required")
        try:
            return json.loads(self.body)
        except json.JSONDecodeError:
            raise BadRequest("request body is not valid JSON") from None


@dataclass(frozen=True)
class SqsRecord:
    message_id: str
    body: str
    receive_count: int = 1

    @classmethod
    def from_record(cls, record: dict) -> "SqsRecord":
        return cls(
            message_id=record["messageId"],
            body=record.get("body", ""),
            receive_count=int(record.get("attributes", {}).get("ApproximateReceiveCount", 1)),
        )

    def json(self) -> Any:
        return json.loads(self.body)


def sqs_records(event: dict) -> list[SqsRecord]:
    return [SqsRecord.from_record(record) for record in event.get("Records", [])]


def json_response(status: int, body: Any, headers: dict[str, str] | None = None) -> dict:
    """An HTTP API (payload format 2.0) response."""
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json", **(headers or {})},
        "body": json.dumps(body),
    }
