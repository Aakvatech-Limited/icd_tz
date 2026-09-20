<template>
  <div class="flex flex-wrap divide-x divide-gray-200 border-b border-gray-200">
    <div class="min-w-[140px] flex-1 px-4 py-3">
      <div class="text-xl font-semibold tabular-nums">
        {{ summary.total_containers }}
      </div>
      <div class="text-xs text-gray-600">Total containers</div>
    </div>
    <div class="min-w-[140px] flex-1 px-4 py-3">
      <div class="text-xl font-semibold tabular-nums">
        {{ summary.booked_containers }}
      </div>
      <div class="text-xs text-gray-600">Already booked</div>
    </div>
    <div class="min-w-[140px] flex-1 px-4 py-3">
      <div class="text-xl font-semibold tabular-nums">
        {{ summary.billable_containers }}
      </div>
      <div class="text-xs text-gray-600">Billable now</div>
    </div>
    <div class="min-w-[180px] flex-1 px-4 py-3">
      <div class="flex items-center gap-2">
        <span
          class="text-xl font-semibold tabular-nums"
          :class="summary.missing_discharge_date ? 'text-orange-600' : ''"
        >
          {{ summary.missing_discharge_date }}
        </span>
        <Button
          v-if="summary.missing_discharge_date"
          theme="gray"
          size="sm"
          :loading="fetching"
          @click="$emit('fetch-discharge-dates')"
        >
          Fetch now
        </Button>
      </div>
      <div class="text-xs text-gray-600">Missing discharge date</div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  summary: { type: Object, default: () => ({}) },
  fetching: Boolean,
});

defineEmits(["fetch-discharge-dates"]);
</script>
