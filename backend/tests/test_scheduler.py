import unittest
from datetime import timedelta

from app.core.scheduler import BULLETIN_JOB_ID, build_scheduler, reschedule_bulletin_job


class SchedulerTests(unittest.TestCase):
    """
    Covers only job registration/rescheduling — the interval is always hours
    (minimum 1h), so briefly starting the scheduler to make `get_job()`
    queryable (APScheduler only moves a job out of its pending-jobs queue
    once started) never lets `run_scheduled_scrape` actually fire within a
    test's lifetime; no real network/DB activity happens. The actual
    scrape/save logic is already covered by
    `test_bulletin_parser.py::ScrapeAndSaveAllTests`; `run_scheduled_scrape()`
    is a thin asyncio.run(...) + try/except wrapper around it.
    """

    def test_build_scheduler_registers_job_with_correct_interval(self):
        scheduler = build_scheduler(5)
        scheduler.start()
        try:
            job = scheduler.get_job(BULLETIN_JOB_ID)
            self.assertIsNotNone(job)
            self.assertEqual(job.trigger.interval, timedelta(hours=5))
        finally:
            scheduler.shutdown(wait=False)

    def test_reschedule_bulletin_job_updates_interval(self):
        scheduler = build_scheduler(5)
        scheduler.start()
        try:
            reschedule_bulletin_job(scheduler, 10)
            job = scheduler.get_job(BULLETIN_JOB_ID)
            self.assertEqual(job.trigger.interval, timedelta(hours=10))
        finally:
            scheduler.shutdown(wait=False)


if __name__ == "__main__":
    unittest.main()
