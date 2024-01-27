"""Invoke a handler locally with an event file.

    python scripts/invoke.py events/api.json
    python scripts/invoke.py events/sqs.json --handler handlers.queue.handler

The handler runs in this process against moto, an in-memory fake of AWS, so
no account, credentials or Docker are needed and nothing real is touched.
The fake DynamoDB table starts with the items in ``events/seed_items.json``
and is discarded when the script exits.

The handler is chosen from the event shape (SQS records go to the queue
handler, everything else to the API handler) unless ``--handler`` is given.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TABLE_NAME = "items-local"


class LocalContext:
    """Stand-in for the Lambda context object."""

    function_name = "local-invoke"
    function_version = "$LATEST"
    memory_limit_in_mb = 256
    invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:local-invoke"

    def __init__(self):
        self.aws_request_id = str(uuid.uuid4())

    def get_remaining_time_in_millis(self) -> int:
        return 10_000


def pick_handler(event: dict) -> str:
    records = event.get("Records") if isinstance(event, dict) else None
    if records and records[0].get("eventSource") == "aws:sqs":
        return "handlers.queue.handler"
    return "handlers.api.handler"


def load_handler(dotted: str):
    module_name, _, attribute = dotted.rpartition(".")
    return getattr(importlib.import_module(module_name), attribute)


def invoke(event: dict, handler_path: str | None = None, seed_file: Path | None = None):
    """Run the handler against a fresh in-memory table and return ``(result, items_in_table)``."""
    os.environ.update(
        AWS_ACCESS_KEY_ID="testing",
        AWS_SECRET_ACCESS_KEY="testing",
        AWS_DEFAULT_REGION="us-east-1",
        AWS_SHARED_CREDENTIALS_FILE=os.devnull,  # ignore any real profiles on this machine
        AWS_CONFIG_FILE=os.devnull,
        TABLE_NAME=TABLE_NAME,
    )
    for name in ("AWS_PROFILE", "AWS_SESSION_TOKEN"):
        os.environ.pop(name, None)
    os.environ.setdefault("SERVICE_NAME", "lambda-python-starter")
    sys.path.insert(0, str(ROOT / "src"))

    import boto3
    from moto import mock_aws

    with mock_aws():
        from shared.config import get_config
        from shared.items import Item, get_store

        get_config.cache_clear()
        get_store.cache_clear()
        boto3.client("dynamodb").create_table(
            TableName=TABLE_NAME, BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        )
        if seed_file and seed_file.exists():
            for raw in json.loads(seed_file.read_text()):
                get_store().put(Item.from_payload(raw))
        handler = load_handler(handler_path or pick_handler(event))
        result = handler(event, LocalContext())
        count = boto3.client("dynamodb").scan(TableName=TABLE_NAME, Select="COUNT")["Count"]
        get_store.cache_clear()
        return result, count


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Invoke a Lambda handler locally against an in-memory AWS fake.")
    parser.add_argument("event", help="path to a JSON event file, e.g. events/api.json")
    parser.add_argument("--handler", help="module.function, e.g. handlers.queue.handler (default: from the event)")
    parser.add_argument("--seed", default=str(ROOT / "events" / "seed_items.json"),
                        help="JSON list of items to load into the table first")
    args = parser.parse_args(argv)
    try:
        event = json.loads(Path(args.event).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: cannot read event file {args.event}: {exc}", file=sys.stderr)
        return 2
    handler_path = args.handler or pick_handler(event)
    print(f"--- invoking {handler_path} with {args.event} (in-memory AWS, logs follow)")
    result, count = invoke(event, handler_path, Path(args.seed))
    print("--- result")
    if isinstance(result, dict) and isinstance(result.get("body"), str):
        try:  # show an HTTP body as JSON instead of an escaped string
            result = {**result, "body": json.loads(result["body"])}
        except json.JSONDecodeError:
            pass
    print(json.dumps(result, indent=2))
    print(f"--- items in the in-memory table afterwards: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
