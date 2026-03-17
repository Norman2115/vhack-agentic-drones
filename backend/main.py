"""
Swarm Runner
────────────
Wires every layer together and launches N drone agents concurrently.

Usage
─────
  python main.py

  # Or from code:
  from main import run_swarm, SwarmConfig

  config = SwarmConfig(
      mission_id   = "SAR-001",
      swarm_size   = 4,
      zone_bounds  = {"min_x": 0, "max_x": 500, "min_y": 0, "max_y": 500},
      objectives   = ["survivor_search"],
      max_duration = 300,
  )
  asyncio.run(run_swarm(config))

Layer instantiation order
─────────────────────────
  1. MissionConfig          ← config/types.py
  2. SimulationBackend      ← tools/mcp_tools.py  (swap for RealHardwareBackend)
  3. DroneTools             ← tools/mcp_tools.py  (one per drone)
  4. GossipHandler          ← protocols/gossip.py
  5. ContractNetHandler     ← protocols/contract_net.py
  6. DroneGraphDeps         ← graph/agent_loop.py
  7. DroneGraph             ← graph/agent_loop.py  (one per drone)
  8. CommandAgent           ← agents/command_agent.py  (optional, shared)
  9. OutputPipeline         ← outputs/pipeline.py       (shared)
"""

from __future__ import annotations
import asyncio
import time
import uuid
from dataclasses import dataclass, field

from config.types import AgentState, DroneState, DroneStatus, MissionConfig, Position
from tools.mcp_tools import DroneTools, SimulationBackend, AITools
from protocols.gossip import GossipHandler
from protocols.contract_net import ContractNetHandler
from graph.agent_loop import DroneGraphDeps, build_drone_graph
from agents.command_agent import CommandAgent
from outputs.pipeline import DecisionLogger, OutputPipeline, SelfHealing, WebSocketStream


# ─── Swarm Configuration ──────────────────────────────────────────────────────

@dataclass
class SwarmConfig:
    mission_id:   str   = field(default_factory=lambda: f"MISSION-{str(uuid.uuid4())[:6].upper()}")
    swarm_size:   int   = 3
    zone_bounds:  dict  = field(default_factory=lambda: {
        "min_x": 0, "max_x": 500, "min_y": 0, "max_y": 500
    })
    objectives:   list  = field(default_factory=lambda: ["survivor_search"])
    max_duration: float = 120.0   # seconds
    base_x:       float = 250.0
    base_y:       float = 250.0
    max_ticks:    int   = 50


# ─── Single-Drone Task ───────────────────────────────────────────────────────

async def run_drone(
    drone_id:     str,
    mission:      MissionConfig,
    message_bus:  asyncio.Queue,
    output:       OutputPipeline,
    max_ticks:    int,
) -> AgentState:
    """Run one drone agent to completion."""
    backend = SimulationBackend(message_bus)
    tools   = DroneTools(drone_id, backend) # Normal tools without AI
    ai_tools = AITools(tools)  # Wrap tools with AI interface

    deps = DroneGraphDeps(
        tools  = tools,
        gossip = GossipHandler(),
        cnp    = ContractNetHandler(),
        ai_tools = ai_tools,  # Enable AI-powered decision making
    )
    graph = build_drone_graph(deps)

    # Initial state
    state = AgentState(
        drone_id   = drone_id,
        mission    = mission,
        self_state = DroneState(
            drone_id  = drone_id,
            position  = Position(
                x = mission.zone_bounds["min_x"] + (hash(drone_id) % 200),
                y = mission.zone_bounds["min_y"] + (hash(drone_id[::-1]) % 200),
            ),
            battery  = 0.8 + (hash(drone_id) % 20) / 100,  # Slightly varied starting batteries
            status   = DroneStatus.IDLE,
            sector   = f"SECTOR-{drone_id[-1]}",
            workload = 0,
        ),
    )

    print(f"[{drone_id}] Agent started — sector {state.self_state.sector}")

    for tick in range(max_ticks):
        # Drain the shared message bus into this drone's inbox
        drained = 0
        while not message_bus.empty() and drained < 20:
            try:
                msg = message_bus.get_nowait()
                state.inbox.append(msg)
                drained += 1
            except asyncio.QueueEmpty:
                break

        state = await graph.tick(state)
        await output.process(state)

        # Print a brief status each tick
        s = state.self_state
        print(
            f"  [{drone_id}] tick={state.tick:03d} "
            f"bat={s.battery:.0%} status={s.status.value:12s} "
            f"pos=({s.position.x:.0f},{s.position.y:.0f}) "
            f"decision={state.decision.value if state.decision else '-':10s} "
            f"log_entries={len(state.decision_log)}"
        )

        await asyncio.sleep(0.05)

    print(f"[{drone_id}] Agent finished after {state.tick} ticks")
    return state


