# Universal Crypto Reversal Scanner (Starter v1)

## यह क्या करता है?
- Binance Spot के eligible USDT trading pairs की सूची अपने आप लेता है।
- 4H और 1D के बंद हो चुके candles पर RSI(14), EMA(20/50), Support/Resistance जांचता है।
- 40 pairs के batches में scan करता है; `Scan all pairs` से सभी batches चलाए जा सकते हैं।
- Buy/Sell Watch और Strong signals दिखाता है।
- यह signal-only है; कोई order नहीं लगाता और Binance API key नहीं मांगता।

## Android पर चलाने के लिए
यह ZIP एक starter project है, सीधे Android APK नहीं। इसे पहले cloud host (जैसे Render/Railway या अपना VPS) पर deploy करना होगा।
1. ZIP को extract करें।
2. GitHub पर नया repository बनाकर सभी files upload करें।
3. Render/Railway पर Python/Docker web service बनाएं और repository connect करें।
4. Service का public URL खोलें Android Chrome में।
5. Chrome menu → Add to Home screen / Install app चुनें।

## Local test (computer/VPS)
```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```
फिर `http://localhost:8000` खोलें।

## Signal नियम
प्रत्येक timeframe पर:
- RSI bullish: पिछली RSI < 30 और आखिरी बंद candle की RSI >= 30.
- RSI bearish: पिछली RSI > 70 और आखिरी बंद candle की RSI <= 70.
- EMA bullish/bearish: EMA20 और EMA50 का नया crossover.
- Support/Resistance: पिछले 30 बंद candles का low/high; पास में rejection candle.
- 2/3 = Watch; 3/3 = Strong; अन्यथा Wait.

## सीमाएं और सावधानियां
- Support/Resistance v1 में पिछले 30 candles का simple swing range है; advanced pivot-zone clustering नहीं।
- RSI divergence शामिल नहीं है।
- सभी symbols की scan एक साथ नहीं होती; API rate limits के लिए batches में होती है।
- Browser notification तब काम करती है जब app/browser चल रहा हो और notification permission दी गई हो। Background push notifications के लिए अलग push service और VAPID configuration की जरूरत होगी।
- Cloud hosting account और internet connection उपयोगकर्ता को उपलब्ध कराने होंगे; यह project अपने आप deploy नहीं हुआ है।
- पहले paper trading और backtesting करें। कोई signal लाभ की गारंटी नहीं देता।
