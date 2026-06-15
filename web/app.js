const API_BASE = "/api";

// Variables globales para Chart.js
let priceChart = null;
const chartLimit = 40;
let chartLabels = [];
let chartData = [];

// Estado de la UI
let activeWorkerId = "worker_1";
let workersList = [];
let openOrdersList = [];
let lastPrice = 0.0;
let quoteAsset = "USD";
let baseAsset = "BTC";
let isForexOrEvent = false;
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

// Lables de base y quote asset
const quoteAssetLabels = document.querySelectorAll(".quote-asset-lbl");
const baseAssetLabels = document.querySelectorAll(".base-asset-lbl");


// --- INICIALIZACIÓN DE LA GRÁFICA ---
function initChart() {
    const ctx = document.getElementById('priceChart').getContext('2d');
    
    // Crear gradiente azul de fondo
    const gradient = ctx.createLinearGradient(0, 0, 0, 400);
    gradient.addColorStop(0, 'rgba(0, 230, 255, 0.15)');
    gradient.addColorStop(1, 'rgba(0, 230, 255, 0.0)');

    if (priceChart) {
        priceChart.destroy();
    }

    priceChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: chartLabels,
            datasets: [{
                label: 'Precio',
                data: chartData,
                borderColor: '#00e6ff',
                borderWidth: 2,
                pointRadius: 0, // Ocultar puntos para estilo limpio
                pointHoverRadius: 5,
                pointHoverBackgroundColor: '#eaecef',
                pointHoverBorderColor: '#00e6ff',
                pointHoverBorderWidth: 2,
                fill: true,
                backgroundColor: gradient,
                tension: 0.15
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 200 },
            plugins: {
                legend: { display: false },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                    backgroundColor: '#161a1e',
                    titleColor: '#848e9c',
                    bodyColor: '#eaecef',
                    borderColor: '#242c35',
                    borderWidth: 1,
                    titleFont: { family: 'Inter', size: 11 },
                    bodyFont: { family: 'JetBrains Mono', size: 12 },
                    callbacks: {
                        label: function(context) {
                            return ` Precio: $${context.raw.toLocaleString(undefined, { minimumFractionDigits: 2 })}`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(36, 44, 53, 0.4)' },
                    ticks: { color: '#848e9c', font: { family: 'Inter', size: 10 } }
                },
                y: {
                    grid: { color: 'rgba(36, 44, 53, 0.4)' },
                    ticks: { color: '#848e9c', font: { family: 'JetBrains Mono', size: 10 } }
                }
            }
        }
    });
}

