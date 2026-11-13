
import os
import time
import threading
import requests

from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# =====================================
# BINANCE CONFIGURATION
# =====================================

BASE = os.getenv(
    "BINANCE_BASE_URL",
    "https://data-api.binance.vision"
)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "UniversalCryptoReversalScanner/2.0"
})

app = FastAPI(title="Universal Crypto Reversal Scanner V2")

app.mount(
    "/static",
    StaticFiles(directory="static"),
    name="static"
)

universe = {"at": 0, "symbols": []}
lock = threading.Lock()


# =====================================
# BINANCE API
# =====================================

def api_get(path, params=None):
    response = SESSION.get(
        BASE + path,
        params=params,
        timeout=20
    )
    response.raise_for_status()
    return response.json()


def get_symbols():
    now = time.time()

    with lock:
        if universe["symbols"] and now - universe["at"] < 1800:
            return universe["symbols"]

    info = api_get("/api/v3/exchangeInfo")

    symbols = []

    for item in info.get("symbols", []):
        name = item.get("symbol", "")

        if (
            item.get("status") == "TRADING"
            and item.get("quoteAsset") == "USDT"
            and item.get("isSpotTradingAllowed", True)
        ):
            symbols.append(name)

    symbols = sorted(set(symbols))

    with lock:
        universe["at"] = now
        universe["symbols"] = symbols

    return symbols


# =====================================
# TECHNICAL INDICATORS
# =====================================

def ema(values, period):
    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)
    result = sum(values[:period]) / period

    for price in values[period:]:
        result = (
            price * multiplier
            + result * (1 - multiplier)
        )

    return result


def rsi(values, period=14):
    if len(values) < period + 2:
        return None, None

    changes = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ]

    gains = [max(x, 0) for x in changes]
    losses = [max(-x, 0) for x in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    output = []

    for i in range(period, len(changes)):
        avg_gain = (
            avg_gain * (period - 1) + gains[i]
        ) / period

        avg_loss = (
            avg_loss * (period - 1) + losses[i]
        ) / period

        if avg_loss == 0:
            value = 100
        else:
            rs = avg_gain / avg_loss
            value = 100 - (100 / (1 + rs))

        output.append(value)

    if len(output) < 2:
        return None, None

    return output[-1], output[-2]


# =====================================
# REVERSAL ANALYSIS
# =====================================

def analyze(symbol, interval):

    candles = api_get(
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": 100
        }
    )

    # Ignore currently forming candle
    candles = candles[:-1]

    if len(candles) < 55:
        return None

    closes = [float(c[4]) for c in candles]
    opens = [float(c[1]) for c in candles]
    highs = [float(c[2]) for c in candles]
    lows = [float(c[3]) for c in candles]

    price = closes[-1]

    current_rsi, previous_rsi = rsi(closes)

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)

    previous_ema20 = ema(closes[:-1], 20)
    previous_ema50 = ema(closes[:-1], 50)

    old_ema20 = ema(closes[:-2], 20)

    if None in (
        current_rsi,
        previous_rsi,
        ema20,
        ema50,
        previous_ema20,
        previous_ema50,
        old_ema20
    ):
        return None

    # Support and resistance from previous 30 candles
    support = min(lows[-31:-1])
    resistance = max(highs[-31:-1])

    # Current candle information
    candle_open = opens[-1]
    candle_close = closes[-1]
    candle_high = highs[-1]
    candle_low = lows[-1]

    candle_range = max(
        candle_high - candle_low,
        1e-12
    )

    bullish_candle = candle_close > candle_open
    bearish_candle = candle_close < candle_open

    bullish_rejection = (
        bullish_candle
        and (candle_close - candle_low) / candle_range >= 0.65
    )

    bearish_rejection = (
        bearish_candle
        and (candle_high - candle_close) / candle_range >= 0.65
    )

    near_support = price <= support * 1.025
    near_resistance = price >= resistance * 0.975

    # EMA direction
    ema_rising = ema20 > old_ema20
    ema_falling = ema20 < old_ema20

    ema_bull_cross = (
        previous_ema20 <= previous_ema50
        and ema20 > ema50
    )

    ema_bear_cross = (
        previous_ema20 >= previous_ema50
        and ema20 < ema50
    )

    # RSI reversal
    rsi_turn_up = (
        previous_rsi < 35
        and current_rsi >= 35
    )

    rsi_turn_down = (
        previous_rsi > 65
        and current_rsi <= 65
    )

    rsi_bullish = current_rsi > 50
    rsi_bearish = current_rsi < 50

    # =================================
    # EARLY BUY / SELL
    # =================================

    early_buy_score = sum([
        rsi_turn_up or (
            current_rsi < 40
            and current_rsi > previous_rsi
        ),
        ema_rising and price > ema20,
        near_support or bullish_rejection
    ])

    early_sell_score = sum([
        rsi_turn_down or (
            current_rsi > 60
            and current_rsi < previous_rsi
        ),
        ema_falling and price < ema20,
        near_resistance or bearish_rejection
    ])

    if early_buy_score >= 2 and early_buy_score > early_sell_score:
        early_signal = "EARLY BUY"

    elif early_sell_score >= 2 and early_sell_score > early_buy_score:
        early_signal = "EARLY SELL"

    else:
        early_signal = "WAIT"

    # =================================
    # CONFIRMED BUY / SELL
    # =================================

    confirmed_buy = (
        ema_bull_cross
        and rsi_bullish
        and (bullish_rejection or near_support)
    )

    confirmed_sell = (
        ema_bear_cross
        and rsi_bearish
        and (bearish_rejection or near_resistance)
    )

    if confirmed_buy:
        confirmed_signal = "CONFIRMED BUY"

    elif confirmed_sell:
        confirmed_signal = "CONFIRMED SELL"

    else:
        confirmed_signal = "WAIT"

    # Backward compatible signal
    if confirmed_signal != "WAIT":
        signal = confirmed_signal
    elif early_signal != "WAIT":
        signal = early_signal
    else:
        signal = "WAIT"

    return {
        "symbol": symbol,
        "timeframe": interval,
        "price": price,
        "rsi": round(current_rsi, 2),
        "ema20": round(ema20, 10),
        "ema50": round(ema50, 10),
        "support": support,
        "resistance": resistance,
        "early_signal": early_signal,
        "confirmed_signal": confirmed_signal,
        "early_buy_score": early_buy_score,
        "early_sell_score": early_sell_score,
        "signal": signal
    }


