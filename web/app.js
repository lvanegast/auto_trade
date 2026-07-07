const API_BASE = window.location.protocol === "file:" ? "http://localhost:8080/api" : "/api";

const platformAssets = {
    "alpaca": [
        { symbol: "BTC/USD", name: "Bitcoin", desc: "BTC / USD (Alpaca Real)", price: 58295.92, change: 1.42, tag: "CRIPTO", prices: [57200, 57500, 57100, 58000, 57800, 58400, 58100, 58295.92] },
        { symbol: "ETH/USD", name: "Ethereum", desc: "ETH / USD (Alpaca Real)", price: 3415.22, change: -0.85, tag: "CRIPTO", prices: [3480, 3460, 3430, 3450, 3400, 3420, 3390, 3415.22] },
        { symbol: "SOL/USD", name: "Solana", desc: "SOL / USD (Alpaca Real)", price: 142.85, change: 3.12, tag: "CRIPTO", prices: [136, 138, 135, 140, 139, 144, 141, 142.85] },
        { symbol: "LTC/USD", name: "Litecoin", desc: "LTC / USD (Alpaca Real)", price: 74.50, change: 0.15, tag: "CRIPTO", prices: [73.8, 74.2, 73.9, 74.6, 74.1, 74.8, 74.3, 74.50] },
        { symbol: "DOGE/USD", name: "Dogecoin", desc: "DOGE / USD (Alpaca Real)", price: 0.124, change: -2.44, tag: "MEME", prices: [0.129, 0.127, 0.125, 0.126, 0.122, 0.125, 0.121, 0.124] }
    ],
    "binance": [
        { symbol: "BNB/USDT", name: "Binance Coin", desc: "BNB / USDT (Binance Sim)", price: 574.80, change: 1.15, tag: "CRIPTO", prices: [565, 568, 564, 572, 570, 576, 573, 574.8] },
        { symbol: "BTC/USDT", name: "Bitcoin", desc: "BTC / USDT (Binance Sim)", price: 58295.92, change: 1.42, tag: "CRIPTO", prices: [57200, 57500, 57100, 58000, 57800, 58400, 58100, 58295.92] },
        { symbol: "ETH/USDT", name: "Ethereum", desc: "ETH / USDT (Binance Sim)", price: 3415.22, change: -0.85, tag: "CRIPTO", prices: [3480, 3460, 3430, 3450, 3400, 3420, 3390, 3415.22] },
        { symbol: "SOL/USDT", name: "Solana", desc: "SOL / USDT (Binance Sim)", price: 142.85, change: 3.12, tag: "CRIPTO", prices: [136, 138, 135, 140, 139, 144, 141, 142.85] },
        { symbol: "ADA/USDT", name: "Cardano", desc: "ADA / USDT (Binance Sim)", price: 0.385, change: 0.78, tag: "CRIPTO", prices: [0.378, 0.381, 0.375, 0.388, 0.382, 0.391, 0.383, 0.385] },
        { symbol: "XRP/USDT", name: "Ripple", desc: "XRP / USDT (Binance Sim)", price: 0.495, change: -1.20, tag: "CRIPTO", prices: [0.505, 0.501, 0.498, 0.502, 0.491, 0.499, 0.492, 0.495] }
    ],
    "polymarket": [
        { symbol: "55010547192661590740925574347715096531393664724810793796541603527267389823616", name: "Mundial: Francia", desc: "Francia gana el Mundial (YES)", price: 0.38, change: 2.70, tag: "MUNDIAL", prices: [0.35, 0.36, 0.34, 0.37, 0.36, 0.39, 0.37, 0.38] },
        { symbol: "55010547192661590740925574347715096531393664724810793796541603527267389823617", name: "Mundial: Brasil", desc: "Brasil gana el Mundial (YES)", price: 0.28, change: -1.25, tag: "MUNDIAL", prices: [0.29, 0.29, 0.28, 0.30, 0.27, 0.29, 0.27, 0.28] },
        { symbol: "55010547192661590740925574347715096531393664724810793796541603527267389823618", name: "Mundial: Argentina", desc: "Argentina gana el Mundial (YES)", price: 0.22, change: 4.54, tag: "MUNDIAL", prices: [0.20, 0.21, 0.19, 0.22, 0.21, 0.23, 0.21, 0.22] },
        { symbol: "87910547192661590740925574347715096531393664724810793796541603527267389823616", name: "Midterms: Cámara", desc: "Demócratas controlan Cámara (YES)", price: 0.52, change: 0.98, tag: "POLÍTICA", prices: [0.50, 0.51, 0.49, 0.52, 0.51, 0.53, 0.51, 0.52] },
        { symbol: "87910547192661590740925574347715096531393664724810793796541603527267389823617", name: "Midterms: Senado", desc: "Republicanos mantienen Senado (YES)", price: 0.65, change: -0.75, tag: "POLÍTICA", prices: [0.66, 0.67, 0.64, 0.66, 0.63, 0.65, 0.64, 0.65] },
        { symbol: "21742617192661590740925574347715096531393664724810793796541603527267389823616", name: "FED: Corte Julio 26", desc: "FED recorta tasas en Julio 26 (YES)", price: 0.72, change: 6.25, tag: "MACRO", prices: [0.65, 0.68, 0.66, 0.70, 0.69, 0.73, 0.71, 0.72] },
        { symbol: "21742617192661590740925574347715096531393664724810793796541603527267389823617", name: "FED: No Corte Julio", desc: "FED recorta tasas en Julio 26 (NO)", price: 0.28, change: -12.50, tag: "MACRO", prices: [0.35, 0.32, 0.34, 0.30, 0.31, 0.27, 0.29, 0.28] },
        { symbol: "21742617192661590740925574347715096531393664724810793796541603527267389823619", name: "FED: Corte Sept. 26", desc: "FED recorta tasas en Sept. 26 (YES)", price: 0.81, change: 1.25, tag: "MACRO", prices: [0.78, 0.80, 0.79, 0.82, 0.80, 0.83, 0.81, 0.81] },
        { symbol: "21742617192661590740925574347715096531393664724810793796541603527267389823620", name: "Macro: Recesión Q3", desc: "EE.UU. entra en recesión Q3 (YES)", price: 0.34, change: 4.88, tag: "MACRO", prices: [0.30, 0.31, 0.29, 0.32, 0.33, 0.35, 0.32, 0.34] },
        { symbol: "11010547192661590740925574347715096531393664724810793796541603527267389823616", name: "Finanzas: BTC > $150k", desc: "Bitcoin supera los $150k en 2026 (YES)", price: 0.15, change: 1.12, tag: "MACRO", prices: [0.14, 0.14, 0.13, 0.15, 0.14, 0.16, 0.15, 0.15] },
        { symbol: "33010547192661590740925574347715096531393664724810793796541603527267389823616", name: "Tecnología: GPT-5", desc: "GPT-5 anunciado en 2026 (YES)", price: 0.68, change: 1.49, tag: "TECNOLOGÍA", prices: [0.66, 0.67, 0.65, 0.68, 0.67, 0.69, 0.67, 0.68] },
        { symbol: "33010547192661590740925574347715096531393664724810793796541603527267389823617", name: "Espacio: Artemis III", desc: "Artemis III logra alunizaje 26 (YES)", price: 0.45, change: -3.15, tag: "TECNOLOGÍA", prices: [0.47, 0.48, 0.46, 0.47, 0.44, 0.46, 0.43, 0.45] },
        { symbol: "33010547192661590740925574347715096531393664724810793796541603527267389823618", name: "Espacio: Retraso Artemis", desc: "Artemis III se retrasa a 2027 (YES)", price: 0.55, change: 3.77, tag: "TECNOLOGÍA", prices: [0.51, 0.53, 0.50, 0.54, 0.52, 0.56, 0.53, 0.55] }
    ],
    "kalshi": [
        { symbol: "INFLATION-26", name: "Inflación EEUU < 2.6%", desc: "Inflación anual menor a 2.6% (YES)", price: 0.58, change: 1.75, tag: "INFLACIÓN", prices: [0.55, 0.56, 0.54, 0.57, 0.56, 0.59, 0.57, 0.58] },
        { symbol: "CPI-26", name: "CPI Mensual > 0.3%", desc: "CPI de EE.UU. sube más de 0.3% (YES)", price: 0.32, change: -2.40, tag: "INFLACIÓN", prices: [0.35, 0.34, 0.33, 0.35, 0.31, 0.33, 0.30, 0.32] },
        { symbol: "FED-RATE-26", name: "FED Tasa de Interés > 5.0%", desc: "Tasa de interés mayor al 5.0% (YES)", price: 0.74, change: 0.95, tag: "TASAS", prices: [0.72, 0.73, 0.71, 0.74, 0.73, 0.75, 0.73, 0.74] },
        { symbol: "ECB-RATE-26", name: "ECB Recorte 25bps", desc: "ECB recorta tasas en 25bps (YES)", price: 0.62, change: 3.33, tag: "TASAS", prices: [0.58, 0.60, 0.59, 0.61, 0.60, 0.63, 0.61, 0.62] },
        { symbol: "UNEMP-26", name: "Desempleo EE.UU. > 4.2%", desc: "Desempleo mensual supera 4.2% (YES)", price: 0.42, change: 2.44, tag: "EMPLEO", prices: [0.39, 0.41, 0.40, 0.42, 0.41, 0.43, 0.41, 0.42] },
        { symbol: "EV-26", name: "Ventas EV EE.UU. > 12%", desc: "Cuota mercado EV supera el 12% (YES)", price: 0.67, change: -1.47, tag: "CLIMA", prices: [0.69, 0.68, 0.67, 0.69, 0.66, 0.68, 0.66, 0.67] }
    ]
};

