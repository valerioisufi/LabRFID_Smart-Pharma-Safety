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
        } else if (data.type === 'new_system_log') {
            appendSystemLog(data.log, data.level);
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
    
    // Toggle Commission Form visibility
    const commissionForm = document.getElementById('commission-form');
    if (state.read_point === 'PACKAGING_LINE') {
        commissionForm.style.display = 'block';
    } else {
        commissionForm.style.display = 'none';
    }
    
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

    // Update Monitor Button (hide it if we are in PACKAGING_LINE because we use the Conveyor controls instead)
    const btnMonitor = document.getElementById('btn-monitor');
    if (state.read_point === 'PACKAGING_LINE') {
        btnMonitor.style.display = 'none';
        
        // Update Belt Controls
        if (state.batch_active) {
            document.getElementById('btn-start-batch').style.display = 'none';
            document.getElementById('btn-stop-batch').style.display = 'block';
            document.getElementById('belt-status-indicator').style.display = 'flex';
            // Disable inputs
            document.querySelectorAll('#commission-form input').forEach(i => i.disabled = true);
        } else {
            document.getElementById('btn-start-batch').style.display = 'block';
            document.getElementById('btn-stop-batch').style.display = 'none';
            document.getElementById('belt-status-indicator').style.display = 'none';
            // Enable inputs
            document.querySelectorAll('#commission-form input').forEach(i => i.disabled = false);
        }
    } else {
        btnMonitor.style.display = 'flex'; // show the generic monitor button
        if (state.is_monitoring) {
            btnMonitor.innerText = "⏹ Stop Monitoring";
            btnMonitor.classList.add('danger');
        } else {
            btnMonitor.innerText = "▶ Start Monitoring";
            btnMonitor.classList.remove('danger');
        }
    }

    // Render KPIs based on context
    renderKPIs(state.kpis, state.read_point);

    // Render Event Log
    renderLog(state.events);

    // Render system logs if present
    if (state.system_logs) {
        const consoleBody = document.getElementById('console-body');
        if (consoleBody) {
            consoleBody.innerHTML = '';
            state.system_logs.forEach(logLine => {
                let level = "INFO";
                if (logLine.includes(" - WARNING - ")) level = "WARNING";
                else if (logLine.includes(" - ERROR - ")) level = "ERROR";
                
                const entry = document.createElement('div');
                entry.className = `log-entry ${level}`;
                entry.innerText = logLine;
                consoleBody.appendChild(entry);
            });
            consoleBody.scrollTop = consoleBody.scrollHeight;
        }
    }
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
            <td>${new Date(e.timestamp).toLocaleTimeString()}</td>
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
    const port = document.getElementById('portSelect').value;
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

async function startBatch() {
    const gtin = document.getElementById('inp-gtin').value;
    const batch = document.getElementById('inp-batch').value;
    const expiry = document.getElementById('inp-expiry').value;
    const aic = document.getElementById('inp-aic').value;
    const serial_offset = document.getElementById('inp-offset').value;
    
    await fetch('/api/start_batch', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ gtin, batch, expiry, aic, serial_offset })
    });
}

async function stopBatch() {
    await fetch('/api/stop_batch', { method: 'POST' });
}

function appendSystemLog(logText, level = "INFO") {
    const consoleBody = document.getElementById('console-body');
    if (!consoleBody) return;
    
    const entry = document.createElement('div');
    entry.className = `log-entry ${level}`;
    entry.innerText = logText;
    consoleBody.appendChild(entry);
    
    // Auto-scroll to bottom
    consoleBody.scrollTop = consoleBody.scrollHeight;
}

async function loadAvailablePorts() {
    try {
        const response = await fetch('/api/ports');
        const data = await response.json();
        const select = document.getElementById('portSelect');
        if (!select) return;
        
        select.innerHTML = ''; // Clear
        
        if (data.ports.length === 0) {
            const opt = document.createElement('option');
            opt.value = '';
            opt.innerText = 'Nessuna porta rilevata';
            select.appendChild(opt);
            return;
        }
        
        let selectedIndex = 0;
        data.ports.forEach((port, idx) => {
            const opt = document.createElement('option');
            opt.value = port;
            opt.innerText = port;
            select.appendChild(opt);
            
            // Prefer FTDI/USB serial ports or matching cu.usbserial on macOS
            if (port.includes('usbserial') || port.includes('ttyUSB') || port.includes('COM3')) {
                selectedIndex = idx;
            }
        });
        
        select.selectedIndex = selectedIndex;
    } catch (error) {
        console.error("Error loading ports:", error);
    }
}

// Init
window.onload = function() {
    connectWebSocket();
    loadAvailablePorts();
};
