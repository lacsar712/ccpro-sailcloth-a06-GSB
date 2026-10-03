<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import api from '../api'
import { errText } from '../errText'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const isAdmin = computed(() => auth.user?.role === 'admin' || auth.user?.is_superuser)

const cards = ref([])
const lofts = ref([])
const error = ref('')
const busy = ref(false)
const stateFilter = ref('active')

const tabs = [
  { key: 'active', label: '现行' },
  { key: 'voided', label: '已作废' },
  { key: '', label: '全部' },
]

const form = reactive({
  loftId: null,
  bladeBatchNo: '',
  remainingUses: 1,
})

async function load() {
  error.value = ''
  try {
    const params = stateFilter.value ? { state: stateFilter.value } : {}
    const [c, l] = await Promise.all([
      api.get('/bladecards/', { params }),
      api.get('/lofts/'),
    ])
    cards.value = c.data.results || c.data
    lofts.value = l.data.results || l.data
    if (!form.loftId && lofts.value.length) form.loftId = lofts.value[0].id
  } catch (e) {
    error.value = errText(e.response?.data, '刀片寿命卡加载失败')
  }
}

function setFilter(key) {
  stateFilter.value = key
  load()
}

async function createCard() {
  error.value = ''
  busy.value = true
  try {
    await api.post('/bladecards/', {
      loftId: form.loftId,
      bladeBatchNo: form.bladeBatchNo,
      remainingUses: form.remainingUses,
    })
    form.bladeBatchNo = ''
    form.remainingUses = 1
    await load()
  } catch (e) {
    error.value = errText(e.response?.data, '建卡失败')
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
    error.value = errText(e.response?.data, '作废失败')
  } finally {
    busy.value = false
  }
}

function fmt(dt) {
  return dt ? new Date(dt).toLocaleString() : '—'
}

onMounted(load)
</script>

<template>
  <div>
    <h1>刮胶刀片寿命卡</h1>
    <p class="sub">
      每登记一笔浸渍消耗 1 刀次；剩余刀次为 0 即挡住登记。同一帆布间最多一张现行卡，作废仅管理员。
    </p>
    <p v-if="error" class="error">{{ error }}</p>

    <div class="tabs">
      <button
        v-for="t in tabs"
        :key="t.key"
        type="button"
        class="tab"
        :class="{ 'tab-on': stateFilter === t.key }"
        @click="setFilter(t.key)"
      >
        {{ t.label }}
      </button>
    </div>

    <form class="panel row" @submit.prevent="createCard">
      <label>帆布间
        <select v-model.number="form.loftId" required>
          <option v-for="l in lofts" :key="l.id" :value="l.id">{{ l.name }}</option>
        </select>
      </label>
      <label>刀片批号
        <input v-model="form.bladeBatchNo" required placeholder="如 BLADE-2026-002" />
      </label>
      <label>剩余刀次
        <input v-model.number="form.remainingUses" type="number" min="0" step="1" required />
      </label>
      <button class="btn" type="submit" :disabled="busy">新建寿命卡</button>
    </form>

    <table>
      <thead>
        <tr>
          <th>帆布间</th>
          <th>刀片批号</th>
          <th>剩余刀次</th>
          <th>状态</th>
          <th>作废时刻</th>
          <th>建卡时间</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in cards" :key="row.id">
          <td>{{ row.loftName }}</td>
          <td>{{ row.bladeBatchNo }}</td>
          <td>
            <span class="badge" :class="row.isActive && row.remainingUses === 0 ? 'badge-empty' : 'badge-uses'">
              {{ row.remainingUses }}
            </span>
          </td>
          <td>
            <span class="badge" :class="row.isActive ? 'badge-active' : 'badge-voided'">
              {{ row.isActive ? '现行' : '已作废' }}
            </span>
          </td>
          <td>{{ fmt(row.voidedAt) }}</td>
          <td>{{ fmt(row.created_at) }}</td>
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
          <td colspan="7" class="hint">暂无符合条件的寿命卡</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
