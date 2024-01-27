"""The example domain: items stored in a DynamoDB table.

Replace this module with your own model and storage. The handlers only use
``Item.from_payload``, ``ItemStore.put`` and ``ItemStore.get``.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from functools import lru_cache

import boto3

from .config import get_config
from .events import BadRequest

MAX_NAME_LENGTH = 200


@dataclass(frozen=True)
class Item:
    id: str
    name: str
    quantity: int = 0

    @classmethod
    def from_payload(cls, payload, item_id: str | None = None) -> "Item":
        """Validate untrusted input. ``item_id`` overrides any id in the payload."""
        if not isinstance(payload, dict):
            raise BadRequest("expected a JSON object")
        name = payload.get("name")
        if not isinstance(name, str) or not name.strip():
            raise BadRequest("'name' must be a non-empty string")
        if len(name) > MAX_NAME_LENGTH:
            raise BadRequest(f"'name' must be at most {MAX_NAME_LENGTH} characters")
        quantity = payload.get("quantity", 0)
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
            raise BadRequest("'quantity' must be a non-negative integer")
        item_id = item_id or payload.get("id") or str(uuid.uuid4())
        if not isinstance(item_id, str) or not item_id.strip():
            raise BadRequest("'id' must be a non-empty string")
        return cls(id=item_id, name=name.strip(), quantity=quantity)

    def to_dict(self) -> dict:
        return asdict(self)


class ItemStore:
    def __init__(self, table_name: str, client=None):
        self.table_name = table_name
        self.client = client or boto3.client("dynamodb")

    def put(self, item: Item) -> None:
        """Create or replace the item. Writing the same item twice is harmless,
        which matters for the queue handler: SQS can deliver a message more than once."""
        self.client.put_item(
            TableName=self.table_name,
            Item={"id": {"S": item.id}, "name": {"S": item.name}, "quantity": {"N": str(item.quantity)}},
        )

    def get(self, item_id: str) -> Item | None:
        response = self.client.get_item(TableName=self.table_name, Key={"id": {"S": item_id}})
        raw = response.get("Item")
        if raw is None:
            return None
        return Item(id=raw["id"]["S"], name=raw["name"]["S"], quantity=int(raw.get("quantity", {"N": "0"})["N"]))


@lru_cache(maxsize=1)
def get_store() -> ItemStore:
    """One store, and so one boto3 client, per execution environment.

    Creating the client outside the handler function lets warm invocations
    reuse its connections.
    """
    return ItemStore(get_config().table_name)