function getTagStyle(tag) {
    let color = '#00e6ff';
    let bg = 'rgba(0, 230, 255, 0.12)';
    
    if (tag === 'CRIPTO') { color = '#f0b90b'; bg = 'rgba(240, 185, 11, 0.12)'; }
    else if (tag === 'MEME') { color = '#ff7f50'; bg = 'rgba(255, 127, 80, 0.12)'; }
    else if (tag === 'MUNDIAL') { color = '#ff4757'; bg = 'rgba(255, 71, 87, 0.12)'; }
    else if (tag === 'POLÍTICA') { color = '#a03ffc'; bg = 'rgba(160, 63, 252, 0.12)'; }
    else if (tag === 'MACRO') { color = '#ff9f43'; bg = 'rgba(255, 159, 67, 0.12)'; }
    else if (tag === 'TECNOLOGÍA') { color = '#00e6ff'; bg = 'rgba(0, 230, 255, 0.12)'; }
    else if (tag === 'INFLACIÓN') { color = '#e069c3'; bg = 'rgba(224, 105, 195, 0.12)'; }
    else if (tag === 'TASAS') { color = '#02c076'; bg = 'rgba(2, 192, 118, 0.12)'; }
    else if (tag === 'EMPLEO') { color = '#3498db'; bg = 'rgba(52, 152, 219, 0.12)'; }
    else if (tag === 'CLIMA') { color = '#2ecc71'; bg = 'rgba(46, 204, 113, 0.12)'; }
    
    return { color, bg };
}

// ============================================================
//  WEBSOCKET STREAMING (Fase 2)
//  Conexión en tiempo real, con fallback a polling REST
// ============================================================
// Configuración de WebSocket
// ============================================================
let wsConnection = null;
let wsReconnectTimer = null;
let wsResetTimer = null;
let wsReconnectAttempts = 0;
let wsUsePollingFallback = false;
const WS_BASE_DELAY = 1000;     // 1s base
const WS_MAX_DELAY = 60000;     // 60s cap
const WS_RESET_AFTER = 30000;   // Resetear contador tras 30s conectado

function connectWebSocket(workerId) {
    if (wsConnection && wsConnection.readyState === WebSocket.OPEN) {
        // Ya conectado al mismo worker
        if (wsConnection._workerId === workerId) return;
        // Cambio de worker: cerrar y reconectar
        wsConnection.close();
    }

    // Limpiar timers pendientes
    if (wsReconnectTimer) {
        clearTimeout(wsReconnectTimer);
        wsReconnectTimer = null;
    }
    if (wsResetTimer) {
        clearTimeout(wsResetTimer);
        wsResetTimer = null;
    }

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host || "localhost:8080";
    const url = `${protocol}//${host}/ws/${workerId}`;

    console.log(`[WS] Conectando a ${url}...`);
    const ws = new WebSocket(url);
    ws._workerId = workerId;

    ws.onopen = () => {
        console.log(`[WS] Conectado a worker ${workerId}`);
        wsUsePollingFallback = false;
        updateConnectionIndicator(true);

        // Resetear backoff al conectar exitosamente
        wsReconnectAttempts = 0;

        // Programar reset del contador tras conexión estable prolongada
        if (wsResetTimer) clearTimeout(wsResetTimer);
        wsResetTimer = setTimeout(() => {
            wsReconnectAttempts = 0;
            console.log("[WS] Conexión estable, contador de reconexión reseteado.");
        }, WS_RESET_AFTER);

        // Cargar estado inicial desde REST mientras el WS calienta
        fetchStatus();
        fetchTrades();
        loadWorkers();
    };

    ws.onmessage = (msg) => {
        try {
            const event = JSON.parse(msg.data);
            handleWsEvent(event);
        } catch (e) {
            console.error("[WS] Error parseando mensaje:", e);
        }
    };

    ws.onclose = (e) => {
        console.log(`[WS] Desconectado (code=${e.code}). Activando polling fallback...`);
        wsConnection = null;
        wsUsePollingFallback = true;
        updateConnectionIndicator(false);

        // Limpiar timer de reset
        if (wsResetTimer) {
            clearTimeout(wsResetTimer);
            wsResetTimer = null;
        }

        // Reconexión con backoff exponencial + jitter
        if (activeWorkerId === workerId) {
            const jitter = Math.random() * 1000;  // 0-1s de jitter
            const delay = Math.min(
                WS_BASE_DELAY * Math.pow(2, wsReconnectAttempts) + jitter,
                WS_MAX_DELAY
            );
            wsReconnectAttempts++;
            console.log(`[WS] Reconectando en ${(delay / 1000).toFixed(1)}s (intento #${wsReconnectAttempts})...`);
            wsReconnectTimer = setTimeout(() => connectWebSocket(workerId), delay);
        }
    };

    ws.onerror = (e) => {
        console.error("[WS] Error de conexión. Usando polling.");
        wsUsePollingFallback = true;
        updateConnectionIndicator(false);
        wsConnection = null;
        try { ws.close(); } catch (_) { /* ya cerrado */ }
    };

    wsConnection = ws;
}

function handleWsEvent(event) {
    const { type, data } = event;

    switch (type) {
        case "initial_state":
            // Actualizar UI con estado completo
            if (data.last_price) {
                lastPrice = data.last_price;
                updateTickerDisplay(data);
            }
            if (data.portfolio) {
                updatePortfolioDisplay(data);
            }
            updatePositionDisplay(data);
            break;

        case "price_update":
            // Actualizar en tiempo real
            lastPrice = data.price;
            updateTickerDisplay({
                last_price: data.price,
                symbol: data.symbol,
                teorical_probability: data.teorical_probability,
                edge: data.edge,
                last_position: data.last_position,
            });
            pushTick(data.price);
            updatePositionDisplay(data);
            // Actualizar línea de entrada si hay posición activa
            if (data.last_position && data.entry_price > 0) {
                updateAvgEntryPriceLine(data.entry_price);
            } else if (!data.last_position) {
                clearTradeLines();
            }
            break;

        case "trade_update":
            // Nuevo trade: refrescar tablas y agregar marcador en el gráfico
            fetchTrades();
            fetchStatus();
            if (data.price && data.side) {
                addTradeMarker(Math.floor(Date.now() / 1000), data.side, data.price);
            }
            break;

        case "worker_status":
            // Cambio de estado de worker (start/stop) — actualizar sin polling
            updateWorkerCardStatus(data);
            break;

        case "depth_update":
            // Libro de órdenes recibido vía WebSocket
            currentBids = data.bids || [];
            currentAsks = data.asks || [];
            updateOrderBookDisplay(currentBids, currentAsks);
            break;

        case "log":
            // Nueva entrada de log en tiempo real
            appendLogEntry(data);
            break;

        case "heartbeat":
            // Mantener vivo, no acción necesaria
            break;

        case "pong":
            // Respuesta a nuestro ping
            break;

        default:
            console.log("[WS] Evento desconocido:", type);
    }
}

// --- Funciones helper para eventos WebSocket ---

function updateWorkerCardStatus(data) {
    // Actualiza el indicador visual de estado en las pestañas de workers
    const tabs = document.querySelectorAll(".tab-btn");
    tabs.forEach(btn => {
        if (btn.textContent.trim() === data.name) {
            if (data.is_running) {
                btn.classList.add("worker-running");
                btn.title = `${data.name}: ONLINE (${data.feeder_type.toUpperCase()})`;
            } else {
                btn.classList.remove("worker-running");
                btn.title = `${data.name}: OFFLINE`;
            }
        }
    });
    // Actualizar también el texto de estado en el panel si está visible
    const statusEl = document.getElementById("worker-status-text");
    if (statusEl) {
        statusEl.textContent = data.is_running ? "ONLINE" : "OFFLINE";
        statusEl.style.color = data.is_running ? "#02c076" : "#f84960";
    }
}

function requestDepth() {
    if (wsConnection && wsConnection.readyState === WebSocket.OPEN) {
        wsConnection.send("depth");
    }
}

function updateOrderBookDisplay(bidsData, asksData) {
    // Si no hay datos, generar simulación local
    if ((!bidsData || bidsData.length === 0) && (!asksData || asksData.length === 0)) {
        if (lastPrice <= 0) return;
        const spreadPct = 0.0003;
        const tickSpacing = isForexOrEvent ? 0.0005 : 0.25;
        bidsData = [];
        asksData = [];
        for (let i = 1; i <= 5; i++) {
            const bidPrice = lastPrice * (1 - spreadPct) - (i * tickSpacing);
            const bidQty = Math.random() * (isForexOrEvent ? 20000 : 0.8) + (isForexOrEvent ? 1000 : 0.05);
            bidsData.push([bidPrice, bidQty]);
            const askPrice = lastPrice * (1 + spreadPct) + (i * tickSpacing);
            const askQty = Math.random() * (isForexOrEvent ? 20000 : 0.8) + (isForexOrEvent ? 1000 : 0.05);
            asksData.push([askPrice, askQty]);
        }
        asksData.sort((a, b) => b[0] - a[0]);
    } else {
        bidsData = bidsData.slice(0, 5);
        asksData = asksData.slice(0, 5);
        asksData.sort((a, b) => b[0] - a[0]);
    }

    const decimals = isForexOrEvent ? 4 : 2;
    const amountDecs = baseAsset === "BTC" || baseAsset === "ETH" ? 4 : 2;

    // Renderizar Asks (Venta) - Rojo
    obAsks.innerHTML = "";
    let runningTotalAsk = 0;
    const asksList = [];
    for (let i = asksData.length - 1; i >= 0; i--) {
        const [price, qty] = asksData[i];
        runningTotalAsk += qty;
        asksList.unshift({ price, qty, total: runningTotalAsk });
    }

    asksList.forEach(ask => {
        const row = document.createElement("div");
        row.className = "ob-row ask";
        const maxTotal = asksList[0] ? asksList[0].total : 1;
        const depthVal = Math.min((ask.total / (maxTotal * 1.1)) * 100, 100);

        row.innerHTML = `
            <div class="ob-depth-bar" style="width: ${depthVal}%"></div>
            <span class="ob-price">${ask.price.toFixed(decimals)}</span>
            <span class="text-right">${ask.qty.toFixed(amountDecs)}</span>
            <span class="text-right">${(ask.qty * ask.price).toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
        `;

        row.addEventListener("click", () => {
            if (manualOrderType === "LIMIT") {
                inputPrice.value = ask.price.toFixed(decimals);
            }
            inputQty.value = formatAmountInput(ask.qty);
            inputTotal.value = (ask.qty * ask.price).toFixed(2);
        });

        obAsks.appendChild(row);
    });

    // Spread / Mid Price
    obMidVal.textContent = `$${lastPrice.toFixed(decimals)}`;
    obMidDir.textContent = Math.random() > 0.4 ? "▲" : "▼";
    obMidDir.className = obMidDir.textContent === "▲" ? "mid-price-dir text-success" : "mid-price-dir text-danger";

    // Renderizar Bids (Compra) - Verde
    obBids.innerHTML = "";
    let runningTotalBid = 0;
    const bidsList = [];
    bidsData.forEach(([price, qty]) => {
        runningTotalBid += qty;
        bidsList.push({ price, qty, total: runningTotalBid });
    });

    bidsList.forEach(bid => {
        const row = document.createElement("div");
        row.className = "ob-row bid";
        const maxTotal = bidsList[bidsList.length - 1] ? bidsList[bidsList.length - 1].total : 1;
        const depthVal = Math.min((bid.total / (maxTotal * 1.1)) * 100, 100);

        row.innerHTML = `
            <div class="ob-depth-bar" style="width: ${depthVal}%"></div>
            <span class="ob-price">${bid.price.toFixed(decimals)}</span>
            <span class="text-right">${bid.qty.toFixed(amountDecs)}</span>
            <span class="text-right">${(bid.qty * bid.price).toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
        `;

        row.addEventListener("click", () => {
            if (manualOrderType === "LIMIT") {
                inputPrice.value = bid.price.toFixed(decimals);
            }
            inputQty.value = formatAmountInput(bid.qty);
            inputTotal.value = (bid.qty * bid.price).toFixed(2);
        });

        obBids.appendChild(row);
    });

    currentBids = bidsData;
    currentAsks = asksData;
    updateDepthOnChart(currentBids, currentAsks);
}

