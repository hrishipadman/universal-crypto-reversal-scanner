
from flask import Flask, jsonify, send_from_directory
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import time

app = Flask(__name__, static_folder="static")

# Binance Public API endpoints: automatic fallback
BINANCE_BASES = [
    "https://data-api.binance.vision",
    "https://api-gcp.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api4.binance.com",
    "https://api.binance.com"
]

TIMEOUT = 10

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT",
    "SOLUSDT", "DOGEUSDT", "ADAUSDT", "TRXUSDT",
    "LINKUSDT", "AVAXUSDT", "DOTUSDT", "LTCUSDT",
    "BCHUSDT", "NEARUSDT", "ATOMUSDT", "DOGEBTC"
]

INTERVALS = {
    "1H": "1h",
    "4H": "4h",
    "1D": "1d"
}


def get_json(path, params=None):
    errors = []

    for base in BINANCE_BASES:
        try:
            response = requests.get(
                base + path,
                params=params,
                timeout=TIMEOUT,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/json"
                }
            )

            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as exc:
            errors.append(
                base + " : " + str(exc)[:120]
            )

    raise Exception(
        "All Binance Public API endpoints failed: "
        + " | ".join(errors[-3:])
    )


def fetch_klines(symbol, interval, limit=100):

    raw = get_json(
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )

    # Ignore currently forming candle
    if len(raw) > 1:
        raw = raw[:-1]

    candles = []

    for k in raw:
        candles.append({
            "open_time": int(k[0]),
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
            "close_time": int(k[6])
        })

    return candles


def ema(values, period):

    if len(values) < period:
        return None

    alpha = 2.0 / (period + 1.0)

    value = sum(values[:period]) / period

    for item in values[period:]:
        value = (
            item * alpha
            + value * (1.0 - alpha)
        )

    return value


def rsi_series(values, period=14):

    if len(values) <= period:
        return []

    gains = []
    losses = []

    for i in range(1, len(values)):

        change = values[i] - values[i - 1]

        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    result = [None] * period

    def calculate_rsi(gain, loss):

        if loss == 0:
            return 100.0 if gain > 0 else 50.0

        rs = gain / loss

        return 100.0 - (100.0 / (1.0 + rs))

    result.append(
        calculate_rsi(avg_gain, avg_loss)
    )

    for i in range(period, len(gains)):

        avg_gain = (
            avg_gain * (period - 1) + gains[i]
        ) / period

        avg_loss = (
            avg_loss * (period - 1) + losses[i]
        ) / period

        result.append(
            calculate_rsi(avg_gain, avg_loss)
        )

    return result


