from typing import List, Optional
from dataclasses import dataclass, field
import card_logic


@dataclass
class Hand:
    id: int
    owner: str  # 'player' or 'dealer' or 'split'
    cards: List[str] = field(default_factory=list)
    status: str = "active"  # active, stand, bust, blackjack, finished
    is_split: bool = False

    def add_card(self, card: str):
        if card not in self.cards:
            self.cards.append(card)
        self._update_status()

    def remove_card(self, card: str):
        if card in self.cards:
            self.cards.remove(card)
        self._update_status()

    def value(self) -> int:
        _, val = card_logic.hand_type(self.cards)
        return val

    def is_bust(self) -> bool:
        return self.value() > 21

    def is_blackjack(self) -> bool:
        return len(self.cards) == 2 and self.value() == 21

    def _update_status(self):
        if self.is_blackjack():
            self.status = "blackjack"
        elif self.is_bust():
            self.status = "bust"


class GameSession:
    def __init__(self):
        self.player_hands: List[Hand] = []
        self.dealer_hand: Optional[Hand] = None
        self.current_hand_idx: int = 0
        self.next_hand_id: int = 1
        self.waiting_for_user_action: bool = False
        self.phase: str = "idle"  # idle, player, dealer, compute, complete
        self.outcome_published: bool = False

    def reset(self):
        self.player_hands = []
        self.dealer_hand = None
        self.current_hand_idx = 0
        self.next_hand_id = 1
        self.waiting_for_user_action = False
        self.phase = "idle"
        self.outcome_published = False

    def create_new_player_hand(self, cards: Optional[List[str]] = None) -> Hand:
        h = Hand(id=self.next_hand_id, owner="player", cards=cards or [])
        self.next_hand_id += 1
        self.player_hands.append(h)
        return h

    def ensure_dealer_hand(self) -> Hand:
        if self.dealer_hand is None:
            self.dealer_hand = Hand(id=0, owner="dealer", cards=[])
        return self.dealer_hand

    def start_dealer_turn(self):
        self.phase = "dealer"
        # mark player sequence finished
        self.current_hand_idx = len(self.player_hands)

    def end_round(self):
        self.phase = "complete"

    def get_active_hand(self) -> Optional[Hand]:
        if not self.player_hands:
            return None
        if self.current_hand_idx < 0 or self.current_hand_idx >= len(self.player_hands):
            return None
        return self.player_hands[self.current_hand_idx]

    def start_split(self, hand_idx: int) -> bool:
        # split only allowed if exactly 2 same-value cards
        if hand_idx < 0 or hand_idx >= len(self.player_hands):
            return False
        hand = self.player_hands[hand_idx]
        if len(hand.cards) != 2:
            return False
        # compare rank only (allow different suits)
        r0 = card_logic.normalize_card(hand.cards[0])
        r1 = card_logic.normalize_card(hand.cards[1])
        if r0 != r1:
            return False
        # create two hands each with one card
        c1, c2 = hand.cards[0], hand.cards[1]
        hand.cards = [c1]
        hand.is_split = True
        new_hand = Hand(id=self.next_hand_id, owner="player", cards=[c2], is_split=True)
        self.next_hand_id += 1
        # insert new hand after current
        self.player_hands.insert(hand_idx + 1, new_hand)
        return True

    def stand_current_hand(self):
        h = self.get_active_hand()
        if h:
            h.status = "stand"
        self.advance_hand()

    def advance_hand(self):
        self.current_hand_idx += 1
        if self.current_hand_idx >= len(self.player_hands):
            # all player hands done
            self.waiting_for_user_action = False
            # Automatically start dealer turn when all player hands are processed
            self.start_dealer_turn()

    def assign_detected_cards(self, detected_player_cards: List[str], detected_dealer_cards: List[str]):
        # detect dealer second-card reveal transition and update dealer hand
        prev_dealer_count = len(self.dealer_hand.cards) if self.dealer_hand else 0
        if detected_dealer_cards:
            d = self.ensure_dealer_hand()
            # overwrite dealer hand with the latest detected set
            d.cards = list(detected_dealer_cards)
            d._update_status()
            if prev_dealer_count < 2 and len(d.cards) >= 2:
                # Dealer revealed second card
                # if players already finished, start dealer turn
                if all(h.status in ["stand", "bust", "blackjack", "finished"] for h in self.player_hands):
                    self.start_dealer_turn()
            # If currently in dealer phase, check whether dealer should stop (>=17)
            try:
                if self.phase == "dealer":
                    if d.value() >= 17:
                        d.status = "stand"
                        self.phase = "compute"
            except Exception:
                pass

        # If starting from idle and player cards detected -> create initial hand and enter player phase
        if self.phase == "idle" and detected_player_cards:
            h = self.create_new_player_hand(cards=list(detected_player_cards))
            self.phase = "player"
            # If newly created hand is a pair and basic strategy suggests split, wait for user action
            try:
                if len(h.cards) == 2:
                    strat = card_logic.basic_strategy(h.cards, self.get_dealer_cards()) if self.get_dealer_cards() else ""
                    if strat == "Split":
                        self.waiting_for_user_action = True
                        return
            except Exception:
                pass
            self.waiting_for_user_action = False
            return

        # Map detected player cards: collect known cards and add unknowns to the active hand
        known = set()
        for h in self.player_hands:
            for c in h.cards:
                known.add(c)

        active = self.get_active_hand() or (self.player_hands[0] if self.player_hands else None)
        # If no existing hand and player cards are present, create one
        if active is None and detected_player_cards:
            active = self.create_new_player_hand(cards=list(detected_player_cards))
            self.phase = "player"
            self.waiting_for_user_action = False
            return
        if active is None:
            return

        added_any = False
        for c in detected_player_cards:
            if c not in known:
                active.add_card(c)
                added_any = True

        # During player phase, evaluate whether player should stand.
        # This runs even without new cards so the state can progress on stable frames.
        if self.phase == "player" and active.status == "active":
            # if basic strategy is available and dealer upcard is known, decide
            try:
                dealer_cards = self.get_dealer_cards()
                if dealer_cards:
                    strat = card_logic.basic_strategy(active.cards, dealer_cards)
                    if strat in ["Stand", "Double"]:
                        active.status = "stand"
                        self.advance_hand()
                    elif strat == "Split":
                        # let UI decide; mark waiting
                        self.waiting_for_user_action = True
                    else:
                        # keep hitting
                        pass
                else:
                    # no dealer upcard yet — wait for dealer card to decide
                    pass
            except Exception:
                pass

        # If all player hands are finished, and dealer has enough cards, move to dealer
        if self.phase == "player" and all(h.status in ["stand", "bust", "blackjack", "finished"] for h in self.player_hands):
            # if dealer already has 2+ cards, start dealer
            if self.dealer_hand and len(self.dealer_hand.cards) >= 2:
                self.start_dealer_turn()

    def get_all_player_cards(self) -> List[str]:
        out = []
        for h in self.player_hands:
            out.extend(h.cards)
        return out

    def get_dealer_cards(self) -> List[str]:
        return list(self.dealer_hand.cards) if self.dealer_hand else []

    def compute_outcomes(self) -> List[dict]:
        # Requires dealer hand to be present
        results = []
        if not self.dealer_hand:
            return results
        dealer_val = self.dealer_hand.value()
        dealer_bust = self.dealer_hand.is_bust()
        for h in self.player_hands:
            if h.status == "bust" or h.is_bust():
                results.append({"hand_id": h.id, "result": "lose"})
                continue
            if h.is_blackjack() and not self.dealer_hand.is_blackjack():
                results.append({"hand_id": h.id, "result": "win_blackjack"})
                continue
            if self.dealer_hand.is_blackjack() and not h.is_blackjack():
                results.append({"hand_id": h.id, "result": "lose"})
                continue
            if dealer_bust:
                results.append({"hand_id": h.id, "result": "win"})
                continue
            pv = h.value()
            if pv > dealer_val:
                results.append({"hand_id": h.id, "result": "win"})
            elif pv == dealer_val:
                results.append({"hand_id": h.id, "result": "push"})
            else:
                results.append({"hand_id": h.id, "result": "lose"})
        return results

    def reset_if_empty(self, persisted_player_cards: List[str], persisted_dealer_cards: List[str]):
        if not persisted_player_cards and not persisted_dealer_cards:
            self.reset()
