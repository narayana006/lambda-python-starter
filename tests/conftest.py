import io
import json
import logging
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from shared import log
from shared.config import get_config
from shared.items import get_store

EVENTS = Path(__file__).resolve().parent.parent / "events"
TABLE = "items-test"


class FakeContext:
    aws_request_id = "test-request-id"
    function_name = "test-function"

    def get_remaining_time_in_millis(self):
        return 10_000


@pytest.fixture(autouse=True)
def environment(monkeypatch, tmp_path):
    """Dummy credentials and settings for every test, so nothing can reach a real account."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-credentials"))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-config"))
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    monkeypatch.setenv("TABLE_NAME", TABLE)
    monkeypatch.setenv("SERVICE_NAME", "starter-test")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    get_config.cache_clear()
    get_store.cache_clear()
    yield
    get_config.cache_clear()
    get_store.cache_clear()
    log.clear_context()
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_starter_json", False):
            root.removeHandler(handler)


@pytest.fixture
def table():
    with mock_aws():
        client = boto3.client("dynamodb")
        client.create_table(
            TableName=TABLE, BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        )
        yield client


@pytest.fixture
def context():
    return FakeContext()


@pytest.fixture
def log_lines(monkeypatch):
    """Capture what the handlers log, parsed from JSON."""
    stream = io.StringIO()
    real_configure = log.configure
    monkeypatch.setattr(log, "configure", lambda service, level="INFO", stream_=None: real_configure(service, level, stream))
    return lambda: [json.loads(line) for line in stream.getvalue().splitlines()]


def load_event(name):
    return json.loads((EVENTS / name).read_text())
