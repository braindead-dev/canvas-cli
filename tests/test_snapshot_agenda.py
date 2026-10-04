"""Offline snapshot-date planning, privacy boundaries and installed CLI behavior."""

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from canvas_cli.arguments import parser
from canvas_cli.cli import run
from canvas_cli.client import CanvasError
from canvas_cli.completion import candidates
from canvas_cli.formatting import brief
from canvas_cli.navigation import command_help, command_schema
from canvas_cli.planning import agenda as live_agenda
from canvas_cli.planning import project_agenda
from canvas_cli.snapshot_agenda import agenda


def snapshot(cid=123, **changes):
    return {'schema_version': 1, 'origin': 'https://canvas.example.edu',
            'course_id': cid, 'viewer_user_id': 7,
            'course': {'id': cid, 'name': f'Synthetic course {cid}'},
            'captured_at': '2030-10-01T00:00:00Z', 'complete': True, 'unavailable': {},
            'assignments': [{'id': 456, 'course_id': cid, 'name': 'Synthetic assignment',
                             'due_at': '2030-10-05T12:00:00Z'}], **changes}


class SnapshotAgendaTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2030, 10, 3, tzinfo=timezone.utc)

    def project(self, *snapshots, **options):
        return agenda(list(snapshots), now=self.now, time_zone='UTC', **options)

    def test_multiple_courses_share_urgency_sorting_without_using_cached_completion(self):
        rows = [
            {'id': 1, 'due_at': '2030-10-01T00:00:00Z', 'submission': {'workflow_state': 'graded', 'grade': 'A'}},
            {'id': 2, 'due_at': '2030-10-02T00:00:00Z', 'submission': {'excused': True}},
            {'id': 3, 'due_at': '2030-10-03T12:00:00Z', 'submission': {'workflow_state': 'submitted'}},
            {'id': 4, 'due_at': '2030-10-04T00:00:00Z', 'submission': {'workflow_state': 'pending_review'}},
            {'id': 5, 'due_at': '2030-10-10T00:00:00Z'},
            {'id': 6, 'due_at': '2030-12-01T00:00:00Z'},
        ]
        result = self.project(snapshot(assignments=rows), snapshot(124, assignments=[]))
        self.assertEqual([item['assignment_id'] for item in result['items']], [2, 1, 3, 4, 5])
        self.assertEqual([item['urgency'] for item in result['items']],
                         ['overdue', 'overdue', 'today', 'next_72h', 'later'])
        self.assertTrue(all(item['status'] == 'unknown' for item in result['items']))
        self.assertFalse(result['live_state_verified'])
        self.assertEqual([context['course_id'] for context in result['snapshots']], [123, 124])

    def test_capture_age_coverage_and_unknown_status_are_explicit_in_json_and_brief(self):
        result = self.project(snapshot())
        context = result['snapshots'][0]
        self.assertEqual(context['age_seconds'], 172800)
        self.assertFalse(context['future_dated_capture'])
        self.assertTrue(context['snapshot_reported_complete'])
        self.assertTrue(context['assignment_inventory_reported_complete'])
        self.assertEqual(context['reported_viewer_user_id'], 7)
        self.assertIn('reported claims', result['note'])
        text = brief(result)
        self.assertIn('Offline cached-date Agenda', text)
        self.assertIn('172800 seconds old', text)
        self.assertIn('Submission status and current access are unknown', text)
        self.assertNotIn('unsubmitted', text)

    def test_future_capture_age_is_not_presented_as_verified_freshness(self):
        result = self.project(snapshot(captured_at='2030-10-04T00:00:00Z'))
        self.assertEqual(result['snapshots'][0]['age_seconds'], -86400)
        self.assertTrue(result['snapshots'][0]['future_dated_capture'])
        self.assertIn('future-dated capture; age unverified', brief(result))
        self.assertNotIn('-86400 seconds old', brief(result))

    def test_empty_cached_view_is_not_a_current_completion_claim(self):
        result = self.project(snapshot(assignments=[]))
        self.assertEqual(result['items'], [])
        self.assertIn('not a current completion claim', brief(result))
        self.assertNotIn('No unfinished dated assignments', brief(result))

    def test_undated_and_invalid_dates_remain_separate_from_deadlines(self):
        source = snapshot(assignments=[{'id': 1}, {'id': 2, 'due_at': 'invalid'},
                                       {'id': 3, 'due_at': '2030-10-05T12:00:00'}])
        result = self.project(source)
        self.assertEqual(result['undated_count'], 3)
        self.assertIsNone(result['undated'])
        result = self.project(source, include_undated=True)
        self.assertEqual([item['assignment_id'] for item in result['undated']], [1, 2, 3])
        self.assertTrue(all(item['status'] == 'unknown' for item in result['undated']))
        self.assertIn('not deadlines', brief(result))

    def test_partial_assignment_inventory_keeps_observed_rows_without_echoing_private_errors(self):
        source = snapshot(complete=False, unavailable={'assignments': 'Synthetic private error with secret'})
        result = self.project(source)
        self.assertEqual(len(result['items']), 1)
        self.assertFalse(result['snapshots'][0]['assignment_inventory_reported_complete'])
        self.assertFalse(result['snapshots'][0]['snapshot_reported_complete'])
        self.assertEqual(result['unavailable_courses'][0]['course_id'], 123)
        self.assertNotIn('Synthetic private error', json.dumps(result))
        self.assertIn('Assignments unavailable', brief(result))

    def test_other_capture_gaps_do_not_invent_missing_assignment_coverage(self):
        result = self.project(snapshot(complete=False, unavailable={'pages': 'Denied'}))
        self.assertFalse(result['snapshots'][0]['snapshot_reported_complete'])
        self.assertTrue(result['snapshots'][0]['assignment_inventory_reported_complete'])
        self.assertEqual(result['unavailable_courses'], [])

    def test_legacy_viewer_metadata_is_unverified_even_when_another_file_reports_a_viewer(self):
        legacy = snapshot()
        del legacy['viewer_user_id']
        for sources in ((legacy,), (legacy, snapshot(124))):
            with self.subTest(count=len(sources)):
                result = self.project(*sources)
                self.assertFalse(result['all_snapshots_report_viewer_identity'])
                self.assertIn('account association is unverified', brief(result))
        with self.assertRaisesRegex(CanvasError, 'mixed-account'):
            self.project(snapshot(), snapshot(124, viewer_user_id=8))

    def test_origin_and_course_histories_are_not_silently_merged(self):
        with self.assertRaisesRegex(CanvasError, 'same Canvas origin'):
            self.project(snapshot(), snapshot(124, origin='https://other.example.edu'))
        with self.assertRaisesRegex(CanvasError, 'one snapshot per course'):
            self.project(snapshot(), snapshot(captured_at='2030-10-02T00:00:00Z'))
        result = self.project(snapshot(origin='https://canvas.example.edu/'))
        self.assertEqual(result['snapshots'][0]['origin'], 'https://canvas.example.edu')

    def test_malformed_schema_course_and_viewer_identity_fail_without_value_echo(self):
        variants = [None, [], {}, snapshot(schema_version=True), snapshot(schema_version=2),
                    snapshot(course_id='123'), snapshot(course_id=True), snapshot(course_id=0),
                    snapshot(course=None), snapshot(course={'id': 124}), snapshot(course={'id': '123'})]
        variants += [snapshot(viewer_user_id=value) for value in (None, True, 0, -1, '7', 7.0)]
        for source in variants:
            with self.subTest(source=source), self.assertRaises(CanvasError):
                self.project(source)
        for sources in ([], None, {}, 'Synthetic private invalid input'):
            with self.subTest(sources=sources), self.assertRaisesRegex(CanvasError, 'at least one snapshot'):
                agenda(sources)

    def test_invalid_origins_cannot_expose_credentials_or_construct_untrusted_navigation(self):
        for host in (None, {}, 'http://canvas.example.edu', 'https://user:SyntheticSecret@example.edu',
                     'https://canvas.example.edu?token=SyntheticSecret', 'https://canvas.example.edu/path',
                     'https://canvas.example.edu:99999', 'https://canvas.example.edu:bad',
                     'https://canvas.example.edu\n', 'https://can vas.example.edu', 'https://canvas.example.edu\x7f'):
            with self.subTest(host=host), self.assertRaisesRegex(CanvasError, 'origin metadata') as raised:
                self.project(snapshot(origin=host))
            self.assertNotIn('SyntheticSecret', str(raised.exception))

    def test_malformed_capture_and_coverage_do_not_become_false_empty_success(self):
        variants = [snapshot(captured_at=value) for value in
                    (None, {}, 'invalid', '2030-10-01T00:00:00', '0001-01-01T00:00:00+01:00')]
        variants += [snapshot(complete=value) for value in (None, 0, 1, 'true')]
        variants += [snapshot(unavailable=value) for value in (None, [], {1: 'Denied'}, {'assignments': 'Denied'})]
        variants += [snapshot(assignments=value) for value in (None, {}, 'Synthetic private body')]
        for source in variants:
            with self.subTest(source=source), self.assertRaisesRegex(CanvasError, 'capture or coverage'):
                self.project(source)

    def test_foreign_duplicate_and_malformed_assignment_identity_fail_closed(self):
        rows = [None, [], {}, {'id': True}, {'id': 0}, {'id': '456'},
                {'id': 456, 'course_id': 124}, {'id': 456, 'course_id': '123'}]
        for row in rows:
            with self.subTest(row=row), self.assertRaisesRegex(CanvasError, 'assignment identity'):
                self.project(snapshot(assignments=[row]))
        with self.assertRaisesRegex(CanvasError, 'Duplicate snapshot assignment identity'):
            self.project(snapshot(assignments=[{'id': 456}, {'id': 456}]))

    def test_visibility_exclusion_never_prints_hidden_titles_or_bodies(self):
        flags = [{'published': False}, {'hidden_for_user': True}, {'locked_for_user': True},
                 {'state': 'unpublished'}, {'state': 'locked'}, {'workflow_state': 'deleted'},
                 {'workflow_state': 'unpublished'}]
        rows = [{'id': i + 1, 'name': 'Synthetic hidden title',
                 'description': 'Synthetic hidden body', **flag} for i, flag in enumerate(flags)]
        result = self.project(snapshot(assignments=rows))
        self.assertEqual(result['snapshots'][0]['excluded_saved_visibility_rows'], len(rows))
        self.assertEqual(result['items'], [])
        self.assertNotIn('Synthetic hidden', json.dumps(result) + brief(result))
        self.assertIn('saved hidden/unpublished/locked row(s) withheld', brief(result))

    def test_bodies_grades_raw_links_and_terminal_controls_are_not_exported(self):
        source = snapshot(course={'id': 123, 'name': '\x1bSynthetic\ncourse\x7f'}, assignments=[{
            'id': 456, 'name': 'Synthetic\x00assignment\rname', 'due_at': '2030-10-05T12:00:00Z',
            'description': 'Synthetic private answer', 'html_url': 'https://other.example.edu/?token=SyntheticSecret',
            'submission': {'workflow_state': 'graded', 'body': 'Synthetic private answer', 'grade': 'SECRET_GRADE'},
            'feedback': 'Synthetic private feedback', 'access_token': 'SyntheticSecret'}])
        before = copy.deepcopy(source)
        result = self.project(source)
        encoded = json.dumps(result) + brief(result)
        for forbidden in ('Synthetic private', 'SyntheticSecret', 'SECRET_GRADE', 'other.example.edu', '\x1b', '\x00', '\x7f'):
            self.assertNotIn(forbidden, encoded)
        self.assertEqual(result['items'][0]['html_url'], 'https://canvas.example.edu/courses/123/assignments/456')
        self.assertEqual(result['items'][0]['name'], 'Synthetic assignment name')
        self.assertEqual(source, before)

    def test_malformed_selected_text_and_date_metadata_fail_without_body_echo(self):
        variants = [snapshot(course={'id': 123, 'name': {}}),
                    snapshot(course={'id': 123, 'course_code': []}),
                    snapshot(assignments=[{'id': 456, 'name': {}}])]
        variants += [snapshot(assignments=[{'id': 456, field: {'body': 'SyntheticPrivateSecret'}}])
                     for field in ('due_at', 'unlock_at', 'lock_at')]
        for source in variants:
            with self.subTest(source=source), self.assertRaises(CanvasError) as raised:
                self.project(source)
            self.assertNotIn('SyntheticPrivateSecret', str(raised.exception))

    def test_raw_invalid_timestamps_are_withheld_and_valid_timestamps_are_canonical_inert_utc(self):
        source = snapshot(captured_at='2030-10-01\x1b00:00:00Z', assignments=[
            {'id': 1, 'due_at': 'SyntheticPrivateSecret\x1b[31m', 'unlock_at': 'SyntheticPrivateSecret'},
            {'id': 2, 'due_at': '2030-10-05\x1b12:00:00Z', 'lock_at': 'SyntheticPrivateSecret'}])
        result = self.project(source, include_undated=True)
        self.assertEqual(result['snapshots'][0]['captured_at'], '2030-10-01T00:00:00+00:00')
        self.assertEqual(result['items'][0]['due_at'], '2030-10-05T12:00:00+00:00')
        self.assertEqual(result['items'][0]['lock_at'], 'unknown_invalid_date')
        self.assertEqual(result['items'][0]['availability'], 'unknown_invalid_dates')
        self.assertEqual(result['undated'][0]['due_at'], 'unknown_invalid_date')
        self.assertNotIn('SyntheticPrivateSecret', json.dumps(result) + brief(result))
        self.assertNotIn('\x1b', brief(result))

    def test_saved_availability_is_date_only_and_malformed_bounds_are_unknown(self):
        rows = [{'id': 1, 'due_at': '2030-10-05T12:00:00Z', 'unlock_at': 'invalid', 'lock_at': 'invalid'},
                {'id': 2, 'due_at': '2030-10-05T12:00:00Z', 'lock_at': '2030-10-02T00:00:00Z'},
                {'id': 3, 'due_at': '2030-10-05T12:00:00Z', 'unlock_at': '2030-10-04T00:00:00Z'},
                {'id': 4, 'due_at': '2030-10-05T12:00:00Z', 'unlock_at': '2030-10-01T00:00:00Z',
                 'lock_at': '2030-10-06T00:00:00Z'}]
        result = self.project(snapshot(assignments=rows))
        self.assertEqual([item['availability'] for item in result['items']],
                         ['unknown_invalid_dates', 'closed', 'not_yet_open', 'within_window'])
        self.assertIn('not current permission', result['note'])

    def test_timezone_dst_and_date_projection_match_the_live_agenda_builder(self):
        now = datetime(2030, 11, 2, 17, tzinfo=timezone.utc)
        source = snapshot(assignments=[{'id': 456, 'due_at': '2030-11-03T09:00:00Z'}])
        result = agenda([source], now=now, time_zone='America/Los_Angeles')
        direct = project_agenda([{'course_id': 123, 'assignment_id': 456, 'status': 'unknown',
                                 'due_at': '2030-11-03T09:00:00Z'}], [], now=now, time_zone='America/Los_Angeles')
        for key in ('due_local', 'due_display', 'urgency', 'availability'):
            self.assertEqual(result['items'][0][key], direct['items'][0][key])
        self.assertEqual(result['items'][0]['due_local'], '2030-11-03T01:00:00-08:00')

    def test_invalid_live_agenda_options_fail_before_any_canvas_reads(self):
        variants = [{'days': value} for value in (0, -1, True, '14', 10**30)]
        variants += [{'time_zone': value} for value in (None, {}, 'No/Such_Zone')]
        variants += [{'now': value} for value in (0, True, 'invalid', datetime(2030, 10, 3),
                                                  datetime(9999, 12, 31, tzinfo=timezone.utc))]
        for options in variants:
            client = Mock()
            with self.subTest(options=options), self.assertRaises(CanvasError):
                live_agenda(client, 100, **options)
            client.list.assert_not_called()

    def test_offline_help_schema_and_completion_discover_the_new_command(self):
        self.assertEqual(command_help(parser(), 'snapshot-agenda')['safety'], 'Read-only')
        arguments = command_schema(parser(), 'snapshot-agenda')['commands'][0]['arguments']
        paths = next(arg for arg in arguments if arg['destination'] == 'snapshots')
        self.assertEqual(paths['nargs'], '+')
        self.assertEqual(candidates(parser(), ['canvas', 'snapshot-a'], 1)['completion_candidates'], ['snapshot-agenda'])


class SnapshotAgendaCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'synthetic.json'
        self.source = snapshot(assignments=[{'id': 456, 'name': 'Synthetic cached task',
                                            'due_at': (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()}])
        self.path.write_text(json.dumps(self.source), encoding='utf-8')

    def invoke(self, *args):
        environment = {**os.environ, 'CANVAS_ORIGIN': 'http://invalid.example.edu',
                       'CANVAS_TOKEN': 'SyntheticUnusedCredential', 'XDG_CONFIG_HOME': self.tmp.name}
        return subprocess.run([sys.executable, '-m', 'canvas_cli.cli', *args], env=environment,
                              capture_output=True, text=True, timeout=15, check=False)

    @patch('canvas_cli.auth.connect')
    @patch('canvas_cli.auth.config_path')
    def test_routing_never_accesses_credentials_and_never_edits_selected_files(self, config, connect):
        before = self.path.read_bytes()
        result = run(parser().parse_args(['snapshot-agenda', str(self.path), '--timezone', 'UTC']))
        self.assertEqual(result['agenda_source'], 'snapshot')
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(sorted(path.name for path in Path(self.tmp.name).iterdir()), ['synthetic.json'])
        config.assert_not_called()
        connect.assert_not_called()

    def test_installed_subprocess_has_no_canvas_auth_requirement_or_extra_files(self):
        before = self.path.read_bytes()
        for output in ('json', 'brief'):
            result = self.invoke('snapshot-agenda', str(self.path), '--format', output)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Synthetic cached task', result.stdout)
            self.assertNotIn('SyntheticUnusedCredential', result.stdout + result.stderr)
            if output == 'json':
                self.assertFalse(json.loads(result.stdout)['live_state_verified'])
            else:
                self.assertIn('Offline cached-date', result.stdout)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(sorted(path.name for path in Path(self.tmp.name).iterdir()), ['synthetic.json'])

    def test_file_and_metadata_failures_do_not_echo_untrusted_contents(self):
        for text in ('SyntheticPrivateSecret', '{"schema_version":1,"schema_version":1}',
                     '{"schema_version":1,"value":NaN}', json.dumps(snapshot(origin='https://a:SyntheticPrivateSecret@example.edu'))):
            with self.subTest(text=text):
                self.path.write_text(text, encoding='utf-8')
                result = self.invoke('snapshot-agenda', str(self.path))
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')
                self.assertNotIn('SyntheticPrivateSecret', result.stderr)
        result = self.invoke('snapshot-agenda', str(Path(self.tmp.name) / 'missing.json'))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('valid JSON snapshot', result.stderr)

    def test_multi_file_invocation_preserves_each_explicit_course_and_refuses_duplicate_history(self):
        other = Path(self.tmp.name) / 'other-synthetic.json'
        other.write_text(json.dumps(snapshot(124)), encoding='utf-8')
        result = self.invoke('snapshot-agenda', str(self.path), str(other), '--timezone', 'UTC')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([context['course_id'] for context in json.loads(result.stdout)['snapshots']], [123, 124])
        result = self.invoke('snapshot-agenda', str(self.path), str(self.path))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('one snapshot per course', result.stderr)
