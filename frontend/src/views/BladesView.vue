<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import api from '../api'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const cards = ref([])
const lofts = ref([])
const error = ref('')
const busy = ref(false)
const stateFilter = ref('active')

const form = reactive({
  loftId: null,
  bladeBatch: '',
  remainingUses: 10,
})

const isAdmin = computed(() => auth.user?.role === 'admin')

const stateTabs = [
  { key: 'active', label: '现行' },
  { key: 'voided', label: '已作废' },
  { key: 'all', label: '全部' },
]

async function load() {
  error.value = ''
  try {
    const params = stateFilter.value === 'all' ? {} : { state: stateFilter.value }
    const [c, l] = await Promise.all([
      api.get('/bladecards/', { params }),
      api.get('/lofts/'),
    ])
    cards.value = c.data.results || c.data
    lofts.value = l.data.results || l.data
    if (!form.loftId && lofts.value.length) form.loftId = lofts.value[0].id
  } catch {
    error.value = '刀片寿命卡加载失败'
  }
}

function switchState(key) {
  stateFilter.value = key
  load()
}

async function create() {
  error.value = ''
  busy.value = true
  try {
    await api.post('/bladecards/', {
      loftId: form.loftId,
      bladeBatch: form.bladeBatch,
      remainingUses: form.remainingUses,
    })
    form.bladeBatch = ''
    await load()
  } catch (e) {
    const data = e.response?.data
    error.value =
      data?.detail ||
      data?.loftId?.[0] ||
      data?.bladeBatch?.[0] ||
      data?.remainingUses?.[0] ||
      '建卡失败'
  } finally {
    busy.value = false
  }
}

async function voidCard(card) {
  error.value = ''
  busy.value = true
  try {
    await api.post(`/bladecards/${card.id}/void/`)
    await load()
  } catch (e) {
    error.value = e.response?.data?.detail || '作废失败（仅管理员可作废）'
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <h1>刮胶刀片寿命卡</h1>
    <p class="sub">每登记一笔浸渍消耗 1 个刀次；剩余刀次为 0 时挡住登记。同一帆布间现行卡最多一张，作废仅管理员。</p>
    <p v-if="error" class="error">{{ error }}</p>

    <form class="panel row" @submit.prevent="create">
      <label>帆布间
        <select v-model.number="form.loftId" required>
          <option v-for="l in lofts" :key="l.id" :value="l.id">{{ l.name }}</option>
        </select>
      </label>
      <label>刀片批号
        <input v-model.trim="form.bladeBatch" required placeholder="如 BL-2026-001" />
      </label>
      <label>剩余刀次
        <input v-model.number="form.remainingUses" type="number" min="0" step="1" required />
      </label>
      <button class="btn" type="submit" :disabled="busy">建卡</button>
    </form>

    <div class="panel">
      <div class="tab-row">
        <button
          v-for="t in stateTabs"
          :key="t.key"
          class="btn"
          :class="{ secondary: stateFilter !== t.key }"
          type="button"
          @click="switchState(t.key)"
        >
          {{ t.label }}
        </button>
      </div>

      <table>
        <thead>
          <tr>
            <th>帆布间</th>
            <th>刀片批号</th>
            <th>剩余刀次</th>
            <th>状态</th>
            <th>作废时刻</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in cards" :key="row.id">
            <td>{{ row.loftName }}</td>
            <td>{{ row.bladeBatch }}</td>
            <td>{{ row.remainingUses }}</td>
            <td>
              <span class="badge" :class="row.isActive ? 'badge-dipping' : 'badge-raw'">
                {{ row.isActive ? '现行' : '已作废' }}
              </span>
            </td>
            <td>{{ row.voidedAt ? new Date(row.voidedAt).toLocaleString() : '—' }}</td>
            <td>
              <button
                v-if="row.isActive && isAdmin"
                class="btn secondary"
                type="button"
                :disabled="busy"
                @click="voidCard(row)"
              >
                作废
              </button>
            </td>
          </tr>
          <tr v-if="!cards.length">
            <td colspan="6" class="hint">暂无卡片</td>
          </tr>
        </tbody>
      </table>
      <p v-if="!isAdmin" class="hint" style="margin-top: 10px">作废卡片需管理员账号。</p>
    </div>
  </div>
</template>

<style scoped>
.tab-row {
  display: flex;
  gap: 8px;
  margin-bottom: 14px;
}
</style>
