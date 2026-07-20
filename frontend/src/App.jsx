import React, { useState, useEffect } from 'react';
import HeaderTicker from './components/HeaderTicker';
import Chart from './components/Chart';
import OrderBook from './components/OrderBook';
import PositionsTable from './components/PositionsTable';
import ControlPanel from './components/ControlPanel';
import { fetchWorkers, fetchWorkerStatus, fetchTrades, fetchOpenPositions } from './services/api';
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

        <ControlPanel
          statusData={statusData}
          activeWorkerId={activeWorkerId}
          onSelectWorker={setActiveWorkerId}
          workers={workers}
        />
      </div>
    </div>
  );
}
