import React, { useState } from 'react';

export default function PositionsTable({ positions, trades, portfolio }) {
  const [activeTab, setActiveTab] = useState('positions');

  return (
    <div className="bottom-panel" style={{ flex: 1, background: '#161a1e', borderTop: '1px solid #242c35', padding: '10px' }}>
      <div style={{ display: 'flex', gap: '15px', borderBottom: '1px solid #242c35', paddingBottom: '8px', marginBottom: '10px' }}>
        <button
          className={`tab-btn ${activeTab === 'positions' ? 'active' : ''}`}
          onClick={() => setActiveTab('positions')}
          style={{ background: 'none', color: activeTab === 'positions' ? '#00e6ff' : '#848e9c', fontWeight: 600 }}
        >
          Posiciones Abiertas ({positions.length})
        </button>
        <button
          className={`tab-btn ${activeTab === 'trades' ? 'active' : ''}`}
          onClick={() => setActiveTab('trades')}
          style={{ background: 'none', color: activeTab === 'trades' ? '#00e6ff' : '#848e9c', fontWeight: 600 }}
        >
          Historial de Operaciones ({trades.length})
        </button>
        <button
          className={`tab-btn ${activeTab === 'portfolio' ? 'active' : ''}`}
          onClick={() => setActiveTab('portfolio')}
          style={{ background: 'none', color: activeTab === 'portfolio' ? '#00e6ff' : '#848e9c', fontWeight: 600 }}
        >
          Mi Portafolio
        </button>
      </div>

      <div style={{ maxHeight: '180px', overflowY: 'auto', fontSize: '12px', fontFamily: 'JetBrains Mono' }}>
        {activeTab === 'positions' && (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ color: '#848e9c', textAlign: 'left', borderBottom: '1px solid #20262d' }}>
                <th style={{ padding: '6px' }}>ID</th>
                <th>Símbolo</th>
                <th>Lado</th>
                <th>Precio Entrada</th>
                <th>Estado</th>
                <th>Fecha</th>
              </tr>
            </thead>
            <tbody>
              {positions.length === 0 ? (
                <tr><td colSpan="6" style={{ padding: '15px', textAlign: 'center', color: '#474f57' }}>No hay posiciones abiertas activas.</td></tr>
              ) : (
                positions.map((p) => (
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
                <tr><td colSpan="7" style={{ padding: '15px', textAlign: 'center', color: '#474f57' }}>No hay ejecuciones registradas.</td></tr>
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

        {activeTab === 'portfolio' && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: '10px', padding: '10px 0' }}>
            {portfolio.map((item, idx) => (
              <div key={idx} style={{ background: '#20262d', padding: '10px', borderRadius: '6px', border: '1px solid #242c35' }}>
                <div style={{ fontSize: '11px', color: '#848e9c' }}>{item.asset}</div>
                <div style={{ fontSize: '16px', fontWeight: 700, color: '#00e6ff', marginTop: '4px' }}>
                  {parseFloat(item.free_balance).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
