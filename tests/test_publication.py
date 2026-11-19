"""Offline publication recovery with a real local Git remote."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
import devloop as d


class PublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.mock(d, 'ROOT', self.root / 'state')
        self.mock(d, 'STOP', False)
        self.remote = self.root / 'remote.git'
        self.git('init', '--bare', '--initial-branch=main', str(self.remote))
        self.config = d.load(SOURCE / 'examples/jobstein.json')
        self.config.update(repository='synthetic/publish', auto_push=False)
        self.project = self.new_project('fixture')
        self.repo = self.project.repo
        self.git('init', '--initial-branch=main', str(self.repo))
        self.git('config', 'user.name', 'Synthetic Tester', cwd=self.repo)
        self.git('config', 'user.email', 'tester@example.invalid', cwd=self.repo)
        self.git('remote', 'add', 'origin', str(self.remote), cwd=self.repo)
        self.fixture = self.repo / 'README.md'
        self.fixture.write_text('base\n')
        self.git('add', 'README.md', cwd=self.repo)
        self.git('commit', '-m', 'Synthetic base', cwd=self.repo)
        self.git('push', 'origin', 'main', cwd=self.repo)
        self.base = self.git('rev-parse', 'HEAD', cwd=self.repo)
        self.fixture.write_text('tested change\n')
        self.git('add', 'README.md', cwd=self.repo)
        self.tree = self.git('write-tree', cwd=self.repo)
        self.pushes = []
        self.remote_checks = []
        self.ci_checks = []
        self.push_failure = None
        self.remote_unavailable = False
        self.ci_result = 'success'
        self.mock(d.Project, 'invoke', self.transport)
        self.addCleanup(lambda: self.assertFalse(self.project.cfg['auto_push']))

    def mock(self, target, name, value):
        override = patch.object(target, name, value)
        override.start()
        self.addCleanup(override.stop)

    def new_project(self, name, **changes):
        d.atomic(d.project_home(name) / 'config.json', dict(self.config, **changes))
        return d.Project(name)

    @staticmethod
    def git(*args, cwd=None):
        return subprocess.run(['git', *args], cwd=cwd, text=True,
                              capture_output=True, check=True, timeout=10).stdout.strip()

    def transport(self, argv, cwd=None, **_):
        if argv[:2] == ['gh', 'run']:
            candidate = argv[argv.index('--commit') + 1]
            self.ci_checks.append(candidate)
            return json.dumps([
                dict(headSha=candidate, event='push', status='completed',
                     conclusion=self.ci_result, databaseId=7),
                dict(headSha=self.base, event='push', status='completed',
                     conclusion='success', databaseId=99),
            ])
        self.assertEqual(argv[0], 'git', 'only synthetic Git and CI transport is allowed')
        args = argv[1:]
        if args == ['remote', 'get-url', '--push', '--all', 'origin']:
            self.assertEqual(self.git(*args, cwd=cwd), str(self.remote))
            return self.project.origin
        if args[0] == 'ls-remote':
            self.assertEqual(args, ['ls-remote', '--refs', '--', self.project.origin, 'refs/heads/main'])
            self.remote_checks.append(args[-1])
            if self.remote_unavailable:
                raise d.Blocked('Synthetic remote outage')
            return self.git(*args[:3], str(self.remote), args[-1])
        if args[0] == 'push':
            journal = d.load_private(self.project.publication)
            self.assertEqual(journal['phase'], 'prepared')
            self.assertEqual(journal['base'], self.base)
            self.assertEqual(args, ['push', 'origin', journal['commit'] + ':refs/heads/main'])
            self.pushes.append(journal['commit'])
            if self.push_failure == 'before':
                raise d.Blocked('Synthetic push interrupted before acceptance')
            self.git(*args, cwd=cwd)
            if self.push_failure == 'after':
                raise d.Blocked('Synthetic push response lost after acceptance')
            return ''
        self.assertIn(args[0], ('fetch', 'rev-parse', 'commit', 'show'))
        return self.git(*args, cwd=cwd)

    def publish(self):
        with self.project.lock():
            self.project.publish(self.base, self.tree)

    def remote_head(self):
        return self.git('--git-dir=' + str(self.remote), 'rev-parse', 'refs/heads/main')

    def advance_remote(self):
        other = self.git('commit-tree', self.tree, '-p', self.base, '-m', 'External update', cwd=self.repo)
        self.git('push', 'origin', other + ':refs/heads/main', cwd=self.repo)
        return other

    def restart(self, name='fixture'):
        # Online preflight or a new checkout would be a regression during recovery.
        project = d.Project(name)
        with patch.object(project, 'doctor', side_effect=AssertionError('unexpected preflight')):
            project.iteration()
        return project

    def test_lost_response_after_remote_acceptance_recovers_exact_candidate_without_repush(self):
        self.push_failure = 'after'
        with self.assertRaisesRegex(d.Blocked, 'outcome unconfirmed'):
            self.publish()
        candidate, = self.pushes
        entry = d.load_private(self.project.publication)
        self.assertEqual(entry['commit'], candidate)
        self.assertEqual(entry['phase'], 'prepared')
        self.assertEqual(self.remote_head(), candidate)
        self.assertEqual(self.ci_checks, [])

        self.fixture.write_text('edit to preserve during recovery\n')
        recovered = self.restart()
        self.assertEqual(self.fixture.read_text(), 'edit to preserve during recovery\n')
        self.assertEqual(self.ci_checks, [candidate])
        self.assertEqual(self.pushes, [candidate])
        self.assertEqual(self.remote_checks, ['refs/heads/main'])
        self.assertIsNone(recovered.pending_publication())
        state = d.load_private(recovered.state)
        self.assertEqual((state['status'], state['sha'], state['run_id']), ('ci-success', candidate, 7))

    def test_unobserved_outcome_preserved_on_outage_unchanged_moved_or_missing_ref(self):
        self.push_failure = 'before'
        with self.assertRaisesRegex(d.Blocked, 'outcome unconfirmed'):
            self.publish()
        candidate, = self.pushes
        entry = self.project.pending_publication()
        self.remote_unavailable = True
        with self.assertRaisesRegex(d.Blocked, 'Synthetic remote outage'):
            self.restart()
        self.remote_unavailable = False
        with self.assertRaisesRegex(d.Blocked, 'still at the publication base'):
            self.restart()
        self.assertEqual(self.remote_head(), self.base)
        other = self.advance_remote()
        with self.assertRaisesRegex(d.Blocked, 'missing or at an unexpected commit'):
            self.restart()
        self.assertEqual(self.remote_head(), other)
        self.git('--git-dir=' + str(self.remote), 'update-ref', '-d', 'refs/heads/main')
        with self.assertRaisesRegex(d.Blocked, 'missing or at an unexpected commit'):
            self.restart()
        self.assertEqual(self.project.pending_publication(), entry)
        self.assertEqual(self.pushes, [candidate])
        self.assertEqual(self.ci_checks, [])
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=self.repo), candidate)

    def test_stale_base_stops_publication_before_commit_or_journal(self):
        other = self.advance_remote()
        with self.assertRaisesRegex(d.Blocked, 'Remote branch advanced'):
            self.publish()
        self.assertEqual(self.remote_head(), other)
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=self.repo), self.base)
        self.assertEqual(self.git('write-tree', cwd=self.repo), self.tree)
        self.assertIsNone(self.project.pending_publication())
        self.assertEqual(self.pushes, [])

    def test_observed_publication_survives_interrupted_ci_and_completes_on_restart(self):
        with patch.object(self.project, 'wait_ci', side_effect=d.Blocked('Synthetic CI interruption')):
            with self.assertRaisesRegex(d.Blocked, 'CI interruption'):
                self.publish()
        candidate, = self.pushes
        self.assertEqual(self.project.pending_publication()['phase'], 'observed')
        self.assertEqual(self.remote_checks, ['refs/heads/main'])
        self.ci_result = 'failure'
        recovered = self.restart()
        self.assertEqual(self.ci_checks, [candidate])
        self.assertEqual(self.pushes, [candidate])
        self.assertEqual(self.remote_checks, ['refs/heads/main'])
        self.assertIsNone(recovered.pending_publication())
        self.assertEqual(d.load_private(recovered.state)['status'], 'ci-failure')

    def test_shared_journal_blocks_alias_with_different_branch_or_workflow(self):
        self.push_failure = 'after'
        with self.assertRaises(d.Blocked):
            self.publish()
        self.new_project('alias', repository='Synthetic/Publish', branch='other')
        with self.assertRaisesRegex(d.Blocked, 'different branch or workflow'):
            self.restart('alias')
        self.assertEqual(self.project.pending_publication()['phase'], 'prepared')
        self.assertEqual(len(self.pushes), 1)
        self.assertEqual(self.remote_checks, [])
        self.assertEqual(self.ci_checks, [])

    def test_invalid_journal_does_not_start_a_new_iteration(self):
        with self.project.lock():
            d.atomic(self.project.publication, {'version': True, 'commit': 'invalid'})
        with self.assertRaisesRegex(d.Blocked, 'Invalid publication journal'):
            self.restart()
        self.assertEqual(self.pushes, [])
        self.assertEqual(self.remote_checks, [])
