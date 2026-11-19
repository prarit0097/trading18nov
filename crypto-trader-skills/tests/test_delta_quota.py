from pathlib import Path
import tempfile
import unittest

from crypto_skills.delta_quota import assess_weekly_quota, entry_hold_reason, quota_allows_entry


class WeeklyQuotaTests(unittest.TestCase):
    def reading(self, percent, *, reset=2000, duration=10080):
        return {'usedPercent': percent, 'windowDurationMins': duration, 'resetsAt': reset}

    def test_codex_weekly_limit_overrides_legacy_and_five_hour_windows(self):
        data = {'rateLimits': {'primary': self.reading(1)}, 'rateLimitsByLimitId': {
            'codex': {'primary': self.reading(0, duration=300), 'secondary': self.reading(50)},
        }}
        self.assertEqual(assess_weekly_quota(data, now=1000),
                         {'status': 'weekly_quota_reserve', 'remaining_percent': 50, 'resets_at': 2000})

    def test_unavailable_or_expired_weekly_limits_never_admit_orders(self):
        for weekly in (self.reading(0, reset=1000), self.reading(0, duration=300),
                       self.reading(-1), self.reading(True), self.reading(101)):
            with self.subTest(weekly=weekly):
                self.assertEqual(assess_weekly_quota(
                    {'rateLimits': {'primary': weekly}}, now=1000)['status'], 'weekly_quota_unavailable')

    def test_only_fresh_verified_headroom_admits_orders(self):
        quota = {'status': 'available', 'checked_at': 1000, 'resets_at': 1030}
        self.assertTrue(quota_allows_entry(quota, now=1029))
        self.assertFalse(quota_allows_entry(quota, now=1030))
        self.assertFalse(quota_allows_entry(quota, now=999))
        self.assertFalse(quota_allows_entry(
            dict(quota, resets_at=2000), now=1060))
        self.assertFalse(quota_allows_entry({'status': 'weekly_quota_unavailable'}, now=1030))

    def test_entry_hold_stops_submissions_with_valid_quota(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / 'ENTRY_HOLD').touch()
            self.assertEqual(entry_hold_reason(run), 'entry_hold')
            (run / 'STOP').touch()
            self.assertEqual(entry_hold_reason(run), 'stop_file')
