// A thin reconnecting WebSocket client for one session. Reconnects on drop and
// re-syncs from the next full snapshot the server sends on (re)connect.

export type WsHandler = (msg: any) => void;

export class GameSocket {
  private ws: WebSocket | null = null;
  private url: string;
  private handler: WsHandler;
  private closed = false;
  private heartbeat?: number;

  constructor(sessionId: string, handler: WsHandler) {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    this.url = `${proto}://${location.host}/ws/${sessionId}`;
    this.handler = handler;
    this.connect();
  }

  private connect() {
    if (this.closed) return;
    const ws = new WebSocket(this.url);
    this.ws = ws;
    ws.onmessage = (ev) => {
      try {
        this.handler(JSON.parse(ev.data));
      } catch {
        /* ignore malformed frame */
      }
    };
    ws.onopen = () => {
      this.handler({ type: "_open" });
      this.heartbeat = window.setInterval(() => this.send({ type: "heartbeat" }), 20000);
    };
    ws.onclose = () => {
      window.clearInterval(this.heartbeat);
      this.handler({ type: "_close" });
      if (!this.closed) window.setTimeout(() => this.connect(), 1000);
    };
    ws.onerror = () => ws.close();
  }

  send(msg: any) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    }
  }

  close() {
    this.closed = true;
    window.clearInterval(this.heartbeat);
    this.ws?.close();
  }
}
