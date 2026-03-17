"""
Shared types and state definitions for the Drone Swarm system.
All layers import from here — never from each other directly.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Literal, Optional
from enum import Enum
import time


# ─── Enums ────────────────────────────────────────────────────────────────────

class DroneStatus(str, Enum):
    IDLE      = "idle"
    EXPLORING = "exploring"
    VERIFYING = "verifying"
    RETURNING = "returning"
    OFFLINE   = "offline"
    CHARGING  = "charging"

class TaskType(str, Enum):
    EXPLORE  = "explore"
    VERIFY   = "verify"
    ASSIST   = "assist"

class DecisionRoute(str, Enum):
    EXPLORE = "explore"
    VERIFY  = "verify"
    RTB     = "rtb"       # Return to Base
    IDLE    = "idle"


# ─── Core Data Models ─────────────────────────────────────────────────────────

@dataclass
class Position:
    x: float
    y: float
    z: float = 0.0

    def distance_to(self, other: Position) -> float:
        return ((self.x - other.x)**2 + (self.y - other.y)**2 + (self.z - other.z)**2) ** 0.5

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "z": self.z}


@dataclass
class DroneState:
    """Full state snapshot for a single drone — shared via Gossip."""
    drone_id:   str
    position:   Position
    battery:    float           # 0.0 – 1.0
    status:     DroneStatus
    sector:     Optional[str]   # Assigned sector ID
    workload:   int             # Number of pending tasks
    last_seen:  float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "drone_id":  self.drone_id,
            "position":  self.position.to_dict(),
            "battery":   self.battery,
            "status":    self.status.value,
            "sector":    self.sector,
            "workload":  self.workload,
            "last_seen": self.last_seen,
        }

    @staticmethod
    def from_dict(d: dict) -> DroneState:
        return DroneState(
            drone_id  = d["drone_id"],
            position  = Position(**d["position"]),
            battery   = d["battery"],
            status    = DroneStatus(d["status"]),
            sector    = d.get("sector"),
            workload  = d.get("workload", 0),
            last_seen = d.get("last_seen", time.time()),
        )


@dataclass
class ScanResult:
    """Output of a thermal / motion scan."""
    drone_id:         str
    position:         Position
    thermal_detected: bool
    motion_detected:  bool
    confidence:       float      # 0.0 – 1.0
    timestamp:        float = field(default_factory=time.time)

    def has_detection(self) -> bool:
        return self.thermal_detected or self.motion_detected


@dataclass
class TaskAnnouncement:
    """Contract Net CFP broadcast."""
    task_id:      str
    task_type:    TaskType
    position:     Position
    priority:     int           # 1 (low) – 10 (high)
    issuer_id:    str
    deadline:     float         # epoch seconds
    description:  str = ""

    def to_dict(self) -> dict:
        return {
            "task_id":     self.task_id,
            "task_type":   self.task_type.value,
            "position":    self.position.to_dict(),
            "priority":    self.priority,
            "issuer_id":   self.issuer_id,
            "deadline":    self.deadline,
            "description": self.description,
        }


@dataclass
class Bid:
    """Contract Net bid from a drone."""
    task_id:  str
    drone_id: str
    score:    float     # Higher = better bid
    eta:      float     # Seconds to reach target

    def to_dict(self) -> dict:
        return {"task_id": self.task_id, "drone_id": self.drone_id, "score": self.score, "eta": self.eta}


@dataclass
class MissionConfig:
    """Top-level mission parameters passed as input."""
    mission_id:    str
    zone_bounds:   dict             # {min_x, max_x, min_y, max_y}
    objectives:    list[str]        # e.g. ["survivor_search", "mapping"]
    swarm_size:    int
    priority_sectors: list[str]
    max_duration:  float            # seconds
    base_position: Position

    def to_dict(self) -> dict:
        return {
            "mission_id":        self.mission_id,
            "zone_bounds":       self.zone_bounds,
            "objectives":        self.objectives,
            "swarm_size":        self.swarm_size,
            "priority_sectors":  self.priority_sectors,
            "max_duration":      self.max_duration,
            "base_position":     self.base_position.to_dict(),
        }


# ─── LangGraph Agent State ────────────────────────────────────────────────────

@dataclass
class AgentState:
    """
    The full state object that flows through every LangGraph node.
    Extend this — never replace fields; add Optional ones.
    """
    # Identity
    drone_id:     str
    mission:      MissionConfig

    # Runtime state
    self_state:   DroneState
    swarm_registry: dict[str, DroneState] = field(default_factory=dict)  # drone_id → DroneState

    # Inbox / Outbox (cleared each tick)
    inbox:        list[dict[str, Any]]    = field(default_factory=list)
    outbox:       list[dict[str, Any]]    = field(default_factory=list)

    # Detections
    last_scan:    Optional[ScanResult]    = None
    active_tasks: list[TaskAnnouncement]  = field(default_factory=list)
    won_task:     Optional[TaskAnnouncement] = None

    # Routing
    decision:     Optional[DecisionRoute] = None

    # Outputs (appended each tick)
    ws_events:    list[dict[str, Any]]    = field(default_factory=list)
    decision_log: list[dict[str, Any]]    = field(default_factory=list)

    # Tick counter
    tick:         int = 0

    def log(self, node: str, summary: str, extra: dict | None = None):
        """Append a decision log entry — called inside each LangGraph node."""
        self.decision_log.append({
            "tick":      self.tick,
            "drone_id":  self.drone_id,
            "node":      node,
            "summary":   summary,
            "battery":   self.self_state.battery,
            "position":  self.self_state.position.to_dict(),
            "timestamp": time.time(),
            **(extra or {}),
        })

    def emit_ws(self, event_type: str, payload: dict):
        """Queue a WebSocket event for the output layer."""
        self.ws_events.append({
            "type":      event_type,
            "drone_id":  self.drone_id,
            "tick":      self.tick,
            "timestamp": time.time(),
            "payload":   payload,
        })