function appendLogEntry(data) {
    // Añade una entrada de log en tiempo real al panel de logs
    if (!logConsole) return;

    const date = new Date(data.timestamp);
    const timeStr = date.toLocaleTimeString();
    const levelClass = data.level === "ERROR" ? "error"
        : data.level === "WARNING" ? "warning"
        : "info";

    const entry = document.createElement("div");
    entry.className = `terminal-line ${levelClass}`;
    entry.innerHTML = `<span class="log-time">[${timeStr}]</span> ${data.level}: ${data.message}`;
    logConsole.insertBefore(entry, logConsole.firstChild);

    // Limitar a 100 entradas para evitar acumulación excesiva
    while (logConsole.children.length > 100) {
        logConsole.removeChild(logConsole.lastChild);
    }

    // Si el mensaje inicial de "Esperando logs..." está presente, limpiarlo
    const placeholder = logConsole.querySelector(".terminal-line.info");
    if (placeholder && placeholder.textContent.includes("Esperando logs")) {
        placeholder.remove();
    }
}

function updateConnectionIndicator(connected) {
    const dot = document.getElementById("connection-dot");
    const text = document.getElementById("connection-text");
    if (dot) {
        dot.style.background = connected ? "#02c076" : "#f84960";
        dot.style.boxShadow = connected
            ? "0 0 8px rgba(2, 192, 118, 0.6)"
            : "0 0 8px rgba(248, 73, 96, 0.6)";
    }
    if (text) {
        text.textContent = connected ? "LIVE" : "POLLING";
        text.style.color = connected ? "#02c076" : "#f84960";
    }
}

function addChartPoint(price) {
    /** Compatibilidad: redirige a pushTick para Lightweight Charts. */
    pushTick(price);
}

function updateTickerDisplay(data) {
    const priceEl = document.getElementById("ticker-price");
    const symbolEl = document.getElementById("ticker-symbol");
    if (priceEl && data.last_price) {
        priceEl.textContent = formatCurrency(data.last_price);
    }
    if (symbolEl && data.symbol) {
        symbolEl.textContent = data.symbol;
    }
    // Actualizar probabilidad teórica y edge si existen
    const probEl = document.getElementById("stat-teorical-prob");
    if (probEl && data.teorical_probability !== undefined) {
        probEl.textContent = (data.teorical_probability * 100).toFixed(1) + "%";
    }
    const edgeEl = document.getElementById("stat-edge");
    if (edgeEl && data.edge !== undefined) {
        const edgePct = (data.edge * 100).toFixed(3);
        edgeEl.textContent = (data.edge >= 0 ? "+" : "") + edgePct + "%";
        edgeEl.style.color = data.edge >= 0 ? "#02c076" : "#f84960";
    }
}

function updatePositionDisplay(data) {
    const badge = document.getElementById("position-badge");
    if (badge && data.last_position !== undefined) {
        if (data.last_position === "BUY") {
            badge.textContent = "COMPRADO";
            badge.className = "badge badge-buy";
        } else if (data.last_position === "SELL") {
            badge.textContent = "VENDIDO";
            badge.className = "badge badge-sell";
        } else {
            badge.textContent = "SIN POSICIÓN";
            badge.className = "badge badge-neutral";
        }
    }
}

function updatePortfolioDisplay(data) {
    // Actualizar balances en el panel de trading
    if (data.portfolio && data.quote_asset) {
        availableQuote = data.portfolio[data.quote_asset] || 0;
        document.getElementById("available-quote").textContent =
            formatCurrency(availableQuote) + " " + data.quote_asset;
    }
    if (data.portfolio && data.base_asset) {
        availableBase = data.portfolio[data.base_asset] || 0;
        document.getElementById("available-base").textContent =
            availableBase.toFixed(6) + " " + data.base_asset;
    }
}

function sendWsPing() {
    if (wsConnection && wsConnection.readyState === WebSocket.OPEN) {
        wsConnection.send("ping");
    }
}

// Ping cada 25s para mantener vivo el WebSocket
setInterval(sendWsPing, 25000);

