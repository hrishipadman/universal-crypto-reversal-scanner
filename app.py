
import os
import time
import threading
import requests

from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Binance public market data endpoint
BASE = os.getenv(
    "BINANCE_BASE_URL",
    "https://data-api.binance.vision"
)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "UniversalCryptoReversalScanner/1.0"
})

app = FastAPI(title="Universal Crypto Reversal Scanner")

app.mount(
    "/static",
    StaticFiles(directory="static"),
    name="static"
)

universe = {"at": 0, "symbols": []}
lock = threading.Lock()


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
            and not any(
                word in name
                for word in ["UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT"]
            )
        ):
            symbols.append(name)

    symbols = sorted(set(symbols))

    with lock:
        universe["at"] = now
        universe["symbols"] = symbols

    return symbols


def ema(values, period):
    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)
    value = sum(values[:period]) / period

    for price in values[period:]:
        value = price * multiplier + value * (1 - multiplier)

    return value


def rsi(values, period=14):
    if len(values) < period + 2:
        return None, None

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    result = []

    for i in range(period, len(gains)):
        avg_gain = (
            avg_gain * (period - 1) + gains[i]
        ) / period

        avg_loss = (
            avg_loss * (period - 1) + losses[i]
        ) / period

        rs = avg_gain / avg_loss if avg_loss else 100
        result.append(100 - (100 / (1 + rs)))

    if len(result) < 2:
        return None, None

    return result[-1], result[-2]


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
    highs = [float(c[2]) for c in candles[-30:]]
    lows = [float(c[3]) for c in candles[-30:]]

    current_rsi, previous_rsi = rsi(closes)

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)

    previous_ema20 = ema(closes[:-1], 20)
    previous_ema50 = ema(closes[:-1], 50)

    price = closes[-1]

    support = min(lows)
    resistance = max(highs)

    near_support = price <= support * 1.018
    near_resistance = price >= resistance * 0.982

    rsi_bull = (
        previous_rsi is not None
        and previous_rsi < 30
        and current_rsi >= 30
    )

    rsi_bear = (
        previous_rsi is not None
        and previous_rsi > 70
        and current_rsi <= 70
    )

    ema_bull = (
        previous_ema20 <= previous_ema50
        and ema20 > ema50
    )

    ema_bear = (
        previous_ema20 >= previous_ema50
        and ema20 < ema50
    )

    last = candles[-1]

    open_price = float(last[1])
    high_price = float(last[2])
    low_price = float(last[3])
    close_price = float(last[4])

    candle_range = max(high_price - low_price, 1e-12)

    bullish_rejection = (
        near_support
        and close_price > open_price
        and (close_price - low_price) / candle_range >= 0.65
    )

    bearish_rejection = (
        near_resistance
        and close_price < open_price
        and (high_price - close_price) / candle_range >= 0.65
    )

    buy_score = (
        int(rsi_bull)
        + int(ema_bull)
        + int(bullish_rejection)
    )

    sell_score = (
        int(rsi_bear)
        + int(ema_bear)
        + int(bearish_rejection)
    )

    if buy_score == 3:
        signal = "STRONG BUY"
    elif buy_score == 2:
        signal = "BUY WATCH"
    elif sell_score == 3:
        signal = "STRONG SELL"
    elif sell_score == 2:
        signal = "SELL WATCH"
    else:
        signal = "WAIT"

    return {
        "symbol": symbol,
        "timeframe": interval,
        "price": price,
        "rsi": round(current_rsi, 2),
        "ema20": ema20,
        "ema50": ema50,
        "support": support,
        "resistance": resistance,
        "buy_score": buy_score,
        "sell_score": sell_score,
        "signal": signal
    }


def scan_one(symbol):

    results = {}

    for timeframe in ("4h", "1d"):
        try:
            results[timeframe] = analyze(symbol, timeframe)

        except Exception as error:
            results[timeframe] = {
                "symbol": symbol,
                "timeframe": timeframe,
                "signal": "DATA ERROR",
                "error": str(error)[:140]
            }

        time.sleep(0.04)

    return {
        "symbol": symbol,
        "4h": results["4h"],
        "1d": results["1d"]
    }


@app.get("/")
def home():
    return FileResponse("static/index.html")


@app.get("/api/status")
def status():

    try:
        symbols = get_symbols()

        return {
            "ok": True,
            "exchange": "Binance Spot",
            "quote": "USDT",
            "total_pairs": len(symbols),
            "timeframes": ["4h", "1d"]
        }

    except Exception as error:
        return {
            "ok": False,
            "error": str(error)
        }


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

            futures = [
                executor.submit(scan_one, symbol)
                for symbol in batch
            ]

            for future in as_completed(futures):
                output.append(future.result())

        output.sort(key=lambda x: x["symbol"])

        next_offset = offset + len(batch)

        return {
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
