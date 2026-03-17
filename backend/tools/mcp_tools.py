"""
MCP Tools Layer
───────────────
Exposes the standardised tool interface used by every drone agent.
Each tool is a plain async function. Swap the body for real hardware
or simulation backends without touching the LangGraph nodes above.

Tools
-----
  move_to()           – navigate to a target position
  thermal_scan()      – run IR sensor sweep
  get_battery()       – read current battery level
  broadcast_status()  – gossip own state to peers
  announce_task()     – Contract Net CFP broadcast
  submit_bid()        – Contract Net bid submission
  claim_task()        – Contract Net task award

Integration
-----------
  Implement MCPBackend to connect to real hardware, ROS2, or a sim.
  Pass the backend to DroneTools.__init__ and everything else stays unchanged.
"""

from __future__ import annotations
import asyncio
import math
import random
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any

from langchain.tools import tool

from config.types import (
    AgentState, Bid, DroneStatus, Position, ScanResult,
    TaskAnnouncement, TaskType,
)


# ─── Backend Interface ────────────────────────────────────────────────────────

class MCPBackend(ABC):
    """
    Swap this to integrate real hardware / ROS2 / DJI SDK / sim.
    All drone tools delegate to this interface.
    """

    @abstractmethod
    async def navigate(self, drone_id: str, target: Position) -> bool:
        """Returns True when the drone reaches the target."""

    @abstractmethod
    async def read_thermal(self, drone_id: str, position: Position) -> dict[str, Any]:
        """Returns raw sensor payload from the IR camera."""

    @abstractmethod
    async def read_battery(self, drone_id: str) -> float:
        """Returns battery level 0.0 – 1.0."""

    @abstractmethod
    async def send_message(self, drone_id: str, channel: str, payload: dict) -> None:
        """Sends a message on the given comm channel (gossip / contractnet)."""


# ─── Simulation Backend (default) ─────────────────────────────────────────────

class SimulationBackend(MCPBackend):
    """
    Lightweight in-process simulation for development and testing.
    Replace with RealHardwareBackend for production deployments.
    """

    def __init__(self, shared_message_bus: asyncio.Queue):
        self._bus = shared_message_bus
        self._positions: dict[str, Position] = {}
        self._batteries: dict[str, float] = {}

    async def navigate(self, drone_id: str, target: Position) -> bool:
        current = self._positions.get(drone_id, Position(0, 0))
        dist    = current.distance_to(target)
        await asyncio.sleep(min(dist * 0.01, 0.5))   # Simulated travel time
        self._positions[drone_id] = target
        return True

    async def read_thermal(self, drone_id: str, position: Position) -> dict[str, Any]:
        await asyncio.sleep(0.05)
        # ~10% survivor detection probability per scan
        return {
            "thermal_detected": random.random() < 0.10,
            "motion_detected":  random.random() < 0.08,
            "confidence":       round(random.uniform(0.6, 0.99), 3),
            "raw_temp_celsius": round(random.uniform(20, 38), 2),
        }

    async def read_battery(self, drone_id: str) -> float:
        level = self._batteries.get(drone_id, 1.0)
        level = max(0.0, level - random.uniform(0.01, 0.03))
        self._batteries[drone_id] = level
        return round(level, 3)

    async def send_message(self, drone_id: str, channel: str, payload: dict) -> None:
        await self._bus.put({"channel": channel, "sender": drone_id, "payload": payload})


# ─── MCP Tool Suite ───────────────────────────────────────────────────────────

