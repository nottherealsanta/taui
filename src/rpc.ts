export class RpcClient {
  private url: string;
  private ws: WebSocket | null = null;
  private nextId: number = 1;
  private pending: Map<number, { resolve: (value: any) => void; reject: (error: Error) => void }> = new Map();
  private notificationHandlers: Set<(method: string, params: any) => void> = new Set();

  constructor(url: string) {
    this.url = url;
  }

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(this.url);
      this.ws = ws;

      ws.addEventListener('open', () => resolve());
      ws.addEventListener('error', (event) => reject(new Error(`WebSocket failed: ${event.type}`)));
      ws.addEventListener('close', () => {
        for (const [, req] of this.pending) {
          req.reject(new Error('Socket closed'));
        }
        this.pending.clear();
      });
      ws.addEventListener('message', (event) => this.onMessage(event.data));
    });
  }

  request(method: string, params: any = {}): Promise<any> {
    const id = this.nextId++;
    const payload = { jsonrpc: '2.0', id, method, params };
    this.send(payload);
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
    });
  }

  notify(method: string, params: any = {}) {
    this.send({ jsonrpc: '2.0', method, params });
  }

  onNotification(handler: (method: string, params: any) => void): () => void {
    this.notificationHandlers.add(handler);
    return () => this.notificationHandlers.delete(handler);
  }

  close() {
    this.ws?.close();
  }

  private send(payload: any) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error('Socket not connected');
    }
    this.ws.send(JSON.stringify(payload));
  }

  private onMessage(raw: string) {
    const msg = JSON.parse(raw);
    if (Object.prototype.hasOwnProperty.call(msg, 'id')) {
      const req = this.pending.get(msg.id);
      if (!req) {
        return;
      }
      this.pending.delete(msg.id);
      if (msg.error) {
        req.reject(new Error(msg.error.message || 'RPC error'));
        return;
      }
      req.resolve(msg.result);
      return;
    }

    if (msg.method) {
      for (const handler of this.notificationHandlers) {
        handler(msg.method, msg.params || {});
      }
    }
  }
}
