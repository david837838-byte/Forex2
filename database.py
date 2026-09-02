import sqlite3
import time
import os
import threading

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "marketpulse.db")
db_lock = threading.RLock()

def get_connection():
    """Returns a SQLite connection with WAL mode and busy timeout configured."""
    conn = sqlite3.connect(DB_FILE, timeout=15.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=15000;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

def init_db():
    """Initializes all database tables if they do not exist."""
    with db_lock:
        conn = get_connection()
        try:
            with conn:
                cursor = conn.cursor()

                # 1. Accounts Table
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    account_key TEXT PRIMARY KEY,
                    server TEXT,
                    login TEXT,
                    mode TEXT DEFAULT 'demo',
                    balance REAL DEFAULT 0.0,
                    equity REAL DEFAULT 0.0,
                    margin REAL DEFAULT 0.0,
                    free_margin REAL DEFAULT 0.0,
                    margin_level REAL DEFAULT 0.0,
                    currency TEXT DEFAULT 'USD',
                    account_type TEXT DEFAULT 'DEMO',
                    leverage INTEGER DEFAULT 100,
                    connected INTEGER DEFAULT 0,
                    mt5_connected INTEGER DEFAULT 0,
                    ea_connected INTEGER DEFAULT 0,
                    broker_connected INTEGER DEFAULT 0,
                    bridge_mode TEXT DEFAULT 'DISCONNECTED',
                    last_heartbeat REAL DEFAULT 0,
                    last_account_sync REAL DEFAULT 0,
                    last_position_sync REAL DEFAULT 0,
                    last_sync_time TEXT DEFAULT '',
                    latency_ms REAL DEFAULT 0.0,
                    enabled INTEGER DEFAULT 1,
                    emergency_stop INTEGER DEFAULT 0,
                    emergency_reason TEXT DEFAULT '',
                    updated_at REAL DEFAULT 0
                );
                """)

                # 2. Risk Config Table
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS risk_configs (
                    account_key TEXT PRIMARY KEY,
                    risk_percent REAL DEFAULT 1.0,
                    max_lot_cap REAL DEFAULT 0.50,
                    max_open_trades INTEGER DEFAULT 3,
                    min_score INTEGER DEFAULT 75,
                    auto_breakeven INTEGER DEFAULT 1,
                    partial_tp1_close_pct INTEGER DEFAULT 50,
                    allowed_metals INTEGER DEFAULT 1,
                    allowed_forex INTEGER DEFAULT 1,
                    allowed_stocks INTEGER DEFAULT 1,
                    allowed_crypto INTEGER DEFAULT 1,
                    allowed_symbols TEXT DEFAULT '',
                    updated_at REAL DEFAULT 0
                );
                """)

                # Migrations for existing databases
                for col, col_def in [
                    ('allowed_metals', 'INTEGER DEFAULT 1'),
                    ('allowed_forex', 'INTEGER DEFAULT 1'),
                    ('allowed_stocks', 'INTEGER DEFAULT 1'),
                    ('allowed_crypto', 'INTEGER DEFAULT 1'),
                    ('allowed_symbols', "TEXT DEFAULT ''")
                ]:
                    try:
                        cursor.execute(f"ALTER TABLE risk_configs ADD COLUMN {col} {col_def};")
                    except Exception:
                        pass

                # 3. Positions Table
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    ticket TEXT PRIMARY KEY,
                    account_key TEXT,
                    symbol TEXT,
                    type TEXT,
                    lot REAL,
                    entry REAL,
                    current_price REAL,
                    sl REAL,
                    tp1 REAL,
                    tp2 REAL,
                    tp3 REAL,
                    score INTEGER,
                    pnl REAL DEFAULT 0.0,
                    swap REAL DEFAULT 0.0,
                    commission REAL DEFAULT 0.0,
                    tp1_hit INTEGER DEFAULT 0,
                    tp2_hit INTEGER DEFAULT 0,
                    signal_id TEXT,
                    open_time TEXT,
                    status TEXT,
                    notes TEXT,
                    created_at REAL,
                    updated_at REAL
                );
                """)

                # 4. Trades History Table
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket TEXT,
                    account_key TEXT,
                    symbol TEXT,
                    type TEXT,
                    lot REAL,
                    entry REAL,
                    close_price REAL,
                    sl REAL,
                    tp1 REAL,
                    pnl REAL,
                    swap REAL DEFAULT 0.0,
                    commission REAL DEFAULT 0.0,
                    open_time TEXT,
                    close_time TEXT,
                    status TEXT,
                    close_reason TEXT,
                    closed_at REAL
                );
                """)

                # 5. Audit Logs Table
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_key TEXT,
                    event_type TEXT,
                    symbol TEXT,
                    ticket TEXT,
                    message TEXT,
                    created_at REAL,
                    time_str TEXT
                );
                """)

                # 6. Commands Table
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS commands (
                    command_id TEXT PRIMARY KEY,
                    account_key TEXT,
                    action TEXT,
                    symbol TEXT,
                    type TEXT,
                    lot REAL,
                    entry REAL,
                    sl REAL,
                    tp1 REAL,
                    tp2 REAL,
                    tp3 REAL,
                    ticket TEXT,
                    signal_id TEXT,
                    status TEXT,
                    retry_count INTEGER DEFAULT 0,
                    created_at REAL,
                    expires_at REAL
                );
                """)
        finally:
            conn.close()
    print("[DATABASE] SQLite tables initialized.")

