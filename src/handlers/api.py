"""HTTP API handler: ``POST /items`` and ``GET /items/{id}``."""

from __future__ import annotations

import logging

from shared.events import BadRequest, HttpRequest, LambdaContext, json_response
from shared.items import Item, get_store
from shared.middleware import lambda_handler

logger = logging.getLogger(__name__)


def create_item(request: HttpRequest) -> dict:
    item = Item.from_payload(request.json())
    get_store().put(item)
    logger.info("item created", extra={"item_id": item.id})
    return json_response(201, item.to_dict(), {"location": f"/items/{item.id}"})


def get_item(request: HttpRequest) -> dict:
    item_id = request.path_parameters.get("id", "")
    item = get_store().get(item_id)
    if item is None:
        return json_response(404, {"error": "item not found"})
    return json_response(200, item.to_dict())


ROUTES = {
    "POST /items": create_item,
    "GET /items/{id}": get_item,
}


@lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    try:
        request = HttpRequest.from_event(event)
        route = ROUTES.get(request.route_key)
        if route is None:
            return json_response(404, {"error": f"no route for {request.route_key}"})
        response = route(request)
    except BadRequest as exc:
        logger.info("bad request", extra={"reason": str(exc)})
        return json_response(400, {"error": str(exc)})
    except Exception:
        # The caller gets a generic message and the request id; the traceback goes to the log.
        logger.exception("request failed")
        return json_response(500, {"error": "internal error", "request_id": getattr(context, "aws_request_id", None)})
    logger.info("request handled", extra={"route": request.route_key, "status": response["statusCode"]})
    return response
