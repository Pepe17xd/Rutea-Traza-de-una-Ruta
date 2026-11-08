from types import SimpleNamespace
import pytest

from app.db.dynamodb import DynamoRepository


class ConditionalCheckFailedException(Exception):
    pass


class TransactionCanceledException(Exception):
    pass


class FakeTable:
    def __init__(self, name, client):
        self.name = name
        self.meta = SimpleNamespace(client=client)
        self.calls = []
        self.item = None

    def put_item(self, **kwargs):
        self.calls.append(("put_item", kwargs))

    def get_item(self, **kwargs):
        self.calls.append(("get_item", kwargs))
        return {"Item": self.item} if self.item else {}

    def query(self, **kwargs):
        self.calls.append(("query", kwargs))
        return {"Items": [{"mission_id": "m1", "sequence": 2, "command_sequence": 18}], "LastEvaluatedKey": None}

    def scan(self, **kwargs):
        self.calls.append(("scan", kwargs))
        return {"Items": [], "LastEvaluatedKey": None}


class FakeClient:
    exceptions = SimpleNamespace(
        ConditionalCheckFailedException=ConditionalCheckFailedException,
        TransactionCanceledException=TransactionCanceledException,
    )

    def __init__(self):
        self.transactions = []
        self.cancel_next = False

    def transact_write_items(self, **kwargs):
        self.transactions.append(kwargs)
        if self.cancel_next:
            self.cancel_next = False
            raise TransactionCanceledException("duplicate or stale sample")


class FakeResource:
    def __init__(self):
        self.client = FakeClient()
        self.tables = {
            name: FakeTable(name, self.client) for name in ("missions", "telemetry")
        }

    def Table(self, name):
        return self.tables[name]


def repository():
    resource = FakeResource()
    return DynamoRepository("us-east-1", "missions", "telemetry", resource=resource), resource


def test_latest_telemetry_is_single_consistent_get_not_table_scan():
    repo, resource = repository()
    repo.telemetry.item = {
        "mission_id": "ROBOT#CART-1",
        "sample_key": "LATEST",
        "reported_mission_id": "mission-1",
        "sequence": 8,
        "timestamp": "2026-11-04T12:00:00+00:00",
    }

    result = repo.latest_telemetry("CART-1")

    assert result["mission_id"] == "mission-1"
    assert repo.telemetry.calls == [
        (
            "get_item",
            {
                "Key": {"mission_id": "ROBOT#CART-1", "sample_key": "LATEST"},
                "ConsistentRead": True,
            },
        )
    ]
    assert not any(call[0] == "scan" for call in repo.telemetry.calls)


def test_append_telemetry_transacts_sequence_latest_and_trace_with_ttl():
    repo, resource = repository()
    accepted = repo.append_telemetry(
        {
            "robot_id": "CART-1",
            "device_id": "ESP32-1",
            "mission_id": "mission-1",
            "sequence": 3,
            "timestamp": "2026-11-04T12:00:00+00:00",
            "lat": -12.0,
            "lon": -77.0,
        }
    )

    assert accepted is True
    transaction = resource.client.transactions[0]["TransactItems"]
    assert len(transaction) == 3
    assert "Update" in transaction[0]
    update_values = transaction[0]["Update"]["ExpressionAttributeValues"]
    assert update_values[":seq"] == {"N": "3"}
    assert update_values[":ts"] == {"S": "2026-11-04T12:00:00+00:00"}
    latest = transaction[1]["Put"]["Item"]
    assert transaction[1]["Put"]["ExpressionAttributeValues"][":seq"] == {"N": "3"}
    trace = transaction[2]["Put"]["Item"]
    assert latest["mission_id"]["S"] == "ROBOT#CART-1"
    assert latest["sample_key"]["S"] == "LATEST"
    assert latest["reported_mission_id"]["S"] == "mission-1"
    assert trace["mission_id"]["S"] == "mission-1"
    assert trace["expires_at"]["N"].isdigit()


def test_append_telemetry_rejects_double_serialized_sequence_before_writing():
    from boto3.dynamodb.types import TypeSerializer

    repo, resource = repository()
    data = {
        "robot_id": "CART-1",
        "device_id": "ESP32-1",
        "mission_id": None,
        # This is already an AttributeValue. Serializing it again produces M,
        # which reproduces DynamoDB's '< operand type: M' ValidationException.
        "sequence": {"N": "2"},
        "timestamp": "2026-11-04T12:00:00+00:00",
    }

    assert TypeSerializer().serialize(data["sequence"]) == {"M": {"N": {"S": "2"}}}
    with pytest.raises(ValueError, match="sequence debe ser un entero Python sin serializar"):
        repo.append_telemetry(data)

    # Reject before establishing the binding or sending a transaction.
    assert repo.telemetry.calls == []
    assert resource.client.transactions == []


def test_trace_query_uses_mission_partition_and_resumes_cursor():
    repo, _ = repository()

    items, cursor = repo.list_trace("mission-1", 50, None)

    assert items[0]["mission_id"] == "m1"
    assert cursor is None
    query = repo.telemetry.calls[-1][1]
    assert query["Limit"] == 50
    assert query["ScanIndexForward"] is True

def test_command_sequence_reads_only_latest_robot_index_entry():
    repo, _ = repository()
    assert repo.latest_command_sequence("CART-1") == 18
    params = repo.missions.calls[-1][1]
    assert params["IndexName"] == "robot_created"
    assert params["ScanIndexForward"] is False
    assert params["Limit"] == 1

def test_mission_create_and_terminal_transition_use_atomic_robot_lock():
    repo, resource = repository()
    mission = {"mission_id": "m1", "robot_id": "CART-1", "status": "PENDING"}
    repo.create_mission(mission)
    create = resource.client.transactions[-1]["TransactItems"]
    assert len(create) == 2
    assert create[0]["Put"]["Item"]["mission_id"]["S"] == "m1"
    assert create[1]["Put"]["Item"]["mission_id"]["S"] == "ROBOT#CART-1"

    repo.missions.item = {"active_mission_id": "m1"}
    repo.update_mission({**mission, "status": "CANCELLED"})
    terminal = resource.client.transactions[-1]["TransactItems"]
    assert terminal[0]["Put"]["Item"]["status"]["S"] == "CANCELLED"
    assert terminal[1]["Delete"]["Key"]["mission_id"]["S"] == "ROBOT#CART-1"

def test_dynamo_duplicate_or_stale_sequence_is_rejected_idempotently():
    repo, resource = repository()
    resource.client.cancel_next = True
    data = {
        "robot_id": "CART-1", "device_id": "ESP32-1", "mission_id": None,
        "sequence": 1, "timestamp": "2026-11-04T12:00:00+00:00",
    }
    assert repo.append_telemetry(data) is False
