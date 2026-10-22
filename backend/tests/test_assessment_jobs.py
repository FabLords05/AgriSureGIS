import unittest

from app.core import assessment_jobs
from app.core.assessment_jobs import JobProgress, start_job


class AssessmentJobTests(unittest.TestCase):
    def setUp(self):
        assessment_jobs._jobs.clear()

    def _statuses(self, job_id):
        return [s["status"] for s in assessment_jobs.get_job(job_id)["stages"]]

    def test_stages_run_one_at_a_time_in_order(self):
        job, _ = start_job(1, 10, "manual")
        progress = JobProgress(job.job_id)

        progress.stage("data_preparation")
        self.assertEqual(self._statuses(job.job_id), ["processing", "pending", "pending", "pending", "pending"])

        progress.stage("spatial_analysis", total=4)
        # Starting a stage completes every earlier one; only one is processing.
        self.assertEqual(self._statuses(job.job_id), ["completed", "completed", "processing", "pending", "pending"])
        self.assertEqual(self._statuses(job.job_id).count("processing"), 1)

    def test_percent_follows_real_counts_and_never_hits_100_before_done(self):
        job, _ = start_job(1, 10, "manual")
        progress = JobProgress(job.job_id)
        progress.stage("indemnity_calculation", total=200)
        before = assessment_jobs.get_job(job.job_id)["percent"]
        progress.advance(100)
        halfway = assessment_jobs.get_job(job.job_id)["percent"]
        self.assertGreater(halfway, before)

        progress.stage("completion")
        self.assertLess(assessment_jobs.get_job(job.job_id)["percent"], 100)

        progress.done({"assessments_computed": 3})
        snapshot = assessment_jobs.get_job(job.job_id)
        self.assertEqual(snapshot["percent"], 100)
        self.assertEqual(snapshot["status"], "done")
        self.assertEqual(set(self._statuses(job.job_id)), {"completed"})

    def test_failure_marks_current_stage_and_leaves_later_ones_pending(self):
        job, _ = start_job(1, 10, "manual")
        progress = JobProgress(job.job_id)
        progress.stage("exposure_calculation")
        progress.fail("boom")

        snapshot = assessment_jobs.get_job(job.job_id)
        self.assertEqual(snapshot["status"], "error")
        self.assertEqual(self._statuses(job.job_id), ["completed", "failed", "pending", "pending", "pending"])
        self.assertLess(snapshot["percent"], 100)

    def test_stage_cannot_move_backwards(self):
        job, _ = start_job(1, 10, "manual")
        progress = JobProgress(job.job_id)
        progress.stage("indemnity_calculation")
        with self.assertRaises(RuntimeError):
            progress.stage("data_preparation")

    def test_second_run_for_same_typhoon_joins_the_running_one(self):
        first, created_first = start_job(1, 10, "manual")
        second, created_second = start_job(1, 11, "manual")
        other, created_other = start_job(2, 20, "manual")

        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertIs(second, first)
        self.assertTrue(created_other)

    def test_latest_job_prefers_the_running_one(self):
        done_job, _ = start_job(1, 10, "manual")
        JobProgress(done_job.job_id).done({})
        running, _ = start_job(1, 11, "manual")

        self.assertEqual(assessment_jobs.latest_job_for_typhoon(1)["job_id"], running.job_id)
        self.assertIsNone(assessment_jobs.latest_job_for_typhoon(99))


if __name__ == "__main__":
    unittest.main()
