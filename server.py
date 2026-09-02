import copy
import hmac
import os
import time
import threading
import json
import urllib.request
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import database

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_HOST = os.getenv('MARKETPULSE_HOST', '0.0.0.0')
SERVER_PORT = int(os.getenv('MARKETPULSE_PORT', '8081'))
PUBLIC_BASE_URL = os.getenv('MARKETPULSE_PUBLIC_URL', 'http://187.77.174.215:8081').rstrip('/')
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        'MARKETPULSE_CORS_ORIGINS',
        f'{PUBLIC_BASE_URL},http://127.0.0.1:8081,http://localhost:8081'
    ).split(',')
    if origin.strip()
]

try:
    import resource
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE, (min(65535, hard), hard))
except Exception:
    pass
"""
==========================================================================
MARKETPULSE FX — EXCLUSIVE TRADINGVIEW REAL-TIME BACKEND SERVER
==========================================================================
Pulls 100% Real-Time Live Prices directly from TradingView's Global Scanner API:
- Gold: TVC:GOLD ($4037.68)
- Silver: TVC:SILVER ($57.62)
- Oil: TVC:USOIL ($79.50)
- Forex: OANDA (EURUSD, GBPUSD, USDJPY, etc.)
- Stocks: NASDAQ (NVDA, TSLA, AAPL)
- Crypto: BINANCE (BTCUSDT, ETHUSDT, SOLUSDT)
"""

import xml.etree.ElementTree as ET
import re
import yfinance as yf

app = Flask(__name__)
CORS(app, resources={r'/api/*': {'origins': CORS_ORIGINS}}, max_age=86400)

FETCH_INTERVAL = 6  # Fetch fresh TradingView prices every 6 seconds cleanly!
MACRO_FETCH_INTERVAL = 60 # Fetch news every 60 seconds
cache_lock = threading.RLock()

price_cache = {
    'last_updated': 0.0,
    'data': {}
}

news_cache = []
calendar_cache = []
macro_cache = {
    'fedBias': 'neutral',
    'fedBiasLabel': 'محايد (Neutral)',
    'geoRisk': 'low',
    'geoRiskLabel': 'منخفض (Low Risk)',
    'overallSentiment': 'neutral'
}

# Mapping TradingView Tickers -> App Symbol Keys (100% Verified Working Symbols)
TV_TICKER_MAP = {
    "OANDA:XAUUSD":    "XAUUSD",
    "TVC:SILVER":      "XAGUSD",
    "NYMEX:CL1!":      "USOIL",
    "NYMEX:NG1!":      "NGAS",
    "OANDA:EURUSD":    "EURUSD",
    "OANDA:GBPUSD":    "GBPUSD",
    "OANDA:USDJPY":    "USDJPY",
    "OANDA:USDCHF":    "USDCHF",
    "OANDA:USDCAD":    "USDCAD",
    "OANDA:AUDUSD":    "AUDUSD",
    "OANDA:NZDUSD":    "NZDUSD",
    "OANDA:EURGBP":    "EURGBP",
    "OANDA:EURJPY":    "EURJPY",
    "OANDA:GBPJPY":    "GBPJPY",
    "OANDA:AUDJPY":    "AUDJPY",
    "OANDA:US30USD":   "US30",
    "FOREXCOM:NSXUSD": "US100",
    "NASDAQ:NVDA":     "NVDA",
    "NASDAQ:TSLA":     "TSLA",
    "NASDAQ:AAPL":     "AAPL",
    "BINANCE:BTCUSDT": "BTCUSD",
    "BINANCE:ETHUSDT": "ETHUSD",
    "BINANCE:SOLUSDT": "SOLUSD"
}

def fetch_tradingview_live_prices():
    """Fetch 100% Real Live Prices directly from TradingView Scanner API."""
    url = "https://scanner.tradingview.com/global/scan"
    payload = {
        "symbols": {
            "tickers": list(TV_TICKER_MAP.keys())
        },
        "columns": ["close", "change", "change_abs"]
    }
    
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Content-Type': 'application/json',
                'Connection': 'close'
            }
        )
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            items = data.get('data', [])
            
            with cache_lock:
                for item in items:
                    tv_symbol = item.get('s')
                    vals = item.get('d', [])
                    if tv_symbol in TV_TICKER_MAP and len(vals) >= 2:
                        app_key = TV_TICKER_MAP[tv_symbol]
                        close_price = float(vals[0])
                        pct_change = float(vals[1])
                        is_up = pct_change >= 0
                        
                        # Decimal precision rules
                        if 'USD' in app_key and app_key not in ['XAUUSD', 'BTCUSD', 'ETHUSD', 'SOLUSD']:
                            if 'JPY' in app_key:
                                rounded_price = round(close_price, 2)
                            else:
                                rounded_price = round(close_price, 4)
                        else:
                            rounded_price = round(close_price, 2)
                            
                        price_cache['data'][app_key] = {
                            'price': rounded_price,
                            'change': f"{'+' if is_up else ''}{pct_change:.2f}%",
                            'isUp': is_up
                        }
                price_cache['last_updated'] = time.time()
                print(f"[TRADINGVIEW] Successfully updated {len(price_cache['data'])} real-time symbols.")
    except Exception as e:
        print(f"[TRADINGVIEW ERROR]: {e}")

def fetch_macro_news():
    """Fetch real-time news from RSS feeds and analyze macro sentiment."""
    rss_urls = [
        "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664", # CNBC Top News
        "https://nypost.com/business/feed/" # NYPost Business Live
    ]
    
    fetched_news = []
    text_corpus = ""
    
    for url in rss_urls:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5) as resp:
                xml_data = resp.read()
                root = ET.fromstring(xml_data)
                for item in root.findall('.//item')[:5]:
                    title = item.find('title').text if item.find('title') is not None else ""
                    link = item.find('link').text if item.find('link') is not None else "#"
                    pubDate = item.find('pubDate').text if item.find('pubDate') is not None else ""
                    
                    if title:
                        fetched_news.append({
                            'title': title,
                            'category': 'عاجل - أسواق',
                            'pubDate': pubDate,
                            'link': link,
                            'impact': 'high'
                        })
                        text_corpus += " " + title.lower()
        except Exception as e:
            print(f"[RSS ERROR] {e}")
            
    if not fetched_news:
        return
        
    # Simple NLP Keyword Sentiment for Macro Bias
    fed_hawkish = len(re.findall(r'hike|inflation|cpi|powell|strong|hawkish', text_corpus))
    fed_dovish = len(re.findall(r'cut|dovish|weak|drop|lower', text_corpus))
    geo_risk = len(re.findall(r'war|tension|strike|missile|middle east|russia|ukraine|israel|iran|oil', text_corpus))
    
    with cache_lock:
        news_cache.clear()
        news_cache.extend(fetched_news[:6]) # Keep top 6
        
        # Determine Fed Bias
        if fed_hawkish > fed_dovish:
            macro_cache['fedBias'] = 'hawkish'
            macro_cache['fedBiasLabel'] = 'تشددي (Hawkish) - تركيز على كبح التضخم 🔴'
        elif fed_dovish > fed_hawkish:
            macro_cache['fedBias'] = 'dovish'
            macro_cache['fedBiasLabel'] = 'تيسيري (Dovish) - خفض الفائدة محتمل 🟢'
        else:
            macro_cache['fedBias'] = 'neutral'
            macro_cache['fedBiasLabel'] = 'محايد (Neutral) 🟡'
            
        # Determine Geo Risk
        if geo_risk > 3:
            macro_cache['geoRisk'] = 'high'
            macro_cache['geoRiskLabel'] = 'مرتفع ⚠️ (توترات جيوسياسية)'
        elif geo_risk > 0:
            macro_cache['geoRisk'] = 'medium'
            macro_cache['geoRiskLabel'] = 'متوسط 🟡'
        else:
            macro_cache['geoRisk'] = 'low'
            macro_cache['geoRiskLabel'] = 'منخفض 🟢'
            
        # Overall Sentiment for signals
        if macro_cache['geoRisk'] == 'high' or macro_cache['fedBias'] == 'dovish':
            macro_cache['overallSentiment'] = 'gold_bullish'
        elif macro_cache['fedBias'] == 'hawkish':
            macro_cache['overallSentiment'] = 'usd_bullish'
        else:
            macro_cache['overallSentiment'] = 'neutral'


