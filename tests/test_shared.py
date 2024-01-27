import base64
import io
import json
import logging

import pytest

from shared import log
from shared.config import Config, ConfigError
from shared.events import BadRequest, HttpRequest, SqsRecord, json_response, sqs_records
from shared.items import Item, ItemStore

from conftest import TABLE, load_event


# --- config -----------------------------------------------------------------

def test_config_from_env_with_defaults():
    assert Config.from_env({"TABLE_NAME": "t"}) == Config("t", "lambda-python-starter", "INFO")
    config = Config.from_env({"TABLE_NAME": " t ", "LOG_LEVEL": "debug", "SERVICE_NAME": "orders"})
    assert config == Config("t", "orders", "DEBUG")


@pytest.mark.parametrize("env, message", [
    ({}, "TABLE_NAME"),
    ({"TABLE_NAME": "  "}, "TABLE_NAME"),
    ({"TABLE_NAME": "t", "LOG_LEVEL": "LOUD"}, "LOG_LEVEL"),
])
def test_config_errors_name_the_variable(env, message):
    with pytest.raises(ConfigError, match=message):
        Config.from_env(env)


# --- logging ----------------------------------------------------------------

def capture():
    stream = io.StringIO()
    log.configure("svc", "INFO", stream)
    return lambda: [json.loads(line) for line in stream.getvalue().splitlines()]


def test_log_lines_are_json_with_context_and_extras():
    lines = capture()
    log.set_context(aws_request_id="req-1", function_name="fn", cold_start=True, skipped=None)
    logging.getLogger("app").info("hello %s", "world", extra={"item_id": "i-1", "count": 2})
    logging.getLogger("app").debug("below the level")
    (line,) = lines()
    assert line["message"] == "hello world"
    assert (line["level"], line["service"], line["logger"]) == ("INFO", "svc", "app")
    assert (line["aws_request_id"], line["function_name"], line["cold_start"]) == ("req-1", "fn", True)
    assert (line["item_id"], line["count"]) == ("i-1", 2)
    assert "skipped" not in line
    assert line["timestamp"].endswith("+00:00")


def test_log_exception_and_unserializable_values():
    lines = capture()
    try:
        raise ValueError("boom")
    except ValueError:
        logging.getLogger("app").exception("failed", extra={"obj": object()})
    (line,) = lines()
    assert line["level"] == "ERROR"
    assert "ValueError: boom" in line["exception"]
    assert isinstance(line["obj"], str)


def test_configure_twice_does_not_duplicate_lines():
    capture()
    lines = capture()
    logging.getLogger("app").warning("once")
    assert len(lines()) == 1
    assert sum(1 for h in logging.getLogger().handlers if getattr(h, "_starter_json", False)) == 1


def test_configure_replaces_the_runtime_handler_inside_lambda(monkeypatch):
    root = logging.getLogger()
    runtime_handler = logging.NullHandler()
    root.addHandler(runtime_handler)
    try:
        capture()
        assert runtime_handler in root.handlers  # outside Lambda other handlers are left alone
        monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "fn")
        saved = [h for h in root.handlers if h is not runtime_handler and not getattr(h, "_starter_json", False)]
        capture()
        assert runtime_handler not in root.handlers
        for handler in saved:  # give pytest its own handlers back
            root.addHandler(handler)
    finally:
        root.removeHandler(runtime_handler)


def test_clear_context():
    lines = capture()
    log.set_context(aws_request_id="req-1")
    log.clear_context()
    logging.getLogger("app").info("x")
    assert "aws_request_id" not in lines()[0]


# --- events -----------------------------------------------------------------

def test_http_request_from_sample_event():
    request = HttpRequest.from_event(load_event("api.json"))
    assert (request.method, request.path, request.route_key) == ("GET", "/items/item-001", "GET /items/{id}")
    assert request.path_parameters == {"id": "item-001"}
    assert request.headers["accept"] == "application/json"
    assert request.query == {} and request.body is None
    assert request.request_id == "example-request-id-0001"


def test_http_request_body_handling():
    event = load_event("api_create.json")
    assert HttpRequest.from_event(event).json()["name"] == "Desk lamp"
    event["body"] = base64.b64encode(b'{"name": "encoded"}').decode()
    event["isBase64Encoded"] = True
    assert HttpRequest.from_event(event).json() == {"name": "encoded"}
    event["headers"] = {"Content-Type": "application/json"}
    assert HttpRequest.from_event(event).headers == {"content-type": "application/json"}


@pytest.mark.parametrize("change, message", [
    ({"body": None}, "body is required"),
    ({"body": "{not json"}, "not valid JSON"),
    ({"body": "%%%", "isBase64Encoded": True}, "base64"),
])
def test_http_request_bad_bodies(change, message):
    event = {**load_event("api_create.json"), **change}
    with pytest.raises(BadRequest, match=message):
        HttpRequest.from_event(event).json()


@pytest.mark.parametrize("event", [{}, {"requestContext": {}}, {"Records": []}, {"requestContext": {"http": None}}])
def test_http_request_rejects_other_event_shapes(event):
    with pytest.raises(BadRequest, match="HTTP API"):
        HttpRequest.from_event(event)


def test_sqs_records_from_sample_event():
    records = sqs_records(load_event("sqs.json"))
    assert [r.message_id[:8] for r in records] == ["11111111", "22222222", "33333333"]
    assert records[1].receive_count == 2
    assert records[0].json() == {"id": "item-200", "name": "Notebook", "quantity": 12}
    assert sqs_records({}) == []
    assert SqsRecord.from_record({"messageId": "m"}) == SqsRecord("m", "", 1)


def test_json_response():
    response = json_response(201, {"id": "1"}, {"location": "/items/1"})
    assert response == {
        "statusCode": 201,
        "headers": {"content-type": "application/json", "location": "/items/1"},
        "body": '{"id": "1"}',
    }


# --- items ------------------------------------------------------------------

def test_item_from_payload():
    assert Item.from_payload({"id": "a", "name": " Lamp ", "quantity": 2}) == Item("a", "Lamp", 2)
    assert Item.from_payload({"name": "Lamp"}, item_id="forced") == Item("forced", "Lamp", 0)
    generated = Item.from_payload({"name": "Lamp"})
    assert len(generated.id) == 36


@pytest.mark.parametrize("payload", [
    None, [], "text", {}, {"name": ""}, {"name": "  "}, {"name": 5}, {"name": "x" * 201},
    {"name": "ok", "quantity": -1}, {"name": "ok", "quantity": 1.5}, {"name": "ok", "quantity": "2"},
    {"name": "ok", "quantity": True}, {"name": "ok", "id": 7},
])
def test_item_from_payload_rejects_bad_input(payload):
    with pytest.raises(BadRequest):
        Item.from_payload(payload)


def test_item_store_round_trip(table):
    store = ItemStore(TABLE, table)
    assert store.get("missing") is None
    store.put(Item("a", "Lamp", 2))
    store.put(Item("a", "Lamp", 5))  # same key: replaced, not duplicated
    assert store.get("a") == Item("a", "Lamp", 5)
    assert table.scan(TableName=TABLE, Select="COUNT")["Count"] == 1
