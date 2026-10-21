"""Offline tests: python3 test_stockboard.py   (no internet or LED panel needed)"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import yaml
import market, providers, screens
from core import State, Control


def test_symbols():
    assert providers.clean_symbol(" aapl ") == "AAPL"
    assert providers.clean_symbol("spx") == "^GSPC"
    assert providers.clean_symbol("$tsla") == "TSLA"
    assert providers.clean_symbol("bad sym!") is None
    assert providers.clean_list(["aapl", "AAPL", "msft", ""], 5) == ["AAPL", "MSFT"]


def test_quote_fallback(monkeypatch=None):
    calls = []
    def bad(sym): calls.append("y"); raise RuntimeError("429")
    def good(sym): calls.append("c"); return {"price": 10.0, "prev": 8.0, "chg": 25.0}
    orig = (providers.quote_yahoo, providers.quote_cnbc)
    providers.quote_yahoo, providers.quote_cnbc = bad, good
    providers._yahoo_block_until = 0
    try:
        q = providers.fetch_quote("AAPL")
    finally:
        providers.quote_yahoo, providers.quote_cnbc = orig
    assert q["source"] == "cnbc" and q["sym"] == "AAPL" and calls == ["y", "c"]


def test_all_fail_message():
    o = (providers.quote_yahoo, providers.quote_cnbc, providers.quote_nasdaq, providers.quote_stooq)
    def bad(sym): raise RuntimeError("blocked")
    providers.quote_yahoo = providers.quote_cnbc = providers.quote_nasdaq = providers.quote_stooq = bad
    providers._yahoo_block_until = 0
    try:
        try:
            providers.fetch_quote("AAPL"); assert False
        except RuntimeError as e:
            for n in ("yahoo", "cnbc", "nasdaq", "stooq"):
                assert n in str(e)
    finally:
        providers.quote_yahoo, providers.quote_cnbc, providers.quote_nasdaq, providers.quote_stooq = o


def test_yahoo_parse():
    js = {"chart": {"result": [{"meta": {"regularMarketPrice": 110, "chartPreviousClose": 100},
                                "timestamp": [1, 2, 3], "indicators": {"quote": [{"close": [100, None, 110]}]}}]}}
    o = providers.get_json
    providers.get_json = lambda *a, **k: js
    try:
        q = providers.quote_yahoo("AAPL"); c = providers.chart_yahoo("AAPL", "1d")
    finally:
        providers.get_json = o
    assert abs(q["chg"] - 10) < 1e-9 and c["v"] == [100.0, 110.0] and c["prev"] == 100


def test_render_everything():
    cfg = yaml.safe_load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")))
    st, ctl = State(), Control()
    ctx = screens.Ctx(cfg)
    for t in (0, 5, 50):                                   # empty state must not crash
        img, d = ctx.new(); screens.main_area(ctx, d, 24, t, st, cfg, ctl)
    providers.demo(st, cfg, ctl)
    ctl.ranges = ["1d", "5d", "1mo", "3mo", "6mo", "1y"]
    for mode in ("auto", "cards", "overview", "movers", "status", "clock"):
        ctl.mode = mode
        for t in range(0, 200, 3):
            img, d = ctx.new(); screens.main_area(ctx, d, 24, t, st, cfg, ctl)
    segs = screens.build_ticker(st, cfg, ctl)
    assert segs and segs[0][0].strip() == "SPX"


def test_market():
    import datetime as dt
    assert not market.is_trading_day(dt.date(2026, 11, 26))      # Thanksgiving
    assert market.is_trading_day(dt.date(2026, 10, 21))


if __name__ == "__main__":
    n = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); n += 1; print("ok", k)
    print(n, "tests passed")