function generateSparklinePath(prices, width = 50, height = 20) {
    if (!prices || prices.length < 2) return "";
    const min = Math.min(...prices);
    const max = Math.max(...prices);
    const range = max - min === 0 ? 1 : max - min;
    
    return prices.map((price, idx) => {
        const x = (idx / (prices.length - 1)) * width;
        const y = height - ((price - min) / range) * height;
        return `${idx === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
    }).join(" ");
}

function renderSidebarAssetCards(feederType, activeSymbol) {
    // Guardar para uso en filtros
    lastKnownFeederType = feederType;
    lastKnownActiveSymbol = activeSymbol;

    const container = document.getElementById("sidebar-asset-cards-container");
    if (!container) return;
    
    container.innerHTML = "";
    
    const platform = platformAssets[feederType] ? feederType : "alpaca";
    let assets = platformAssets[platform];
    
    // Actualizar datalist para autocompletado del input manual
    const datalist = document.getElementById("custom-symbol-suggestions");
    if (datalist) {
        datalist.innerHTML = "";
        const allAssets = platformAssets[platform] || [];
        allAssets.forEach(asset => {
            const opt = document.createElement("option");
            opt.value = asset.symbol;
            opt.textContent = `${asset.name} (${asset.tag})`;
            datalist.appendChild(opt);
        });
    }
    
    // Aplicar filtro si el input de búsqueda tiene valor
    const query = searchAssetInput ? searchAssetInput.value.toLowerCase().trim() : "";
    if (query) {
        assets = assets.filter(a => 
            a.name.toLowerCase().includes(query) || 
            a.desc.toLowerCase().includes(query) || 
            a.symbol.toLowerCase().includes(query)
        );
    }
    
    assets.forEach(asset => {
        const isActive = asset.symbol === activeSymbol;
        
        let displayPrice = asset.price;
        let displayChange = asset.change;
        let displayPrices = asset.prices;
        
        if (isActive && lastPrice > 0) {
            displayPrice = lastPrice;
            if (tickBuffer.length > 1) {
                const first = tickBuffer[0].price;
                const last = tickBuffer[tickBuffer.length - 1].price;
                displayChange = first > 0 ? ((last - first) / first) * 100 : 0;
                displayPrices = tickBuffer.slice(-8).map(t => t.price);
                if (displayPrices.length < 2) {
                    displayPrices = [first, last];
                }
            }
        }
        
        const isUp = displayChange >= 0;
        const changeSign = isUp ? "+" : "";
        const changeClass = isUp ? "up" : "down";
        const sparklineClass = isUp ? "up" : "down";
        
        const path = generateSparklinePath(displayPrices, 50, 20);
        
        const tagStyle = getTagStyle(asset.tag);
        
        const card = document.createElement("div");
        card.className = `asset-card ${isActive ? 'active' : ''}`;
        card.innerHTML = `
            <div class="asset-info">
                <span class="asset-title" title="${asset.name}">${asset.name}</span>
                <span class="asset-desc" title="${asset.desc}">
                    <span style="background: ${tagStyle.bg}; color: ${tagStyle.color}; padding: 1px 4px; border-radius: 3px; font-size: 8px; font-weight: 700; margin-right: 4px; text-transform: uppercase;">${asset.tag}</span>
                    ${asset.desc}
                </span>
            </div>
            <div class="asset-chart-val">
                <svg class="asset-sparkline ${sparklineClass}" viewBox="0 0 50 20">
                    <path d="${path}"></path>
                </svg>
                <div class="asset-price-col">
                    <span class="asset-card-price">${displayPrice < 2 ? '$' + displayPrice.toFixed(4) : '$' + displayPrice.toLocaleString(undefined, {minimumFractionDigits:2})}</span>
                    <span class="asset-card-change ${changeClass}">${changeSign}${displayChange.toFixed(2)}%</span>
                </div>
            </div>
        `;
        
        card.addEventListener("click", () => {
            changeAssetSymbolTo(platform, asset.symbol);
        });
        
        container.appendChild(card);
    });
}

// ============================================================
// Gráfico — Lightweight Charts (TradingView)
// ============================================================
let priceChart = null;        // IChartApi
let candleSeries = null;      // ISeriesApi<"Candlestick">
let volumeSeries = null;      // ISeriesApi<"Histogram"> (depth/volume)
let entryPriceLine = null;    // Active position price line
let tradeMarkers = [];        // Historical trade markers [{time, position, color, shape, text}]

// Tick buffer para agregación OHLC
let tickBuffer = [];           // [{time: number, price: number}]
let currentTimeframe = "1m";   // "1m" | "5m" | "15m" | "1h"
let currentFeederTypeForChart = null;

// Constantes de timeframe
const TF_MINUTES = { "1m": 1, "5m": 5, "15m": 15, "1h": 60 };

// Estado de la UI
let activeWorkerId = "worker_1";
let workersList = [];
let openOrdersList = [];
let lastPrice = 0.0;
let quoteAsset = "USD";
let baseAsset = "BTC";
let isForexOrEvent = false;
let lastActiveSymbol = "";
let recentTradesList = [];
let currentBids = [];
let currentAsks = [];
let isPredictionMarket = false;

function getDisplayBase(asset) {
    if (/^\d+$/.test(asset) && asset.length > 12) {
        return "PM-" + asset.slice(-6);
    }
    return asset;
}

let availableQuote = 0.0;
let availableBase = 0.0;
let manualSide = "BUY"; // "BUY" o "SELL"
let manualOrderType = "MARKET"; // "MARKET" o "LIMIT"

// Elementos de la UI - Header & Ticker
const workerTabsContainer = document.getElementById("worker-tabs-container");
const headerPrice = document.getElementById("header-price");
const headerChange = document.getElementById("header-change");
const headerHigh = document.getElementById("header-high");
const headerLow = document.getElementById("header-low");
const headerVolume = document.getElementById("header-volume");
const botStatusDot = document.getElementById("bot-status-dot");
const botStatusText = document.getElementById("bot-status-text");
const botMode = document.getElementById("bot-mode");

// Elementos de la UI - Libro de Órdenes / Trades Recientes
const tabBook = document.getElementById("tab-book");
const tabMarketTrades = document.getElementById("tab-market-trades");
const orderBookContainer = document.getElementById("order-book-container");
const marketTradesContainer = document.getElementById("market-trades-container");
const obAsks = document.getElementById("ob-asks");
const obBids = document.getElementById("ob-bids");
const obMidVal = document.getElementById("ob-mid-val");
const obMidDir = document.getElementById("ob-mid-dir");
const obLiveTrades = document.getElementById("ob-live-trades");

// Elementos de la UI - Centro
const chartSymbolName = document.getElementById("chart-symbol-name");
const chartSourceName = document.getElementById("chart-source-name");
const viewEma9 = document.getElementById("view-ema9");
const viewEma21 = document.getElementById("view-ema21");
const viewRsi = document.getElementById("view-rsi");
const viewProbP = document.getElementById("view-prob-p");
const viewEdge = document.getElementById("view-edge");
const viewKelly = document.getElementById("view-kelly");

const radialGaugeContainer = document.getElementById("radial-gauge-container");
const gaugeCircleFill = document.getElementById("gauge-circle-fill");
const gaugePercentText = document.getElementById("gauge-percent-text");
const gaugeLabelText = document.getElementById("gauge-label-text");
const priceChartCanvas = document.getElementById("priceChart");

const strategyPosition = document.getElementById("strategy-position");
const balanceQuote = document.getElementById("balance-quote");
const balanceBase = document.getElementById("balance-base");
const strategyPnl = document.getElementById("strategy-pnl");
const portfolioTotal = document.getElementById("portfolio-total");

// Elementos de la UI - Paneles Inferiores (Tabs)
const bottomTabBtns = document.querySelectorAll(".bottom-tab-btn");
const bottomTabPanels = document.querySelectorAll(".bottom-tab-panel");
const openOrdersTableBody = document.getElementById("open-orders-table-body");
const portfolioWalletTableBody = document.getElementById("portfolio-wallet-table-body");
const tradesTableBody = document.getElementById("trades-table-body");
const logConsole = document.getElementById("log-console");

const detailEma9 = document.getElementById("detail-ema9");
const detailEma21 = document.getElementById("detail-ema21");
const detailRsiVal = document.getElementById("detail-rsi-val");
const detailRsiBadge = document.getElementById("detail-rsi-badge");
const rsiPointer = document.getElementById("rsi-pointer");

// Elementos de la UI - Terminal Panel (Derecha)
const toggleManual = document.getElementById("toggle-manual");
const toggleAuto = document.getElementById("toggle-auto");
const manualTradeSection = document.getElementById("manual-trade-section");
const autoBotSection = document.getElementById("auto-bot-section");

const sideBuyBtn = document.getElementById("side-buy-btn");
const sideSellBtn = document.getElementById("side-sell-btn");
const orderMarketBtn = document.getElementById("order-market-btn");
const orderLimitBtn = document.getElementById("order-limit-btn");

const availableFundsLabel = document.getElementById("available-funds-label");
const priceInputGroup = document.getElementById("price-input-group");
const inputPrice = document.getElementById("input-price");
const inputQty = document.getElementById("input-qty");
const inputTotal = document.getElementById("input-total");
const pctBtns = document.querySelectorAll(".pct-btn");
const btnExecuteOrder = document.getElementById("btn-execute-order");

// Bot Controls (Panel Auto)
const btnStart = document.getElementById("btn-start");
const btnStop = document.getElementById("btn-stop");
const botCardWorkerName = document.getElementById("bot-card-worker-name");
const botBadgeStatus = document.getElementById("bot-badge-status");
const paramSymbol = document.getElementById("param-symbol");
const paramSource = document.getElementById("param-source");
const searchAssetInput = document.getElementById("search-asset-input");
const eventProbabilityContainer = document.getElementById("event-probability-container");
const probabilityYesBar = document.getElementById("probability-yes-bar");
const probabilityValueText = document.getElementById("probability-value-text");

let lastKnownFeederType = "alpaca";
let lastKnownActiveSymbol = "";


// Lables de base y quote asset
const quoteAssetLabels = document.querySelectorAll(".quote-asset-lbl");
const baseAssetLabels = document.querySelectorAll(".base-asset-lbl");


// --- INICIALIZACIÓN DE LA GRÁFICA ---
// (currentFeederTypeForChart movido arriba con las otras variables del gráfico)

// ============================================================
// Funciones de agregación OHLC y chart
// ============================================================

function aggregateTicks(ticks, tfMinutes) {
    /** Agrupa ticks en velas OHLC por intervalo de tiempo (en minutos). */
    if (!ticks.length) return [];
    const bucketMs = tfMinutes * 60 * 1000;
    const candles = [];
    let bucketStart = null;
    let open = 0, high = -Infinity, low = Infinity, close = 0;

    for (const tick of ticks) {
        const tMs = tick.time * 1000;
        const bucket = Math.floor(tMs / bucketMs) * bucketMs;

        if (bucketStart === null) {
            bucketStart = bucket;
            open = tick.price;
            high = tick.price;
            low = tick.price;
            close = tick.price;
        } else if (bucket !== bucketStart) {
            candles.push({
                time: Math.floor(bucketStart / 1000),
                open, high, low, close,
            });
            bucketStart = bucket;
            open = tick.price;
            high = tick.price;
            low = tick.price;
            close = tick.price;
        } else {
            close = tick.price;
            if (tick.price > high) high = tick.price;
            if (tick.price < low) low = tick.price;
        }
    }
    if (bucketStart !== null) {
        candles.push({
            time: Math.floor(bucketStart / 1000),
            open, high, low, close,
        });
    }
    return candles;
}

function buildChart(containerId, feederType) {
    /** Crea la instancia de Lightweight Charts con tema oscuro. */
    if (priceChart) {
        try { priceChart.remove(); } catch (_) { /* cleanup */ }
    }

    const container = document.getElementById(containerId);
    if (!container) return;

    // Limpiar container
    container.innerHTML = "";

    priceChart = LightweightCharts.createChart(container, {
        layout: {
            background: { type: "solid", color: "#161a1e" },
            textColor: "#848e9c",
        },
        grid: {
            vertLines: { color: "rgba(36, 44, 53, 0.4)" },
            horzLines: { color: "rgba(36, 44, 53, 0.4)" },
        },
        crosshair: {
            mode: 0,
            vertLine: { color: "rgba(36, 44, 53, 0.6)", labelBackgroundColor: "#242c35" },
            horzLine: { color: "rgba(36, 44, 53, 0.6)", labelBackgroundColor: "#242c35" },
        },
        rightPriceScale: {
            borderColor: "rgba(36, 44, 53, 0.6)",
            autoScale: true,
        },
        timeScale: {
            borderColor: "rgba(36, 44, 53, 0.6)",
            timeVisible: true,
            secondsVisible: false,
        },
        handleScroll: { vertTouchDrag: false },
    });

    // Determinar colores por plataforma
    let upColor = "#02c076";
    let downColor = "#f84960";
    let borderUp = "rgba(2, 192, 118, 0.6)";
    let borderDown = "rgba(248, 73, 96, 0.6)";
    let wickColor = "#848e9c";

    if (feederType === "binance") {
        upColor = "#02c076"; downColor = "#f84960";
    } else if (feederType === "polymarket") {
        upColor = "#a03ffc"; downColor = "#cf5bdb";
        borderUp = "rgba(160, 63, 252, 0.6)"; borderDown = "rgba(207, 91, 219, 0.6)";
    } else if (feederType === "kalshi") {
        upColor = "#02c076"; downColor = "#f84960";
    }

    candleSeries = priceChart.addCandlestickSeries({
        upColor: upColor,
        downColor: downColor,
        borderUpColor: borderUp,
        borderDownColor: borderDown,
        wickUpColor: wickColor,
        wickDownColor: wickColor,
    });

    // Serie de volumen/depth como histograma en overlay (se actualiza con depth)
    volumeSeries = priceChart.addHistogramSeries({
        color: "rgba(2, 192, 118, 0.25)",
        priceFormat: { type: "volume" },
        priceScaleId: "overlay",
    });
    volumeSeries.priceScale().applyOptions({
        scaleMargins: { top: 0.85, bottom: 0 },
    });

    currentFeederTypeForChart = feederType;
    return priceChart;
}

function initChart(feederType) {
    feederType = feederType || "alpaca";
    buildChart("priceChart", feederType);

    // Cargar datos existentes si hay
    if (tickBuffer.length > 0) {
        const candles = aggregateTicks(tickBuffer, TF_MINUTES[currentTimeframe]);
        if (candles.length > 0 && candleSeries) {
            candleSeries.setData(candles);
        }
    }

    // Restaurar marcadores de trade
    if (tradeMarkers.length > 0 && candleSeries) {
        candleSeries.setMarkers(tradeMarkers);
    }

    // Configurar timeframe buttons
    document.querySelectorAll(".tf-btn").forEach(btn => {
        btn.addEventListener("click", function () {
            document.querySelectorAll(".tf-btn").forEach(b => b.classList.remove("active"));
            this.classList.add("active");
            const newTf = this.dataset.tf;
            if (newTf !== currentTimeframe) {
                currentTimeframe = newTf;
                applyTimeframe();
            }
        });
    });

    // Activar botón del timeframe actual
    const activeBtn = document.querySelector(`.tf-btn[data-tf="${currentTimeframe}"]`);
    if (activeBtn) activeBtn.classList.add("active");
}

function applyTimeframe() {
    /** Re-agrega todas las velas para el timeframe seleccionado. */
    if (!candleSeries || tickBuffer.length === 0) return;
    const candles = aggregateTicks(tickBuffer, TF_MINUTES[currentTimeframe]);
    candleSeries.setData(candles);
    // Re-aplicar marcadores
    if (tradeMarkers.length > 0) {
        candleSeries.setMarkers(tradeMarkers);
    }
}

// ============================================================
// Funciones de actualización del gráfico (Lightweight Charts)
// ============================================================

function pushTick(price) {
    /** Agrega un tick al buffer y actualiza la vela actual. */
    if (!price || price <= 0) return;
    const now = Math.floor(Date.now() / 1000);
    tickBuffer.push({ time: now, price: price });

    // Limitar buffer a ~8 horas de ticks
    const maxTicks = 30000;
    if (tickBuffer.length > maxTicks) {
        tickBuffer = tickBuffer.slice(-maxTicks);
    }

    if (!candleSeries) return;

    const tfMin = TF_MINUTES[currentTimeframe];
    const bucketMs = tfMin * 60 * 1000;
    const bucket = Math.floor(now * 1000 / bucketMs) * bucketMs;

    // Tomar ticks relevantes para el periodo actual y anterior
    const relevantTicks = tickBuffer.filter(t => {
        const tBucket = Math.floor(t.time * 1000 / bucketMs) * bucketMs;
        return tBucket >= bucket - bucketMs;
    }).slice(-500);

    const candles = aggregateTicks(relevantTicks, tfMin);
    if (candles.length > 0) {
        const lastCandle = candles[candles.length - 1];
        candleSeries.update(lastCandle);
    }
}

function addChartPoint(price) {
    /** Compatibilidad: redirige a pushTick. */
    pushTick(price);
}

function updateChart(price) {
    /** Compatibilidad: redirige a pushTick. */
    pushTick(price);
}

function updateAvgEntryPriceLine(avgEntryPrice) {
    /** Dibuja/actualiza línea de precio de entrada en el gráfico. */
    if (!candleSeries) return;

    if (entryPriceLine) {
        candleSeries.removePriceLine(entryPriceLine);
        entryPriceLine = null;
    }

    if (avgEntryPrice > 0) {
        entryPriceLine = candleSeries.createPriceLine({
            price: avgEntryPrice,
            color: "#f0b90b",
            lineWidth: 1.5,
            lineStyle: 2,
            axisLabelVisible: true,
            title: "ENTRADA",
        });
    }
}

function addTradeMarker(time, side, price) {
    /** Agrega un marcador de trade ejecutado en el gráfico. */
    if (!candleSeries) return;
    tradeMarkers.push({
        time: time,
        position: side === "BUY" ? "belowBar" : "aboveBar",
        color: side === "BUY" ? "#02c076" : "#f84960",
        shape: side === "BUY" ? "arrowUp" : "arrowDown",
        text: side === "BUY" ? "B" : "S",
        size: 2,
    });
    if (tradeMarkers.length > 50) {
        tradeMarkers = tradeMarkers.slice(-50);
    }
    candleSeries.setMarkers(tradeMarkers);
}

function clearTradeLines() {
    /** Limpia la línea de precio de entrada cuando no hay posición. */
    if (entryPriceLine && candleSeries) {
        candleSeries.removePriceLine(entryPriceLine);
        entryPriceLine = null;
    }
}

function updateDepthOnChart(bids, asks) {
    /** Actualiza la serie de volumen/depth en el gráfico. */
    if (!volumeSeries || !priceChart) return;
    let totalBidVol = 0;
    if (bids && bids.length > 0) {
        bids.slice(0, 5).forEach(b => { totalBidVol += b[1]; });
    }
    let totalAskVol = 0;
    if (asks && asks.length > 0) {
        asks.slice(0, 5).forEach(a => { totalAskVol += a[1]; });
    }
    const netVol = totalBidVol - totalAskVol;
    const time = Math.floor(Date.now() / 1000);
    try {
        volumeSeries.update({ time, value: netVol, color: netVol >= 0 ? "rgba(2,192,118,0.25)" : "rgba(248,73,96,0.25)" });
    } catch (_) { /* ignore */ }
}





// --- CONFIGURACIÓN DE PESTAÑAS DEL SISTEMA (BOTTOM TABS) ---
bottomTabBtns.forEach(btn => {
    btn.addEventListener("click", () => {
        // Remover activo de todos
        bottomTabBtns.forEach(b => b.classList.remove("active"));
        bottomTabPanels.forEach(p => p.classList.add("hidden"));
        
        // Activar seleccionado
        btn.classList.add("active");
        const targetId = btn.getAttribute("data-target");
        document.getElementById(targetId).classList.remove("hidden");
    });
});


// --- TOGGLE PANELS DERECHA (MANUAL / BOT AUTOMÁTICO) ---
toggleManual.addEventListener("click", () => {
    toggleManual.classList.add("active");
    toggleAuto.classList.remove("active");
    manualTradeSection.classList.remove("hidden");
    autoBotSection.classList.add("hidden");
});

toggleAuto.addEventListener("click", () => {
    toggleAuto.classList.add("active");
    toggleManual.classList.remove("active");
    autoBotSection.classList.remove("hidden");
    manualTradeSection.classList.add("hidden");
});


// --- COMPRAR / VENDER TOGGLE (MANUAL TERMINAL) ---
sideBuyBtn.addEventListener("click", () => {
    manualSide = "BUY";
    sideBuyBtn.classList.add("active");
    sideSellBtn.classList.remove("active");
    btnExecuteOrder.className = "btn btn-action-buy";
    btnExecuteOrder.textContent = `Comprar ${getDisplayBase(baseAsset)}`;
    
    // Limpiar input y calcular disponible
    inputQty.value = "";
    inputTotal.value = "";
    clearActivePct();
    updateAvailableDisplay();
});

sideSellBtn.addEventListener("click", () => {
    manualSide = "SELL";
    sideSellBtn.classList.add("active");
    sideBuyBtn.classList.remove("active");
    btnExecuteOrder.className = "btn btn-action-sell";
    btnExecuteOrder.textContent = `Vender ${getDisplayBase(baseAsset)}`;
    
    // Limpiar input y calcular disponible
    inputQty.value = "";
    inputTotal.value = "";
    clearActivePct();
    updateAvailableDisplay();
});


// --- TIPO DE ORDEN TOGGLE (MERCADO / LÍMITE) ---
orderMarketBtn.addEventListener("click", () => {
    manualOrderType = "MARKET";
    orderMarketBtn.classList.add("active");
    orderLimitBtn.classList.remove("active");
    
    // Configurar campos
    inputPrice.value = "Precio de Mercado";
    inputPrice.readOnly = true;
    priceInputGroup.classList.add("disabled");
    
    inputQty.value = "";
    inputTotal.value = "";
    clearActivePct();
});

orderLimitBtn.addEventListener("click", () => {
    manualOrderType = "LIMIT";
    orderLimitBtn.classList.add("active");
    orderMarketBtn.classList.remove("active");
    
    // Configurar campos
    inputPrice.value = lastPrice.toFixed(isForexOrEvent ? 4 : 2);
    inputPrice.readOnly = false;
    priceInputGroup.classList.remove("disabled");
    
    inputQty.value = "";
    inputTotal.value = "";
    clearActivePct();
});


// --- MANEJO DE PORCENTAJES DE BALANCE ---
pctBtns.forEach(btn => {
    btn.addEventListener("click", () => {
        clearActivePct();
        btn.classList.add("active");
        
        const pct = parseInt(btn.getAttribute("data-pct")) / 100.0;
        const price = manualOrderType === "LIMIT" ? parseFloat(inputPrice.value) : lastPrice;
        
        if (isNaN(price) || price <= 0) return;
        
        if (manualSide === "BUY") {
            // Comprar: Gastar porcentaje de balance Quote
            const spendAmount = availableQuote * pct;
            const qty = spendAmount / price;
            inputQty.value = formatAmountInput(qty);
            inputTotal.value = spendAmount.toFixed(2);
        } else {
            // Vender: Vender porcentaje de balance Base
            const qty = availableBase * pct;
            inputQty.value = formatAmountInput(qty);
            inputTotal.value = (qty * price).toFixed(2);
        }
    });
});

function clearActivePct() {
    pctBtns.forEach(b => b.classList.remove("active"));
}

function formatAmountInput(val) {
    if (baseAsset === "BTC" || baseAsset === "ETH") {
        return val.toFixed(6);
    }
    return val.toFixed(2);
}


// --- CALCULADORA DE ENTRADA (CANTIDAD / TOTAL) ---
inputQty.addEventListener("input", () => {
    clearActivePct();
    const qty = parseFloat(inputQty.value);
    const price = manualOrderType === "LIMIT" ? parseFloat(inputPrice.value) : lastPrice;
    
    if (isNaN(qty) || qty <= 0 || isNaN(price) || price <= 0) {
        inputTotal.value = "";
        return;
    }
    
    inputTotal.value = (qty * price).toFixed(2);
});

inputPrice.addEventListener("input", () => {
    if (manualOrderType !== "LIMIT") return;
    clearActivePct();
    const qty = parseFloat(inputQty.value);
    const price = parseFloat(inputPrice.value);
    
    if (isNaN(qty) || qty <= 0 || isNaN(price) || price <= 0) {
        inputTotal.value = "";
        return;
    }
    
    inputTotal.value = (qty * price).toFixed(2);
});


// --- ACTUALIZAR VISUALIZADOR DE FONDOS TERMINAL ---
function updateAvailableDisplay() {
    let lockedQuote = 0.0;
    let lockedBase = 0.0;
    openOrdersList.forEach(o => {
        if (o.side.toUpperCase() === "BUY") {
            lockedQuote += o.total;
        } else {
            lockedBase += o.amount;
        }
    });
    
    const dispQuote = Math.max(availableQuote - lockedQuote, 0);
    const dispBase = Math.max(availableBase - lockedBase, 0);

    if (manualSide === "BUY") {
        availableFundsLabel.textContent = `${dispQuote.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${quoteAsset}`;
    } else {
        const decimals = baseAsset === "BTC" || baseAsset === "ETH" ? 6 : 2;
        availableFundsLabel.textContent = `${dispBase.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })} ${getDisplayBase(baseAsset)}`;
    }
}


// --- CARGAR LISTADO DE WORKERS ---
async function loadWorkers() {
    try {
        const res = await fetch(`${API_BASE}/workers`);
        if (!res.ok) throw new Error("Error API");
        const workers = await res.json();
        
        workersList = workers;
        renderWorkerTabs();
    } catch (err) {
        console.error("Error cargando workers:", err);
    }
}

function renderWorkerTabs() {
    if (!workerTabsContainer) return;
    workerTabsContainer.innerHTML = "";
    
    workersList.forEach(worker => {
        const btn = document.createElement("button");
        btn.className = `tab-btn ${worker.worker_id === activeWorkerId ? 'active' : ''}`;
        btn.textContent = worker.name;
        btn.addEventListener("click", () => {
            if (activeWorkerId !== worker.worker_id) {
                switchWorker(worker.worker_id);
            }
        });
        workerTabsContainer.appendChild(btn);
    });
}

function switchWorker(workerId) {
    activeWorkerId = workerId;
    renderWorkerTabs();

    // Limpiar inputs
    inputQty.value = "";
    inputTotal.value = "";
    clearActivePct();

    // Reconectar WebSocket al nuevo worker
    connectWebSocket(workerId);

    // Fallback inicial mientras el WS conecta
    fetchStatus();
    fetchLogs();
    fetchTrades();
}


// --- CONSULTAR ESTADO ---
async function fetchStatus() {
    try {
        const res = await fetch(`${API_BASE}/status?worker_id=${activeWorkerId}`);
        if (!res.ok) throw new Error("Error API status");
        const data = await res.json();
        
        // Cargar variables de activos
        quoteAsset = data.quote_asset || "USD";
        baseAsset = data.base_asset || "BTC";
        isForexOrEvent = quoteAsset === "USD" && baseAsset !== "BTC" && baseAsset !== "ETH";
        
        // Renderizar las tarjetas visuales de activos del panel lateral
        renderSidebarAssetCards(data.feeder_type, data.symbol);

        // Re-inicializar gráfica si cambia la plataforma
        if (data.feeder_type !== currentFeederTypeForChart) {
            initChart(data.feeder_type);
        }

        
        // Actualizar etiquetas de la interfaz
        quoteAssetLabels.forEach(lbl => lbl.textContent = quoteAsset);
        baseAssetLabels.forEach(lbl => lbl.textContent = getDisplayBase(baseAsset));
        
        // Status global del bot
        const isOnline = data.status === "ONLINE";
        botStatusDot.className = `status-dot ${isOnline ? 'online' : 'offline'}`;
        botStatusText.textContent = isOnline ? "ONLINE" : "OFFLINE";
        botMode.textContent = data.trading_mode;
        
        // Ticker Header
        lastPrice = data.last_price;
        
        // Actualizar barra de probabilidad de evento si corresponde
        if (eventProbabilityContainer && probabilityYesBar && probabilityValueText) {
            const isEvent = data.feeder_type === 'polymarket' || data.feeder_type === 'kalshi';
            if (isEvent) {
                eventProbabilityContainer.style.display = "flex";
                const probPct = Math.min(99, Math.max(1, Math.round(lastPrice * 100)));
                probabilityYesBar.style.width = `${probPct}%`;
                probabilityValueText.textContent = `${probPct}% SI`;
            } else {
                eventProbabilityContainer.style.display = "none";
            }
        }

        const decimals = isForexOrEvent ? 4 : 2;
        headerPrice.textContent = `$${lastPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: decimals })}`;
        chartSymbolName.textContent = getDisplayBase(data.symbol);
        chartSymbolName.title = data.symbol;
        chartSourceName.textContent = data.feeder_type.toUpperCase() + " FEED";
        
        // Simular info de cabecera de Binance
        headerChange.textContent = isOnline ? "+1.42%" : "+0.00%";
        headerHigh.textContent = `$${(lastPrice * 1.02).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: decimals })}`;
        headerLow.textContent = `$${(lastPrice * 0.98).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: decimals })}`;
        headerVolume.textContent = `428.14 ${getDisplayBase(baseAsset)}`;
        
        // Trazado dinámico de visualización: Gráfica para Crypto/Forex, Dial Radial para Predicciones
        isPredictionMarket = data.feeder_type === "kalshi" || data.feeder_type === "polymarket";
        if (isPredictionMarket) {
            if (radialGaugeContainer) radialGaugeContainer.style.display = "flex";
            if (priceChartCanvas) priceChartCanvas.style.display = "none";
            
            let prob = (data.teorical_probability !== undefined && data.teorical_probability < 1.5) ? data.teorical_probability : (lastPrice < 1.5 ? lastPrice : 0.50);
            prob = Math.max(0.01, Math.min(0.99, prob));
            const probPct = prob * 100;
            
            if (gaugePercentText) gaugePercentText.textContent = `${probPct.toFixed(1)}%`;
            if (gaugeCircleFill) {
                const radius = 90;
                const circumference = 2 * Math.PI * radius;
                const offset = circumference - (probPct / 100) * circumference;
                gaugeCircleFill.style.strokeDashoffset = offset;
                
                if (probPct >= 50) {
                    gaugeCircleFill.setAttribute("stroke", "#02c076");
                    if (gaugeLabelText) {
                        gaugeLabelText.textContent = "SI PROBABLE";
                        gaugeLabelText.style.color = "#02c076";
                    }
                } else {
                    gaugeCircleFill.setAttribute("stroke", "#f6465d");
                    if (gaugeLabelText) {
                        gaugeLabelText.textContent = "NO PROBABLE";
                        gaugeLabelText.style.color = "#f6465d";
                    }
                }
            }
        } else {
            if (radialGaugeContainer) radialGaugeContainer.style.display = "none";
            if (priceChartCanvas) priceChartCanvas.style.display = "block";
        }

        // Alimentar gráfica desde el histórico del backend si cambiamos de activo o no hay datos
        if (data.price_history && (data.symbol !== lastActiveSymbol || tickBuffer.length === 0)) {
            // Cargar historial de precios en el buffer de ticks
            tickBuffer = data.price_history.map(item => {
                const d = new Date(item.timestamp);
                const secs = Math.floor(d.getTime() / 1000);
                return { time: secs, price: item.price };
            });
            if (candleSeries) {
                const candles = aggregateTicks(tickBuffer, TF_MINUTES[currentTimeframe]);
                candleSeries.setData(candles);
            }
        } else {
            // Alimentar gráfica con tick individual en tiempo real
            if (!isPredictionMarket) {
                pushTick(lastPrice);
            }
        }
        lastActiveSymbol = data.symbol;

        // Sincronizar balances del portafolio
        availableQuote = data.portfolio[quoteAsset] || 0.0;
        availableBase = data.portfolio[baseAsset] || 0.0;

        let lockedQuote = 0.0;
        let lockedBase = 0.0;
        openOrdersList.forEach(o => {
            if (o.side.toUpperCase() === "BUY") {
                lockedQuote += o.total;
            } else {
                lockedBase += o.amount;
            }
        });

        const dispQuote = Math.max(availableQuote - lockedQuote, 0);
        const dispBase = Math.max(availableBase - lockedBase, 0);
        const totalEstimated = availableQuote + (availableBase * lastPrice);

        balanceQuote.textContent = `$${dispQuote.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
        const baseDecs = baseAsset === "BTC" || baseAsset === "ETH" ? 6 : 2;
        balanceBase.textContent = dispBase.toLocaleString(undefined, { minimumFractionDigits: baseDecs, maximumFractionDigits: baseDecs });
        portfolioTotal.textContent = `$${totalEstimated.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

        // Calcular PnL No Realizado
        const avgEntryPrice = data.avg_entry_price || 0.0;
        updateAvgEntryPriceLine(avgEntryPrice);
        if (availableBase > 0.000001 && avgEntryPrice > 0) {
            const pnlUSD = (lastPrice - avgEntryPrice) * availableBase;
            const pnlPercent = ((lastPrice - avgEntryPrice) / avgEntryPrice) * 100;
            const sign = pnlUSD >= 0 ? "+" : "";
            
            strategyPnl.textContent = `${sign}$${pnlUSD.toFixed(2)} (${sign}${pnlPercent.toFixed(2)}%)`;
            strategyPnl.className = pnlUSD >= 0 ? "stat-val text-success" : "stat-val text-danger";
        } else {
            strategyPnl.textContent = "$0.00 (0.00%)";
            strategyPnl.className = "stat-val text-muted";
        }
        
        updateAvailableDisplay();
        updatePortfolioTable();
        
        // Posición actual de la estrategia
        if (data.last_position === "BUY") {
            strategyPosition.textContent = "COMPRADO (BUY)";
            strategyPosition.className = "pos-badge buy";
        } else if (data.last_position === "SELL") {
            strategyPosition.textContent = "VENDIDO (SELL)";
            strategyPosition.className = "pos-badge sell";
        } else {
            strategyPosition.textContent = "SIN POSICIÓN";
            strategyPosition.className = "pos-badge neutral";
        }
        
        // Indicadores en vivo
        const ind = data.indicators || { ema_short: 0.0, ema_long: 0.0, rsi: 0.0 };
        
        const ema9Val = ind.ema_short > 0 ? ind.ema_short.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: decimals }) : "-";
        const ema21Val = ind.ema_long > 0 ? ind.ema_long.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: decimals }) : "-";
        const rsiVal = ind.rsi > 0 ? ind.rsi.toFixed(2) : "-";
        
        if (viewEma9) viewEma9.textContent = ema9Val;
        if (viewEma21) viewEma21.textContent = ema21Val;
        if (viewRsi) viewRsi.textContent = rsiVal;
        
        // Nuevos Indicadores Cuantitativos (Compatibles con Arbitraje Lead-Lag)
        if (viewProbP) {
            let pVal = "-";
            if (data.teorical_probability !== undefined) {
                if (data.teorical_probability > 1.5) {
                    pVal = `$${data.teorical_probability.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
                } else {
                    pVal = `${(data.teorical_probability * 100).toFixed(1)}%`;
                }
            }
            viewProbP.textContent = pVal;
        }
        if (viewEdge) {
            let edgeVal = "-";
            if (data.edge !== undefined) {
                if (Math.abs(data.edge) < 0.10) {
                    edgeVal = `${data.edge > 0 ? '+' : ''}${(data.edge * 100).toFixed(3)}%`;
                } else {
                    edgeVal = `${data.edge > 0 ? '+' : ''}${data.edge.toLocaleString(undefined, { minimumFractionDigits: 4, maximumFractionDigits: 4 })}`;
                }
            }
            viewEdge.textContent = edgeVal;
            if (data.edge > 0) {
                viewEdge.style.color = "#02c076"; // Verde
            } else if (data.edge < 0) {
                viewEdge.style.color = "#f6465d"; // Rojo
            } else {
                viewEdge.style.color = "#00e6ff"; // Cyan
            }
        }
        if (viewKelly) {
            let kellyVal = "-";
            if (data.kelly_recommendation !== undefined) {
                if (data.kelly_recommendation < 0.05) {
                    kellyVal = `${(data.kelly_recommendation * 100).toFixed(3)}%`;
                } else {
                    kellyVal = `${(data.kelly_recommendation * 100).toFixed(1)}%`;
                }
            }
            viewKelly.textContent = kellyVal;
            if (Math.abs(data.kelly_recommendation) > 0.0005) {
                viewKelly.style.color = "#f0b90b"; // Dorado
            } else {
                viewKelly.style.color = "#848e9c";
            }
        }
        
        if (detailEma9) detailEma9.textContent = ema9Val;
        if (detailEma21) detailEma21.textContent = ema21Val;
        if (detailRsiVal) detailRsiVal.textContent = rsiVal;
        
        if (ind.rsi > 0) {
            rsiPointer.style.left = `${ind.rsi}%`;
            if (ind.rsi >= 70) {
                detailRsiBadge.textContent = "SOBRECOMPRA (SELL)";
                detailRsiBadge.className = "ind-badge overbought";
            } else if (ind.rsi <= 30) {
                detailRsiBadge.textContent = "SOBREVENTA (BUY)";
                detailRsiBadge.className = "ind-badge oversold";
            } else {
                detailRsiBadge.textContent = "NORMAL (HOLD)";
                detailRsiBadge.className = "ind-badge";
            }
        } else {
            rsiPointer.style.left = `50%`;
            detailRsiBadge.textContent = "SIN DATOS";
            detailRsiBadge.className = "ind-badge";
        }
        
        // Configurar panel de auto bot
        botCardWorkerName.textContent = data.name;
        botBadgeStatus.className = `bot-badge ${isOnline ? 'online' : 'offline'}`;
        botBadgeStatus.textContent = isOnline ? "ONLINE" : "OFFLINE";
        paramSymbol.textContent = getDisplayBase(data.symbol);
        paramSymbol.title = data.symbol;
        paramSource.textContent = data.feeder_type.toUpperCase();
        
        if (isOnline) {
            btnStart.classList.add("disabled");
            btnStart.disabled = true;
            btnStop.classList.remove("disabled");
            btnStop.disabled = false;
        } else {
            btnStart.classList.remove("disabled");
            btnStart.disabled = false;
            btnStop.classList.add("disabled");
            btnStop.disabled = true;
        }
        
    } catch (err) {
        console.error("Error al consultar status:", err);
    }
}


