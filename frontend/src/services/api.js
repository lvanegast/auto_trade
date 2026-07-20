const API_BASE = '/api';

export async function fetchWorkers() {
  const res = await fetch(`${API_BASE}/workers`);
  if (!res.ok) throw new Error('Error al obtener trabajadores');
  return res.json();
}

export async function fetchWorkerStatus(workerId = 'worker_1') {
  const res = await fetch(`${API_BASE}/status?worker_id=${workerId}`);
  if (!res.ok) throw new Error(`Error en el estado del worker ${workerId}`);
  return res.json();
}

export async function fetchTrades(workerId = null) {
  const url = workerId ? `${API_BASE}/trades?worker_id=${workerId}` : `${API_BASE}/trades`;
  const res = await fetch(url);
  if (!res.ok) throw new Error('Error al obtener trades');
  return res.json();
}

export async function fetchOpenPositions(workerId = null) {
  const url = workerId ? `${API_BASE}/positions?worker_id=${workerId}` : `${API_BASE}/positions`;
  const res = await fetch(url);
  if (!res.ok) throw new Error('Error al obtener posiciones');
  return res.json();
}

export async function startBot(workerId = 'worker_1') {
  const res = await fetch(`${API_BASE}/start?worker_id=${workerId}`, { method: 'POST' });
  if (!res.ok) throw new Error('Error al iniciar el bot');
  return res.json();
}

export async function stopBot(workerId = 'worker_1') {
  const res = await fetch(`${API_BASE}/stop?worker_id=${workerId}`, { method: 'POST' });
  if (!res.ok) throw new Error('Error al detener el bot');
  return res.json();
}
