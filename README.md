# Stock Ticker LED Board

<img width="1290" height="990" alt="image" src="https://github.com/user-attachments/assets/a524016c-cd12-43ce-a668-251598b35273" />

A desk/wall stock ticker for a Raspberry Pi + Adafruit RGB Matrix Bonnet/HAT driving a 64x32 panel.

- **Main screen:** your favorite stocks, one at a time, each with price, % change and a live chart (green when up for
  the day, red when down, dotted line at the previous close). Between the cards it rotates through a **market
  overview** (S&P 500, Dow, Nasdaq), **top movers** and a **market status** screen (open/closed, countdown to the
  bell, holidays and early closes).
- **Bottom row:** a full scrolling ticker of the indices, your favorites and your whole watchlist, with price and
  green/red change.
- **No web page, nothing exposed on your network:** the board only makes outgoing requests for prices. All settings
  live in `config.yaml` on the Pi.
- Free: no accounts or API keys. Stocks, ETFs, indices and crypto (`BTC-USD`).

> Prices come from free public sources and can be delayed or occasionally wrong. This is a display, not trading
> advice, and not something to trade from.


## 1. Parts

- Raspberry Pi 3B+/4/5 (a Pi Zero 2 W works but is slower)
- Adafruit RGB Matrix Bonnet or HAT, and a 64x32 HUB75 panel (e.g. Adafruit 64x32, 5 mm pitch, product 2277)
- **5 V** power supply for the panel (4 A is plenty for one 64x32 panel; never 12 V on the panel or Bonnet's 5 V input), and a separate power supply for the Pi (or the bonnet can power the Pi, per Adafruit's guide)
- microSD card

## 2. Install

On the Pi (Raspberry Pi OS Lite is fine, with Wi-Fi set up):

```bash
# 1) Display driver (Adafruit's helper installs hzeller's rpi-rgb-led-matrix and the Python bindings)
curl https://raw.githubusercontent.com/adafruit/Raspberry-Pi-Installer-Scripts/main/rgb-matrix.sh > rgb-matrix.sh
sudo bash rgb-matrix.sh
#   choose: Bonnet (or HAT), then "convenience" or "quality" as you like.  If asked about the PWM jumper:
#   answer "no" unless you made the solder mod (then set hardware_mapping: adafruit-hat-pwm in config.yaml).

# 2) This project
unzip stockboard.zip -d ~/          # gives ~/stockboard
cd ~/stockboard
sudo pip3 install -r requirements.txt --break-system-packages
sudo apt install -y fonts-dejavu-core   # the font used for the display

# 3) Try it
sudo python3 main.py
```

If the panel stays dark, check the power and the ribbon cable direction, then see Troubleshooting.

### Start on boot
```bash
sudo cp stockboard.service /etc/systemd/system/
# edit the two /home/pi paths in that file if your username isn't "pi"
sudo systemctl daemon-reload
sudo systemctl enable --now stockboard
journalctl -u stockboard -f        # live log
```

### Try it without a panel (or before the Pi arrives; works on any computer with Python and Pillow)
```bash
python3 main.py --demo --snapshot out.png --mode cards      # save a picture of one screen
python3 main.py --demo --snapshot out.png --at 40           # the screen 40 s into the rotation
python3 main.py --diagnose                           # test which data sources work on your network
python3 test_stockboard.py                           # offline self-test
```


## 3. Choose your stocks

Edit `config.yaml` on the Pi (`nano ~/stockboard/config.yaml`), then restart: `sudo systemctl restart stockboard`.

```yaml
stocks:
  favorites: [AAPL, NVDA, TSLA, MSFT]    # cards with charts (up to 12)
  watchlist: [AMZN, GOOGL, META, SPY, QQQ, BTC-USD]   # ticker only (up to 60)
  indices: ["^GSPC", "^DJI", "^IXIC"]
  chart_ranges: ["1d"]                    # 1d 5d 1mo 3mo 6mo 1y; e.g. ["1d", "1mo"] shows two charts per favorite
```

Symbol cheat-sheet: normal tickers (`AAPL`, `BRK-B`), ETFs (`SPY`), crypto (`BTC-USD`, `ETH-USD`), indices
(`^GSPC` or `SPX`, `^DJI` or `DOW`, `^IXIC` or `NASDAQ`, `^VIX`). A symbol that doesn't exist just stays out of the ticker.

