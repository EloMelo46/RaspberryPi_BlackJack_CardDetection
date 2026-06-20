from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

import card_logic as bj
from config import CARD_LABELS, DECAY_LIMIT
from deck_config import (
    DeckROI,
    decks_to_dicts,
    load_active_deck_id,
    load_decks,
    save_active_deck_id,
    save_decks,
    upsert_deck,
    remove_deck,
    find_deck,
)


def card_hi_lo(card_label: str) -> int:
    rank = bj.normalize_card(card_label)
    if rank in ["2", "3", "4", "5", "6"]:
        return 1
    if rank in ["7", "8", "9"]:
        return 0
    return -1


def card_points(card_label: str) -> int:
    rank = bj.normalize_card(card_label)
    if rank == "A":
        return 1
    if rank in ["J", "Q", "K"]:
        return 10
    return int(rank)


def hand_totals(cards: List[str]) -> List[int]:
    if not cards:
        return []
    low_total = sum(card_points(card) for card in cards)
    ace_count = sum(1 for card in cards if bj.normalize_card(card) == "A")
    totals = {low_total}
    for ace_as_high in range(1, ace_count + 1):
        totals.add(low_total + 10 * ace_as_high)
    return sorted(totals)


def hand_points_text(cards: List[str]) -> str:
    totals = hand_totals(cards)
    if not totals:
        return "-"
    playable = [total for total in totals if total <= 21]
    if len(playable) >= 2:
        return "/".join(str(total) for total in playable)
    if playable:
        return str(max(playable))
    return str(min(totals))


def best_hand_value(cards: List[str]) -> int:
    totals = hand_totals(cards)
    if not totals:
        return 0
    playable = [total for total in totals if total <= 21]
    return max(playable) if playable else min(totals)


@dataclass
class DeckState:
    deck: DeckROI
    cards: List[str] = field(default_factory=list)
    seen_counter: Dict[str, int] = field(default_factory=dict)
    last_recommendation: str = "Waiting for cards"

    def as_dict(self) -> dict:
        data = asdict(self.deck)
        data["cards"] = list(self.cards)
        data["seen_counter"] = dict(self.seen_counter)
        data["last_recommendation"] = self.last_recommendation
        data["running_count"] = self.running_count()
        data["true_count"] = self.true_count()
        data["points"] = hand_points_text(self.cards)
        data["best_value"] = best_hand_value(self.cards)
        return data

    def running_count(self) -> int:
        return int(sum(card_hi_lo(card) for card in self.cards))

    def true_count(self, num_decks: int = 1) -> float:
        if num_decks <= 0:
            num_decks = 1
        return float(self.running_count() / float(num_decks))

    def recommendation(self) -> str:
        if len(self.cards) < 2:
            return self.last_recommendation if self.last_recommendation else "Waiting for cards"
        try:
            htype, value = bj.hand_type(self.cards)
            return f"{htype.title()} {value}"
        except Exception:
            return "Waiting for cards"


