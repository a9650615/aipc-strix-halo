"""Voice session state machine (explicit states, pure transitions).

Maps to legacy mic modes: listen | wake_buf | command for the I/O loop.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from aipc_voice_wake_policy import (
    MAX_REPROMPTS,
    junk_capture_action,
    miss_backoff_seconds,
    next_mode_after_empty_capture,
)


class SessionState(str, Enum):
    IDLE = "idle"
    WAKE_BUFFER = "wake_buffer"
    CAPTURING = "capturing"  # intentional command
    REPROMPT_CAPTURING = "reprompt_capturing"
    FOLLOWUP_ARMED = "followup_armed"  # background probe; no UI
    FOLLOWUP_CAPTURING = "followup_capturing"
    RESOLVING = "resolving"  # once/stream running (optional marker)


class MicMode(str, Enum):
    LISTEN = "listen"
    WAKE_BUF = "wake_buf"
    COMMAND = "command"


def mic_mode(state: SessionState) -> str:
    """Legacy string used by run_phrase_loop branches."""
    if state is SessionState.IDLE or state is SessionState.FOLLOWUP_ARMED:
        return MicMode.LISTEN.value
    if state is SessionState.WAKE_BUFFER:
        return MicMode.WAKE_BUF.value
    if state in (
        SessionState.CAPTURING,
        SessionState.REPROMPT_CAPTURING,
        SessionState.FOLLOWUP_CAPTURING,
        SessionState.RESOLVING,
    ):
        return MicMode.COMMAND.value
    return MicMode.LISTEN.value


def ui_allowed(state: SessionState) -> bool:
    """Whether overlay SHOW is allowed (ghost / followup_armed stay dark)."""
    return state in (
        SessionState.CAPTURING,
        SessionState.REPROMPT_CAPTURING,
        SessionState.FOLLOWUP_CAPTURING,
        SessionState.RESOLVING,
    )


@dataclass
class Session:
    state: SessionState = SessionState.IDLE
    intentional: bool = False
    reprompt_used: int = 0
    miss_streak: int = 0
    followup_turn: int = 0

    @property
    def mode(self) -> str:
        return mic_mode(self.state)

    def reset_idle(self) -> Session:
        return Session(
            state=SessionState.IDLE,
            intentional=False,
            reprompt_used=0,
            miss_streak=self.miss_streak,
            followup_turn=0,
        )


def on_energy_open(sess: Session) -> Session:
    """Ambient energy gate opened → buffer wake STT."""
    return replace(sess, state=SessionState.WAKE_BUFFER)


def on_wake_decision(sess: Session, decision: dict) -> Session:
    """After STT+score arm decision."""
    if decision.get("arm"):
        return Session(
            state=SessionState.CAPTURING,
            intentional=bool(decision.get("intentional")),
            reprompt_used=0,
            miss_streak=0,
            followup_turn=0,
        )
    return replace(
        sess,
        state=SessionState.IDLE,
        intentional=False,
        reprompt_used=0,
        miss_streak=sess.miss_streak + 1,
    )


def on_ptt(sess: Session) -> Session:
    return Session(
        state=SessionState.CAPTURING,
        intentional=True,
        reprompt_used=0,
        miss_streak=0,
        followup_turn=sess.followup_turn if sess.followup_turn else 0,
    )


def on_empty_capture(sess: Session) -> tuple[Session, str]:
    """Empty/junk command: reprompt once if intentional else idle.

    Returns (new_session, action) where action is reprompt|idle.
    """
    action = junk_capture_action(
        intentional=sess.intentional,
        reprompt_used=sess.reprompt_used,
        max_reprompts=MAX_REPROMPTS,
    )
    if action == "reprompt":
        return (
            replace(
                sess,
                state=SessionState.REPROMPT_CAPTURING,
                reprompt_used=sess.reprompt_used + 1,
            ),
            action,
        )
    # idle: clear intentional
    return (
        Session(
            state=SessionState.IDLE,
            intentional=False,
            reprompt_used=0,
            miss_streak=sess.miss_streak,
            followup_turn=0,
        ),
        action,
    )


def on_followup_arm(sess: Session) -> Session:
    """After successful reply: arm background follow-up without UI."""
    return replace(
        sess,
        state=SessionState.FOLLOWUP_ARMED,
        intentional=False,  # follow-up junk does not REPROMPT
        reprompt_used=0,
        followup_turn=sess.followup_turn + 1,
    )


def on_followup_speech(sess: Session) -> Session:
    return replace(
        sess,
        state=SessionState.FOLLOWUP_CAPTURING,
        intentional=False,
    )


def on_submit_turn(sess: Session) -> Session:
    return replace(sess, state=SessionState.RESOLVING)


def on_turn_done_idle(sess: Session) -> Session:
    return sess.reset_idle()


def miss_backoff_for(sess: Session) -> float:
    return miss_backoff_seconds(sess.miss_streak)


def empty_capture_mic_mode(action: str) -> str:
    return next_mode_after_empty_capture(action)
