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

    def test_restart_preserves_dirty_checkout_before_fetch(self):
        recovered = d.Project('fixture')
        with patch.dict(os.environ, self.env, clear=True), patch.object(recovered, 'doctor'), \
                patch.object(recovered, 'wait_ci') as wait_ci:
            with self.assertRaisesRegex(d.Blocked, 'Dirty checkout preserved'):
                recovered.iteration()
        wait_ci.assert_not_called()
        self.assertEqual(self.git('write-tree'), self.tree)
        self.assertEqual(self.fixture.read_text(), 'staged change\n')

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

    def test_staged_validation_scans_index_blobs_and_ignores_worktree_edits(self):
        self.fixture.write_text('temporary unstaged edit\n')
        with patch.dict(os.environ, self.env, clear=True):
            self.project.validate_staged_tree(self.base, self.tree)
            self.fixture.write_bytes(b'ghp_' + b'x' * 36 + b'\n')
            self.git('add', 'README.md')
            secret_tree = self.git('write-tree')
            self.fixture.write_text('clean worktree edit\n')
            with self.assertRaisesRegex(d.Blocked, 'Possible credential'):
                self.project.validate_staged_tree(self.base, secret_tree)
        self.assertEqual(self.git('write-tree'), secret_tree)
        self.assertEqual(self.fixture.read_text(), 'clean worktree edit\n')
        self.assertNotIn('ghp_' + 'x' * 36, d.read_private(self.project.log))

    def test_staged_tree_rejects_binary_symlink_size_and_forbidden_paths(self):
        self.project.cfg['allowed_paths'].append('docs/')
        docs = self.project.repo / 'docs'
        docs.mkdir()
        with patch.dict(os.environ, self.env, clear=True):
            for name, contents, expected in (
                ('sample.txt', b'\0', 'binary'),
                ('link with spaces', None, 'symlink'),
                ('large.txt', b'x' * (d.STAGED_BLOB_LIMIT + 1), 'scan limit'),
                ('.env.fixture', b'example\n', 'Forbidden'),
            ):
                with self.subTest(name=name):
                    artifact = docs / name
                    if contents is None:
                        artifact.symlink_to('../README.md')
                    else:
                        artifact.write_bytes(contents)
                    self.git('add', '--', 'docs/' + name)
                    with self.assertRaisesRegex(d.Blocked, expected):
                        self.project.validate_staged_tree(self.base, self.git('write-tree'))
                    self.git('restore', '--staged', '--', 'docs/' + name)
                    artifact.unlink()

    def assert_iteration_blocks_metadata_change(self, phase, mutate):
        self.git('restore', '--source=HEAD', '--staged', '--worktree', 'README.md')
        real_invoke = self.project.invoke
        changed = False

        def invoke(argv, *args, **options):
            nonlocal changed
            self.assertFalse(changed, 'runner invoked a subprocess after metadata changed')
            if options.get('agent'):
                self.fixture.write_text('synthetic agent edit\n')
                if phase == 'agent':
                    mutate()
                    changed = True
                return ''
            if options.get('untrusted'):
                self.assertEqual(phase, 'build')
                mutate()
                changed = True
                return ''
            return real_invoke(argv, *args, **options)

        with patch.dict(os.environ, self.env, clear=True), \
                patch.object(self.project, 'doctor'), \
                patch.object(self.project, 'checkout', return_value=self.base), \
                patch.object(self.project, 'wait_ci', return_value=('success', 1)), \
                patch.object(self.project, 'invoke', side_effect=invoke), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(d.Blocked, 'Protected Git'):
                self.project.iteration()
        self.assertTrue(changed)
        self.assertIsNone(self.project.pending_review())
        self.assertEqual(self.fixture.read_text(), 'synthetic agent edit\n')
        restarted = d.Project('fixture')
        with patch.object(restarted, 'doctor') as doctor:
            with self.assertRaisesRegex(d.Blocked, 'Protected Git'):
                restarted.iteration()
        doctor.assert_not_called()

    def test_agent_origin_change_blocks_before_further_git_and_after_restart(self):
        self.assert_iteration_blocks_metadata_change(
            'agent', lambda: self.git('remote', 'set-url', 'origin', 'https://example.invalid/new.git'))

    def test_build_hook_change_blocks_before_further_git_and_after_restart(self):
        def add_hook():
            hook = self.project.repo / '.git' / 'hooks' / 'pre-commit'
            hook.parent.mkdir(exist_ok=True)
            hook.write_text('#!/bin/sh\nexit 1\n')
            hook.chmod(0o700)
        self.assert_iteration_blocks_metadata_change('build', add_hook)

    def test_build_config_change_blocks_before_further_git_and_after_restart(self):
        self.assert_iteration_blocks_metadata_change(
            'build', lambda: self.git('config', 'core.hooksPath', '/synthetic/hooks'))
