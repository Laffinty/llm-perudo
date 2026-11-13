import type { Envelope, MatchSummary, SlotSpec } from "./types";

export async function createMatch(spec: {
  mode: string;
  slots: SlotSpec[];
  config: Record<string, unknown>;
}): Promise<MatchSummary> {
  const res = await fetch("/matches", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(spec),
  });
  if (!res.ok) throw new Error((await res.json()).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function listMatches(): Promise<MatchSummary[]> {
  const res = await fetch("/matches");
  return res.json();
}

export async function matchState(matchId: string, action: string): Promise<MatchSummary> {
  const res = await fetch(`/matches/${matchId}/state`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
  if (!res.ok) throw new Error((await res.json()).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function fetchPending(matchId: string): Promise<{ waiting: boolean; view?: unknown }> {
  const res = await fetch(`/matches/${matchId}/pending`);
  if (!res.ok) return { waiting: false };
  return res.json();
}

export async function submitAction(matchId: string, action: Record<string, unknown>): Promise<void> {
  const res = await fetch(`/matches/${matchId}/action`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
  if (!res.ok) throw new Error((await res.json()).detail ?? `HTTP ${res.status}`);
}

/** 视图流 WS 客户端（G-02：last_seq 补发 + 断线自动重连全量重放）。 */
export function connectStream(
  matchId: string,
  role: string,
  onEnvelope: (e: Envelope) => void,
  onBacklogDone: () => void,
  opts: { getLastSeq: () => number | null; reconnectMs?: number },
): { close: () => void } {
  let ws: WebSocket | null = null;
  let closed = false;
  let sawEnded = false;
  const connect = () => {
    const lastSeq = opts.getLastSeq();
    const qs = lastSeq === null ? `role=${role}` : `role=${role}&last_seq=${lastSeq}`;
    ws = new WebSocket(`ws://${location.host}/matches/${matchId}/stream?${qs}`);
    ws.onmessage = (msg) => {
      const envelope = JSON.parse(msg.data) as Envelope;
      if (envelope.type === "BacklogDone") {
        onBacklogDone();
        return;
      }
      if (envelope.type === "Error") {
        console.error("stream error", envelope.payload);
        return;
      }
      if (envelope.type === "MATCH_ENDED" || envelope.type === "MATCH_STATE_CHANGED") {
        const status = (envelope.payload as { status?: string }).status;
        if (envelope.type === "MATCH_ENDED" || status === "ABANDONED") sawEnded = true;
      }
      onEnvelope(envelope);
    };
    ws.onclose = () => {
      if (closed || sawEnded) return; // 终局收束后不再重连（结束页接管）
      setTimeout(connect, opts.reconnectMs ?? 1500);
    };
  };
  connect();
  return { close: () => { closed = true; ws?.close(); } };
}
