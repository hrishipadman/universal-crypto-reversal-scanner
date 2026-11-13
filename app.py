
import os
import time
import requests
import pandas as pd
from flask import Flask, jsonify, send_from_directory

app = Flask(__name__, static_folder="static")

BINANCE_API = "https://data-api.binance.vision"
SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT",
    "SOLUSDT", "DOGEUSDT", "ADAUSDT", "TRXUSDT",
    "LINKUSDT", "AVAXUSDT", "DOTUSDT", "LTCUSDT",
    "BCHUSDT", "ETCUSDT", "NEARUSDT"
]


def get_candles(symbol, interval, limit=220):
    url = f"{BINANCE_API}/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }

    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()
    data = response.json()

    df = pd.DataFrame(data, columns=[
        "time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore"
    ])

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col])

    return df


def calculate_indicators(df):
    df = df.copy()

    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()

    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, 0.0000001)
    df["rsi"] = 100 - (100 / (1 + rs))

    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()

    df["macd"] = ema12 - ema26
    df["signal"] = df["macd"].ewm(span=9, adjust=False).mean()

    return df


def analyze_timeframe(symbol, interval):
    df = calculate_indicators(get_candles(symbol, interval))

    # Use the last completed candle, not the currently forming candle.
    last = df.iloc[-2]
    previous = df.iloc[-3]

    price = float(last["close"])
    rsi = float(last["rsi"])
    ema20 = float(last["ema20"])
    ema50 = float(last["ema50"])
    macd = float(last["macd"])
    macd_signal = float(last["signal"])

    bullish_early = (
        price > ema20
        and ema20 > ema50
        and rsi > float(previous["rsi"])
        and 40 <= rsi <= 65
    )

    bearish_early = (
        price < ema20
        and ema20 < ema50
        and rsi < float(previous["rsi"])
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

    early = "BUY" if bullish_early else (
        "SELL" if bearish_early else "WAIT"
    )

    confirmed = "BUY" if bullish_confirmed else (
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
    result = {"symbol": symbol}

    try:
        one_hour = analyze_timeframe(symbol, "1h")
        four_hour = analyze_timeframe(symbol, "4h")
        one_day = analyze_timeframe(symbol, "1d")

        # Strong signal only when BOTH 4H and 1D agree.
        strong_signal = "WAIT"

        if (
            four_hour["confirmed_signal"] == "BUY"
            and one_day["confirmed_signal"] == "BUY"
        ):
            strong_signal = "STRONG BUY"

        elif (
            four_hour["confirmed_signal"] == "SELL"
            and one_day["confirmed_signal"] == "SELL"
        ):
            strong_signal = "STRONG SELL"

        result.update({
            "1h": one_hour,
            "4h": four_hour,
            "1d": one_day,
            "strong_signal": strong_signal,
            "status": "OK"
        })

    except Exception as error:
        result.update({
            "status": "ERROR",
            "error": str(error),
            "strong_signal": "WAIT"
        })

    return result


@app.route("/")
def home():
    return send_from_directory("static", "index.html")


@app.route("/api/scan")
def scan():
    results = []

    for symbol in SYMBOLS:
        results.append(analyze_coin(symbol))
        time.sleep(0.15)

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
