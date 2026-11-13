<script setup lang="ts">
import { computed, onUnmounted, ref } from "vue";
import { connectStream, matchState } from "../api";
import type { ChatItem, DiceState, Envelope, Judgment } from "../types";

const props = defineProps<{ matchId: string; mode: string }>();
const emit = defineEmits<{ ended: [summary: never] }>();

const chatItems = ref<ChatItem[]>([]);
const diceCards = ref<Record<number, DiceState>>({});
const scores = ref<number[]>([]);
const wildState = ref("fly");
const onesCalled = ref(false);
const currentBid = ref<[number, number] | null>(null);
const roundNo = ref(0);
const logLines = ref<string[]>([]);
const logPath = ref<string | null>(null);
const logOpen = ref(false);
const status = ref("RUNNING");
const lastSeq = ref<number | null>(null);
const chatEl = ref<HTMLElement | null>(null);
const autoScroll = ref(true);

const playerCount = computed(() => scores.value.length || 4);
const role = computed(() => (props.mode === "eve" ? "spectator" : "player"));

function seatName(seat: number | string): string {
  const idx = Number(seat);
  return `${idx}号`;
}

function push(item: ChatItem) {
  chatItems.value.push(item);
  // 长局回放截断：只保留最近 300 条（LOG 抽屉才是全量载体，04 §5）
  if (chatItems.value.length > 300) chatItems.value.splice(0, chatItems.value.length - 300);
  if (autoScroll.value && chatEl.value) {
    requestAnimationFrame(() => chatEl.value?.scrollTo(0, chatEl.value.scrollHeight));
  }
}

function handleEnvelope(e: Envelope) {
  // seq 追踪（G-02）：断线重连按 last_seq 补发
  if (typeof e.seq === "number" && e.seq > 0) lastSeq.value = e.seq;
  logLines.value.push(JSON.stringify(e));
  const p = e.payload as Record<string, never>;
  switch (e.type) {
    case "RoundStarted":
      roundNo.value = Number(p.round_no);
      push({ kind: "system", seq: e.seq, text: `第 ${p.round_no} 局开始，${p.caller} 号起叫` });
      break;
    case "Rerolled":
      push({ kind: "system", seq: e.seq, text: `${seatName(String(p.seat))} 散骰重摇（第 ${p.times} 次）` });
      break;
    case "HandObserved": {
      const seat = Number(p.seat);
      diceCards.value[seat] = {
        seat,
        name: seatName(seat),
        dice: (p.dice as number[]).map(Number),
        flag: (p.leopard_flag as string | null) ?? null,
      };
      break;
    }
    case "ThinkingObserved":
      // 内心戏气泡（04 §4）：灰底斜体 + 内心角标；仅 EVE 观战流出现（F-06）
      push({ kind: "think", seq: e.seq, seat: Number(p.seat), name: seatName(String(p.seat)), text: String(p.thinking_text) });
      break;
    case "BidMade": {
      const kindText = p.kind === "zhai" ? "（斋）" : p.kind === "fei" ? "（飞）" : "";
      const badge = `${p.count} 个 ${p.face}${kindText}`;
      wildState.value = String(p.wild_state ?? wildState.value);
      onesCalled.value = Boolean(p.ones_called);
      push({
        kind: "quote",
        seq: e.seq,
        seat: Number(p.seat),
        name: seatName(String(p.seat)),
        quote: String(p.quote ?? ""),
        badge,
      });
      currentBid.value = [Number(p.count), Number(p.face)];
      break;
    }
    case "ChallengeMade": {
      const targets = (p.targets as number[]).join("、");
      push({
        kind: "system",
        seq: e.seq,
        emphasis: p.kind === "jump" ? "challenge" : undefined,
        text: `${seatName(String(p.seat))} 发起${p.kind === "jump" ? "跳杀" : p.kind === "sweep" ? "通杀" : p.kind === "multi" ? "连杀" : "开杀"} → ${targets}！×${p.base_multiplier}`,
      });
      break;
    }
    case "Responded": {
      const choice = String(p.choice);
      const text =
        choice === "surrender"
          ? `${seatName(String(p.seat))} 投降（当前惩罚减半）`
          : choice === "counter"
            ? `${seatName(String(p.seat))} 反杀！`
            : choice === "recounter"
              ? `${seatName(String(p.seat))} 再反杀！`
              : `${seatName(String(p.seat))} 开盅清点`;
      push({ kind: "system", seq: e.seq, text, emphasis: choice !== "reveal" ? "challenge" : undefined });
      if (p.wild_state) wildState.value = String(p.wild_state);
      break;
    }
    case "Revealed": {
      wildState.value = String(p.wild_state ?? wildState.value);
      onesCalled.value = Boolean(p.ones_called);
      push({
        kind: "reveal",
        seq: e.seq,
        hands: p.hands as Record<string, number[]>,
        judgments: p.judgments as Judgment[],
        darkness: Boolean(p.darkness),
      });
      break;
    }
    case "RoundSettled": {
      scores.value = (p.scores as number[]).map(Number);
      const detail = (p.entries as { seat: number; codes: number; multiplier: number[] }[])
        .map((x) => `${x.seat}号 ${x.codes} 码`)
        .join("；");
      push({ kind: "system", seq: e.seq, emphasis: "settle", text: `第 ${p.round_no} 局结算：${detail || "无输家"}` });
      break;
    }
    case "TurnDegraded":
      push({ kind: "system", seq: e.seq, emphasis: "degrade", text: `${seatName(String(p.seat))} 决策失败，引擎代打（${p.reason}）` });
      break;
    case "MatchEnded":
      scores.value = (p.scores as number[]).map(Number);
      push({ kind: "system", seq: e.seq, text: `终局（${p.reason}）：积分最小者胜 → ${(p.winners as number[]).map(seatName).join("、")}` });
      status.value = "ENDED";
      break;
    case "MatchStateChanged":
      status.value = String(p.status);
      break;
    default:
      break;
  }
}

