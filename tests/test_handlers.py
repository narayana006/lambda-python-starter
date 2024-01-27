import json

import pytest
from botocore.exceptions import ClientError

from handlers import api, queue
from shared import middleware
from shared.config import ConfigError, get_config
from shared.items import Item, get_store

from conftest import TABLE, load_event


def body(response):
    return json.loads(response["body"])


# --- API handler ------------------------------------------------------------

def test_get_existing_item(table, context):
    get_store().put(Item("item-001", "Blue widget", 3))
    response = api.handler(load_event("api.json"), context)
    assert response["statusCode"] == 200
    assert response["headers"]["content-type"] == "application/json"
    assert body(response) == {"id": "item-001", "name": "Blue widget", "quantity": 3}


def test_get_missing_item_is_404(table, context):
    response = api.handler(load_event("api.json"), context)
    assert (response["statusCode"], body(response)) == (404, {"error": "item not found"})


def test_create_item_stores_it(table, context):
    response = api.handler(load_event("api_create.json"), context)
    assert response["statusCode"] == 201
    assert response["headers"]["location"] == "/items/item-100"
    assert body(response) == {"id": "item-100", "name": "Desk lamp", "quantity": 4}
    stored = table.get_item(TableName=TABLE, Key={"id": {"S": "item-100"}})["Item"]
    assert stored == {"id": {"S": "item-100"}, "name": {"S": "Desk lamp"}, "quantity": {"N": "4"}}


def test_create_item_generates_an_id(table, context):
    event = load_event("api_create.json")
    event["body"] = json.dumps({"name": "No id"})
    created = body(api.handler(event, context))
    assert get_store().get(created["id"]).name == "No id"


@pytest.mark.parametrize("raw_body, message", [
    (None, "request body is required"),
    ("{broken", "request body is not valid JSON"),
    ("[1, 2]", "expected a JSON object"),
    ('{"name": ""}', "'name' must be a non-empty string"),
    ('{"name": "x", "quantity": -3}', "'quantity' must be a non-negative integer"),
])
def test_create_item_validation_errors_are_400(table, context, raw_body, message):
    event = load_event("api_create.json")
    event["body"] = raw_body
    response = api.handler(event, context)
    assert (response["statusCode"], body(response)) == (400, {"error": message})
    assert table.scan(TableName=TABLE, Select="COUNT")["Count"] == 0


def test_unknown_route_is_404(table, context):
    event = load_event("api.json")
    event["routeKey"] = "DELETE /items/{id}"
    response = api.handler(event, context)
    assert (response["statusCode"], body(response)) == (404, {"error": "no route for DELETE /items/{id}"})


def test_non_http_event_is_400(table, context):
    assert api.handler({"Records": []}, context)["statusCode"] == 400


def test_storage_failure_is_a_500_without_details(context, log_lines):
    # No table exists inside this mock, so DynamoDB answers ResourceNotFoundException.
    from moto import mock_aws
    with mock_aws():
        response = api.handler(load_event("api.json"), context)
    assert response["statusCode"] == 500
    assert body(response) == {"error": "internal error", "request_id": "test-request-id"}
    error = next(line for line in log_lines() if line["level"] == "ERROR")
    assert error["message"] == "request failed"
    assert "ResourceNotFoundException" in error["exception"]


def test_api_logs_are_structured(table, context, log_lines):
    api.handler(load_event("api_create.json"), context)
    lines = log_lines()
    assert [line["message"] for line in lines] == ["item created", "request handled"]
    assert lines[0]["item_id"] == "item-100"
    assert (lines[1]["route"], lines[1]["status"]) == ("POST /items", 201)
    for line in lines:
        assert line["aws_request_id"] == "test-request-id"
        assert line["function_name"] == "test-function"
        assert line["service"] == "starter-test"
        assert "Desk lamp" not in json.dumps(line)  # request bodies are not logged


# --- queue handler ----------------------------------------------------------

def test_queue_stores_valid_messages_and_reports_the_bad_one(table, context, log_lines):
    result = queue.handler(load_event("sqs.json"), context)
    assert result == {"batchItemFailures": [{"itemIdentifier": "22222222-2222-4222-8222-222222222222"}]}
    assert get_store().get("item-200") == Item("item-200", "Notebook", 12)
    assert get_store().get("item-201") == Item("item-201", "Stapler", 0)
    assert table.scan(TableName=TABLE, Select="COUNT")["Count"] == 2
    warning = next(line for line in log_lines() if line["level"] == "WARNING")
    assert warning["message"] == "invalid message"
    assert warning["message_id"].startswith("22222222") and warning["receive_count"] == 2
    summary = log_lines()[-1]
    assert (summary["message"], summary["received"], summary["failed"]) == ("batch processed", 3, 1)


def test_queue_all_good_returns_no_failures(table, context):
    event = load_event("sqs.json")
    del event["Records"][1]
    assert queue.handler(event, context) == {"batchItemFailures": []}


def test_queue_reports_non_json_bodies(table, context):
    event = load_event("sqs.json")
    event["Records"] = event["Records"][:1]
    event["Records"][0]["body"] = "plain text"
    result = queue.handler(event, context)
    assert [f["itemIdentifier"][:8] for f in result["batchItemFailures"]] == ["11111111"]


def test_queue_reports_storage_failures_per_message(table, context, monkeypatch):
    store = get_store()
    real_put = store.put

    def flaky_put(item):
        if item.id == "item-200":
            raise ClientError({"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "slow down"}},
                              "PutItem")
        real_put(item)

    monkeypatch.setattr(store, "put", flaky_put)
    result = queue.handler(load_event("sqs.json"), context)
    assert [f["itemIdentifier"][:8] for f in result["batchItemFailures"]] == ["11111111", "22222222"]
    assert store.get("item-201") is not None  # the rest of the batch still went through


def test_queue_empty_event(table, context):
    assert queue.handler({}, context) == {"batchItemFailures": []}


# --- middleware -------------------------------------------------------------

def test_cold_start_flag_is_true_only_once(table, context, log_lines, monkeypatch):
    monkeypatch.setattr(middleware, "_cold_start", True)
    api.handler(load_event("api.json"), context)
    api.handler(load_event("api.json"), context)
    assert [line["cold_start"] for line in log_lines()] == [True, False]


def test_unhandled_errors_are_logged_and_reraised(context, log_lines):
    @middleware.lambda_handler
    def broken(event, context):
        raise RuntimeError("kaput")

    with pytest.raises(RuntimeError, match="kaput"):
        broken({}, context)
    (line,) = log_lines()
    assert line["message"] == "unhandled error" and "RuntimeError: kaput" in line["exception"]
    assert line["aws_request_id"] == "test-request-id"


def test_missing_configuration_fails_fast(context, monkeypatch):
    monkeypatch.delenv("TABLE_NAME")
    get_config.cache_clear()
    with pytest.raises(ConfigError, match="TABLE_NAME"):
        api.handler(load_event("api.json"), context)
