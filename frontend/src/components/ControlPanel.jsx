import React, { useState } from 'react';
import { startBot, stopBot } from '../services/api';

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

export default function ControlPanel({ statusData, activeWorkerId, onSelectWorker, workers }) {
  const [mode, setMode] = useState('manual');
  const [side, setSide] = useState('BUY');
  const [orderType, setOrderType] = useState('MARKET');
  const [price, setPrice] = useState('');
  const [qty, setQty] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const currentPrice = statusData?.last_price || 0.0;
  const feederType = statusData?.feeder_type || 'alpaca';
  const isPredictionMarket = feederType === 'kalshi' || feederType === 'polymarket';
  const quoteAsset = 'USD';
  const baseAsset = statusData?.symbol ? statusData.symbol.split('/')[0] : 'BTC';

  const isBotRunning = statusData?.status === 'ONLINE';

  const handlePctClick = (pct) => {
    const freeBal = getAssetBalance(statusData?.portfolio, 'USD') || 1000.0;
    const effPrice = orderType === 'LIMIT' && parseFloat(price) > 0 ? parseFloat(price) : currentPrice;
    if (effPrice > 0) {
      const targetUsd = freeBal * (pct / 100);
      const calculatedQty = (targetUsd / effPrice).toFixed(4);
      setQty(calculatedQty);
    }
  };

  const calculateTotal = () => {
    const effPrice = orderType === 'LIMIT' && parseFloat(price) > 0 ? parseFloat(price) : currentPrice;
    const numQty = parseFloat(qty) || 0;
    return (effPrice * numQty).toFixed(2);
  };

  const handleExecuteOrder = async () => {
    if (!qty || parseFloat(qty) <= 0) {
      alert('Ingresa una cantidad válida');
      return;
    }
    setIsSubmitting(true);
    try {
      const payload = {
        worker_id: activeWorkerId,
        symbol: statusData?.symbol || 'BTC/USD',
        side: side,
        type: orderType.toLowerCase(),
        price: orderType === 'LIMIT' ? parseFloat(price) : currentPrice,
        amount: parseFloat(qty),
      };
      const res = await fetch('/api/order', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error('Error al enviar la orden');
      const data = await res.json();
      alert(`Orden ejecutada con éxito ID: #${data.order_id || 'OK'}`);
      setQty('');
    } catch (err) {
      alert(err.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleStartBot = async () => {
    try {
      await startBot(activeWorkerId);
      window.location.reload();
    } catch (err) {
      alert(err.message);
    }
  };

  const handleStopBot = async () => {
    try {
      await stopBot(activeWorkerId);
      window.location.reload();
    } catch (err) {
      alert(err.message);
    }
  };

  const filteredWorkers = workers.filter(
    (w) =>
      w.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      w.symbol.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <aside className="workspace-panel terminal-panel" style={{ width: '280px', background: '#161a1e', borderLeft: '1px solid #242c35', display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="panel-header" style={{ padding: '12px 15px', borderBottom: '1px solid #242c35', fontWeight: 700, fontSize: '13px', color: '#eaecef' }}>
        Panel de Control
      </div>

      {/* Toggle Mode: Manual / Auto Bot */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px', padding: '10px', background: '#181a20' }}>
        <button
          onClick={() => setMode('manual')}
          style={{
            padding: '8px',
            borderRadius: '4px',
            fontSize: '12px',
            fontWeight: 600,
            background: mode === 'manual' ? '#20262d' : 'transparent',
            color: mode === 'manual' ? '#00e6ff' : '#848e9c',
            border: mode === 'manual' ? '1px solid #00e6ff' : 'none',
          }}
        >
          Manual
        </button>
        <button
          onClick={() => setMode('auto')}
          style={{
            padding: '8px',
            borderRadius: '4px',
            fontSize: '12px',
            fontWeight: 600,
            background: mode === 'auto' ? '#20262d' : 'transparent',
            color: mode === 'auto' ? '#00e6ff' : '#848e9c',
            border: mode === 'auto' ? '1px solid #00e6ff' : 'none',
          }}
        >
          Auto Bot
        </button>
      </div>

      <div style={{ padding: '12px', flex: 1, overflowY: 'auto' }}>
        {mode === 'manual' ? (
          <div>
            {/* Buy / Sell Tabs */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px', marginBottom: '12px' }}>
              <button
                onClick={() => setSide('BUY')}
                style={{
                  padding: '10px',
                  borderRadius: '4px',
                  fontWeight: 700,
                  fontSize: '13px',
                  background: side === 'BUY' ? '#02c076' : 'rgba(2, 192, 118, 0.15)',
                  color: side === 'BUY' ? '#fff' : '#02c076',
                }}
              >
                Comprar
              </button>
              <button
                onClick={() => setSide('SELL')}
                style={{
                  padding: '10px',
                  borderRadius: '4px',
                  fontWeight: 700,
                  fontSize: '13px',
                  background: side === 'SELL' ? '#f84960' : 'rgba(248, 73, 96, 0.15)',
                  color: side === 'SELL' ? '#fff' : '#f84960',
                }}
              >
                Vender
              </button>
            </div>

            {/* Order Type: Market / Limit */}
            <div style={{ display: 'flex', gap: '10px', marginBottom: '12px', fontSize: '12px' }}>
              <button
                onClick={() => setOrderType('MARKET')}
                style={{
                  background: 'none',
                  color: orderType === 'MARKET' ? '#00e6ff' : '#848e9c',
                  fontWeight: orderType === 'MARKET' ? 700 : 400,
                  borderBottom: orderType === 'MARKET' ? '2px solid #00e6ff' : 'none',
                  paddingBottom: '4px',
                }}
              >
                Mercado
              </button>
              <button
                onClick={() => setOrderType('LIMIT')}
                style={{
                  background: 'none',
                  color: orderType === 'LIMIT' ? '#00e6ff' : '#848e9c',
                  fontWeight: orderType === 'LIMIT' ? 700 : 400,
                  borderBottom: orderType === 'LIMIT' ? '2px solid #00e6ff' : 'none',
                  paddingBottom: '4px',
                }}
              >
                Límite
              </button>
            </div>

            {/* Price Field */}
            <div style={{ marginBottom: '10px' }}>
              <label style={{ fontSize: '11px', color: '#848e9c', display: 'block', marginBottom: '4px' }}>Precio ({quoteAsset})</label>
              <input
                type="number"
                disabled={orderType === 'MARKET'}
                value={orderType === 'MARKET' ? currentPrice.toFixed(4) : price}
                onChange={(e) => setPrice(e.target.value)}
                style={{
                  width: '100%',
                  background: '#20262d',
                  border: '1px solid #242c35',
                  color: '#fff',
                  padding: '8px 10px',
                  borderRadius: '4px',
                  fontSize: '13px',
                  fontFamily: 'JetBrains Mono',
                }}
              />
            </div>

            {/* Quantity Field */}
            <div style={{ marginBottom: '10px' }}>
              <label style={{ fontSize: '11px', color: '#848e9c', display: 'block', marginBottom: '4px' }}>Cantidad ({baseAsset})</label>
              <input
                type="number"
                step="any"
                placeholder="0.00"
                value={qty}
                onChange={(e) => setQty(e.target.value)}
                style={{
                  width: '100%',
                  background: '#20262d',
                  border: '1px solid #242c35',
                  color: '#fff',
                  padding: '8px 10px',
                  borderRadius: '4px',
                  fontSize: '13px',
                  fontFamily: 'JetBrains Mono',
                }}
              />
            </div>

            {/* Shortcut Percentages */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '4px', marginBottom: '12px' }}>
              {[25, 50, 75, 100].map((pct) => (
                <button
                  key={pct}
                  onClick={() => handlePctClick(pct)}
                  style={{
                    background: '#20262d',
                    border: '1px solid #242c35',
                    color: '#848e9c',
                    fontSize: '10px',
                    padding: '4px',
                    borderRadius: '4px',
                  }}
                >
                  {pct}%
                </button>
              ))}
            </div>

            {/* Total Estimate */}
            <div style={{ marginBottom: '15px', padding: '8px', background: '#181a20', borderRadius: '4px', fontSize: '12px', display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: '#848e9c' }}>Total Est.</span>
              <strong style={{ color: '#00e6ff', fontFamily: 'JetBrains Mono' }}>${calculateTotal()} USD</strong>
            </div>

            {/* Execute Button */}
            <button
              onClick={handleExecuteOrder}
              disabled={isSubmitting}
              style={{
                width: '100%',
                padding: '12px',
                borderRadius: '6px',
                fontWeight: 700,
                fontSize: '14px',
                background: side === 'BUY' ? '#02c076' : '#f84960',
                color: '#fff',
              }}
            >
              {side === 'BUY' ? 'Comprar' : 'Vender'} {baseAsset}
            </button>
          </div>
        ) : (
          /* AUTO BOT CONTROL SECTION */
          <div>
            <div style={{ background: '#181a20', padding: '12px', borderRadius: '6px', border: '1px solid #242c35', marginBottom: '15px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                <strong style={{ fontSize: '13px', color: '#fff' }}>{statusData?.name || activeWorkerId}</strong>
                <span
                  style={{
                    fontSize: '10px',
                    fontWeight: 700,
                    padding: '2px 6px',
                    borderRadius: '4px',
                    background: isBotRunning ? 'rgba(2, 192, 118, 0.2)' : 'rgba(248, 73, 96, 0.2)',
                    color: isBotRunning ? '#02c076' : '#f84960',
                  }}
                >
                  {isBotRunning ? 'ONLINE' : 'OFFLINE'}
                </span>
              </div>
              <p style={{ fontSize: '11px', color: '#848e9c', lineHeight: 1.4 }}>
                Ejecuta algoritmos automáticos de arbitraje (Black-Scholes & Kelly Criterion) en tiempo real.
              </p>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '15px' }}>
              <button
                onClick={handleStartBot}
                disabled={isBotRunning}
                style={{
                  padding: '10px',
                  borderRadius: '6px',
                  fontWeight: 700,
                  fontSize: '12px',
                  background: isBotRunning ? '#20262d' : '#02c076',
                  color: '#fff',
                  opacity: isBotRunning ? 0.5 : 1,
                }}
              >
                Iniciar Bot
              </button>
              <button
                onClick={handleStopBot}
                disabled={!isBotRunning}
                style={{
                  padding: '10px',
                  borderRadius: '6px',
                  fontWeight: 700,
                  fontSize: '12px',
                  background: !isBotRunning ? '#20262d' : '#f84960',
                  color: '#fff',
                  opacity: !isBotRunning ? 0.5 : 1,
                }}
              >
                Detener Bot
              </button>
            </div>

            <div style={{ fontSize: '11px', color: '#848e9c', lineHeight: 1.8, background: '#181a20', padding: '10px', borderRadius: '6px' }}>
              <div>Símbolo: <strong style={{ color: '#fff' }}>{statusData?.symbol || '-'}</strong></div>
              <div>Estrategia: <strong style={{ color: '#00e6ff' }}>{statusData?.strategy_name || 'Spot-Arb'}</strong></div>
              <div>Feeder: <strong style={{ color: '#ff9900' }}>{(statusData?.feeder_type || 'ALPACA').toUpperCase()}</strong></div>
            </div>
          </div>
        )}

        {/* DYNAMIC INSTRUMENT SELECTOR */}
        <div style={{ marginTop: '20px', paddingTop: '15px', borderTop: '1px solid #242c35' }}>
          <h4 style={{ fontSize: '11px', color: '#848e9c', textTransform: 'uppercase', marginBottom: '8px' }}>Seleccionar Instrumento</h4>
          <input
            type="text"
            placeholder="🔍 Buscar mercado..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            style={{
              width: '100%',
              background: '#20262d',
              border: '1px solid #242c35',
              color: '#fff',
              padding: '6px 10px',
              borderRadius: '4px',
              fontSize: '12px',
              marginBottom: '10px',
            }}
          />

          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', maxHeight: '180px', overflowY: 'auto' }}>
            {filteredWorkers.map((w) => (
              <div
                key={w.worker_id}
                onClick={() => onSelectWorker(w.worker_id)}
                style={{
                  padding: '8px 10px',
                  borderRadius: '4px',
                  background: w.worker_id === activeWorkerId ? '#20262d' : '#181a20',
                  border: w.worker_id === activeWorkerId ? '1px solid #00e6ff' : '1px solid transparent',
                  cursor: 'pointer',
                  display: 'flex',
                  justify: 'space-between',
                  alignItems: 'center',
                }}
              >
                <div>
                  <div style={{ fontSize: '12px', fontWeight: 600, color: '#fff' }}>{w.name}</div>
                  <div style={{ fontSize: '10px', color: '#848e9c' }}>{w.symbol}</div>
                </div>
                <span style={{ fontSize: '10px', color: w.is_running ? '#02c076' : '#848e9c' }}>
                  {w.is_running ? '● RUN' : '○ OFF'}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </aside>
  );
}
