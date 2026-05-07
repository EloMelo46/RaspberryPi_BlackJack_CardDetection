#!/usr/bin/env python3

"""
OBSOLETE - Kept for reference only

This file is no longer used. The card tracking logic (memory decay, player/dealer 
classification) has been integrated directly into run_card_detection.py.

The migration from Sony IMX500 to Hailo 10H consolidated this functionality
into the main inference loop for simplicity and performance.

See run_card_detection.py::update_card_tracking() for the current implementation.
"""

# Original logic (IMX500-based) preserved below for reference:
#
# PERSISTENT LISTS
# player_cards_persistent = []
# dealer_cards_persistent = []
#
# MEMORY DECAY COUNTER (Frames since last sighting)
# player_seen_counter = {}
# dealer_seen_counter = {}
#
# Number of frames until card is deleted
# DECAY_LIMIT = 20


            log(f"Dealer Cards: {dealer_cards_persistent}")
            log(f"Player Cards: {player_cards_persistent}")   

            action = bj.basic_strategy(player_cards_persistent, dealer_cards_persistent)
            log(f"Recommendation: {action}")
            # tail -f bj_log.txt >> to see in other terminal

            # Save information for web server in .txt files
            with open("outputs/latest.txt", "w") as f:
                f.write(action)

            with open("outputs/player_cards.txt", "w") as f:
                f.write(" ".join(player_cards_persistent))

            with open("outputs/dealer_cards.txt", "w") as f:
                f.write(" ".join(dealer_cards_persistent))
    
