import React, { useEffect, useState } from 'react';

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

  return (
    <header className="top-header">
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
  );
}
