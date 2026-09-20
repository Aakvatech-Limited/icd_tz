import { createResource } from "frappe-ui";

const API = "icd_tz.icd_tz.api";
const API_DOCTYPE = "icd_tz.icd_tz.doctype";

export function createExpenseView() {
  return createResource({
    url: `${API}.port_expenses.get_expense_view`,
    auto: false,
  });
}

export function createRowContainers() {
  return createResource({
    url: `${API}.port_expenses.get_expense_row_containers`,
    auto: false,
  });
}

export function createPurchaseOrder() {
  return createResource({
    url: `${API}.purchase_order.create_purchase_order`,
    auto: false,
  });
}

export function createDischargeFetch() {
  return createResource({
    url: `${API_DOCTYPE}.icd_container.icd_container.enqueue_ship_dc_dates`,
    auto: false,
  });
}

export function formatMoney(value, currency) {
  const amount = Number(value || 0);
  if (!currency) {
    return amount.toLocaleString();
  }

  return `${currency} ${amount.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

// a row is orderable when it has containers and a rate to price them at
export function isBillable(row) {
  return Boolean(row.container_count && row.rate && row.amount);
}

export function describeCriteria(row) {
  return ["size", "cargo_type", "destination", "port"]
    .map((field) => row[field])
    .filter(Boolean)
    .join(" · ");
}
