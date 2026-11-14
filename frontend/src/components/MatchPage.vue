<script setup lang="ts">
import { computed, onUnmounted, ref } from "vue";
import { connectStream, fetchPending, matchState, submitAction } from "../api";
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
const myHandRevealed = ref(false);

const pending = ref<Awaited<ReturnType<typeof fetchPending>>>({ waiting: false });
const quote = ref("");
const submitError = ref("");
const bidCount = ref(0);
const bidFace = ref(3);
const bidKind = ref("normal");
const selectedResponse = ref("reveal");
const selectedChallenge = ref<{ kind: string; targets: number[] }>({ kind: "open", targets: [] });
const confirmAbandon = ref(false);

const isPve = computed(() => props.mode === "pve");

const legalBids = computed(() =>
  (pending.value.view?.legal_actions ?? []).filter((a) => a.t === "bid"),
);
const legalChallenges = computed(() =>
  (pending.value.view?.legal_actions ?? []).filter((a) => a.t === "challenge"),
);
const legalResponses = computed(() =>
  (pending.value.view?.legal_actions ?? []).filter((a) => a.t === "response"),
);
const bidKinds = computed(() => [...new Set(legalBids.value.map((a) => a.kind))]);
const bidCountRange = computed(() => {
  const counts = legalBids.value.filter((a) => a.kind === bidKind.value).map((a) => a.count);
  return counts.length ? [Math.min(...counts), Math.max(...counts)] : null;
});

function seatName(seat: number | string): string {
  return `${seat}号`;
}

function push(item: ChatItem) {
  chatItems.value.push(item);
  if (chatItems.value.length > 300) chatItems.value.splice(0, chatItems.value.length - 300);
  if (autoScroll.value && chatEl.value) {
    requestAnimationFrame(() => chatEl.value?.scrollTo(0, chatEl.value.scrollHeight));
  }
}

async function refreshPending() {
  if (!isPve.value || status.value !== "RUNNING") return;
  pending.value = await fetchPending(props.matchId);
  if (pending.value.waiting && pending.value.view) {
    const bids = pending.value.view.legal_actions.filter((a) => a.t === "bid");
    if (bids.length) {
      bidKind.value = String(bids[0].kind);
      bidCount.value = Number(bids[0].count);
      bidFace.value = Number(bids[0].face);
    }
  }
}

function composeAction(): Record<string, unknown> | null {
  const legal = pending.value.view?.legal_actions ?? [];
  if (legal.some((a) => a.t === "response")) {
    const kind = legalResponses.value.find((a) => a.kind === selectedResponse.value);
    return kind ? { t: "response", kind: kind.kind } : null;
  }
  if (legal.some((a) => a.t === "challenge") && !legal.some((a) => a.t === "bid")) {
    const hit = legalChallenges.value.find(
      (a) =>
        a.kind === selectedChallenge.value.kind &&
        JSON.stringify(a.targets) === JSON.stringify(selectedChallenge.value.targets),
    );
    return hit ? { t: "challenge", kind: hit.kind, targets: hit.targets } : null;
  }
  if (legalBids.value.length) {
    const hit = legalBids.value.find(
      (a) => a.kind === bidKind.value && a.count === bidCount.value && a.face === bidFace.value,
    );
    return hit ? { t: "bid", kind: hit.kind, count: hit.count, face: hit.face } : null;
  }
  return null;
}

async function submit() {
  submitError.value = "";
  const action = composeAction();
  if (!action) {
    submitError.value = "所选组合不在合法动作集中";
    return;
  }
  try {
    await submitAction(props.matchId, action, quote.value);
    quote.value = "";
    pending.value = { waiting: false };
  } catch (e) {
    submitError.value = String(e);
  }
}

async function abandon() {
  if (!confirmAbandon.value) {
    confirmAbandon.value = true;
    return;
  }
  const s = await matchState(props.matchId, "abandon");
  status.value = s.status;
  fetchSummaryThenEnd();
}

async function fetchSummaryThenEnd() {
  const s = await matchState(props.matchId);
  emit("ended", s as never);
}

function handleEnvelope(e: Envelope) {
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
    case "RoundSettled":
      scores.value = (p.scores as number[]).map(Number);
      push({
        kind: "system",
        seq: e.seq,
        emphasis: "settle",
        text: `第 ${p.round_no} 局结算：${(p.entries as { seat: number; codes: number }[]).map((x) => `${x.seat}号 ${x.codes} 码`).join("；") || "无输家"}`,
      });
      break;
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
    case "ActionRequired":
      if (isPve.value) {
        pending.value = { waiting: true, view: p.view as never };
        refreshPending();
      }
      break;
    default:
      break;
  }
}

let conn: { close: () => void } | null = null;
let pollTimer: number | null = null;

conn = connectStream(
  props.matchId,
  isPve.value ? "player" : "spectator",
  (e: Envelope) => {
    handleEnvelope(e);
    if (e.type === "MatchEnded") fetchSummaryThenEnd();
  },
  () => {},
  { getLastSeq: () => lastSeq.value, seat: 0 },
);

