"""
LangGraph Drone Agent — Five-Node Loop
───────────────────────────────────────
Implements the exact node sequence shown in the architecture diagram using
LangGraph's StateGraph for stateful, durable agent execution:

  ① Listen        – drain inbox from Gossip + CNP channels
  ② Update State  – merge peer gossip into swarm registry
  ③ Detect Events – thermal scan + CNP CFP detection
  ④ Decision      – AI-powered reasoning OR rule-based routing → explore/verify/rtb
  ⑤ Execute       – MCP tool calls, emit WS events, loop back

Each node is a plain async function optimized for LangGraph:
  async def node_name(state: AgentState, deps: DroneGraphDeps) -> AgentState

The graph is built with build_drone_graph() and compiled once per drone.

AI-Powered Decision Making
──────────────────────────
When AI tools are available (OpenAI API key set), the decision node uses
an LLM agent with access to all drone tools. The AI can:
- Analyze complex situations beyond simple rule thresholds
- Call multiple tools in sequence to gather information
- Make strategic decisions based on swarm state and mission context
- Adapt to novel scenarios not covered by hardcoded rules

Benefits of LangGraph + AI
──────────────────────────
- **Durable execution**: Resume from checkpoints after failures
- **Human-in-the-loop**: Inspect and modify state at any graph node
- **Streaming**: Track state transitions in real-time
- **AI Reasoning**: Intelligent tool selection and strategic planning
- **Visualization**: Built-in debugging with LangSmith integration

Integration
-----------
  from graph.agent_loop import build_drone_graph, DroneGraphDeps

  deps  = DroneGraphDeps(tools=my_tools, gossip=GossipHandler(), cnp=ContractNetHandler(), ai_tools=my_ai_tools)
  graph = build_drone_graph(deps)
  state = AgentState(...)
  state = await graph.tick(state)   # Run one full tick
"""

from __future__ import annotations
import asyncio
import time
import uuid
from dataclasses import dataclass
from functools import partial
from typing import Callable, Awaitable

from langgraph.graph import START, StateGraph

from config.types import (
    AgentState, DecisionRoute, DroneStatus, Position,
    ScanResult, TaskType,
)
from tools.mcp_tools import DroneTools, AITools
from protocols.gossip import GossipHandler
from protocols.contract_net import ContractNetHandler

# Optional AI imports - only loaded if AI features are enabled
try:
    from langchain_openai import ChatOpenAI
    from langchain.agents import create_tool_calling_agent, AgentExecutor
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False


# ─── Thresholds (tune without changing graph logic) ───────────────────────────

BATTERY_RTB_THRESHOLD    = 0.20   # Return to base below this level
BATTERY_LOW_THRESHOLD    = 0.30   # Prefer not to bid below this level
DETECTION_MIN_CONFIDENCE = 0.70   # Minimum confidence to act on scan


# ─── Dependency Container ─────────────────────────────────────────────────────

@dataclass
class DroneGraphDeps:
    """
    Inject real implementations here.  All nodes receive this object.
    Decouples the graph from specific backend choices.
    """
    tools:  DroneTools
    gossip: GossipHandler
    cnp:    ContractNetHandler

    # Optional: supply a callable to receive WS events in real-time
    ws_sink: Callable[[dict], Awaitable[None]] | None = None

    # AI tools for LLM-based decision making
    ai_tools: Any = None  # Will be AITools instance


# ─── Node 1 — Listen ─────────────────────────────────────────────────────────

async def node_listen(state: AgentState, deps: DroneGraphDeps) -> AgentState:
    """
    Drain the message bus into state.inbox for this tick.
    In a real deployment the inbox is filled by the transport layer
    (UDP/WiFi/LoRa) between ticks.  In simulation it is pre-populated.
    """
    state.tick += 1
    state.ws_events.clear()      # Fresh slate each tick
    state.outbox.clear()

    # Refresh own battery reading
    await deps.tools.get_battery(state)

    state.log("listen", f"Tick {state.tick} — inbox has {len(state.inbox)} messages")
    return state


# ─── Node 2 — Update State ────────────────────────────────────────────────────