def reversal_analysis(candles):

    if len(candles) < 55:

        return {
            "signal": "WAIT",
            "reason": "कम candles",
            "rsi": None,
            "support": None,
            "resistance": None
        }

    closes = [c["close"] for c in candles]

    last = candles[-1]

    rsis = rsi_series(closes, 14)

    rsi_now = rsis[-1] if rsis else None

    rsi_prev = (
        rsis[-2] if len(rsis) > 1 else None
    )

    ema20_now = ema(closes, 20)
    ema50_now = ema(closes, 50)

    ema20_prev = ema(closes[:-1], 20)
    ema50_prev = ema(closes[:-1], 50)

    # Previous 30 closed candles
    history = candles[-31:-1]

    support = min(c["low"] for c in history)
    resistance = max(c["high"] for c in history)

    price = last["close"]

    tolerance = 0.018

    near_support = (
        last["low"] <= support * (1 + tolerance)
        and price >= support * (1 - tolerance)
    )

    near_resistance = (
        last["high"] >= resistance * (1 - tolerance)
        and price <= resistance * (1 + tolerance)
    )

    candle_range = max(
        last["high"] - last["low"],
        1e-12
    )

    lower_wick = (
        min(last["open"], last["close"])
        - last["low"]
    )

    upper_wick = (
        last["high"]
        - max(last["open"], last["close"])
    )

    lower_wick_ratio = max(
        0.0, lower_wick / candle_range
    )

    upper_wick_ratio = max(
        0.0, upper_wick / candle_range
    )

    # Support rejection
    bullish_rejection = (
        near_support
        and last["close"] > last["open"]
        and lower_wick_ratio >= 0.65
    )

    # Resistance rejection
    bearish_rejection = (
        near_resistance
        and last["close"] < last["open"]
        and upper_wick_ratio >= 0.65
    )

    # RSI 14 crossing
    rsi_bull_cross = (
        rsi_prev is not None
        and rsi_now is not None
        and rsi_prev <= 30
        and rsi_now > 30
    )

    rsi_bear_cross = (
        rsi_prev is not None
        and rsi_now is not None
        and rsi_prev >= 70
        and rsi_now < 70
    )

    # RSI divergence
    bull_div = False
    bear_div = False

    if len(candles) >= 35 and len(rsis) >= 35:

        a = candles[-10:-5]
        b = candles[-5:]

        ra = [
            x for x in rsis[-10:-5]
            if x is not None
        ]

        rb = [
            x for x in rsis[-5:]
            if x is not None
        ]

        if ra and rb:

            bull_div = (
                min(x["low"] for x in b)
                < min(x["low"] for x in a)
                and min(rb) > min(ra)
            )

            bear_div = (
                max(x["high"] for x in b)
                > max(x["high"] for x in a)
                and max(rb) < max(ra)
            )

    # EMA crossover
    ema_bull_cross = (
        ema20_prev is not None
        and ema50_prev is not None
        and ema20_now > ema50_now
        and ema20_prev <= ema50_prev
    )

    ema_bear_cross = (
        ema20_prev is not None
        and ema50_prev is not None
        and ema20_now < ema50_now
        and ema20_prev >= ema50_prev
    )

    # Breakout and retest
    breakout_retest_buy = (
        last["close"] > resistance
        and last["low"] <= resistance * (1 + tolerance)
    )

    breakout_retest_sell = (
        last["close"] < support
        and last["high"] >= support * (1 - tolerance)
    )

    bull_rsi_ok = rsi_bull_cross or bull_div
    bear_rsi_ok = rsi_bear_cross or bear_div

    bull_confirm = (
        bullish_rejection
        and (bull_rsi_ok or ema_bull_cross)
    ) or (
        breakout_retest_buy
        and (bull_rsi_ok or ema_bull_cross)
    )

    bear_confirm = (
        bearish_rejection
        and (bear_rsi_ok or ema_bear_cross)
    ) or (
        breakout_retest_sell
        and (bear_rsi_ok or ema_bear_cross)
    )

    if bull_confirm and not bear_confirm:
        signal = "BUY"

    elif bear_confirm and not bull_confirm:
        signal = "SELL"

    else:
        signal = "WAIT"

    reasons = []

    if bullish_rejection:
        reasons.append("Support rejection")

    if bearish_rejection:
        reasons.append("Resistance rejection")

    if rsi_bull_cross:
        reasons.append("RSI crossed above 30")

    if rsi_bear_cross:
        reasons.append("RSI crossed below 70")

    if bull_div:
        reasons.append("Bullish RSI divergence")

    if bear_div:
        reasons.append("Bearish RSI divergence")

    if ema_bull_cross:
        reasons.append("EMA20 crossed above EMA50")

    if ema_bear_cross:
        reasons.append("EMA20 crossed below EMA50")

    if breakout_retest_buy:
        reasons.append("Bullish breakout/retest")

    if breakout_retest_sell:
        reasons.append("Bearish breakout/retest")

    return {
        "signal": signal,
        "reason": (
            ", ".join(reasons)
            if reasons
            else "Reversal setup not confirmed"
        ),
        "rsi": (
            round(rsi_now, 2)
            if rsi_now is not None
            else None
        ),
        "support": support,
        "resistance": resistance,
        "price": price,
        "ema20": ema20_now,
        "ema50": ema50_now,
        "closed_candle_time": last["close_time"]
    }


def scan_symbol(symbol):

    result = {
        "symbol": symbol,
        "1H": None,
        "4H": None,
        "1D": None,
        "strong": "WAIT"
    }

    try:

        for label, interval in INTERVALS.items():

            candles = fetch_klines(
                symbol,
                interval,
                100
            )

            result[label] = reversal_analysis(candles)

        four_h = result["4H"]["signal"]
        one_d = result["1D"]["signal"]

        if four_h == "BUY" and one_d == "BUY":

            result["strong"] = "STRONG BUY"

        elif four_h == "SELL" and one_d == "SELL":

            result["strong"] = "STRONG SELL"

        else:

            result["strong"] = "WAIT"

        return result

    except Exception as exc:

        result["error"] = str(exc)[:500]

        return result


@app.route("/")
def home():

    return send_from_directory(
        "static",
        "index.html"
    )


@app.route("/health")
def health():

    return jsonify({
        "status": "ok",
        "service": "Universal Crypto Reversal Scanner"
    })


@app.route("/api/scan")
def api_scan():

    started = time.time()

    rows = []

    # Limited workers to protect Render memory
    with ThreadPoolExecutor(max_workers=3) as pool:

        futures = {
            pool.submit(scan_symbol, symbol): symbol
            for symbol in SYMBOLS
        }

        for future in as_completed(futures):

            rows.append(future.result())

    order = {
        symbol: i
        for i, symbol in enumerate(SYMBOLS)
    }

    rows.sort(
        key=lambda x: order.get(x["symbol"], 999)
    )

    return jsonify({

        "status": "success",

        "count": len(rows),

        "symbols": rows,

        "strategy": (
            "Support/Resistance + RSI14 + "
            "Divergence + EMA20/50 + Breakout/Retest"
        ),

        "timeframes": [
            "1H Early",
            "4H Main Reversal",
            "1D Confirmation"
        ],

        "closed_candles_only": True,

        "scan_seconds": round(
            time.time() - started, 2
        ),

        "updated_utc": datetime.now(
            timezone.utc
        ).isoformat()

    })


if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=10000
    )
