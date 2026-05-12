#!/usr/bin/env python3
"""
commentary_engine.py

Blackjack commentary engine usable from `main.py`.

It exposes `CommentaryEngine.process_state(state_dict)` which accepts the
in-memory game state dict returned by `postprocessing.get_game_state_dict()`.

Requirements:
    pip install openai
    export OPENAI_API_KEY=...
"""

import hashlib
import json
import time
import threading
import subprocess
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from openai import OpenAI


class CommentaryEngine:
    def __init__(
        self,
        output_dir: str = "commentary_output",
        text_model: str = "gpt-5.4-mini",
        tts_model: str = "gpt-4o-mini-tts",
        voice: str = "echo",
        cooldown_seconds: float = 10.0,
        enable_audio: bool = True,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.text_model = text_model
        self.tts_model = tts_model
        self.voice = voice
        self.cooldown_seconds = cooldown_seconds
        self.enable_audio = enable_audio

        self.client = OpenAI()

        self.last_state_hash: Optional[str] = None
        self.last_comment_time = 0.0
        self._worker_lock = threading.Lock()
        self._playback_lock = threading.Lock()
        self._current_player_proc = None
        self._last_played_audio_mtime: float = 0.0

    @staticmethod
    def frequency_to_cooldown(frequency: str) -> float:
        """Map UI-friendly frequency levels to cooldown seconds."""
        f = (frequency or "mittel").strip().lower()
        if f in {"wenig", "low"}:
            return 18.0
        if f in {"staendig", "ständig", "high"}:
            return 2.0
        return 6.0

    def set_frequency(self, frequency: str):
        self.cooldown_seconds = self.frequency_to_cooldown(frequency)

    def normalize_state_for_hash(self, state: Dict[str, Any]) -> str:
        relevant = {
            "dealer_cards": state.get("dealer_cards"),
            "player_cards": state.get("player_cards"),
            "player_score": state.get("player_score"),
            "dealer_score": state.get("dealer_score"),
            "phase": state.get("phase"),
            "winner": state.get("winner"),
            "round_id": state.get("round_id"),
        }
        raw = json.dumps(relevant, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def should_comment(self, state: Dict[str, Any]) -> bool:
        if self.enable_audio and self.is_playing_audio():
            return False
        now = time.time()
        if now - self.last_comment_time < self.cooldown_seconds:
            return False
        current_hash = self.normalize_state_for_hash(state)
        if current_hash == self.last_state_hash:
            return False
        self.last_state_hash = current_hash
        self.last_comment_time = now
        return True

    def build_prompt(self, state: Dict[str, Any]) -> str:
        return f"""
Du bist ein lustiger, enthusiastischer, sarkastischer Blackjack-Kommentator!

Du kennst die Bedeutung dieses Game-State-JSON:

- player_wins: Anzahl gewonnener Runden des Spielers.
- dealer_wins: Anzahl gewonnener Runden des Dealers.
- pushes: Anzahl Unentschieden.
- blackjacks: Anzahl Blackjacks des Spielers.
- last_outcome: Ergebnis der letzten Runde, z.B. player_win, dealer_win, push, blackjack oder null.
- round_phase: Aktuelle Spielphase. player = Spieler ist am Zug, dealer = Dealer ist am Zug, round_over = Runde beendet.
- current_leader: Wer aktuell vorne liegt. player, dealer, tie oder unknown.
- player_hands: Liste der Spielerhände. Mehrere Hände sind möglich bei Split.
- id: Nummer der Spielerhand.
- status: Zustand der Hand. active = noch im Spiel, stood = Spieler bleibt stehen, busted = über 21, blackjack = Blackjack.
- points: Aktueller Punktewert der Hand.
- type: hard = kein flexibles Ass, soft = Ass kann als 1 oder 11 zählen.
- cards: Karten der Hand. Beispiel 5c = 5 of clubs, Js = Jack of spades.
- dealer_hand: Aktuelle sichtbare Dealer-Hand.
- counts.running_count: Laufender Hi-Lo Count.
- counts.true_count: Running Count geteilt durch verbleibende Decks.
- counts.decks: Anzahl verwendeter Decks.

Karten-Codes:
- c = clubs / Kreuz
- d = diamonds / Karo
- h = hearts / Herz
- s = spades / Pik
- A = Ass
- J = Bube
- Q = Dame
- K = König

Aufgabe:
Kommentiere den aktuellen Spielzustand in genau einem kurzen Satz wie ein Komiker.

Regeln:
- Antworte und reagiere blitzschnell.
- Maximal 10 Wörter.
- Keine langen Erklärungen.
- Keine Strategie-Tabelle.
- Kein Markdown.
- Kein Emoji.
- Humorvoll, aber nicht beleidigend.
- Du beobachtest das Spiel wie ein Sportkommentator.
- Wenn der Spieler schlecht steht, darfst du trocken sarkastisch sein.
- Wenn der Spieler gut steht, darfst du übertrieben dramatisch loben.
- Nutze die Werte aus dem JSON korrekt.
- Erfinde keine Karten oder Spielstände dazu.

Spielzustand:
{json.dumps(state, ensure_ascii=False, indent=2)}
"""

    def generate_text_comment(self, state: Dict[str, Any]) -> Optional[str]:
        prompt = self.build_prompt(state)
        try:
            resp = self.client.responses.create(model=self.text_model, input=prompt)
            return getattr(resp, "output_text", "").strip()
        except Exception:
            return None

    def save_text_comment(self, comment: str) -> Path:
        path = self.output_dir / "latest_comment.txt"
        path.write_text(comment, encoding="utf-8")
        return path

    def generate_audio(self, comment: str) -> Optional[Path]:
        path = self.output_dir / "latest_comment.mp3"
        try:
            if self.enable_audio and self.is_playing_audio():
                return None
            with self.client.audio.speech.with_streaming_response.create(
                model=self.tts_model, voice=self.voice, input=comment
            ) as r:
                r.stream_to_file(path)
            self.play_audio_file(path)
            return path
        except Exception:
            return None

    def is_playing_audio(self) -> bool:
        """Return True while the current audio player process is still running."""
        with self._playback_lock:
            if self._current_player_proc is None:
                return False
            if self._current_player_proc.poll() is None:
                return True
            self._current_player_proc = None
            return False

    def play_audio_file(self, path: Path) -> bool:
        """Best-effort, non-blocking audio playback on Linux."""
        try:
            if not path.exists():
                return False

            mtime = path.stat().st_mtime
            # Avoid replaying the exact same file repeatedly.
            if mtime <= self._last_played_audio_mtime:
                return False

            # Try common Linux audio players in order.
            player_cmds = [
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)],
                ["mpg123", "-q", str(path)],
                ["mpg321", "-q", str(path)],
                ["cvlc", "--play-and-exit", "--quiet", str(path)],
                ["play", "-q", str(path)],  # sox
                ["aplay", str(path)],
            ]

            for cmd in player_cmds:
                if shutil.which(cmd[0]):
                    with self._playback_lock:
                        if self._current_player_proc is not None and self._current_player_proc.poll() is None:
                            return False
                        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        self._current_player_proc = proc
                        self._last_played_audio_mtime = mtime
                        return True

            print("[COMMENTARY] MP3 generated, but no audio player found (ffplay/mpg123/cvlc/play/aplay).")
            return False
        except Exception as e:
            print(f"[COMMENTARY] Audio playback failed: {e}")
            return False

    def process_state(self, state: Dict[str, Any]) -> Optional[str]:
        """Called from main loop with `get_game_state_dict()` result."""
        if state is None:
            return None
        if not self.should_comment(state):
            return None
        comment = self.generate_text_comment(state)
        if not comment:
            return None
        self.save_text_comment(comment)
        if self.enable_audio:
            self.generate_audio(comment)
        return comment

    def process_state_non_blocking(self, state: Dict[str, Any]):
        """Run commentary work in a background thread to avoid blocking frame loop."""
        if state is None:
            return
        # Drop frame commentary request if a previous commentary job is still running.
        if not self._worker_lock.acquire(blocking=False):
            return

        snapshot = dict(state)

        def _job():
            try:
                self.process_state(snapshot)
            finally:
                self._worker_lock.release()

        threading.Thread(target=_job, daemon=True).start()