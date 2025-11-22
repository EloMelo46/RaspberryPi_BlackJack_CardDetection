# bj_logic.py

def normalize_card(card):
    """
    Entfernt Symbol (z. B. 'd','h','s','c') und gibt nur den Kartenwert zurück.
    '3d' -> '3'
    'Kd' -> 'K'
    'As' -> 'A'
    '10h' -> '10'
    """
    card = str(card)

    # falls die Karte mit "10" beginnt (zweistellig)
    if card.startswith("10"):
        return "10"

    # sonst erster Buchstabe
    return card[0]


def card_value(card):

    card = normalize_card(card)

    if card in ["J", "Q", "K"]:
        return 10
    if card == "A":
        return 11
    return int(card)


def hand_type(cards):
    """
    Returns:
        ("pair", value)
        ("soft", total)
        ("hard", total)
    """

    # normalize all cards
    cards = [normalize_card(c) for c in cards]

    # Pair?
    if len(cards) == 2 and cards[0] == cards[1]:
        v = card_value(cards[0])
        return "pair", v * 2

    # Compute total with soft Ace handling
    values = [card_value(c) for c in cards]
    total = sum(values)

    # Soft?
    if "A" in cards:
        if total <= 21:
            return "soft", total
        total -= 10  # make Ace=1 if needed

    return "hard", total


def dealer_value(card):

    card = normalize_card(card) 

    """Convert dealer up-card symbol to numerical value."""
    if card in ["J", "Q", "K"]:
        return 10
    if card == "A":
        return 11
    return int(card)


def basic_strategy(player_cards, dealer_cards):
    """
    Implements exact Poker Basic Strategy.
    Returns: "Hit", "Stand", "Double", "Split"
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
