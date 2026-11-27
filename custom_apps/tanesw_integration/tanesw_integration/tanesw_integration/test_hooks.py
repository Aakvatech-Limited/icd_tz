import unittest

from tanesw_integration import hooks

JOBS = (
	"tanesw_integration.allocations.enqueue_allocation_watch",
	"tanesw_integration.containers.enqueue_container_sync",
	"tanesw_integration.icd_link.enqueue_icd_link",
	"tanesw_integration.icd_link.purge_old_links",
	"tanesw_integration.manifest_sync.enqueue_manifest_sync",
	"tanesw_integration.reception_dates.enqueue_reception_date_check",
)


class TestSchedule(unittest.TestCase):
	def test_every_background_job_is_scheduled(self):
		ev = hooks.scheduler_events
		listed = [m for k, v in ev.items() if k != "cron" for m in v]
		listed += [m for v in ev.get("cron", {}).values() for m in v]
		for job in JOBS:
			self.assertIn(job, listed, job + " is not on the schedule")

	def test_no_schedule_key_is_written_twice(self):
		src = open(hooks.__file__).read()
		block = src[src.index("scheduler_events = {") :]
		block = block[: block.index("\n}\n")]
		keys = [l.strip().split(":")[0] for l in block.splitlines() if l.strip().startswith('"*/')]
		self.assertEqual(len(keys), len(set(keys)), keys)