# ─── Swarm Runner ────────────────────────────────────────────────────────────

async def run_swarm(config: SwarmConfig) -> list[AgentState]:
    """
    Launch all drone agents concurrently and return their final states.
    """
    print(f"\n{'═'*60}")
    print(f"  DRONE SWARM — {config.mission_id}")
    print(f"  Drones: {config.swarm_size}  |  Duration: {config.max_duration}s")
    print(f"  Zone: {config.zone_bounds}")
    print(f"{'═'*60}\n")

    # ── Shared infrastructure ─────────────────────────────────────────────────
    message_bus = asyncio.Queue()

    mission = MissionConfig(
        mission_id       = config.mission_id,
        zone_bounds      = config.zone_bounds,
        objectives       = config.objectives,
        swarm_size       = config.swarm_size,
        priority_sectors = [f"SECTOR-{i}" for i in range(config.swarm_size)],
        max_duration     = config.max_duration,
        base_position    = Position(config.base_x, config.base_y),
    )

    # ── Output pipeline ───────────────────────────────────────────────────────
    async def _print_ws_event(e: dict) -> None:
        print(f"  [WS] {e['type']:20s} {e['drone_id']}")

    ws_stream = WebSocketStream(sink=_print_ws_event)
    logger    = DecisionLogger()
    healing   = SelfHealing(message_bus)
    output    = OutputPipeline(ws_stream, logger, healing)

    # ── Optional Command Agent ────────────────────────────────────────────────
    command_agent = CommandAgent(mission=mission)
    online        = await command_agent.is_online()
    print(f"  Command Agent: {'ONLINE' if online else 'OFFLINE (swarm runs autonomously)'}\n")

    # ── Launch all drones ─────────────────────────────────────────────────────
    drone_ids = [f"DRONE-{chr(65 + i)}" for i in range(config.swarm_size)]
    tasks     = [
        run_drone(did, mission, message_bus, output, config.max_ticks)
        for did in drone_ids
    ]

    start  = time.time()
    states = await asyncio.gather(*tasks)
    elapsed = time.time() - start

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'═'*60}")
    print(f"  MISSION COMPLETE  — {elapsed:.1f}s")
    print(f"{'─'*60}")
    for state in states:
        s = state.self_state
        survivors = [
            e for e in logger.query(drone_id=state.drone_id, node="verify")
            if "CONFIRMED" in e.get("summary", "")
        ]
        print(
            f"  {state.drone_id:10s} "
            f"ticks={state.tick:3d}  "
            f"battery={s.battery:.0%}  "
            f"status={s.status.value:12s}  "
            f"survivors_confirmed={len(survivors)}"
        )

    total_decisions = sum(len(logger.query(drone_id=s.drone_id)) for s in states)
    print(f"{'─'*60}")
    print(f"  Total decision log entries: {total_decisions}")
    print(f"{'═'*60}\n")

    return list(states)


# ─── Entry Point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    config = SwarmConfig(
        swarm_size   = 3,
        max_ticks    = 15,
        max_duration = 300,
    )
    asyncio.run(run_swarm(config))