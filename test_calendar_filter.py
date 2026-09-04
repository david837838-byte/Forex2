import unittest
from datetime import datetime, timezone

import server


class TestCalendarFiltering(unittest.TestCase):
    def test_parser_uses_utc_and_handles_am_pm(self):
        parsed, estimated = server.parse_calendar_datetime('09-04-2026', '12:30pm')
        self.assertFalse(estimated)
        self.assertEqual(parsed, datetime(2026, 9, 4, 12, 30, tzinfo=timezone.utc))

    def test_relevant_events_hide_previous_days(self):
        now = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
        events = [
            {'title': 'Old', 'date': '09-02-2026', 'time': '2:00pm', 'impact': 'High'},
            {'title': 'Released today', 'date': '09-04-2026', 'time': '8:00am', 'impact': 'High'},
            {'title': 'Next today', 'date': '09-04-2026', 'time': '12:30pm', 'impact': 'High'},
            {'title': 'Tomorrow', 'date': '09-05-2026', 'time': '9:00am', 'impact': 'Medium'}
        ]

        relevant = server.relevant_calendar_events(events, now)

        self.assertEqual([event['title'] for event in relevant], ['Next today', 'Tomorrow', 'Released today'])
        self.assertEqual(relevant[0]['status'], 'upcoming')
        self.assertEqual(relevant[-1]['status'], 'released')

    def test_tentative_event_gets_a_stable_midday_time(self):
        parsed, estimated = server.parse_calendar_datetime('09-05-2026', 'Tentative')
        self.assertTrue(estimated)
        self.assertEqual(parsed.hour, 12)


if __name__ == '__main__':
    unittest.main()
