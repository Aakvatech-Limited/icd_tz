<template>
  <div class="overflow-x-auto">
    <table class="w-full min-w-[820px] table-fixed text-sm">
      <thead>
        <tr
          class="border-b border-gray-300 text-[10px] uppercase tracking-wide text-gray-600"
        >
          <th class="w-12 px-3 py-2 text-right">#</th>
          <th class="w-[30%] px-3 py-2 text-left">Charge</th>
          <th class="w-[20%] px-3 py-2 text-left">Criteria</th>
          <th class="px-3 py-2 text-right">Qty / Days</th>
          <th class="px-3 py-2 text-right">Cont.</th>
          <th class="px-3 py-2 text-right">Rate</th>
          <th class="w-[16%] px-3 py-2 text-right">Amount</th>
        </tr>
      </thead>

      <tbody>
        <template v-for="(row, index) in rows" :key="row.row_key">
          <tr
            class="border-b border-gray-200"
            :class="[
              isBillable(row) ? '' : 'bg-gray-50',
              isOpen(row) ? 'bg-blue-50' : '',
            ]"
          >
            <td class="px-3 py-2 text-right text-xs tabular-nums text-gray-400">
              {{ index + 1 }}
            </td>

            <td class="cursor-pointer px-3 py-2" @click="$emit('open', row)">
              <!-- the charge keeps full contrast even on a row that cannot be ordered -->
              <div class="text-[13px] font-semibold leading-snug text-gray-900">
                <span v-if="isOpen(row)" class="text-blue-600">▾ </span
                >{{ row.item_code }}
              </div>
            </td>

            <td class="px-3 py-2 text-gray-600">
              {{ describeCriteria(row) || "any" }}
            </td>
            <td
              class="px-3 py-2 text-right tabular-nums"
              :class="mutedCell(row)"
            >
              {{ row.display_qty }}
            </td>
            <td
              class="px-3 py-2 text-right tabular-nums"
              :class="mutedCell(row)"
            >
              {{ row.container_count }}
            </td>
            <td
              class="px-3 py-2 text-right tabular-nums"
              :class="mutedCell(row)"
            >
              {{ row.rate }}
            </td>

            <td class="px-3 py-2 text-right">
              <div class="tabular-nums" :class="mutedCell(row)">
                {{ formatMoney(row.amount, currency) }}
              </div>
              <Badge v-if="!row.container_count" theme="gray" class="mt-1"
                >No containers</Badge
              >
              <Badge v-else-if="!row.rate" theme="red" class="mt-1"
                >No rate</Badge
              >
            </td>
          </tr>

          <tr
            v-if="isOpen(row)"
            :key="`${row.row_key}-containers`"
            class="border-b border-gray-200 bg-blue-50"
          >
            <td colspan="7" class="px-4 py-3">
              <div
                class="mb-2 flex items-center justify-between text-xs font-semibold"
              >
                <span>
                  {{ row.item_code }} — {{ row.container_count }} containers,
                  {{ row.qty }} billable
                </span>
                <button class="text-blue-600" @click="$emit('open', row)">
                  collapse ▴
                </button>
              </div>
              <div v-if="loadingContainers" class="text-xs text-gray-500">
                Loading containers…
              </div>
              <div
                v-else
                class="flex flex-wrap gap-x-4 gap-y-1 font-mono text-xs text-gray-700"
              >
                <span
                  v-for="container in containers"
                  :key="container.container_no"
                >
                  {{ container.container_no }}
                  <span class="text-gray-500">({{ container.qty }})</span>
                </span>
                <span v-if="!containers.length" class="text-gray-500">
                  No containers for this charge
                </span>
              </div>
            </td>
          </tr>
        </template>

        <tr v-if="!rows.length">
          <td colspan="7" class="px-4 py-8 text-center text-gray-500">
            No expense criteria configured for this port
          </td>
        </tr>

        <tr v-else class="border-t-2 border-gray-900 font-semibold">
          <td colspan="6" class="px-3 py-3">
            Total · {{ billableRows.length }} charges to order
          </td>
          <td class="px-3 py-3 text-right tabular-nums">
            {{ formatMoney(total, currency) }}
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { computed } from "vue";

import { describeCriteria, formatMoney, isBillable } from "@/data/portExpenses";

const props = defineProps({
  rows: { type: Array, default: () => [] },
  currency: String,
  openRow: String,
  containers: { type: Array, default: () => [] },
  loadingContainers: Boolean,
});

defineEmits(["open"]);

const isOpen = (row) => props.openRow === row.row_key;

// only the figures fade on a row that cannot be ordered, never the charge name
const mutedCell = (row) => (isBillable(row) ? "" : "text-gray-400");

// every billable row goes on the order, there is nothing to tick
const billableRows = computed(() => props.rows.filter(isBillable));

const total = computed(() =>
  billableRows.value.reduce((sum, row) => sum + Number(row.amount || 0), 0)
);
</script>