// --- CONSULTAR HISTORIAL DE OPERACIONES Y ÓRDENES ABIERTAS ---
async function fetchTrades() {
    try {
        const res = await fetch(`${API_BASE}/trades?worker_id=${activeWorkerId}&limit=50`);
        if (!res.ok) throw new Error("Error API trades");
        const data = await res.json();
        
        tradesTableBody.innerHTML = "";
        openOrdersTableBody.innerHTML = "";
        
        // Separar órdenes abiertas (status PENDING_NEW, NEW, ACCEPTED) de las completadas
        const openOrders = data.filter(t => t.status === "PENDING_NEW" || t.status === "NEW" || t.status === "ACCEPTED");
        openOrdersList = openOrders;
        updatePortfolioTable();
        const completedTrades = data.filter(t => t.status !== "PENDING_NEW" && t.status !== "NEW" && t.status !== "ACCEPTED");
        
        // 1. RENDERIZAR ÓRDENES ABIERTAS
        if (openOrders.length === 0) {
            openOrdersTableBody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">No hay órdenes abiertas activas.</td></tr>';
        } else {
            openOrders.forEach(order => {
                const date = new Date(order.timestamp);
                const dateStr = date.toLocaleString();
                const sideClass = order.side.toLowerCase() === 'buy' ? 'badge-buy' : 'badge-sell';
                const decimals = isForexOrEvent ? 4 : 2;
                const amountDecs = baseAsset === "BTC" || baseAsset === "ETH" ? 6 : 2;
                
                const row = document.createElement("tr");
                row.innerHTML = `
                    <td>${dateStr}</td>
                    <td title="${order.symbol}">${getDisplayBase(order.symbol)}</td>
                    <td><span class="${sideClass}">${order.side}</span></td>
                    <td class="font-mono">$${order.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: decimals })}</td>
                    <td class="font-mono">${order.amount.toLocaleString(undefined, { minimumFractionDigits: amountDecs, maximumFractionDigits: amountDecs })}</td>
                    <td class="font-mono">$${order.total.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                    <td>
                        <button class="text-danger" style="background:transparent; border:none; font-weight:600;" onclick="cancelOrder('${order.id}', '${order.external_order_id}')">Cancelar</button>
                    </td>
                `;
                openOrdersTableBody.appendChild(row);
            });
        }
        
        // 2. RENDERIZAR HISTORIAL DE OPERACIONES
        if (completedTrades.length === 0) {
            tradesTableBody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">No se han realizado operaciones en esta ventana.</td></tr>';
            return;
        }
        
        completedTrades.forEach(trade => {
            const date = new Date(trade.timestamp);
            const dateStr = date.toLocaleString();
            const sideClass = trade.side.toLowerCase() === 'buy' ? 'badge-buy' : 'badge-sell';
            const decimals = isForexOrEvent ? 4 : 2;
            const amountDecs = baseAsset === "BTC" || baseAsset === "ETH" ? 6 : 2;
            
            const isFilled = trade.status.toUpperCase() === "COMPLETED" || trade.status.toUpperCase() === "FILLED";
            const statusClass = isFilled ? "text-success" : "text-muted";
            
            const row = document.createElement("tr");
            row.innerHTML = `
                <td>${dateStr}</td>
                <td title="${trade.symbol}">${getDisplayBase(trade.symbol)}</td>
                <td><span class="${sideClass}">${trade.side}</span></td>
                <td class="font-mono">$${trade.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: decimals })}</td>
                <td class="font-mono">${trade.amount.toLocaleString(undefined, { minimumFractionDigits: amountDecs, maximumFractionDigits: amountDecs })}</td>
                <td class="font-mono">$${trade.total.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                <td><span class="${statusClass}">${trade.status}</span></td>
            `;
            tradesTableBody.appendChild(row);
        });
    } catch (err) {
        console.error("Error al consultar trades:", err);
    }
}