async def node_update_state(state: AgentState, deps: DroneGraphDeps) -> AgentState:
    """
    Merge incoming gossip into the swarm registry.
    Evict stale peers (triggers self-healing output).
    """
    updated = deps.gossip.process_inbox(state)
    stale   = deps.gossip.evict_stale_peers(state)
    summary = deps.gossip.swarm_summary(state)

    state.log(
        "update_state",
        f"Registry synced — {len(updated)} updates, {len(stale)} evicted",
        {"swarm_summary": summary, "stale_peers": stale},
    )
    state.emit_ws("swarm_health", {"registry": summary, "stale_evicted": stale})

    # Broadcast own state so peers stay current
    await deps.tools.broadcast_status(state)

    return state


# ─── Node 3 — Detect Events ──────────────────────────────────────────────────

async def node_detect_events(state: AgentState, deps: DroneGraphDeps) -> AgentState:
    """
    1. Run thermal + motion scan at current position.
    2. Check for incoming Contract Net CFP messages.
    If a survivor is detected, immediately broadcast a CFP so the
    nearest available drone can be tasked with verification.
    """
    # ── Sensor scan ──────────────────────────────────────────────────────────
    scan = await deps.tools.thermal_scan(state)

    if scan.has_detection() and scan.confidence >= DETECTION_MIN_CONFIDENCE:
        state.log(
            "detect_events",
            f"Detection at {scan.position.to_dict()} confidence={scan.confidence}",
            {"scan": {"thermal": scan.thermal_detected, "motion": scan.motion_detected}},
        )
        state.emit_ws("survivor_alert", {
            "position":   scan.position.to_dict(),
            "confidence": scan.confidence,
            "sensor":     {"thermal": scan.thermal_detected, "motion": scan.motion_detected},
        })
        # Announce task to swarm so best-placed drone handles it
        await deps.tools.announce_task(
            state,
            task_type   = TaskType.VERIFY,
            position    = scan.position,
            priority    = 9,
            description = f"Survivor signature detected — confidence {scan.confidence:.0%}",
        )
    else:
        state.log("detect_events", "No detection this scan")

    # ── Incoming CFP messages ─────────────────────────────────────────────────
    new_tasks = deps.cnp.process_cfp(state)
    for task in new_tasks:
        # Auto-bid if battery is sufficient and not already busy
        if (state.self_state.battery >= BATTERY_LOW_THRESHOLD
                and state.self_state.workload < 2
                and task.issuer_id != state.drone_id):
            bid = await deps.tools.submit_bid(state, task)
            state.log("detect_events", f"Bid submitted for task {task.task_id} score={bid.score}")

    return state


# ─── Node 4 — Decision Engine ────────────────────────────────────────────────

async def node_decide(state: AgentState, deps: DroneGraphDeps) -> AgentState:
    """
    Conditional routing logic.  Sets state.decision to one of:
      RTB     → battery critical
      VERIFY  → won a verification task
      EXPLORE → default navigation
    """
    # ── Priority 1: Low battery ───────────────────────────────────────────────
    if state.self_state.battery <= BATTERY_RTB_THRESHOLD:
        state.decision = DecisionRoute.RTB
        state.self_state.status = DroneStatus.RETURNING
        state.log("decide", f"Battery {state.self_state.battery:.0%} — routing to RTB")
        state.emit_ws("decision", {"route": DecisionRoute.RTB.value, "reason": "low_battery"})
        return state

    # ── Priority 2: Verify won task ───────────────────────────────────────────
    # Check if we won any Contract Net award messages in the inbox
    award_msgs = [m for m in state.inbox if m.get("channel") == "contractnet_award"
                  and m.get("payload", {}).get("winner") == state.drone_id]
    if award_msgs:
        # Find the matching task
        task_id     = award_msgs[0]["payload"]["task_id"]
        won_task    = next((t for t in state.active_tasks if t.task_id == task_id), None)
        if won_task:
            await deps.tools.claim_task(state, won_task)
            state.decision = DecisionRoute.VERIFY
            state.self_state.status = DroneStatus.VERIFYING
            state.log("decide", f"Won task {task_id} — routing to VERIFY")
            state.emit_ws("decision", {"route": DecisionRoute.VERIFY.value, "task_id": task_id})
            return state

    # ── Priority 3: Default — explore sector ──────────────────────────────────
    state.decision = DecisionRoute.EXPLORE
    state.self_state.status = DroneStatus.EXPLORING
    state.log("decide", "No priority trigger — routing to EXPLORE")
    state.emit_ws("decision", {"route": DecisionRoute.EXPLORE.value})
    return state


# ─── AI-Powered Decision Engine ──────────────────────────────────────────────