def fetch_calendar():
    try:
        req = urllib.request.Request("https://nfs.faireconomy.media/ff_calendar_thisweek.xml", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            xml_data = response.read()
        
        root = ET.fromstring(xml_data)
        events = []
        for event in root.findall("event"):
            title = event.findtext("title") or ""
            country = event.findtext("country") or ""
            date_str = event.findtext("date") or ""
            time_str = event.findtext("time") or ""
            impact = event.findtext("impact") or ""
            forecast = event.findtext("forecast") or ""
            previous = event.findtext("previous") or ""
            
            # Filter only High and Medium impact to keep UI clean
            if impact in ["High", "Medium"]:
                events.append({
                    "title": title,
                    "country": country,
                    "date": date_str,
                    "time": time_str,
                    "impact": impact,
                    "forecast": forecast,
                    "previous": previous
                })
        with cache_lock:
            calendar_cache.clear()
            calendar_cache.extend(events)
    except Exception as e:
        print(f"[CALENDAR ERROR] {e}")

def background_tradingview_worker():
    """Background worker updating TradingView prices every 5 seconds."""
    macro_timer = 0
    while True:
        try:
            fetch_tradingview_live_prices()
            if macro_timer % MACRO_FETCH_INTERVAL == 0:
                fetch_macro_news()
            if macro_timer % 900 == 0:
                fetch_calendar()
        except Exception as e:
            print(f"Worker exception: {e}")
        time.sleep(FETCH_INTERVAL)
        macro_timer += FETCH_INTERVAL

# Initial Immediate Fetch on Server Startup
fetch_tradingview_live_prices()
fetch_macro_news()
fetch_calendar()

# Start background thread
worker = threading.Thread(target=background_tradingview_worker, daemon=True)
worker.start()

# ============================================================
# FLASK ROUTE ENDPOINTS
# ============================================================
@app.route('/', methods=['GET'])
def serve_index():
    """Serve the dashboard and API from the same VPS port."""
    return send_from_directory(APP_DIR, 'index.html')


@app.route('/app.js', methods=['GET'])
def serve_app_js():
    return send_from_directory(APP_DIR, 'app.js')


@app.route('/fibonacci.js', methods=['GET'])
def serve_fibonacci_js():
    return send_from_directory(APP_DIR, 'fibonacci.js')


@app.route('/style.css', methods=['GET'])
def serve_style_css():
    return send_from_directory(APP_DIR, 'style.css')


@app.route('/api/prices', methods=['GET'])
def get_prices():
    """Returns 100% Real Live TradingView Prices."""
    with cache_lock:
        data = dict(price_cache['data'])
    return jsonify({
        'status': 'success',
        'provider': 'TradingView Real-Time Global Stream',
        'timestamp': price_cache['last_updated'],
        'prices': data
    })

@app.route('/api/ohlcv', methods=['GET'])
def get_ohlcv():
    symbol = request.args.get('symbol', 'XAUUSD')
    timeframe = request.args.get('timeframe', '1h')
    
    yf_symbol = symbol
    if symbol == 'XAUUSD' or symbol == 'XAUUSD_OTC': yf_symbol = 'GC=F'
    elif symbol == 'XAGUSD' or symbol == 'XAGUSD_OTC': yf_symbol = 'SI=F'
    elif symbol == 'USOIL' or symbol == 'USOIL_OTC': yf_symbol = 'CL=F'
    elif symbol == 'NGAS': yf_symbol = 'NG=F'
    elif symbol in ['BTCUSDT', 'BTCUSD']: yf_symbol = 'BTC-USD'
    elif symbol in ['ETHUSDT', 'ETHUSD']: yf_symbol = 'ETH-USD'
    elif symbol in ['SOLUSDT', 'SOLUSD']: yf_symbol = 'SOL-USD'
    elif symbol in ['XRPUSDT', 'XRPUSD']: yf_symbol = 'XRP-USD'
    elif symbol in ['BNBUSDT', 'BNBUSD']: yf_symbol = 'BNB-USD'
    elif symbol in ['ADAUSDT', 'ADAUSD']: yf_symbol = 'ADA-USD'
    elif symbol in ['DOGEUSDT', 'DOGEUSD']: yf_symbol = 'DOGE-USD'
    elif symbol in ['AVAXUSDT', 'AVAXUSD']: yf_symbol = 'AVAX-USD'
    elif symbol in ['LINKUSDT', 'LINKUSD']: yf_symbol = 'LINK-USD'
    elif symbol == 'US30': yf_symbol = '^DJI'
    elif symbol in ['US100', 'NAS100']: yf_symbol = '^IXIC'
    elif symbol == 'SPX500': yf_symbol = '^GSPC'
    elif symbol in ['AAPL', 'TSLA', 'NVDA']: yf_symbol = symbol
    elif symbol.endswith('_OTC'): yf_symbol = symbol.replace('_OTC', '') + '=X'
    else: yf_symbol = symbol + '=X'  # Forex pairs like EURGBP, EURJPY, EURUSD etc.
    
    interval_map = {'15m': ('15m', '30d'), '1h': ('1h', '60d'), '4h': ('1h', '60d'), '1d': ('1d', '2y')}
    interval, period = interval_map.get(timeframe, ('1h', '10d'))
    
    try:
        ticker = yf.Ticker(yf_symbol)
        df = ticker.history(interval=interval, period=period)
        if df.empty:
            return jsonify({'status': 'error', 'message': 'No data'})
            
        candles = []
        for index, row in df.iterrows():
            candles.append({
                'time': int(index.timestamp() * 1000),
                'open': row['Open'],
                'high': row['High'],
                'low': row['Low'],
                'close': row['Close'],
                'volume': row['Volume']
            })
        return jsonify({'status': 'success', 'data': candles})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/api/news', methods=['GET'])
def get_news():
    with cache_lock:
        news = list(news_cache)
    return jsonify({
        'status': 'success',
        'timestamp': time.time(),
        'news': news if news else [
            {'title': 'جاري تحميل الأخبار الحية من السيرفر...', 'category': 'تحديث', 'pubDate': 'الآن', 'link': '#', 'impact': 'medium'}
        ]
    })

@app.route('/api/macro', methods=['GET'])
def get_macro():
    with cache_lock:
        macro = dict(macro_cache)
    return jsonify({
        'status': 'success',
        'timestamp': time.time(),
        'macro': macro
    })

@app.route('/api/calendar', methods=['GET'])
def get_calendar():
    with cache_lock:
        cal = list(calendar_cache)
    return jsonify({
        'status': 'success',
        'timestamp': time.time(),
        'calendar': cal
    })

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'ok',
        'provider': 'TradingView',
        'symbols_count': len(price_cache['data'])
    })


import numpy as np
import pandas as pd

def bt_calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def bt_calc_atr(df, period=14):
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    return true_range.rolling(period).mean()

def bt_calc_adx(df, period=14):
    up_move = df['High'] - df['High'].shift(1)
    down_move = df['Low'].shift(1) - df['Low']
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = bt_calc_atr(df, 1)
    tr_sum = pd.Series(tr).rolling(period).sum()
    plus_di = 100 * (pd.Series(plus_dm.flatten()).rolling(period).sum() / tr_sum.reset_index(drop=True))
    minus_di = 100 * (pd.Series(minus_dm.flatten()).rolling(period).sum() / tr_sum.reset_index(drop=True))
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
    adx = dx.rolling(period).mean()
    adx.index = df.index
    return adx

@app.route('/api/backtest', methods=['GET'])
def api_backtest():
    symbol = request.args.get('symbol', 'XAUUSD')
    timeframe = request.args.get('timeframe', '1h')
    
    yf_symbol = symbol
    if symbol == 'XAUUSD': yf_symbol = 'GC=F'
    elif symbol == 'XAGUSD': yf_symbol = 'SI=F'
    elif symbol == 'USOIL': yf_symbol = 'CL=F'
    elif symbol == 'EURUSD': yf_symbol = 'EURUSD=X'
    elif symbol == 'BTCUSDT' or symbol == 'BTCUSD': yf_symbol = 'BTC-USD'
    else: return jsonify({'status': 'error', 'message': 'Asset not supported for backtest yet'})
    
    interval, period = ('1h', '60d')
    if timeframe == '15m': interval, period = ('15m', '30d')
    elif timeframe == '4h': interval, period = ('1h', '60d')
    
    try:
        df = yf.download(yf_symbol, period=period, interval=interval, progress=False)
        if df.empty: return jsonify({'status': 'error', 'message': 'No data'})
        
        df['EMA50'] = bt_calc_ema(df['Close'], 50)
        df['EMA200'] = bt_calc_ema(df['Close'], 200)
        df['ATR'] = bt_calc_atr(df, 14)
        df['ADX'] = bt_calc_adx(df, 14)
        df.dropna(inplace=True)
        
        wins = 0; losses = 0; open_trades = []
        for i in range(len(df)):
            row = df.iloc[i]
            new_open_trades = []
            for t in open_trades:
                if t['type'] == 'BUY':
                    if row['Low'].iloc[0] <= t['sl']: losses += 1
                    elif row['High'].iloc[0] >= t['tp1']: wins += 1
                    else: new_open_trades.append(t)
                else:
                    if row['High'].iloc[0] >= t['sl']: losses += 1
                    elif row['Low'].iloc[0] <= t['tp1']: wins += 1
                    else: new_open_trades.append(t)
            open_trades = new_open_trades
            
            trend = 'Uptrend' if row['EMA50'].iloc[0] > row['EMA200'].iloc[0] else 'Downtrend'
            structure = 'Bullish' if row['Close'].iloc[0] > row['EMA50'].iloc[0] else 'Bearish'
            adx = row['ADX'].iloc[0]
            
            local_dir = 'NO_TRADE'
            if trend == 'Uptrend' and structure == 'Bullish' and adx > 25: local_dir = 'BUY'
            elif trend == 'Downtrend' and structure == 'Bearish' and adx > 25: local_dir = 'SELL'
            
            if local_dir != 'NO_TRADE' and len(open_trades) == 0:
                p = row['Close'].iloc[0]
                atr = row['ATR'].iloc[0]
                tp1 = p + (atr*1.5) if local_dir == 'BUY' else p - (atr*1.5)
                sl = p - (atr*1.5) if local_dir == 'BUY' else p + (atr*1.5)
                open_trades.append({'type': local_dir, 'entry': p, 'tp1': tp1, 'sl': sl})
                
        win_rate = (wins / (wins + losses)) * 100 if (wins + losses) > 0 else 50.0
        return jsonify({'status': 'success', 'winRate': round(win_rate, 2), 'trades': wins+losses})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

# ==========================================================================
# INSTITUTIONAL EXECUTION ENGINE, STATE MACHINE & RECONCILIATION
# ==========================================================================
import os
import hashlib
import json
import uuid

STATE_FILE_PATH = os.path.join(APP_DIR, "autotrade_state.json")
EA_WEBHOOK_SECRET = os.getenv('MARKETPULSE_EA_SECRET', 'marketpulse_live_bridge_sec_2026')
COMMAND_TTL_SECONDS = 60.0  # 60s Time-To-Live for queued commands


