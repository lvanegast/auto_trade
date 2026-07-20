import React, { useState, useEffect } from 'react';
import HeaderTicker from './components/HeaderTicker';
import Chart from './components/Chart';
import OrderBook from './components/OrderBook';
import PositionsTable from './components/PositionsTable';
import { fetchWorkers, fetchWorkerStatus, fetchTrades, fetchOpenPositions, startBot, stopBot } from './services/api';
import { WebSocketClient } from './services/websocket';

export default function App() {
  const [workers, setWorkers] = useState([]);
  const [activeWorkerId, setActiveWorkerId] = useState('worker_1');
  const [statusData, setStatusData] = useState(null);
  const [trades, setTrades] = useState([]);
  const [positions, setPositions] = useState([]);
  const [isOnline, setIsOnline] = useState(false);

  // Cargar lista de trabajadores
  useEffect(() => {
    fetchWorkers()
      .then((data) => {
        setWorkers(data);
        if (data.length > 0 && !activeWorkerId) {
          setActiveWorkerId(data[0].worker_id);
        }
      })
      .catch(console.error);

    const interval = setInterval(() => {
      fetchWorkers().then(setWorkers).catch(() => {});
    }, 10000);

    return () => clearInterval(interval);
  }, []);

  // Poll status data for active worker
  useEffect(() => {
    if (!activeWorkerId) return;

    const loadData = () => {
      fetchWorkerStatus(activeWorkerId).then(setStatusData).catch(() => {});
      fetchTrades(activeWorkerId).then(setTrades).catch(() => {});
      fetchOpenPositions(activeWorkerId).then(setPositions).catch(() => {});
    };

    loadData();
    const interval = setInterval(loadData, 2500);

    // WebSocket connection
    const client = new WebSocketClient(
      activeWorkerId,
      (data) => {
        if (data.type === 'price_update') {
          setStatusData((prev) => (prev ? { ...prev, last_price: data.price } : prev));
        }
      },
      (connected) => setIsOnline(connected)
    );
    client.connect();

    return () => {
      clearInterval(interval);
      client.disconnect();
    };
  }, [activeWorkerId]);

  const handleToggleBot = async () => {
    if (!statusData) return;
    const isRunning = statusData.status === 'ONLINE';
    try {
      if (isRunning) {
        await stopBot(activeWorkerId);
      } else {
        await startBot(activeWorkerId);
      }
      const updated = await fetchWorkerStatus(activeWorkerId);
      setStatusData(updated);
    } catch (err) {
      alert(err.message);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#0b0e11' }}>
      <HeaderTicker
        workers={workers}
        activeWorkerId={activeWorkerId}
        onSelectWorker={setActiveWorkerId}
        statusData={statusData}
        isOnline={isOnline}
      />

      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <OrderBook statusData={statusData} />

        <main style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <Chart statusData={statusData} />
          <PositionsTable positions={positions} trades={trades} portfolio={statusData?.portfolio || []} />
        </main>

        <aside style={{ width: '240px', background: '#161a1e', borderLeft: '1px solid #242c35', padding: '15px' }}>
          <h4 style={{ fontSize: '12px', color: '#848e9c', textTransform: 'uppercase', marginBottom: '10px' }}>PANEL DE CONTROL</h4>
          <button
            onClick={handleToggleBot}
            style={{
              width: '100%',
              padding: '12px',
              borderRadius: '6px',
              fontWeight: 700,
              fontSize: '14px',
              background: statusData?.status === 'ONLINE' ? '#f84960' : '#02c076',
              color: '#fff',
              marginBottom: '15px',
            }}
          >
            {statusData?.status === 'ONLINE' ? 'Detener Bot' : 'Iniciar Bot'}
          </button>

          <div style={{ fontSize: '11px', color: '#848e9c', lineHeight: 1.8 }}>
            <div>Worker Activo: <strong style={{ color: '#fff' }}>{activeWorkerId}</strong></div>
            <div>Estrategia: <strong style={{ color: '#00e6ff' }}>Black-Scholes / Kelly</strong></div>
            <div>Modo: <strong style={{ color: '#02c076' }}>{statusData?.trading_mode || 'PAPER'}</strong></div>
          </div>
        </aside>
      </div>
    </div>
  );
}
