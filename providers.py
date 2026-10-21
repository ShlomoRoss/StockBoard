"""Market data for the stock board. Everything here is free and keyless.

Quotes:  Yahoo Finance chart endpoint -> CNBC -> Nasdaq.com -> Stooq (first that answers), Finnhub if you add a key.
Charts:  Yahoo (intraday and history) -> Nasdaq.com (intraday) / Stooq (daily history) as backups.
These are unofficial public endpoints; they can change or rate-limit, which is why every step has a backup and the
dashboard shows exactly which source failed and why.
"""
import csv
import io
import logging
import math
import random
import re
import threading
import time
from urllib.parse import quote

import requests

import market

log = logging.getLogger("providers")
_session = requests.Session()
_session.headers["User-Agent"] = "stockboard/1.0"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}


def get_json(url, params=None, headers=None):
    r = _session.get(url, params=params, headers=headers or UA, timeout=10)
    r.raise_for_status()
    return r.json()


# ------------------------------------------------------------------ symbols
ALIASES = {"SPX": "^GSPC", "S&P": "^GSPC", "SP500": "^GSPC", "DJI": "^DJI", "DOW": "^DJI", "IXIC": "^IXIC",
           "COMP": "^IXIC", "NASDAQ": "^IXIC", "NDX": "^NDX", "RUT": "^RUT", "VIX": "^VIX"}
NAMES = {"^GSPC": "SPX", "^DJI": "DOW", "^IXIC": "NAS", "^RUT": "RUT", "^VIX": "VIX", "^NDX": "NDX"}
SYMBOL_RE = re.compile(r"[A-Z0-9^][A-Z0-9.=^-]{0,11}")


def clean_symbol(s):
    """'  aapl ' -> 'AAPL', 'spx' -> '^GSPC'. Returns None if it doesn't look like a ticker."""
    s = str(s or "").strip().upper().lstrip("$")
    s = ALIASES.get(s, s)
    return s if SYMBOL_RE.fullmatch(s) else None


def clean_list(items, limit):
    out = []
    for x in items or []:
        s = clean_symbol(x)
        if s and s not in out:
            out.append(s)
    return out[:limit]


def nice(sym):
    if sym in NAMES:
        return NAMES[sym]
    return sym[:-4] if sym.endswith("-USD") else sym


def is_crypto(sym):
    return sym.endswith("-USD")


# ------------------------------------------------------------------ quotes
_yahoo_block_until = 0.0
_cache = {}


def _num(x):
    return float(str(x).replace(",", "").replace("$", "").replace("%", "").strip())


def quote_yahoo(sym):
    global _yahoo_block_until
    last = None
    for host in ("query1", "query2"):
        try:
            js = get_json(f"https://{host}.finance.yahoo.com/v8/finance/chart/{quote(sym, safe='')}",
                          {"interval": "1d", "range": "1d"})
            meta = js["chart"]["result"][0]["meta"]
            price = float(meta["regularMarketPrice"])
            prev = meta.get("previousClose") or meta.get("chartPreviousClose")
            prev = float(prev) if prev else None
            return {"price": price, "prev": prev, "chg": (price / prev - 1) * 100 if prev else 0.0}
        except requests.HTTPError as e:
            last = e
            if e.response is not None and e.response.status_code == 429:
                continue
            raise
    _yahoo_block_until = time.time() + 300
    log.warning("Yahoo is rate-limiting us (429); backing off for 5 minutes and using the backup sources")
    raise last


_CNBC = {"^GSPC": ".SPX", "^DJI": ".DJI", "^IXIC": ".IXIC", "^RUT": ".RUT", "^VIX": ".VIX", "^NDX": ".NDX"}


