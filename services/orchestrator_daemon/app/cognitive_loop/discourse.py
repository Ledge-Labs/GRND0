# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class TopicFrame:
    topic_id: str
    name: str
    status: str
    entities: tuple[str, ...]
    summary: str
    first_turn: int
    last_turn: int
    sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class TurnFrame:
    turn_id: str
    index: int
    query: str
    subject: str
    summary: str
    verification: str


@dataclass(frozen=True)
class DiscourseState:
    session_id: str
    current_turn: int = 0
    active_subject: str = ""
    topic_stack: tuple[TopicFrame, ...] = ()
    recent_turns: tuple[TurnFrame, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DiscourseState":
        topics = []
        for item in value.get("topic_stack", []):
            topics.append(
                TopicFrame(
                    **{
                        **item,
                        "entities": tuple(item.get("entities", [])),
                        "sources": tuple(item.get("sources", [])),
                    }
                )
            )
        return cls(
            session_id=str(value.get("session_id") or ""),
            current_turn=int(value.get("current_turn", 0)),
            active_subject=str(value.get("active_subject") or ""),
            topic_stack=tuple(topics),
            recent_turns=tuple(TurnFrame(**item) for item in value.get("recent_turns", [])),
        )


@dataclass(frozen=True)
class DiscourseUpdate:
    session_id: str
    turn_id: str
    query: str
    subject: str
    topic: str
    relation: str
    answer_summary: str
    verification: str
    entities: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()


def reduce_state(state: DiscourseState, update: DiscourseUpdate) -> DiscourseState:
    """Pure, idempotent left-fold for one completed conversational turn."""
    if any(turn.turn_id == update.turn_id for turn in state.recent_turns):
        return state

    turn_index = state.current_turn + 1
    subject = update.subject.strip() or state.active_subject or update.topic.strip() or "current request"
    topic_id = subject.casefold()
    existing = next((item for item in state.topic_stack if item.topic_id == topic_id), None)
    retained = [item for item in state.topic_stack if item.topic_id != topic_id]
    retained = [
        TopicFrame(**{**asdict(item), "status": "background"})
        for item in retained
    ]
    frame = TopicFrame(
        topic_id=topic_id,
        name=subject,
        status="active",
        entities=tuple(dict.fromkeys((*(existing.entities if existing else ()), *update.entities))),
        summary=update.answer_summary[:1200],
        first_turn=existing.first_turn if existing else turn_index,
        last_turn=turn_index,
        sources=tuple(dict.fromkeys((*(existing.sources if existing else ()), *update.sources))),
    )
    turn = TurnFrame(
        turn_id=update.turn_id,
        index=turn_index,
        query=update.query[:1200],
        subject=subject,
        summary=update.answer_summary[:1200],
        verification=update.verification,
    )
    return DiscourseState(
        session_id=state.session_id,
        current_turn=turn_index,
        active_subject=subject,
        topic_stack=tuple(([frame] + retained)[:12]),
        recent_turns=tuple((*state.recent_turns, turn)[-12:]),
    )


def fold_updates(state: DiscourseState, updates: Iterable[DiscourseUpdate]) -> DiscourseState:
    for update in updates:
        state = reduce_state(state, update)
    return state


def subject_menu(state: DiscourseState) -> tuple[str, ...]:
    values: list[str] = []
    if state.active_subject:
        values.append(state.active_subject)
    for topic in state.topic_stack:
        values.extend((topic.name, *topic.entities))
    values.append("unresolved")
    return tuple(dict.fromkeys(value for value in values if value))


def render_state(state: DiscourseState) -> str:
    if not state.recent_turns:
        return "No prior turns are committed for this session."
    topics = "; ".join(
        f"{item.name} ({item.status}; last turn {item.last_turn})" for item in state.topic_stack[:6]
    )
    turns = "\n".join(
        f"Turn {item.index}: subject={item.subject}; user={item.query}; result={item.summary}"
        for item in state.recent_turns[-6:]
    )
    return f"Active subject: {state.active_subject}\nTopics: {topics}\nRecent turns:\n{turns}"
