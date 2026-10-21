"""US stock-market hours (NYSE / Nasdaq regular session) with holidays and early closes.

The holiday rules are built in, so no internet lookup is needed. They cover the standard NYSE calendar; a rare
one-off closure (a national day of mourning, say) is not known and would show as "open" while no prices move.
"""
import datetime as dt

try:
    from zoneinfo import ZoneInfo
except ImportError:      # pragma: no cover
    ZoneInfo = None

ET = ZoneInfo("America/New_York") if ZoneInfo else None
OPEN, CLOSE, EARLY_CLOSE = dt.time(9, 30), dt.time(16, 0), dt.time(13, 0)
PRE_OPEN, AFTER_CLOSE = dt.time(4, 0), dt.time(20, 0)


def _nth_weekday(year, month, weekday, n):
    d = dt.date(year, month, 1)
    d += dt.timedelta(days=(weekday - d.weekday()) % 7)
    return d + dt.timedelta(weeks=n - 1)


def _last_weekday(year, month, weekday):
    d = dt.date(year + (month == 12), month % 12 + 1, 1) - dt.timedelta(days=1)
    return d - dt.timedelta(days=(d.weekday() - weekday) % 7)


def _easter(year):
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return dt.date(year, month, day + 1)


def _observed(d):
    """A fixed-date holiday: Saturday -> the Friday before is NOT closed for New Year's, but is for the others."""
    if d.weekday() == 5:
        return d - dt.timedelta(days=1)
    if d.weekday() == 6:
        return d + dt.timedelta(days=1)
    return d


def holidays(year):
    """{date: name} of full-day NYSE closures in `year`."""
    h = {}
    ny = dt.date(year, 1, 1)
    if ny.weekday() != 5:                       # Jan 1 on a Saturday: the market is open the Friday before
        h[_observed(ny)] = "New Year's Day"
    h[_nth_weekday(year, 1, 0, 3)] = "Martin Luther King Jr. Day"
    h[_nth_weekday(year, 2, 0, 3)] = "Presidents Day"
    h[_easter(year) - dt.timedelta(days=2)] = "Good Friday"
    h[_last_weekday(year, 5, 0)] = "Memorial Day"
    h[_observed(dt.date(year, 6, 19))] = "Juneteenth"
    h[_observed(dt.date(year, 7, 4))] = "Independence Day"
    h[_nth_weekday(year, 9, 0, 1)] = "Labor Day"
    h[_nth_weekday(year, 11, 3, 4)] = "Thanksgiving"
    h[_observed(dt.date(year, 12, 25))] = "Christmas"
    return h


def early_closes(year):
    """Days the market closes at 1 pm."""
    out = {_nth_weekday(year, 11, 3, 4) + dt.timedelta(days=1): "Day after Thanksgiving"}
    hol = holidays(year)
    for d, name in ((dt.date(year, 7, 3), "Day before Independence Day"), (dt.date(year, 12, 24), "Christmas Eve")):
        if d.weekday() < 5 and d not in hol:
            out[d] = name
    return out


def is_trading_day(d):
    return d.weekday() < 5 and d not in holidays(d.year)


def close_time(d):
    return EARLY_CLOSE if d in early_closes(d.year) else CLOSE


def now_et(now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    return now.astimezone(ET) if ET else now


def status(now=None):
    """{'state': 'open'|'pre'|'after'|'closed', 'label': 'OPEN', 'detail': 'closes 4:00p', 'secs': seconds until the
    next change, 'early': bool}. 'pre'/'after' are the extended-hours windows on a trading day."""
    n = now_et(now)
    today, t = n.date(), n.time()
    if is_trading_day(today):
        close = close_time(today)
        early = close != CLOSE
        if OPEN <= t < close:
            secs = (dt.datetime.combine(today, close, n.tzinfo) - n).total_seconds()
            return {"state": "open", "label": "OPEN", "secs": int(secs), "early": early,
                    "detail": "closes " + _fmt(close)}
        if PRE_OPEN <= t < OPEN:
            secs = (dt.datetime.combine(today, OPEN, n.tzinfo) - n).total_seconds()
            return {"state": "pre", "label": "PRE-MKT", "secs": int(secs), "early": early, "detail": "opens 9:30a"}
        if close <= t < AFTER_CLOSE:
            return {"state": "after", "label": "AFTER-HRS", "secs": 0, "early": early, "detail": "closed " + _fmt(close)}
    nxt = today + dt.timedelta(days=1 if (is_trading_day(today) and t >= OPEN) or not is_trading_day(today) else 0)
    while not is_trading_day(nxt):
        nxt += dt.timedelta(days=1)
    opens = dt.datetime.combine(nxt, OPEN, n.tzinfo)
    return {"state": "closed", "label": "CLOSED", "secs": max(0, int((opens - n).total_seconds())), "early": False,
            "detail": "opens " + (nxt.strftime("%a") if nxt != today else "today") + " 9:30a"}


def _fmt(t):
    return f"{(t.hour % 12) or 12}:{t.minute:02d}{'a' if t.hour < 12 else 'p'}"


def countdown(secs):
    """3725 -> '1h02m'; 540 -> '9m'; 90000 -> '1d1h'."""
    secs = max(0, int(secs))
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d}d{h}h"
    if h:
        return f"{h}h{m:02d}m"
    return f"{m}m"