let conn: { close: () => void } | null = null;
let pollTimer: number | null = null;

// 宿主 WS + 轮询兜底：status ENDED 即转结束页（W1 断线恢复 = last_seq 补发）
conn = connectStream(
  props.matchId,
  role.value,
  (e: Envelope) => {
    handleEnvelope(e);
    if (e.type === "MATCH_ENDED") {
      fetchSummaryThenEnd();
    }
  },
  () => {},
  { getLastSeq: () => lastSeq.value },
);

async function fetchSummaryThenEnd() {
  const s = await matchState(props.matchId);
  emit("ended", s as never);
}

pollTimer = window.setInterval(async () => {
  try {
    const s = await matchState(props.matchId);
    status.value = s.status;
    if (s.status === "ENDED" || s.status === "ABANDONED") {
      if (chatItems.value.some((c) => c.kind === "system" && c.text.startsWith("终局"))) {
        fetchSummaryThenEnd();
      }
    }
  } catch {
    /* 轮询失败忽略（WS 重连中） */
  }
}, 2000);

onUnmounted(() => {
  conn?.close();
  if (pollTimer) window.clearInterval(pollTimer);
});

function onScroll() {
  const el = chatEl.value;
  if (!el) return;
  autoScroll.value = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
}
</script>

<template>
  <div class="row panel">
    <h1 style="font-size: 16px">对局 · {{ mode === "eve" ? "EVE 观战" : "PVE" }}</h1>
    <div class="spacer" />
    <span>第 {{ roundNo }} 局</span>
    <span class="state-lamp" :class="wildState === 'fly' ? 'lamp-fly' : 'lamp-dead'">
      {{ wildState === "fly" ? "飞 · 1 是癞子" : "斋/过 1 · 1 按面值" }}{{ onesCalled ? "（已过 1）" : "" }}
    </span>
    <span style="color: var(--muted); font-size: 13px">状态 {{ status }}</span>
    <span v-if="currentBid" style="color: var(--accent)">当前叫骰 {{ currentBid[0] }} 个 {{ currentBid[1] }}</span>
  </div>

  <div class="row" style="align-items: stretch">
    <div class="panel" style="flex: 3; min-width: 0">
      <div ref="chatEl" class="chat" @scroll="onScroll">
        <template v-for="(item, i) in chatItems" :key="i">
          <div v-if="item.kind === 'quote'" class="bubble bubble-quote">
            <div class="meta"><span class="tag">玩家发言</span>{{ item.name }}</div>
            {{ item.quote || "（沉默出手）" }}<span class="badge">{{ item.badge }}</span>
          </div>
          <div v-else-if="item.kind === 'think'" class="bubble bubble-think">
            <div class="meta"><span class="tag">内心</span>{{ item.name }} 的思考（不可信文本，仅观战直出 F-06）</div>
            {{ item.text }}
          </div>
          <div v-else-if="item.kind === 'reveal'" class="bubble bubble-system">
            开盅{{ item.darkness ? "（天黑黑！全场无真点）" : "" }}：
            <span v-for="(dice, seat) in item.hands" :key="seat" style="margin-right: 8px">
              {{ seat }}号[{{ dice.join(",") }}]
            </span>
            <div v-for="j in item.judgments" :key="j.seat" style="font-size: 13px">
              → {{ j.seat }}号叫 {{ j.bid[0] }} 个 {{ j.bid[1] }}：count={{ j.count }} ⇒ {{ j.stood ? "成立（开杀方输）" : "不成立（被杀方输）" }}
            </div>
          </div>
          <div v-else class="bubble bubble-system" :class="item.emphasis ? `emphasis-${item.emphasis}` : ''">
            {{ item.text }}
          </div>
        </template>
      </div>
      <div class="log-toggle" @click="logOpen = !logOpen">
        {{ logOpen ? "▾" : "▸" }} 文本 LOG（同源不同形 · 边打边写 {{ logLines.length }} 行）
        <span v-if="logPath" style="margin-left: 8px">{{ logPath }}</span>
      </div>
      <div v-if="logOpen" class="log-drawer">{{ logLines.join("\n") }}</div>
    </div>

    <div class="panel" style="flex: 1">
      <h2>积分榜（1 码 = 1 分）</h2>
      <div class="scoreboard">
        <div v-for="(s, i) in scores" :key="i">
          <span>{{ seatName(String(i)) }}</span><span :style="s >= 100 ? 'color: var(--danger)' : ''">{{ s }}</span>
        </div>
      </div>
      <h2>骰盅区（EVE 实时 / 围骰标注来自引擎 F-09）</h2>
      <div class="dice-row">
        <div v-for="card in diceCards" :key="card.seat" class="dice-card" :class="{ leopard: card.flag }">
          <div class="who">{{ card.name }}</div>
          <div class="dice">{{ card.dice.join(" ") }}</div>
          <div v-if="card.flag" class="flag">{{ card.flag }}！</div>
        </div>
      </div>
    </div>
  </div>
</template>