# Run init on module load
init_db()

# ==============================================================================
# CRUD & BUSINESS LOGIC HELPERS
# ==============================================================================

def get_account_key(server="JustMarkets-Demo", login=""):
    s = (server or "JustMarkets-Demo").strip()
    l = str(login or "").strip()
    return f"{s}_{l}" if l else "default_account"

def get_or_create_account(server="JustMarkets-Demo", login=""):
    """Fetches account state and risk config, creating defaults if not exist."""
    key = get_account_key(server, login)
    now = time.time()
    with db_lock:
        conn = get_connection()
        try:
            with conn:
                c = conn.cursor()
                c.execute("SELECT * FROM accounts WHERE account_key = ?", (key,))
                acc_row = c.fetchone()
                if not acc_row:
                    conn.execute("""
                    INSERT INTO accounts (account_key, server, login, mode, updated_at)
                    VALUES (?, ?, ?, 'demo', ?)
                    """, (key, server, login, now))
                    conn.execute("""
                    INSERT INTO risk_configs (account_key, updated_at)
                    VALUES (?, ?)
                    """, (key, now))
                    c.execute("SELECT * FROM accounts WHERE account_key = ?", (key,))
                    acc_row = c.fetchone()

                c.execute("SELECT * FROM risk_configs WHERE account_key = ?", (key,))
                risk_row = c.fetchone()

                acc_dict = dict(acc_row)
                risk_dict = dict(risk_row) if risk_row else {
                    'risk_percent': 1.0, 'max_lot_cap': 0.50, 'max_open_trades': 3,
                    'min_score': 75, 'auto_breakeven': 1, 'partial_tp1_close_pct': 50,
                    'allowed_metals': 1, 'allowed_forex': 1, 'allowed_stocks': 1,
                    'allowed_crypto': 1, 'allowed_symbols': ''
                }
                return acc_dict, risk_dict
        finally:
            conn.close()

def update_risk_config_db(server, login, cfg_data):
    """Updates user risk and asset selection settings in SQLite."""
    key = get_account_key(server, login)
    now = time.time()
    with db_lock:
        conn = get_connection()
        try:
            with conn:
                conn.execute("""
                INSERT INTO risk_configs (
                    account_key, risk_percent, max_lot_cap, max_open_trades, min_score,
                    auto_breakeven, partial_tp1_close_pct, allowed_metals, allowed_forex,
                    allowed_stocks, allowed_crypto, allowed_symbols, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_key) DO UPDATE SET
                    risk_percent=excluded.risk_percent,
                    max_lot_cap=excluded.max_lot_cap,
                    max_open_trades=excluded.max_open_trades,
                    min_score=excluded.min_score,
                    auto_breakeven=excluded.auto_breakeven,
                    partial_tp1_close_pct=excluded.partial_tp1_close_pct,
                    allowed_metals=excluded.allowed_metals,
                    allowed_forex=excluded.allowed_forex,
                    allowed_stocks=excluded.allowed_stocks,
                    allowed_crypto=excluded.allowed_crypto,
                    allowed_symbols=excluded.allowed_symbols,
                    updated_at=excluded.updated_at
                """, (
                    key,
                    float(cfg_data.get('risk_percent', 1.0)),
                    float(cfg_data.get('max_lot_cap', 0.50)),
                    int(cfg_data.get('max_open_trades', 3)),
                    int(cfg_data.get('min_score', 75)),
                    1 if cfg_data.get('auto_breakeven', True) else 0,
                    int(cfg_data.get('partial_tp1_close_pct', 50)),
                    1 if cfg_data.get('allowed_metals', True) else 0,
                    1 if cfg_data.get('allowed_forex', True) else 0,
                    1 if cfg_data.get('allowed_stocks', True) else 0,
                    1 if cfg_data.get('allowed_crypto', True) else 0,
                    str(cfg_data.get('allowed_symbols', '')),
                    now
                ))
        finally:
            conn.close()

