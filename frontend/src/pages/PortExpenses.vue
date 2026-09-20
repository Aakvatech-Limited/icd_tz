<template>
  <div class="mx-auto max-w-7xl p-4">
    <div
      class="overflow-hidden rounded-lg border border-gray-300 bg-white shadow-sm"
    >
      <div
        class="flex items-center justify-between gap-4 border-b border-gray-200 px-4 py-3"
      >
        <h1 class="text-base font-semibold">Port Expenses</h1>
        <div class="flex gap-2">
          <Button theme="gray" :loading="view.loading" @click="reload"
            >Refresh</Button
          >
          <Button
            variant="solid"
            :disabled="!canCreate"
            :loading="purchaseOrder.loading"
            @click="createOrder"
          >
            Create Purchase Order
          </Button>
        </div>
      </div>

      <ExpenseFilters
        :manifest="manifest"
        :buyingPriceList="buyingPriceList"
        :supplier="supplier"
        :port="view.data?.port"
        :vesselName="view.data?.vessel_name"
        :currency="view.data?.currency"
        @update:manifest="onManifestChange"
        @update:buyingPriceList="onPriceListChange"
        @update:supplier="(value) => (supplier = value)"
      />

      <ExpenseSummary
        v-if="view.data"
        :summary="view.data.summary"
        :fetching="dischargeFetch.loading"
        @fetch-discharge-dates="fetchDischargeDates"
      />

      <div
        v-if="errorMessage"
        class="border-b border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
      >
        {{ errorMessage }}
      </div>

      <div v-if="!manifest" class="px-4 py-12 text-center text-gray-500">
        Select a manifest to see what is owed at the port
      </div>

      <ExpenseTable
        v-else
        :rows="view.data?.rows || []"
        :currency="view.data?.currency"
        :openRow="openRow"
        :containers="rowContainers.data || []"
        :loadingContainers="rowContainers.loading"
        @open="toggleOpenRow"
      />
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import ExpenseFilters from "@/components/ExpenseFilters.vue";
import ExpenseSummary from "@/components/ExpenseSummary.vue";
import ExpenseTable from "@/components/ExpenseTable.vue";
import {
  createDischargeFetch,
  createExpenseView,
  createPurchaseOrder,
  createRowContainers,
  isBillable,
} from "@/data/portExpenses";

const route = useRoute();

const manifest = ref(route.params.manifest || "");
const buyingPriceList = ref("");
const supplier = ref("");
const openRow = ref("");
const errorMessage = ref("");

const view = createExpenseView();
const rowContainers = createRowContainers();
const purchaseOrder = createPurchaseOrder();
const dischargeFetch = createDischargeFetch();

// every billable row is ordered, so there is nothing for the user to tick
const billableRows = computed(() => (view.data?.rows || []).filter(isBillable));

const canCreate = computed(() =>
  Boolean(manifest.value && supplier.value && billableRows.value.length)
);

onMounted(() => {
  if (manifest.value) {
    reload();
  }
});

function reload() {
  if (!manifest.value) {
    return;
  }

  errorMessage.value = "";
  openRow.value = "";
  rowContainers.reset();

  view.submit(
    {
      manifest: manifest.value,
      buying_price_list: buyingPriceList.value || undefined,
    },
    {
      onSuccess: (data) => {
        buyingPriceList.value = data.buying_price_list;
      },
      onError: (error) => {
        errorMessage.value = readError(error);
      },
    }
  );
}

function onManifestChange(value) {
  manifest.value = value;
  reload();
}

function onPriceListChange(value) {
  buyingPriceList.value = value;
  reload();
}

function toggleOpenRow(row) {
  // one row open at a time, so a long manifest stays readable
  if (openRow.value === row.row_key) {
    openRow.value = "";
    return;
  }

  openRow.value = row.row_key;
  rowContainers.submit({
    manifest: manifest.value,
    criteria_row: row.criteria_row,
    display_qty: row.display_qty,
    buying_price_list: buyingPriceList.value || undefined,
  });
}

function createOrder() {
  errorMessage.value = "";

  purchaseOrder.submit(
    {
      manifest: manifest.value,
      buying_price_list: buyingPriceList.value,
      supplier: supplier.value,
      criteria_rows: JSON.stringify(
        billableRows.value.map((row) => row.criteria_row)
      ),
    },
    {
      onSuccess: (name) => {
        window.location.href = `/app/purchase-order/${encodeURIComponent(
          name
        )}`;
      },
      onError: (error) => {
        errorMessage.value = readError(error);
      },
    }
  );
}

function fetchDischargeDates() {
  dischargeFetch.submit(
    { manifest: manifest.value },
    { onError: (error) => (errorMessage.value = readError(error)) }
  );
}

function readError(error) {
  return error?.messages?.join(" ") || error?.message || "Something went wrong";
}
</script>
