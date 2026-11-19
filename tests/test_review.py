"""Offline review acknowledgement through the CLI and across runner restarts."""

import contextlib
import io
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


class ReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        state_root = directory / 'state'
        override = patch.object(d, 'ROOT', state_root)
        override.start()
        self.addCleanup(override.stop)
        self.env = {'PATH': os.defpath, 'HOME': str(directory), 'GIT_CONFIG_NOSYSTEM': '1',
                    'DEVLOOP_HOME': str(state_root), 'GIT_TERMINAL_PROMPT': '0'}
        config = dict(d.load(SOURCE / 'examples/jobstein.json'),
                      repository='synthetic/review', auto_push=False)
        d.atomic(d.project_home('fixture') / 'config.json', config)
        self.project = d.Project('fixture')
        self.git('init', '--initial-branch=main', str(self.project.repo), cwd=directory)
        self.git('remote', 'add', 'origin', self.project.origin)
        self.git('config', 'user.name', 'Synthetic Reviewer')
        self.git('config', 'user.email', 'reviewer@example.invalid')
        self.fixture = self.project.repo / 'README.md'
        self.fixture.write_text('baseline\n')
        self.git('add', 'README.md')
        self.git('commit', '-m', 'Synthetic baseline')
        self.base = self.git('rev-parse', 'HEAD')
        self.fixture.write_text('staged change\n')
        self.git('add', 'README.md')
        self.tree = self.git('write-tree')

    def git(self, *args, cwd=None):
        return subprocess.run(['git', *args], cwd=cwd or self.project.repo, env=self.env,
                              capture_output=True, text=True, check=True, timeout=5).stdout.strip()

    def cli(self, command, *args):
        return subprocess.run([sys.executable, '-B', str(SOURCE / 'devloop.py'), command, 'fixture', *args],
                              env=self.env, capture_output=True, text=True, timeout=5)

    def queue_review(self):
        with self.project.lock(), contextlib.redirect_stdout(io.StringIO()):
            self.project.pause_for_review(self.base, self.tree)
        return self.project.pending_review()['id']

    def test_acknowledgement_requires_matching_id_and_resolved_checkout(self):
        review_id = self.queue_review()
        status = json.loads(self.cli('status').stdout)
        self.assertEqual((status['review']['id'], status['review']['tree']), (review_id, self.tree))
        self.assertIn('Acknowledge', self.cli('resume').stderr)
        self.assertIn('does not match', self.cli('acknowledge', '0' * 32).stderr)
        self.assertIn('Resolve staged', self.cli('acknowledge', review_id).stderr)
        self.assertEqual(self.git('write-tree'), self.tree)
        self.git('commit', '-m', 'Manual synthetic review resolution')
        accepted = self.cli('acknowledge', review_id)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        status = json.loads(self.cli('status').stdout)
        self.assertTrue(status['paused'])
        self.assertIsNone(status['review'])
        self.assertEqual(status['last']['review_id'], review_id)
        self.assertEqual(status['last']['status'], 'review-acknowledged')
        self.assertIn('does not match', self.cli('acknowledge', review_id).stderr)
        self.assertEqual(self.cli('resume').returncode, 0)
        self.assertFalse(self.project.is_paused())

    def test_durable_review_blocks_restart_without_pause_or_status_snapshot(self):
        review_id = self.queue_review()
        d.remove_private(self.project.pause)
        d.remove_private(self.project.state)
        recovered = d.Project('fixture')
        with patch.object(recovered, 'doctor') as doctor:
            recovered.iteration()
        doctor.assert_not_called()
        self.assertTrue(recovered.is_paused())
        self.assertEqual(recovered.pending_review()['id'], review_id)

    def test_legacy_review_and_untracked_changes(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.project.record('review', 'Legacy staged changes', sha=self.base)
        self.project.set_paused()
        self.assertIn('Acknowledge', self.cli('resume').stderr)
        self.git('restore', '--source=HEAD', '--staged', '--worktree', 'README.md')
        untracked = self.project.repo / 'untracked.txt'
        untracked.write_text('preserve me\n')
        self.assertIn('Resolve staged', self.cli('acknowledge', self.base).stderr)
        untracked.unlink()
        result = self.cli('acknowledge', self.base)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.project.is_paused())
        self.assertIsNone(self.project.pending_review())

    def test_concurrent_review_commands_respect_iteration_lock(self):
        review_id = self.queue_review()
        with self.project.lock():
            for command in (('acknowledge', review_id), ('resume',)):
                self.assertIn('holds the project lock', self.cli(*command).stderr)
        self.assertEqual(self.project.pending_review()['id'], review_id)
