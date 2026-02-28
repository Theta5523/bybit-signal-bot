import asyncio
import logging
import os
from datetime import datetime, timedelta
import aiohttp
import pandas as pd
import numpy as np
from telegram import Bot
from telegram.constants import ParseMode

# GET SECRETS FROM ENVIRONMENT
BYBIT_API_KEY = os.environ.get('BYBIT_API_KEY')
BYBIT_API_SECRET = os.environ.get('BYBIT_API_SECRET')
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_ID = os.environ.get('TELEGRAM_CHANNEL_ID')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

class BybitClient:
    def __init__(self):
        self.base_url = "https://api.bybit.com"
        
    async def get_klines(self, symbol, interval, limit=100):
        async with aiohttp.ClientSession() as session:
            url = f"{self.base_url}/v5/market/kline"
            params = {"category": "linear", "symbol": symbol, "interval": interval, "limit": limit}
            async with session.get(url, params=params) as resp:
                data = await resp.json()
                if data.get("retCode") == 0:
                    df = pd.DataFrame(data["result"]["list"], 
                                    columns=["timestamp", "open", "high", "low", "close", "volume", "turnover"])
                    for col in ["open", "high", "low", "close", "volume"]:
                        df[col] = pd.to_numeric(df[col])
                    return df.sort_values("timestamp")
                return pd.DataFrame()

def analyze_signal(df):
    if len(df) < 30:
        return None
    close = df["close"]
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    current_rsi = rsi.iloc[-1]
    ema9 = close.ewm(span=9).mean().iloc[-1]
    ema21 = close.ewm(span=21).mean().iloc[-1]
    price = close.iloc[-1]
    
    signal = None
    confidence = 0
    
    if ema9 > ema21 and current_rsi > 35 and current_rsi < 60:
        signal = "LONG"
        confidence = 85 if current_rsi < 45 else 70
    elif ema9 < ema21 and current_rsi > 40 and current_rsi < 65:
        signal = "SHORT"
        confidence = 85 if current_rsi > 55 else 70
    
    if signal and confidence >= 70:
        atr = (df["high"] - df["low"]).rolling(14).mean().iloc[-1]
        if signal == "LONG":
            entry, sl, tp = price, price - (atr * 1.5), price + (atr * 2.5)
        else:
            entry, sl, tp = price, price + (atr * 1.5), price - (atr * 2.5)
        return {
            "signal": signal,
            "entry": round(entry, 4),
            "stop_loss": round(sl, 4),
            "take_profit": round(tp, 4),
            "confidence": confidence,
            "rsi": round(current_rsi, 1)
        }
    return None

class SignalBot:
    def __init__(self):
        self.bot = Bot(token=TELEGRAM_BOT_TOKEN)
        self.bybit = BybitClient()
        self.sent_signals = {}
        
    async def send_signal(self, symbol, timeframe, data):
        emoji = "🟢 LONG" if data["signal"] == "LONG" else "🔴 SHORT"
        risk = abs(data["entry"] - data["stop_loss"])
        reward = abs(data["take_profit"] - data["entry"])
        rr = round(reward / risk, 2) if risk > 0 else 0
        
        msg = f"""🔥 <b>BYBIT SIGNAL</b> 🔥

📊 <b>{symbol}</b> | {timeframe}m
📈 <b>{emoji}</b>

💰 Entry: <code>{data['entry']}</code>
🛑 Stop: <code>{data['stop_loss']}</code>
🎯 Target: <code>{data['take_profit']}</code>
📊 R:R = 1:{rr}

📉 RSI: {data['rsi']}
🎯 Confidence: {data['confidence']}%

⏱ Valid 4-8 hours | ⚠️ Manage risk!"""
        
        try:
            await self.bot.send_message(
                chat_id=TELEGRAM_CHANNEL_ID,
                text=msg,
                parse_mode=ParseMode.HTML
            )
            logging.info(f"✅ Signal sent: {symbol} {data['signal']}")
            self.sent_signals[f"{symbol}_{timeframe}_{data['signal']}"] = datetime.now()
        except Exception as e:
            logging.error(f"❌ Error: {e}")
    
    async def scan(self):
        logging.info("🔍 Scanning...")
        coins = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "PEPEUSDT", "FETUSDT", "WIFUSDT"]
        
        for coin in coins:
            for tf in ["60", "240"]:
                try:
                    df = await self.bybit.get_klines(coin, tf)
                    signal = analyze_signal(df)
                    
                    if signal:
                        key = f"{coin}_{tf}_{signal['signal']}"
                        if key in self.sent_signals and (datetime.now() - self.sent_signals[key]) < timedelta(hours=4):
                            continue
                        await self.send_signal(coin, tf, signal)
                except Exception as e:
                    logging.error(f"Error: {e}")
        logging.info("😴 Sleeping 5 minutes...")
    
    async def run(self):
        logging.info("🚀 BOT STARTED!")
        while True:
            await self.scan()
            await asyncio.sleep(300)

if __name__ == "__main__":
    bot = SignalBot()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logging.info("Stopped")
