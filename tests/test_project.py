"""Checks that the template, the event files and the local invoke script agree with the code."""

import importlib
import json
import re
from pathlib import Path

import pytest
import yaml

import invoke

from conftest import EVENTS, load_event

ROOT = Path(__file__).resolve().parent.parent


class CfnLoader(yaml.SafeLoader):
    """SafeLoader that tolerates CloudFormation short-form tags such as !Ref and !GetAtt."""


def _tagged(loader, suffix, node):
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node)
    else:
        value = loader.construct_mapping(node)
    return {suffix: value}


CfnLoader.add_multi_constructor("!", _tagged)


@pytest.fixture(scope="module")
def template():
    return yaml.load((ROOT / "template.yaml").read_text(), Loader=CfnLoader)


def functions(template):
    return {name: res["Properties"] for name, res in template["Resources"].items()
            if res["Type"] == "AWS::Serverless::Function"}


def test_template_handlers_point_at_real_functions(template):
    assert template["Transform"] == "AWS::Serverless-2016-10-31"
    assert template["Globals"]["Function"]["CodeUri"] == "src/"
    handlers = {name: props["Handler"] for name, props in functions(template).items()}
    assert handlers == {"ApiFunction": "handlers.api.handler", "QueueFunction": "handlers.queue.handler"}
    for dotted in handlers.values():
        module_name, _, attribute = dotted.rpartition(".")
        assert callable(getattr(importlib.import_module(module_name), attribute))


def test_template_sets_the_environment_the_config_reads(template):
    variables = template["Globals"]["Function"]["Environment"]["Variables"]
    assert set(variables) == {"TABLE_NAME", "LOG_LEVEL", "SERVICE_NAME"}
    assert variables["TABLE_NAME"] == {"Ref": "ItemsTable"}


def test_template_routes_match_the_api_handler(template):
    from handlers.api import ROUTES
    events = functions(template)["ApiFunction"]["Events"].values()
    declared = {f"{e['Properties']['Method']} {e['Properties']['Path']}" for e in events}
    assert declared == set(ROUTES)


def test_template_queue_wiring(template):
    source = functions(template)["QueueFunction"]["Events"]["Items"]["Properties"]
    assert source["FunctionResponseTypes"] == ["ReportBatchItemFailures"]
    queue = template["Resources"]["ItemsQueue"]["Properties"]
    assert queue["VisibilityTimeout"] >= template["Globals"]["Function"]["Timeout"]
    assert queue["RedrivePolicy"]["deadLetterTargetArn"] == {"GetAtt": "ItemsDeadLetterQueue.Arn"}


def test_template_policies_are_scoped_to_the_table(template):
    for props in functions(template).values():
        for policy in props["Policies"]:
            for statement in policy["Statement"]:
                assert statement["Resource"] == {"GetAtt": "ItemsTable.Arn"}
                actions = statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
                assert all(a.startswith("dynamodb:") and "*" not in a for a in actions)


@pytest.mark.parametrize("path", sorted(EVENTS.glob("*.json")), ids=lambda p: p.name)
def test_event_files_are_valid_json_with_fake_account_ids(path):
    text = path.read_text()
    json.loads(text)
    # Account ids, in ARNs or accountId fields, must be the documentation placeholder.
    accounts = re.findall(r":(\d{12}):", text) + re.findall(r'"accountId": "(\d+)"', text)
    assert set(accounts) <= {"123456789012"}


def test_pick_handler():
    assert invoke.pick_handler(load_event("sqs.json")) == "handlers.queue.handler"
    assert invoke.pick_handler(load_event("api.json")) == "handlers.api.handler"
    assert invoke.pick_handler({}) == "handlers.api.handler"


def test_invoke_api_event_reads_the_seeded_item():
    result, count = invoke.invoke(load_event("api.json"), seed_file=EVENTS / "seed_items.json")
    assert result["statusCode"] == 200
    assert json.loads(result["body"]) == {"id": "item-001", "name": "Blue widget", "quantity": 3}
    assert count == 2


def test_invoke_main_prints_result(capsys):
    assert invoke.main([str(EVENTS / "sqs.json")]) == 0
    out = capsys.readouterr().out
    assert "invoking handlers.queue.handler" in out
    assert '"itemIdentifier": "22222222-2222-4222-8222-222222222222"' in out
    assert "items in the in-memory table afterwards: 4" in out


def test_invoke_main_reports_a_missing_event_file(capsys):
    assert invoke.main(["events/does-not-exist.json"]) == 2
    assert "cannot read event file" in capsys.readouterr().err
