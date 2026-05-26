let ws;

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

    ws.onmessage = function(event) {
        const data = JSON.parse(event.data);
        if (data.type === 'state_update') {
            updateState(data);
        } else if (data.type === 'scan_results') {
            renderScanResults(data.results);
        }
    };

    ws.onclose = function() {
        setTimeout(connectWebSocket, 1000); // Auto-reconnect
    };
}

function updateState(state) {
    // Update theme/context
    document.body.setAttribute('data-context', state.read_point);
    document.getElementById('readPointSelect').value = state.read_point;
    
    // Update Header
    document.getElementById('context-title').innerText = state.read_point.replace('_', ' ');

    // Update Connection Button
    const btnConnect = document.getElementById('btn-connect');
    if (state.is_connected) {
        btnConnect.innerText = "🔌 Disconnect Reader";
        btnConnect.classList.add('danger');
    } else {
        btnConnect.innerText = "🔌 Connect Reader";
        btnConnect.classList.remove('danger');
    }

    // Update Monitor Button
    const btnMonitor = document.getElementById('btn-monitor');
    if (state.is_monitoring) {
        btnMonitor.innerText = "⏹ Stop Monitoring";
        btnMonitor.classList.add('danger');
    } else {
        btnMonitor.innerText = "▶ Start Monitoring";
        btnMonitor.classList.remove('danger');
    }

    // Render KPIs based on context
    renderKPIs(state.kpis, state.read_point);

    // Render Event Log
    renderLog(state.events);
}

function renderKPIs(kpis, context) {
    const container = document.getElementById('kpi-container');
    container.innerHTML = ''; // Clear

    let kpiData = [];
    if (context === "PACKAGING_LINE") {
        kpiData = [
            { label: "Total Assets in DB", value: kpis.total_assets },
            { label: "Packed Today", value: kpis.packed }
        ];
    } else if (context === "SMART_TRUCK") {
        kpiData = [
            { label: "Batches in Transit", value: kpis.in_transit }
        ];
    } else if (context === "SMART_CABINET") {
        kpiData = [
            { label: "In Cabinet", value: kpis.in_cabinet },
            { label: "Expired Alerts", value: kpis.expired }
        ];
    } else if (context === "DESK") {
        kpiData = [
            { label: "Dispensed", value: kpis.dispensed }
        ];
    } else if (context === "WASTE_CONTAINER") {
        kpiData = [
            { label: "Disposed", value: kpis.disposed }
        ];
    }

    kpiData.forEach(k => {
        container.innerHTML += `
            <div class="glass-panel kpi-card">
                <label>${k.label}</label>
                <div class="kpi-value">${k.value}</div>
            </div>
        `;
    });
}

function renderScanResults(results) {
    const container = document.getElementById('results-container');
    
    results.forEach(res => {
        const isOk = res.status === "OK";
        const asset = res.asset;
        if(!asset) return;

        const card = document.createElement('div');
        card.className = `glass-panel asset-card ${isOk ? 'ok' : 'alert'}`;
        
        let html = `
            <div class="asset-header">
                <span>${asset.epc}</span>
                <span>${isOk ? '🟢' : '🔴'}</span>
            </div>
            <div class="asset-detail">Batch: <strong>${asset.batch}</strong></div>
            <div class="asset-detail">Expiry: <strong>${asset.expiryDate}</strong></div>
            <div class="asset-detail">State: <strong>${asset.currentState}</strong></div>
        `;

        if (!isOk) {
            html += `<div class="alert-msg">${res.message}</div>`;
        }

        card.innerHTML = html;
        container.prepend(card); // Add to top
        
        // Remove old cards if > 6
        if(container.children.length > 6) {
            container.removeChild(container.lastChild);
        }
    });
}

function renderLog(events) {
    const tbody = document.getElementById('log-body');
    tbody.innerHTML = '';
    
    // Reverse events for newest first
    [...events].reverse().forEach(e => {
        const alerts = e.alerts && e.alerts.length > 0 ? e.alerts.join(', ') : 'OK';
        const isAlert = alerts !== 'OK';
        
        const tr = document.createElement('tr');
        if (isAlert) tr.className = 'row-alert';
        
        tr.innerHTML = `
            <td>${e.timestamp.split('T')[1].split('.')[0]}</td>
            <td>${e.epc}</td>
            <td>${e.readPoint}</td>
            <td>${e.action}</td>
            <td>${e.newState}</td>
            <td>${alerts}</td>
        `;
        tbody.appendChild(tr);
    });
}

// API Calls
async function toggleConnection() {
    const port = document.getElementById('portInput').value;
    await fetch('/api/connect', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({port: port})
    });
}

async function changeReadPoint() {
    const rp = document.getElementById('readPointSelect').value;
    document.getElementById('results-container').innerHTML = ''; // Clear results on switch
    await fetch('/api/read_point', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({read_point: rp})
    });
}

async function toggleMonitor() {
    await fetch('/api/monitor', { method: 'POST' });
}

// Init
window.onload = connectWebSocket;
