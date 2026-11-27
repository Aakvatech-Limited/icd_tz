app_name = "tanesw_integration"
app_title = "TANeSW Integration"
app_publisher = "Silver Entertrade Ltd"
app_description = "TANeSW-ERPNext integration for ICD operations"
app_email = "hisham@silverentertrade.co.tz"
app_license = "mit"

# icd_tz must be installed first: the app reads its tables and saves its documents through its controllers
required_apps = ["icd_tz"]

# TANeSW additions to icd_tz's Manifest form (a Diverted card, a warning before port expense orders)
doctype_js = {"Manifest": "public/js/manifest_tanesw.js"}

# TANeSW roles and live (not prepared) reports (install.py)
after_install = "tanesw_integration.install.after_install"
before_migrate = "tanesw_integration.install.before_migrate"
after_migrate = "tanesw_integration.install.after_migrate"
# icd_tz's form rules are put back as they were (install.before_uninstall)
before_uninstall = "tanesw_integration.install.before_uninstall"

doc_events = {
	"Container Movement Order": {
		"before_update_after_submit": "tanesw_integration.best_pick_setup.validate_manifest_change",
	},
	"Manifest": {
		# only the TANeSW manifest sync may add/remove rows of a submitted Manifest (manifest_sync.py)
		"before_update_after_submit": "tanesw_integration.manifest_sync.guard_manifest_tables",
	},
	# port charges only for boxes TANeSW still allocates to us (port_charge_check.py)
	"Purchase Order": {
		"validate": "tanesw_integration.port_charge_check.check_document",
		"before_submit": "tanesw_integration.port_charge_check.check_document",
	},
	"Purchase Invoice": {
		"validate": "tanesw_integration.port_charge_check.check_document",
		"before_submit": "tanesw_integration.port_charge_check.check_document",
	},
	# Posting Date vs the TANeSW carry-in: warn or correct before icd_tz sets the storage start (reception_dates.py)
	"Container Reception": {
		"validate": "tanesw_integration.reception_dates.on_reception_validate",
	},
}

scheduler_events = {
	"daily": ["tanesw_integration.icd_link.purge_old_links"],
	# One key per schedule: a repeated key in a dict literal silently replaces the earlier one (a job then falls
	# off the schedule). test_hooks checks every job is still listed.
	"cron": {
		"*/15 * * * *": [
			"tanesw_integration.allocations.enqueue_allocation_watch",
			# live boxes (at terminal / on the road / arrived ships); once an hour also the rest
			"tanesw_integration.containers.enqueue_container_sync",
		],
		"*/5 * * * *": ["tanesw_integration.icd_link.enqueue_icd_link"],
		# TANeSW manifest Excel vs ERP Manifest, box by box (manifest_sync.py)
		"*/30 * * * *": ["tanesw_integration.manifest_sync.enqueue_manifest_sync"],
		# Container Reception Posting Date vs TANeSW carry-in, hourly at :20 (reception_dates.py)
		"20 * * * *": ["tanesw_integration.reception_dates.enqueue_reception_date_check"],
	},
}