pollTimer = window.setInterval(() => {
  refreshPending();
  fetch(`/matches/${props.matchId}`)
    .then((r) => r.json())
    .then((s: { status: string; round_no: number }) => {
      status.value = s.status;
      roundNo.value = s.round_no;
    })
    .catch(() => {});
}, 1500);

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
    <button v-if="isPve" style="color: var(--danger)" @click="abandon">
      {{ confirmAbandon ? "确认退出（弃局，不可恢复）？" : "退出并结束本桌" }}
    </button>
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
          <span>{{ seatName(String(i)) }}</span><span>{{ s }}</span>
        </div>
      </div>
      <h2>骰盅区（{{ isPve ? "PVE · 仅本人，点击开看" : "EVE 实时 · 围骰标注来自引擎" }}）</h2>
      <div class="dice-row">
        <template v-if="!isPve">
          <div v-for="card in diceCards" :key="card.seat" class="dice-card" :class="{ leopard: card.flag }">
            <div class="who">{{ card.name }}</div>
            <div class="dice">{{ card.dice.join(" ") }}</div>
            <div v-if="card.flag" class="flag">{{ card.flag }}！</div>
          </div>
        </template>
        <div v-else class="dice-card" style="cursor: pointer" @click="myHandRevealed = !myHandRevealed">
          <div class="who">我的骰盅（{{ myHandRevealed ? "已翻开" : "扣置 · 点击开看" }}）</div>
          <div class="dice">{{ myHandRevealed ? (pending.view?.my_hand ?? []).join(" ") : "？ ？ ？ ？ ？" }}</div>
        </div>
      </div>
    </div>
  </div>

  <div v-if="isPve && pending.waiting && pending.view" class="panel">
    <h2>
      动作面板 · 轮到你（{{ seatName(String(pending.view.seat)) }} · 第 {{ pending.view.round_no }} 局 ·
      {{ pending.view.phase === "bidding" ? "叫骰轮" : "应牌链" }}）
      <span v-if="pending.view.correction_reason" style="color: var(--danger); font-size: 13px">
        ⚠ {{ pending.view.correction_reason }}
      </span>
    </h2>

    <div v-if="pending.view.phase === 'respond'" class="row">
      <button
        v-for="r in legalResponses"
        :key="r.kind"
        :class="{ primary: selectedResponse === r.kind }"
        @click="selectedResponse = r.kind"
      >
        {{ r.kind === "reveal" ? "开盅清点" : r.kind === "counter" ? "反杀" : r.kind === "recounter" ? "再反杀" : "投降" }}
      </button>
    </div>

    <div v-else-if="legalBids.length" class="row" style="flex-wrap: wrap">
      <label>叫法</label>
      <select v-model="bidKind">
        <option v-for="k in bidKinds" :key="k" :value="k">
          {{ k === "normal" ? "普通叫骰" : k === "zhai" ? "转斋" : "飞斋" }}
        </option>
      </select>
      <label>数量</label>
      <input
        v-model.number="bidCount"
        type="number"
        :min="bidCountRange?.[0]"
        :max="bidCountRange?.[1]"
        style="width: 80px"
      />
      <label>点数</label>
      <button
        v-for="f in [1, 2, 3, 4, 5, 6]"
        :key="f"
        :class="{ primary: bidFace === f }"
        style="padding: 6px 10px"
        @click="bidFace = f"
      >
        {{ f }}
      </button>
    </div>
    <div v-else-if="legalChallenges.length" class="row" style="flex-wrap: wrap">
      <label>叫满上限，必须发起挑战：</label>
      <button
        v-for="c in legalChallenges"
        :key="JSON.stringify(c)"
        :class="{
          primary:
            selectedChallenge.kind === c.kind &&
            JSON.stringify(selectedChallenge.targets) === JSON.stringify(c.targets),
        }"
        @click="selectedChallenge = { kind: c.kind, targets: c.targets as number[] }"
      >
        {{ c.kind === "open" ? "开杀" : c.kind === "jump" ? "跳杀" : c.kind === "multi" ? "连杀" : "通杀" }} →
        {{ (c.targets as number[]).join("、") }}
      </button>
    </div>

    <div class="row" style="margin-top: 8px">
      <input v-model="quote" placeholder="台词（可选，发给全桌）" style="flex: 1" />
      <button class="primary" @click="submit">出牌</button>
    </div>
    <div v-if="submitError" style="color: var(--danger); font-size: 13px">{{ submitError }}</div>
    <div style="color: var(--muted); font-size: 12px; margin-top: 6px">
      合法动作集由引擎下发（02 §3.1 唯一权威）；面板只做 UI 组装，合法性由引擎终审（F-09）。
    </div>
  </div>

  <div v-else-if="isPve && status === 'RUNNING'" class="panel" style="color: var(--muted)">
    等待其他玩家决策中……
  </div>
</template>