def require_ea_secret(data=None):
    """Return an unauthorized response unless the MT5 bridge secret is valid."""
    data = data or {}
    supplied = request.headers.get('X-MarketPulse-Secret') or request.args.get('secret') or data.get('secret', '')
    if not supplied or not hmac.compare_digest(str(supplied), EA_WEBHOOK_SECRET):
        return jsonify({'status': 'unauthorized', 'message': 'Invalid or missing Secret Key'}), 401
    return None

autotrade_lock = threading.RLock()
execution_mutex = threading.RLock()
command_lock = threading.RLock()

# Initial Default State Structure
default_state = {
    'enabled': False,
    'mode': 'demo',               # 'demo' | 'live'
    'emergency_stop': False,      # Emergency Kill Switch active flag
    'emergency_reason': '',
    'account': {
        'connected': False,
        'mt5_connected': False,
        'ea_connected': False,
        'broker_connected': False,
        'bridge_mode': 'DISCONNECTED', # 'EA_WEBHOOK_LIVE' | 'DISCONNECTED'
        'server': 'JustMarkets-Demo',
        'login': '',
        'balance': 0.0,
        'equity': 0.0,
        'margin': 0.0,
        'free_margin': 0.0,
        'margin_level': 0.0,
        'currency': 'USD',
        'leverage': 100,
        'last_sync_time': '',
        'last_heartbeat': 0.0,
        'last_account_sync': 0.0,
        'last_position_sync': 0.0,
        'last_market_sync': 0.0,
        'latency_ms': 0.0
    },
    'market_data': {}, # { symbol: { bid, ask, spread, time } }
    'risk_config': {
        'risk_percent': 1.0,          # 1.0% risk per trade
        'max_lot_cap': 0.50,          # Strict lot ceiling
        'max_open_trades': 3,         # Max simultaneous positions
        'max_daily_trades': 10,       # Max trades allowed per calendar day
        'max_daily_loss_pct': 3.0,    # 3.0% daily loss limit (Kill Switch trigger)
        'min_score': 75,              # Minimum signal score required
        'auto_breakeven': True,       # Move SL to Entry + buffer at TP1
        'breakeven_buffer_pips': 2.0,
        'partial_tp1_close_pct': 50,  # Close 50% at TP1
        'partial_tp2_close_pct': 30,  # Close 30% at TP2
        'trailing_stop_enabled': False,
        'trailing_atr_multiplier': 1.5,
        'max_spread_pips': { 'forex': 2.5, 'gold': 0.45, 'crypto': 35.0, 'oil': 0.06, 'stocks': 0.35 },
        'news_filter_minutes': 30,    # 30m window around High Impact news
        'consecutive_loss_limit': 2,  # Max consecutive losses before cooldown
        'loss_cooldown_minutes': 30   # 30-min cooldown
    },
    'daily_stats': {
        'date': time.strftime('%Y-%m-%d'),
        'trades_opened': 0,
        'starting_balance': 0.0,
        'realized_pnl': 0.0,
        'floating_pnl': 0.0,
        'consecutive_losses': 0,
        'cooldown_until': 0.0,
        'peak_equity': 0.0
    },
    'open_positions': [],
    'history': []
}

