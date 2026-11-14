<script setup lang="ts">
import { reactive, ref } from "vue";
import { createMatch } from "../api";
import type { SlotSpec } from "../types";

const emit = defineEmits<{ started: [summary: never, spec: object]; open: [summary: never] }>();

const mode = ref<"eve" | "pve">("eve");
const endThreshold = ref(40);
const maxRounds = ref(300);

type SlotUI = {
  kind: "bot" | "llm" | "human";
  name: string;
  provider: string;
  model: string;
  api_key_ref: string;
  base_url: string;
  persona_name: string;
  persona_style: string;
  trash_talk: number;
  thinking: string;
};

function emptySlot(i: number): SlotUI {
  return {
    kind: i === 0 ? "bot" : "bot",
    name: `bot${i}`,
    provider: "glm",
    model: "glm-5.3-flash",
    api_key_ref: "env:GLM_API_KEY",
    base_url: "",
    persona_name: `玩家${i + 1}`,
    persona_style: "",
    trash_talk: 1,
    thinking: "auto",
  };
}

const slots = reactive<SlotUI[]>([emptySlot(0), emptySlot(1), emptySlot(2), emptySlot(3)]);

function setCount(n: number) {
  while (slots.length < n) slots.push(emptySlot(slots.length));
  while (slots.length > n) slots.pop();
}

function onModeChange() {
  if (mode.value === "pve") {
    slots[0].kind = "human";
    slots[0].name = "人类";
  } else if (slots[0].kind === "human") {
    slots[0].kind = "bot";
    slots[0].name = "bot0";
  }
}

const error = ref("");
const busy = ref(false);
const matches = ref<{ match_id: string; mode: string; status: string; round_no: number }[]>([]);

const matchGroups = computed(() => {
  const running = matches.value.filter((m) => m.status === "RUNNING");
  const suspended = matches.value.filter((m) => m.status === "SUSPENDED");
  const done = matches.value.filter((m) => m.status === "ENDED" || m.status === "ABANDONED");
  return [
    { label: "进行中", items: running },
    { label: "挂起", items: suspended },
    { label: "已结束 / 已弃局", items: done },
  ];
});

async function abandonMatch(id: string) {
  const { matchState } = await import("../api");
  await matchState(id, "abandon");
  await refresh();
}

async function refresh() {
  const { listMatches } = await import("../api");
  matches.value = await listMatches();
}
refresh();
setInterval(refresh, 3000);

async function submit() {
  busy.value = true;
  error.value = "";
  try {
    const specs: SlotSpec[] = slots.slice(0, slotCount.value).map((s, i) => {
      if (s.kind === "bot") return { kind: "bot", name: s.name || `bot${i}` };
      if (s.kind === "human") return { kind: "human", name: s.name || "人类" };
      return {
        kind: "llm",
        provider: s.provider,
        model: s.model,
        api_key_ref: s.api_key_ref,
        base_url: s.base_url || undefined,
        persona_name: s.persona_name,
        persona_style: s.persona_style,
        trash_talk: s.trash_talk,
        thinking: s.thinking,
      };
    });
    const spec = {
      mode: mode.value,
      slots: specs,
      config: { end_threshold: endThreshold.value, max_rounds: maxRounds.value },
    };
    const summary = await createMatch(spec);
    emit("started", summary as never, spec);
  } catch (e) {
    error.value = String(e);
  } finally {
    busy.value = false;
  }
}

const slotCount = ref(4);
</script>

<template>
  <div class="panel">
    <h2>开桌向导（W1）</h2>
    <div class="row">
      <label>模式</label>
      <select v-model="mode" @change="onModeChange">
        <option value="eve">EVE（纯 LLM，进入观战）</option>
        <option value="pve">PVE（1 人类席 + N−1 LLM/bot）</option>
      </select>
      <label>人数</label>
      <select v-model.number="slotCount" @change="setCount(slotCount)">
        <option v-for="n in [2, 3, 4, 5, 6]" :key="n" :value="n">{{ n }}</option>
      </select>
      <label>终局阈值</label>
      <input v-model.number="endThreshold" type="number" min="1" style="width: 90px" />
      <label>局数保险丝</label>
      <input v-model.number="maxRounds" type="number" min="1" style="width: 90px" />
    </div>

    <h2>玩家槽位（W1：bot 席可离线观战；LLM 席需 API Key 环境变量）</h2>
    <div v-for="(s, i) in slots.slice(0, slotCount)" :key="i" class="panel" style="margin-bottom: 8px">
      <div class="row">
        <label>类型</label>
        <select v-model="s.kind" :disabled="i === 0 && mode === 'pve'">
          <option value="bot">bot（离线）</option>
          <option value="llm">LLM</option>
          <option v-if="i === 0 && mode === 'pve'" value="human">人类</option>
        </select>
        <label>署名</label>
        <input v-model="s.name" style="width: 110px" />
        <template v-if="s.kind === 'llm'">
          <label>服务商</label>
          <select v-model="s.provider">
            <option value="deepseek">DeepSeek</option>
            <option value="glm">GLM</option>
          </select>
          <label>型号</label>
          <input v-model="s.model" style="width: 170px" />
          <label>Key 引用</label>
          <input v-model="s.api_key_ref" style="width: 180px" />
        </template>
      </div>
      <div v-if="s.kind === 'llm'" class="row">
        <label>自托管/网关 base_url（可选）</label>
        <input v-model="s.base_url" placeholder="留空 = 官方端点" style="width: 320px" />
        <label>人格名</label>
        <input v-model="s.persona_name" style="width: 110px" />
        <label>风格</label>
        <input v-model="s.persona_style" style="width: 200px" />
        <label>思考档</label>
        <select v-model="s.thinking">
          <option value="auto">auto</option>
          <option value="off">off</option>
          <option value="low">low</option>
          <option value="mid">mid</option>
          <option value="high">high</option>
        </select>
      </div>
    </div>

    <div class="row">
      <button class="primary" :disabled="busy" @click="submit">冻结配置并开桌</button>
      <span style="color: var(--danger); font-size: 13px">{{ error }}</span>
    </div>
  </div>

  <div class="panel">
    <h2>桌局列表（进行中 / 挂起 / 已结束 · F-11）</h2>
    <div v-for="group in matchGroups" :key="group.label">
      <h3 style="margin: 6px 0 2px; font-size: 13px; color: var(--muted)">{{ group.label }}</h3>
      <div v-for="m in group.items" :key="m.match_id" class="row" style="padding: 3px 0">
        <span style="font-size: 13px">{{ m.match_id }}</span>
        <span class="spacer" />
        <span style="font-size: 12px; color: var(--muted)">{{ m.mode }} · {{ m.status }} · {{ m.round_no }} 局</span>
        <button v-if="m.status === 'RUNNING' || m.status === 'SUSPENDED'" @click="emit('open', m as never)">
          进入
        </button>
        <button
          v-if="m.status === 'RUNNING' || m.status === 'SUSPENDED'"
          style="color: var(--danger)"
          @click="abandonMatch(m.match_id)"
        >
          弃局
        </button>
      </div>
      <div v-if="!group.items.length" style="color: var(--muted); font-size: 12px">（无）</div>
    </div>
  </div>
</template>