def update_account_enabled_db(server, login, enabled):
    """Updates account enabled state in SQLite."""
    key = get_account_key(server, login)
    now = time.time()
    with db_lock:
        conn = get_connection()
        try:
            with conn:
                conn.execute("UPDATE accounts SET enabled = ?, updated_at = ? WHERE account_key = ?", (1 if enabled else 0, now, key))
        finally:
            conn.close()

def update_account_telemetry(server, login, data):
    """Updates live account balance, equity, and heartbeat from MT5."""
    key = get_account_key(server, login)
    now = time.time()
    with db_lock:
        conn = get_connection()
        try:
            with conn:
                for target_k in set([key, 'default_account']):
                    conn.execute("""
                    INSERT INTO accounts (
                        account_key, server, login, mode, balance, equity, margin, free_margin,
                        margin_level, currency, account_type, leverage, connected, mt5_connected,
                        ea_connected, broker_connected, bridge_mode, last_heartbeat, last_account_sync,
                        last_position_sync, last_sync_time, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, 1, 1, 'EA_WEBHOOK_LIVE', ?, ?, ?, ?, ?)
                    ON CONFLICT(account_key) DO UPDATE SET
                        server=excluded.server,
                        login=excluded.login,
                        balance=excluded.balance,
                        equity=excluded.equity,
                        margin=excluded.margin,
                        free_margin=excluded.free_margin,
                        margin_level=excluded.margin_level,
                        currency=excluded.currency,
                        account_type=excluded.account_type,
                        leverage=excluded.leverage,
                        connected=1,
                        mt5_connected=1,
                        ea_connected=1,
                        broker_connected=1,
                        bridge_mode='EA_WEBHOOK_LIVE',
                        last_heartbeat=excluded.last_heartbeat,
                        last_account_sync=excluded.last_account_sync,
                        last_position_sync=excluded.last_position_sync,
                        last_sync_time=excluded.last_sync_time,
                        updated_at=excluded.updated_at
                    """, (
                        target_k, server, login, data.get('mode', 'demo'),
                        data.get('balance', 0.0), data.get('equity', 0.0), data.get('margin', 0.0),
                        data.get('free_margin', 0.0), data.get('margin_level', 0.0),
                        data.get('currency', 'USD'), data.get('account_type', 'DEMO'),
                        data.get('leverage', 100), now, now, now,
                        time.strftime('%H:%M:%S'), now
                    ))
        finally:
            conn.close()

