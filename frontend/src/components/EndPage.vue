<script setup lang="ts">
import type { MatchSummary } from "../types";

const props = defineProps<{ summary: MatchSummary }>();
const emit = defineEmits<{ rematch: [] }>();

const ranked = [...props.summary.scores]
  .map((score, seat) => ({ seat, score }))
  .sort((a, b) => a.score - b.score);
const minScore = Math.min(...props.summary.scores);
</script>

<template>
  <div class="panel">
    <h1>桌局结束</h1>
    <p style="color: var(--muted)">{{ summary.match_id }} · {{ summary.mode.toUpperCase() }}</p>
    <h2>终局积分榜（分数最小者胜）</h2>
    <div class="scoreboard">
      <div v-for="r in ranked" :key="r.seat" :style="r.score === minScore ? 'color: var(--ok); font-weight: 600' : ''">
        <span>{{ r.seat }}号{{ r.score === minScore ? " 🏆" : "" }}</span><span>{{ r.score }}</span>
      </div>
    </div>
    <div class="row" style="margin-top: 16px">
      <button class="primary" @click="emit('rematch')">再来一桌（同配置 · 新种子）</button>
      <span style="color: var(--muted); font-size: 13px">
        复盘档与 AI 赛后评述入口（预留 · 属 05 / N4-05）：archives/{{ summary.match_id }}/
      </span>
    </div>
  </div>
</template>
