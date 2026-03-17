"""
Gossip Protocol
───────────────
Peer-to-peer swarm state broadcast.

Each drone periodically pushes its DroneState to neighbours.
No central registry required — every node keeps a local copy
of the swarm registry that converges eventually.

Integration
-----------
  GossipHandler.process_inbox(state) is called by the
  LangGraph "listen" and "update_state" nodes.

  To plug in a real radio / mesh network:
    1. Implement GossipTransport.send() / receive()
    2. Pass it to GossipHandler.__init__
"""

from __future__ import annotations
import time
from typing import Any

from config.types import AgentState, DroneState


# ─── Stale Peer Threshold ─────────────────────────────────────────────────────

STALE_SECONDS = 30      # Peers not heard from in this long are marked offline


# ─── Gossip Handler ───────────────────────────────────────────────────────────

class GossipHandler:
    """
    Processes incoming gossip messages and maintains the swarm registry.
    Stateless — all mutable data lives in AgentState.
    """

    def process_inbox(self, state: AgentState) -> list[DroneState]:
        """
        Filter gossip messages from the agent inbox and merge them
        into state.swarm_registry.
        Returns the list of peers whose state was updated this tick.
        """
        updated_peers: list[DroneState] = []

        gossip_msgs = [m for m in state.inbox if m.get("channel") == "gossip"]
        for msg in gossip_msgs:
            payload = msg.get("payload", {})
            try:
                peer = DroneState.from_dict(payload)
                if peer.drone_id == state.drone_id:
                    continue                   # Ignore own echo
                state.swarm_registry[peer.drone_id] = peer
                updated_peers.append(peer)
            except (KeyError, TypeError):
                pass                           # Malformed — skip

        return updated_peers

    def evict_stale_peers(self, state: AgentState) -> list[str]:
        """
        Remove peers that haven't broadcast for STALE_SECONDS.
        Returns the list of evicted drone IDs (triggers self-healing).
        """
        now    = time.time()
        stale  = [
            did for did, ds in state.swarm_registry.items()
            if now - ds.last_seen > STALE_SECONDS
        ]
        for did in stale:
            del state.swarm_registry[did]
            state.emit_ws("swarm_health", {
                "event":    "peer_lost",
                "drone_id": did,
                "reason":   "gossip_timeout",
            })
            state.log("gossip_evict", f"Peer {did} evicted (stale)", {"evicted": did})
        return stale

    def swarm_summary(self, state: AgentState) -> dict:
        """Quick overview of the current swarm registry."""
        return {
            "total_known": len(state.swarm_registry),
            "active":      sum(
                1 for ds in state.swarm_registry.values()
                if ds.status.value not in ("offline", "charging")
            ),
            "average_battery": round(
                sum(ds.battery for ds in state.swarm_registry.values()) /
                max(len(state.swarm_registry), 1), 3
            ),
        }