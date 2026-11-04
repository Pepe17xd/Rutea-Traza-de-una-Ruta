import asyncio
from collections import defaultdict
from fastapi import WebSocket


class EventHub:
    def __init__(self): self.clients: dict[str, set[WebSocket]] = defaultdict(set)
    async def connect(self, robot_id: str, ws: WebSocket):
        await ws.accept(); self.clients[robot_id].add(ws)
        await ws.send_json({"type": "CONNECTION", "robot_id": robot_id, "connected": True})
    def disconnect(self, robot_id: str, ws: WebSocket): self.clients[robot_id].discard(ws)
    async def publish(self, robot_id: str, payload: dict):
        stale = []
        for ws in list(self.clients[robot_id]):
            try: await ws.send_json(payload)
            except Exception: stale.append(ws)
        for ws in stale: self.disconnect(robot_id, ws)


hub = EventHub()
