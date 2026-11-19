"""Offline tests using real subprocess sessions and synthetic child processes."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import signal
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import devloop as d


PROCESS_GROUP = """
import os, signal, sys, time
from pathlib import Path

child = os.fork()
if child == 0:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(30)
    sys.exit()
ready = Path(sys.argv[1])
ready.with_suffix('.tmp').write_text(f'{os.getpid()} {child}')
ready.with_suffix('.tmp').replace(ready)
if sys.argv[2] == 'stay':
    time.sleep(30)
"""


class CancellationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.start_patch('ROOT', root)
        self.start_patch('STOP', False)
        home = root / 'fixture'
        home.mkdir(mode=0o700)
        config = d.load(Path(__file__).resolve().parents[1] / 'examples/jobstein.json')
        d.atomic(home / 'config.json', config)
        self.project = d.Project('fixture')
        self.ready = root / 'ready'

    def start_patch(self, name, value):
        override = patch.object(d, name, value)
        override.start()
        self.addCleanup(override.stop)

    def command(self, mode='stay'):
        return [sys.executable, '-c', PROCESS_GROUP, str(self.ready), mode]

    def wait_ready(self):
        deadline = time.monotonic() + 3
        while not self.ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(self.ready.exists(), 'subprocess group did not start')

    @staticmethod
    def process_running(pid):
        try:
            return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0] not in ('Z', 'X')
        except (FileNotFoundError, ProcessLookupError):
            return False

    def assert_group_stopped(self):
        self.wait_ready()
        leader, child = map(int, self.ready.read_text().split())
        deadline = time.monotonic() + 2
        while any(map(self.process_running, (leader, child))) and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse(self.process_running(leader), 'subprocess leader survived')
        self.assertFalse(self.process_running(child), 'subprocess descendant survived')

    def test_timeout_kills_descendant_after_leader_exits(self):
        with self.assertRaisesRegex(d.Blocked, 'timed out'):
            self.project.invoke(self.command('exit'), timeout=1.5)
        self.assert_group_stopped()

    def test_pause_cancels_active_build_and_preserves_checkout(self):
        self.project.repo.mkdir()
        marker = self.project.repo / 'synthetic-edit'
        marker.write_text('keep this edit')

        def pause():
            self.wait_ready()
            self.project.set_paused()

        with ThreadPoolExecutor(1) as executor, self.project.lock():
            trigger = executor.submit(pause)
            with self.assertRaisesRegex(d.Blocked, 'Pause requested'):
                self.project.invoke(self.command(), timeout=5, capture=False, untrusted=True)
            trigger.result()
        self.assert_group_stopped()
        self.assertEqual(marker.read_text(), 'keep this edit')
        self.assertEqual(self.project.invoke([sys.executable, '-c', 'print("ok")']), 'ok')

    def test_stop_signal_cancels_active_subprocess_group(self):
        def stop():
            self.wait_ready()
            os.kill(os.getpid(), signal.SIGTERM)

        previous = signal.signal(signal.SIGTERM, d.stop_handler)
        self.addCleanup(signal.signal, signal.SIGTERM, previous)
        with ThreadPoolExecutor(1) as executor:
            trigger = executor.submit(stop)
            with self.assertRaisesRegex(d.Blocked, 'Stop requested'):
                self.project.invoke(self.command(), timeout=5)
            trigger.result()
        self.assert_group_stopped()

    def test_polling_preserves_stdin_and_captured_stdout(self):
        child = 'import sys, time; print("start", flush=True); time.sleep(0.45); print(sys.stdin.read())'
        self.assertEqual(self.project.invoke([sys.executable, '-c', child], input_text='fixture'),
                         'start\nfixture')
