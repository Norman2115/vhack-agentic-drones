"""
Contract Net Protocol (CNP)
────────────────────────────
Task allocation via CFP → Bid → Award.

Flow (per task)
---------------
  1. Detecting drone calls announce_task() → CFP broadcast
  2. All eligible drones call submit_bid() → Bid messages
  3. CFP issuer collects bids, selects winner (highest score)
  4. Winner calls claim_task() → Award broadcast
  5. Non-winners drop the task

This module handles bid collection and winner selection.
The LangGraph detect + decide nodes drive the flow.

Integration
-----------
  ContractNetHandler.process_bids(state) → call in the decide node.
  ContractNetHandler.process_cfp(state) → call in the detect node.
"""

from __future__ import annotations
import time
from typing import Any

from config.types import AgentState, Bid, TaskAnnouncement, TaskType


# ─── Bid Wait Window ──────────────────────────────────────────────────────────

BID_COLLECTION_SECONDS = 2.0    # How long to wait for bids before awarding


# ─── CNP Handler ─────────────────────────────────────────────────────────────

class ContractNetHandler:
    """
    Stateless CNP logic. All mutable data lives in AgentState.
    """

    # ── Responder side (all non-issuing drones) ────────────────────────────

    def process_cfp(self, state: AgentState) -> list[TaskAnnouncement]:
        """
        Extract incoming CFP messages from inbox and register them as
        active tasks. Returns newly discovered TaskAnnouncements.
        """
        new_tasks: list[TaskAnnouncement] = []
        cfp_msgs  = [m for m in state.inbox if m.get("channel") == "contractnet_cfp"]

        for msg in cfp_msgs:
            try:
                p = msg["payload"]
                task = TaskAnnouncement(
                    task_id     = p["task_id"],
                    task_type   = TaskType(p["task_type"]),
                    position    = __import__("config.types", fromlist=["Position"]).Position(**p["position"]),
                    priority    = p["priority"],
                    issuer_id   = p["issuer_id"],
                    deadline    = p["deadline"],
                    description = p.get("description", ""),
                )
                if task.issuer_id == state.drone_id:
                    continue       # Own CFP — ignore on responder side
                if time.time() > task.deadline:
                    continue       # Expired
                # Deduplicate
                if not any(t.task_id == task.task_id for t in state.active_tasks):
                    state.active_tasks.append(task)
                    new_tasks.append(task)
            except (KeyError, TypeError, ValueError):
                pass

        return new_tasks

    # ── Issuer side (the drone that sent the CFP) ─────────────────────────

    def collect_bids(self, state: AgentState, task_id: str) -> list[Bid]:
        """
        Collect all bid messages for task_id from the inbox.
        Called by the issuing drone each tick while waiting.
        """
        bids: list[Bid] = []
        for msg in state.inbox:
            if msg.get("channel") != "contractnet_bid":
                continue
            p = msg.get("payload", {})
            if p.get("task_id") != task_id:
                continue
            try:
                bids.append(Bid(
                    task_id  = p["task_id"],
                    drone_id = p["drone_id"],
                    score    = float(p["score"]),
                    eta      = float(p["eta"]),
                ))
            except (KeyError, TypeError, ValueError):
                pass
        return bids

    def select_winner(self, bids: list[Bid]) -> Bid | None:
        """Return the bid with the highest score, or None if no bids."""
        return max(bids, key=lambda b: b.score) if bids else None

    # ── Self-healing task reassignment ────────────────────────────────────

    def find_tasks_for_lost_sector(
        self, state: AgentState, lost_sector: str
    ) -> list[str]:
        """
        When a peer goes offline, identify any tasks they owned and
        return them as new task_ids that need re-announcement.
        (Concrete tracking requires cross-referencing the decision log.)
        """
        owned = [
            entry["extra"].get("task_id")
            for entry in state.decision_log
            if entry.get("node") == "claim_task"
            and entry.get("extra", {}).get("sector") == lost_sector
        ]
        return [t for t in owned if t]