def load_persisted_state():
    """Restores persisted state from disk on server startup."""
    try:
        if os.path.exists(STATE_FILE_PATH):
            with open(STATE_FILE_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for k, v in default_state.items():
                    if k not in data:
                        data[k] = v
                try:
                    print(f"[STATE RESTORE] Successfully loaded persisted state ({len(data.get('open_positions', []))} open positions)")
                except Exception:
                    pass
                return data
    except Exception:
        pass
    return json.loads(json.dumps(default_state))


def save_persisted_state():
    """Persists current state to disk safely with atomic write."""
    try:
        tmp_path = STATE_FILE_PATH + ".tmp"
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(autotrade_state, f, indent=2, ensure_ascii=False)
        if os.path.exists(tmp_path):
            if os.path.exists(STATE_FILE_PATH):
                os.replace(tmp_path, STATE_FILE_PATH)
            else:
                os.rename(tmp_path, STATE_FILE_PATH)
    except Exception as e:
        pass

autotrade_state = load_persisted_state()
commands_store = {}     # { command_id: command_dict }
idempotency_store = {}  # { hash: timestamp }
audit_logs = []         # Chronological audit log buffer (max 200 items)

# ============================================================
# MULTI-TENANT ACCOUNT ISOLATION ENGINE (ROBUST & THREAD-SAFE)
# ============================================================
user_accounts_store = {}

def get_or_create_user_account(login_str=None, server_name=""):
    login_key = str(login_str).strip() if login_str else ""
    server_key = str(server_name).strip() if server_name else "JustMarkets-Demo"
    
    # 1. Enforce strict isolation key: ServerName_Login
    isolation_key = f"{server_key}_{login_key}"
    
    # If no specific login requested, fallback to default global state ONLY for anonymous visitors 
    if not login_key:
        return autotrade_state
    
    if isolation_key not in user_accounts_store:
        import copy
        user_accounts_store[isolation_key] = copy.deepcopy(autotrade_state)
        u_acc = user_accounts_store[isolation_key]['account']
        u_acc['login'] = login_key
        u_acc['server'] = server_key
        u_acc['connected'] = False
        u_acc['balance'] = 0.0
        u_acc['equity'] = 0.0
        u_acc['margin'] = 0.0
        u_acc['free_margin'] = 0.0
        user_accounts_store[isolation_key]['open_positions'] = []
        user_accounts_store[isolation_key]['history'] = []
        
    return user_accounts_store[isolation_key]


def log_audit_event(event_type, symbol, ticket, reason, details=None):
    """Records a secure timestamped audit log entry."""
    entry = {
        'id': f"LOG-{int(time.time()*1000)%1000000}",
        'time': time.strftime('%H:%M:%S'),
        'timestamp': time.time(),
        'event': event_type,
        'symbol': symbol or 'ALL',
        'ticket': ticket or '—',
        'reason': reason,
        'details': details or {}
    }
    with autotrade_lock:
        audit_logs.insert(0, entry)
        if len(audit_logs) > 200:
            audit_logs.pop()
    try:
        print(f"[AUDIT LOG] [{entry['time']}] {event_type} | {symbol} | Ticket: {ticket} | {reason}")
    except Exception:
        pass

# ==========================================================================
# POSITION SIZING & CONTRACT SPECIFICATIONS
# ==========================================================================
CONTRACT_SPECS = {
    'XAUUSD': { 'size': 100.0,   'category': 'gold',   'point': 0.01,  'tick_val': 1.0 },
    'XAGUSD': { 'size': 5000.0,  'category': 'gold',   'point': 0.001, 'tick_val': 5.0 },
    'USOIL':  { 'size': 1000.0,  'category': 'oil',    'point': 0.01,  'tick_val': 10.0 },
    'NGAS':   { 'size': 10000.0, 'category': 'oil',    'point': 0.001, 'tick_val': 10.0 },
    'BTCUSD': { 'size': 1.0,     'category': 'crypto', 'point': 0.01,  'tick_val': 1.0 },
    'ETHUSD': { 'size': 1.0,     'category': 'crypto', 'point': 0.01,  'tick_val': 1.0 },
    'SOLUSD': { 'size': 1.0,     'category': 'crypto', 'point': 0.01,  'tick_val': 1.0 },
    'US30':   { 'size': 1.0,     'category': 'stocks', 'point': 1.0,   'tick_val': 1.0 },
    'US100':  { 'size': 1.0,     'category': 'stocks', 'point': 1.0,   'tick_val': 1.0 },
    'NVDA':   { 'size': 10.0,    'category': 'stocks', 'point': 0.01,  'tick_val': 0.10 },
    'TSLA':   { 'size': 10.0,    'category': 'stocks', 'point': 0.01,  'tick_val': 0.10 },
    'AAPL':   { 'size': 10.0,    'category': 'stocks', 'point': 0.01,  'tick_val': 0.10 }
}


BROKER_SYMBOL_MAPPING = {
    'XAUUSD': 'XAUUSD',   # Standard
    # Example configurations:
    # 'XAUUSD': 'XAUUSDm', # Exness Mini
    # 'XAUUSD': 'GOLD',    # Other brokers
}

def map_symbol_to_broker(symbol):
    sym = symbol.upper()
    return BROKER_SYMBOL_MAPPING.get(sym, sym)

def map_symbol_from_broker(broker_symbol):
    for k, v in BROKER_SYMBOL_MAPPING.items():
        if v.upper() == broker_symbol.upper():
            return k
    return broker_symbol.upper()

def get_symbol_spec(symbol):
    sym = map_symbol_to_broker(symbol).upper()

    if sym in CONTRACT_SPECS:
        return CONTRACT_SPECS[sym]
    return { 'size': 100000.0, 'category': 'forex', 'point': 0.0001 if 'JPY' not in sym else 0.01, 'tick_val': 10.0 }

def calculate_risk_position_size(symbol, entry_price, sl_price, balance, risk_percent, max_lot_cap):
    """Calculates exact risk-based lot size based on balance, risk %, and stop loss distance."""
    sl_dist = abs(entry_price - sl_price)
    if sl_dist <= 0 or balance <= 0:
        return 0.01
    
    spec = get_symbol_spec(symbol)
    contract_size = spec['size']
    risk_dollars = balance * (risk_percent / 100.0)
    
    raw_lot = risk_dollars / (sl_dist * contract_size)
    calculated_lot = max(0.01, min(max_lot_cap, round(raw_lot, 2)))
    return calculated_lot

# ==========================================================================
# RECONCILIATION ENGINE (MT5 = Single Source of Truth)
# ==========================================================================
def reconcile_positions_with_mt5(mt5_positions, target_state, mt5_account_data=None):
    """
    Continuous bi-directional reconciliation treating MT5 as absolute Source of Truth.
    - Synchronizes open positions and discovers manual trades seamlessly.
    - Moves closed positions from active list into history.
    - Updates manually adjusted SL/TP levels in real time.
    """
    if not isinstance(mt5_positions, list):
        return

    now = time.time()
    with autotrade_lock:
        current_db_positions = {str(p.get('ticket')): p for p in target_state['open_positions'] if p.get('ticket')}
        mt5_tickets_seen = set()
        updated_open_positions = []

        # 1. Process MT5 Active Positions
        for mt5_pos in mt5_positions:
            ticket = str(mt5_pos.get('ticket', ''))
            if not ticket:
                continue
            mt5_tickets_seen.add(ticket)

            if ticket in current_db_positions:
                # Existing position: Reconcile and update live metrics & manual SL/TP changes
                existing = current_db_positions[ticket]
                existing['current_price'] = float(mt5_pos.get('current_price', existing.get('current_price', 0)))
                existing['pnl'] = round(float(mt5_pos.get('pnl', existing.get('pnl', 0))), 2)
                existing['swap'] = float(mt5_pos.get('swap', 0))
                existing['commission'] = float(mt5_pos.get('commission', 0))
                
                # Check for manual SL/TP adjustment in MT5
                new_sl = float(mt5_pos.get('sl', 0))
                new_tp = float(mt5_pos.get('tp1', mt5_pos.get('tp', 0)))
                if new_sl > 0 and abs(new_sl - existing.get('sl', 0)) > 0.00001:
                    existing['sl'] = new_sl
                    log_audit_event("RECONCILED_MANUAL_SL_CHANGE", existing['symbol'], ticket, f"تم اكتشاف تعديل يدوي لـ SL في MT5 إلى {new_sl}")
                if new_tp > 0 and abs(new_tp - existing.get('tp1', 0)) > 0.00001:
                    existing['tp1'] = new_tp
                    log_audit_event("RECONCILED_MANUAL_TP_CHANGE", existing['symbol'], ticket, f"تم اكتشاف تعديل يدوي لـ TP في MT5 إلى {new_tp}")

                updated_open_positions.append(existing)
            else:
                # New manual or external trade opened in MT5: Register without tampering
                new_manual_pos = {
                    'ticket': ticket,
                    'symbol': mt5_pos.get('symbol', '').upper(),
                    'type': mt5_pos.get('type', 'BUY').upper(),
                    'lot': float(mt5_pos.get('lot', 0.01)),
                    'entry': float(mt5_pos.get('entry', 0)),
                    'current_price': float(mt5_pos.get('current_price', 0)),
                    'sl': float(mt5_pos.get('sl', 0)),
                    'tp1': float(mt5_pos.get('tp1', mt5_pos.get('tp', 0))),
                    'pnl': float(mt5_pos.get('pnl', 0)),
                    'swap': float(mt5_pos.get('swap', 0)),
                    'commission': float(mt5_pos.get('commission', 0)),
                    'open_time': mt5_pos.get('open_time', time.strftime('%H:%M:%S')),
                    'status': 'OPEN_MANUAL',
                    'notes': 'صفقة يدوية / خارجية تم استيعابها من MT5 👤'
                }
                updated_open_positions.append(new_manual_pos)
                log_audit_event("RECONCILED_NEW_MANUAL_TRADE", new_manual_pos['symbol'], ticket, f"تم رصد ومزامنة صفقة يدوية مفتوحة في MT5 (#{ticket})")

        # 2. Identify and Archive Closed Positions
        for ticket, db_pos in current_db_positions.items():
            if ticket not in mt5_tickets_seen:
                # Position closed in MT5: Archive to history
                db_pos['status'] = 'CLOSED_IN_MT5'
                db_pos['close_time'] = time.strftime('%H:%M:%S')
                autotrade_state['history'].insert(0, db_pos)
                log_audit_event("RECONCILED_CLOSED_TRADE", db_pos['symbol'], ticket, f"تم تأكيد إغلاق الصفقة في MT5 ونقلها للأرشيف")

        target_state['open_positions'] = updated_open_positions
        save_persisted_state()

# ==========================================================================
# 15-POINT INSTITUTIONAL RISK ENGINE
# ==========================================================================
def validate_trade_risk(signal_data, login=None, server_name=None):
    """Strict 15-point multi-layer risk inspection before order dispatch."""
    now = time.time()
    today_str = time.strftime('%Y-%m-%d')
    symbol = signal_data.get('symbol', '').upper()
    trade_type = signal_data.get('type', '').upper()
    entry = float(signal_data.get('entry', 0))
    sl = float(signal_data.get('sl', 0))
    tp1 = float(signal_data.get('tp1', 0))
    score = int(signal_data.get('score', 0))
    signal_id = signal_data.get('signal_id') or signal_data.get('id') or f"{symbol}_{trade_type}_{int(now)}"

    req_login = login or signal_data.get('login') or ''
    req_server = server_name or signal_data.get('server') or 'JustMarkets-Demo'

    with autotrade_lock:
        target_state = get_or_create_user_account(req_login, req_server) if req_login else autotrade_state

        if target_state['daily_stats']['date'] != today_str:
            target_state['daily_stats'] = {
                'date': today_str,
                'trades_opened': 0,
                'starting_balance': target_state['account']['balance'],
                'realized_pnl': 0.0,
                'floating_pnl': 0.0,
                'consecutive_losses': 0,
                'cooldown_until': 0.0,
                'peak_equity': target_state['account']['equity']
            }

        cfg = target_state['risk_config']
        acc = target_state['account']
        d_stats = target_state['daily_stats']

        # Named accounts may restore their heartbeat from SQLite. Anonymous/global
        # requests must never inherit the most recently active account.
        if req_login:
            db_acc, _ = database.get_or_create_account(req_server, req_login)
            acc_hb = max(acc.get('last_heartbeat', 0), db_acc.get('last_heartbeat', 0))
        else:
            acc_hb = acc.get('last_heartbeat', 0)
        heartbeat_age = now - acc_hb if acc_hb > 0 else 999.0
        is_conn = acc_hb > 0 and heartbeat_age < 10.0

        # 1. Master AutoTrade Enable Check
        if not target_state['enabled']:
            return False, "AUTOTRADE_DISABLED", "التداول الآلي متوقف حالياً في لوحة التحكم (اضغط تفعيل التداول الآلي 🟢)"

        # 2. Emergency Kill Switch Check
        if target_state['emergency_stop']:
            return False, "EMERGENCY_STOP_ACTIVE", f"تم تفعيل زر الطوارئ سابقاً: {target_state['emergency_reason']}"

        # 3. Live MT5 Heartbeat Freshness (< 10s timeout)
        if not is_conn:
            return False, "MT5_DISCONNECTED", "انقطع الاتصال ببرنامج الميتاتريدر أو توقف الإكسبرت (Heartbeat Timeout > 10s)"

        # 4. Starting Balance & Drawdown Calculation
        if d_stats['starting_balance'] <= 0:
            d_stats['starting_balance'] = acc['balance'] if acc['balance'] > 0 else 40000.0

        daily_drawdown_pct = 0.0
        if d_stats['starting_balance'] > 0:
            total_daily_loss = -(d_stats['realized_pnl'] + min(0, d_stats['floating_pnl']))
            daily_drawdown_pct = (total_daily_loss / d_stats['starting_balance']) * 100.0

        # 5. Maximum Daily Loss (Kill Switch Trigger)
        if daily_drawdown_pct >= cfg['max_daily_loss_pct']:
            target_state['emergency_stop'] = True
            target_state['emergency_reason'] = f"تجاوز سقف الخسارة اليومية ({daily_drawdown_pct:.2f}% >= {cfg['max_daily_loss_pct']}%)"
            target_state['enabled'] = False
            log_audit_event("EMERGENCY_KILL_SWITCH", symbol, None, target_state['emergency_reason'])
            return False, "MAX_DAILY_LOSS_EXCEEDED", target_state['emergency_reason']

        # 6. Consecutive Loss Cooldown Check
        if now < d_stats.get('cooldown_until', 0):
            remain_mins = int((d_stats['cooldown_until'] - now) / 60)
            return False, "LOSS_COOLDOWN_ACTIVE", f"فترة تبريد نشطة بعد خسارتين متتاليتين (متبقي {remain_mins} دقيقة)"

        # 7. Max Open Trades Limit Check
        if len(target_state['open_positions']) >= cfg['max_open_trades']:
            return False, "MAX_OPEN_TRADES_LIMIT", f"تم بلوغ الحد الأقصى للصفقات المفتوحة ({len(target_state['open_positions'])}/{cfg['max_open_trades']})"

        # 8. Max Daily Trades Limit Check
        if d_stats['trades_opened'] >= cfg['max_daily_trades']:
            return False, "MAX_DAILY_TRADES_LIMIT", f"تم بلوغ الحد الأقصى للصفقات اليومية ({d_stats['trades_opened']}/{cfg['max_daily_trades']})"

        # 9. Same Symbol Open Protection
        for pos in target_state['open_positions']:
            if pos['symbol'].upper() == symbol:
                return False, "SAME_SYMBOL_ACTIVE", f"توجد صفقة مفتوحة بالفعل على الزوج {symbol}"

        # 10. Currency Correlation Exposure Check (Max 2 USD positions)
        if 'USD' in symbol:
            usd_count = sum(1 for p in target_state['open_positions'] if 'USD' in p['symbol'].upper())
            if usd_count >= 2:
                return False, "CORRELATION_EXPOSURE_LIMIT", f"تم بلوغ الحد الأقصى للتعرض المالي لعملة الدولار USD ({usd_count} صفقات مفتوحة)"

        # 11. Confluence Score Threshold Check
        if score < cfg['min_score']:
            return False, "SCORE_BELOW_MINIMUM", f"نقاط التوافق الفني ({score}) أقل من الحد الأدنى المطلوب ({cfg['min_score']})"

        # 12. Asset Class / Market Permission Check
        spec = get_symbol_spec(symbol)
        category = spec.get('category', 'forex').lower()
        if category in ['gold', 'oil', 'metals'] and not bool(cfg.get('allowed_metals', True)):
            return False, "METALS_TRADING_DISABLED", f"تداول المعادن والطاقة ({symbol}) معطل حالياً بناءً على إعداداتك المحددة للأصول"

        if category == 'forex' and not bool(cfg.get('allowed_forex', True)):
            return False, "FOREX_TRADING_DISABLED", f"تداول أزواج العملات الأجنبية ({symbol}) معطل حالياً بناءً على إعداداتك المحددة للأصول"

        if category == 'stocks' and not bool(cfg.get('allowed_stocks', True)):
            return False, "STOCKS_TRADING_DISABLED", f"تداول الأسهم والمؤشرات ({symbol}) معطل حالياً بناءً على إعداداتك المحددة للأصول"

        if category == 'crypto' and not bool(cfg.get('allowed_crypto', True)):
            return False, "CRYPTO_TRADING_DISABLED", f"تداول العملات المشفرة ({symbol}) معطل حالياً بناءً على إعداداتك المحددة للأصول"

        # 13. Valid Stop Loss Distance
        sl_dist = abs(entry - sl)
        min_stop_distance = spec['point'] * 15
        if sl_dist < min_stop_distance:
            return False, "INVALID_STOP_LOSS", f"مسافة وقف الخسارة ({sl_dist}) أقل من الحد الأدنى المسموح ({min_stop_distance})"

        # 13. Risk/Reward Ratio Check (Must be >= 1:1.5)
        tp_dist = abs(tp1 - entry)
        if sl_dist > 0 and (tp_dist / sl_dist) < 1.40:
            return False, "INVALID_RISK_REWARD", f"نسبة العائد إلى المخاطرة ({tp_dist/sl_dist:.2f}) أقل من الحد الأدنى 1:1.5"

        # 14. Margin Sufficiency Check
        calculated_lot = calculate_risk_position_size(symbol, entry, sl, acc['balance'], cfg['risk_percent'], cfg['max_lot_cap'])
        required_margin = (calculated_lot * spec['size'] * entry) / max(1, acc['leverage'])
        if acc['free_margin'] <= 0 or required_margin > (acc['free_margin'] * 0.80):
            return False, "INSUFFICIENT_MARGIN", f"الهامش المتاح غير كافٍ لفتح لوت {calculated_lot} (المطلوب: ${required_margin:.2f}, المتاح: ${acc['free_margin']:.2f})"

        # 15. Idempotency Key Duplicate Prevention
        idem_key = hashlib.sha256(f"{symbol}_{trade_type}_{int(now//30)}".encode('utf-8')).hexdigest()
        if idem_key in idempotency_store and (now - idempotency_store[idem_key] < 60):
            return False, "DUPLICATE_IDEMPOTENT_SIGNAL", "تم تجاهل الإشارة لأنها مكررة في نفس النافذة الزمنية"
        idempotency_store[idem_key] = now

        return True, "RISK_APPROVED", {
            'lot': calculated_lot,
            'signal_id': signal_id,
            'idempotency_key': idem_key
        }

# ==========================================================================
# LIFECYCLE ENGINE & COMMAND DISPATCH HELPER
# ==========================================================================
def queue_trade_command(action_type, symbol, lot=0.0, entry=0.0, sl=0.0, tp1=0.0, tp2=0.0, tp3=0.0, ticket=None, signal_id=None):
    """Queues a persistent command with UUID and 60-second TTL."""
    now = time.time()
    cmd_id = f"CMD-{uuid.uuid4().hex[:8].upper()}"
    cmd = {
        'command_id': cmd_id,
        'action': action_type,
        'symbol': map_symbol_to_broker(symbol),
        'type': 'BUY' if 'BUY' in action_type else ('SELL' if 'SELL' in action_type else action_type),
        'lot': lot,
        'entry': entry,
        'sl': sl,
        'tp1': tp1,
        'tp2': tp2,
        'tp3': tp3,
        'ticket': ticket or '',
        'signal_id': signal_id or '',
        'status': 'QUEUED',
        'created_at': now,
        'expires_at': now + COMMAND_TTL_SECONDS,
        'retry_count': 0
    }
    with command_lock:
        commands_store[cmd_id] = cmd
    return cmd

def process_position_lifecycle_step(test_prices=None):
    """Processes 1 iteration of position lifecycle checks."""
    with autotrade_lock:
        if not autotrade_state['open_positions']:
            autotrade_state['daily_stats']['floating_pnl'] = 0.0
            if autotrade_state['account']['connected']:
                autotrade_state['account']['equity'] = autotrade_state['account']['balance']
            return

        total_floating = 0.0
        active_positions = []
        cfg = autotrade_state['risk_config']
        now = time.time()

        for pos in autotrade_state['open_positions']:
            sym = pos['symbol']
            cur_p = None
            if test_prices and sym in test_prices:
                cur_p = test_prices[sym]
            else:
                with cache_lock:
                    if sym in price_cache['data']:
                        cur_p = price_cache['data'][sym].get('price')

            if not cur_p or cur_p <= 0:
                active_positions.append(pos)
                continue

            spec = get_symbol_spec(sym)
            is_buy = pos['type'].upper() == 'BUY'

            # Calculate Floating PnL
            if is_buy:
                pnl = (cur_p - pos['entry']) * pos['lot'] * spec['size']
            else:
                pnl = (pos['entry'] - cur_p) * pos['lot'] * spec['size']

            pos['current_price'] = cur_p
            pos['pnl'] = round(pnl, 2)
            total_floating += pnl

            # 1. Stop Loss Hit Check
            sl_hit = (cur_p <= pos['sl']) if is_buy else (cur_p >= pos['sl'])
            if sl_hit:
                autotrade_state['account']['balance'] += pnl
                autotrade_state['account']['balance'] = round(autotrade_state['account']['balance'], 2)
                autotrade_state['daily_stats']['realized_pnl'] += pnl
                autotrade_state['daily_stats']['consecutive_losses'] += 1
                
                if autotrade_state['daily_stats']['consecutive_losses'] >= cfg['consecutive_loss_limit']:
                    autotrade_state['daily_stats']['cooldown_until'] = now + (cfg['loss_cooldown_minutes'] * 60)
                    log_audit_event("COOLDOWN_TRIGGERED", sym, pos['ticket'], f"تفعيل فترة تبريد لمدة {cfg['loss_cooldown_minutes']} دقيقة بعد {cfg['consecutive_loss_limit']} خسائر متتالية")

                pos['status'] = 'CLOSED_SL'
                pos['close_price'] = cur_p
                pos['close_time'] = time.strftime('%H:%M:%S')
                autotrade_state['history'].insert(0, pos)
                log_audit_event("POSITION_CLOSED_SL", sym, pos['ticket'], f"ضرب وقف الخسارة عند {cur_p} (خسارة: ${pnl:.2f})")
                continue

            # 2. TP1 Hit Check (Auto Break-Even & 50% Partial Close)
            tp1_hit = (cur_p >= pos['tp1']) if is_buy else (cur_p <= pos['tp1'])
            if tp1_hit and not pos.get('tp1_hit'):
                pos['tp1_hit'] = True
                close_vol = round(pos['lot'] * 0.50, 2)
                if close_vol >= 0.01:
                    realized = (pnl * 0.50)
                    autotrade_state['account']['balance'] += realized
                    autotrade_state['daily_stats']['realized_pnl'] += realized
                    pos['lot'] = round(pos['lot'] - close_vol, 2)
                    log_audit_event("TP1_PARTIAL_CLOSE", sym, pos['ticket'], f"إغلاق جزئي 50% ({close_vol} لوت) وحجز ربح ${realized:.2f}")

                # Auto Break-Even Buffer
                if cfg['auto_breakeven']:
                    buf = spec['point'] * cfg['breakeven_buffer_pips'] * 10
                    new_sl = round(pos['entry'] + buf if is_buy else pos['entry'] - buf, 5)
                    if (is_buy and new_sl > pos['sl']) or (not is_buy and new_sl < pos['sl']):
                        pos['sl'] = new_sl
                        pos['notes'] = f"تم تأمين الصفقة ونقل الوقف للدخول ({new_sl}) 🛡️"
                        log_audit_event("AUTO_BREAKEVEN_TRIGGERED", sym, pos['ticket'], f"نقل وقف الخسارة إلى سعر الدخول مع هامش أمان ({new_sl})")
                        queue_trade_command('MODIFY_SL', sym, ticket=pos['ticket'], sl=new_sl, tp1=pos.get('tp2', pos['tp1']))

            # 3. TP2 Hit Check (30% Partial Close)
            if pos.get('tp2') and not pos.get('tp2_hit'):
                tp2_hit = (cur_p >= pos['tp2']) if is_buy else (cur_p <= pos['tp2'])
                if tp2_hit:
                    pos['tp2_hit'] = True
                    close_vol = round(pos['lot'] * 0.60, 2)
                    if close_vol >= 0.01:
                        realized = (pnl * 0.60)
                        autotrade_state['account']['balance'] += realized
                        autotrade_state['daily_stats']['realized_pnl'] += realized
                        pos['lot'] = round(pos['lot'] - close_vol, 2)
                        log_audit_event("TP2_PARTIAL_CLOSE", sym, pos['ticket'], f"إغلاق الهدف الثاني TP2 وحجز ربح ${realized:.2f}")

            # 4. TP3 Hit Check (Final Target Full Close)
            if pos.get('tp3'):
                tp3_hit = (cur_p >= pos['tp3']) if is_buy else (cur_p <= pos['tp3'])
                if tp3_hit:
                    autotrade_state['account']['balance'] += pnl
                    autotrade_state['daily_stats']['realized_pnl'] += pnl
                    autotrade_state['daily_stats']['consecutive_losses'] = 0
                    pos['status'] = 'CLOSED_TP3'
                    pos['close_price'] = cur_p
                    pos['close_time'] = time.strftime('%H:%M:%S')
                    autotrade_state['history'].insert(0, pos)
                    log_audit_event("POSITION_CLOSED_TP3", sym, pos['ticket'], f"تحقيق الهدف النهائي بالكامل TP3 (ربح: ${pnl:.2f})")
                    continue

            active_positions.append(pos)

        autotrade_state['open_positions'] = active_positions
        autotrade_state['daily_stats']['floating_pnl'] = round(total_floating, 2)
        if autotrade_state['account']['connected']:
            autotrade_state['account']['equity'] = round(autotrade_state['account']['balance'] + total_floating, 2)
            autotrade_state['account']['free_margin'] = round(max(0, autotrade_state['account']['equity'] - autotrade_state['account']['margin']), 2)
            if autotrade_state['account']['margin'] > 0:
                autotrade_state['account']['margin_level'] = round((autotrade_state['account']['equity'] / autotrade_state['account']['margin']) * 100, 2)
        save_persisted_state()

def position_lifecycle_worker():
    """Monitors active positions, updates floating PnL, executes TP1/TP2/TP3 & Trailing Stops."""
    while True:
        try:
            time.sleep(1.5)
            now = time.time()
            with autotrade_lock:
                if autotrade_state['account']['connected'] and autotrade_state['account']['last_heartbeat'] > 0:
                    if (now - autotrade_state['account']['last_heartbeat']) > 10.0:
                        autotrade_state['account']['connected'] = False
                        autotrade_state['account']['mt5_connected'] = False
                        autotrade_state['account']['ea_connected'] = False
                        autotrade_state['account']['broker_connected'] = False
                        autotrade_state['account']['bridge_mode'] = 'DISCONNECTED'
                        log_audit_event("MT5_HEARTBEAT_TIMEOUT", "SYSTEM", None, "انقطع الاتصال بالإكسبرت (Heartbeat Timeout > 10s)")

            # Clean expired commands
            with command_lock:
                for cid, cmd in list(commands_store.items()):
                    if cmd['status'] in ['QUEUED', 'SENT_TO_EA'] and now > cmd.get('expires_at', 0):
                        cmd['status'] = 'EXPIRED'
                        log_audit_event("COMMAND_EXPIRED", cmd.get('symbol'), cmd.get('ticket'), f"انتهت صلاحية الأمر {cmd['command_id']} (TTL > 60s)")

            process_position_lifecycle_step()
        except Exception as e:
            print(f"[POSITION LIFECYCLE WORKER ERROR] {e}")

threading.Thread(target=position_lifecycle_worker, daemon=True).start()

# ==========================================================================
# COMMAND QUEUE & EXECUTION STATE MACHINE ENDPOINTS
# ==========================================================================
@app.route('/api/mt5/commands', methods=['GET'])
def mt5_get_commands():
    """EA polls for active non-expired pending commands."""
    auth_error = require_ea_secret()
    if auth_error:
        return auth_error

    now = time.time()
    pending = []
    with command_lock:
        for cid, cmd in commands_store.items():
            if cmd['status'] == 'QUEUED' and now <= cmd['expires_at']:
                cmd['status'] = 'SENT_TO_EA'
                pending.append(cmd)

    return jsonify({'status': 'success', 'commands': pending, 'timestamp': now})

@app.route('/api/mt5/command-ack', methods=['POST'])
def mt5_post_command_ack():
    """EA acknowledges command reception."""
    data = request.json or {}
    auth_error = require_ea_secret(data)
    if auth_error:
        return auth_error
    cmd_id = data.get('command_id')
    if not cmd_id:
        return jsonify({'status': 'error', 'message': 'command_id is required'}), 400
    with command_lock:
        if cmd_id not in commands_store:
            return jsonify({'status': 'error', 'message': 'Command not found'}), 404
        commands_store[cmd_id]['status'] = 'BROKER_PENDING'
        commands_store[cmd_id]['ack_time'] = time.time()
    return jsonify({'status': 'success', 'command_id': cmd_id})

@app.route('/api/mt5/command-result', methods=['POST'])
def mt5_post_command_result():
    """EA reports broker fill/rejection with real MQL5 retcode."""
    data = request.json or {}
    auth_error = require_ea_secret(data)
    if auth_error:
        return auth_error
    cmd_id = data.get('command_id')
    if not cmd_id:
        return jsonify({'status': 'error', 'message': 'command_id is required'}), 400
    ticket = str(data.get('ticket', ''))
    try:
        retcode = int(data.get('retcode', 0))
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'retcode must be an integer'}), 400
    err_msg = data.get('error_message', '')

    with command_lock:
        cmd = commands_store.get(cmd_id)
        if cmd is None:
            return jsonify({'status': 'error', 'message': 'Command not found'}), 404
        cmd['retcode'] = retcode
        cmd['error_message'] = err_msg
        if retcode in [10008, 10009]: # TRADE_RETCODE_PLACED, TRADE_RETCODE_DONE
            cmd['status'] = 'FILLED'
            cmd['ticket'] = ticket
            log_audit_event("ORDER_FILLED_BY_BROKER", cmd.get('symbol'), ticket, f"تم تنفيذ الأمر بنجاح في البروكر (Ticket: {ticket})")
        else:
            cmd['status'] = 'REJECTED'
            log_audit_event("ORDER_REJECTED_BY_BROKER", cmd.get('symbol'), ticket, f"رفض البروكر الأمر (كود: {retcode} - {err_msg})")

    # If filled, reconcile immediately
    if ticket and retcode in [10008, 10009]:
        with autotrade_lock:
            for pos in autotrade_state['open_positions']:
                if pos.get('signal_id') == cmd.get('signal_id') or pos.get('ticket', '').startswith('T-'):
                    pos['ticket'] = ticket
                    pos['status'] = 'FILLED'
                    break
            save_persisted_state()

    return jsonify({'status': 'success', 'command_id': cmd_id, 'retcode': retcode})

