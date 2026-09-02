document.addEventListener('DOMContentLoaded', () => {
    const AutoTrade = {
        apiBase: window.location.protocol === 'http:' || window.location.protocol === 'https:'
                 ? window.location.origin
                 : 'http://187.77.174.215:8081',

        state: {
            enabled: false,
            mode: 'demo',
            emergency_stop: false,
            emergency_reason: '',
            is_heartbeat_fresh: false,
            account: {
                connected: false,
                server: 'JustMarkets-Demo',
                login: '',
                balance: 0.0,
                equity: 0.0,
                margin: 0.0,
                free_margin: 0.0,
                margin_level: 0.0,
                currency: 'USD',
                last_sync_time: '',
                latency_ms: 0.0
            },
            risk_config: {
                risk_percent: 1.0,
                max_lot_cap: 0.50,
                max_open_trades: 3,
                min_score: 75,
                auto_breakeven: true,
                partial_tp1_close_pct: 50
            },
            daily_stats: {
                trades_opened: 0,
                realized_pnl: 0.0,
                floating_pnl: 0.0
            },
            open_positions: [],
            history: [],
            audit_logs: []
        },

        async syncStatus() {
            try {
                const savedLogin = localStorage.getItem('mp_at_login') || document.getElementById('at-login-num')?.value.trim() || '';
                const queryParam = savedLogin ? `?login=${encodeURIComponent(savedLogin)}` : '';
                const headers = savedLogin ? { 'X-Account-Login': savedLogin } : {};

                const [statusRes, posRes, histRes, logsRes] = await Promise.all([
                    fetch(`${this.apiBase}/api/autotrade/status${queryParam}`, { headers }),
                    fetch(`${this.apiBase}/api/autotrade/positions${queryParam}`, { headers }),
                    fetch(`${this.apiBase}/api/autotrade/history${queryParam}`, { headers }),
                    fetch(`${this.apiBase}/api/autotrade/audit-logs${queryParam}`, { headers })
                ]);

                if (statusRes.ok) {
                    const data = await statusRes.json();
                    if (data.status === 'success') {
                        this.state.enabled = data.enabled;
                        this.state.mode = data.mode;
                        this.state.emergency_stop = data.emergency_stop;
                        this.state.emergency_reason = data.emergency_reason;
                        this.state.is_heartbeat_fresh = data.is_heartbeat_fresh;
                        this.state.account = data.account || this.state.account;
                        this.state.risk_config = data.risk_config || this.state.risk_config;
                        this.state.daily_stats = data.daily_stats || this.state.daily_stats;
                    }
                }

                if (posRes.ok) {
                    const pData = await posRes.json();
                    if (pData.status === 'success') {
                        this.state.open_positions = pData.positions || [];
                    }
                }

                if (histRes.ok) {
                    const hData = await histRes.json();
                    if (hData.status === 'success') {
                        this.state.history = hData.history || [];
                    }
                }

                if (logsRes.ok) {
                    const lData = await logsRes.json();
                    if (lData.status === 'success') {
                        this.state.audit_logs = lData.logs || [];
                    }
                }

                
            // 7. Auto-populate Connection Form Fields if not actively focused
            const acc = this.state.account || {};
            const serverInput = document.getElementById('at-server-name');
            const loginInput = document.getElementById('at-login-num');
            if (serverInput && acc.server && !serverInput.matches(':focus')) {
                serverInput.value = acc.server;
            }
            if (loginInput && acc.login && !loginInput.matches(':focus')) {
                loginInput.value = acc.login;
            }

            this.renderUI();
            } catch (e) {
                console.error('syncStatus Error:', e);
                this.state.account.connected = false;
                this.renderUI();
            }
        },

        renderUI() {
            const acc = this.state.account || {};
            const isConnected = acc.connected && this.state.is_heartbeat_fresh;
            const isEnabled = this.state.enabled && !this.state.emergency_stop;

            // 1. Master Toggle & Status Badge
            const masterToggle = document.getElementById('autotrade-master-toggle');
            const masterStatus = document.getElementById('autotrade-master-status');
            if (masterToggle) {
                masterToggle.checked = isEnabled;
            }
            if (masterStatus) {
                if (this.state.emergency_stop) {
                    masterStatus.className = 'badge badge-danger';
                    masterStatus.textContent = '🚨 طوارئ (Kill Switch)';
                } else if (isEnabled) {
                    masterStatus.className = 'badge badge-live';
                    masterStatus.textContent = 'تداول آلي نشط 🟢';
                } else {
                    masterStatus.className = 'badge badge-warning';
                    masterStatus.textContent = 'متوقف مؤقتاً 🔴';
                }
            }

            // 2. Real KPI Cards (Zero Fake Data)
            const kpiBal = document.getElementById('at-balance-val');
            const kpiEq = document.getElementById('at-equity-val');
            const kpiFree = document.getElementById('at-margin-val');
            const kpiFloat = document.getElementById('at-floating-pnl-val');
            const openCountBadge = document.getElementById('at-open-count');

            const openPos = this.state.open_positions || [];
            let totalFloat = 0;
            openPos.forEach(p => { totalFloat += (p.pnl || 0); });

            if (openCountBadge) openCountBadge.textContent = openPos.length;

            if (isConnected && acc.balance > 0) {
                if (kpiBal) kpiBal.textContent = `$${acc.balance.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
                if (kpiEq) kpiEq.textContent = `$${acc.equity.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
                if (kpiFree) kpiFree.textContent = `$${acc.free_margin.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            } else {
                if (kpiBal) kpiBal.textContent = '—';
                if (kpiEq) kpiEq.textContent = '—';
                if (kpiFree) kpiFree.textContent = '—';
            }

            if (kpiFloat) {
                const s = totalFloat >= 0 ? '+' : '';
                kpiFloat.textContent = `${s}$${totalFloat.toFixed(2)}`;
                kpiFloat.style.color = totalFloat >= 0 ? 'var(--success)' : 'var(--danger)';
            }

            // 3. Connection Status Text Banner
            const bridgeText = document.getElementById('at-bridge-status-text');
            const bridgeBanner = document.getElementById('at-bridge-status-banner');
            const syncBadge = document.getElementById('at-last-sync-badge');
            if (bridgeText) {
                if (isConnected) {
                    bridgeText.innerHTML = `مربوط بالبروكر (${acc.server || 'JustMarkets-Demo'} #${acc.login || ''}) 🟢`;
                    bridgeText.className = 'text-success';
                    if (bridgeBanner) {
                        bridgeBanner.style.background = 'rgba(0,230,118,0.1)';
                        bridgeBanner.style.borderColor = 'rgba(0,230,118,0.3)';
                    }
                    if (syncBadge) syncBadge.textContent = `تحديث حي (${acc.last_sync_time || '1s'}) • ${acc.latency_ms || 12}ms`;
                } else {
                    bridgeText.innerHTML = `غير متصل بالوسيط (BROKER DISCONNECTED) 🔴`;
                    bridgeText.className = 'text-danger';
                    if (bridgeBanner) {
                        bridgeBanner.style.background = 'rgba(255,82,82,0.1)';
                        bridgeBanner.style.borderColor = 'rgba(255,82,82,0.3)';
                    }
                    if (syncBadge) syncBadge.textContent = `الإكسبرت غير نشط (Offline)`;
                }
            }

            // 4. Render Live Open Positions Table
            const posTbody = document.getElementById('at-positions-tbody');
            if (posTbody) {
                if (openPos.length === 0) {
                    posTbody.innerHTML = `<tr><td colspan="10" style="padding: 2rem; color: var(--text-secondary);"><i class="fa-solid fa-radar fa-beat text-gold" style="font-size:1.4rem; display:block; margin-bottom:0.4rem;"></i>لا توجد صفقات مفتوحة حالياً. الصفقات الحقيقية والمطابقة من MT5 ستظهر هنا فوراً.</td></tr>`;
                } else {
                    posTbody.innerHTML = openPos.map(p => {
                        const isBuy = p.type === 'BUY';
                        const pClass = (p.pnl || 0) >= 0 ? 'text-success' : 'text-danger';
                        const s = (p.pnl || 0) >= 0 ? '+' : '';
                        return `<tr>
                            <td><strong style="color:var(--text-secondary); font-family:monospace;">#${p.ticket}</strong></td>
                            <td><strong style="color:var(--gold);">${p.symbol}</strong></td>
                            <td><span class="badge ${isBuy ? 'badge-buy' : 'badge-sell'}">${p.type}</span></td>
                            <td><strong>${p.lot}</strong></td>
                            <td>${p.entry}</td>
                            <td><strong>${p.current_price || p.entry}</strong></td>
                            <td class="text-danger">${p.sl}</td>
                            <td class="text-success">${p.tp1}</td>
                            <td><strong class="${pClass}">${s}$${(p.pnl || 0).toFixed(2)}</strong></td>
                            <td><button class="btn btn-sm btn-outline at-close-btn" data-ticket="${p.ticket}" style="border-color:var(--danger); color:var(--danger); padding:0.25rem 0.6rem;"><i class="fa-solid fa-xmark"></i> إغلاق</button></td>
                        </tr>`;
                    }).join('');

                    posTbody.querySelectorAll('.at-close-btn').forEach(btn => {
                        btn.addEventListener('click', (e) => {
                            const ticket = e.currentTarget.getAttribute('data-ticket');
                            this.closePosition(ticket);
                        });
                    });
                }
            }

            // 5. Render Audit Logs Table
            const auditTbody = document.getElementById('at-audit-tbody');
            const logs = this.state.audit_logs || [];
            if (auditTbody) {
                if (logs.length === 0) {
                    auditTbody.innerHTML = `<tr><td colspan="5" style="padding: 1.5rem; color: var(--text-secondary);">لا توجد أحداث مسجلة بعد.</td></tr>`;
                } else {
                    auditTbody.innerHTML = logs.slice(0, 30).map(l => {
                        const isOk = l.event.includes('APPROVED') || l.event.includes('FILLED') || l.event.includes('RECONCILED');
                        const isBad = l.event.includes('REJECTED') || l.event.includes('KILL') || l.event.includes('TIMEOUT');
                        const color = isOk ? 'badge-live' : (isBad ? 'badge-warning' : 'badge-gold');
                        return `<tr>
                            <td style="font-family:monospace; font-size:0.78rem;">${l.time}</td>
                            <td><span class="badge ${color}" style="font-size:0.75rem;">${l.event}</span></td>
                            <td><strong>${l.symbol}</strong></td>
                            <td style="font-family:monospace; font-size:0.78rem;">${l.ticket || '—'}</td>
                            <td style="text-align:right; font-size:0.8rem; color:var(--text-primary);">${l.reason}</td>
                        </tr>`;
                    }).join('');
                }
            }

            // 6. Render Trade History Table
            const histTbody = document.getElementById('at-history-tbody');
            const hist = this.state.history || [];
            if (histTbody) {
                if (hist.length === 0) {
                    histTbody.innerHTML = `<tr><td colspan="9" style="padding: 2rem; color: var(--text-secondary);">لا توجد صفقات مغلقة في هذه الجلسة حتى الآن.</td></tr>`;
                } else {
                    histTbody.innerHTML = hist.slice(0, 30).map(h => {
                        const pClass = (h.pnl || 0) >= 0 ? 'text-success' : 'text-danger';
                        const s = (h.pnl || 0) >= 0 ? '+' : '';
                        return `<tr>
                            <td><strong style="color:var(--text-secondary); font-family:monospace;">#${h.ticket || '—'}</strong></td>
                            <td><strong style="color:var(--gold);">${h.symbol}</strong></td>
                            <td><span class="badge ${h.type === 'BUY' ? 'badge-buy' : 'badge-sell'}">${h.type}</span></td>
                            <td><strong>${h.lot || 0.1}</strong></td>
                            <td>${h.entry || 0}</td>
                            <td>${h.close_price || h.current_price || '—'}</td>
                            <td><span class="badge badge-gold">${h.status || 'CLOSED'}</span></td>
                            <td><strong class="${pClass}">${s}$${(h.pnl || 0).toFixed(2)}</strong></td>
                            <td style="font-family:monospace; font-size:0.78rem;">${h.close_time || h.open_time || '—'}</td>
                        </tr>`;
                    }).join('');
                }
            }
        },

        async toggleAutoTrade(enabled) {
            try {
                const res = await fetch(`${this.apiBase}/api/autotrade/toggle`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ enabled })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    this.syncStatus();
                }
            } catch (e) {
                alert('فشل تغيير حالة التداول الآلي: ' + e.message);
            }
        },

        async pauseNewTrades() {
            try {
                const res = await fetch(`${this.apiBase}/api/autotrade/pause`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                const data = await res.json();
                alert(data.message || 'تم إيقاف فتح صفقات جديدة ⏸️');
                this.syncStatus();
            } catch (e) {
                alert('فشل إيقاف الصفقات: ' + e.message);
            }
        },

        async triggerEmergencyStop() {
            const ok = confirm('🚨 تحذير أمان عالي الخطورة!\n\nهل أنت متأكد تماماً من تفعيل نظام الطوارئ الشامل؟\n\n- سيتم إغلاق جميع الصفقات المفتوحة فوراً في MT5.\n- سيتم تجميد التداول الآلي بالكامل.');
            if (!ok) return;

            const doubleCheck = prompt('للتأكيد النهائي، اكتب كلمة (STOP) بالإنجليزية:');
            if (doubleCheck !== 'STOP') {
                alert('⚠️ تم إلغاء العملية، لم تتم كتابة كلمة STOP بشكل صحيح.');
                return;
            }

            try {
                const res = await fetch(`${this.apiBase}/api/autotrade/emergency-stop`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ reason: 'تفعيل إغلاق الطوارئ الشامل المباشر من المتداول', close_all: true })
                });
                const data = await res.json();
                alert(data.message || '🚨 تم تفعيل إغلاق الطوارئ الشامل');
                this.syncStatus();
            } catch (e) {
                alert('فشل تفعيل نظام الطوارئ: ' + e.message);
            }
        },

        async closePosition(ticket) {
            try {
                const res = await fetch(`${this.apiBase}/api/autotrade/close`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ticket })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    this.syncStatus();
                }
            } catch (e) {
                alert('فشل إغلاق الصفقة: ' + e.message);
            }
        },

        async saveConfig() {
            try {
                const risk_percent = parseFloat(document.getElementById('at-risk-percent')?.value || 1.0);
                const max_lot_cap = parseFloat(document.getElementById('at-max-lot')?.value || 0.50);
                const max_open_trades = parseInt(document.getElementById('at-max-open')?.value || 3);
                const min_score = parseInt(document.getElementById('at-min-score')?.value || 75);
                const auto_breakeven = document.getElementById('at-auto-be')?.checked ?? true;
                const partial_tp1 = document.getElementById('at-partial-tp1')?.checked ?? true;

                const res = await fetch(`${this.apiBase}/api/autotrade/config`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        risk_percent, max_lot_cap, max_open_trades, min_score, auto_breakeven,
                        partial_tp1_close_pct: partial_tp1 ? 50 : 0
                    })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    alert('✅ تم حفظ قواعد إدارة المخاطر وتطبيقها فوراً!');
                    this.syncStatus();
                }
            } catch (e) {
                alert('فشل حفظ الإعدادات: ' + e.message);
            }
        },

        
        disconnectAccount() {
            if (!confirm('هل تريد تسجيل الخروج وفصل هذا الحساب من هذا الجهاز؟')) return;
            localStorage.removeItem('mp_at_server');
            localStorage.removeItem('mp_at_login');
            localStorage.removeItem('mp_at_mode');
            if (document.getElementById('at-server-name')) document.getElementById('at-server-name').value = '';
            if (document.getElementById('at-login-num')) document.getElementById('at-login-num').value = '';
            if (document.getElementById('at-password')) document.getElementById('at-password').value = '';
            this.state.account.connected = false;
            this.state.account.balance = 0.0;
            this.state.open_positions = [];
            this.renderUI();
            alert('✅ تم مسح بيانات الحساب وتسجيل الخروج من هذا الجهاز بنجاح.');
        },

        async connectAccount() {
            const btn = document.getElementById('save-at-connect-btn');
            const origHtml = btn ? btn.innerHTML : '';
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> جاري حفظ ومزامنة الاتصال بالسيرفر...';
            }

            try {
                const server = document.getElementById('at-server-name')?.value.trim() || 'JustMarkets-Demo';
                const login = document.getElementById('at-login-num')?.value.trim() || '2001944351';
                const password = document.getElementById('at-password')?.value || '';
                const mode = document.getElementById('at-trading-mode')?.value || 'demo';

                // Save locally so it never resets on page refresh
                localStorage.setItem('mp_at_server', server);
                localStorage.setItem('mp_at_login', login);
                localStorage.setItem('mp_at_mode', mode);

                if (mode === 'real') {
                    if (!confirm('⚠️ تحذير أمني: أنت على وشك تفعيل التداول على حساب حقيقي (LIVE REAL). هل تريد المتابعة؟')) {
                        if (btn) { btn.disabled = false; btn.innerHTML = origHtml; }
                        return;
                    }
                }

                const ctrl = new AbortController();
                const timeoutId = setTimeout(() => ctrl.abort(), 6000);

                const res = await fetch(`${this.apiBase}/api/autotrade/connect`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ server, login, password, mode }),
                    signal: ctrl.signal
                });
                clearTimeout(timeoutId);

                const data = await res.json();
                if (data.status === 'success') {
                    alert('✅ ' + data.message);
                    this.syncStatus();
                } else {
                    alert('⚠️ تنبيه: ' + (data.message || 'حدث خطأ غير متوقع'));
                }
            } catch (e) {
                if (e.name === 'AbortError' || e.message.includes('fetch')) {
                    alert('⚠️ تم حفظ بيانات الحساب في المتصفح بنجاح!\n\n💡 ملاحظة: جاري محاولة الوصول لسيرفر الباك إند (' + this.apiBase + '). تأكد من تشغيل أمر السيرفر على الـ VPS لبدء تدفق الأرقام الحية.');
                } else {
                    alert('فشل حفظ إعدادات الاتصال: ' + e.message);
                }
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = origHtml;
                }
            }
        },

        async executeSignal(signal) {
            if (!this.state.enabled || this.state.emergency_stop) return;
            try {
                const res = await fetch(`${this.apiBase}/api/autotrade/execute`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        symbol: signal.symbol,
                        type: signal.type,
                        entry: signal.entry,
                        sl: signal.sl,
                        tp1: signal.tp1,
                        tp2: signal.tp2 || 0,
                        tp3: signal.tp3 || 0,
                        score: signal.score || 80,
                        signal_id: signal.id || `${signal.symbol}_${signal.type}_${Date.now()}`
                    })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    console.log(`[AUTOTRADE ORDER DISPATCHED] ${signal.symbol}:`, data.message);
                    this.syncStatus();
                } else {
                    console.log(`[AUTOTRADE RISK REJECTED] ${signal.symbol}:`, data.message);
                }
            } catch (e) {
                console.warn('AutoTrade execute error:', e);
            }
        },

        init() {
            // Restore saved credentials from localStorage
            const savedServer = localStorage.getItem('mp_at_server');
            const savedLogin = localStorage.getItem('mp_at_login');
            const savedMode = localStorage.getItem('mp_at_mode');
            if (savedServer && document.getElementById('at-server-name')) document.getElementById('at-server-name').value = savedServer;
            if (savedLogin && document.getElementById('at-login-num')) document.getElementById('at-login-num').value = savedLogin;
            if (savedMode && document.getElementById('at-trading-mode')) document.getElementById('at-trading-mode').value = savedMode;

            // 1. Modal Open / Close Triggers
            const modal = document.getElementById('autotrade-modal');
            const overlay = document.getElementById('autotrade-modal-overlay');
            const closeBtn = document.getElementById('autotrade-modal-close-btn');

            const openTriggers = [
                document.getElementById('autotrade-panel-btn'),
                document.getElementById('autotrade-btn'),
                document.getElementById('header-autotrade-btn'),
                document.getElementById('nav-autotrade-btn')
            ];

            openTriggers.forEach(btn => {
                if (btn && modal) {
                    btn.addEventListener('click', (e) => {
                        e.preventDefault();
                        modal.style.display = 'flex';
                        this.syncStatus();
                    });
                }
            });

            if (closeBtn && modal) {
                closeBtn.addEventListener('click', () => { modal.style.display = 'none'; });
            }
            if (overlay && modal) {
                overlay.addEventListener('click', () => { modal.style.display = 'none'; });
            }

            // 2. Master Toggle Switch
            const masterToggle = document.getElementById('autotrade-master-toggle');
            if (masterToggle) {
                masterToggle.addEventListener('change', (e) => {
                    this.toggleAutoTrade(e.target.checked);
                });
            }

            // 3. Two-Tier Emergency Controls
            const pauseBtn = document.getElementById('at-pause-btn');
            if (pauseBtn) {
                pauseBtn.addEventListener('click', () => this.pauseNewTrades());
            }

            const emBtn = document.getElementById('at-emergency-btn');
            if (emBtn) {
                emBtn.addEventListener('click', () => this.triggerEmergencyStop());
            }

            // 4. Save Config & Connect Buttons
            const saveCfgBtn = document.getElementById('save-at-config-btn');
            if (saveCfgBtn) {
                saveCfgBtn.addEventListener('click', () => this.saveConfig());
            }

            const saveConnBtn = document.getElementById('save-at-connect-btn');
            if (saveConnBtn) {
                saveConnBtn.addEventListener('click', () => this.connectAccount());
            }

            // 5. Tab Switching inside Modal
            document.querySelectorAll('#autotrade-modal .admin-tab-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    document.querySelectorAll('#autotrade-modal .admin-tab-btn').forEach(b => b.classList.remove('active'));
                    document.querySelectorAll('#autotrade-modal .at-tab-content').forEach(c => { c.style.display = 'none'; });

                    e.currentTarget.classList.add('active');
                    const tabKey = e.currentTarget.getAttribute('data-attab');
                    const targetEl = document.getElementById(`attab-${tabKey}`);
                    if (targetEl) targetEl.style.display = 'block';
                });
            });

            // 6. 2-Second Real-Time Telemetry Polling
            setInterval(() => { this.syncStatus(); }, 2000);
            this.syncStatus();
        }
    };

    // Initialize AutoTrade Controller
    AutoTrade.init();

}); // End DOMContentLoaded
