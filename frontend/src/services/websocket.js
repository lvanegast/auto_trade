export class WebSocketClient {
  constructor(workerId, onMessage, onStatusChange) {
    this.workerId = workerId;
    this.onMessage = onMessage;
    this.onStatusChange = onStatusChange;
    this.ws = null;
    this.reconnectTimer = null;
    this.isDisposed = false;
  }

  connect() {
    if (this.isDisposed) return;
    
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const wsUrl = `${protocol}//${host}/ws/${this.workerId}`;

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        if (this.onStatusChange) this.onStatusChange(true);
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (this.onMessage) this.onMessage(data);
        } catch (err) {
          console.error('[WS Error]', err);
        }
      };

      this.ws.onclose = () => {
        if (this.onStatusChange) this.onStatusChange(false);
        if (!this.isDisposed) {
          this.reconnectTimer = setTimeout(() => this.connect(), 3000);
        }
      };

      this.ws.onerror = () => {
        if (this.ws) this.ws.close();
      };
    } catch (e) {
      if (!this.isDisposed) {
        this.reconnectTimer = setTimeout(() => this.connect(), 3000);
      }
    }
  }

  disconnect() {
    this.isDisposed = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.ws) {
      try { this.ws.close(); } catch (_) {}
      this.ws = null;
    }
  }
}
