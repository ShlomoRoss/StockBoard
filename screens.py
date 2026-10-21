"""All drawing code for the stock board (64x32 panel, 8px font): the rotating main area (stock cards with charts,
market overview, top movers, market status) and the full-width scrolling ticker along the bottom row."""
import datetime as dt

from PIL import Image, ImageDraw, ImageFont

import market
import providers

WHITE = (255, 255, 255)
GREEN = (0, 210, 80)
RED = (255, 50, 50)
YELLOW = (255, 210, 0)
GRAY = (110, 110, 110)
CYAN = (0, 200, 255)
ORANGE = (255, 100, 0)
BLUE = (40, 110, 255)
COLORS = {"white": WHITE, "green": GREEN, "red": RED, "yellow": YELLOW, "gray": GRAY, "cyan": CYAN,
          "orange": ORANGE, "blue": BLUE}


def dim(c, f):
    return tuple(int(x * f) for x in c)


def load_font(path, size):
    for p in (path, "DejaVuSansMono-Bold.ttf", "DejaVuSansMono.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()


class Ctx:
    def __init__(self, cfg):
        d = cfg["display"]
        self.cfg = cfg
        self.W = d["width"] * d["chain_length"]
        self.H = d["height"] * d["parallel"]
        self.font = load_font(d["font"], d["font_size"])
        self.rh = d["font_size"]
        self.big = load_font(d["font"], d.get("big_font_size", 16))
        self.bigh = d.get("big_font_size", 16)

    def new(self):
        img = Image.new("RGB", (self.W, self.H), (0, 0, 0))
        d = ImageDraw.Draw(img)
        d.fontmode = "1"
        return img, d

    PCT = ("##..#", "##.#.", "..#..", ".#.##", "#..##")      # the font's own % is a smudge at 8px; draw our own

    def tw(self, d, s):
        parts = s.split("%")
        return sum(int(d.textlength(p, font=self.font)) for p in parts) + 6 * (len(parts) - 1)

    def text(self, d, x, y, s, fill=WHITE, align="l"):
        if align == "r":
            x -= self.tw(d, s)
        elif align == "c":
            x -= self.tw(d, s) // 2
        parts = s.split("%")
        for i, p in enumerate(parts):
            if p:
                d.text((x, y), p, font=self.font, fill=fill)
                x += int(d.textlength(p, font=self.font))
            if i < len(parts) - 1:
                for r, row in enumerate(self.PCT):
                    for c, ch in enumerate(row):
                        if ch == "#":
                            d.point((x + c, y + 2 + r), fill=fill)
                x += 6


# ------------------------------------------------------------------ formatting
def fmt_price(p):
    if p is None:
        return "--"
    if p >= 1000:
        return f"{p:.0f}"
    if p >= 1:
        return f"{p:.2f}"
    return f"{p:.4f}"


def fmt_pct(c, decimals=2, sign=True):
    if c is None:
        return "--"
    a = abs(c)
    if a >= 100:
        s = f"{a:.0f}"
    elif a >= 10:
        s = f"{a:.1f}" if decimals else f"{a:.0f}"
    else:
        s = f"{a:.{decimals}f}"
    return ("+" if c >= 0 else "-") + s if sign else s


def chg_color(c):
    return GREEN if (c or 0) >= 0 else RED


# ------------------------------------------------------------------ chart
def sparkline(d, box, c, color):
    """Line chart with a dim fill, dotted previous-close baseline and a bright last point."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0 + 1, y1 - y0 + 1
    vals, ts = c["v"], c["t"]
    if len(vals) < 2:
        return
    prev = c.get("prev")
    lo, hi = min(vals), max(vals)
    if prev:
        lo, hi = min(lo, prev), max(hi, prev)
    if hi - lo < 1e-9:
        hi, lo = hi + 1, lo - 1
    pad = (hi - lo) * 0.06
    lo, hi = lo - pad, hi + pad
    yf = lambda v: y1 - (v - lo) / (hi - lo) * (h - 1)
    op, cl = c.get("open"), c.get("close")
    if op and cl and cl > op:
        xs = [x0 + min(1.0, max(0.0, (t - op) / (cl - op))) * (w - 1) for t in ts]
    else:
        xs = [x0 + i / (len(vals) - 1) * (w - 1) for i in range(len(vals))]
    if prev:
        by = int(round(yf(prev)))
        for x in range(x0, x1 + 1, 2):
            d.point((x, by), fill=(70, 70, 70))
    area, ycol = dim(color, 0.22), {}
    j = 0
    for px in range(int(round(xs[0])), int(round(xs[-1])) + 1):
        while j < len(xs) - 2 and xs[j + 1] < px:
            j += 1
        xa, xb = xs[j], xs[j + 1]
        f = 0 if xb == xa else min(1.0, max(0.0, (px - xa) / (xb - xa)))
        ycol[px] = yf(vals[j] + (vals[j + 1] - vals[j]) * f)
    for px, yy in ycol.items():
        yi = int(round(yy))
        if yi + 1 <= y1:
            d.line((px, yi + 1, px, y1), fill=area)
    pts = [(px, int(round(yy))) for px, yy in sorted(ycol.items())]
    d.line(pts, fill=color) if len(pts) > 1 else None
    d.point(pts[-1], fill=WHITE)


# ------------------------------------------------------------------ main-area screens
def header_row(ctx, d, left, left_color=GRAY, right=None, right_color=GRAY):
    ctx.text(d, 1, 0, left, left_color)
    if right:
        ctx.text(d, ctx.W - 1, 0, right, right_color, "r")


def card(ctx, d, area_h, state, sym, rng):
    """One favorite: symbol/price/change on the left, chart on the right."""
    q = (state.get("quotes") or {}).get(sym)
    c = (state.get("charts") or {}).get(providers.key(sym, rng))
    rh = ctx.rh
    name = providers.nice(sym)[:5]
    if not q:
        ctx.text(d, 1, 0, name, WHITE)
        ctx.text(d, 1, rh, "loading", GRAY)
        return
    col = chg_color(q["chg"])
    ctx.text(d, 1, 0, name, CYAN)
    ctx.text(d, 1, rh, fmt_price(q["price"]), WHITE)
    ctx.text(d, 1, rh * 2, fmt_pct(q["chg"]) + "%" if abs(q["chg"]) < 100 else fmt_pct(q["chg"]), col)
    ctx.text(d, ctx.W - 2, 0, providers.RANGE_LABEL.get(rng, rng.upper()), GRAY, "r")
    box = (ctx.W - 31, rh + 1, ctx.W - 1, area_h - 2)
    if c and len(c["v"]) > 1:
        up = (c["v"][-1] >= (c.get("prev") or c["v"][0]))
        sparkline(d, box, c, GREEN if up else RED)
    else:
        ctx.text(d, box[0] + 15, rh + 6, "no chart", GRAY, "c")


def overview(ctx, d, area_h, state, cfg, ctl):
    rh = ctx.rh
    _, _, idx, _ = providers.cfg_lists(cfg, ctl)
    quotes = state.get("quotes") or {}
    rows = [s for s in idx if s in quotes][:3]
    if not rows:
        ctx.text(d, 1, 0, "MARKETS", GRAY)
        ctx.text(d, 1, rh, "loading", GRAY)
        return
    for i, s in enumerate(rows):
        q = quotes[s]
        y = rh * i
        ctx.text(d, 1, y, providers.nice(s)[:3], CYAN)
        ctx.text(d, 43, y, fmt_price(q["price"]), WHITE, "r")
        ctx.text(d, ctx.W - 1, y, fmt_pct(q["chg"], 1), chg_color(q["chg"]), "r")


def movers(ctx, d, area_h, state, cfg, ctl):
    rh = ctx.rh
    fav, wl, _, _ = providers.cfg_lists(cfg, ctl)
    quotes = state.get("quotes") or {}
    have = [quotes[s] for s in dict.fromkeys(fav + wl) if s in quotes and quotes[s].get("chg") is not None]
    if len(have) < 2:
        ctx.text(d, 1, 0, "MOVERS", GRAY)
        ctx.text(d, 1, rh, "need 2+", GRAY)
        return
    have.sort(key=lambda q: q["chg"], reverse=True)
    ctx.text(d, 1, 0, "TOP MOVERS", GRAY)
    for i, q in enumerate((have[0], have[-1])):
        y = rh * (i + 1)
        ctx.text(d, 1, y, q["sym"][:5], WHITE)
        ctx.text(d, ctx.W - 1, y, fmt_pct(q["chg"]) + ("%" if abs(q["chg"]) < 100 else ""), chg_color(q["chg"]), "r")


def status(ctx, d, area_h, state, cfg, ctl):
    rh = ctx.rh
    m = market.status()
    col = {"open": GREEN, "pre": YELLOW, "after": YELLOW}.get(m["state"], RED)
    et = market.now_et().strftime("%-I:%M%p").lower()[:-1]
    ctx.text(d, 1, 0, "NYSE", GRAY)
    ctx.text(d, ctx.W - 1, 0, et + "ET", CYAN, "r")
    ctx.text(d, ctx.W // 2, rh, m["label"], col, "c")
    det = m["detail"]
    if m["secs"] and m["state"] in ("open", "pre", "closed"):
        det = ("closes " if m["state"] == "open" else "opens ") + market.countdown(m["secs"])
    ctx.text(d, ctx.W // 2, rh * 2, det[:12], WHITE, "c")


def clock(ctx, d, area_h):
    now = dt.datetime.now()
    h24 = ctx.cfg.get("clock", {}).get("hour24", False)
    tm = now.strftime("%H:%M" if h24 else "%-I:%M")
    ampm = "" if h24 else now.strftime("%p")
    tw = int(d.textlength(tm, font=ctx.big))
    sw = (ctx.tw(d, ampm) + 1) if ampm else 0
    top = max(0, (area_h - ctx.rh - ctx.bigh) // 2)
    ctx.text(d, ctx.W // 2, top, now.strftime("%a %b %-d").upper(), CYAN, "c")
    x = max(0, (ctx.W - tw - sw) // 2)
    d.text((x, top + ctx.rh - 1), tm, font=ctx.big, fill=WHITE)
    if ampm:
        ctx.text(d, x + tw + 1, top + ctx.rh + ctx.bigh - ctx.rh - 1, ampm, GRAY)


def no_data(ctx, d, area_h, state):
    st = state.get("stocks_status") or {}
    ctx.text(d, ctx.W // 2, 0, "STOCKS", CYAN, "c")
    if st.get("error"):
        ctx.text(d, ctx.W // 2, ctx.rh, "NO DATA", RED, "c")
        ctx.text(d, ctx.W // 2, ctx.rh * 2, "check page", GRAY, "c")
    else:
        ctx.text(d, ctx.W // 2, ctx.rh, "loading...", WHITE, "c")


# ------------------------------------------------------------------ rotation
SCREEN_NAMES = ("cards", "overview", "movers", "status")


def slots(cfg, ctl, state):
    """[(kind, sym, range, seconds)] for the whole rotation."""
    fav, _, _, rngs = providers.cfg_lists(cfg, ctl)
    rot = cfg.get("rotation", {})
    cs, os_ = float(rot.get("card_seconds", 6)), float(rot.get("other_seconds", 4))
    scr = ctl.screens if ctl.screens is not None else rot.get("screens", ["overview", "movers", "status"])
    out = []
    quotes = state.get("quotes") or {}
    for s in fav:
        if s in quotes or not quotes:
            for r in rngs:
                out.append(("card", s, r, cs))
    # extras after each batch of cards
    for k in scr:
        if k in ("overview", "movers", "status"):
            out.append((k, None, None, os_))
    return out


def main_area(ctx, d, area_h, t, state, cfg, ctl):
    mode = ctl.mode
    quotes = state.get("quotes") or {}
    if mode == "clock":
        return clock(ctx, d, area_h)
    if mode in ("overview", "movers", "status"):
        kind, sym, rng = mode, None, None
    elif mode == "cards" and not providers.cfg_lists(cfg, ctl)[0]:
        return no_data(ctx, d, area_h, state)
    else:
        sl = slots(cfg, ctl, state)
        if mode == "cards":
            sl = [x for x in sl if x[0] == "card"]
        if not sl:
            return no_data(ctx, d, area_h, state) if not quotes else clock(ctx, d, area_h)
        total = sum(x[3] for x in sl)
        pos = t % total
        for kind, sym, rng, secs in sl:
            if pos < secs:
                break
            pos -= secs
    if not quotes:
        return no_data(ctx, d, area_h, state)
    if kind == "card":
        card(ctx, d, area_h, state, sym, rng)
    elif kind == "overview":
        overview(ctx, d, area_h, state, cfg, ctl)
    elif kind == "movers":
        movers(ctx, d, area_h, state, cfg, ctl)
    else:
        status(ctx, d, area_h, state, cfg, ctl)


# ------------------------------------------------------------------ ticker
def build_ticker(state, cfg, ctl, night=False):
    quotes = state.get("quotes") or {}
    syms = providers.ticker_symbols(cfg, ctl)
    if night and cfg.get("night", {}).get("favorites_only", False):
        syms = providers.cfg_lists(cfg, ctl)[0]
    segs = []
    for s in syms:
        q = quotes.get(s)
        if not q:
            continue
        col = chg_color(q["chg"])
        arrow = "+" if q["chg"] >= 0 else "-"
        segs += [(q["sym"] + " ", CYAN), (fmt_price(q["price"]) + " ", WHITE),
                 (f"{arrow}{abs(q['chg']):.2f}%", col), ("   ", WHITE)]
    return segs


def ticker(ctx, d, y, segs, t, speed=24):
    full = sum(ctx.tw(d, s) for s, _ in segs)
    if not segs:
        ctx.text(d, ctx.W // 2, y, "LOADING...", GRAY, "c")
        return
    x = ctx.W - int(t * speed) % (full + ctx.W)
    for s, c in segs:
        if x < ctx.W and x + ctx.tw(d, s) > 0:
            ctx.text(d, x, y, s, c)
        x += ctx.tw(d, s)


def message(ctx, m, t):
    img, d = ctx.new()
    col = COLORS.get(m.get("color", "yellow"), YELLOW)
    s = m["text"]
    w = ctx.tw(d, s)
    y = (ctx.H - ctx.rh) // 2
    if w <= ctx.W:
        ctx.text(d, ctx.W // 2, y, s, col, "c")
    else:
        ctx.text(d, ctx.W - int(t * 30) % (w + ctx.W), y, s, col)
    return img
