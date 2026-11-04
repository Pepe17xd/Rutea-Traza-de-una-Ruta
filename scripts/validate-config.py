from pathlib import Path

try:
    import yaml
    from yaml.nodes import MappingNode, ScalarNode, SequenceNode
except ImportError as exc:
    raise SystemExit("Falta PyYAML para validar configuracion. Instale las dependencias de desarrollo de Backend.") from exc


class CloudFormationLoader(yaml.SafeLoader):
    pass


def unknown_tag(loader, suffix, node):
    if isinstance(node, ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, MappingNode):
        return loader.construct_mapping(node)
    return None


CloudFormationLoader.add_multi_constructor("!", unknown_tag)
root = Path(__file__).resolve().parents[1]
compose_path = root / "serverless-compose.yml"
backend_path = root / "Backend/serverless.yml"
compose = yaml.load(compose_path.read_text(encoding="utf-8"), Loader=CloudFormationLoader)
backend = yaml.load(backend_path.read_text(encoding="utf-8"), Loader=CloudFormationLoader)

services = compose.get("services", {})
assert set(services) == {"api"}, "Compose debe desplegar solo el servicio API; el frontend se empaqueta con FastAPI"
assert services["api"].get("path") == "Backend"
assert backend["service"] == "rutea-api"
provider = backend["provider"]
assert provider["runtime"] == "python3.12"
assert provider["region"] == "${opt:region, env:AWS_REGION, 'us-east-1'}"
assert provider["iam"]["role"] == "arn:aws:iam::${env:AWS_ACCOUNT_ID}:role/LabRole"
assert "role" not in provider or isinstance(provider["role"], str)
assert backend["functions"]["api"]["handler"] == "app.lambda_handler.handler"
assert backend["functions"]["api"]["events"]
assert backend["resources"]["Resources"]["MissionsTable"]["DeletionPolicy"] == "Retain"
assert backend["resources"]["Resources"]["TelemetryTable"]["DeletionPolicy"] == "Retain"
assert backend["resources"]["Resources"]["ApiLogGroup"]["Properties"]["RetentionInDays"] <= 14
outputs = backend["resources"]["Outputs"]
assert "FrontendUrl" in outputs and "ApiBaseUrl" in outputs
assert "HttpApi" in str(outputs["FrontendUrl"]["Value"])
assert not (root / "Frontend/serverless.yml").exists(), "La compilacion estatica no debe ser una infraestructura ficticia separada"
print("Validacion local de Compose, Serverless, IAM LabRole, API y retencion DynamoDB aprobada (sin llamadas AWS).")
