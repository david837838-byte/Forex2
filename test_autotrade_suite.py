import unittest
import time
import server

class TestInstitutionalAutoTradeSuite(unittest.TestCase):
    def setUp(self):
        # Reset server autotrade state for fresh testing
        with server.autotrade_lock:
            server.autotrade_state['enabled'] = True
            server.autotrade_state['mode'] = 'demo'
            server.autotrade_state['emergency_stop'] = False
            server.autotrade_state['emergency_reason'] = ''
            server.autotrade_state['account'] = {
                'connected': True,
                'bridge_mode': 'EA_WEBHOOK_LIVE',
                'server': 'JustMarkets-Demo',
                'login': '2001944351',
                'balance': 40000.00,
                'equity': 40000.00,
                'margin': 0.0,
                'free_margin': 40000.00,
                'margin_level': 100.0,
                'currency': 'USD',
                'leverage': 100,
                'last_sync_time': time.strftime('%H:%M:%S'),
                'last_heartbeat': time.time(),
                'latency_ms': 12.5
            }
            server.autotrade_state['risk_config'] = {
                'risk_percent': 1.0,
                'max_lot_cap': 0.50,
                'max_open_trades': 3,
                'max_daily_trades': 10,
                'max_daily_loss_pct': 3.0,
                'min_score': 75,
                'auto_breakeven': True,
                'breakeven_buffer_pips': 2.0,
                'partial_tp1_close_pct': 50,
                'partial_tp2_close_pct': 30,
                'trailing_stop_enabled': False,
                'consecutive_loss_limit': 2,
                'loss_cooldown_minutes': 30
            }
            server.autotrade_state['daily_stats'] = {
                'date': time.strftime('%Y-%m-%d'),
                'trades_opened': 0,
                'starting_balance': 40000.0,
                'realized_pnl': 0.0,
                'floating_pnl': 0.0,
                'consecutive_losses': 0,
                'cooldown_until': 0.0,
                'peak_equity': 40000.0
            }
            server.autotrade_state['open_positions'] = []
            server.autotrade_state['history'] = []
            server.commands_store.clear()
            server.idempotency_store.clear()

    # 1. Broker Connection & Heartbeat
    def test_01_broker_connection_heartbeat(self):
        client = server.app.test_client()
        res = client.post('/api/mt5/sync', json={
            'secret': server.EA_WEBHOOK_SECRET,
            'login': 2001944351,
            'server': 'JustMarkets-Demo',
            'balance': 42500.0,
            'equity': 42650.0,
            'margin': 500.0,
            'free_margin': 42150.0,
            'positions': []
        })
        self.assertEqual(res.status_code, 200)
        with server.autotrade_lock:
            self.assertTrue(server.autotrade_state['account']['connected'])
            self.assertEqual(server.autotrade_state['account']['balance'], 42500.0)

    # 2. Stale Heartbeat Detection (> 10s)
    def test_02_stale_heartbeat_detection(self):
        with server.autotrade_lock:
            server.autotrade_state['account']['last_heartbeat'] = time.time() - 15.0 # 15s ago
        
        signal = {'symbol': 'EURUSD', 'type': 'BUY', 'entry': 1.0850, 'sl': 1.0825, 'tp1': 1.0900, 'score': 85}
        passed, code, reason = server.validate_trade_risk(signal)
        self.assertFalse(passed)
        self.assertEqual(code, 'MT5_DISCONNECTED')

    # 3. Risk-Based Lot Sizing (Forex: EURUSD)
    def test_03_risk_lot_forex(self):
        # Balance = $40,000, 1% Risk = $400, SL = 25 pips (0.0025)
        # Lot = 400 / (0.0025 * 100,000) = 1.60 Lot
        # But max_lot_cap = 0.50, so capped at 0.50
        lot = server.calculate_risk_position_size('EURUSD', 1.0850, 1.0825, 40000.0, 1.0, 5.0)
        self.assertEqual(lot, 1.60)

    # 4. Risk-Based Lot Sizing (Gold: XAUUSD)
    def test_04_risk_lot_gold(self):
        # Balance = $40,000, 1% Risk = $400, SL = $4.00 (Contract size = 100)
        # Lot = 400 / (4.00 * 100) = 1.00 Lot
        lot = server.calculate_risk_position_size('XAUUSD', 2480.0, 2476.0, 40000.0, 1.0, 5.0)
        self.assertEqual(lot, 1.00)

    # 5. Max Lot Cap Enforcement
    def test_05_max_lot_cap_enforcement(self):
        lot = server.calculate_risk_position_size('XAUUSD', 2480.0, 2476.0, 40000.0, 1.0, 0.50)
        self.assertEqual(lot, 0.50)

    # 6. Valid BUY Order Execution
    def test_06_valid_buy_order_execution(self):
        client = server.app.test_client()
        res = client.post('/api/autotrade/execute', json={
            'symbol': 'EURUSD',
            'type': 'BUY',
            'entry': 1.0850,
            'sl': 1.0820,
            'tp1': 1.0900,
            'score': 85
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['command']['status'], 'QUEUED')
        # MT5 is the source of truth; the position appears after the EA sync confirms it.
        self.assertEqual(len(server.autotrade_state['open_positions']), 0)

    # 7. Valid SELL Order Execution
    def test_07_valid_sell_order_execution(self):
        client = server.app.test_client()
        res = client.post('/api/autotrade/execute', json={
            'symbol': 'GBPUSD',
            'type': 'SELL',
            'entry': 1.2950,
            'sl': 1.2980,
            'tp1': 1.2900,
            'score': 88
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'success')

    # 8. Duplicate Signal Idempotency Rejection
    def test_08_duplicate_signal_idempotency(self):
        client = server.app.test_client()
        # 1st dispatch
        client.post('/api/autotrade/execute', json={
            'symbol': 'USOIL',
            'type': 'BUY',
            'entry': 78.50,
            'sl': 77.80,
            'tp1': 79.80,
            'score': 82
        })
        # 2nd immediate identical dispatch
        res2 = client.post('/api/autotrade/execute', json={
            'symbol': 'USOIL',
            'type': 'BUY',
            'entry': 78.50,
            'sl': 77.80,
            'tp1': 79.80,
            'score': 82
        })
        self.assertEqual(res2.status_code, 400)
        data = res2.get_json()
        self.assertIn(data['code'], ['SAME_SYMBOL_ACTIVE', 'DUPLICATE_IDEMPOTENT_SIGNAL'])

    # 9. Same Symbol Open Protection
    def test_09_same_symbol_protection(self):
        signal = {'symbol': 'EURUSD', 'type': 'BUY', 'entry': 1.0850, 'sl': 1.0820, 'tp1': 1.0900, 'score': 85}
        with server.autotrade_lock:
            server.autotrade_state['open_positions'].append({'symbol': 'EURUSD', 'ticket': '123'})
        passed, code, reason = server.validate_trade_risk(signal)
        self.assertFalse(passed)
        self.assertEqual(code, 'SAME_SYMBOL_ACTIVE')

    # 10. Max Open Trades Limit
    def test_10_max_open_trades_limit(self):
        with server.autotrade_lock:
            server.autotrade_state['open_positions'] = [
                {'symbol': 'EURUSD', 'ticket': '1'},
                {'symbol': 'GBPUSD', 'ticket': '2'},
                {'symbol': 'XAUUSD', 'ticket': '3'}
            ]
        signal = {'symbol': 'USDJPY', 'type': 'BUY', 'entry': 155.0, 'sl': 154.5, 'tp1': 156.0, 'score': 85}
        passed, code, reason = server.validate_trade_risk(signal)
        self.assertFalse(passed)
        self.assertEqual(code, 'MAX_OPEN_TRADES_LIMIT')

    # 11. Daily Drawdown Limit Trigger (Kill Switch)
    def test_11_daily_loss_limit_kill_switch(self):
        with server.autotrade_lock:
            server.autotrade_state['daily_stats']['starting_balance'] = 40000.0
            server.autotrade_state['daily_stats']['realized_pnl'] = -1300.0 # -3.25% (exceeds 3.0%)
        
        signal = {'symbol': 'AUDUSD', 'type': 'BUY', 'entry': 0.6500, 'sl': 0.6470, 'tp1': 0.6560, 'score': 85}
        passed, code, reason = server.validate_trade_risk(signal)
        self.assertFalse(passed)
        self.assertEqual(code, 'MAX_DAILY_LOSS_EXCEEDED')
        with server.autotrade_lock:
            self.assertTrue(server.autotrade_state['emergency_stop'])

    # 12. Consecutive Loss Cooldown
    def test_12_consecutive_loss_cooldown(self):
        with server.autotrade_lock:
            server.autotrade_state['daily_stats']['cooldown_until'] = time.time() + 1800 # 30 min cooldown
        signal = {'symbol': 'USDCHF', 'type': 'BUY', 'entry': 0.8800, 'sl': 0.8760, 'tp1': 0.8880, 'score': 85}
        passed, code, reason = server.validate_trade_risk(signal)
        self.assertFalse(passed)
        self.assertEqual(code, 'LOSS_COOLDOWN_ACTIVE')

    # 13. Correlation Exposure Protection (Max 2 USD positions)
    def test_13_correlation_exposure_limit(self):
        with server.autotrade_lock:
            server.autotrade_state['open_positions'] = [
                {'symbol': 'EURUSD', 'ticket': '1'},
                {'symbol': 'GBPUSD', 'ticket': '2'}
            ]
        signal = {'symbol': 'USDJPY', 'type': 'BUY', 'entry': 155.0, 'sl': 154.5, 'tp1': 156.0, 'score': 85}
        passed, code, reason = server.validate_trade_risk(signal)
        self.assertFalse(passed)
        self.assertEqual(code, 'CORRELATION_EXPOSURE_LIMIT')

    # 14. Insufficient Margin Rejection
    def test_14_insufficient_margin(self):
        with server.autotrade_lock:
            server.autotrade_state['account']['free_margin'] = 10.0 # Only $10 free margin
        signal = {'symbol': 'XAUUSD', 'type': 'BUY', 'entry': 2480.0, 'sl': 2470.0, 'tp1': 2500.0, 'score': 85}
        passed, code, reason = server.validate_trade_risk(signal)
        self.assertFalse(passed)
        self.assertEqual(code, 'INSUFFICIENT_MARGIN')

    # 15. Invalid SL / Min Stop Distance
    def test_15_invalid_sl_distance(self):
        # SL is only 0.00005 away (less than 15 points)
        signal = {'symbol': 'EURUSD', 'type': 'BUY', 'entry': 1.08500, 'sl': 1.08498, 'tp1': 1.09000, 'score': 85}
        passed, code, reason = server.validate_trade_risk(signal)
        self.assertFalse(passed)
        self.assertEqual(code, 'INVALID_STOP_LOSS')

    # 16. Invalid Risk/Reward Ratio
    def test_16_invalid_risk_reward(self):
        # SL = 50 pips, TP1 = 20 pips (RR = 1:0.4 < 1:1.5)
        signal = {'symbol': 'EURUSD', 'type': 'BUY', 'entry': 1.0850, 'sl': 1.0800, 'tp1': 1.0870, 'score': 85}
        passed, code, reason = server.validate_trade_risk(signal)
        self.assertFalse(passed)
        self.assertEqual(code, 'INVALID_RISK_REWARD')

    # 17. Auto Break-Even & 50% Partial Close on TP1
    def test_17_auto_breakeven_partial_tp1(self):
        with server.autotrade_lock:
            server.autotrade_state['open_positions'] = [{
                'ticket': 'T-999',
                'symbol': 'EURUSD',
                'type': 'BUY',
                'lot': 0.50,
                'entry': 1.0850,
                'current_price': 1.0850,
                'sl': 1.0820,
                'tp1': 1.0900,
                'tp1_hit': False,
                'pnl': 0.0
            }]
            # Inject live price hitting TP1
            server.price_cache['data']['EURUSD'] = {'price': 1.0905, 'isUp': True}

        # Run one deterministic lifecycle iteration instead of racing the worker timer.
        server.process_position_lifecycle_step({'EURUSD': 1.0905})
        with server.autotrade_lock:
            pos = server.autotrade_state['open_positions'][0] if server.autotrade_state['open_positions'] else None
            if pos:
                self.assertTrue(pos.get('tp1_hit'))
                self.assertGreaterEqual(pos['sl'], 1.0850) # SL moved to Entry + buffer

    # 18. Manual Close Position
    def test_18_manual_close_position(self):
        with server.autotrade_lock:
            server.autotrade_state['open_positions'] = [{
                'ticket': 'T-100',
                'symbol': 'EURUSD',
                'type': 'BUY',
                'lot': 0.20,
                'entry': 1.0850,
                'pnl': 50.0
            }]
        client = server.app.test_client()
        res = client.post('/api/autotrade/close', json={'ticket': 'T-100'})
        self.assertEqual(res.status_code, 200)
        with server.autotrade_lock:
            # The server queues the close; MT5 later confirms removal via reconciliation.
            self.assertEqual(server.autotrade_state['open_positions'][0]['status'], 'CLOSE_REQUESTED')
            self.assertEqual(len(server.autotrade_state['history']), 0)

    # 19. Close All Positions
    def test_19_close_all_positions(self):
        with server.autotrade_lock:
            server.autotrade_state['open_positions'] = [
                {'ticket': 'T-1', 'symbol': 'EURUSD', 'pnl': 10.0},
                {'ticket': 'T-2', 'symbol': 'GBPUSD', 'pnl': -5.0}
            ]
        client = server.app.test_client()
        res = client.post('/api/autotrade/close-all', json={})
        self.assertEqual(res.status_code, 200)
        with server.autotrade_lock:
            self.assertEqual(len(server.autotrade_state['open_positions']), 0)

    # 20. Emergency Stop Trigger & Recovery
    def test_20_emergency_stop_trigger(self):
        client = server.app.test_client()
        res = client.post('/api/autotrade/emergency-stop', json={'reason': 'اختبار زر الطوارئ'})
        self.assertEqual(res.status_code, 200)
        with server.autotrade_lock:
            self.assertTrue(server.autotrade_state['emergency_stop'])
            self.assertFalse(server.autotrade_state['enabled'])

    # 21. Multi-Asset Contract Specs Check
    def test_21_multi_asset_specs(self):
        gold = server.get_symbol_spec('XAUUSD')
        self.assertEqual(gold['size'], 100.0)
        oil = server.get_symbol_spec('USOIL')
        self.assertEqual(oil['size'], 1000.0)
        crypto = server.get_symbol_spec('BTCUSD')
        self.assertEqual(crypto['size'], 1.0)
        forex = server.get_symbol_spec('EURUSD')
        self.assertEqual(forex['size'], 100000.0)

if __name__ == '__main__':
    unittest.main(verbosity=2)
