"""Shared state: data written by the providers, settings changed from the dashboard."""
import json
import threading
import time


class State:
    """Thread-safe key/value store the data providers write into."""

    def __init__(self):
        self._lock = threading.Lock()
        self._d = {}

    def set(self, key, value):
        with self._lock:
            self._d[key] = value

    def get(self, key, default=None):
        with self._lock:
            return self._d.get(key, default)

    def update(self, key, fn, default=None):
        """Atomically replace state[key] with fn(old)."""
        with self._lock:
            self._d[key] = fn(self._d.get(key, default))


class Control:
    """Settings changed from the dashboard (saved to control.json so they survive restarts).
    None means "use whatever config.yaml says"."""

    _KEYS = ("mode", "brightness", "night_mode", "night_brightness", "night_start", "night_end",
             "favorites", "watchlist", "ranges", "screens", "ticker_speed")

    def __init__(self, path=None):
        self.path = path
        self.mode = "auto"            # auto | cards | overview | movers | status | clock | off
        self.brightness = None
        self.night_mode = "auto"      # auto (follow schedule) | on | off
        self.night_brightness = None
        self.night_start = None
        self.night_end = None
        self.favorites = None         # list of symbols with a card + chart; None -> config.yaml
        self.watchlist = None         # list of symbols in the bottom ticker; None -> config.yaml
        self.ranges = None            # chart ranges to cycle, e.g. ["1d", "1mo"]
        self.screens = None           # which extra screens are in the rotation
        self.ticker_speed = None
        self.message = None           # {"text", "until", "color"}
        if path:
            self._load()

    def _load(self):
        try:
            with open(self.path) as f:
                d = json.load(f)
            for k in self._KEYS:
                if k in d:
                    setattr(self, k, d[k])
        except Exception:
            pass

    def save(self):
        if not self.path:
            return
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump({k: getattr(self, k) for k in self._KEYS}, f)
            import os
            os.replace(tmp, self.path)
        except Exception:
            pass

    def set_message(self, text, seconds=30, color="yellow"):
        self.message = {"text": text, "until": time.time() + seconds, "color": color}

    def clear_message(self):
        self.message = None

    def active_message(self):
        m = self.message
        return m if m and m["until"] > time.time() else None


class Frame:
    """Holds the most recent rendered frame so the dashboard can preview it."""

    def __init__(self):
        self.img = None