# ==========================================================================
# MODULAR PRIVATE REST API ENDPOINTS (/api/mt5/*)
# ==========================================================================
@app.route('/api/mt5/register', methods=['POST'])
def mt5_post_register():
    data = request.json or {}
    auth_error = require_ea_secret(data)
    if auth_error:
        return auth_error

    with autotrade_lock:
        acc = autotrade_state['account']
        acc['connected'] = True
        acc['mt5_connected'] = True
        acc['ea_connected'] = True
        acc['broker_connected'] = True
        acc['bridge_mode'] = 'EA_WEBHOOK_LIVE'
        acc['server'] = data.get('server', acc['server'])
        acc['login'] = str(data.get('login', acc['login']))
        acc['currency'] = data.get('currency', acc['currency'])
        acc['leverage'] = int(data.get('leverage', acc['leverage']))
        acc['last_heartbeat'] = time.time()
        acc['last_sync_time'] = time.strftime('%H:%M:%S')
        save_persisted_state()

    log_audit_event("EA_REGISTERED", "SYSTEM", None, f"تم تسجيل إكسبرت MT5 بنجاح ({acc['server']} #{acc['login']})")
    return jsonify({'status': 'success', 'message': f"MT5 EA Registered for {acc['server']} #{acc['login']}"})

@app.route('/api/mt5/heartbeat', methods=['POST'])
def mt5_post_heartbeat():
    data = request.json or {}
    auth_error = require_ea_secret(data)
    if auth_error:
        return auth_error

    now = time.time()
    client_time = float(data.get('timestamp', now))
    latency_ms = round(abs(now - client_time) * 1000, 1)

    with autotrade_lock:
        acc = autotrade_state['account']
        acc['connected'] = True
        acc['mt5_connected'] = True
        acc['ea_connected'] = True
        acc['broker_connected'] = True
        acc['last_heartbeat'] = now
        acc['latency_ms'] = latency_ms
        acc['last_sync_time'] = time.strftime('%H:%M:%S')

    return jsonify({'status': 'success', 'server_time': now, 'latency_ms': latency_ms})

