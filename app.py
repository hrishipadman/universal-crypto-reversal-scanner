
from flask import Flask, jsonify
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

# -----------------------------
# SETTINGS
# -----------------------------

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "SOLUSDT", "TRXUSDT",
    "LINKUSDT", "LTCUSDT", "BCHUSDT", "DOTUSDT",
    "AVAXUSDT", "MATICUSDT", "SHIBUSDT", "DOGEBTC"
]

BINANCE_HOSTS = [
    "https://data-api.binance.vision",
    "https://api-gcp.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api4.binance.com",
    "https://api.binance.com"
]

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "UniversalCryptoReversalScanner/1.0"})


# -----------------------------
# BINANCE DATA
# -----------------------------

def get_klines(symbol, interval, limit=120):
    last_error = None

    for host in BINANCE_HOSTS:
        try:
            url = f"{host}/api/v3/klines"
            response = SESSION.get(
                url,
                params={
                    "symbol": symbol,
                    "interval": interval,
                    "limit": limit
                },
                timeout=12
            )
            response.raise_for_status()
            data = response.json()

            if not isinstance(data, list) or len(data) < 55:
                raise ValueError("Not enough candle data")

            # Binance's final candle may still be forming.
            # Keep only fully closed candles.
            now_ms = int(time.time() * 1000)
            closed = [c for c in data if int(c[6]) < now_ms]

            if len(closed) < 55:
                raise ValueError("Not enough closed candles")

            return [
                {
                    "time": int(c[0]),
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "volume": float(c[5])
                }
                for c in closed
            ]

        except Exception as exc:
            last_error = str(exc)

    raise RuntimeError(last_error or "Binance API unavailable")


# -----------------------------
# INDICATORS
# -----------------------------

def calculate_ema(values, period):
    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)
    ema_value = sum(values[:period]) / period

    for value in values[period:]:
        ema_value = (value * multiplier) + (
            ema_value * (1 - multiplier)
        )

    return ema_value


def calculate_rsi(values, period=14):
    if len(values) <= period:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    rsi_values = []

    def get_rsi(gain, loss):
        if loss == 0:
            return 100.0
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    rsi_values.append(get_rsi(avg_gain, avg_loss))

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period
        rsi_values.append(get_rsi(avg_gain, avg_loss))

    return rsi_values


def get_support_resistance(candles):
    # Use the previous 30 closed candles, excluding the latest candle.
    previous = candles[-31:-1]

    if not previous:
        return None, None

    support = min(c["low"] for c in previous)
    resistance = max(c["high"] for c in previous)

    return support, resistance


def candle_details(candle):
    body = abs(candle["close"] - candle["open"])
    total_range = max(candle["high"] - candle["low"], 1e-12)

    lower_wick = min(candle["open"], candle["close"]) - candle["low"]
    upper_wick = candle["high"] - max(candle["open"], candle["close"])

    return {
        "bullish": candle["close"] > candle["open"],
        "bearish": candle["close"] < candle["open"],
        "body": body,
        "lower_wick": max(lower_wick, 0),
        "upper_wick": max(upper_wick, 0),
        "range": total_range
    }


# -----------------------------
# 1H EARLY SIGNAL
# Three required conditions:
# Candle + RSI crossing + Support/Resistance
# -----------------------------

def early_analysis(candles):
    closes = [c["close"] for c in candles]
    rsi_values = calculate_rsi(closes)

    support, resistance = get_support_resistance(candles)
    last = candles[-1]
    details = candle_details(last)

    current_rsi = rsi_values[-1]
    previous_rsi = rsi_values[-2]

    ema30 = calculate_ema(closes, 30)
    ema50 = calculate_ema(closes, 50)

    ema_bias = "NEUTRAL"
    if ema30 is not None and ema50 is not None:
        if ema30 > ema50:
            ema_bias = "BULLISH"
        elif ema30 < ema50:
            ema_bias = "BEARISH"

    near_support = (
        support is not None
        and last["low"] <= support * 1.018
        and last["close"] >= support
    )

    near_resistance = (
        resistance is not None
        and last["high"] >= resistance * 0.982
        and last["close"] <= resistance
    )

    # BUY: bullish reversal candle + RSI crosses above 30 + support zone
    bullish_candle = (
        details["bullish"]
        and details["lower_wick"] >= details["body"] * 0.5
    )

    if (
        bullish_candle
        and previous_rsi <= 30
        and current_rsi > 30
        and near_support
    ):
        signal = "BUY"
        reason = "Bullish candle + RSI crossed above 30 + Support"

    # SELL: bearish reversal candle + RSI crosses below 70 + resistance zone
    elif (
        details["bearish"]
        and details["upper_wick"] >= details["body"] * 0.5
        and previous_rsi >= 70
        and current_rsi < 70
        and near_resistance
    ):
        signal = "SELL"
        reason = "Bearish candle + RSI crossed below 70 + Resistance"

    else:
        signal = "WAIT"
        reason = "All three Early Signal conditions not met"

    return {
        "signal": signal,
        "rsi": round(current_rsi, 2),
        "support": support,
        "resistance": resistance,
        "ema30": ema30,
        "ema50": ema50,
        "ema_bias": ema_bias,
        "reason": reason
    }