async def node_decide_with_ai(state: AgentState, deps: DroneGraphDeps) -> AgentState:
    """
    Use an LLM to decide which action to take based on current state.
    The LLM has access to all available tools and reasons about the best action.
    Falls back to rule-based decision if AI is not available.
    """
    if not AI_AVAILABLE or not deps.ai_tools:
        # Fallback to rule-based decision
        return await node_decide(state, deps)

    try:
        llm = ChatOpenAI(model="gpt-4-turbo", temperature=0.3)
        tools = deps.ai_tools.get_all_tools()

        # Create system prompt with current state context
        system_prompt = f"""
        You are a drone agent in a search-and-rescue swarm.
        Your goal is to find survivors efficiently while managing battery and cooperating with team.

        Current state:
        - Battery: {state.self_state.battery:.0%}
        - Position: ({state.self_state.position.x:.1f}, {state.self_state.position.y:.1f})
        - Tasks available: {len(state.active_tasks)}
        - Workload: {state.self_state.workload}
        - Sector: {state.self_state.sector or 'None'}
        - Tick: {state.tick}

        Mission priorities (in order):
        1. If battery critical (< 20%), plan return to base
        2. If you won a task, verify the target
        3. Otherwise, scan and explore to find survivors

        Use the available tools to make progress. You can call multiple tools in sequence.
        After gathering information, decide on the next action: RTB, VERIFY, or EXPLORE.
        """

        agent = create_tool_calling_agent(llm, tools, system_prompt)
        executor = AgentExecutor(
            agent=agent,
            tools=tools,
            max_iterations=3,
            verbose=False,
            handle_parsing_errors=True
        )

        # Let LLM decide and execute tools
        result = await executor.ainvoke({
            "input": "Analyze the current situation and decide what action to take next. "
                    "Use tools to gather information if needed, then choose: RTB, VERIFY, or EXPLORE."
        })

        # Parse LLM's decision from the output
        decision_text = result.get("output", "").lower()

        if "return" in decision_text and "base" in decision_text:
            state.decision = DecisionRoute.RTB
            state.self_state.status = DroneStatus.RETURNING
            state.emit_ws("decision", {"route": DecisionRoute.RTB.value, "reason": "ai_decision"})
        elif "verify" in decision_text:
            state.decision = DecisionRoute.VERIFY
            state.self_state.status = DroneStatus.VERIFYING
            state.emit_ws("decision", {"route": DecisionRoute.VERIFY.value, "reason": "ai_decision"})
        else:
            state.decision = DecisionRoute.EXPLORE
            state.self_state.status = DroneStatus.EXPLORING
            state.emit_ws("decision", {"route": DecisionRoute.EXPLORE.value, "reason": "ai_decision"})

        state.log("decide_with_ai", f"AI decision: {decision_text[:100]}...")
        return state

    except Exception as e:
        # Fallback to rule-based on any AI error
        state.log("decide_with_ai", f"AI failed ({e}), falling back to rules")
        return await node_decide(state, deps)


# ─── Node 5 — Execute Action ─────────────────────────────────────────────────

async def node_execute(state: AgentState, deps: DroneGraphDeps) -> AgentState:
    """
    Dispatches to the correct action branch based on state.decision.
    After execution, emits accumulated WS events and loops back.
    """
    route = state.decision

    if route == DecisionRoute.RTB:
        await _action_rtb(state, deps)

    elif route == DecisionRoute.VERIFY:
        await _action_verify(state, deps)

    elif route == DecisionRoute.EXPLORE:
        await _action_explore(state, deps)

    # ── Flush WebSocket events ────────────────────────────────────────────────
    if deps.ws_sink:
        for event in state.ws_events:
            await deps.ws_sink(event)

    state.log("execute", f"Action branch '{route.value}' complete — tick {state.tick} done")
    # Clear inbox for next tick
    state.inbox.clear()
    state.active_tasks = [t for t in state.active_tasks if time.time() < t.deadline]
    return state


# ─── Action Branches ──────────────────────────────────────────────────────────

async def _action_explore(state: AgentState, deps: DroneGraphDeps) -> None:
    """
    Grid-sweep the assigned sector.
    Advances position by one step; real nav is handled by MCP move_to().
    """
    pos = state.self_state.position
    # Simple grid step — replace with a real path planner
    next_pos = Position(pos.x + 10, pos.y, pos.z)
    bounds   = state.mission.zone_bounds
    if next_pos.x > bounds.get("max_x", 1000):
        next_pos = Position(bounds.get("min_x", 0), pos.y + 10, pos.z)

    await deps.tools.move_to(next_pos, state)
    state.log("explore", f"Sector sweep step → {next_pos.to_dict()}")