def quote_cnbc(sym):
    if is_crypto(sym) or "=" in sym:
        raise ValueError("not covered by CNBC")
    js = get_json("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol",
                  {"symbols": _CNBC.get(sym, sym), "requestMethod": "itv", "noform": 1, "partnerId": 2, "fund": 1,
                   "exthrs": 0, "output": "json", "events": 1})
    q = js["FormattedQuoteResult"]["FormattedQuote"][0]
    price = _num(q["last"])
    prev = q.get("previous_day_closing")
    prev = _num(prev) if prev not in (None, "", "UNCH") else None
    return {"price": price, "prev": prev, "chg": (price / prev - 1) * 100 if prev else _num(q.get("change_pct") or 0)}


def quote_nasdaq(sym):
    if not re.fullmatch(r"[A-Z]{1,5}([.-][A-Z])?", sym):
        raise ValueError("not covered by Nasdaq.com")
    last = None
    for cls in ("stocks", "etf"):
        try:
            js = get_json(f"https://api.nasdaq.com/api/quote/{quote(sym.replace('-', '.'), safe='')}/info",
                          {"assetclass": cls}, dict(UA, Accept="application/json, text/plain, */*"))
            pd_ = js["data"]["primaryData"]
            return {"price": _num(pd_["lastSalePrice"]), "prev": None, "chg": _num(pd_.get("percentageChange") or 0)}
        except Exception as e:
            last = e
    raise last


_STOOQ = {"^GSPC": "^spx", "^DJI": "^dji", "^IXIC": "^ndq"}


def _stooq_sym(sym):
    if sym in _STOOQ:
        return _STOOQ[sym]
    if sym.endswith("-USD"):
        return sym[:-4].lower() + ".v"
    if re.fullmatch(r"[A-Z]{1,5}([.-][A-Z])?", sym):
        return sym.lower().replace("-", ".") + ".us"
    return None


def quote_stooq(sym):
    ss = _stooq_sym(sym)
    if not ss:
        raise ValueError("no mapping")
    r = _session.get("https://stooq.com/q/l/", params={"s": ss, "f": "sd2t2ohlcvp", "h": "", "e": "csv"}, timeout=10)
    r.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(r.text)))
    row = {k.lower(): v for k, v in rows[0].items()} if rows else {}
    if row.get("close") in (None, "", "N/D"):
        raise ValueError("no quote")
    price = float(row["close"])
    base = row.get("prev") or row.get("previous") or row.get("open")
    prev = float(base) if base not in (None, "", "N/D") else None
    return {"price": price, "prev": prev, "chg": (price / prev - 1) * 100 if prev else 0.0}


def quote_finnhub(sym, key):
    js = get_json("https://finnhub.io/api/v1/quote", {"symbol": sym, "token": key})
    price, prev = float(js["c"]), js.get("pc")
    if not price:
        raise ValueError("no price")
    prev = float(prev) if prev else None
    return {"price": price, "prev": prev, "chg": (price / prev - 1) * 100 if prev else 0.0}


def fetch_quote(sym, finnhub_key=""):
    """Try each source; the error lists every source's problem so you can see what is blocked."""
    sources = []
    if time.time() >= _yahoo_block_until:
        sources.append(("yahoo", quote_yahoo))
    sources += [("cnbc", quote_cnbc), ("nasdaq", quote_nasdaq), ("stooq", quote_stooq)]
    if finnhub_key:
        sources.append(("finnhub", lambda s: quote_finnhub(s, finnhub_key)))
    errs = []
    for name, fn in sources:
        try:
            q = fn(sym)
            q.update(sym=nice(sym), raw=sym, ts=time.time(), source=name)
            return q
        except Exception as e:
            errs.append(f"{name}: " + str(e).split(" for url")[0].split("Max retries")[0].strip()[:60])
    raise RuntimeError("; ".join(errs))


# ------------------------------------------------------------------ charts
RANGES = {"1d": ("1d", "5m"), "5d": ("5d", "15m"), "1mo": ("1mo", "1d"), "3mo": ("3mo", "1d"),
          "6mo": ("6mo", "1d"), "1y": ("1y", "1wk")}