class DroneTools:
    """
    The full MCP tool suite for a single drone.
    Instantiate one per drone and inject into the LangGraph nodes.
    """

    def __init__(self, drone_id: str, backend: MCPBackend):
        self.drone_id = drone_id
        self._backend = backend

    # ── Navigation ────────────────────────────────────────────────────────────

    async def move_to(self, target: Position, state: AgentState) -> bool:
        """Navigate drone to target coordinates."""
        success = await self._backend.navigate(self.drone_id, target)
        if success:
            state.self_state.position = target
            state.emit_ws("drone_state", {
                "event": "moved",
                "position": target.to_dict(),
            })
            state.log("move_to", f"Moved to {target.to_dict()}")
        return success

    # ── Sensing ───────────────────────────────────────────────────────────────

    async def thermal_scan(self, state: AgentState) -> ScanResult:
        """Run thermal + motion detection at current position."""
        raw = await self._backend.read_thermal(self.drone_id, state.self_state.position)
        result = ScanResult(
            drone_id         = self.drone_id,
            position         = state.self_state.position,
            thermal_detected = raw["thermal_detected"],
            motion_detected  = raw["motion_detected"],
            confidence       = raw["confidence"],
        )
        state.last_scan = result
        state.log("thermal_scan", f"Scan complete — thermal={result.thermal_detected} motion={result.motion_detected}")
        return result

    # ── Battery ───────────────────────────────────────────────────────────────

    async def get_battery(self, state: AgentState) -> float:
        """Read and update battery level in agent state."""
        level = await self._backend.read_battery(self.drone_id)
        state.self_state.battery = level
        return level

    # ── Gossip ────────────────────────────────────────────────────────────────

    async def broadcast_status(self, state: AgentState) -> None:
        """Gossip own DroneState to all peers."""
        payload = state.self_state.to_dict()
        await self._backend.send_message(self.drone_id, "gossip", payload)
        state.emit_ws("swarm_health", {"event": "gossip_broadcast", "state": payload})

    # ── Contract Net ──────────────────────────────────────────────────────────

    async def announce_task(
        self,
        state:       AgentState,
        task_type:   TaskType,
        position:    Position,
        priority:    int = 5,
        description: str = "",
    ) -> TaskAnnouncement:
        """Broadcast a Call-for-Proposals (CFP) to the swarm."""
        task = TaskAnnouncement(
            task_id     = str(uuid.uuid4())[:8],
            task_type   = task_type,
            position    = position,
            priority    = priority,
            issuer_id   = self.drone_id,
            deadline    = time.time() + 30,
            description = description,
        )
        await self._backend.send_message(self.drone_id, "contractnet_cfp", task.to_dict())
        state.emit_ws("task_event", {"event": "cfp_broadcast", "task": task.to_dict()})
        state.log("announce_task", f"CFP broadcast for task {task.task_id}")
        return task

    async def submit_bid(self, state: AgentState, task: TaskAnnouncement) -> Bid:
        """Compute and submit a bid for an open task."""
        dist  = state.self_state.position.distance_to(task.position)
        batt  = state.self_state.battery
        load  = state.self_state.workload

        # Scoring: higher is better (0–1 range)
        dist_score = 1.0 / (1.0 + dist * 0.01)
        batt_score = batt
        load_score = 1.0 / (1.0 + load)
        score = round((dist_score * 0.5 + batt_score * 0.3 + load_score * 0.2), 4)

        eta = dist / 10.0   # 10 units/s assumed
        bid = Bid(task_id=task.task_id, drone_id=self.drone_id, score=score, eta=eta)

        await self._backend.send_message(self.drone_id, "contractnet_bid", bid.to_dict())
        state.log("submit_bid", f"Bid submitted for {task.task_id} score={score}")
        return bid

    async def claim_task(self, state: AgentState, task: TaskAnnouncement) -> None:
        """Award accepted — mark task as won and update workload."""
        state.won_task              = task
        state.self_state.workload  += 1
        await self._backend.send_message(self.drone_id, "contractnet_award", {
            "task_id": task.task_id, "winner": self.drone_id,
        })
        state.emit_ws("task_event", {"event": "task_claimed", "task": task.to_dict()})
        state.log("claim_task", f"Task {task.task_id} claimed")


# ─── AI Tool Definitions (LangChain format) ───────────────────────────────────

class AITools:
    """
    AI-powered tool definitions for LLM-based decision making.
    These wrap the DroneTools methods with LangChain @tool decorators.
    """

    def __init__(self, drone_tools: DroneTools):
        self._tools = drone_tools

    @tool
    async def scan_thermal(self, state: AgentState) -> dict:
        """
        Run thermal + motion sensor scan at current drone position.
        Returns detection results (thermal_detected, motion_detected, confidence).
        Use this to detect survivors in the area.
        """
        scan_result = await self._tools.thermal_scan(state)
        return {
            "thermal_detected": scan_result.thermal_detected,
            "motion_detected": scan_result.motion_detected,
            "confidence": scan_result.confidence,
            "position": scan_result.position.to_dict(),
        }

    @tool
    async def navigate_to(self, target_x: float, target_y: float, state: AgentState) -> bool:
        """
        Navigate drone to target coordinates (x, y).
        Returns True if navigation successful.
        Use when moving to a new sector or target position.
        """
        target = Position(target_x, target_y, state.self_state.position.z)
        return await self._tools.move_to(target, state)

    @tool
    async def read_battery_level(self, state: AgentState) -> float:
        """
        Get current battery percentage (0.0 - 1.0).
        Use to monitor power and decide when to return to base.
        """
        return await self._tools.get_battery(state)

    @tool
    async def broadcast_swarm_status(self, state: AgentState) -> dict:
        """
        Gossip own drone state to all peers.
        Returns swarm registry summary.
        Use to keep peers updated and gather swarm intelligence.
        """
        await self._tools.broadcast_status(state)
        return {"broadcast_sent": True}

    @tool
    async def submit_task_bid(self, task_id: str, priority: int, state: AgentState) -> dict:
        """
        Submit a bid for an open task auction.
        Returns bid score. Higher score = more likely to win.
        Use when you want to volunteer for a task.
        """
        # Find the task in active tasks
        task = next((t for t in state.active_tasks if t.task_id == task_id), None)
        if not task:
            return {"error": f"Task {task_id} not found"}

        bid = await self._tools.submit_bid(state, task)
        return {
            "task_id": task_id,
            "bid_score": bid.score,
            "eta_seconds": bid.eta,
        }

    @tool
    async def announce_survivor_task(self, position_x: float, position_y: float, confidence: float, state: AgentState) -> dict:
        """
        Announce a survivor detection task to the swarm for verification.
        Use when you detect a potential survivor and want other drones to help verify.
        """
        position = Position(position_x, position_y, state.self_state.position.z)
        task = await self._tools.announce_task(
            state,
            task_type=TaskType.VERIFY,
            position=position,
            priority=9,
            description=f"Survivor signature detected — confidence {confidence:.0%}",
        )
        return {"task_id": task.task_id, "announced": True}

    def get_all_tools(self) -> list:
        """Return all AI tools for LLM agent initialization."""
        return [
            self.scan_thermal,
            self.navigate_to,
            self.read_battery_level,
            self.broadcast_swarm_status,
            self.submit_task_bid,
            self.announce_survivor_task,
        ]