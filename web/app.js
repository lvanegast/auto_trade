const API_BASE = "http://localhost:8080/api";

// Variables globales para Chart.js
let priceChart = null;
const chartLimit = 30;
let chartLabels = [];
let chartData = [];

// Elementos de la UI
const btnStart = document.getElementById("btn-start");
const btnStop = document.getElementById("btn-stop");
const botStatusDot = document.getElementById("bot-status-dot");
const botStatusText = document.getElementById("bot-status-text");
const botMode = document.getElementById("bot-mode");
const tickerPrice = document.getElementById("ticker-price");
const balanceUsdt = document.getElementById("balance-usdt");
const balanceBtc = document.getElementById("balance-btc");
const portfolioTotal = document.getElementById("portfolio-total");
const logConsole = document.getElementById("log-console");
const tradesTableBody = document.getElementById("trades-table-body");
const chartSymbol = document.getElementById("chart-symbol");
const portfolioTitle = document.getElementById("portfolio-title");
const labelQuote = document.getElementById("label-quote");
const labelBase = document.getElementById("label-base");
const tickerLabel = document.querySelector(".ticker-label");

// Inicialización de la Gráfica de Precio
function initChart() {
    const ctx = document.getElementById('priceChart').getContext('2d');
    
    // Crear gradiente para el área debajo de la línea
    const gradient = ctx.createLinearGradient(0, 0, 0, 300);
    gradient.addColorStop(0, 'rgba(79, 172, 254, 0.3)');
    gradient.addColorStop(1, 'rgba(0, 242, 254, 0.0)');

    priceChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: chartLabels,
            datasets: [{
                label: 'Precio',
                data: chartData,
                borderColor: '#4facfe',
                borderWidth: 2,
                pointBackgroundColor: '#00f2fe',
                pointBorderColor: '#080b11',
                pointHoverRadius: 6,
                fill: true,
                backgroundColor: gradient,
                tension: 0.3
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(255, 255, 255, 0.03)' },
                    ticks: { color: '#94a3b8', font: { family: 'Space Grotesk' } }
                },
                y: {
                    grid: { color: 'rgba(255, 255, 255, 0.03)' },
                    ticks: { color: '#94a3b8', font: { family: 'Space Grotesk' } }
                }
            }
        }
    });
}

// Actualizar la Gráfica con nuevos valores de precio
function updateChart(price) {
    const now = new Date();
    const timeLabel = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    
    chartLabels.push(timeLabel);
    chartData.push(price);
    
    // Mantener la gráfica en el límite establecido
    if (chartLabels.length > chartLimit) {
        chartLabels.shift();
        chartData.shift();
    }
    
    if (priceChart) {
        priceChart.update();
    }
}

