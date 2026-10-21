#!/usr/bin/env python3
"""Stock ticker LED board for Raspberry Pi + Adafruit RGB matrix: your favorite stocks with live charts on the main
screen and a full scrolling ticker of your watchlist along the bottom.

    sudo python3 main.py                  # run on the Pi
        python3 main.py --demo --snapshot out.png --mode cards     # save one frame and exit
    python3 main.py --diagnose            # test every data source from this machine
"""
import argparse
import datetime as dt
import logging
import os
import sys
import time

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import providers  # noqa: E402
import screens  # noqa: E402
from core import Control, Frame, State  # noqa: E402

log = logging.getLogger("main")


def make_matrix(cfg):
    from rgbmatrix import RGBMatrix, RGBMatrixOptions
    d = cfg["display"]
    o = RGBMatrixOptions()
    o.rows = d["height"]
    o.cols = d["width"]
    o.chain_length = d["chain_length"]
    o.parallel = d["parallel"]
    o.hardware_mapping = d["hardware_mapping"]
    o.gpio_slowdown = d["gpio_slowdown"]
    o.brightness = d["brightness"]
    o.drop_privileges = False
    for k, v in (d.get("extra") or {}).items():
        try:
            setattr(o, k, v)
        except Exception as e:
            log.warning("ignoring display.extra.%s: %s", k, e)
    return RGBMatrix(options=o)


def diagnose(cfg):
    """Try every quote/chart source for a few symbols so you can see exactly what this network can reach."""
    import providers as p
    print("Testing market data sources from this machine...\n")
    for sym in ("AAPL", "^GSPC"):
        for name, fn in (("yahoo", p.quote_yahoo), ("cnbc", p.quote_cnbc), ("nasdaq", p.quote_nasdaq),
                         ("stooq", p.quote_stooq)):
            try:
                q = fn(sym)
                print(f"  quote  {name:7s} {sym:6s} OK   {q['price']:.2f} ({q['chg']:+.2f}%)")
            except Exception as e:
                print(f"  quote  {name:7s} {sym:6s} FAIL {str(e).split(' for url')[0][:70]}")
        for name, fn in (("yahoo", p.chart_yahoo), ("nasdaq", p.chart_nasdaq), ("stooq", p.chart_stooq)):
            rng = "1d" if name != "stooq" else "1mo"
            try:
                c = fn(sym, rng)
                print(f"  chart  {name:7s} {sym:6s} OK   {len(c['v'])} points ({rng})")
            except Exception as e:
                print(f"  chart  {name:7s} {sym:6s} FAIL {str(e).split(' for url')[0][:70]}")
    print("\nOnly one working quote source and one chart source are needed. The board tries them in order.")


class App:
    def __init__(self, cfg, state, ctl):
        self.cfg, self.state, self.ctl = cfg, state, ctl
        self.ctx = screens.Ctx(cfg)

    @staticmethod
    def _hhmm(s, default):
        try:
            return dt.datetime.strptime(str(s), "%H:%M").time()
        except (TypeError, ValueError):
            return dt.datetime.strptime(default, "%H:%M").time()

    def is_night(self, now=None):
        mode, n = self.ctl.night_mode, self.cfg.get("night", {})
        if mode == "on":
            return True
        if mode == "off" or not n.get("enabled", True):
            return False
        start = self._hhmm(self.ctl.night_start or n.get("start"), "22:00")
        end = self._hhmm(self.ctl.night_end or n.get("end"), "07:00")
        cur = (now or dt.datetime.now()).time()
        return (cur >= start or cur < end) if start > end else (start <= cur < end)

    def night_brightness(self):
        return self.ctl.night_brightness or self.cfg.get("night", {}).get("brightness", 8)

    def brightness(self):
        if self.is_night():
            return max(1, int(self.night_brightness()))
        return self.ctl.brightness or self.cfg["display"]["brightness"]

    def render(self, t):
        ctx, ctl, cfg = self.ctx, self.ctl, self.cfg
        if ctl.mode == "off":
            return ctx.new()[0]
        m = ctl.active_message()
        if m:
            return screens.message(ctx, m, t)
        img, d = ctx.new()
        segs = screens.build_ticker(self.state, cfg, ctl, night=self.is_night())
        area_h = ctx.H - ctx.rh
        screens.main_area(ctx, d, area_h, t, self.state, cfg, ctl)
        d.line((0, area_h, ctx.W, area_h), fill=(25, 25, 25))
        speed = ctl.ticker_speed or cfg.get("ticker", {}).get("speed", 24)
        screens.ticker(ctx, d, ctx.H - ctx.rh, segs, t, speed)
        return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(HERE, "config.yaml"))
    ap.add_argument("--sim", action="store_true", help="no LED hardware (use with --snapshot)")
    ap.add_argument("--demo", action="store_true", help="use fake quotes and charts (no internet needed)")
    ap.add_argument("--snapshot", help="render one frame to this PNG and exit")
    ap.add_argument("--mode", help="force a screen (auto, cards, overview, movers, status, clock, off)")
    ap.add_argument("--at", type=float, default=0, help="with --snapshot: time offset in seconds into the rotation")
    ap.add_argument("--diagnose", action="store_true", help="test the market data sources and exit")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    with open(args.config) as f:
        cfg = yaml.safe_load(f)
    if args.diagnose:
        return diagnose(cfg)

    state, frame = State(), Frame()
    ctl = Control(None)      # no web page: everything comes from config.yaml
    if args.mode:
        ctl.mode = args.mode
    app = App(cfg, state, ctl)

    if args.demo:
        providers.demo(state, cfg, ctl)
    elif not args.snapshot:
        providers.start_providers(cfg, state, ctl)

    if args.snapshot:
        img = app.render(args.at)
        img.resize((img.width * 10, img.height * 10), 0).save(args.snapshot)
        print("saved", args.snapshot)
        return

    if args.sim:
        log.error("--sim needs --snapshot (there is no web preview any more)")
        return
    try:
        matrix = make_matrix(cfg)
        canvas = matrix.CreateFrameCanvas()
    except Exception as e:
        log.error("LED matrix unavailable (%s). Run with sudo on the Pi, or use --snapshot to test without a panel.", e)
        return

    period = 1.0 / cfg["display"]["fps"]
    while True:
        t0 = time.time()
        try:
            img = app.render(t0)
        except Exception:
            log.exception("render failed")
            img = app.ctx.new()[0]
        frame.img = img
        if matrix:
            b = app.brightness()
            if matrix.brightness != b:
                matrix.brightness = b
            canvas.SetImage(img)
            canvas = matrix.SwapOnVSync(canvas)
        time.sleep(max(0, period - (time.time() - t0)))


if __name__ == "__main__":
    main()
