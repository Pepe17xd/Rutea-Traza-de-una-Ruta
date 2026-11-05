from pathlib import Path

import yaml


def test_serverless_config_is_http_only_cost_guarded_and_reuses_lab_role():
    config = yaml.safe_load(Path("serverless.yml").read_text(encoding="utf-8"))
    assert config["service"] == "rutea-api"
    assert config["frameworkVersion"] == "4.43.0"
    assert config["provider"]["runtime"] == "python3.12"
    assert config["provider"]["region"] == "${opt:region, env:AWS_REGION, 'us-east-1'}"
    assert config["provider"]["iam"]["role"] == "arn:aws:iam::${env:AWS_ACCOUNT_ID}:role/LabRole"
    assert "httpApi" not in config["provider"]  # SPA y API usan el mismo origen HTTPS.
    resources = config["resources"]["Resources"]
    conditions = config["resources"]["Conditions"]
    assert resources["MissionsTable"]["Condition"] == "CreateMissionsTable"
    assert resources["TelemetryTable"]["Condition"] == "CreateTelemetryTable"
    assert conditions["CreateMissionsTable"]["Fn::Equals"] == ["${param:createMissionsTable, 'false'}", "true"]
    assert conditions["CreateTelemetryTable"]["Fn::Equals"] == ["${param:createTelemetryTable, 'false'}", "true"]
    assert {name for name, resource in resources.items() if resource.get("Type") == "AWS::DynamoDB::Table"} == {"MissionsTable", "TelemetryTable"}
    for name in ("MissionsTable", "TelemetryTable"):
        assert resources[name]["DeletionPolicy"] == "Retain"
        assert resources[name]["UpdateReplacePolicy"] == "Retain"
    assert config["resources"]["Resources"]["TelemetryTable"]["Properties"]["BillingMode"] == "PAY_PER_REQUEST"
    assert "ApiBaseUrl" in config["resources"]["Outputs"]
    assert "FrontendUrl" in config["resources"]["Outputs"]
    assert config["resources"]["Resources"]["ApiLogGroup"]["Properties"]["RetentionInDays"] == 7
    assert config["functions"]["api"]["handler"] == "app.lambda_handler.handler"
    assert all("websocket" not in str(event).lower() for event in config["functions"]["api"]["events"])
    assert "scikit-learn" not in Path("requirements-lambda.txt").read_text(encoding="utf-8")
    assert "mangum" in Path("requirements-lambda.txt").read_text(encoding="utf-8")
    assert not config.get("plugins")
    assert Path("package.json").read_text(encoding="utf-8").find("serverless-python-requirements") == -1
