"""Offline Linux installation and service commands in a temporary home."""

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]


class InstallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.home = root / 'home with spaces'
        self.home.mkdir()
        self.config_home = root / 'xdg config'
        self.state = root / 'state'
        self.calls = root / 'calls.jsonl'
        self.program = self.home / '.local/bin/devloop'
        self.unit = self.config_home / 'systemd/user/devloop@.service'
        bin_dir = root / 'bin'
        bin_dir.mkdir()
        systemctl = bin_dir / 'systemctl'
        systemctl.write_text('#!' + sys.executable + '\n' + '''
import json, os, sys
with open(os.environ['SYNTHETIC_SERVICE_CALLS'], 'a') as stream:
    stream.write(json.dumps(sys.argv[1:]) + '\\n')
sys.exit(int(os.environ.get('SYNTHETIC_SERVICE_EXIT', '0')))
''')
        systemctl.chmod(0o700)
        self.env = {'HOME': str(self.home), 'XDG_CONFIG_HOME': str(self.config_home),
                    'DEVLOOP_HOME': str(self.state), 'SYNTHETIC_SERVICE_CALLS': str(self.calls),
                    'PATH': str(bin_dir) + os.pathsep + os.defpath}

    def run_command(self, *args):
        return subprocess.run(args, env=self.env, text=True, capture_output=True, timeout=5)

    def service_calls(self):
        if not self.calls.exists():
            return []
        return [json.loads(line) for line in self.calls.read_text().splitlines()]

    def test_install_update_and_stop_preserve_project_state(self):
        result = self.run_command('bash', SOURCE / 'install.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.service_calls(), [['--user', 'daemon-reload']])
        self.assertEqual(self.program.read_bytes(), (SOURCE / 'devloop.py').read_bytes())
        self.assertEqual(self.unit.read_bytes(), (SOURCE / 'systemd/devloop@.service').read_bytes())
        self.assertEqual(stat.S_IMODE(self.program.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.unit.stat().st_mode), 0o600)

        result = self.run_command(self.program, 'add', 'fixture', SOURCE / 'examples/jobstein.json')
        self.assertEqual(result.returncode, 0, result.stderr)
        config = self.state / 'fixture/config.json'
        saved = config.read_bytes()
        before = self.program.stat().st_ino
        self.assertEqual(self.run_command('bash', SOURCE / 'install.sh').returncode, 0)
        self.assertNotEqual(self.program.stat().st_ino, before)
        self.assertEqual(list(self.program.parent.glob('devloop.tmp.*')), [])

        status = self.run_command(self.program, 'status', 'fixture')
        self.assertEqual(status.returncode, 0, status.stderr)
        project = json.loads(status.stdout)['project']
        self.assertFalse(project['auto_push'])
        self.assertEqual(Path(project['checkout']), config.parent / 'checkout')
        self.assertEqual(config.read_bytes(), saved)
        config.write_text('corrupt synthetic config')
        stopped = self.run_command(self.program, 'stop', 'fixture')
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        self.assertEqual(self.service_calls()[-1], ['--user', 'stop', 'devloop@fixture.service'])
        self.assertEqual(config.read_text(), 'corrupt synthetic config')

    def test_foreground_install_skips_user_service(self):
        result = self.run_command('bash', SOURCE / 'install.sh', '--no-service')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.program.exists())
        self.assertFalse(self.unit.exists())
        self.assertEqual(self.service_calls(), [])
        self.assertEqual(self.run_command(self.program, '--help').returncode, 0)

    def test_disable_failure_is_reported_and_preserves_configuration(self):
        self.state.mkdir()
        marker = self.state / 'fixture'
        marker.write_text('synthetic project state')
        self.env['SYNTHETIC_SERVICE_EXIT'] = '3'
        result = self.run_command('bash', SOURCE / 'uninstall.sh', 'fixture')
        self.assertEqual(result.returncode, 3)
        self.assertNotIn('Service disabled', result.stdout)
        self.assertEqual(self.service_calls(), [['--user', 'disable', '--now', 'devloop@fixture.service']])
        self.assertEqual(marker.read_text(), 'synthetic project state')
        self.env.pop('SYNTHETIC_SERVICE_EXIT')
        self.assertEqual(self.run_command('bash', SOURCE / 'uninstall.sh', 'fixture').returncode, 0)
        self.assertEqual(marker.read_text(), 'synthetic project state')