class DeckRegistry:
    def __init__(self):
        self.decks: List[DeckROI] = load_decks()
        self.active_deck_id: Optional[str] = load_active_deck_id()
        self.states: Dict[str, DeckState] = {
            deck.deck_id: DeckState(deck=deck, cards=[], seen_counter={}) for deck in self.decks
        }
        self._ensure_active_deck()

    def _ensure_active_deck(self) -> None:
        if self.active_deck_id in self.states and not self.states[self.active_deck_id].deck.is_dealer():
            return
        for deck in self.decks:
            if not deck.is_dealer():
                self.active_deck_id = deck.deck_id
                return
        self.active_deck_id = None

    def refresh_from_disk(self) -> None:
        loaded_decks = load_decks()
        if not loaded_decks and self.decks:
            return
        self.decks = loaded_decks
        self.active_deck_id = load_active_deck_id()
        current = {deck.deck_id: self.states.get(deck.deck_id) for deck in self.decks}
        self.states = {}
        for deck in self.decks:
            state = current.get(deck.deck_id)
            if state is None:
                state = DeckState(deck=deck)
            state.deck = deck
            self.states[deck.deck_id] = state
        self._ensure_active_deck()

    def list_decks(self) -> List[dict]:
        return [state.as_dict() for state in self.states.values()]

    def dealer_state(self) -> Optional[DeckState]:
        for state in self.states.values():
            if state.deck.is_dealer():
                return state
        return None

    def has_dealer(self) -> bool:
        return self.dealer_state() is not None

    def ready_errors(self) -> List[str]:
        errors = []
        if not self.has_dealer():
            errors.append("Dealer ROI missing")
        if self.active_deck_id is None:
            errors.append("No player deck configured")
        return errors

    def get_active_state(self) -> Optional[DeckState]:
        if self.active_deck_id is None:
            return None
        return self.states.get(self.active_deck_id)

    def get_active_recommendation(self) -> str:
        active = self.get_active_state()
        dealer = self.dealer_state()
        if dealer is None:
            return "Error: Dealer ROI missing"
        if active is None:
            return "No deck selected"
        if len(active.cards) < 2:
            return active.last_recommendation if active.last_recommendation else "Waiting for cards"
        try:
            return bj.basic_strategy(active.cards, dealer.cards)
        except Exception:
            return "Waiting for cards"

    def set_active_deck(self, deck_id: str) -> bool:
        state = self.states.get(deck_id)
        if state is not None and not state.deck.is_dealer():
            self.active_deck_id = deck_id
            save_active_deck_id(deck_id)
            return True
        return False

    def upsert(self, deck: DeckROI) -> None:
        self.decks = upsert_deck(self.decks, deck)
        save_decks(self.decks, self.active_deck_id)
        self.refresh_from_disk()

    def remove(self, deck_id: str) -> None:
        self.decks = remove_deck(self.decks, deck_id)
        active = None if self.active_deck_id == deck_id else self.active_deck_id
        save_decks(self.decks, active)
        self.refresh_from_disk()

    def clear(self) -> None:
        for state in self.states.values():
            state.cards = []
            state.seen_counter = {}
            state.last_recommendation = "Waiting for cards"

    def update_deck_cards(self, deck_id: str, detected_cards: List[str]) -> None:
        state = self.states.get(deck_id)
        if state is None:
            return

        detected_cards = [card for card in detected_cards if card in CARD_LABELS]
        seen = set(detected_cards)

        for card in detected_cards:
            state.seen_counter[card] = 0

        for card in list(state.seen_counter.keys()):
            if card not in seen:
                state.seen_counter[card] += 1

        # rebuild cards from currently visible set and decayed counters
        current_cards = [card for card in detected_cards if state.seen_counter.get(card, 0) < DECAY_LIMIT]
        if current_cards:
            state.cards = list(dict.fromkeys(current_cards))
        else:
            state.cards = [card for card in state.cards if state.seen_counter.get(card, 0) < DECAY_LIMIT]

        if state.deck.is_dealer():
            state.last_recommendation = "Dealer"
        else:
            state.last_recommendation = self.get_active_recommendation() if deck_id == self.active_deck_id else state.recommendation()

    def update_dealer_cards(self, detected_cards: List[str]) -> None:
        dealer = self.dealer_state()
        if dealer is None:
            return
        self.update_deck_cards(dealer.deck.deck_id, detected_cards)

    def global_running_count(self) -> int:
        return int(sum(state.running_count() for state in self.states.values()))

    def global_true_count(self, num_decks: int = 1) -> float:
        if num_decks <= 0:
            num_decks = 1
        return float(self.global_running_count() / float(num_decks))

    def summary(self, num_decks: int = 1) -> dict:
        active = self.get_active_state()
        dealer = self.dealer_state()
        return {
            "active_deck_id": self.active_deck_id,
            "decks": self.list_decks(),
            "dealer": dealer.as_dict() if dealer else None,
            "active_deck": active.as_dict() if active else None,
            "running_count": self.global_running_count(),
            "true_count": self.global_true_count(num_decks=num_decks),
            "ready_errors": self.ready_errors(),
        }


registry = DeckRegistry()
