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


def get_historical_candles(symbol, interval):
    url = f"{BINANCE_API}/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": 1000}

    response = session.get(url, params=params, timeout=25)
    response.raise_for_status()
    data = response.json()

    candles = []
    for item in data[:-1]:
        candles.append({
            "open_time": int(item[0]),
            "close_time": int(item[6]),
            "high": float(item[2]),
            "low": float(item[3]),
            "close": float(item[4])
        })

    return candles


def historical_confirmed_signal(closes):
    if len(closes) < 60:
        return "WAIT"

    price = closes[-1]
    rsi = calculate_rsi(closes)
    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    macd, macd_signal = calculate_macd(closes)

    if price > ema20 and ema20 > ema50 and rsi > 50 and macd > macd_signal:
        return "BUY"

    if price < ema20 and ema20 < ema50 and rsi < 50 and macd < macd_signal:
        return "SELL"

    return "WAIT"


def backtest_coin(symbol):
    try:
        candles4h = get_historical_candles(symbol, "4h")
        candles1d = get_historical_candles(symbol, "1d")

        closes4h = [c["close"] for c in candles4h]
        closes1d = [c["close"] for c in candles1d]

        daily_index = 0
        trades = []

        # 7 days ahead requires 42 future 4H candles.
        for i in range(59, len(candles4h) - 42):

            signal_time = candles4h[i]["close_time"]

            while (
                daily_index + 1 < len(candles1d)
                and candles1d[daily_index + 1]["close_time"] <= signal_time
            ):
                daily_index += 1

            if candles1d[daily_index]["close_time"] > signal_time:
                continue

            signal4h = historical_confirmed_signal(closes4h[:i + 1])
            signal1d = historical_confirmed_signal(
                closes1d[:daily_index + 1]
            )

            if signal4h == "BUY" and signal1d == "BUY":
                direction = 1
                signal = "STRONG BUY"

            elif signal4h == "SELL" and signal1d == "SELL":
                direction = -1
                signal = "STRONG SELL"

            else:
                continue

            entry = closes4h[i]
            result = {
                "signal": signal,
                "entry_price": entry,
                "time": signal_time
            }

            for days, bars in [(1, 6), (3, 18), (7, 42)]:
                future_price = closes4h[i + bars]
                raw_return = ((future_price / entry) - 1) * 100
                directional_return = raw_return * direction

                result[f"return_{days}d_pct"] = round(raw_return, 3)
                result[f"directional_{days}d_pct"] = round(
                    directional_return, 3
                )
                result[f"win_{days}d"] = directional_return > 0

            trades.append(result)

        summary = {}

        for days in [1, 3, 7]:
            key = f"directional_{days}d_pct"
            wins = sum(1 for t in trades if t[f"win_{days}d"])
            count = len(trades)

            summary[f"{days}d"] = {
                "trades": count,
                "wins": wins,
                "losses": count - wins,
                "win_rate_pct": round(wins / count * 100, 2) if count else 0,
                "average_return_pct": round(
                    sum(t[key] for t in trades) / count, 3
                ) if count else 0
            }

        return {
            "symbol": symbol,
            "status": "OK",
            "total_strong_signals": len(trades),
            "summary": summary,
            "recent_trades": trades[-10:]
        }

    except Exception as error:
        return {
            "symbol": symbol,
            "status": "ERROR",
            "error": str(error)
        }


@app.route("/api/backtest")
def run_backtest():
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(backtest_coin, SYMBOLS))

    valid = [r for r in results if r["status"] == "OK"]

    return jsonify({
        "success": True,
        "method": "4H and 1D confirmed signals",
        "future_periods": ["1 day", "3 days", "7 days"],
        "coins_tested": len(results),
        "successful_coins": len(valid),
        "results": results
    })
    
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