def log_audit(account_key, event_type, symbol, ticket, message):
    """Inserts a structured audit event into database."""
    now = time.time()
    time_str = time.strftime('%H:%M:%S')
    with db_lock:
        try:
            conn = get_connection()
            try:
                with conn:
                    conn.execute("""
                    INSERT INTO audit_logs (account_key, event_type, symbol, ticket, message, created_at, time_str)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (account_key, event_type, symbol or '', str(ticket or ''), message, now, time_str))
            finally:
                conn.close()
        except Exception as e:
            print(f"[DB AUDIT LOG ERROR] {e}")

def get_dashboard_snapshot(server="JustMarkets-Demo", login=""):
    """Fetches complete consolidated snapshot for the web dashboard in a single query."""
    with db_lock:
        conn = get_connection()
        try:
            c = conn.cursor()
            if not login or login == 'default_account':
                c.execute("SELECT server, login FROM accounts WHERE last_heartbeat > 0 ORDER BY last_heartbeat DESC LIMIT 1")
                active_row = c.fetchone()
                if active_row and active_row['login']:
                    server = active_row['server']
                    login = active_row['login']
        finally:
            conn.close()

    key = get_account_key(server, login)
    acc_dict, risk_dict = get_or_create_account(server, login)
    now = time.time()

    hb_age = now - acc_dict.get('last_heartbeat', 0) if acc_dict.get('last_heartbeat', 0) > 0 else 999999.0
    is_fresh = hb_age < 300.0
    acc_dict['connected'] = bool(acc_dict.get('balance', 0) > 0 or is_fresh)
    acc_dict['mt5_connected'] = bool(acc_dict.get('balance', 0) > 0 or is_fresh)
    acc_dict['ea_connected'] = bool(is_fresh or acc_dict.get('balance', 0) > 0)
    acc_dict['is_heartbeat_fresh'] = bool(is_fresh or acc_dict.get('balance', 0) > 0)

    with db_lock:
        conn = get_connection()
        try:
            c = conn.cursor()

            # Open positions: Fetch all active positions
            c.execute("SELECT * FROM positions ORDER BY created_at DESC")
            open_positions = [dict(r) for r in c.fetchall()]

            # Trade history (last 25)
            c.execute("SELECT * FROM trades_history ORDER BY closed_at DESC LIMIT 25")
            history = [dict(r) for r in c.fetchall()]

            # Audit logs (last 30)
            c.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 30")
            logs = [dict(r) for r in c.fetchall()]

            # Daily stats calculation
            start_of_day = now - (now % 86400)
            c.execute("SELECT COUNT(*), COALESCE(SUM(pnl), 0.0) FROM trades_history WHERE closed_at >= ?", (start_of_day,))
            daily_row = c.fetchone()
            trades_count = daily_row[0] if daily_row else 0
            realized_pnl = round(daily_row[1], 2) if daily_row else 0.0

            floating_pnl = round(sum(p.get('pnl', 0.0) for p in open_positions), 2)
        finally:
            conn.close()

    return {
        'status': 'success',
        'enabled': bool(acc_dict.get('enabled', 1)),
        'mode': acc_dict.get('mode', 'demo'),
        'emergency_stop': bool(acc_dict.get('emergency_stop', 0)),
        'emergency_reason': acc_dict.get('emergency_reason', ''),
        'is_heartbeat_fresh': is_fresh,
        'account': acc_dict,
        'risk_config': risk_dict,
        'daily_stats': {
            'trades_opened': trades_count + len(open_positions),
            'realized_pnl': realized_pnl,
            'floating_pnl': floating_pnl
        },
        'open_positions': open_positions,
        'history': history,
        'audit_logs': logs,
        'timestamp': now
    }

def reconcile_mt5_positions_db(server, login, mt5_positions):
    """Strict Single-Source-of-Truth reconciliation in SQLite."""
    key = get_account_key(server, login)
    now = time.time()
    if not isinstance(mt5_positions, list):
        return

    with db_lock:
        conn = get_connection()
        try:
            with conn:
                c = conn.cursor()
                c.execute("SELECT * FROM positions")
                db_positions = {str(r['ticket']): dict(r) for r in c.fetchall()}

                seen_tickets = set()

                for mt5_pos in mt5_positions:
                    ticket = str(mt5_pos.get('ticket', ''))
                    if not ticket:
                        continue
                    seen_tickets.add(ticket)

                    sym = mt5_pos.get('symbol', '').upper()
                    p_type = mt5_pos.get('type', 'BUY').upper()
                    lot = float(mt5_pos.get('lot', 0.01))
                    entry = float(mt5_pos.get('entry', 0.0))
                    cur_price = float(mt5_pos.get('current_price', entry))
                    sl = float(mt5_pos.get('sl', 0.0))
                    tp1 = float(mt5_pos.get('tp1', mt5_pos.get('tp', 0.0)))
                    pnl = round(float(mt5_pos.get('pnl', 0.0)), 2)
                    swap = float(mt5_pos.get('swap', 0.0))
                    comm = float(mt5_pos.get('commission', 0.0))

                    if ticket in db_positions:
                        # Update live price and PnL
                        conn.execute("""
                        UPDATE positions SET
                            current_price = ?, pnl = ?, swap = ?, commission = ?, sl = ?, tp1 = ?, updated_at = ?
                        WHERE ticket = ?
                        """, (cur_price, pnl, swap, comm, sl, tp1, now, ticket))
                    else:
                        # New position discovered from MT5
                        conn.execute("""
                        INSERT INTO positions (
                            ticket, account_key, symbol, type, lot, entry, current_price,
                            sl, tp1, tp2, tp3, score, pnl, swap, commission, status, open_time, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 80, ?, ?, ?, 'ACTIVE', ?, ?, ?)
                        """, (
                            ticket, key, sym, p_type, lot, entry, cur_price,
                            sl, tp1, pnl, swap, comm, time.strftime('%H:%M:%S'), now, now
                        ))
                        log_audit(key, "POSITION_SYNCED", sym, ticket, f"تم تسجيل صفقة حقيقية من MT5: #{ticket} ({p_type} {lot} لوت)")

                # Move closed trades to history
                for ticket, old_pos in db_positions.items():
                    if ticket not in seen_tickets:
                        conn.execute("DELETE FROM positions WHERE ticket = ?", (ticket,))
                        conn.execute("""
                        INSERT INTO trades_history (
                            ticket, account_key, symbol, type, lot, entry, close_price,
                            sl, tp1, pnl, swap, commission, open_time, close_time, status, close_reason, closed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CLOSED', 'إغلاق من MT5', ?)
                        """, (
                            ticket, key, old_pos['symbol'], old_pos['type'], old_pos['lot'],
                            old_pos['entry'], old_pos.get('current_price', old_pos['entry']),
                            old_pos.get('sl', 0), old_pos.get('tp1', 0), old_pos.get('pnl', 0),
                            old_pos.get('swap', 0), old_pos.get('commission', 0),
                            old_pos.get('open_time', ''), time.strftime('%H:%M:%S'), now
                        ))
                        log_audit(key, "POSITION_CLOSED", old_pos['symbol'], ticket, f"تم تأكيد إغلاق الصفقة #{ticket} (الربح: ${old_pos.get('pnl', 0):.2f})")
        finally:
            conn.close()

def queue_command_db(server, login, action, symbol, lot=0.0, entry=0.0, sl=0.0, tp1=0.0, tp2=0.0, tp3=0.0, ticket="", signal_id=""):
    """Inserts a trade execution command into the database queue with 60s TTL."""
    key = get_account_key(server, login)
    now = time.time()
    import uuid
    cmd_id = f"CMD-{uuid.uuid4().hex[:8].upper()}"
    p_type = 'BUY' if 'BUY' in action.upper() else ('SELL' if 'SELL' in action.upper() else action.upper())

    with db_lock:
        conn = get_connection()
        try:
            with conn:
                conn.execute("""
                INSERT INTO commands (
                    command_id, account_key, action, symbol, type, lot, entry,
                    sl, tp1, tp2, tp3, ticket, signal_id, status, retry_count, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'QUEUED', 0, ?, ?)
                """, (
                    cmd_id, key, action.upper(), symbol.upper(), p_type, lot, entry,
                    sl, tp1, tp2, tp3, str(ticket or ''), str(signal_id or ''), now, now + 60.0
                ))
        finally:
            conn.close()

    return {
        'command_id': cmd_id,
        'action': action.upper(),
        'symbol': symbol.upper(),
        'type': p_type,
        'lot': lot,
        'entry': entry,
        'sl': sl,
        'tp1': tp1,
        'ticket': ticket,
        'status': 'QUEUED',
        'expires_at': now + 60.0
    }

def get_pending_commands_db(server="", login=""):
    """Pulls active QUEUED commands to dispatch to MT5 EA."""
    key = get_account_key(server, login) if login else None
    now = time.time()
    with db_lock:
        conn = get_connection()
        try:
            with conn:
                c = conn.cursor()
                if key:
                    c.execute("SELECT * FROM commands WHERE (account_key = ? OR account_key = 'default_account') AND status = 'QUEUED' AND expires_at >= ?", (key, now))
                else:
                    c.execute("SELECT * FROM commands WHERE status = 'QUEUED' AND expires_at >= ?", (now,))
                rows = [dict(r) for r in c.fetchall()]

                for r in rows:
                    conn.execute("UPDATE commands SET status = 'SENT_TO_EA' WHERE command_id = ?", (r['command_id'],))
                return rows
        finally:
            conn.close()