# -----------------------------
# 4H MAIN REVERSAL
# RSI + EMA 30/50
# -----------------------------

def main_reversal_analysis(candles):
    closes = [c["close"] for c in candles]
    rsi_values = calculate_rsi(closes)

    current_rsi = rsi_values[-1]
    previous_rsi = rsi_values[-2]

    ema30 = calculate_ema(closes, 30)
    ema50 = calculate_ema(closes, 50)

    bullish_rsi = previous_rsi <= 30 and current_rsi > 30
    bearish_rsi = previous_rsi >= 70 and current_rsi < 70

    bullish_ema = ema30 > ema50
    bearish_ema = ema30 < ema50

    if bullish_rsi and bullish_ema:
        signal = "BUY"
        reason = "4H RSI crossed above 30 + EMA30 above EMA50"

    elif bearish_rsi and bearish_ema:
        signal = "SELL"
        reason = "4H RSI crossed below 70 + EMA30 below EMA50"

    else:
        signal = "WAIT"
        reason = "4H RSI and EMA confirmation not aligned"

    support, resistance = get_support_resistance(candles)

    return {
        "signal": signal,
        "rsi": round(current_rsi, 2),
        "support": support,
        "resistance": resistance,
        "ema30": ema30,
        "ema50": ema50,
        "reason": reason
    }


# -----------------------------
# 1D CONFIRMATION
# Daily RSI + candle direction
# -----------------------------

def daily_confirmation(candles):
    closes = [c["close"] for c in candles]
    rsi_values = calculate_rsi(closes)

    current_rsi = rsi_values[-1]
    last = candles[-1]
    details = candle_details(last)

    if current_rsi > 50 and details["bullish"]:
        signal = "BUY"
        reason = "Daily RSI above 50 + bullish candle"

    elif current_rsi < 50 and details["bearish"]:
        signal = "SELL"
        reason = "Daily RSI below 50 + bearish candle"

    else:
        signal = "WAIT"
        reason = "Daily RSI and candle direction not aligned"

    return {
        "signal": signal,
        "rsi": round(current_rsi, 2),
        "reason": reason
    }


# -----------------------------
# SCAN ONE COIN
# -----------------------------

def scan_symbol(symbol):
    try:
        candles_1h = get_klines(symbol, "1h")
        candles_4h = get_klines(symbol, "4h")
        candles_1d = get_klines(symbol, "1d")

        early = early_analysis(candles_1h)
        main = main_reversal_analysis(candles_4h)
        daily = daily_confirmation(candles_1d)

        strong = "WAIT"

        if (
            main["signal"] == "BUY"
            and daily["signal"] == "BUY"
        ):
            strong = "STRONG BUY"

        elif (
            main["signal"] == "SELL"
            and daily["signal"] == "SELL"
        ):
            strong = "STRONG SELL"

        return {
            "symbol": symbol,
            "1H": early,
            "4H": main,
            "1D": daily,
            "rsi": main["rsi"],
            "support": main["support"],
            "resistance": main["resistance"],
            "strong": strong,
            "status": "OK"
        }

    except Exception as exc:
        return {
            "symbol": symbol,
            "1H": {"signal": "WAIT", "reason": "Data unavailable"},
            "4H": {"signal": "WAIT", "reason": "Data unavailable"},
            "1D": {"signal": "WAIT", "reason": "Data unavailable"},
            "rsi": None,
            "support": None,
            "resistance": None,
            "strong": "WAIT",
            "status": "ERROR",
            "error": str(exc)
        }


# -----------------------------
# API ROUTES
# -----------------------------

@app.route("/")
def home():
    return jsonify({
        "service": "Universal Crypto Reversal Scanner",
        "status": "running"
    })


@app.route("/health")
def health():
    return jsonify({
        "service": "Universal Crypto Reversal Scanner",
        "status": "ok"
    })


@app.route("/api/scan")
def scan():
    results = []

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(scan_symbol, symbol): symbol
            for symbol in SYMBOLS
        }

        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                symbol = futures[future]
                results.append({
                    "symbol": symbol,
                    "status": "ERROR",
                    "error": str(exc),
                    "strong": "WAIT"
                })

    # Keep the dashboard in the configured coin order.
    order = {symbol: index for index, symbol in enumerate(SYMBOLS)}
    results.sort(key=lambda item: order.get(item["symbol"], 999))

    return jsonify({
        "status": "success",
        "total": len(results),
        "successful": sum(1 for r in results if r.get("status") == "OK"),
        "failed": sum(1 for r in results if r.get("status") != "OK"),
        "strong_buy": sum(1 for r in results if r.get("strong") == "STRONG BUY"),
        "strong_sell": sum(1 for r in results if r.get("strong") == "STRONG SELL"),
        "results": results
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
