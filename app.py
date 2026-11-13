import os, time, math, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
import requests
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE = os.getenv("BINANCE_BASE_URL", "https://api.binance.com")
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "UniversalCryptoReversalScanner/1.0"})
app = FastAPI(title="Universal Crypto Reversal Scanner")
app.mount("/static", StaticFiles(directory="static"), name="static")

_universe = {"at": 0, "symbols": []}
_lock = threading.Lock()

def api_get(path, params=None, timeout=15):
    r = SESSION.get(BASE + path, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()

def get_symbols():
    now = time.time()
    with _lock:
        if _universe["symbols"] and now - _universe["at"] < 1800:
            return _universe["symbols"]
    info = api_get("/api/v3/exchangeInfo")
    symbols = []
    for s in info.get("symbols", []):
        name = s.get("symbol", "")
        if (s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT"
            and s.get("isSpotTradingAllowed", True)
            and not any(x in name for x in ["UPUSDT","DOWNUSDT","BULLUSDT","BEARUSDT"])): 
            symbols.append(name)
    with _lock:
        _universe.update({"at": now, "symbols": sorted(set(symbols))})
    return _universe["symbols"]

def ema(values, period):
    if len(values) < period: return None
    k = 2/(period+1)
    v = sum(values[:period])/period
    for x in values[period:]:
        v = x*k + v*(1-k)
    return v

def rsi(values, period=14):
    if len(values) < period+2: return None, None
    gains, losses = [], []
    for i in range(1, len(values)):
        d = values[i]-values[i-1]
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    avg_g = sum(gains[:period])/period
    avg_l = sum(losses[:period])/period
    series = []
    for i in range(period, len(gains)):
        avg_g = (avg_g*(period-1)+gains[i])/period
        avg_l = (avg_l*(period-1)+losses[i])/period
        rs = avg_g/avg_l if avg_l else 100
        series.append(100-(100/(1+rs)))
    if len(series) < 2: return None, None
    return series[-1], series[-2]

def analyze(symbol, interval):
    candles = api_get("/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": 100})
    # Exclude the still-forming candle to avoid repainting signals.
    candles = candles[:-1]
    closes = [float(c[4]) for c in candles]
    lows = [float(c[3]) for c in candles[-30:]]
    highs = [float(c[2]) for c in candles[-30:]]
    if len(closes) < 55: return None
    rv, rp = rsi(closes)
    e20, e50 = ema(closes, 20), ema(closes, 50)
    # Previous EMA values are computed from closes excluding the last closed candle.
    pe20, pe50 = ema(closes[:-1], 20), ema(closes[:-1], 50)
    price = closes[-1]
    support, resistance = min(lows), max(highs)
    near_support = price <= support * 1.018
    near_resistance = price >= resistance * 0.982
    rsi_bull = rp is not None and rp < 30 and rv >= 30
    rsi_bear = rp is not None and rp > 70 and rv <= 70
    ema_bull = pe20 is not None and pe50 is not None and pe20 <= pe50 and e20 > e50
    ema_bear = pe20 is not None and pe50 is not None and pe20 >= pe50 and e20 < e50
    # Support/resistance rejection: candle closes in upper/lower part of its range.
    last = candles[-1]
    o, h, l, c = map(float, [last[1], last[2], last[3], last[4]])
    rng = max(h-l, 1e-12)
    bullish_reject = near_support and c > o and (c-l)/rng >= 0.65
    bearish_reject = near_resistance and c < o and (h-c)/rng >= 0.65
    buy = int(rsi_bull) + int(ema_bull) + int(bullish_reject)
    sell = int(rsi_bear) + int(ema_bear) + int(bearish_reject)
    if buy == 3: signal = "STRONG BUY"
    elif buy == 2: signal = "BUY WATCH"
    elif sell == 3: signal = "STRONG SELL"
    elif sell == 2: signal = "SELL WATCH"
    else: signal = "WAIT"
    return {
        "symbol": symbol, "timeframe": interval, "price": price,
        "rsi": round(rv, 2), "ema20": e20, "ema50": e50,
        "support": support, "resistance": resistance,
        "buy_score": buy, "sell_score": sell, "signal": signal,
        "checks": {"rsi_bull": rsi_bull, "ema_bull": ema_bull,
                   "support_rejection": bullish_reject, "rsi_bear": rsi_bear,
                   "ema_bear": ema_bear, "resistance_rejection": bearish_reject}
    }

def scan_one(symbol):
    results = {}
    for tf in ("4h", "1d"):
        try:
            results[tf] = analyze(symbol, tf)
        except Exception as e:
            results[tf] = {"symbol": symbol, "timeframe": tf, "signal": "DATA ERROR",
                           "error": str(e)[:140]}
        time.sleep(0.04)
    return {"symbol": symbol, "4h": results["4h"], "1d": results["1d"]}

@app.get("/")
def home():
    return FileResponse("static/index.html")

@app.get("/api/status")
def status():
    try:
        syms = get_symbols()
        return {"ok": True, "exchange": "Binance Spot", "quote": "USDT",
                "total_pairs": len(syms), "timeframes": ["4h", "1d"]}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/scan")
def scan(offset: int = Query(0, ge=0), limit: int = Query(40, ge=1, le=100)):
    try:
        symbols = get_symbols()
        batch = symbols[offset:offset+limit]
        if not batch:
            return {"total": len(symbols), "offset": offset, "next_offset": 0,
                    "done": True, "results": []}
        output = []
        # Keep concurrency modest to respect public API rate limits.
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(scan_one, s) for s in batch]
            for f in as_completed(futures):
                output.append(f.result())
        output.sort(key=lambda x: x["symbol"])
        next_offset = offset + len(batch)
        return {"total": len(symbols), "offset": offset,
                "next_offset": 0 if next_offset >= len(symbols) else next_offset,
                "done": next_offset >= len(symbols), "results": output}
    except Exception as e:
        return {"error": str(e), "results": []}

@app.get("/manifest.json")
def manifest():
    return FileResponse("static/manifest.json")
