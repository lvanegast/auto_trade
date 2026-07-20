import React, { useState, useEffect } from 'react';

export default function BottomTabsArea({ positions, trades, portfolio, statusData }) {
  const [activeTab, setActiveTab] = useState('open-orders');
  const [posSubTab, setPosSubTab] = useState('open');
  const [logs, setLogs] = useState([]);
  const [metrics, setMetrics] = useState(null);

  // Fetch logs and metrics periodically
  useEffect(() => {
    const fetchLogsAndMetrics = async () => {
      try {
        const resLogs = await fetch('/api/logs?limit=50');
        if (resLogs.ok) {
          const lData = await resLogs.json();
          setLogs(lData);
        }
        const resMetrics = await fetch('/api/metrics');
        if (resMetrics.ok) {
          const mData = await resMetrics.json();
          setMetrics(mData);
        }
      } catch (_) {}
    };

    fetchLogsAndMetrics();
    const interval = setInterval(fetchLogsAndMetrics, 3000);
    return () => clearInterval(interval);
  }, []);

  const openPositions = positions.filter((p) => p.status === 'OPEN');
  const closedPositions = positions.filter((p) => p.status === 'CLOSED');

  const rsiVal = statusData?.rsi || 50.0;
  const ema9 = statusData?.ema9 || 0.0;
  const ema21 = statusData?.ema21 || 0.0;

  const getRsiBadgeClass = (val) => {
    if (val >= 70) return { text: 'SOBRECOMPRA', color: '#f84960' };
    if (val <= 30) return { text: 'SOBREVENTA', color: '#02c076' };
    return { text: 'NEUTRAL', color: '#00e6ff' };
  };

  const rsiBadge = getRsiBadgeClass(rsiVal);

  return (
    <div className="bottom-panel" style={{ flex: 1, background: '#161a1e', borderTop: '1px solid #242c35', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Tabs Header Bar */}
      <div style={{ display: 'flex', gap: '8px', borderBottom: '1px solid #242c35', padding: '8px 12px', background: '#181a20', overflowX: 'auto' }}>
        {[
          { id: 'open-orders', label: 'Órdenes Abiertas' },
          { id: 'positions', label: `Posiciones (${openPositions.length})` },
          { id: 'portfolio', label: 'Mi Portafolio' },
          { id: 'trades', label: `Historial (${trades.length})` },
          { id: 'logs', label: 'Consola de Eventos' },
          { id: 'indicators', label: 'Indicadores Técnicos' },
          { id: 'arbitrage', label: 'Arbitraje Cross' },
          { id: 'metrics', label: 'Métricas' },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            style={{
              background: activeTab === tab.id ? '#20262d' : 'transparent',
              color: activeTab === tab.id ? '#00e6ff' : '#848e9c',
              border: activeTab === tab.id ? '1px solid #00e6ff' : 'none',
              padding: '6px 12px',
              borderRadius: '4px',
              fontWeight: 600,
              fontSize: '12px',
              cursor: 'pointer',
              whiteSpace: 'nowrap',
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tabs Content Container */}
      <div style={{ flex: 1, padding: '12px', overflowY: 'auto', fontSize: '12px', fontFamily: 'JetBrains Mono' }}>
        
        {/* Tab 1: Órdenes Abiertas */}
        {activeTab === 'open-orders' && (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ color: '#848e9c', textAlign: 'left', borderBottom: '1px solid #20262d' }}>
                <th style={{ padding: '6px' }}>Fecha / Hora</th>
                <th>Par</th>
                <th>Tipo</th>
                <th>Precio</th>
                <th>Monto</th>
                <th>Total</th>
                <th>Estado</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td colSpan="7" style={{ padding: '15px', textAlign: 'center', color: '#474f57' }}>
                  No hay órdenes abiertas en espera.
                </td>
              </tr>
            </tbody>
          </table>
        )}

        {/* Tab 2: Posiciones */}
        {activeTab === 'positions' && (
          <div>
            <div style={{ display: 'flex', gap: '10px', marginBottom: '10px', borderBottom: '1px solid #20262d', paddingBottom: '6px' }}>
              <button
                onClick={() => setPosSubTab('open')}
                style={{ background: 'none', color: posSubTab === 'open' ? '#00e6ff' : '#848e9c', fontWeight: 600 }}
              >
                Abiertas ({openPositions.length})
              </button>
              <button
                onClick={() => setPosSubTab('closed')}
                style={{ background: 'none', color: posSubTab === 'closed' ? '#00e6ff' : '#848e9c', fontWeight: 600 }}
              >
                Cerradas ({closedPositions.length})
              </button>
              <button
                onClick={() => setPosSubTab('history')}
                style={{ background: 'none', color: posSubTab === 'history' ? '#00e6ff' : '#848e9c', fontWeight: 600 }}
              >
                Historial Completo
              </button>
            </div>

            {posSubTab === 'open' && (
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ color: '#848e9c', textAlign: 'left', borderBottom: '1px solid #20262d' }}>
                    <th style={{ padding: '6px' }}>ID</th>
                    <th>Símbolo</th>
                    <th>Lado</th>
                    <th>Entrada</th>
                    <th>Estado</th>
                    <th>Fecha</th>
                  </tr>
                </thead>
                <tbody>
                  {openPositions.length === 0 ? (
                    <tr><td colSpan="6" style={{ padding: '15px', textAlign: 'center', color: '#474f57' }}>No hay posiciones abiertas activas.</td></tr>
                  ) : (
                    openPositions.map((p) => (
                      <tr key={p.id} style={{ borderBottom: '1px solid #20262d' }}>
                        <td style={{ padding: '6px' }}>#{p.id}</td>
                        <td>{p.symbol}</td>
                        <td style={{ color: p.side === 'BUY' ? '#02c076' : '#f84960', fontWeight: 600 }}>{p.side}</td>
                        <td>${parseFloat(p.entry_price).toFixed(4)}</td>
                        <td><span style={{ background: 'rgba(2,192,118,0.15)', color: '#02c076', padding: '2px 6px', borderRadius: '4px' }}>{p.status}</span></td>
                        <td style={{ color: '#848e9c' }}>{new Date(p.entry_time).toLocaleTimeString()}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            )}

            {posSubTab === 'closed' && (
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ color: '#848e9c', textAlign: 'left', borderBottom: '1px solid #20262d' }}>
                    <th style={{ padding: '6px' }}>ID</th>
                    <th>Símbolo</th>
                    <th>Lado</th>
                    <th>Entrada</th>
                    <th>Salida</th>
                    <th>PnL</th>
                    <th>Razón</th>
                  </tr>
                </thead>
                <tbody>
                  {closedPositions.length === 0 ? (
                    <tr><td colSpan="7" style={{ padding: '15px', textAlign: 'center', color: '#474f57' }}>No hay posiciones cerradas.</td></tr>
                  ) : (
                    closedPositions.map((p) => (
                      <tr key={p.id} style={{ borderBottom: '1px solid #20262d' }}>
                        <td style={{ padding: '6px' }}>#{p.id}</td>
                        <td>{p.symbol}</td>
                        <td style={{ color: p.side === 'BUY' ? '#02c076' : '#f84960', fontWeight: 600 }}>{p.side}</td>
                        <td>${parseFloat(p.entry_price).toFixed(4)}</td>
                        <td>${parseFloat(p.exit_price || 0).toFixed(4)}</td>
                        <td style={{ color: (p.pnl || 0) >= 0 ? '#02c076' : '#f84960', fontWeight: 700 }}>
                          ${parseFloat(p.pnl || 0).toFixed(2)} ({parseFloat(p.pnl_pct || 0).toFixed(2)}%)
                        </td>
                        <td style={{ color: '#848e9c' }}>{p.exit_reason || 'SIGNAL'}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            )}

            {posSubTab === 'history' && (
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ color: '#848e9c', textAlign: 'left', borderBottom: '1px solid #20262d' }}>
                    <th style={{ padding: '6px' }}>ID</th>
                    <th>Worker</th>
                    <th>Símbolo</th>
                    <th>Lado</th>
                    <th>Entrada</th>
                    <th>Salida</th>
                    <th>Estado</th>
                    <th>PnL</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p) => (
                    <tr key={p.id} style={{ borderBottom: '1px solid #20262d' }}>
                      <td style={{ padding: '6px' }}>#{p.id}</td>
                      <td>{p.worker_id}</td>
                      <td>{p.symbol}</td>
                      <td style={{ color: p.side === 'BUY' ? '#02c076' : '#f84960', fontWeight: 600 }}>{p.side}</td>
                      <td>${parseFloat(p.entry_price).toFixed(4)}</td>
                      <td>${parseFloat(p.exit_price || 0).toFixed(4)}</td>
                      <td>{p.status}</td>
                      <td style={{ color: (p.pnl || 0) >= 0 ? '#02c076' : '#f84960', fontWeight: 700 }}>
                        ${parseFloat(p.pnl || 0).toFixed(2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {/* Tab 3: Mi Portafolio */}
        {activeTab === 'portfolio' && (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ color: '#848e9c', textAlign: 'left', borderBottom: '1px solid #20262d' }}>
                <th style={{ padding: '6px' }}>Activo</th>
                <th>Disponible</th>
                <th>En Orden (Bloqueado)</th>
                <th>Valor Estimado (USD)</th>
              </tr>
            </thead>
            <tbody>
              {portfolio.length === 0 ? (
                <tr><td colSpan="4" style={{ padding: '15px', textAlign: 'center', color: '#474f57' }}>No hay saldos registrados.</td></tr>
              ) : (
                portfolio.map((item, idx) => (
                  <tr key={idx} style={{ borderBottom: '1px solid #20262d' }}>
                    <td style={{ padding: '6px', fontWeight: 700, color: '#00e6ff' }}>{item.asset}</td>
                    <td>{parseFloat(item.free_balance).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}</td>
                    <td style={{ color: '#848e9c' }}>{parseFloat(item.locked_balance || 0).toFixed(2)}</td>
                    <td>${parseFloat(item.free_balance).toFixed(2)} USD</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        )}

        {/* Tab 4: Historial de Operaciones */}
        {activeTab === 'trades' && (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ color: '#848e9c', textAlign: 'left', borderBottom: '1px solid #20262d' }}>
                <th style={{ padding: '6px' }}>ID</th>
                <th>Símbolo</th>
                <th>Tipo</th>
                <th>Precio</th>
                <th>Monto</th>
                <th>Total</th>
                <th>Fecha</th>
              </tr>
            </thead>
            <tbody>
              {trades.length === 0 ? (
                <tr><td colSpan="7" style={{ padding: '15px', textAlign: 'center', color: '#474f57' }}>No hay transacciones.</td></tr>
              ) : (
                trades.map((t) => (
                  <tr key={t.id} style={{ borderBottom: '1px solid #20262d' }}>
                    <td style={{ padding: '6px' }}>#{t.id}</td>
                    <td>{t.symbol}</td>
                    <td style={{ color: t.side === 'BUY' ? '#02c076' : '#f84960', fontWeight: 600 }}>{t.side}</td>
                    <td>${parseFloat(t.price).toFixed(4)}</td>
                    <td>{parseFloat(t.amount).toFixed(4)}</td>
                    <td>${parseFloat(t.total).toFixed(2)}</td>
                    <td style={{ color: '#848e9c' }}>{new Date(t.timestamp).toLocaleTimeString()}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        )}

        {/* Tab 5: Consola de Eventos (Logs) */}
        {activeTab === 'logs' && (
          <div style={{ background: '#0b0e11', padding: '10px', borderRadius: '6px', maxHeight: '180px', overflowY: 'auto' }}>
            {logs.length === 0 ? (
              <div style={{ color: '#474f57' }}>Esperando logs del sistema...</div>
            ) : (
              logs.map((l) => (
                <div key={l.id} style={{ marginBottom: '4px', lineHeight: 1.4 }}>
                  <span style={{ color: '#848e9c', marginRight: '8px' }}>[{new Date(l.timestamp).toLocaleTimeString()}]</span>
                  <span style={{ color: l.level === 'ERROR' ? '#f84960' : l.level === 'WARNING' ? '#ff9900' : '#02c076', fontWeight: 700, marginRight: '8px' }}>
                    [{l.level}]
                  </span>
                  <span style={{ color: '#eaecef' }}>{l.message}</span>
                </div>
              ))
            )}
          </div>
        )}

        {/* Tab 6: Indicadores Técnicos */}
        {activeTab === 'indicators' && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px' }}>
            <div style={{ background: '#20262d', padding: '12px', borderRadius: '6px', border: '1px solid #242c35' }}>
              <div style={{ fontSize: '11px', color: '#848e9c' }}>EMA 9 (Rápida)</div>
              <div style={{ fontSize: '20px', fontWeight: 700, color: '#00e6ff', marginTop: '4px' }}>
                {ema9 > 0 ? `$${ema9.toFixed(2)}` : '-'}
              </div>
            </div>
            <div style={{ background: '#20262d', padding: '12px', borderRadius: '6px', border: '1px solid #242c35' }}>
              <div style={{ fontSize: '11px', color: '#848e9c' }}>EMA 21 (Lenta)</div>
              <div style={{ fontSize: '20px', fontWeight: 700, color: '#ff9900', marginTop: '4px' }}>
                {ema21 > 0 ? `$${ema21.toFixed(2)}` : '-'}
              </div>
            </div>
            <div style={{ background: '#20262d', padding: '12px', borderRadius: '6px', border: '1px solid #242c35' }}>
              <div style={{ fontSize: '11px', color: '#848e9c', display: 'flex', justifyContent: 'space-between' }}>
                <span>RSI 14</span>
                <span style={{ color: rsiBadge.color, fontWeight: 700 }}>{rsiBadge.text}</span>
              </div>
              <div style={{ fontSize: '20px', fontWeight: 700, color: '#fff', marginTop: '4px' }}>
                {rsiVal.toFixed(1)}
              </div>
              <div style={{ width: '100%', height: '4px', background: '#363c4e', borderRadius: '2px', marginTop: '8px', overflow: 'hidden' }}>
                <div style={{ width: `${rsiVal}%`, height: '100%', background: rsiBadge.color }} />
              </div>
            </div>
          </div>
        )}

        {/* Tab 7: Arbitraje Cross */}
        {activeTab === 'arbitrage' && (
          <div>
            <div style={{ background: 'linear-gradient(135deg, rgba(2, 192, 118, 0.15), rgba(0, 230, 255, 0.10))', border: '1px solid #02c076', padding: '10px', borderRadius: '6px', marginBottom: '10px' }}>
              <strong style={{ color: '#02c076', fontSize: '13px' }}>🔔 Monitor de Arbitraje Cuantitativo 1xN</strong>
              <p style={{ color: '#eaecef', fontSize: '11px', marginTop: '4px' }}>
                Escaneando desbalances de probabilidad entre Polymarket CLOB y Binance Spot.
              </p>
            </div>
          </div>
        )}

        {/* Tab 8: Métricas de Performance */}
        {activeTab === 'metrics' && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '10px' }}>
            <div style={{ background: '#20262d', padding: '10px', borderRadius: '6px' }}>
              <div style={{ fontSize: '10px', color: '#848e9c' }}>TOTAL TRADES</div>
              <div style={{ fontSize: '18px', fontWeight: 700, color: '#fff' }}>{metrics?.total_trades || 0}</div>
            </div>
            <div style={{ background: '#20262d', padding: '10px', borderRadius: '6px' }}>
              <div style={{ fontSize: '10px', color: '#848e9c' }}>WIN RATE</div>
              <div style={{ fontSize: '18px', fontWeight: 700, color: '#02c076' }}>{((metrics?.win_rate || 0) * 100).toFixed(1)}%</div>
            </div>
            <div style={{ background: '#20262d', padding: '10px', borderRadius: '6px' }}>
              <div style={{ fontSize: '10px', color: '#848e9c' }}>TOTAL P&L</div>
              <div style={{ fontSize: '18px', fontWeight: 700, color: (metrics?.total_pnl || 0) >= 0 ? '#02c076' : '#f84960' }}>
                ${(metrics?.total_pnl || 0).toFixed(2)}
              </div>
            </div>
            <div style={{ background: '#20262d', padding: '10px', borderRadius: '6px' }}>
              <div style={{ fontSize: '10px', color: '#848e9c' }}>PROFIT FACTOR</div>
              <div style={{ fontSize: '18px', fontWeight: 700, color: '#ff9900' }}>{(metrics?.profit_factor || 0).toFixed(2)}</div>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