# =====================================
# SCAN ONE COIN
# =====================================

def scan_one(symbol):

    results = {}

    for timeframe in ("4h", "1d"):

        try:
            results[timeframe] = analyze(
                symbol,
                timeframe
            )

        except Exception as error:
            results[timeframe] = {
                "symbol": symbol,
                "timeframe": timeframe,
                "signal": "DATA ERROR",
                "early_signal": "DATA ERROR",
                "confirmed_signal": "DATA ERROR",
                "error": str(error)[:160]
            }

        time.sleep(0.04)

    return {
        "symbol": symbol,
        "4h": results["4h"],
        "1d": results["1d"]
    }


# =====================================
# HOME PAGE
# =====================================

@app.get("/")
def home():
    return FileResponse("static/index.html")


# =====================================
# STATUS API
# =====================================

@app.get("/api/status")
def status():

    try:
        symbols = get_symbols()

        return {
            "ok": True,
            "version": "2.0",
            "exchange": "Binance Spot",
            "quote": "USDT",
            "total_pairs": len(symbols),
            "timeframes": ["4h", "1d"],
            "indicators": [
                "RSI 14",
                "EMA 20",
                "EMA 50",
                "Support",
                "Resistance"
            ],
            "signals": [
                "EARLY BUY",
                "EARLY SELL",
                "CONFIRMED BUY",
                "CONFIRMED SELL"
            ]
        }

    except Exception as error:
        return {
            "ok": False,
            "error": str(error)
        }


# =====================================
# SCAN API
# =====================================

@app.get("/api/scan")
def scan(
    offset: int = Query(0, ge=0),
    limit: int = Query(40, ge=1, le=100)
):

    try:
        symbols = get_symbols()
        batch = symbols[offset:offset + limit]

        if not batch:
            return {
                "total": len(symbols),
                "offset": offset,
                "next_offset": 0,
                "done": True,
                "results": []
            }

        output = []

        with ThreadPoolExecutor(max_workers=6) as executor:

            futures = {
                executor.submit(scan_one, symbol): symbol
                for symbol in batch
            }

            for future in as_completed(futures):
                try:
                    output.append(future.result())
                except Exception as error:
                    symbol = futures[future]
                    output.append({
                        "symbol": symbol,
                        "4h": None,
                        "1d": None,
                        "error": str(error)[:160]
                    })

        output.sort(key=lambda x: x["symbol"])

        next_offset = offset + len(batch)

        return {
            "version": "2.0",
            "total": len(symbols),
            "offset": offset,
            "next_offset": (
                0 if next_offset >= len(symbols)
                else next_offset
            ),
            "done": next_offset >= len(symbols),
            "results": output
        }

    except Exception as error:
        return {
            "error": str(error),
            "results": []
        }


# =====================================
# HEALTH CHECK
# =====================================

@app.get("/health")
def health():
    return {
        "status": "online",
        "version": "2.0"
    }
