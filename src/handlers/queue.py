"""SQS handler: each message body is a JSON item to store.

Returns a partial batch response. Only the messages listed in
``batchItemFailures`` go back to the queue; the rest of the batch is
deleted. This needs ``ReportBatchItemFailures`` on the event source mapping
(set in ``template.yaml``). Without it Lambda ignores the return value and a
single bad message makes the whole batch retry.
"""

from __future__ import annotations

import json
import logging

from shared.events import BadRequest, LambdaContext, sqs_records
from shared.items import Item, get_store
from shared.middleware import lambda_handler

logger = logging.getLogger(__name__)


@lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    store = get_store()
    failures = []
    records = sqs_records(event)
    for record in records:
        try:
            item = Item.from_payload(record.json())
            store.put(item)
        except (BadRequest, json.JSONDecodeError) as exc:
            # Retrying will not fix a malformed message; after maxReceiveCount
            # deliveries the queue's redrive policy moves it to the dead-letter queue.
            logger.warning("invalid message", extra={
                "message_id": record.message_id, "reason": str(exc), "receive_count": record.receive_count})
            failures.append(record.message_id)
        except Exception:
            logger.exception("failed to store message", extra={"message_id": record.message_id})
            failures.append(record.message_id)
    logger.info("batch processed", extra={"received": len(records), "failed": len(failures)})
    return {"batchItemFailures": [{"itemIdentifier": message_id} for message_id in failures]}