RANGE_LABEL = {"1d": "1D", "5d": "5D", "1mo": "1M", "3mo": "3M", "6mo": "6M", "1y": "1Y"}
_STOOQ_DAYS = {"5d": 5, "1mo": 22, "3mo": 66, "6mo": 126, "1y": 252}


def chart_yahoo(sym, rng):
    global _yahoo_block_until
    rg, iv = RANGES[rng]
    last = None
    for host in ("query1", "query2"):
        try:
            js = get_json(f"https://{host}.finance.yahoo.com/v8/finance/chart/{quote(sym, safe='')}",
                          {"interval": iv, "range": rg})
            res = js["chart"]["result"][0]
            meta = res["meta"]
            ts = res.get("timestamp") or []
            cl = (res["indicators"]["quote"][0].get("close")) or []
            pts = [(t, float(c)) for t, c in zip(ts, cl) if c is not None]
            if not pts:
                raise ValueError("no chart points")
            prev = meta.get("chartPreviousClose") if rng == "1d" else pts[0][1]
            prev = meta.get("previousClose") or prev if rng == "1d" else prev
            per = ((meta.get("currentTradingPeriod") or {}).get("regular")) or {}
            return {"t": [p[0] for p in pts], "v": [p[1] for p in pts], "prev": float(prev) if prev else None,
                    "open": per.get("start") if rng == "1d" and not is_crypto(sym) else None,
                    "close": per.get("end") if rng == "1d" and not is_crypto(sym) else None,
                    "price": float(meta["regularMarketPrice"]) if meta.get("regularMarketPrice") else pts[-1][1]}
        except requests.HTTPError as e:
            last = e
            if e.response is not None and e.response.status_code == 429:
                continue
            raise
    _yahoo_block_until = time.time() + 300
    raise last


def chart_nasdaq(sym, rng):
    if rng != "1d" or not re.fullmatch(r"[A-Z]{1,5}([.-][A-Z])?", sym):
        raise ValueError("Nasdaq.com backup only has intraday charts for stocks")
    js = get_json(f"https://api.nasdaq.com/api/quote/{quote(sym.replace('-', '.'), safe='')}/chart",
                  {"assetclass": "stocks"}, dict(UA, Accept="application/json, text/plain, */*"))
    pts = []
    for p in js["data"]["chart"]:
        y = p.get("y")
        if y is None:
            y = _num((p.get("z") or {}).get("value"))
        x = p.get("x")
        pts.append((x / 1000.0 if x else len(pts), float(y)))
    if len(pts) < 2:
        raise ValueError("no chart points")
    return {"t": [p[0] for p in pts], "v": [p[1] for p in pts], "prev": None, "open": None, "close": None,
            "price": pts[-1][1]}


def chart_stooq(sym, rng):
    ss = _stooq_sym(sym)
    if not ss or rng == "1d":
        raise ValueError("Stooq backup only has daily history")
    r = _session.get("https://stooq.com/q/d/l/", params={"s": ss, "i": "d"}, timeout=12)
    r.raise_for_status()
    rows = [x for x in csv.DictReader(io.StringIO(r.text)) if x.get("Close") not in (None, "", "N/D")]
    rows = rows[-_STOOQ_DAYS.get(rng, 22):]
    if rng == "1y":
        rows = rows[::5] + ([rows[-1]] if rows and (len(rows) - 1) % 5 else [])
    if len(rows) < 2:
        raise ValueError("no history")
    v = [float(x["Close"]) for x in rows]
    return {"t": list(range(len(v))), "v": v, "prev": v[0], "open": None, "close": None, "price": v[-1]}


def fetch_chart(sym, rng):
    sources = []
    if time.time() >= _yahoo_block_until:
        sources.append(("yahoo", chart_yahoo))
    sources += [("nasdaq", chart_nasdaq), ("stooq", chart_stooq)]
    errs = []
    for name, fn in sources:
        try:
            c = fn(sym, rng)
            c.update(ts=time.time(), source=name)
            return c
        except Exception as e:
            errs.append(f"{name}: " + str(e).split(" for url")[0].split("Max retries")[0].strip()[:60])
    raise RuntimeError("; ".join(errs))


