<script setup lang="ts">
import { ref } from "vue";
import WizardPage from "./components/WizardPage.vue";
import MatchPage from "./components/MatchPage.vue";
import EndPage from "./components/EndPage.vue";
import type { MatchSummary } from "./types";

type Page = "wizard" | "match" | "end";

const page = ref<Page>("wizard");
const matchId = ref("");
const mode = ref<"eve" | "pve">("eve");
const summary = ref<MatchSummary | null>(null);
const endedSummary = ref<MatchSummary | null>(null);
const lastSpec = ref<{ mode: string; slots: unknown[]; config: Record<string, unknown> } | null>(null);

// URL 直达：/?match=<id>&mode=eve|pve —— 断线恢复入口（G-02 全量重放）
const urlParams = new URLSearchParams(location.search);
const urlMatch = urlParams.get("match");
if (urlMatch) {
  page.value = "match";
  matchId.value = urlMatch;
  mode.value = (urlParams.get("mode") as "eve" | "pve") ?? "eve";
}

function onMatchStarted(s: MatchSummary, spec: { mode: string; slots: unknown[]; config: Record<string, unknown> }) {
  matchId.value = s.match_id;
  mode.value = spec.mode as "eve" | "pve";
  summary.value = s;
  lastSpec.value = spec;
  page.value = "match";
}

function onOpenMatch(s: MatchSummary) {
  matchId.value = s.match_id;
  mode.value = s.mode as "eve" | "pve";
  summary.value = s;
  page.value = "match";
}

function onEnded(s: MatchSummary) {
  endedSummary.value = s;
  page.value = "end";
}

async function rematch() {
  if (!lastSpec.value) return;
  const { createMatch } = await import("./api");
  const s = await createMatch(lastSpec.value as never);
  onMatchStarted(s, lastSpec.value);
}
</script>

<template>
  <header class="row">
    <h1>大话骰 · LLM 桌局</h1>
    <div class="spacer" />
    <span v-if="summary" style="color: var(--muted); font-size: 13px">{{ summary.match_id }}</span>
  </header>
  <WizardPage v-if="page === 'wizard'" @started="onMatchStarted" @open="onOpenMatch" />
  <MatchPage
    v-else-if="page === 'match' && matchId"
    :match-id="matchId"
    :mode="mode"
    @ended="onEnded"
  />
  <EndPage v-else-if="page === 'end' && endedSummary" :summary="endedSummary" @rematch="rematch" />
  <footer style="color: var(--muted); font-size: 12px; margin-top: 16px">
    localhost 单机宿主 · 无鉴权（F-01） · 前端零规则逻辑（F-09）：一切规则口径来自引擎事件载荷
  </footer>
</template>