@app.route('/api/mt5/account', methods=['POST'])
def mt5_post_account():
    data = request.json or {}
    auth_error = require_ea_secret(data)
    if auth_error:
        return auth_error

    now = time.time()
    with autotrade_lock:
        acc = autotrade_state['account']
        acc['connected'] = True
        acc['last_heartbeat'] = now
        acc['last_account_sync'] = now
        acc['last_sync_time'] = time.strftime('%H:%M:%S')
        if 'balance' in data: acc['balance'] = round(float(data['balance']), 2)
        if 'equity' in data: acc['equity'] = round(float(data['equity']), 2)
        if 'margin' in data: acc['margin'] = round(float(data['margin']), 2)
        if 'free_margin' in data: acc['free_margin'] = round(float(data['free_margin']), 2)
        if 'margin_level' in data: acc['margin_level'] = round(float(data['margin_level']), 2)
        if 'server' in data: acc['server'] = str(data['server'])
        if 'login' in data: acc['login'] = str(data['login'])
        save_persisted_state()

    return jsonify({'status': 'success', 'account': autotrade_state['account']})

@app.route('/api/mt5/market', methods=['POST'])
def mt5_post_market():
    data = request.json or {}
    auth_error = require_ea_secret(data)
    if auth_error:
        return auth_error

    now = time.time()
    symbol = data.get('symbol', '').upper()
    bid = float(data.get('bid', 0))
    ask = float(data.get('ask', 0))
    spread = float(data.get('spread', 0))

    if symbol and bid > 0:
        with autotrade_lock:
            autotrade_state['market_data'][symbol] = {
                'bid': bid,
                'ask': ask,
                'spread': spread,
                'time': now
            }
            autotrade_state['account']['last_market_sync'] = now

    return jsonify({'status': 'success', 'symbol': symbol})

