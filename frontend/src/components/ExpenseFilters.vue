<template>
  <div
    class="grid grid-cols-1 gap-4 border-b border-gray-200 bg-gray-50 p-4 md:grid-cols-10"
  >
    <div class="md:col-span-2">
      <label class="mb-1 block text-xs uppercase tracking-wide text-gray-600"
        >Manifest</label
      >
      <Autocomplete
        :options="manifestOptions"
        :modelValue="manifest"
        placeholder="Select a manifest"
        @update:modelValue="(option) => $emit('update:manifest', option?.value)"
      />
    </div>

    <div class="md:col-span-2">
      <label class="mb-1 block text-xs uppercase tracking-wide text-gray-600"
        >Price List</label
      >
      <Autocomplete
        :options="priceListOptions"
        :modelValue="buyingPriceList"
        placeholder="Select a price list"
        @update:modelValue="
          (option) => $emit('update:buyingPriceList', option?.value)
        "
      />
    </div>

    <div class="md:col-span-2">
      <label class="mb-1 block text-xs uppercase tracking-wide text-gray-600"
        >Supplier</label
      >
      <Autocomplete
        :options="supplierOptions"
        :modelValue="supplier"
        placeholder="Select a supplier"
        @update:modelValue="(option) => $emit('update:supplier', option?.value)"
      />
    </div>

    <!-- read-only context: the port and vessel come from the manifest, the currency from the price list -->
    <div class="flex items-end md:col-span-4">
      <div
        class="grid w-full grid-cols-[minmax(0,1fr)_minmax(0,2fr)_minmax(0,1fr)] divide-x divide-gray-200 rounded border border-gray-300 bg-white"
      >
        <div class="px-3 py-1">
          <div class="text-[10px] uppercase tracking-wide text-gray-500">
            Port
          </div>
          <div class="truncate text-sm font-semibold">{{ port || "—" }}</div>
        </div>
        <div class="px-3 py-1">
          <div class="text-[10px] uppercase tracking-wide text-gray-500">
            Vessel
          </div>
          <div class="truncate text-sm font-semibold">
            {{ vesselName || "—" }}
          </div>
        </div>
        <div class="px-3 py-1">
          <div class="text-[10px] uppercase tracking-wide text-gray-500">
            Currency
          </div>
          <div class="truncate text-sm font-semibold">
            {{ currency || "—" }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { createListResource } from "frappe-ui";
import { computed } from "vue";

defineProps({
  manifest: String,
  buyingPriceList: String,
  supplier: String,
  port: String,
  vesselName: String,
  currency: String,
});

defineEmits(["update:manifest", "update:buyingPriceList", "update:supplier"]);

const manifests = createListResource({
  doctype: "Manifest",
  fields: ["name", "vessel_name"],
  filters: { docstatus: 1 },
  orderBy: "creation desc",
  pageLength: 100,
  auto: true,
});

const priceLists = createListResource({
  doctype: "Price List",
  fields: ["name"],
  filters: { buying: 1, enabled: 1 },
  pageLength: 100,
  auto: true,
});

const suppliers = createListResource({
  doctype: "Supplier",
  fields: ["name"],
  orderBy: "name asc",
  pageLength: 100,
  auto: true,
});

const manifestOptions = computed(() =>
  (manifests.data || []).map((row) => ({ label: row.name, value: row.name }))
);

const priceListOptions = computed(() =>
  (priceLists.data || []).map((row) => ({ label: row.name, value: row.name }))
);

const supplierOptions = computed(() =>
  (suppliers.data || []).map((row) => ({ label: row.name, value: row.name }))
);
</script>
