const btnConnect    = document.getElementById('btnConnect');
const btnDisconnect = document.getElementById('btnDisconnect');
const statusDiv     = document.getElementById('status');
const tbody         = document.querySelector('#data-table tbody');

let ws = null;

// Función que actualiza la tabla con un objeto de datos
function updateTable(data) {
  tbody.innerHTML = '';
  Object.entries(data).forEach(([tag, value]) => {
    const tr = document.createElement('tr');
    const tdTag = document.createElement('td');
    const tdVal = document.createElement('td');
    tdTag.textContent = tag;
    tdVal.textContent = value;
    tr.append(tdTag, tdVal);
    tbody.append(tr);
  });
}

// Conectar WebSocket
btnConnect.addEventListener('click', () => {
  ws = new WebSocket(`ws://${location.host}/ws`);

  ws.onopen = () => {
    statusDiv.textContent = 'WebSocket conectado. Recibiendo datos…';
    btnConnect.disabled    = true;
    btnDisconnect.disabled = false;
  };

  ws.onmessage = evt => {
    let parsed;
    try {
      parsed = JSON.parse(evt.data);
    } catch {
      return; // ignoramos strings no JSON
    }
    if (Array.isArray(parsed) && parsed.length > 0) {
      updateTable(parsed[0]);
      const now = new Date().toLocaleTimeString();
      statusDiv.textContent = `Última actualización: ${now}`;
    }
  };

  ws.onclose = () => {
    statusDiv.textContent = 'WebSocket desconectado.';
    btnConnect.disabled    = false;
    btnDisconnect.disabled = true;
  };
});

// Desconectar WebSocket
btnDisconnect.addEventListener('click', () => {
  if (ws) {
    ws.close();
    ws = null;
  }
});
