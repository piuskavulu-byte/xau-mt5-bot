# main.py - FINAL XAU - $3 Trailing - Render.com Ready
import os, time, requests, json, asyncio, websockets
import pandas as pd, yfinance as yf
from flask import Flask

SYMBOL = "XAUUSD"
RR = 3.0
LOT = 0.01
ENABLE_TRAILING = True
TRAILING_START = 3.0
TRAILING_STEP = 2.0
TRAILING_DISTANCE = 3.0

DERIV_TOKEN = os.getenv("DERIV_TOKEN", "")
DERIV_MT5_LOGIN = os.getenv("DERIV_MT5_LOGIN", "")
DERIV_APP_ID = "1089"
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")

app = Flask(__name__)

def tg(msg):
    print(msg)
    if not TG_TOKEN or not TG_CHAT: return
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                      json={"chat_id": TG_CHAT, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except: pass

def get_candles(interval, period, count=250):
    try:
        df = yf.download("GC=F", period=period, interval=interval, progress=False)
        if df.empty: return None
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        df = df.rename(columns={"Open":"open","High":"high","Low":"low","Close":"close"})
        return df.tail(count)
    except: return None

def get_trend(df):
    if df is None or len(df) < 200: return "NEUTRAL"
    df['ema50'] = df['close'].ewm(span=50).mean()
    df['ema200'] = df['close'].ewm(span=200).mean()
    return "BULLISH" if df.iloc[-1]['ema50'] > df.iloc[-1]['ema200'] else "BEARISH"

def check_liq(df, bias):
    if df is None or len(df) < 30: return False, 0
    rh = df['high'].iloc[-21:-1].max()
    rl = df['low'].iloc[-21:-1].min()
    close = df['close'].iloc[-1]
    low = df['low'].iloc[-1]
    high = df['high'].iloc[-1]
    if bias=="BULLISH": return (low < rl and close > rl), rl
    else: return (high > rh and close < rh), rh

def check_entry(df, bias):
    if df is None or len(df) < 25: return None
    rh = df['high'].iloc[-21:-1].max()
    rl = df['low'].iloc[-21:-1].min()
    close = df['close'].iloc[-1]
    if bias=="BULLISH" and close > rh: return {"entry": close, "sl": rl, "bos": rh}
    if bias=="BEARISH" and close < rl: return {"entry": close, "sl": rh, "bos": rl}
    return None

async def place_mt5_async(bias, entry, sl, tp):
    uri = f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"authorize": DERIV_TOKEN}))
        await ws.recv()
        order = {"mt5_new_trade": 1, "login": DERIV_MT5_LOGIN, "symbol": "XAUUSD", "volume": LOT, "type": "buy" if bias=="BULLISH" else "sell", "sl": float(sl), "tp": float(tp)}
        await ws.send(json.dumps(order))
        resp = json.loads(await ws.recv())
        return resp

async def trailing_async():
    uri = f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"
    try:
        async with websockets.connect(uri) as ws:
            await ws.send(json.dumps({"authorize": DERIV_TOKEN}))
            await ws.recv()
            await ws.send(json.dumps({"mt5_get_positions": 1, "login": DERIV_MT5_LOGIN}))
            resp = json.loads(await ws.recv())
            if "mt5_get_positions" not in resp: return
            for pos in resp["mt5_get_positions"]:
                if pos["symbol"]!="XAUUSD": continue
                ticket = pos["ticket"]; entry = float(pos["open_price"]); curr = float(pos["current_price"]); sl = float(pos["sl"]) if pos["sl"] else 0
                profit = (curr-entry) if pos["type"]=="buy" else (entry-curr)
                if profit >= TRAILING_START:
                    new_sl = (curr - TRAILING_DISTANCE) if pos["type"]=="buy" else (curr + TRAILING_DISTANCE)
                    if (pos["type"]=="buy" and new_sl > sl) or (pos["type"]=="sell" and (sl==0 or new_sl < sl)):
                        await ws.send(json.dumps({"mt5_modify_position": 1, "login": DERIV_MT5_LOGIN, "ticket": ticket, "sl": float(new_sl), "tp": float(pos["tp"])}))
                        await ws.recv()
                        tg(f"🔒 *TRAILING {pos['type'].upper()}* Ticket {ticket} New SL `{new_sl:.2f}` Locked +{profit:.2f}$")
    except Exception as e:
        print(f"Trailing err {e}")

def bot_loop():
    tg(f"🟢 *RENDER BOT STARTED* Lot {LOT} RR 1:{RR} Trail ${TRAILING_START} MT5 {DERIV_MT5_LOGIN}")
    while True:
        try:
            df_h1 = get_candles("60m","10d",250)
            df_h4 = get_candles("240m","30d",250)
            df_15m = get_candles("15m","5d",100)
            df_5m = get_candles("5m","5d",100)
            if None not in [df_h1,df_h4,df_15m,df_5m]:
                h1 = get_trend(df_h1); h4 = get_trend(df_h4)
                if h1==h4 and h1!="NEUTRAL":
                    swept, liq = check_liq(df_15m, h1)
                    if swept:
                        sig = check_entry(df_5m, h1)
                        if sig:
                            entry=sig['entry']; sl=sig['sl']
                            tp=entry+abs(entry-sl)*RR if h1=="BULLISH" else entry-abs(entry-sl)*RR
                            tg(f"🟢 *SIGNAL {h1}* Entry {entry:.2f} SL {sl:.2f} TP {tp:.2f} Placing {LOT} lot...")
                            asyncio.run(place_mt5_async(h1,entry,sl,tp))
                            time.sleep(1800)
            if ENABLE_TRAILING:
                asyncio.run(trailing_async())
            time.sleep(15)
        except Exception as e:
            print(e); time.sleep(15)

@app.route('/')
def home(): return f"Bot Live Fixed {LOT} Trail ${TRAILING_START}"

import threading
threading.Thread(target=bot_loop, daemon=True).start()
