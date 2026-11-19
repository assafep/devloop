"""Offline checks for configuration and runner-owned state."""

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
import devloop as d


class PrivateStateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.root = self.directory / 'state'
        self.home = self.root / 'fixture'
        override = patch.object(d, 'ROOT', self.root)
        override.start()
        self.addCleanup(override.stop)
        self.config = d.load(SOURCE / 'examples/jobstein.json')

    def cli(self, *args):
        return subprocess.run([sys.executable, '-B', str(SOURCE / 'devloop.py'), *args],
                              env=dict(os.environ, DEVLOOP_HOME=str(self.root)),
                              capture_output=True, text=True, timeout=5)

    def project(self):
        d.atomic(d.project_home('fixture') / 'config.json', self.config)
        return d.Project('fixture')

    def test_strict_schema(self):
        d.validate_config(self.config)
        invalid = {
            'repository': [None, 'owner/..', 'https://github.com/owner/repo'],
            'branch': ['main//branch', 'feature/.hidden', 'main.lock', 'main..next', 12],
            'workflow': [True, '', 'CI\0'],
            'instructions': [None, '  '],
            'agent_timeout_seconds': [True, 0, -1, 1.0, '10'],
            'auto_push': [0, 'false', None],
            'test_command': ['echo test', [], [''], ['echo', 5], ['echo', '\0']],
            'allowed_paths': ['docs/', [], ['/'], ['/etc/passwd'], ['docs/../x'], ['docs//'],
                              ['.github/'], ['docs/', 'docs/'], ['docs\\other']],
        }
        for field, cases in invalid.items():
            for value in cases:
                with self.subTest(field=field, value=value), self.assertRaises(d.Blocked):
                    d.validate_config(dict(self.config, **{field: value}))
        for invalid_config in (None, [], dict(self.config, surprise=True),
                               {key: value for key, value in self.config.items() if key != 'auto_push'}):
            with self.assertRaises(d.Blocked):
                d.validate_config(invalid_config)

    def test_add_rejects_duplicate_keys_and_invalid_config_without_writing_state(self):
        source = self.directory / 'input.json'
        source.write_text('{"auto_push": false, "auto_push": true}')
        result = self.cli('add', 'fixture', str(source))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('duplicate keys', result.stderr)
        source.write_text('{"interval_seconds": NaN}')
        result = self.cli('add', 'fixture', str(source))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('non-finite number', result.stderr)
        source.write_text(json.dumps(dict(self.config, test_command='echo test')))
        result = self.cli('add', 'fixture', str(source))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('test_command', result.stderr)
        self.assertFalse(self.root.exists())

    def test_private_modes_atomic_updates_and_duplicate_add(self):
        source = self.directory / 'input.json'
        source.write_text(json.dumps(self.config))
        result = self.cli('add', 'fixture', str(source))
        self.assertEqual(result.returncode, 0, result.stderr)
        project = d.Project('fixture')
        project.record('first', 'synthetic')
        old_fd = os.open(project.state, os.O_RDONLY)
        with os.fdopen(old_fd) as old_state:
            project.record('second', 'synthetic')
            self.assertEqual(json.load(old_state)['status'], 'first')
        self.assertEqual(d.load_private(project.state)['status'], 'second')
        with project.lock():
            project.set_paused()
        project.invoke([sys.executable, '-c', 'pass'])
        for directory in (self.root, self.home):
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        for path in self.home.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        source.write_text(json.dumps(dict(self.config, instructions='replacement')))
        result = self.cli('add', 'fixture', str(source))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(d.Project('fixture').cfg, self.config)
        self.assertEqual(list(self.home.glob('.devloop-*')), [])

    def test_rejects_symlinked_root_project_and_checkout(self):
        target = self.directory / 'target'
        target.mkdir(mode=0o700)
        self.root.symlink_to(target, target_is_directory=True)
        with self.assertRaises(OSError):
            d.project_home('fixture')
        self.assertEqual(list(target.iterdir()), [])
        with patch.object(d, 'ROOT', self.root / 'nested'), self.assertRaises(OSError):
            d.project_home('fixture')
        self.assertEqual(list(target.iterdir()), [])
        self.root.unlink()
        self.root.mkdir(mode=0o700)
        self.home.symlink_to(target, target_is_directory=True)
        with self.assertRaises(OSError):
            d.project_home('fixture')
        self.home.unlink()
        project = self.project()
        project.repo.symlink_to(target, target_is_directory=True)
        with patch.object(project, 'invoke') as invoke, self.assertRaises(OSError):
            project.checkout()
        invoke.assert_not_called()

    def test_rejects_unsafe_file_permissions_hardlinks_and_fifos(self):
        project = self.project()
        config = self.home / 'config.json'
        config.chmod(0o644)
        with self.assertRaises(d.Blocked):
            d.Project('fixture')
        config.chmod(0o600)
        alias = self.directory / 'alias'
        os.link(config, alias)
        with self.assertRaises(d.Blocked):
            d.Project('fixture')
        alias.unlink()
        os.mkfifo(project.log, 0o600)
        with self.assertRaises(d.Blocked):
            project.invoke([sys.executable, '-c', 'pass'])
        self.home.chmod(0o755)
        with self.assertRaises(d.Blocked):
            d.Project('fixture')

    def test_symlinked_state_files_leave_targets_untouched(self):
        project = self.project()
        target = self.directory / 'target'
        target.write_text('untouched')
        target.chmod(0o600)
        for path, operation in ((project.state, lambda: d.atomic(project.state, {})),
                                (project.pause, project.set_paused),
                                (project.pause, lambda: d.remove_private(project.pause)),
                                (project.log, lambda: project.invoke([sys.executable, '-c', 'pass'])),
                                (self.home / 'lock', lambda: self.take_lock(project))):
            with self.subTest(path=path, operation=operation):
                path.symlink_to(target)
                with self.assertRaises((d.Blocked, OSError)):
                    operation()
                self.assertTrue(path.is_symlink())
                self.assertEqual(target.read_text(), 'untouched')
                path.unlink()
        (self.home / 'state.tmp').symlink_to(target)
        d.atomic(project.state, {'status': 'safe'})
        self.assertEqual(target.read_text(), 'untouched')

    def test_cli_reads_private_logs_and_rejects_symlinked_config(self):
        project = self.project()
        with d.private_open(project.log, 'a') as stream:
            stream.write('synthetic log line\n')
        result = self.cli('logs', 'fixture')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'synthetic log line\n')
        config = self.home / 'config.json'
        target = self.directory / 'original-config.json'
        config.rename(target)
        config.symlink_to(target)
        result = self.cli('status', 'fixture')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertEqual(d.load(target), self.config)

    @staticmethod
    def take_lock(project):
        with project.lock():
            pass
