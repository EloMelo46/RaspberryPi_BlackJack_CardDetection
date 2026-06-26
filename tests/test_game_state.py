from game_state import GameSession, Hand


def test_detected_cards_create_initial_player_hand():
    session = GameSession()

    session.assign_detected_cards(["9h", "7s"], [])

    assert session.phase == "player"
    assert len(session.player_hands) == 1
    assert session.get_all_player_cards() == ["9h", "7s"]
    assert session.get_dealer_cards() == []
    assert session.get_active_hand().cards == ["9h", "7s"]


def test_detected_new_cards_are_added_only_once_to_active_hand():
    session = GameSession()
    session.assign_detected_cards(["5h", "6s"], [])

    session.assign_detected_cards(["5h", "6s", "Kd"], [])
    session.assign_detected_cards(["5h", "6s", "Kd"], [])

    assert session.get_all_player_cards() == ["5h", "6s", "Kd"]
    assert session.get_active_hand().value() == 21


def test_pair_split_creates_two_split_hands_with_one_card_each():
    session = GameSession()
    session.create_new_player_hand(["9h", "9s"])

    assert session.start_split(0) is True

    assert len(session.player_hands) == 2
    assert session.player_hands[0].cards == ["9h"]
    assert session.player_hands[1].cards == ["9s"]
    assert session.player_hands[0].is_split is True
    assert session.player_hands[1].is_split is True
    assert session.player_hands[0].id == 1
    assert session.player_hands[1].id == 2


def test_split_is_rejected_for_non_pair_or_wrong_hand_index():
    session = GameSession()
    session.create_new_player_hand(["9h", "8s"])

    assert session.start_split(0) is False
    assert session.start_split(-1) is False
    assert session.start_split(99) is False
    assert len(session.player_hands) == 1
    assert session.player_hands[0].cards == ["9h", "8s"]


def test_strategy_waits_for_user_action_when_pair_should_split():
    session = GameSession()

    session.assign_detected_cards(["8h", "8s"], ["6d"])

    assert session.phase == "player"
    assert session.waiting_for_user_action is True
    assert session.get_active_hand().cards == ["8h", "8s"]


def test_stand_current_hand_advances_to_dealer_after_last_player_hand():
    session = GameSession()
    session.create_new_player_hand(["10h", "Qh"])
    session.phase = "player"

    session.stand_current_hand()

    assert session.player_hands[0].status == "stand"
    assert session.phase == "dealer"
    assert session.get_active_hand() is None


def test_dealer_reveal_moves_finished_players_to_dealer_turn():
    session = GameSession()
    player = session.create_new_player_hand(["10h", "Qh"])
    player.status = "stand"
    session.phase = "player"
    session.assign_detected_cards([], ["9d"])

    assert session.phase == "player"

    session.assign_detected_cards([], ["9d", "7s"])

    assert session.phase == "dealer"
    assert session.get_dealer_cards() == ["9d", "7s"]


def test_dealer_stands_and_phase_moves_to_compute_at_17_or_more():
    session = GameSession()
    player = session.create_new_player_hand(["10h", "7h"])
    player.status = "stand"
    session.start_dealer_turn()

    session.assign_detected_cards([], ["10d", "7s"])

    assert session.dealer_hand.status == "stand"
    assert session.phase == "compute"


def test_hand_values_cover_blackjack_soft_hand_and_bust():
    assert Hand(id=1, owner="player", cards=["As", "Kh"]).is_blackjack() is True
    assert Hand(id=1, owner="player", cards=["As", "6h"]).value() == 17
    assert Hand(id=1, owner="player", cards=["As", "9h", "5d"]).value() == 15

    bust = Hand(id=1, owner="player", cards=["10s"])
    bust.add_card("Qh")
    bust.add_card("2d")

    assert bust.status == "bust"
    assert bust.is_bust() is True


def test_outcomes_cover_win_lose_push_blackjack_and_dealer_bust():
    session = GameSession()
    session.create_new_player_hand(["10h", "Qh"])
    session.ensure_dealer_hand().cards = ["9d", "10s"]
    assert session.compute_outcomes() == [{"hand_id": 1, "result": "win"}]

    session = GameSession()
    session.create_new_player_hand(["10h", "Qh", "2d"])
    session.ensure_dealer_hand().cards = ["9d", "10s"]
    assert session.compute_outcomes() == [{"hand_id": 1, "result": "lose"}]

    session = GameSession()
    session.create_new_player_hand(["10h", "9h"])
    session.ensure_dealer_hand().cards = ["9d", "10s"]
    assert session.compute_outcomes() == [{"hand_id": 1, "result": "push"}]

    session = GameSession()
    session.create_new_player_hand(["As", "Kh"])
    session.ensure_dealer_hand().cards = ["9d", "8s"]
    assert session.compute_outcomes() == [{"hand_id": 1, "result": "win_blackjack"}]

    session = GameSession()
    session.create_new_player_hand(["10h", "7h"])
    session.ensure_dealer_hand().cards = ["10d", "8s", "5c"]
    assert session.compute_outcomes() == [{"hand_id": 1, "result": "win"}]


def test_multiple_split_hands_get_individual_outcomes():
    session = GameSession()
    session.create_new_player_hand(["8h", "8s"])
    assert session.start_split(0) is True
    session.player_hands[0].add_card("10d")
    session.player_hands[1].add_card("2c")
    session.ensure_dealer_hand().cards = ["10s", "7d"]

    assert session.compute_outcomes() == [
        {"hand_id": 1, "result": "win"},
        {"hand_id": 2, "result": "lose"},
    ]


def test_reset_if_empty_clears_session_state():
    session = GameSession()
    session.create_new_player_hand(["As", "Kh"])
    session.ensure_dealer_hand().cards = ["9d"]
    session.phase = "player"

    session.reset_if_empty([], [])

    assert session.player_hands == []
    assert session.dealer_hand is None
    assert session.phase == "idle"
    assert session.current_hand_idx == 0


def test_reset_if_empty_keeps_state_when_cards_are_persisted():
    session = GameSession()
    session.create_new_player_hand(["As", "Kh"])

    session.reset_if_empty(["As", "Kh"], [])

    assert len(session.player_hands) == 1
    assert session.get_all_player_cards() == ["As", "Kh"]
