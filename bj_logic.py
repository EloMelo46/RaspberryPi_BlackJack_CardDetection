# bj_logic.py

def normalize_card(card):
    """
    Removes suit symbol (e.g., 'd','h','s','c') and returns only the card rank.
    Examples:
        '3d' -> '3'
        'Kd' -> 'K'
        'As' -> 'A'
        '10h' -> '10'
    """
    card = str(card)

    # 10 as special case (two digits)
    if card.startswith("10"):
        return "10"

    # otherwise first character
    return card[0]


def card_value(card):
    """Numerical card value."""
    card = normalize_card(card)

    if card in ["J", "Q", "K"]:
        return 10
    if card == "A":
        return 11
    return int(card)


def hand_type(cards):
    """
    Determines the player's hand type.

    Returns:
        ("pair", value)
        ("soft", total)
        ("hard", total)
    """

    cards = [normalize_card(c) for c in cards]

    # -------- PAIR-CHECK --------
    if len(cards) == 2 and cards[0] == cards[1]:
        v = card_value(cards[0])
        return "pair", v * 2

    # -------- SOFT/HARD-LOGIC --------
    values = [card_value(c) for c in cards]
    total = sum(values)

    # Number of Aces (all counted as 11 so far)
    aces = cards.count("A")

    # Convert Aces from 11 -> 1 until total <= 21
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1

    # Soft Hand: If at least ONE Ace counts as 11
    if "A" in cards and aces == cards.count("A"):
        # means: all Aces are still counted as 11
        if total <= 21:
            return "soft", total

    # If no Ace counts as 11 -> hard hand
    return "hard", total


def dealer_value(card):
    """Converts Dealer-Upcard to numerical value."""
    card = normalize_card(card)

    if card in ["J", "Q", "K"]:
        return 10
    if card == "A":
        return 11
    return int(card)


def basic_strategy(player_cards, dealer_cards):
    """
    Blackjack Basic Strategy (4–8 Deck, Dealer Hits Soft 17).
    Rückgabe:
        "Hit", "Stand", "Double", "Split"
    """

    player_cards = [normalize_card(c) for c in player_cards]
    dealer_cards = [normalize_card(c) for c in dealer_cards]

    if len(dealer_cards) == 0:
        return "No dealer card detected"

    dealer = dealer_value(dealer_cards[0])
    htype, value = hand_type(player_cards)

    # ============================
    #        PAIR STRATEGY
    # ============================
    if htype == "pair":
        card = player_cards[0]

        if card == "8":
            return "Split"
        if card == "A":
            return "Split"
        if card in ["10", "J", "Q", "K"]:
            return "Stand"
        if card in ["2", "3"]:
            return "Split" if 2 <= dealer <= 7 else "Hit"
        if card == "4":
            return "Split" if dealer in [5, 6] else "Hit"
        if card == "5":
            return "Double" if 2 <= dealer <= 9 else "Hit"
        if card == "6":
            return "Split" if 2 <= dealer <= 6 else "Hit"
        if card == "7":
            return "Split" if 2 <= dealer <= 7 else "Hit"
        if card == "9":
            return "Stand" if dealer in [7, 10, 11] else "Split"

    # ============================
    #        SOFT STRATEGY
    # ============================
    if htype == "soft":
        if value in [13, 14, 15, 16, 17]:
            return "Double" if 4 <= dealer <= 6 else "Hit"
        if value == 18:
            if 3 <= dealer <= 6:
                return "Double"
            if dealer in [2, 7, 8]:
                return "Stand"
            return "Hit"
        if value >= 19:
            return "Stand"

    # ============================
    #       HARD STRATEGY
    # ============================
    if htype == "hard":
        if value <= 8:
            return "Hit"
        if value == 9:
            return "Double" if 3 <= dealer <= 6 else "Hit"
        if value == 10:
            return "Double" if 2 <= dealer <= 9 else "Hit"
        if value == 11:
            return "Double"
        if value == 12:
            return "Stand" if 4 <= dealer <= 6 else "Hit"
        if 13 <= value <= 16:
            return "Stand" if 2 <= dealer <= 6 else "Hit"
        if value >= 17:
            return "Stand"

    return "Hit"