# ------------------------------------------------------------------ settings helpers
def cfg_lists(cfg, ctl):
    """(favorites, watchlist, indices, ranges) after applying dashboard overrides."""
    s = cfg.get("stocks", {})
    fav = clean_list(ctl.favorites if ctl is not None and ctl.favorites is not None else s.get("favorites"), 12)
    wl = clean_list(ctl.watchlist if ctl is not None and ctl.watchlist is not None else s.get("watchlist"), 60)
    idx = clean_list(s.get("indices", ["^GSPC", "^DJI", "^IXIC"]), 6)
    rngs = [r for r in (ctl.ranges if ctl is not None and ctl.ranges is not None else s.get("chart_ranges", ["1d"]))
            if r in RANGES] or ["1d"]
    return fav, wl, idx, rngs


def ticker_symbols(cfg, ctl):
    """Symbols along the bottom: indices first (if enabled), then favorites, then the rest of the watchlist."""
    fav, wl, idx, _ = cfg_lists(cfg, ctl)
    out = list(idx) if cfg.get("ticker", {}).get("include_indices", True) else []
    for s in fav + wl:
        if s not in out:
            out.append(s)
    return out


# ------------------------------------------------------------------ background loop
def key(sym, rng):
    return f"{sym}|{rng}"


def start_providers(cfg, state, ctl):
    t = threading.Thread(target=_loop, args=(cfg, state, ctl), daemon=True, name="stocks")
    t.start()
    return t


def _loop(cfg, state, ctl):
    ref = cfg.get("refresh", {})
    fin_key = (cfg.get("stocks") or {}).get("finnhub_key") or ""
    due = {}                      # ("q"|"c", sym, rng) -> next time to fetch
    errors = {}                   # sym -> last error text
    while True:
        try:
            fav, wl, idx, rngs = cfg_lists(cfg, ctl)
            mkt = market.status()
            quotes = state.get("quotes", {})
            charts = state.get("charts", {})
            now = time.time()
            wanted = []           # (priority, kind, sym, rng, interval)
            for s in fav:
                for r in rngs:
                    iv = (ref.get("favorites", 30) if r == "1d" else ref.get("history", 900))
                    wanted.append((0, "c", s, r, iv))
            for s in idx + [x for x in wl if x not in fav]:
                wanted.append((1, "q", s, "", ref.get("watchlist", 75)))
            for pr, kind, s, r, iv in sorted(wanted, key=lambda w: w[0]):
                live = mkt["state"] == "open" or is_crypto(s)
                k = (kind, s, r)
                have = (key(s, r) in charts) if kind == "c" else (s in quotes)
                if not live and have:
                    iv = ref.get("closed", 1800)
                if k in due and now < due[k]:
                    continue
                try:
                    if kind == "c":
                        c = fetch_chart(s, r)
                        state.update("charts", lambda d: {**d, key(s, r): c}, {})
                        if r == "1d" or s not in quotes:
                            price, prev = c.get("price"), c.get("prev")
                            if price:
                                q = {"sym": nice(s), "raw": s, "price": price, "prev": prev, "ts": time.time(),
                                     "chg": (price / prev - 1) * 100 if prev else 0.0, "source": c["source"]}
                                state.update("quotes", lambda d: {**d, s: q}, {})
                    else:
                        q = fetch_quote(s, fin_key)
                        state.update("quotes", lambda d: {**d, s: q}, {})
                    errors.pop(s, None)
                    due[k] = time.time() + iv
                except Exception as e:
                    log.warning("%s %s failed: %s", kind, s, e)
                    errors[s] = f"{s}: {str(e)[:220]}"
                    due[k] = time.time() + min(iv, 60)
                    if kind == "c" and s not in state.get("quotes", {}):       # at least get a price for the ticker
                        try:
                            q = fetch_quote(s, fin_key)
                            state.update("quotes", lambda d: {**d, s: q}, {})
                        except Exception as e2:
                            errors[s] = f"{s}: {str(e2)[:220]}"
                time.sleep(0.9)           # space requests out; bursts are what trigger 429s
                break                     # one request per pass so dashboard edits are picked up quickly
            quotes = state.get("quotes", {})
            allsyms = set(idx) | set(fav) | set(wl)
            state.set("stocks_status", {
                "ts": time.time(), "symbols": len(allsyms), "loaded": len([s for s in allsyms if s in quotes]),
                "error": next((errors[s] for s in list(errors) if s in allsyms), ""), "market": mkt["state"],
                "yahoo_blocked": time.time() < _yahoo_block_until})
        except Exception:
            log.exception("stocks loop")
        time.sleep(0.25)


