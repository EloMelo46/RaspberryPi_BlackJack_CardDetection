from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_DECK_WIDTH = 640
DEFAULT_DECK_HEIGHT = 480
DECK_CONFIG_PATH = Path("outputs") / "decks.json"
DECK_CONFIG_BACKUP_PATH = Path("outputs") / "decks.bak.json"
DECK_STATE_PATH = Path("outputs") / "deck_state.json"


@dataclass
class DeckROI:
    deck_id: str
    name: str
    x: int
    y: int
    width: int = DEFAULT_DECK_WIDTH
    height: int = DEFAULT_DECK_HEIGHT
    enabled: bool = True
    role: str = "deck"

    def clamp(self, frame_width: int, frame_height: int) -> "DeckROI":
        x = max(0, min(int(self.x), max(0, frame_width - 1)))
        y = max(0, min(int(self.y), max(0, frame_height - 1)))
        width = max(1, min(int(self.width), frame_width - x))
        height = max(1, min(int(self.height), frame_height - y))
        return DeckROI(
            deck_id=self.deck_id,
            name=self.name,
            role=self.role,
            x=x,
            y=y,
            width=width,
            height=height,
            enabled=bool(self.enabled),
        )

    def is_dealer(self) -> bool:
        return str(self.role).lower() == "dealer"


def _default_decks() -> List[DeckROI]:
    return [DeckROI(deck_id="deck-1", name="Deck 1", role="deck", x=0, y=0)]


def ensure_config_dir() -> None:
    DECK_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)


def _read_config() -> Dict[str, Any]:
    ensure_config_dir()
    if not DECK_CONFIG_PATH.exists():
        return {"active_deck_id": None, "decks": [asdict(deck) for deck in _default_decks()]}

    raw = None
    for attempt in range(3):
        try:
            raw = json.loads(DECK_CONFIG_PATH.read_text())
            break
        except Exception:
            if attempt < 2:
                time.sleep(0.02)
    if raw is None:
        return {"active_deck_id": None, "decks": [], "_invalid": True}

    if isinstance(raw, list):
        return {"active_deck_id": None, "decks": raw}
    if isinstance(raw, dict):
        decks = raw.get("decks")
        if isinstance(decks, list):
            return {"active_deck_id": raw.get("active_deck_id"), "decks": decks}

    return {"active_deck_id": None, "decks": [asdict(deck) for deck in _default_decks()]}


def load_active_deck_id() -> Optional[str]:
    active = _read_config().get("active_deck_id")
    return str(active) if active else None


def load_decks() -> List[DeckROI]:
    config = _read_config()
    if config.get("_invalid"):
        return []
    raw = config.get("decks", [])

    decks: List[DeckROI] = []
    for item in raw if isinstance(raw, list) else []:
        try:
            decks.append(
                DeckROI(
                    deck_id=str(item.get("deck_id") or item.get("id") or "deck-1"),
                    name=str(item.get("name") or "Deck"),
                    role=str(item.get("role") or ("dealer" if str(item.get("deck_id") or item.get("id") or "").lower() == "dealer" else "deck")),
                    x=int(item.get("x", 0)),
                    y=int(item.get("y", 0)),
                    width=int(item.get("width", DEFAULT_DECK_WIDTH)),
                    height=int(item.get("height", DEFAULT_DECK_HEIGHT)),
                    enabled=bool(item.get("enabled", True)),
                )
            )
        except Exception:
            continue

    return decks or _default_decks()


def save_decks(decks: List[DeckROI], active_deck_id: Optional[str] = None) -> None:
    ensure_config_dir()
    if active_deck_id is None:
        active_deck_id = load_active_deck_id()
    serializable = {
        "active_deck_id": active_deck_id,
        "decks": [asdict(deck) for deck in decks],
    }
    tmp_path = DECK_CONFIG_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(serializable, indent=2))
    if DECK_CONFIG_PATH.exists():
        try:
            DECK_CONFIG_BACKUP_PATH.write_text(DECK_CONFIG_PATH.read_text())
        except Exception:
            pass
    tmp_path.replace(DECK_CONFIG_PATH)


def save_active_deck_id(deck_id: Optional[str]) -> None:
    decks = load_decks()
    if not decks:
        return
    save_decks(decks, active_deck_id=deck_id)


def upsert_deck(decks: List[DeckROI], deck: DeckROI) -> List[DeckROI]:
    updated: List[DeckROI] = []
    replaced = False
    for item in decks:
        if item.deck_id == deck.deck_id:
            updated.append(deck)
            replaced = True
        else:
            updated.append(item)
    if not replaced:
        updated.append(deck)
    return updated


def remove_deck(decks: List[DeckROI], deck_id: str) -> List[DeckROI]:
    return [deck for deck in decks if deck.deck_id != deck_id]


def deck_to_dict(deck: DeckROI) -> Dict[str, Any]:
    return asdict(deck)


def decks_to_dicts(decks: List[DeckROI]) -> List[Dict[str, Any]]:
    return [deck_to_dict(deck) for deck in decks]


def find_deck(decks: List[DeckROI], deck_id: str) -> Optional[DeckROI]:
    for deck in decks:
        if deck.deck_id == deck_id:
            return deck
    return None


def find_dealer(decks: List[DeckROI]) -> Optional[DeckROI]:
    for deck in decks:
        if deck.is_dealer():
            return deck
    return None