// --- CANCELAR ORDEN ---
async function cancelOrder(tradeId, externalOrderId) {
    const orderIdToCancel = externalOrderId && externalOrderId !== "null" && externalOrderId !== "None" && externalOrderId !== "undefined" ? externalOrderId : tradeId;
    if (!confirm("¿Estás seguro de que deseas cancelar esta orden?")) return;
    
    try {
        const res = await fetch(`${API_BASE}/order/cancel`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                worker_id: activeWorkerId,
                external_order_id: orderIdToCancel
            })
        });
        if (res.ok) {
            fetchStatus();
            fetchLogs();
            fetchTrades();
        } else {
            const err = await res.json();
            alert(`Error al cancelar orden: ${err.detail || "Error desconocido"}`);
        }
    } catch (err) {
        console.error("Error al cancelar orden:", err);
    }
}
window.cancelOrder = cancelOrder;


// --- CONSULTAR LOGS DEL SISTEMA ---
async function fetchLogs() {
    try {
        const res = await fetch(`${API_BASE}/logs?worker_id=${activeWorkerId}&limit=40`);
        if (!res.ok) throw new Error("Error API logs");
        const data = await res.json();
        
        logConsole.innerHTML = "";
        
        if (data.length === 0) {
            logConsole.innerHTML = '<div class="terminal-line info">Esperando logs del sistema...</div>';
            return;
        }
        
        data.forEach(log => {
            const date = new Date(log.timestamp);
            const timeStr = date.toLocaleTimeString();
            const levelClass = log.level.toLowerCase();
            
            const line = document.createElement("div");
            line.className = `terminal-line ${levelClass}`;
            line.innerHTML = `<span class="terminal-time">[${timeStr}]</span> <span class="terminal-msg">${log.message}</span>`;
            logConsole.appendChild(line);
        });
    } catch (err) {
        console.error("Error al consultar logs:", err);
    }
}


