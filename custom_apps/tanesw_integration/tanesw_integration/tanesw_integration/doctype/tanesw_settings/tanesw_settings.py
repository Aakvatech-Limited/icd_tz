from frappe.model.document import Document


class TANeSWSettings(Document):
	def on_update(self):
		if self.has_value_changed("best_pick_without_manifest"):
			from tanesw_integration import best_pick_setup

			best_pick_setup.apply(bool(self.best_pick_without_manifest))
		if self.has_value_changed("update_erp_manifests"):
			from tanesw_integration import manifest_sync

			manifest_sync.apply_setters(bool(self.update_erp_manifests))

	pass
