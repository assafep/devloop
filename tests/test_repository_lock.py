"""Cross-process tests for repository locks using only local fixtures."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
import unittest


SOURCE = Path(__file__).resolve().parents[1]
OFFLINE_ITERATION = """
import os, sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import devloop

os.umask(0o077)
project = devloop.Project(sys.argv[2])

def doctor():
    if len(sys.argv) > 3:
        Path(sys.argv[3]).touch()
        sys.stdin.read()

project.doctor = doctor
project.checkout = lambda: 'a' * 40
project.wait_ci = lambda head: ('blocked-fixture', None)
project.iteration()
"""


class RepositoryLockTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.env = dict(os.environ, DEVLOOP_HOME=str(self.root / 'state'), PATH='')
        self.add_project('first', 'Synthetic/Project')
        self.add_project('alias', 'synthetic/project', branch='review')
        self.add_project('unrelated', 'Other/Project')

    def add_project(self, name, repository, branch='main'):
        config = json.loads((SOURCE / 'examples/jobstein.json').read_text())
        config.update(repository=repository, branch=branch, auto_push=False)
        path = self.root / f'{name}.json'
        path.write_text(json.dumps(config))
        result = self.cli('add', name, str(path))
        self.assertEqual(result.returncode, 0, result.stderr)

    def cli(self, *args):
        return subprocess.run([sys.executable, '-B', str(SOURCE / 'devloop.py'), *args],
                              env=self.env, capture_output=True, text=True, timeout=5)

    def offline_command(self, name, *args):
        return [sys.executable, '-B', '-c', OFFLINE_ITERATION, str(SOURCE), name, *args]

    @contextmanager
    def active_iteration(self):
        ready = self.root / 'ready'
        with subprocess.Popen(self.offline_command('first', str(ready)), env=self.env,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True) as process:
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(ready.exists(), 'first iteration did not reach preflight')
                yield process
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)

    def assert_can_run_offline(self, name):
        result = subprocess.run(self.offline_command(name), env=self.env,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'ci-blocked-fixture')

    def test_alias_conflicts_across_case_and_branch_but_other_repo_can_run(self):
        with self.active_iteration() as holder:
            result = self.cli('run-once', 'alias')
            self.assertEqual(result.returncode, 1, result.stderr)
            state = json.loads(result.stdout)
            self.assertEqual(state['status'], 'blocked')
            self.assertIn('repository lock for synthetic/project', state['message'])
            alias = Path(self.env['DEVLOOP_HOME']) / 'alias'
            self.assertTrue((alias / 'paused').exists())
            self.assertFalse((alias / 'checkout').exists())
            self.assertFalse((alias / 'activity.log').exists())
            self.assert_can_run_offline('unrelated')
            output, errors = holder.communicate('', timeout=5)
            self.assertEqual(holder.returncode, 0, errors)
            self.assertEqual(json.loads(output)['status'], 'ci-blocked-fixture')
        self.assertEqual(self.cli('resume', 'alias').returncode, 0)
        self.assert_can_run_offline('alias')

    def test_lock_released_after_abrupt_runner_exit(self):
        locks = Path(self.env['DEVLOOP_HOME']) / '.repository-locks'
        with self.active_iteration() as holder:
            lock, = locks.iterdir()
            self.assertEqual(stat.S_IMODE(locks.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(lock.stat().st_mode), 0o600)
            inode = lock.stat().st_ino
            holder.kill()
            holder.communicate(timeout=5)
        self.assert_can_run_offline('alias')
        self.assertEqual(list(locks.iterdir()), [lock])
        self.assertEqual(lock.stat().st_ino, inode)

    def test_symlinked_repository_lock_directory_is_rejected(self):
        target = self.root / 'target'
        target.mkdir(mode=0o700)
        locks = Path(self.env['DEVLOOP_HOME']) / '.repository-locks'
        locks.symlink_to(target, target_is_directory=True)
        result = self.cli('run-once', 'first')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'blocked')
        self.assertEqual(list(target.iterdir()), [])
