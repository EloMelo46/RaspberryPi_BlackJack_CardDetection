from deck_config import DeckROI
from deck_manager import DeckState
import postprocessing


def _state(deck_id: str, name: str, cards: list[str], role: str = "deck") -> DeckState:
    return DeckState(
        deck=DeckROI(deck_id=deck_id, name=name, role=role, x=0, y=0),
        cards=list(cards),
    )


def _prepare_round(monkeypatch, tmp_path, states: dict[str, DeckState]) -> None:
    monkeypatch.setattr(postprocessing, "PLAYER_STATS_PATH", tmp_path / "player_stats.json")
    monkeypatch.setattr(postprocessing.registry, "states", states)
    monkeypatch.setattr(postprocessing, "player_stats", {})
    monkeypatch.setattr(postprocessing, "player_bust_candidates", {})
    monkeypatch.setattr(postprocessing, "round_locked", False)


def test_player_bust_requires_same_hand_for_confirmation(monkeypatch):
    monkeypatch.setattr(postprocessing.config, "PLAYER_BUST_CONFIRM_MS", 100)
    monkeypatch.setattr(postprocessing, "player_bust_candidates", {})

    assert postprocessing._player_bust_is_confirmed("player-1", ["10h", "Qd", "2s"], now=1.00) is False
    assert postprocessing._player_bust_is_confirmed("player-1", ["10h", "Qd", "2s"], now=1.09) is False

    # A corrected prediction cancels the pending bust completely.
    assert postprocessing._player_bust_is_confirmed("player-1", ["10h", "Qd"], now=1.10) is False
    assert postprocessing._player_bust_is_confirmed("player-1", ["10h", "Qd", "2s"], now=1.11) is False
    assert postprocessing._player_bust_is_confirmed("player-1", ["2s", "Qd", "10h"], now=1.211) is True


def test_transient_player_bust_is_not_scored_when_dealer_is_terminal(monkeypatch, tmp_path):
    states = {
        "player-1": _state("player-1", "Player 1", ["10h", "Qd", "2s"]),
        "dealer": _state("dealer", "Dealer", ["10c", "8d"], role="dealer"),
    }
    _prepare_round(monkeypatch, tmp_path, states)

    postprocessing._publish_round_if_dealer_terminal(set())

    assert postprocessing.load_player_stats() == {}
    assert postprocessing.round_locked is False

    states["player-1"].cards = ["10h", "Qd"]
    postprocessing._publish_round_if_dealer_terminal(set())

    event = postprocessing.load_player_stats()["player-1"]["current_event"]
    assert event["result"] == "win"
    assert postprocessing.round_locked is True


def test_dealer_bust_scores_every_non_busted_player_as_win(monkeypatch, tmp_path):
    states = {
        "player-1": _state("player-1", "Player 1", ["10h", "Qd"]),
        "player-2": _state("player-2", "Player 2", ["9h", "8d"]),
        "dealer": _state("dealer", "Dealer", ["10c", "8c", "5s"], role="dealer"),
    }
    _prepare_round(monkeypatch, tmp_path, states)

    postprocessing._publish_round_if_dealer_terminal(set())

    stats = postprocessing.load_player_stats()
    assert stats["player-1"]["current_event"]["result"] == "win"
    assert stats["player-2"]["current_event"]["result"] == "win"
    assert stats["player-1"]["score"] == 1
    assert stats["player-2"]["score"] == 1
    assert postprocessing.round_locked is True


def test_dealer_bust_does_not_lock_round_before_a_player_appears(monkeypatch, tmp_path):
    states = {
        "dealer": _state("dealer", "Dealer", ["10c", "8c", "5s"], role="dealer"),
    }
    _prepare_round(monkeypatch, tmp_path, states)

    postprocessing._publish_round_if_dealer_terminal(set())
    assert postprocessing.round_locked is False

    states["player-1"] = _state("player-1", "Player 1", ["10h", "Qd"])
    postprocessing._publish_round_if_dealer_terminal(set())

    event = postprocessing.load_player_stats()["player-1"]["current_event"]
    assert event["result"] == "win"
    assert postprocessing.round_locked is True
