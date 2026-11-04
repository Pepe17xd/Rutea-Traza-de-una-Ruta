import json

import pytest

pytest.importorskip("mangum", reason="instalar Backend con el extra [aws] para comprobar Mangum")

from app.lambda_handler import handler


def test_mangum_serves_fastapi_health_from_http_api_event():
    event = {
        "version": "2.0",
        "routeKey": "GET /api/v1/health",
        "rawPath": "/api/v1/health",
        "rawQueryString": "",
        "headers": {"host": "example.execute-api.us-east-1.amazonaws.com"},
        "requestContext": {
            "http": {
                "method": "GET",
                "path": "/api/v1/health",
                "protocol": "HTTP/1.1",
                "sourceIp": "127.0.0.1",
                "userAgent": "test",
            }
        },
        "isBase64Encoded": False,
    }

    response = handler(event, {})

    assert response["statusCode"] == 200
    payload = json.loads(response["body"])
    assert payload["status"] == "ok"
    assert payload["control_plane"] == "coordination_only"
