"""DynamoDB repository using the documented mission_id/sample_key schema.

The ROBOT# partition stores a strongly consistent last snapshot plus a bounded,
time-ordered telemetry history. DEVICE# stores the device binding and the
monotonic sequence guard. Mission samples are additionally stored in their
mission partition for trace queries.
"""
from __future__ import annotations

import json
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing import Any

from boto3.dynamodb.conditions import Attr, Key

from .repository import Repository


class DynamoRepository(Repository):
    def __init__(
        self,
        region: str,
        missions_table: str,
        telemetry_table: str,
        *,
        telemetry_retention_days: int = 30,
        resource: Any | None = None,
    ):
        if resource is None:
            import boto3

            resource = boto3.resource("dynamodb", region_name=region)
        self.missions = resource.Table(missions_table)
        self.telemetry = resource.Table(telemetry_table)
        self.telemetry_retention_days = telemetry_retention_days

    def create_mission(self, mission: dict[str, Any]) -> None:
        from boto3.dynamodb.types import TypeSerializer

        serializer = TypeSerializer()
        wire = lambda value: serializer.serialize(_safe(value))
        lock = {
            "mission_id": f"ROBOT#{mission['robot_id']}",
            "active_mission_id": mission["mission_id"],
        }
        client = self.missions.meta.client
        try:
            client.transact_write_items(
                TransactItems=[
                    {
                        "Put": {
                            "TableName": self.missions.name,
                            "Item": {k: wire(v) for k, v in _safe(mission).items()},
                            "ConditionExpression": "attribute_not_exists(mission_id)",
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.missions.name,
                            "Item": {k: wire(v) for k, v in lock.items()},
                            "ConditionExpression": "attribute_not_exists(active_mission_id)",
                        }
                    },
                ]
            )
        except client.exceptions.TransactionCanceledException as ex:
            raise ValueError("El robot ya tiene una misión pendiente o activa") from ex

    def get_mission(self, mission_id: str) -> dict[str, Any] | None:
        return self.missions.get_item(
            Key={"mission_id": mission_id}, ConsistentRead=True
        ).get("Item")

    def get_active_mission(self, robot_id: str) -> dict[str, Any] | None:
        lock = self.missions.get_item(
            Key={"mission_id": f"ROBOT#{robot_id}"}, ConsistentRead=True
        ).get("Item")
        mission_id = lock.get("active_mission_id") if lock else None
        mission = self.get_mission(mission_id) if mission_id else None
        return mission if mission and mission.get("status") in ("PENDING", "ACTIVE") else None

    def latest_command_sequence(self, robot_id: str) -> int:
        response = self.missions.query(
            IndexName="robot_created",
            KeyConditionExpression=Key("robot_id").eq(robot_id),
            ScanIndexForward=False,
            Limit=1,
            ProjectionExpression="#seq",
            ExpressionAttributeNames={"#seq": "command_sequence"},
        )
        items = response.get("Items", [])
        return int(items[0].get("command_sequence") or 0) if items else 0

    def update_mission(self, mission: dict[str, Any]) -> None:
        if mission["status"] not in ("COMPLETED", "CANCELLED", "FAILED"):
            self.missions.put_item(
                Item=_safe(mission), ConditionExpression="attribute_exists(mission_id)"
            )
            return

        from boto3.dynamodb.types import TypeSerializer

        serializer = TypeSerializer()
        wire = lambda value: serializer.serialize(_safe(value))
        client = self.missions.meta.client
        lock_id = f"ROBOT#{mission['robot_id']}"
        lock = self.missions.get_item(
            Key={"mission_id": lock_id}, ConsistentRead=True
        ).get("Item", {})
        if lock.get("active_mission_id") != mission["mission_id"]:
            self.missions.put_item(
                Item=_safe(mission), ConditionExpression="attribute_exists(mission_id)"
            )
            return
        try:
            client.transact_write_items(
                TransactItems=[
                    {
                        "Put": {
                            "TableName": self.missions.name,
                            "Item": {k: wire(v) for k, v in _safe(mission).items()},
                            "ConditionExpression": "attribute_exists(mission_id)",
                        }
                    },
                    {
                        "Delete": {
                            "TableName": self.missions.name,
                            "Key": {"mission_id": wire(lock_id)},
                            "ConditionExpression": "active_mission_id = :mission",
                            "ExpressionAttributeValues": {":mission": wire(mission["mission_id"])},
                        }
                    },
                ]
            )
        except client.exceptions.TransactionCanceledException:
            current = self.missions.get_item(
                Key={"mission_id": lock_id}, ConsistentRead=True
            ).get("Item", {})
            if current.get("active_mission_id") == mission["mission_id"]:
                raise
            self.missions.put_item(
                Item=_safe(mission), ConditionExpression="attribute_exists(mission_id)"
            )

    def list_missions(
        self, robot_id: str | None, limit: int, cursor: str | None
    ) -> tuple[list[dict[str, Any]], str | None]:
        start = json.loads(cursor) if cursor else None
        if robot_id:
            params: dict[str, Any] = {
                "IndexName": "robot_created",
                "KeyConditionExpression": Key("robot_id").eq(robot_id),
                "ScanIndexForward": False,
                "Limit": limit,
            }
            if start:
                params["ExclusiveStartKey"] = start
            response = self.missions.query(**params)
            next_key = response.get("LastEvaluatedKey")
            return response.get("Items", []), json.dumps(next_key) if next_key else None

        # Broad administrative listing is intentionally paginated; lock rows have
        # no created_at and are excluded. Normal UI requests use the indexed path.
        items: list[dict[str, Any]] = []
        next_key = start
        while len(items) < limit:
            params = {"Limit": max(1, limit - len(items)), "FilterExpression": Attr("created_at").exists()}
            if next_key:
                params["ExclusiveStartKey"] = next_key
            response = self.missions.scan(**params)
            items.extend(response.get("Items", []))
            next_key = response.get("LastEvaluatedKey")
            if not next_key:
                break
        # Return the service continuation key, not a key reconstructed from a
        # filtered item; this correctly resumes across filtered scan pages.
        return items[:limit], json.dumps(next_key) if next_key else None

    def latest_telemetry(self, robot_id: str) -> dict[str, Any] | None:
        response = self.telemetry.get_item(
            Key={"mission_id": f"ROBOT#{robot_id}", "sample_key": "LATEST"},
            ConsistentRead=True,
        )
        item = response.get("Item")
        if item is None:
            return None
        item["mission_id"] = item.pop("reported_mission_id", None)
        return item

    def append_telemetry(self, data: dict[str, Any]) -> bool:
        from boto3.dynamodb.types import TypeSerializer

        robot_id = data["robot_id"]
        device_partition = f"DEVICE#{robot_id}"
        binding_key = {"mission_id": device_partition, "sample_key": "BINDING"}
        try:
            self.telemetry.put_item(
                Item={**binding_key, "device_id": data["device_id"]},
                ConditionExpression="attribute_not_exists(mission_id)",
            )
        except self.telemetry.meta.client.exceptions.ConditionalCheckFailedException:
            existing = self.telemetry.get_item(
                Key=binding_key, ConsistentRead=True
            ).get("Item", {})
            if existing.get("device_id") != data["device_id"]:
                raise ValueError("device_id no coincide con el dispositivo vinculado al robot")

        serializer = TypeSerializer()
        wire = lambda value: serializer.serialize(_safe(value))
        sample_key = data.get("sample_key") or f"{data['timestamp']}#{data['sequence']:020d}"
        mission_id = data.get("mission_id")
        sample_partition = mission_id or f"ROBOT#{robot_id}"
        expires_at = int((datetime.now(timezone.utc) + timedelta(days=self.telemetry_retention_days)).timestamp())
        sample = dict(data, mission_id=sample_partition, sample_key=sample_key, expires_at=expires_at)
        latest = dict(
            data,
            mission_id=f"ROBOT#{robot_id}",
            sample_key="LATEST",
            reported_mission_id=mission_id,
        )
        sequence_key = {"mission_id": device_partition, "sample_key": "SEQUENCE_STATE"}
        writes = [
            {
                "Update": {
                    "TableName": self.telemetry.name,
                    "Key": {k: wire(v) for k, v in sequence_key.items()},
                    "UpdateExpression": "SET #seq = :seq, #ts = :ts",
                    "ConditionExpression": "(attribute_not_exists(#seq) OR #seq < :seq) AND (attribute_not_exists(#ts) OR #ts < :ts)",
                    "ExpressionAttributeNames": {"#seq": "sequence", "#ts": "timestamp"},
                    "ExpressionAttributeValues": {
                        ":seq": wire(data["sequence"]),
                        ":ts": wire(data["timestamp"]),
                    },
                }
            },
            {
                "Put": {
                    "TableName": self.telemetry.name,
                    "Item": {k: wire(v) for k, v in latest.items()},
                    "ConditionExpression": "attribute_not_exists(sequence) OR sequence < :seq",
                    "ExpressionAttributeValues": {":seq": wire(data["sequence"])},
                }
            },
        ]
        writes.append(
            {
                "Put": {
                    "TableName": self.telemetry.name,
                    "Item": {k: wire(v) for k, v in sample.items()},
                    "ConditionExpression": "attribute_not_exists(mission_id) AND attribute_not_exists(sample_key)",
                }
            }
        )
        try:
            self.telemetry.meta.client.transact_write_items(TransactItems=writes)
            return True
        except self.telemetry.meta.client.exceptions.TransactionCanceledException:
            return False

    def list_trace(
        self, mission_id: str, limit: int, cursor: str | None
    ) -> tuple[list[dict[str, Any]], str | None]:
        params: dict[str, Any] = {
            "KeyConditionExpression": Key("mission_id").eq(mission_id),
            "Limit": limit,
            "ScanIndexForward": True,
        }
        if cursor:
            params["ExclusiveStartKey"] = json.loads(cursor)
        response = self.telemetry.query(**params)
        next_key = response.get("LastEvaluatedKey")
        return response.get("Items", []), json.dumps(next_key) if next_key else None


def _safe(value: Any) -> Any:
    """DynamoDB's numeric type is Decimal; boto3 rejects native float values."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe(v) for v in value]
    return value
