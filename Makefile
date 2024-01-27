PYTHON ?= python
EVENT ?= events/api.json
HANDLER ?=

.PHONY: help install test invoke lint-template validate build deploy clean

help:
	@echo "make install                      install the project and dev tools into the current environment"
	@echo "make test                         run the unit tests (in-memory AWS, no account needed)"
	@echo "make invoke EVENT=events/api.json run a handler locally with an event file"
	@echo "make invoke EVENT=... HANDLER=handlers.queue.handler   choose the handler explicitly"
	@echo "make lint-template                cfn-lint template.yaml (needs: pip install cfn-lint; works offline)"
	@echo "make validate                     sam validate --lint (needs the SAM CLI)"
	@echo "make build                        sam build (needs the SAM CLI)"
	@echo "make deploy                       sam deploy --guided (needs the SAM CLI and AWS credentials; creates resources)"

install:
	$(PYTHON) -m pip install -e ".[dev]"

test:
	$(PYTHON) -m pytest

invoke:
	$(PYTHON) scripts/invoke.py $(EVENT) $(if $(HANDLER),--handler $(HANDLER),)

lint-template:
	cfn-lint template.yaml

validate:
	sam validate --lint

build:
	sam build

deploy: build
	sam deploy --guided

clean:
	rm -rf .aws-sam .pytest_cache build dist src/*.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