// --- EJECUTAR ORDEN MANUAL DESDE TERMINAL ---
async function handleExecuteOrder() {
    const qty = parseFloat(inputQty.value);
    
    if (isNaN(qty) || qty <= 0) {
        alert("Por favor introduce una cantidad válida.");
        return;
    }
    
    btnExecuteOrder.classList.add("disabled");
    btnExecuteOrder.disabled = true;
    
    try {
        const payload = {
            worker_id: activeWorkerId,
            side: manualSide,
            qty: qty,
            order_type: manualOrderType,
            price: manualOrderType === "LIMIT" ? parseFloat(inputPrice.value) : lastPrice
        };
        
        const res = await fetch(`${API_BASE}/order`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(payload)
        });
        
        if (res.ok) {
            // Exito
            inputQty.value = "";
            inputTotal.value = "";
            clearActivePct();
            
            // Recargar datos rápidamente
            setTimeout(() => {
                fetchStatus();
                fetchLogs();
                fetchTrades();
            }, 800);
        } else {
            const errData = await res.json();
            alert(`Error al enviar orden: ${errData.detail || "Error desconocido"}`);
        }
    } catch (err) {
        console.error("Error ejecutando orden manual:", err);
        alert("Ocurrió un error al intentar conectarse al backend.");
    } finally {
        btnExecuteOrder.classList.remove("disabled");
        btnExecuteOrder.disabled = false;
    }
}