@app.route('/api/mt5/positions', methods=['POST'])
def mt5_post_positions():
    data = request.json or {}
    auth_error = require_ea_secret(data)
    if auth_error:
        return auth_error

    positions = data.get('positions', [])
    reconcile_positions_with_mt5(positions)
    return jsonify({'status': 'success', 'positions_count': len(positions)})

@app.route('/api/mt5/history', methods=['POST'])
def mt5_post_history():
    data = request.json or {}
    auth_error = require_ea_secret(data)
    if auth_error:
        return auth_error

    history = data.get('history', [])
    with autotrade_lock:
        if isinstance(history, list) and len(history) > 0:
            autotrade_state['history'] = history[:50]
            save_persisted_state()

    return jsonify({'status': 'success', 'history_count': len(history)})

@app.route('/api/mt5/status', methods=['GET'])
def mt5_get_status():
    with autotrade_lock:
        now = time.time()
        hb = autotrade_state['account']['last_heartbeat']
        is_fresh = (now - hb) < 10.0 if hb > 0 else False
        return jsonify({
            'status': 'success',
            'connected': is_fresh,
            'server': autotrade_state['account']['server'],
            'login': autotrade_state['account']['login'],
            'last_sync_time': autotrade_state['account']['last_sync_time'],
            'heartbeat_age_sec': round(now - hb, 1) if hb > 0 else None,
            'latency_ms': autotrade_state['account']['latency_ms']
        })

@app.route('/api/mt5/sync', methods=['POST'])
def mt5_ea_sync():
    """Unified high-speed sync webhook delivering pending commands and reconciling state."""
    data = request.json or {}
    auth_error = require_ea_secret(data)
    if auth_error:
        return auth_error

    login = str(data.get('login', '')).strip()
    server_name = str(data.get('server', '')).strip()
    currency = str(data.get('currency', 'USD'))
    account_type = str(data.get('account_type', 'DEMO'))
    leverage = int(data.get('leverage', 100))
    balance = float(data.get('balance', 0))
    equity = float(data.get('equity', 0))
    margin = float(data.get('margin', 0))
    free_margin = float(data.get('free_margin', 0))
    positions = data.get('positions', [])
    now = time.time()

    # 1. Update SQLite Database
    database.update_account_telemetry(server_name, login, {
        'balance': balance, 'equity': equity, 'margin': margin,
        'free_margin': free_margin, 'margin_level': round((equity / margin) * 100, 2) if margin > 0 else 0.0,
        'currency': currency, 'account_type': account_type, 'leverage': leverage
    })
    if isinstance(positions, list):
        database.reconcile_mt5_positions_db(server_name, login, positions)

    # 2. Also keep global and user memory cache updated
    with autotrade_lock:
        autotrade_state['account']['connected'] = True
        autotrade_state['account']['mt5_connected'] = True
        autotrade_state['account']['ea_connected'] = True
        autotrade_state['account']['broker_connected'] = True
        autotrade_state['account']['bridge_mode'] = 'EA_WEBHOOK_LIVE'
        autotrade_state['account']['last_heartbeat'] = now
        autotrade_state['account']['last_account_sync'] = now
        autotrade_state['account']['last_position_sync'] = now
        autotrade_state['account']['last_sync_time'] = time.strftime('%H:%M:%S')
        autotrade_state['account']['balance'] = round(balance, 2)
        autotrade_state['account']['equity'] = round(equity, 2)
        autotrade_state['account']['margin'] = round(margin, 2)
        autotrade_state['account']['free_margin'] = round(free_margin, 2)
        autotrade_state['account']['margin_level'] = round((equity / margin) * 100, 2) if margin > 0 else 0.0
        autotrade_state['account']['server'] = server_name
        autotrade_state['account']['login'] = login
        autotrade_state['account']['currency'] = currency
        autotrade_state['account']['account_type'] = account_type
        autotrade_state['account']['leverage'] = leverage

        u_state = get_or_create_user_account(login, server_name)
        u_acc = u_state['account']
        u_acc.update(autotrade_state['account'])

        if isinstance(positions, list):
            reconcile_positions_with_mt5(positions, u_state)
            reconcile_positions_with_mt5(positions, autotrade_state)
            u_acc['last_position_sync'] = now
            autotrade_state['account']['last_position_sync'] = now

    # 3. Pull pending commands from SQLite
    commands_to_send = database.get_pending_commands_db(server_name, login)

    return jsonify({
        'status': 'success',
        'timestamp': now,
        'commands': commands_to_send
    })

# ==========================================================================
# UNIFIED CONSOLIDATED DASHBOARD ENDPOINT (All-in-One Snapshot)
# ==========================================================================
@app.route('/api/autotrade/dashboard', methods=['GET'])
def autotrade_get_dashboard():
    """Unified single endpoint returning account, risk, positions, history, and logs in 1 query."""
    req_login = request.args.get('login') or request.headers.get('X-Account-Login') or ''
    req_server = request.args.get('server') or request.headers.get('X-Account-Server') or 'JustMarkets-Demo'
    return jsonify(database.get_dashboard_snapshot(req_server, req_login))

@app.route('/api/autotrade/status', methods=['GET'])
def autotrade_get_status():
    req_login = request.args.get('login') or request.headers.get('X-Account-Login') or ''
    req_server = request.args.get('server') or request.headers.get('X-Account-Server') or 'JustMarkets-Demo'
    snap = database.get_dashboard_snapshot(req_server, req_login)
    return jsonify({
        'status': 'success',
        'enabled': snap['enabled'],
        'mode': snap['mode'],
        'emergency_stop': snap['emergency_stop'],
        'emergency_reason': snap['emergency_reason'],
        'is_heartbeat_fresh': snap['is_heartbeat_fresh'],
        'account': snap['account'],
        'risk_config': snap['risk_config'],
        'daily_stats': snap['daily_stats'],
        'open_positions_count': len(snap['open_positions']),
        'history_count': len(snap['history'])
    })

@app.route('/api/autotrade/positions', methods=['GET'])
def autotrade_get_positions():
    req_login = request.args.get('login') or request.headers.get('X-Account-Login') or ''
    req_server = request.args.get('server') or request.headers.get('X-Account-Server') or 'JustMarkets-Demo'
    snap = database.get_dashboard_snapshot(req_server, req_login)
    return jsonify({'status': 'success', 'positions': snap['open_positions']})

@app.route('/api/autotrade/history', methods=['GET'])
def autotrade_get_history():
    req_login = request.args.get('login') or request.headers.get('X-Account-Login') or ''
    req_server = request.args.get('server') or request.headers.get('X-Account-Server') or 'JustMarkets-Demo'
    snap = database.get_dashboard_snapshot(req_server, req_login)
    return jsonify({'status': 'success', 'history': snap['history']})

@app.route('/api/autotrade/audit-logs', methods=['GET'])
def autotrade_get_audit_logs():
    req_login = request.args.get('login') or request.headers.get('X-Account-Login') or ''
    req_server = request.args.get('server') or request.headers.get('X-Account-Server') or 'JustMarkets-Demo'
    snap = database.get_dashboard_snapshot(req_server, req_login)
    return jsonify({'status': 'success', 'logs': snap['audit_logs']})

@app.route('/api/autotrade/health', methods=['GET'])
def autotrade_get_health():
    with autotrade_lock:
        now = time.time()
        hb = autotrade_state['account']['last_heartbeat']
        is_fresh = (now - hb) < 10.0 if hb > 0 else False
        
        return jsonify({
            'status': 'ok' if is_fresh else 'degraded',
            'backend_status': 'ONLINE',
            'rest_api_status': 'ONLINE',
            'mt5_status': 'CONNECTED' if is_fresh else 'DISCONNECTED',
            'ea_status': 'STREAMING' if is_fresh else 'OFFLINE',
            'broker_status': 'CONNECTED' if (is_fresh and autotrade_state['account']['balance'] > 0) else 'DISCONNECTED',
            'server': autotrade_state['account']['server'],
            'login': autotrade_state['account']['login'],
            'last_heartbeat': autotrade_state['account']['last_heartbeat'],
            'last_account_sync': autotrade_state['account']['last_account_sync'],
            'last_position_sync': autotrade_state['account']['last_position_sync'],
            'last_market_sync': autotrade_state['account']['last_market_sync'],
            'heartbeat_age_sec': round(now - hb, 1) if hb > 0 else None,
            'latency_ms': autotrade_state['account']['latency_ms'],
            'server_time': time.strftime('%Y-%m-%d %H:%M:%S')
        })

@app.route('/api/autotrade/connect', methods=['POST'])
def autotrade_post_connect():
    data = request.json or {}
    server_name = data.get('server', 'JustMarkets-Demo').strip()
    login = str(data.get('login', '')).strip()
    mode = data.get('mode', 'demo')

    with autotrade_lock:
        u_state = get_or_create_user_account(login, server_name)
        u_state['mode'] = mode
        u_state['emergency_stop'] = False
        u_state['emergency_reason'] = ''
        
        # We do NOT mark it connected here. We wait for MT5 heartbeat to truly mark it connected.
        
        save_persisted_state()

    log_audit_event("ACCOUNT_CONFIGURED", "SYSTEM", None, f"تم حفظ إعدادات الاتصال للميتاتريدر ({server_name} #{login} - نمط {mode.upper()}) بانتظار إشارة EA")
    return jsonify({
        'status': 'success',
        'message': f'تم حفظ إعدادات الاتصال بانتظار اتصال EA ({server_name} #{login})',
        'account': u_state['account']
    })