# ------------------------------------------------------------------ demo data (no internet needed)
def demo(state, cfg, ctl=None):
    """Fake but realistic-looking quotes and charts so you can try the board (python3 main.py --sim --demo)."""
    fav, wl, idx, rngs = cfg_lists(cfg, ctl)
    base = {"AAPL": 227.5, "MSFT": 418.2, "NVDA": 141.9, "TSLA": 251.4, "AMZN": 186.7, "GOOGL": 168.3, "META": 563.1,
            "^GSPC": 5842.5, "^DJI": 42210.0, "^IXIC": 18310.0, "BTC-USD": 67210.0, "SPY": 582.4, "QQQ": 497.0,
            "CRWD": 361.4, "AMD": 164.2, "NFLX": 721.9, "DIS": 93.6, "JPM": 213.4, "KO": 68.9, "COST": 905.1}
    quotes, charts = {}, {}
    now = time.time()
    for s in set(idx) | set(fav) | set(wl):
        rnd = random.Random(s)
        p0 = base.get(s) or rnd.uniform(20, 400)
        drift = rnd.uniform(-1.2, 1.4)
        for r in RANGES:
            n = {"1d": 78, "5d": 130, "1mo": 22, "3mo": 66, "6mo": 126, "1y": 52}[r]
            vol = {"1d": 0.0016, "5d": 0.003, "1mo": 0.008, "3mo": 0.011, "6mo": 0.012, "1y": 0.025}[r]
            v, x = [], p0 / (1 + drift / 100) if r == "1d" else p0 * (1 - (0.02 if r in ("5d", "1mo") else 0.07) * drift)
            for i in range(n):
                x *= 1 + rnd.gauss((drift / 100) / n if r == "1d" else 0.0006 * drift, vol)
                v.append(x)
            scale = p0 / v[-1]
            v = [a * scale for a in v]
            prev = (v[0] / (1 + rnd.uniform(-0.004, 0.004))) if r == "1d" else v[0]
            if r == "1d":
                start = now - 6.5 * 3600 + 0 * 3600
                t = [start + i * 300 for i in range(n)]
                c = {"t": t, "v": v, "prev": prev, "open": start, "close": start + 23400, "price": v[-1]}
            else:
                c = {"t": list(range(n)), "v": v, "prev": prev, "open": None, "close": None, "price": v[-1]}
            c.update(ts=now, source="demo")
            charts[key(s, r)] = c
        c1 = charts[key(s, "1d")]
        quotes[s] = {"sym": nice(s), "raw": s, "price": c1["price"], "prev": c1["prev"],
                     "chg": (c1["price"] / c1["prev"] - 1) * 100, "ts": now, "source": "demo"}
    state.set("quotes", quotes)
    state.set("charts", charts)
    state.set("stocks_status", {"ts": now, "symbols": len(quotes), "loaded": len(quotes), "error": "",
                                "market": market.status()["state"], "yahoo_blocked": False})
