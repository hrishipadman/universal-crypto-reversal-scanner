import os
import time
import requests
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, jsonify, send_from_directory

app = Flask(__name__, static_folder="static")

BINANCE_API = "https://data-api.binance.vision"

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT",
    "SOLUSDT", "DOGEUSDT", "ADAUSDT", "TRXUSDT",
    "LINKUSDT", "AVAXUSDT", "DOTUSDT", "LTCUSDT",
    "BCHUSDT", "ETCUSDT", "NEARUSDT"
]

session = requests.Session()
session.headers.update({"User-Agent": "Crypto-Reversal-Scanner/1.0"})


def get_candles(symbol, interval):
    url = f"{BINANCE_API}/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": 220}

    response = session.get(url, params=params, timeout=15)
    response.raise_for_status()
    data = response.json()

    if not isinstance(data, list) or len(data) < 60:
        raise ValueError("Not enough candle data")

    candles = []
    for item in data:
        candles.append({
            "high": float(item[2]),
            "low": float(item[3]),
            "close": float(item[4])
        })

    # Binance's last candle may still be forming.
    return candles[:-1]


def ema(values, period):
    if len(values) < period:
        raise ValueError("Not enough data for EMA")

    multiplier = 2 / (period + 1)
    result = sum(values[:period]) / period

    for value in values[period:]:
        result = (value - result) * multiplier + result

    return result


def calculate_rsi(values, period=14):
    if len(values) <= period:
        raise ValueError("Not enough data for RSI")

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_macd(values):
    if len(values) < 40:
        raise ValueError("Not enough data for MACD")

    fast_values = []
    slow_values = []

    for end in range(26, len(values) + 1):
        part = values[:end]
        fast_values.append(ema(part, 12))
        slow_values.append(ema(part, 26))

    macd_values = [
        fast_values[i] - slow_values[i]
        for i in range(len(fast_values))
    ]

    macd_line = macd_values[-1]
    signal_line = ema(macd_values, 9)

    return macd_line, signal_line


def analyze_timeframe(symbol, interval):
    candles = get_candles(symbol, interval)
    closes = [c["close"] for c in candles]

    price = closes[-1]
    previous_rsi = calculate_rsi(closes[:-1])
    rsi = calculate_rsi(closes)

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    macd, macd_signal = calculate_macd(closes)

    bullish_early = (
        price > ema20
        and ema20 > ema50
        and rsi > previous_rsi
        and 40 <= rsi <= 65
    )

    bearish_early = (
        price < ema20
        and ema20 < ema50
        and rsi < previous_rsi
        and 35 <= rsi <= 60
    )

    bullish_confirmed = (
        price > ema20
        and ema20 > ema50
        and rsi > 50
        and macd > macd_signal
    )

    bearish_confirmed = (
        price < ema20
        and ema20 < ema50
        and rsi < 50
        and macd < macd_signal
    )

    early = (
        "BUY" if bullish_early else
        "SELL" if bearish_early else "WAIT"
    )

    confirmed = (
        "BUY" if bullish_confirmed else
        "SELL" if bearish_confirmed else "WAIT"
    )

    return {
        "price": round(price, 8),
        "rsi": round(rsi, 2),
        "ema20": round(ema20, 8),
        "ema50": round(ema50, 8),
        "early_signal": early,
        "confirmed_signal": confirmed
    }


def analyze_coin(symbol):
    try:
        one_hour = analyze_timeframe(symbol, "1h")
        four_hour = analyze_timeframe(symbol, "4h")
        one_day = analyze_timeframe(symbol, "1d")

        strong = "WAIT"

        if (
            four_hour["confirmed_signal"] == "BUY"
            and one_day["confirmed_signal"] == "BUY"
        ):
            strong = "STRONG BUY"

        elif (
            four_hour["confirmed_signal"] == "SELL"
            and one_day["confirmed_signal"] == "SELL"
        ):
            strong = "STRONG SELL"

        return {
            "symbol": symbol,
            "status": "OK",
            "1h": one_hour,
            "4h": four_hour,
            "1d": one_day,
            "strong_signal": strong
        }

    except Exception as error:
        return {
            "symbol": symbol,
            "status": "ERROR",
            "error": str(error),
            "strong_signal": "WAIT"
        }


@app.route("/")
def home():
    return send_from_directory("static", "index.html")


@app.route("/api/scan")
def scan():
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(analyze_coin, SYMBOLS))

    return jsonify({
        "success": True,
        "count": len(results),
        "updated": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "coins": results
    })


@app.route("/health")
def health():
    return jsonify({"status": "running"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
