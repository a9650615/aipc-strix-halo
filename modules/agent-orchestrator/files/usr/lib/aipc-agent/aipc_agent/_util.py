"""Shared helpers for aipc_agent graphs."""


def text_of(content: str | list) -> str:
    """Reasoning models (ornith-35b) return content as a list of blocks
    (e.g. {"type": "thinking", ...}), not a plain string — hardware-verified
    2026-07-04/06. Backends built on llama-server reject that shape if it's
    ever re-sent as conversation history ("unsupported content[].type"), so
    any AIMessage kept in graph state must be normalized through this first.
    Takes the final "text"-type block if present; falls back to str() for
    anything else (e.g. a pure tool-call turn with no text block) — str()
    always yields a plain string, so the "content must be a string" wire
    constraint holds no matter what shape the model returned."""
    if isinstance(content, str):
        return content
    for block in reversed(content):
        if isinstance(block, dict) and block.get("type") == "text":
            return block.get("text", "")
    return str(content)