async def _action_verify(state: AgentState, deps: DroneGraphDeps) -> None:
    """
    Close-range verification scan at the task's target position.
    """
    task = state.won_task
    if not task:
        return

    await deps.tools.move_to(task.position, state)
    scan = await deps.tools.thermal_scan(state)

    if scan.has_detection() and scan.confidence >= DETECTION_MIN_CONFIDENCE:
        state.emit_ws("survivor_alert", {
            "confirmed":  True,
            "position":   task.position.to_dict(),
            "confidence": scan.confidence,
            "task_id":    task.task_id,
        })
        state.log("verify", f"Survivor CONFIRMED at {task.position.to_dict()}", {"confidence": scan.confidence})
    else:
        state.emit_ws("survivor_alert", {
            "confirmed":  False,
            "position":   task.position.to_dict(),
            "task_id":    task.task_id,
        })
        state.log("verify", "Verification negative — false alarm")

    state.won_task             = None
    state.self_state.workload  = max(0, state.self_state.workload - 1)


async def _action_rtb(state: AgentState, deps: DroneGraphDeps) -> None:
    """
    Return to base. Broadcast sector vacancy so swarm can reassign.
    """
    base = state.mission.base_position
    await deps.tools.move_to(base, state)

    # Vacate sector — announce via Contract Net so someone else covers it
    if state.self_state.sector:
        await deps.tools.announce_task(
            state,
            task_type   = TaskType.EXPLORE,
            position    = base,
            priority    = 3,
            description = f"Sector {state.self_state.sector} vacated — drone RTB",
        )
        state.self_state.sector = None

    state.self_state.status = DroneStatus.CHARGING
    state.log("rtb", "Returned to base — sector vacancy announced")
    state.emit_ws("drone_state", {"event": "rtb_complete", "status": DroneStatus.CHARGING.value})


# ─── Graph Builder ────────────────────────────────────────────────────────────

class DroneGraph:
    """Compiled agent graph.

    This is a thin wrapper around a LangGraph StateGraph so the agent loop
    execution remains the same while benefiting from LangGraph features such
    as durable execution, state checkpointing, and human-in-the-loop inspection.
    """

    def __init__(self, deps: DroneGraphDeps):
        self.deps = deps
        self._compiled = self._compile_graph()

    def _compile_graph(self):
        graph = StateGraph(AgentState)

        # Bind deps into each node so the LangGraph node signature stays simple.
        graph.add_node("listen",       partial(node_listen, deps=self.deps))
        graph.add_node("update_state", partial(node_update_state, deps=self.deps))
        graph.add_node("detect_events",partial(node_detect_events, deps=self.deps))

        # Use AI-powered decision if available, otherwise rule-based
        if AI_AVAILABLE and self.deps.ai_tools:
            graph.add_node("decide", partial(node_decide_with_ai, deps=self.deps))
        else:
            graph.add_node("decide", partial(node_decide, deps=self.deps))

        graph.add_node("execute",      partial(node_execute, deps=self.deps))

        # Ordered sequence of nodes for one tick
        graph.add_edge(START, "listen")
        graph.add_edge("listen", "update_state")
        graph.add_edge("update_state", "detect_events")
        graph.add_edge("detect_events", "decide")
        graph.add_edge("decide", "execute")

        return graph.compile()

    async def tick(self, state: AgentState) -> AgentState:
        """Run one complete tick through the LangGraph state graph."""
        result = await self._compiled.ainvoke(state)
        # LangGraph may return a dict; the state object itself is expected to be passed through.
        return result if isinstance(result, AgentState) else state

    async def run(self, state: AgentState, max_ticks: int = 1000) -> AgentState:
        """Run the agent loop for up to max_ticks or until mission end."""
        start   = time.time()
        timeout = state.mission.max_duration
        while state.tick < max_ticks:
            if time.time() - start > timeout:
                state.log("run", "Mission timeout reached")
                break
            state = await self.tick(state)
            await asyncio.sleep(0.1)    # Yield between ticks
        return state


def build_drone_graph(deps: DroneGraphDeps) -> DroneGraph:
    """
    Factory function.  Use this instead of instantiating DroneGraph directly
    so the construction point is easy to replace with a real LangGraph
    StateGraph.compile() call later.
    """
    return DroneGraph(deps)