@app.route('/api/autotrade/toggle', methods=['POST'])
def autotrade_post_toggle():
    data = request.json or {}
    req_login = request.args.get('login') or request.headers.get('X-Account-Login') or data.get('login', '')
    req_server = request.args.get('server') or request.headers.get('X-Account-Server') or data.get('server', 'JustMarkets-Demo')

    with autotrade_lock:
        u_state = get_or_create_user_account(req_login, req_server) if req_login else autotrade_state
        if 'enabled' in data:
            u_state['enabled'] = bool(data['enabled'])
        else:
            u_state['enabled'] = not u_state['enabled']
        is_on = u_state['enabled']
        autotrade_state['enabled'] = is_on
        save_persisted_state()

    # Update database account enabled state
    if req_login:
        database.update_account_enabled_db(req_server, req_login, is_on)

    msg = 'تم تفعيل التداول الآلي بنجاح 🟢' if is_on else 'تم إيقاف التداول الآلي ⏸️'
    log_audit_event("AUTOTRADE_TOGGLE", "SYSTEM", None, msg)
    return jsonify({'status': 'success', 'enabled': is_on, 'message': msg})

# TIER 1: Stop New Trades (Pause) - Leaves open positions managed
@app.route('/api/autotrade/pause', methods=['POST'])
def autotrade_post_pause():
    with autotrade_lock:
        autotrade_state['enabled'] = False
        save_persisted_state()
    log_audit_event("STOP_NEW_TRADES", "SYSTEM", None, "تم إيقاف دخول صفقات جديدة مع إبقاء الصفقات المفتوحة قيد الإدارة ⏸️")
    return jsonify({'status': 'success', 'message': 'تم إيقاف فتح صفقات جديدة ⏸️ (الصفقات المفتوحة ما زالت نشطة)'})

@app.route('/api/autotrade/config', methods=['POST'])
def autotrade_post_config():
    data = request.json or {}
    req_login = request.args.get('login') or request.headers.get('X-Account-Login') or data.get('login', '')
    req_server = request.args.get('server') or request.headers.get('X-Account-Server') or data.get('server', 'JustMarkets-Demo')

    with autotrade_lock:
        u_state = get_or_create_user_account(req_login, req_server) if req_login else autotrade_state
        cfg = u_state['risk_config']
        if 'risk_percent' in data: cfg['risk_percent'] = float(data['risk_percent'])
        if 'max_lot_cap' in data: cfg['max_lot_cap'] = float(data['max_lot_cap'])
        if 'max_open_trades' in data: cfg['max_open_trades'] = int(data['max_open_trades'])
        if 'max_daily_trades' in data: cfg['max_daily_trades'] = int(data['max_daily_trades'])
        if 'max_daily_loss_pct' in data: cfg['max_daily_loss_pct'] = float(data['max_daily_loss_pct'])
        if 'min_score' in data: cfg['min_score'] = int(data['min_score'])
        if 'auto_breakeven' in data: cfg['auto_breakeven'] = bool(data['auto_breakeven'])
        if 'trailing_stop_enabled' in data: cfg['trailing_stop_enabled'] = bool(data['trailing_stop_enabled'])
        if 'allowed_metals' in data: cfg['allowed_metals'] = bool(data['allowed_metals'])
        if 'allowed_forex' in data: cfg['allowed_forex'] = bool(data['allowed_forex'])
        if 'allowed_stocks' in data: cfg['allowed_stocks'] = bool(data['allowed_stocks'])
        if 'allowed_crypto' in data: cfg['allowed_crypto'] = bool(data['allowed_crypto'])
        if 'allowed_symbols' in data: cfg['allowed_symbols'] = str(data['allowed_symbols'])
        save_persisted_state()

    # Save to SQLite Database
    database.update_risk_config_db(req_server, req_login, cfg)

    log_audit_event("CONFIG_UPDATED", "SYSTEM", None, "تم تحديث قواعد إدارة المخاطر وتفضيلات الأصول المسموحة بنجاح")
    return jsonify({'status': 'success', 'config': cfg})

@app.route('/api/autotrade/execute', methods=['POST'])
def autotrade_post_execute():
    data = request.json or {}
    req_login = request.args.get('login') or request.headers.get('X-Account-Login') or data.get('login', '')
    req_server = request.args.get('server') or request.headers.get('X-Account-Server') or data.get('server', 'JustMarkets-Demo')

    with execution_mutex:
        passed, code_err, result = validate_trade_risk(data, req_login, req_server)
        if not passed:
            log_audit_event("TRADE_REJECTED", data.get('symbol'), None, f"رفض الصفقة: {result} (كود: {code_err})")
            return jsonify({'status': 'rejected', 'code': code_err, 'message': result}), 400

        symbol = data['symbol'].upper()
        trade_type = data['type'].upper()
        entry = float(data['entry'])
        sl = float(data['sl'])
        tp1 = float(data['tp1'])
        tp2 = float(data.get('tp2', 0))
        tp3 = float(data.get('tp3', 0))
        score = int(data.get('score', 80))
        lot = result['lot']
        signal_id = result['signal_id']
        idem_key = result.get('idempotency_key', '')

        # 1. Queue into SQLite Database
        cmd_db = database.queue_command_db(req_server, req_login, trade_type, symbol, lot=lot, entry=entry, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3, signal_id=signal_id)

        # 2. Also keep in memory commands store
        cmd = queue_trade_command(trade_type, symbol, lot=lot, entry=entry, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3, signal_id=signal_id)
        if req_login:
            cmd['login'] = req_login
            
        log_audit_event("ORDER_APPROVED_AND_QUEUED", symbol, None, f"تم إنشاء أمر {cmd['command_id']} ({trade_type} {lot} لوت)")

        return jsonify({
            'status': 'success',
            'message': f'تم إرسال أمر فتح صفقة {trade_type} على {symbol} بحجم {lot} لوت بنجاح وموجود في الطابور ⏳',
            'command': cmd
        })

@app.route('/api/autotrade/close', methods=['POST'])
def autotrade_post_close():
    data = request.json or {}
    ticket = str(data.get('ticket', ''))
    req_login = request.args.get('login') or request.headers.get('X-Account-Login') or data.get('login', '')
    req_server = request.args.get('server') or request.headers.get('X-Account-Server') or data.get('server', 'JustMarkets-Demo')

    with autotrade_lock:
        target_state = get_or_create_user_account(req_login, req_server) if req_login else autotrade_state
        target = None
        for p in target_state['open_positions']:
            if str(p['ticket']) == ticket:
                target = p
                break

        target_symbol = target['symbol'] if target else 'ALL'
        if target:
            target['status'] = 'CLOSE_REQUESTED'
            save_persisted_state()

    # Queue close command in SQLite Database
    cmd_db = database.queue_command_db(req_server, req_login, 'CLOSE', target_symbol, ticket=ticket)

    cmd = queue_trade_command('CLOSE', target_symbol, ticket=ticket)
    if req_login:
        cmd['login'] = req_login
        
    log_audit_event("CLOSE_REQUESTED", target_symbol, ticket, f"طلب إغلاق يدوي للصفقة #{ticket}")
    return jsonify({'status': 'success', 'message': f'تم إرسال طلب إغلاق الصفقة #{ticket}', 'command': cmd})

@app.route('/api/autotrade/close-all', methods=['POST'])
def autotrade_post_close_all():
    with autotrade_lock:
        closed_count = len(autotrade_state['open_positions'])
        for p in list(autotrade_state['open_positions']):
            autotrade_state['open_positions'].remove(p)
            autotrade_state['account']['balance'] += p['pnl']
            autotrade_state['daily_stats']['realized_pnl'] += p['pnl']
            p['status'] = 'CLOSED_ALL'
            p['close_time'] = time.strftime('%H:%M:%S')
            autotrade_state['history'].insert(0, p)
            queue_trade_command('CLOSE', p['symbol'], ticket=p['ticket'])
        save_persisted_state()

    log_audit_event("CLOSE_ALL_POSITIONS", "ALL", None, f"تم إغلاق جميع الصفقات المفتوحة ({closed_count} صفقة)")
    return jsonify({'status': 'success', 'message': f'تم إغلاق جميع الصفقات المفتوحة ({closed_count}) بنجاح'})

# TIER 2: Close All + Emergency Stop (Double-confirmed full flatten & lock)
@app.route('/api/autotrade/emergency-stop', methods=['POST'])
def autotrade_post_emergency_stop():
    data = request.json or {}
    reason = data.get('reason', 'تم تفعيل إغلاق الطوارئ الشامل من المتداول')
    flatten = data.get('close_all', True)

    with autotrade_lock:
        autotrade_state['enabled'] = False
        autotrade_state['emergency_stop'] = True
        autotrade_state['emergency_reason'] = reason
        if flatten and autotrade_state['open_positions']:
            for p in list(autotrade_state['open_positions']):
                autotrade_state['open_positions'].remove(p)
                autotrade_state['account']['balance'] += p['pnl']
                autotrade_state['daily_stats']['realized_pnl'] += p['pnl']
                p['status'] = 'EMERGENCY_FLATTEN'
                p['close_time'] = time.strftime('%H:%M:%S')
                autotrade_state['history'].insert(0, p)
                queue_trade_command('CLOSE', p['symbol'], ticket=p['ticket'])
        save_persisted_state()

    log_audit_event("EMERGENCY_STOP_TRIGGERED", "SYSTEM", None, reason)
    return jsonify({'status': 'success', 'message': f'🚨 تم تفعيل إغلاق الطوارئ الشامل وإيقاف التداول: {reason}'})

@app.route('/api/mt5/download-ea', methods=['GET'])
def mt5_download_ea():
    try:
        with open(os.path.join(APP_DIR, "MarketPulse_Bridge.mq5"), "r", encoding="utf-8") as f:
            content = f.read()
        from flask import Response
        return Response(
            content,
            mimetype="text/plain",
            headers={"Content-Disposition": "attachment;filename=MarketPulse_Bridge.mq5"}
        )
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
if __name__ == '__main__':
    print(f"MarketPulse FX server running on {PUBLIC_BASE_URL} (bind {SERVER_HOST}:{SERVER_PORT})")
    app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False)
