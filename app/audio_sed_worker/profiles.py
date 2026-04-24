from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptSpec:
    domain: str
    prompt: str


PROFILES: dict[str, list[PromptSpec]] = {
    "action_beats_v1": [
        PromptSpec("fight", "body punch impact"),
        PromptSpec("fight", "kick impact"),
        PromptSpec("fight", "slap or smack"),
        PromptSpec("fight", "body fall impact"),
        PromptSpec("fight", "weapon hit"),
        PromptSpec("fight", "metal hit"),
        PromptSpec("fight", "glass shatter"),
        PromptSpec("gunfire", "single gunshot"),
        PromptSpec("gunfire", "rapid gunfire"),
        PromptSpec("gunfire", "bullet impact"),
        PromptSpec("explosion", "explosion"),
        PromptSpec("explosion", "fire burst"),
        PromptSpec("explosion", "debris impact after explosion"),
    ],
}


def get_profile(name: str) -> list[PromptSpec]:
    if name not in PROFILES:
        supported = ", ".join(sorted(PROFILES))
        raise ValueError(f"Unsupported audio-sed profile={name!r}; supported: {supported}")
    return PROFILES[name]


def slugify(value: str) -> str:
    chars = []
    previous_underscore = False
    for char in value.lower():
        if char.isalnum():
            chars.append(char)
            previous_underscore = False
        elif not previous_underscore:
            chars.append("_")
            previous_underscore = True
    return "".join(chars).strip("_") or "unknown"