// Consultar Estado del Bot
async function fetchStatus() {
    try {
        const res = await fetch(`${API_BASE}/status`);
        if (!res.ok) throw new Error("Error de API");
        const data = await res.json();
        
        // Actualizar Status e Indicadores
        const isOnline = data.status === "ONLINE";
        botStatusDot.className = `dot ${isOnline ? 'online' : 'offline'}`;
        botStatusText.textContent = isOnline ? "ONLINE" : "OFFLINE";
        botMode.textContent = data.trading_mode;
        chartSymbol.textContent = data.symbol;
        
        // Actualizar etiquetas dinámicas
        if (data.base_asset && data.quote_asset) {
            labelQuote.textContent = `Saldo ${data.quote_asset}`;
            labelBase.textContent = `Saldo ${data.base_asset}`;
            if (tickerLabel) {
                tickerLabel.textContent = `Precio Actual (${data.symbol})`;
            }
            if (portfolioTitle) {
                portfolioTitle.textContent = data.feeder_type === "mock" ? "Portafolio (Simulación)" : `Portafolio (Real ${data.feeder_type.toUpperCase()})`;
            }
        }
        
        // Botones de acción
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
        
        // Precios
        const price = data.last_price;
        const quoteAsset = data.quote_asset || "USDT";
        const baseAsset = data.base_asset || "BTC";
        
        tickerPrice.textContent = quoteAsset === "USD" || quoteAsset === "USDT"
            ? `$${price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`
            : `${price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })} ${quoteAsset}`;
        
        // Si el bot está activo, alimentar la gráfica con el precio
        if (isOnline) {
            updateChart(price);
        }
        
        // Saldos
        const quoteBalance = data.portfolio[quoteAsset] || 0.0;
        const baseBalance = data.portfolio[baseAsset] || 0.0;
        const total = quoteBalance + (baseBalance * price);
        
        balanceUsdt.textContent = quoteAsset === "USD" || quoteAsset === "USDT"
            ? `$${quoteBalance.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
            : `${quoteBalance.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${quoteAsset}`;
            
        balanceBtc.textContent = baseBalance.toFixed(baseAsset === "BTC" || baseAsset === "ETH" ? 6 : 2);
        
        portfolioTotal.textContent = quoteAsset === "USD" || quoteAsset === "USDT"
            ? `$${total.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
            : `${total.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${quoteAsset}`;
        
    } catch (err) {
        console.error("No se pudo obtener el estado:", err);
        botStatusText.textContent = "CONEXIÓN PERDIDA";
        botStatusDot.className = "dot offline";
    }
}

// Consultar Logs
async function fetchLogs() {
    try {
        const res = await fetch(`${API_BASE}/logs?limit=30`);
        if (!res.ok) throw new Error("Error de API");
        const data = await res.json();
        
        logConsole.innerHTML = "";
        
        if (data.length === 0) {
            logConsole.innerHTML = '<div class="terminal-line info">Esperando logs...</div>';
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
        console.error("Error al obtener logs:", err);
    }
}

// Consultar Historial de Transacciones
async function fetchTrades() {
    try {
        const res = await fetch(`${API_BASE}/trades?limit=15`);
        if (!res.ok) throw new Error("Error de API");
        const data = await res.json();
        
        tradesTableBody.innerHTML = "";
        
        if (data.length === 0) {
            tradesTableBody.innerHTML = '<tr><td colspan="7" class="text-center">No se han realizado operaciones aún.</td></tr>';
            return;
        }
        
        data.forEach(trade => {
            const date = new Date(trade.timestamp);
            const dateStr = date.toLocaleString();
            const sideClass = trade.side.toLowerCase() === 'buy' ? 'badge-buy' : 'badge-sell';
            
            const row = document.createElement("tr");
            row.innerHTML = `
                <td>${dateStr}</td>
                <td>${trade.symbol}</td>
                <td><span class="${sideClass}">${trade.side}</span></td>
                <td class="font-mono">$${trade.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}</td>
                <td class="font-mono">${trade.amount.toFixed(6)}</td>
                <td class="font-mono">$${trade.total.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                <td><span class="status-completed">${trade.status}</span></td>
            `;
            tradesTableBody.appendChild(row);
        });
    } catch (err) {
        console.error("Error al obtener trades:", err);
    }
}

// Iniciar Bot
async function startBot() {
    try {
        const res = await fetch(`${API_BASE}/start`, { method: "POST" });
        if (res.ok) {
            fetchStatus();
            fetchLogs();
        }
    } catch (err) {
        console.error("Error al arrancar el bot:", err);
    }
}

// Detener Bot
async function stopBot() {
    try {
        const res = await fetch(`${API_BASE}/stop`, { method: "POST" });
        if (res.ok) {
            fetchStatus();
            fetchLogs();
        }
    } catch (err) {
        console.error("Error al detener el bot:", err);
    }
}

// Configurar Event Listeners y Loops
btnStart.addEventListener("click", startBot);
btnStop.addEventListener("click", stopBot);

// Inicializar Aplicación
initChart();
fetchStatus();
fetchLogs();
fetchTrades();

// Intervalos de actualización (Polling)
setInterval(fetchStatus, 1000);   // Consultar estado y actualizar precios/saldos cada 1s
setInterval(fetchLogs, 2000);     // Consultar logs cada 2s
setInterval(fetchTrades, 3000);   // Consultar trades cada 3s
