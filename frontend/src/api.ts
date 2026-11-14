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

export type PendingView = {
  waiting: boolean;
  view?: {
    seat: number;
    round_no: number;
    phase: string;
    my_hand: number[];
    current_bid: number[] | null;
    legal_actions: Record<string, unknown>[];
    correction_reason: string;
  };
};

export async function fetchPending(matchId: string): Promise<PendingView> {
  const res = await fetch(`/matches/${matchId}/pending`);
  if (!res.ok) return { waiting: false };
  return res.json();
}

export async function submitAction(
  matchId: string,
  action: Record<string, unknown>,
  quote = "",
): Promise<void> {
  const res = await fetch(`/matches/${matchId}/action`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, quote }),
  });
  if (!res.ok) throw new Error((await res.json()).detail ?? `HTTP ${res.status}`);
}

/** 视图流 WS 客户端（G-02：last_seq 补发 + 断线自动重连全量重放）。 */
export function connectStream(
  matchId: string,
  role: string,
  onEnvelope: (e: Envelope) => void,
  onBacklogDone: () => void,
  opts: { getLastSeq: () => number | null; reconnectMs?: number; seat?: number },
): { close: () => void } {
  let ws: WebSocket | null = null;
  let closed = false;
  let sawEnded = false;
  const connect = () => {
    const lastSeq = opts.getLastSeq();
    const seatQs = opts.seat !== undefined ? `&seat=${opts.seat}` : "";
    const qs =
      lastSeq === null
        ? `role=${role}${seatQs}`
        : `role=${role}&last_seq=${lastSeq}${seatQs}`;
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
      if (
        envelope.type === "MatchEnded" ||
        (envelope.type === "MatchStateChanged" &&
          (envelope.payload as { status?: string }).status === "ABANDONED")
      ) {
        sawEnded = true;
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