### How long each screen shows
`rotation:` in `config.yaml`: `card_seconds` (default 6) per stock card and `other_seconds` (default 4) for the
extra screens. With 4 favorites and 1 chart range, one full loop is about 24 s of cards plus 12 s of extras.
Choose which extra screens appear with `rotation: screens:` (any of `overview`, `movers`, `status`; leave `[]` for cards only).

### Night mode
Dims the board between 22:00 and 07:00 by default (`night:` in `config.yaml`; `enabled: false` turns it off). Set
`favorites_only: true` to scroll just your favorites at night.


## 4. Where the data comes from

All free and keyless; every step has backups so one blocked site doesn't blank the board:

| What | Tried in this order |
|---|---|
| Quotes | Yahoo Finance, CNBC, Nasdaq.com, Stooq, (Finnhub if you add a key) |
| Intraday chart (1D) | Yahoo Finance, then Nasdaq.com (stocks only) |
| Longer charts (5D-1Y) | Yahoo Finance, then Stooq (daily data) |

These are unofficial public endpoints; they can change or rate-limit. The board spaces requests out (about one per
second), backs off for five minutes if Yahoo says "too many requests", and refreshes slower when the market is closed
(`refresh:` in `config.yaml`). `python3 main.py --diagnose` shows which sources work, and `journalctl -u stockboard -f` shows errors as they happen. For a sturdier setup add a
free key from finnhub.io as `finnhub_key:` (used as one more backup for quotes).

**Update rates:** favorites every 30 s and the ticker every 75 s while the market is open; everything every 30 min
when closed (crypto keeps updating). Keep the whole list under about 40 symbols; more symbols means each one
refreshes less often.

**Market hours** are the NYSE calendar (9:30a-4:00p Eastern, weekends, holidays and 1:00p early closes built in).


## 5. What each screen shows (64x32 panel)

```
+----------------------------------------------------------------+
| AAPL                                               1D           |   Stock card (24 px tall)
| 227.50     chart: line + fill, dotted prev-close line            |
| -0.52%                                                           |
|-----------------------------------------------------------------|
| AAPL 227.50 -0.52%   MSFT 418.20 +1.08%   SPX 5842 ... ->      |   Ticker (8 px)
+----------------------------------------------------------------+
```
Other screens: **Markets** (SPX / DOW / NAS price and % change), **Top movers** (biggest gainer and loser among your
symbols), **Market status** (OPEN / PRE-MKT / AFTER-HRS / CLOSED, time in New York and countdown), **Clock**.
Other panel sizes work (set `width`, `height`, `chain_length` in `config.yaml`), but the layouts are tuned for 64x32.


## 6. Security
There is no web page, login or open port, so nothing on your network can reach or control the board. It only makes
outgoing connections to fetch prices. (To change anything, SSH into the Pi and edit `config.yaml`.)


## 7. Troubleshooting

| Problem | Try |
|---|---|
| Panel dark | Check 5 V supply on the panel, ribbon cable orientation, run with `sudo`. |
| Flicker / glitches | `gpio_slowdown: 3` or `4` (Pi 4/5); `limit_refresh_rate_hz: 120`; if you didn't do the PWM solder mod keep `hardware_mapping: adafruit-hat` and try `disable_hardware_pulsing: true`. |
| Wrong colors | `extra: {led_rgb_sequence: BGR}` (or RBG/GRB). |
| Pi 5 | Use the current rpi-rgb-led-matrix and set `extra: {rp1_pio: 1}` if needed. |
| Board says NO DATA or LOADING | Run `python3 main.py --diagnose` to see which sources your network blocks; check `journalctl -u stockboard`. A symbol that doesn't exist (typo) just stays out of the ticker. |
| "Yahoo is rate-limiting" | Normal now and then; backup sources take over. Lengthen `refresh:` times or shorten the list. |
| After editing config.yaml | `sudo systemctl restart stockboard` |

## 8. Files
`main.py` (starts everything), `providers.py` (market data), `screens.py` (drawing), `market.py` (NYSE hours),
`core.py` (shared state), `config.yaml`,
`stockboard.service`, `test_stockboard.py`.
