import unittest

from canvas_cli.formatting import brief
from canvas_cli.snapshot_diff import compare


def snapshot():
    return {'origin': 'https://canvas.example.edu', 'course_id': 12, 'viewer_user_id': 7,
            'captured_at': '2026-10-01T00:00:00Z', 'course': {'name': 'Synthetic class'},
            'assignments': [{'id': 1, 'name': 'Paper', 'description': 'Synthetic private old description'}],
            'modules': [], 'pages': [], 'announcements': [], 'discussions': [], 'unavailable': {}}


class DiffFormattingTests(unittest.TestCase):
    def test_untrusted_names_and_notes_cannot_send_terminal_controls_from_any_summary(self):
        name = 'Synthetic \x1b]52;c;U3ludGhldGlj\x07 \u202eHidden\u202c'
        samples = ({'appointment_groups': [{'id': 501, 'title': name, 'participant_type': 'User'}], 'note': name},
                   {'team': {'id': 11, 'name': name}, 'appointment_group': {'id': 501}, 'team_reservations': [], 'note': name},
                   {'own_profile': {'name': name}, 'note': name}, [{'id': 101, 'name': name}],
                   {'unknown_synthetic_record': name})
        for data in samples:
            with self.subTest(data=data):
                result = brief(data)
                self.assertNotIn('\x1b', result)
                self.assertNotIn('\x07', result)
                self.assertNotIn('\u202e', result)
                self.assertIn('Synthetic', result)

    def test_terminal_projection_does_not_mutate_the_data_used_by_json_or_confirmation(self):
        record = {'own_profile': {'name': 'Synthetic \x1b[31mname\r\u202e'}, 'note': 'Private metadata'}
        name = record['own_profile']['name']
        result = brief(record)
        self.assertEqual(record['own_profile']['name'], name)
        self.assertIn('\\u001b[31mname\\u000d\\u202e', result)

    def test_brief_diff_names_changes_without_printing_values(self):
        old = snapshot()
        new = {**old, 'captured_at': '2026-10-02T00:00:00Z',
               'course': {**old['course'], 'syllabus_body': 'Synthetic private syllabus'},
               'assignments': [{**old['assignments'][0], 'description': 'Synthetic private new description'},
                               {'id': 2, 'name': 'New reading', 'description': 'Synthetic private added description'}]}
        text = brief(compare(old, new))
        self.assertIn('Snapshot diff: course 12; viewer 7', text)
        self.assertIn('3 change(s) in fully covered resources', text)
        self.assertIn('Course fields: syllabus_body', text)
        self.assertIn('assignments changed: Paper (1) [description]', text)
        self.assertIn('assignments added: New reading (2)', text)
        self.assertNotIn('Synthetic private', text)

    def test_partial_diff_never_reports_full_removals(self):
        old = {**snapshot(), 'unavailable': {'pages': 'Synthetic denied'},
               'pages': [{'url': 'welcome', 'title': 'Welcome', 'body': 'Synthetic private old page'},
                         {'url': 'not-visible-now', 'title': 'Missing page'}]}
        new = {**old, 'pages': [{'url': 'welcome', 'title': 'Welcome', 'body': 'Synthetic private new page'}]}
        text = brief(compare(old, new))
        self.assertIn('1 change(s) observed in partial resources', text)
        self.assertIn('pages observed change: Welcome (welcome) [body]', text)
        self.assertNotIn('pages removed', text)
        self.assertNotIn('Synthetic private', text)
        self.assertIn('Skipped full inventory comparisons: linked_files, pages', text)
        self.assertIn('Unseen changes remain unknown', text)

    def test_legacy_brief_identity_is_unverified_even_when_one_viewer_is_known(self):
        new = snapshot()
        old = {key: value for key, value in new.items() if key != 'viewer_user_id'}
        text = brief(compare(old, new))
        self.assertIn('viewer unverified', text)
        self.assertIn('explicitly selected offline comparison is unverified', text)
        self.assertNotIn('viewer 7', text)

    def test_sync_reuses_diff_details_and_baseline_has_no_invented_changes(self):
        old = snapshot()
        new = {**old, 'assignments': []}
        data = {'origin': old['origin'], 'user_id': 7, 'counts': {},
                'saved': '/private/path/synthetic.json', 'baseline': False, 'diff': compare(old, new)}
        text = brief(data)
        self.assertIn('assignments removed: Paper (1)', text)
        self.assertIn('course snapshots are account-separated', text)
        self.assertNotIn('Synthetic private', text)
        baseline = brief({**data, 'baseline': True, 'diff': None})
        self.assertIn('Baseline created', baseline)
        self.assertNotIn('assignments removed', baseline)

    def test_no_observed_changes_is_not_a_complete_inventory_claim(self):
        text = brief(compare(snapshot(), snapshot()))
        self.assertIn('0 change(s) in fully covered resources', text)
        self.assertIn('Skipped full inventory comparisons: linked_files', text)
        self.assertNotIn('No coursework', text)
        self.assertNotIn('All content unchanged', text)
