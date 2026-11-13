export type Envelope = {
  seq: number;
  type: string;
  payload: Record<string, unknown>;
};

export type SlotSpec = {
  kind: "bot" | "llm" | "human";
  name?: string;
  provider?: string;
  model?: string;
  api_key_ref?: string;
  base_url?: string;
  persona_name?: string;
  persona_style?: string;
  trash_talk?: number;
  thinking?: string;
};

export type MatchSummary = {
  match_id: string;
  mode: string;
  status: string;
  round_no: number;
  scores: number[];
  event_count: number;
  log_path: string | null;
  created_at: string;
};

export type ChatItem =
  | { kind: "quote"; seq: number; seat: number; name: string; quote: string; badge: string }
  | { kind: "think"; seq: number; seat: number; name: string; text: string }
  | { kind: "system"; seq: number; text: string; emphasis?: "challenge" | "degrade" | "settle" }
  | { kind: "reveal"; seq: number; hands: Record<string, number[]>; judgments: Judgment[]; darkness: boolean };

export type Judgment = { seat: number; bid: number[]; count: number; stood: boolean };

export type DiceState = { seat: number; name: string; dice: number[]; flag: string | null };

export const SEAT_NAMES = (n: number) => Array.from({ length: n }, (_, i) => ` seat${i}`);