btnExecuteOrder.addEventListener("click", handleExecuteOrder);


// --- ENCENDER / APAGAR BOT AUTOMÁTICO ---
async function startBot() {
    try {
        const res = await fetch(`${API_BASE}/start?worker_id=${activeWorkerId}`, { method: "POST" });
        if (res.ok) {
            fetchStatus();
            fetchLogs();
        }
    } catch (err) {
        console.error("Error al arrancar el bot:", err);
    }
}

async function stopBot() {
    try {
        const res = await fetch(`${API_BASE}/stop?worker_id=${activeWorkerId}`, { method: "POST" });
        if (res.ok) {
            fetchStatus();
            fetchLogs();
        }
    } catch (err) {
        console.error("Error al detener el bot:", err);
    }
}

btnStart.addEventListener("click", startBot);
btnStop.addEventListener("click", stopBot);


// --- SIMULACIÓN DEL LIBRO DE ÓRDENES (UX DE BINANCE) ---
let simulatedOrderBookInterval = null;
let simulatedLiveTradesInterval = null;

async function runOrderBookSimulation() {
    // REST fallback para profundidad cuando WebSocket no está disponible
    if (lastPrice <= 0) return;

    let bidsData = [];
    let asksData = [];

    try {
        const res = await fetch(`${API_BASE}/depth?worker_id=${activeWorkerId}`);
        if (res.ok) {
            const depth = await res.json();
            bidsData = depth.bids || [];
            asksData = depth.asks || [];
        }
    } catch (e) {
        console.warn("Error fetching live depth:", e);
    }

    updateOrderBookDisplay(bidsData, asksData);
}



// --- SIMULACIÓN DE TRADES RECIENTES ---
function runLiveTradesSimulation() {
    if (simulatedLiveTradesInterval) clearInterval(simulatedLiveTradesInterval);
    
    // Lista de trades inicial
    obLiveTrades.innerHTML = "";
    recentTradesList = [];
    
    simulatedLiveTradesInterval = setInterval(() => {
        if (lastPrice <= 0) return;
        
        // Crear un trade aleatorio
        const now = new Date();
        const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        const side = Math.random() > 0.48 ? "buy" : "sell";
        const spreadShift = (Math.random() - 0.5) * 0.0004;
        const price = lastPrice * (1 + spreadShift);
        const qty = Math.random() * (isForexOrEvent ? 15000 : 0.4) + (isForexOrEvent ? 500 : 0.01);
        
        const newTrade = {
            time: timeStr,
            side: side,
            price: price,
            qty: qty
        };
        recentTradesList.unshift(newTrade);
        if (recentTradesList.length > 18) {
            recentTradesList.pop();
        }
        
        // Renderizar la lista de trades recientes
        obLiveTrades.innerHTML = recentTradesList.map(t => `
            <div class="trade-row ${t.side === 'buy' ? 'text-success' : 'text-danger'}">
                <span class="text-muted">${t.time}</span>
                <span class="font-mono">${t.price.toFixed(isForexOrEvent ? 4 : 2)}</span>
                <span class="text-right font-mono">${t.qty.toFixed(isForexOrEvent ? 0 : 4)}</span>
            </div>
        `).join("");
        
        // Calcular presión de volumen de compra/venta en tiempo real
        let totalBuyQty = 0;
        let totalSellQty = 0;
        recentTradesList.forEach(t => {
            if (t.side === "buy") totalBuyQty += t.qty;
            else totalSellQty += t.qty;
        });
        const totalQty = totalBuyQty + totalSellQty;
        if (totalQty > 0) {
            const buyPct = (totalBuyQty / totalQty) * 100;
            const sellPct = 100 - buyPct;
            
            const pressureBuyPct = document.getElementById("pressure-buy-pct");
            const pressureSellPct = document.getElementById("pressure-sell-pct");
            const pressureBuyBar = document.getElementById("pressure-buy-bar");
            const pressureSellBar = document.getElementById("pressure-sell-bar");
            
            if (pressureBuyPct) pressureBuyPct.textContent = `${buyPct.toFixed(0)}%`;
            if (pressureSellPct) pressureSellPct.textContent = `${sellPct.toFixed(0)}%`;
            if (pressureBuyBar) pressureBuyBar.style.width = `${buyPct}%`;
            if (pressureSellBar) pressureSellBar.style.width = `${sellPct}%`;
        }
    }, 900);
}


// --- TAB SELECTOR PARA EL SIDEBAR IZQUIERDO ---
tabBook.addEventListener("click", () => {
    tabBook.classList.add("active");
    tabMarketTrades.classList.remove("active");
    orderBookContainer.classList.remove("hidden");
    marketTradesContainer.classList.add("hidden");
});

tabMarketTrades.addEventListener("click", () => {
    tabMarketTrades.classList.add("active");
    tabBook.classList.remove("active");
    marketTradesContainer.classList.remove("hidden");
    orderBookContainer.classList.add("hidden");
});


// --- RENDERIZAR TABLA DE PORTAFOLIO ---
function updatePortfolioTable() {
    if (!portfolioWalletTableBody) return;
    
    let lockedQuote = 0.0;
    let lockedBase = 0.0;
    openOrdersList.forEach(o => {
        if (o.side.toUpperCase() === "BUY") {
            lockedQuote += o.total;
        } else {
            lockedBase += o.amount;
        }
    });
    
    const dispQuote = Math.max(availableQuote - lockedQuote, 0);
    const dispBase = Math.max(availableBase - lockedBase, 0);
    
    const totalQuoteVal = availableQuote; // total cash
    const totalBaseVal = availableBase * lastPrice; // total base asset value
    const grandTotal = totalQuoteVal + totalBaseVal;
    
    const quotePct = grandTotal > 0 ? (totalQuoteVal / grandTotal) * 100 : 0.0;
    const basePct = grandTotal > 0 ? (totalBaseVal / grandTotal) * 100 : 0.0;
    
    portfolioWalletTableBody.innerHTML = "";
    
    // Fila 1: Quote Asset (USD)
    const rowQuote = document.createElement("tr");
    rowQuote.innerHTML = `
        <td><strong>${quoteAsset}</strong> <span class="text-muted" style="font-size:0.75rem; margin-left:6px;">Fiat / Stable</span></td>
        <td class="font-mono">$${dispQuote.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
        <td class="font-mono">$${lockedQuote.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
        <td class="font-mono">$${totalQuoteVal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
        <td>
            <div class="progress-bar-container" style="display:flex; align-items:center; gap:8px;">
                <div class="rsi-track" style="flex:1; height:6px; background:#242c35;">
                    <div style="height:100%; width:${quotePct}%; background:var(--primary); border-radius:3px;"></div>
                </div>
                <span class="font-mono" style="font-size:0.75rem; width:45px; text-align:right;">${quotePct.toFixed(1)}%</span>
            </div>
        </td>
    `;
    portfolioWalletTableBody.appendChild(rowQuote);
    
    // Fila 2: Base Asset (BTC)
    const rowBase = document.createElement("tr");
    const decimals = baseAsset === "BTC" || baseAsset === "ETH" ? 6 : 2;
    rowBase.innerHTML = `
        <td><strong>${getDisplayBase(baseAsset)}</strong> <span class="text-muted" style="font-size:0.75rem; margin-left:6px;">Cripto / Activo</span></td>
        <td class="font-mono">${dispBase.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}</td>
        <td class="font-mono">${lockedBase.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}</td>
        <td class="font-mono">$${totalBaseVal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
        <td>
            <div class="progress-bar-container" style="display:flex; align-items:center; gap:8px;">
                <div class="rsi-track" style="flex:1; height:6px; background:#242c35;">
                    <div style="height:100%; width:${basePct}%; background:var(--success); border-radius:3px;"></div>
                </div>
                <span class="font-mono" style="font-size:0.75rem; width:45px; text-align:right;">${basePct.toFixed(1)}%</span>
            </div>
        </td>
    `;
    portfolioWalletTableBody.appendChild(rowBase);
}


// --- ENVIAR CONFIGURACIÓN DE ACTIVO AL SERVIDOR ---
async function changeAssetSymbolTo(feederType, symbol) {
    if (!symbol) return;
    
    try {
        const res = await fetch(`${API_BASE}/worker/config`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                worker_id: activeWorkerId,
                symbol: symbol,
                feeder_type: feederType
            })
        });
        
        if (res.ok) {
            // Limpiar datos del gráfico para refrescar con el nuevo histórico
            tickBuffer = [];
            tradeMarkers = [];
            if (candleSeries) {
                candleSeries.setData([]);
                candleSeries.setMarkers([]);
            }
            if (entryPriceLine) {
                candleSeries.removePriceLine(entryPriceLine);
                entryPriceLine = null;
            }
            fetchStatus();
            fetchLogs();
            fetchTrades();
        } else {
            const err = await res.json();
            alert(`Error al cambiar símbolo: ${err.detail || "Error desconocido"}`);
        }
    } catch (err) {
        console.error("Error al cambiar símbolo:", err);
    }
}



// Evento al escribir en la barra de búsqueda de instrumentos
if (searchAssetInput) {
    searchAssetInput.addEventListener("input", () => {
        renderSidebarAssetCards(lastKnownFeederType, lastKnownActiveSymbol);
    });
}



// --- INICIALIZAR LA APLICACIÓN ---
initChart();
loadWorkers().then(() => {
    // Fase 2: WebSocket primero, polling como fallback
    connectWebSocket(activeWorkerId);
});

// Polling inteligente: solo ejecuta si WebSocket está caído
setInterval(() => {
    if (wsUsePollingFallback) fetchStatus();
}, 1000);

setInterval(() => {
    if (wsUsePollingFallback) fetchLogs();
}, 2000);

setInterval(() => {
    if (wsUsePollingFallback) fetchTrades();
}, 3000);

setInterval(() => {
    // Workers siempre por REST (baja frecuencia)
    loadWorkers();
}, 10000);

// Order book: WebSocket primero, REST como fallback
setInterval(() => {
    if (!wsUsePollingFallback) {
        requestDepth();  // Vía WebSocket cuando está vivo
    } else {
        runOrderBookSimulation();  // REST fallback
    }
}, 1500);

setInterval(() => {
    if (wsUsePollingFallback) runLiveTradesSimulation();
}, 900);
