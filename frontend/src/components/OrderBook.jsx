import React from 'react';

export default function OrderBook({ statusData }) {
  const price = statusData?.last_price || 0.50;
  const isForexOrEvent = statusData?.feeder_type === 'kalshi' || statusData?.feeder_type === 'polymarket';
  const decimals = isForexOrEvent ? 4 : 2;

  // Generación sintética si no hay profundidad real de WebSocket
  const bids = Array.from({ length: 5 }, (_, i) => [
    price * (1 - 0.0005 * (i + 1)),
    (Math.random() * 2 + 0.1).toFixed(2),
  ]);
  const asks = Array.from({ length: 5 }, (_, i) => [
    price * (1 + 0.0005 * (i + 1)),
    (Math.random() * 2 + 0.1).toFixed(2),
  ]).reverse();

  return (
    <aside className="workspace-panel order-book-panel" style={{ width: '280px', borderRight: '1px solid #242c35', background: '#161a1e' }}>
      <div className="panel-tabs" style={{ padding: '10px 15px', borderBottom: '1px solid #242c35', fontWeight: 600, fontSize: '13px', color: '#eaecef' }}>
        Libro de Órdenes (Profundidad)
      </div>

      <div style={{ padding: '10px', fontSize: '11px', fontFamily: 'JetBrains Mono' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', color: '#848e9c', marginBottom: '8px' }}>
          <span>Precio</span>
          <span style={{ textAlign: 'right' }}>Cant</span>
          <span style={{ textAlign: 'right' }}>Total</span>
        </div>

        {/* Asks (Ventas - Rojo) */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          {asks.map(([p, q], idx) => (
            <div key={idx} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', color: '#f84960' }}>
              <span>{parseFloat(p).toFixed(decimals)}</span>
              <span style={{ textAlign: 'right', color: '#eaecef' }}>{q}</span>
              <span style={{ textAlign: 'right', color: '#848e9c' }}>{(p * q).toFixed(1)}</span>
            </div>
          ))}
        </div>

        {/* Mid Price */}
        <div style={{ padding: '8px 0', my: '6px', borderTop: '1px solid #242c35', borderBottom: '1px solid #242c35', fontSize: '14px', fontWeight: 700, color: '#00e6ff', textAlign: 'center' }}>
          ${price.toFixed(decimals)}
        </div>

        {/* Bids (Compras - Verde) */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          {bids.map(([p, q], idx) => (
            <div key={idx} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', color: '#02c076' }}>
              <span>{parseFloat(p).toFixed(decimals)}</span>
              <span style={{ textAlign: 'right', color: '#eaecef' }}>{q}</span>
              <span style={{ textAlign: 'right', color: '#848e9c' }}>{(p * q).toFixed(1)}</span>
            </div>
          ))}
        </div>
      </div>
    </aside>
  );
}
