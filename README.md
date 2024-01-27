# lambda-python-starter

A starting point for Python AWS Lambda services: two example handlers that share code, typed event models, JSON logging, validated configuration, tests, a local invoke script and a SAM template.

**Status:** everything in the checklist below works locally today. The tests and the local invoke run against [moto](https://github.com/getmoto/moto), an in-memory fake of AWS. **The SAM template has not been deployed.** It passes `cfn-lint` and is checked against the code by the tests; `sam validate`, `sam build` and `sam deploy` have not been run on it.

## Get started

Create your own repository from this one ("Use this template" on GitHub, or clone it), then:

```bash
python -m venv .venv && . .venv/bin/activate
make install
make test && make invoke EVENT=events/api.json
```

`make install` runs `pip install -e ".[dev]"`. To install without cloning: `pip install git+https://github.com/narayana006/lambda-python-starter`.

`make invoke` runs a handler in your terminal with an event file. No AWS account, credentials or Docker are needed: DynamoDB is faked in memory and seeded from `events/seed_items.json`. Real output of `make invoke EVENT=events/api.json`:

```
python scripts/invoke.py events/api.json 
--- invoking handlers.api.handler with events/api.json (in-memory AWS, logs follow)
{"timestamp": "2026-11-10T16:35:14.859+00:00", "level": "INFO", "message": "request handled", "service": "lambda-python-starter", "logger": "handlers.api", "aws_request_id": "ad1a37ac-df91-4640-8eeb-5f2e2381e120", "function_name": "local-invoke", "cold_start": true, "route": "GET /items/{id}", "status": 200}
--- result
{
  "statusCode": 200,
  "headers": {
    "content-type": "application/json"
  },
  "body": {
    "id": "item-001",
    "name": "Blue widget",
    "quantity": 3
  }
}
--- items in the in-memory table afterwards: 2
```

The log line is what the function would write to CloudWatch Logs. The timestamp and request id differ on each run.

The handler is picked from the event shape, so an SQS event goes to the queue handler. Output of `make invoke EVENT=events/sqs.json` (the second of the three messages has an empty name on purpose):

```
python scripts/invoke.py events/sqs.json 
--- invoking handlers.queue.handler with events/sqs.json (in-memory AWS, logs follow)
{"timestamp": "2026-11-10T16:35:15.532+00:00", "level": "WARNING", "message": "invalid message", "service": "lambda-python-starter", "logger": "handlers.queue", "aws_request_id": "aeab1a0d-43fe-4acc-a202-9b3eeed0f0bf", "function_name": "local-invoke", "cold_start": true, "message_id": "22222222-2222-4222-8222-222222222222", "reason": "'name' must be a non-empty string", "receive_count": 2}
{"timestamp": "2026-11-10T16:35:15.533+00:00", "level": "INFO", "message": "batch processed", "service": "lambda-python-starter", "logger": "handlers.queue", "aws_request_id": "aeab1a0d-43fe-4acc-a202-9b3eeed0f0bf", "function_name": "local-invoke", "cold_start": true, "received": 3, "failed": 1}
--- result
{
  "batchItemFailures": [
    {
      "itemIdentifier": "22222222-2222-4222-8222-222222222222"
    }
  ]
}
--- items in the in-memory table afterwards: 4
```

Use `make invoke EVENT=events/sqs.json HANDLER=handlers.queue.handler` to choose the handler yourself.

## Layout

```
src/
  handlers/
    api.py          HTTP API: POST /items, GET /items/{id}
    queue.py        SQS consumer with partial batch failures
  shared/
    config.py       settings from environment variables, validated once
    log.py          JSON log formatter and per-invocation context
    events.py       HttpRequest, SqsRecord, LambdaContext, json_response
    middleware.py   @lambda_handler: config, logging context, error logging
    items.py        the example model and its DynamoDB storage
  requirements.txt  runtime dependencies for `sam build` (empty: boto3 is in the runtime)
events/             sample events and seed data
scripts/invoke.py   local invoke
tests/              pytest suite
template.yaml       SAM template
Makefile
```

`src/` is what gets packaged (`CodeUri: src/`), so handler paths are `handlers.api.handler` and `handlers.queue.handler`.

## What the pieces do

**Handlers.** `api.py` maps route keys to functions. A bad request becomes a 400 with a message, an unknown route a 404, and an unexpected error a 500 that carries only the request id while the traceback goes to the log. `queue.py` stores each message and returns `batchItemFailures`, so one bad message does not make the whole batch retry.

**Typed events.** `HttpRequest.from_event` reads an API Gateway HTTP API event (payload format 2.0): method, path, route key, path and query parameters, lower-cased headers, and the body, base64-decoded when needed. `SqsRecord` exposes the message id, body and receive count. Only the fields the handlers use are modelled.

**Configuration.** `Config.from_env` reads these variables and fails on the first invocation with a clear message if one is wrong:

| Variable | Required | Default | Meaning |
| --- | --- | --- | --- |
| `TABLE_NAME` | yes | | DynamoDB table for items |
| `LOG_LEVEL` | no | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL` |
| `SERVICE_NAME` | no | `lambda-python-starter` | value of the `service` log field |

**Logging.** One JSON object per line with `timestamp`, `level`, `message`, `service`, `logger`, `aws_request_id`, `function_name` and `cold_start`. Anything passed as `extra={...}` becomes a top-level field:

```python
logger.info("item created", extra={"item_id": item.id})
```

Exceptions are logged with the traceback in an `exception` field. Request bodies are not logged. `boto3`, `botocore` and `urllib3` loggers are kept at `WARNING` or above.

**`@lambda_handler`.** Wraps each handler: loads the configuration, sets up logging, attaches the request context to every log line, and logs then re-raises unhandled exceptions so Lambda still records the invocation as failed.

## Tests

```bash
make test
```

69 tests. `tests/conftest.py` sets dummy credentials for every test and points the AWS config files at empty paths. Handlers are called with the files in `events/` and a moto DynamoDB table. `tests/test_project.py` checks that the template and the code agree: handler paths resolve to real functions, the routes in the template match the routes in `api.py`, the environment variables match what `config.py` reads, and the IAM statements are limited to the table.

## The SAM template

`template.yaml` defines:

- `ApiFunction` behind an HTTP API with `POST /items` and `GET /items/{id}`
- `QueueFunction` reading `ItemsQueue` in batches of 10 with `ReportBatchItemFailures`
- `ItemsTable`, a DynamoDB table with on-demand billing
- `ItemsDeadLetterQueue`, which receives a message after three failed deliveries

Permissions the functions get:

| Function | IAM actions | Resource |
| --- | --- | --- |
| `ApiFunction` | `dynamodb:GetItem`, `dynamodb:PutItem` | `ItemsTable` |
| `QueueFunction` | `dynamodb:PutItem` | `ItemsTable` |

SAM also adds the basic execution role for CloudWatch Logs to both functions and the SQS polling permissions to `QueueFunction`.

How far the template has been checked:

- `make lint-template` (`cfn-lint template.yaml`, after `pip install cfn-lint`) passes with cfn-lint 1.60.0. It runs offline.
- The tests described above pass.
- `make validate`, `make build` and `make deploy` call the SAM CLI. They are provided but **have not been run**, and the stack has never been deployed. Expect to fix something on your first deploy.

`make deploy` creates billable resources in your account. The HTTP API has no authorizer, so anyone who knows the URL can call it; add one before putting real data behind it.

## Making it yours

1. Replace `src/shared/items.py` with your own model and storage.
2. Edit the routes in `src/handlers/api.py`, or add a module under `src/handlers/` and a matching function in `template.yaml`.
3. Add an event file under `events/` for each new case and use it in a test and with `make invoke`.
4. List runtime dependencies in `src/requirements.txt` and in `pyproject.toml`.

## Checklist

- [x] Project layout with shared code and several handlers
- [x] Typed event models (HTTP API v2 and SQS)
- [x] Unit tests with sample events
- [x] Local invoke script
- [x] Structured JSON logging
- [x] Validated configuration from environment variables
- [x] CI workflow and a SAM template (template linted, not deployed)
- [ ] Event models for more sources (EventBridge, S3, DynamoDB streams)
- [ ] Tracing and metrics
- [ ] Deployment workflow

## Limitations

- Never deployed. Behaviour inside the real Lambda runtime (the log handler replacement, cold start flag, IAM permissions, API Gateway integration) is untested there.
- Local invoke always uses the in-memory fake. It cannot call real AWS, and it does not emulate API Gateway routing, timeouts or memory limits. Use `sam local invoke` for a closer emulation.
- The API handler has no authentication and no pagination or list endpoint.
- `ItemStore.put` replaces an existing item with the same id.
- The CI workflow runs the tests only. It has not run on GitHub yet.

## Contributing

Issues and pull requests are welcome. Keep the starter small: a change should be something most new Lambda projects need, with a test and a sample event.

Built and maintained by [Narayana Vemburaj](https://github.com/narayana006).

## License

[MIT](LICENSE)