function updateChart(price) {
    if (isNaN(price) || price <= 0) return;
    
    const now = new Date();
    const timeLabel = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    
    // Solo actualizamos la gráfica si no hay datos o el precio cambió
    if (chartData.length === 0 || chartData[chartData.length - 1] !== price) {
        chartLabels.push(timeLabel);
        chartData.push(price);
        
        if (chartLabels.length > chartLimit) {
            chartLabels.shift();
            chartData.shift();
        }
        
        if (priceChart) {
            priceChart.update();
        }
    }
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
    btnExecuteOrder.textContent = `Comprar ${baseAsset}`;
    
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
    btnExecuteOrder.textContent = `Vender ${baseAsset}`;
    
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
        availableFundsLabel.textContent = `${dispBase.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })} ${baseAsset}`;
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
    chartLabels = [];
    chartData = [];
    
    if (priceChart) {
        priceChart.data.labels = [];
        priceChart.data.datasets[0].data = [];
        priceChart.update();
    }
    
    renderWorkerTabs();
    
    // Limpiar inputs
    inputQty.value = "";
    inputTotal.value = "";
    clearActivePct();
    
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
        
        // Actualizar etiquetas de la interfaz
        quoteAssetLabels.forEach(lbl => lbl.textContent = quoteAsset);
        baseAssetLabels.forEach(lbl => lbl.textContent = baseAsset);
        
        // Status global del bot
        const isOnline = data.status === "ONLINE";
        botStatusDot.className = `status-dot ${isOnline ? 'online' : 'offline'}`;
        botStatusText.textContent = isOnline ? "ONLINE" : "OFFLINE";
        botMode.textContent = data.trading_mode;
        
        // Ticker Header
        lastPrice = data.last_price;
        const decimals = isForexOrEvent ? 4 : 2;
        headerPrice.textContent = `$${lastPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: decimals })}`;
        chartSymbolName.textContent = data.symbol;
        chartSourceName.textContent = data.feeder_type.toUpperCase() + " FEED";
        
        // Simular info de cabecera de Binance
        headerChange.textContent = isOnline ? "+1.42%" : "+0.00%";
        headerHigh.textContent = `$${(lastPrice * 1.02).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: decimals })}`;
        headerLow.textContent = `$${(lastPrice * 0.98).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: decimals })}`;
        headerVolume.textContent = `428.14 ${baseAsset}`;
        
        // Alimentar gráfica
        updateChart(lastPrice);
        
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
        
        viewEma9.textContent = ema9Val;
        viewEma21.textContent = ema21Val;
        viewRsi.textContent = rsiVal;
        
        detailEma9.textContent = ema9Val;
        detailEma21.textContent = ema21Val;
        detailRsiVal.textContent = rsiVal;
        
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
        paramSymbol.textContent = data.symbol;
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
                    <td>${order.symbol}</td>
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
                <td>${trade.symbol}</td>
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

function runOrderBookSimulation() {
    if (simulatedOrderBookInterval) clearInterval(simulatedOrderBookInterval);
    
    simulatedOrderBookInterval = setInterval(() => {
        if (lastPrice <= 0) return;
        
        const spreadPct = 0.0003;
        const tickSpacing = isForexOrEvent ? 0.0005 : 0.25;
        
        // Generar Asks (Venta)
        obAsks.innerHTML = "";
        const asks = [];
        let runningTotalAsk = 0;
        
        for (let i = 5; i >= 1; i--) {
            const price = lastPrice * (1 + spreadPct) + (i * tickSpacing);
            const qty = Math.random() * (isForexOrEvent ? 20000 : 0.8) + (isForexOrEvent ? 1000 : 0.05);
            runningTotalAsk += qty;
            asks.push({ price, qty, total: runningTotalAsk });
        }
        
        asks.forEach(ask => {
            const row = document.createElement("div");
            row.className = "ob-row ask";
            const depthVal = Math.min((ask.total / (asks[asks.length-1].total * 1.1)) * 100, 100);
            
            row.innerHTML = `
                <div class="ob-depth-bar" style="width: ${depthVal}%"></div>
                <span class="ob-price">${ask.price.toFixed(isForexOrEvent ? 4 : 2)}</span>
                <span class="text-right">${ask.qty.toFixed(isForexOrEvent ? 1 : 4)}</span>
                <span class="text-right">${(ask.qty * ask.price).toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
            `;
            
            // Permitir al usuario rellenar el formulario al hacer click en el precio
            row.addEventListener("click", () => {
                if (manualOrderType === "LIMIT") {
                    inputPrice.value = ask.price.toFixed(isForexOrEvent ? 4 : 2);
                }
                inputQty.value = formatAmountInput(ask.qty);
                inputTotal.value = (ask.qty * ask.price).toFixed(2);
            });
            
            obAsks.appendChild(row);
        });
        
        // Spread / Mid Price
        obMidVal.textContent = `$${lastPrice.toFixed(isForexOrEvent ? 4 : 2)}`;
        obMidDir.textContent = Math.random() > 0.4 ? "▲" : "▼";
        obMidDir.className = obMidDir.textContent === "▲" ? "mid-price-dir text-success" : "mid-price-dir text-danger";
        
        // Generar Bids (Compra)
        obBids.innerHTML = "";
        const bids = [];
        let runningTotalBid = 0;
        
        for (let i = 1; i <= 5; i++) {
            const price = lastPrice * (1 - spreadPct) - (i * tickSpacing);
            const qty = Math.random() * (isForexOrEvent ? 20000 : 0.8) + (isForexOrEvent ? 1000 : 0.05);
            runningTotalBid += qty;
            bids.push({ price, qty, total: runningTotalBid });
        }
        
        bids.forEach(bid => {
            const row = document.createElement("div");
            row.className = "ob-row bid";
            const depthVal = Math.min((bid.total / (bids[bids.length-1].total * 1.1)) * 100, 100);
            
            row.innerHTML = `
                <div class="ob-depth-bar" style="width: ${depthVal}%"></div>
                <span class="ob-price">${bid.price.toFixed(isForexOrEvent ? 4 : 2)}</span>
                <span class="text-right">${bid.qty.toFixed(isForexOrEvent ? 1 : 4)}</span>
                <span class="text-right">${(bid.qty * bid.price).toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
            `;
            
            row.addEventListener("click", () => {
                if (manualOrderType === "LIMIT") {
                    inputPrice.value = bid.price.toFixed(isForexOrEvent ? 4 : 2);
                }
                inputQty.value = formatAmountInput(bid.qty);
                inputTotal.value = (bid.qty * bid.price).toFixed(2);
            });
            
            obBids.appendChild(row);
        });
        
    }, 600);
}


// --- SIMULACIÓN DE TRADES RECIENTES ---
function runLiveTradesSimulation() {
    if (simulatedLiveTradesInterval) clearInterval(simulatedLiveTradesInterval);
    
    // Lista de trades inicial
    obLiveTrades.innerHTML = "";
    
    simulatedLiveTradesInterval = setInterval(() => {
        if (lastPrice <= 0) return;
        
        // Crear un trade aleatorio
        const now = new Date();
        const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        const side = Math.random() > 0.48 ? "buy" : "sell";
        const spreadShift = (Math.random() - 0.5) * 0.0004;
        const price = lastPrice * (1 + spreadShift);
        const qty = Math.random() * (isForexOrEvent ? 15000 : 0.4) + (isForexOrEvent ? 500 : 0.01);
        
        const row = document.createElement("div");
        row.className = `trade-row ${side === "buy" ? "text-success" : "text-danger"}`;
        row.innerHTML = `
            <span class="text-muted">${timeStr}</span>
            <span class="font-mono">${price.toFixed(isForexOrEvent ? 4 : 2)}</span>
            <span class="text-right font-mono">${qty.toFixed(isForexOrEvent ? 0 : 4)}</span>
        `;
        
        obLiveTrades.insertBefore(row, obLiveTrades.firstChild);
        
        // Limitar a 18 elementos
        if (obLiveTrades.children.length > 18) {
            obLiveTrades.removeChild(obLiveTrades.lastChild);
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
        <td><strong>${baseAsset}</strong> <span class="text-muted" style="font-size:0.75rem; margin-left:6px;">Cripto / Activo</span></td>
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


// --- INICIALIZAR LA APLICACIÓN ---
initChart();
loadWorkers().then(() => {
    fetchStatus();
    fetchLogs();
    fetchTrades();
    runOrderBookSimulation();
    runLiveTradesSimulation();
});

// Loops de Polling
setInterval(fetchStatus, 1000);   // Consultar status cada 1s
setInterval(fetchLogs, 2000);     // Consultar logs cada 2s
setInterval(fetchTrades, 3000);   // Consultar trades cada 3s
setInterval(loadWorkers, 10000);  // Actualizar lista de workers cada 10s
