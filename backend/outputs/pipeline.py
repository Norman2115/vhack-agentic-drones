"""
Output & Integration Layer
──────────────────────────
Three output channels that match the architecture diagram:

  WebSocketStream  – Live push to frontend
  DecisionLogger   – Per-node audit trail
  SelfHealing      – Reassign failed sectors

Each class is independent and can be enabled/disabled individually.
All three consume AgentState without modifying it.

Integration
-----------
  Instantiate once per swarm run.
  Pass swarm_outputs to OutputPipeline.process(state) after each tick.
"""

from __future__ import annotations
import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable


# ─── WebSocket Stream ─────────────────────────────────────────────────────────

@dataclass
class WebSocketStream:
    """
    Pushes typed events to the frontend dashboard.

    Event types emitted by the agent loop:
      drone_state     – position, battery, status update
      decision        – routing decision + reason
      task_event      – CFP / bid / award lifecycle
      survivor_alert  – detection and confirmation events
      swarm_health    – registry summary + peer evictions

    Integration:
      Provide an async sink function that delivers to your WS server.
      Example using websockets library:

        async def sink(event: dict) -> None:
            await ws.send(json.dumps(event))

        stream = WebSocketStream(sink=sink)
    """
    sink: Callable[[dict], Awaitable[None]] | None = None
    _buffer: list[dict] = field(default_factory=list, init=False)

    async def flush(self, events: list[dict]) -> None:
        """Push all queued events from a tick."""
        for event in events:
            self._buffer.append(event)
            if self.sink:
                try:
                    await self.sink(event)
                except Exception as e:
                    print(f"[WebSocketStream] Sink error: {e}")

    def get_buffered(self, event_type: str | None = None) -> list[dict]:
        """Return buffered events, optionally filtered by type."""
        if event_type:
            return [e for e in self._buffer if e.get("type") == event_type]
        return list(self._buffer)

    def clear_buffer(self) -> None:
        self._buffer.clear()


# ─── Decision Logger ──────────────────────────────────────────────────────────

@dataclass
class DecisionLogger:
    """
    Appends every LangGraph node transition to a persistent audit trail.

    Log entry schema:
      tick        – agent loop tick number
      drone_id    – which drone
      node        – LangGraph node name
      summary     – human-readable reason
      battery     – battery at time of entry
      position    – {x, y, z}
      timestamp   – epoch float

    Integration:
      Default: in-memory list (good for testing).
      For production: implement a writer that appends to PostgreSQL / S3 / file.

        async def writer(entry: dict) -> None:
            await db.execute("INSERT INTO decisions ...", entry)

        logger = DecisionLogger(writer=writer)
    """
    writer: Callable[[dict], Awaitable[None]] | None = None
    _log: list[dict] = field(default_factory=list, init=False)

    async def record(self, entries: list[dict]) -> None:
        """Persist new log entries from a tick."""
        for entry in entries:
            self._log.append(entry)
            if self.writer:
                try:
                    await self.writer(entry)
                except Exception as e:
                    print(f"[DecisionLogger] Writer error: {e}")

    def query(
        self,
        drone_id: str | None = None,
        node:     str | None = None,
        since:    float | None = None,
    ) -> list[dict]:
        """Filter the audit log."""
        entries = self._log
        if drone_id:
            entries = [e for e in entries if e.get("drone_id") == drone_id]
        if node:
            entries = [e for e in entries if e.get("node") == node]
        if since:
            entries = [e for e in entries if e.get("timestamp", 0) >= since]
        return entries

    def to_jsonl(self) -> str:
        """Export the full audit trail as JSONL."""
        return "\n".join(json.dumps(e) for e in self._log)


# ─── Self-Healing ─────────────────────────────────────────────────────────────

@dataclass
class SelfHealing:
    """
    Detects peer failures and triggers sector reassignment via Contract Net.

    How it works:
      1. GossipHandler evicts stale peers → emits swarm_health events
      2. SelfHealing receives those events and identifies vacated sectors
      3. It injects a new Contract Net CFP into the message bus so the
         nearest available drone is assigned to the lost sector

    Integration:
      Pass the shared message bus and call .process_evictions() each tick.
    """
    message_bus: asyncio.Queue
    _handled: set[str] = field(default_factory=set, init=False)

    async def process_evictions(self, ws_events: list[dict]) -> list[str]:
        """
        Scan the tick's WS events for peer_lost entries.
        Reassigns the lost drone's sector and returns the list of drone IDs handled.
        """
        healed: list[str] = []
        for event in ws_events:
            if event.get("type") != "swarm_health":
                continue
            evicted = event.get("payload", {}).get("stale_evicted", [])
            for drone_id in evicted:
                if drone_id in self._handled:
                    continue
                self._handled.add(drone_id)
                await self._reassign_sector(drone_id)
                healed.append(drone_id)
        return healed

    async def _reassign_sector(self, lost_drone_id: str) -> None:
        """
        Broadcast a CFP to reclaim the lost drone's sector.
        The Contract Net Protocol will select the best-placed available drone.
        """
        import uuid
        cfp = {
            "channel": "contractnet_cfp",
            "sender":  "self_healing",
            "payload": {
                "task_id":     str(uuid.uuid4())[:8],
                "task_type":   "explore",
                "position":    {"x": 0, "y": 0, "z": 0},   # Will be refined by CNP
                "priority":    7,
                "issuer_id":   "self_healing",
                "deadline":    time.time() + 60,
                "description": f"Sector reassignment — drone {lost_drone_id} offline",
            },
        }
        await self.message_bus.put(cfp)
        print(f"[SelfHealing] CFP broadcast for lost drone {lost_drone_id}")


# ─── Output Pipeline ──────────────────────────────────────────────────────────

@dataclass
class OutputPipeline:
    """
    Combines all three output channels into a single post-tick call.
    Wire this to the swarm runner after each DroneGraph.tick().
    """
    ws_stream:    WebSocketStream
    logger:       DecisionLogger
    self_healing: SelfHealing

    async def process(self, state: "AgentState") -> None:     # noqa: F821
        """
        Called once per tick per drone.
        Flushes WS events, records decisions, and handles any peer evictions.
        """
        await self.ws_stream.flush(state.ws_events)
        await self.logger.record(state.decision_log)
        await self.self_healing.process_evictions(state.ws_events)