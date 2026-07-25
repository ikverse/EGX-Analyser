from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.config_store import config_path
from app.time_utils import cairo_now


_PHRASE_SEPARATOR_RE = re.compile(r"[,،]")


def prompt_customization_path() -> Path:
    return config_path().with_name("prompt-customization.json")


def _default_state() -> dict[str, Any]:
    return {
        "version": 1,
        "include_phrases": [],
        "exclude_phrases": [],
        "history": [],
    }


def load_prompt_customization() -> dict[str, Any]:
    path = prompt_customization_path()
    if not path.exists():
        return _default_state()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Prompt customization file must contain a JSON object.")
    state = _default_state()
    state["include_phrases"] = _normalize_phrases(payload.get("include_phrases", []))
    state["exclude_phrases"] = _normalize_phrases(payload.get("exclude_phrases", []))
    state["history"] = payload.get("history", []) if isinstance(payload.get("history"), list) else []
    return state


def _normalize_phrases(value: object) -> list[str]:
    raw_items: list[object]
    if isinstance(value, str):
        raw_items = _PHRASE_SEPARATOR_RE.split(value)
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []
    phrases: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        phrase = " ".join(str(item).split()).strip()
        key = phrase.casefold()
        if not phrase or key in seen:
            continue
        seen.add(key)
        phrases.append(phrase)
    return phrases


def _difference(current: list[str], previous: list[str]) -> list[str]:
    previous_keys = {phrase.casefold() for phrase in previous}
    return [phrase for phrase in current if phrase.casefold() not in previous_keys]


def _write_state(state: dict[str, Any]) -> None:
    path = prompt_customization_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _change_set(previous: dict[str, Any], include_phrases: list[str], exclude_phrases: list[str]) -> dict[str, list[str]]:
    return {
        "include_added": _difference(include_phrases, previous["include_phrases"]),
        "include_removed": _difference(previous["include_phrases"], include_phrases),
        "exclude_added": _difference(exclude_phrases, previous["exclude_phrases"]),
        "exclude_removed": _difference(previous["exclude_phrases"], exclude_phrases),
    }


def save_prompt_customization(include_value: object, exclude_value: object) -> dict[str, Any]:
    previous = load_prompt_customization()
    include_phrases = _normalize_phrases(include_value)
    exclude_phrases = _normalize_phrases(exclude_value)
    excluded_keys = {phrase.casefold() for phrase in exclude_phrases}
    include_phrases = [phrase for phrase in include_phrases if phrase.casefold() not in excluded_keys]
    history = list(previous["history"])
    changes = _change_set(previous, include_phrases, exclude_phrases)
    if any(changes.values()):
        history.append({
            "timestamp": cairo_now().isoformat(),
            "action": "updated",
            **changes,
        })
    state = {
        "version": 1,
        "include_phrases": include_phrases,
        "exclude_phrases": exclude_phrases,
        "history": history,
    }
    _write_state(state)
    return state


def _recover_corrupt_file() -> str | None:
    path = prompt_customization_path()
    if not path.exists():
        return None
    timestamp = cairo_now().strftime("%Y%m%d-%H%M%S-%f")
    backup = path.with_name(f"{path.stem}.corrupt-{timestamp}{path.suffix}")
    path.replace(backup)
    return backup.name


def reset_prompt_customization() -> dict[str, Any]:
    recovered_file: str | None = None
    try:
        previous = load_prompt_customization()
    except (UnicodeError, ValueError, json.JSONDecodeError):
        recovered_file = _recover_corrupt_file()
        previous = _default_state()
    history = list(previous["history"])
    event = {
        "timestamp": cairo_now().isoformat(),
        "action": "reset",
        "include_added": [],
        "include_removed": previous["include_phrases"],
        "exclude_added": [],
        "exclude_removed": previous["exclude_phrases"],
    }
    if recovered_file:
        event["recovered_corrupt_file"] = recovered_file
    history.append(event)
    state = _default_state()
    state["history"] = history
    _write_state(state)
    return state


def _remove_phrases(current: list[str], removed: object) -> list[str]:
    removed_keys = {phrase.casefold() for phrase in _normalize_phrases(removed)}
    return [phrase for phrase in current if phrase.casefold() not in removed_keys]


def _append_phrases(current: list[str], added: object) -> list[str]:
    return _normalize_phrases([*current, *_normalize_phrases(added)])


def _state_at_history_index(history: list[dict[str, Any]], history_index: int) -> tuple[list[str], list[str]]:
    include_phrases: list[str] = []
    exclude_phrases: list[str] = []
    for event in history[:history_index + 1]:
        if event.get("action") == "reset":
            include_phrases, exclude_phrases = [], []
            continue
        include_phrases = _remove_phrases(include_phrases, event.get("include_removed", []))
        exclude_phrases = _remove_phrases(exclude_phrases, event.get("exclude_removed", []))
        include_phrases = _append_phrases(include_phrases, event.get("include_added", []))
        exclude_phrases = _append_phrases(exclude_phrases, event.get("exclude_added", []))
    excluded_keys = {phrase.casefold() for phrase in exclude_phrases}
    return (
        [phrase for phrase in include_phrases if phrase.casefold() not in excluded_keys],
        exclude_phrases,
    )


def restore_prompt_customization(history_index: int) -> dict[str, Any]:
    previous = load_prompt_customization()
    history = list(previous["history"])
    if history_index < 0 or history_index >= len(history):
        raise IndexError("Prompt history entry does not exist.")
    include_phrases, exclude_phrases = _state_at_history_index(history, history_index)
    changes = _change_set(previous, include_phrases, exclude_phrases)
    history.append({
        "timestamp": cairo_now().isoformat(),
        "action": "restored",
        "restored_from_index": history_index,
        "restored_from_timestamp": history[history_index].get("timestamp"),
        **changes,
    })
    state = {
        "version": 1,
        "include_phrases": include_phrases,
        "exclude_phrases": exclude_phrases,
        "history": history,
    }
    _write_state(state)
    return state


def prompt_customization_block(state: dict[str, Any] | None = None) -> str:
    try:
        current = state or load_prompt_customization()
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError(
            "The prompt customization file is damaged or unreadable. Open Settings and use Reset to default prompt."
        ) from error
    include_phrases = current.get("include_phrases") or []
    exclude_phrases = current.get("exclude_phrases") or []
    if not include_phrases and not exclude_phrases:
        return ""
    include_text = ", ".join(include_phrases) if include_phrases else "(none)"
    exclude_text = ", ".join(exclude_phrases) if exclude_phrases else "(none)"
    return (
        "MANAGED RECOMMENDATION PHRASE GUIDANCE\n"
        "This section extends the existing extraction logic without replacing or weakening any base prompt rule.\n"
        f"Include phrases: {include_text}\n"
        "Treat visibly matching include phrases as explicit recommendation context for the surrounding stock-specific content, "
        "then extract it under the unchanged stock-identity, date-eligibility, and output rules.\n"
        f"Exclude phrases: {exclude_text}\n"
        "Do not return content visibly matching an exclude phrase as a recommendation. Exclude phrases take priority over "
        "include phrases when both apply."
    )
