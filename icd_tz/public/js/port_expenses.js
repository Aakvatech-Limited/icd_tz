frappe.provide("icd_tz");

icd_tz.open_port_expenses = (manifest) => {
  window.open(
    `/port-expenses/manifest/${encodeURIComponent(manifest)}`,
    "_blank"
  );
};
