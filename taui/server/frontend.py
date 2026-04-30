"""Inline HTML/JS frontend for the taui web UI."""

INDEX_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>taui</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg: #111; --surface: #191919; --border: #333;
    --text: #e0e0e0; --subtext: #777; --accent: #fff;
    --red: #c44;
    --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    --mono: ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, monospace;
  }
  html, body { height: 100%; background: var(--bg); color: var(--text); font-family: var(--sans); font-size: 14px; }
  body { display: flex; flex-direction: column; }

  #header { display: flex; align-items: center; gap: 10px; padding: 8px 16px; border-bottom: 1px solid var(--border); flex-shrink: 0; }
  #header h1 { font-size: 14px; font-weight: 500; letter-spacing: .02em; }
  #status { font-size: 11px; font-family: var(--mono); color: var(--subtext); }
  #status.status-connected { color: #6a6; }
  #status.status-disconnected { color: var(--red); }
  #session-info { margin-left: auto; font-size: 11px; font-family: var(--mono); color: var(--subtext); }

  #messages { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 2px; }
  .msg { padding: 8px 0; white-space: pre-wrap; word-wrap: break-word; line-height: 1.6; font-size: 13px; font-family: var(--mono); border-bottom: 1px solid var(--border); }
  .msg:last-child { border-bottom: none; }
  .msg-label { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; color: var(--subtext); margin-bottom: 4px; }
  .msg-user .msg-label { color: var(--accent); }
  .msg-body { color: var(--text); }
  .msg-meta { font-size: 11px; color: var(--subtext); margin-top: 4px; }
  .msg-error .msg-body { color: var(--red); }

  #input-area { display: flex; gap: 0; border-top: 1px solid var(--border); flex-shrink: 0; }
  #input { flex: 1; background: var(--surface); color: var(--text); border: none; padding: 12px 16px; font-family: var(--mono); font-size: 13px; resize: none; outline: none; min-height: 44px; max-height: 200px; }
  #send-btn { background: none; color: var(--subtext); border: none; border-left: 1px solid var(--border); padding: 12px 20px; font-family: var(--sans); font-size: 13px; cursor: pointer; flex-shrink: 0; }
  #send-btn:hover { color: var(--accent); }
  #send-btn:disabled { opacity: 0.3; cursor: default; }
</style>
</head>
<body>

<div id="header">
  <h1>taui</h1>
  <span id="status" class="status-connecting">connecting</span>
  <span id="session-info"></span>
</div>

<div id="messages"></div>

<div id="input-area">
  <textarea id="input" rows="1" placeholder=">" autofocus></textarea>
  <button id="send-btn" disabled>send</button>
</div>

<script>
(function() {
  const messagesEl = document.getElementById('messages');
  const inputEl = document.getElementById('input');
  const sendBtn = document.getElementById('send-btn');
  const statusEl = document.getElementById('status');
  const sessionInfo = document.getElementById('session-info');

  let ws = null;
  let nextId = 1;
  const pending = new Map();
  let reconnectTimer = null;
  let backoff = 500;
  let connected = false;

  function setStatus(s) {
    statusEl.textContent = s;
    statusEl.className = 'status-' + s;
    connected = s === 'connected';
    sendBtn.disabled = !connected;
  }

  function scrollBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function addMessage(text, cls, meta) {
    const div = document.createElement('div');
    div.className = 'msg ' + cls;
    const label = document.createElement('div');
    label.className = 'msg-label';
    label.textContent = cls.includes('msg-user') ? 'you' : 'taui';
    div.appendChild(label);
    const body = document.createElement('div');
    body.className = 'msg-body';
    body.textContent = text;
    div.appendChild(body);
    if (meta) {
      const m = document.createElement('div');
      m.className = 'msg-meta';
      m.textContent = meta;
      div.appendChild(m);
    }
    messagesEl.appendChild(div);
    scrollBottom();
  }

  function rpcCall(method, params) {
    return new Promise((resolve, reject) => {
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        reject(new Error('Not connected'));
        return;
      }
      const id = nextId++;
      pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ jsonrpc: '2.0', method, params: params || {}, id }));
    });
  }

  function connect() {
    if (ws) { try { ws.close(); } catch(e) {} }
    setStatus('connecting');
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(proto + '//' + location.host + '/ws');

    ws.onopen = async function() {
      setStatus('connected');
      backoff = 500;
      try {
        const st = await rpcCall('agent/status');
        sessionInfo.textContent = 'session: ' + (st.session_id || '').slice(0, 8);
      } catch(e) {}
    };

    ws.onmessage = function(ev) {
      let msg;
      try { msg = JSON.parse(ev.data); } catch(e) { return; }
      if (msg.id != null && pending.has(msg.id)) {
        const p = pending.get(msg.id);
        pending.delete(msg.id);
        if (msg.error) {
          p.reject(new Error(msg.error.message || 'RPC error'));
        } else {
          p.resolve(msg.result);
        }
      }
    };

    ws.onclose = function() {
      setStatus('disconnected');
      pending.forEach(p => p.reject(new Error('Connection lost')));
      pending.clear();
      reconnectTimer = setTimeout(connect, backoff);
      backoff = Math.min(backoff * 2, 10000);
    };

    ws.onerror = function() {
      ws.close();
    };
  }

  async function sendMessage() {
    const text = inputEl.value.trim();
    if (!text || !connected) return;
    inputEl.value = '';
    inputEl.style.height = 'auto';
    addMessage(text, 'msg-user');
    sendBtn.disabled = true;

    try {
      const result = await rpcCall('agent/send', { message: text });
      const meta = result.turns + ' turn(s), ' + result.tool_uses + ' tool call(s), ' + result.elapsed_ms + 'ms';
      addMessage(result.text, 'msg-ai', meta);
    } catch(e) {
      addMessage('Error: ' + e.message, 'msg-ai msg-error');
    } finally {
      sendBtn.disabled = !connected;
      inputEl.focus();
    }
  }

  sendBtn.addEventListener('click', sendMessage);
  inputEl.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
  inputEl.addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 200) + 'px';
  });

  connect();
})();
</script>
</body>
</html>
"""
