import React, { useEffect, useState } from 'react';

const getAssetBalance = (portfolio, assetSymbol) => {
  if (!portfolio) return 0.0;
  if (Array.isArray(portfolio)) {
    const found = portfolio.find((p) => p.asset === assetSymbol);
    return found ? parseFloat(found.free_balance || 0) : 0.0;
  }
  if (typeof portfolio === 'object') {
    const item = portfolio[assetSymbol] || portfolio[assetSymbol.toLowerCase()];
    if (item) return parseFloat(item.free_balance || item.free || item.balance || 0);
  }
  return 0.0;
};

export default function HeaderTicker({ workers, activeWorkerId, onSelectWorker, statusData, isOnline }) {
  const [countdown, setCountdown] = useState(null);

  useEffect(() => {
    if (!statusData?.expiration) {
      setCountdown(null);
      return;
    }

    const expTime = new Date(statusData.expiration).getTime();
    const interval = setInterval(() => {
      const now = Date.now();
      const diffMs = expTime - now;

      if (diffMs <= 0) {
        setCountdown('EXPIRADO');
      } else {
        const secs = Math.floor(diffMs / 1000);
        const days = Math.floor(secs / 86400);
        const hours = Math.floor((secs % 86400) / 3600);
        const mins = Math.floor((secs % 3600) / 60);

        let str = '';
        if (days > 0) str = `${days}d ${hours}h ${mins}m`;
        else if (hours > 0) str = `${hours}h ${mins}m ${secs % 60}s`;
        else str = `${mins}m ${secs % 60}s`;
        setCountdown(str.toUpperCase());
      }
    }, 1000);

    return () => clearInterval(interval);
  }, [statusData?.expiration]);

  const price = statusData?.last_price || 0.0;
  const isForexOrEvent = statusData?.feeder_type === 'kalshi' || statusData?.feeder_type === 'polymarket';
  const decimals = isForexOrEvent ? 4 : 2;

  // Calculo de balances para la barra de estadísticas
  const usdBal = getAssetBalance(statusData?.portfolio, 'USD');
  const btcBal = getAssetBalance(statusData?.portfolio, 'BTC');
  const totalBal = usdBal + btcBal * price;
  const unrealizedPnL = statusData?.unrealized_pnl || 0.0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', background: '#161a1e', borderBottom: '1px solid #242c35' }}>
      {/* Top Header Line */}
      <header className="top-header" style={{ borderBottom: '1px solid #20262d' }}>
        <div className="header-left">
          <div className="logo">
            <span className="logo-accent">▲</span> Auto<span>Trade</span>
          </div>
          <div className="divider"></div>
          <div className="symbol-tabs">
            {workers.map((w) => (
              <button
                key={w.worker_id}
                className={`tab-btn ${w.worker_id === activeWorkerId ? 'active' : ''} ${w.is_running ? 'worker-running' : ''}`}
                onClick={() => onSelectWorker(w.worker_id)}
              >
                {w.name}
              </button>
            ))}
          </div>
        </div>

        <div className="header-middle">
          <div className="ticker-item">
            <span className="ticker-label">Precio</span>
            <span className="ticker-val highlight-blue">${price.toFixed(decimals)}</span>
          </div>
          <div className="ticker-item">
            <span className="ticker-label">Cambio 24h</span>
            <span className="ticker-val text-success">+1.42%</span>
          </div>
          <div className="ticker-item">
            <span className="ticker-label">Máx 24h</span>
            <span className="ticker-val">${(price * 1.02).toFixed(decimals)}</span>
          </div>
          <div className="ticker-item">
            <span className="ticker-label">Mín 24h</span>
            <span className="ticker-val">${(price * 0.98).toFixed(decimals)}</span>
          </div>
          {countdown && (
            <div className="ticker-item">
              <span className="ticker-label">Vencimiento</span>
              <span className="ticker-val" style={{ color: '#f0b90b', fontWeight: 600 }}>
                {countdown}
              </span>
            </div>
          )}
        </div>

        <div className="header-right">
          <div className="connection-status">
            <span className={`status-dot ${isOnline ? 'online' : 'offline'}`}></span>
            <span className="status-lbl">{isOnline ? 'ONLINE' : 'OFFLINE'}</span>
          </div>
          <div className="mode-badge">{statusData?.trading_mode || 'SIMULACIÓN'}</div>
        </div>
      </header>

      {/* Balance Stats Bar */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '10px', padding: '8px 15px', background: '#12161a', fontSize: '11px', fontFamily: 'JetBrains Mono' }}>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <span style={{ color: '#848e9c' }}>Disponible Quote (USD)</span>
          <strong style={{ fontSize: '13px', color: '#eaecef' }}>${usdBal.toFixed(2)}</strong>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <span style={{ color: '#848e9c' }}>Disponible Base (BTC)</span>
          <strong style={{ fontSize: '13px', color: '#eaecef' }}>{btcBal.toFixed(6)}</strong>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <span style={{ color: '#848e9c' }}>Ganancia No Realizada (PnL)</span>
          <strong style={{ fontSize: '13px', color: unrealizedPnL >= 0 ? '#02c076' : '#f84960' }}>
            ${unrealizedPnL.toFixed(2)}
          </strong>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <span style={{ color: '#848e9c' }}>Balance Total Estimado</span>
          <strong style={{ fontSize: '13px', color: '#00e6ff' }}>${totalBal.toFixed(2)}</strong>
        </div>
      </div>
    </div>
  );
}
