"""Offline build isolation tests with synthetic filesystem and network fixtures."""

import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
import devloop as d


class BuildIsolationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for setting, value in (('ROOT', self.root / 'runner-state'), ('STOP', False)):
            override = patch.object(d, setting, value)
            override.start()
            self.addCleanup(override.stop)
        settings = dict(d.load(SOURCE / 'examples/jobstein.json'), test_isolation='bubblewrap',
                        test_command=['/usr/bin/true'])
        d.atomic(d.project_home('fixture') / 'config.json', settings)
        self.project = d.Project('fixture')
        self.project.repo.mkdir()
        (self.project.repo / '.git').mkdir()

    def test_missing_sandbox_blocks_without_starting_host_command(self):
        with patch.object(d.shutil, 'which', return_value=None), \
                patch.object(self.project, 'invoke') as invoke:
            with self.assertRaisesRegex(d.Blocked, 'requires a system bwrap'):
                self.project.run_test()
            with self.assertRaisesRegex(d.Blocked, 'requires a system bwrap'):
                self.project.doctor()
        invoke.assert_not_called()

    def test_sandbox_failure_is_not_retried_on_host(self):
        self.project.cfg['test_command'] = ['./test', '--unshare-net']
        unavailable = d.Blocked('Synthetic sandbox startup failure')
        with patch.object(d.shutil, 'which', return_value='/usr/bin/bwrap'), \
                patch.object(self.project, 'invoke', side_effect=unavailable) as invoke:
            with self.assertRaisesRegex(d.Blocked, 'Synthetic sandbox startup failure'):
                self.project.run_test()
        command, = invoke.call_args.args
        self.assertEqual(command[0], '/usr/bin/bwrap')
        self.assertEqual(command[-3:], ['--', './test', '--unshare-net'])
        self.assertIn('--clearenv', command)
        self.assertIn('--unshare-net', command[:-3])
        self.assertEqual(invoke.call_count, 1)
        self.assertTrue(invoke.call_args.kwargs['stream_to_log'])

    def test_dependency_symlink_is_rejected_before_start(self):
        (self.project.home / 'test-dependencies').symlink_to(self.root, target_is_directory=True)
        with patch.object(d.shutil, 'which', return_value='/usr/bin/bwrap'), \
                patch.object(self.project, 'invoke') as invoke:
            with self.assertRaises(OSError):
                self.project.run_test()
        invoke.assert_not_called()

    def require_working_sandbox(self):
        if not Path('/usr/bin/python3').is_file():
            self.skipTest('System Python is unavailable inside Bubblewrap')
        bwrap = shutil.which('bwrap', path='/usr/bin:/bin')
        if not bwrap:
            self.skipTest('System Bubblewrap executable is unavailable')
        probe = subprocess.run(
            [bwrap, '--unshare-user', '--disable-userns', '--unshare-pid', '--unshare-net',
             '--unshare-ipc', '--unshare-uts', '--ro-bind', '/usr', '/usr',
             '--ro-bind-try', '/lib', '/lib', '--ro-bind-try', '/lib64', '/lib64',
             '--proc', '/proc', '--dev', '/dev', '--', '/usr/bin/true'],
            cwd='/', env={}, capture_output=True, text=True, timeout=5)
        if probe.returncode:
            self.skipTest(f'Host does not support the Bubblewrap profile: {probe.stderr.strip()}')

    def test_real_build_cannot_read_host_credentials_or_runner_state(self):
        self.require_working_sandbox()
        host_home = self.root / 'host-home'
        host_home.mkdir()
        secrets = []
        for relative in ('.config/gh/hosts.yml', '.git-credentials', '.codex/auth.json'):
            credential = host_home / relative
            credential.parent.mkdir(parents=True, exist_ok=True)
            credential.write_text('synthetic host credential\n')
            secrets.append(str(credential))
        self.project.log.write_text('synthetic runner log credential\n')
        self.project.log.chmod(0o600)
        secrets.extend((str(self.project.log), str(self.project.home / 'config.json')))
        git_config = self.project.repo / '.git/config'
        git_config.write_text('synthetic repository-local credential\n')
        (self.project.repo / 'outside-link').symlink_to(secrets[0])
        (self.project.repo / 'source.txt').write_text('synthetic source\n')
        deps = self.project.home / 'test-dependencies'
        deps.mkdir(mode=0o700)
        (deps / 'tool.txt').write_text('synthetic dependency\n')
        code = '''
import os, socket, stat, sys
from pathlib import Path
for filename in sys.argv[2:]:
    try:
        Path(filename).read_bytes()
    except OSError:
        pass
    else:
        raise AssertionError('a synthetic credential was visible')
assert Path.cwd() == Path('/workspace')
assert Path('source.txt').read_text() == 'synthetic source\\n'
assert os.environ['HOME'] == '/tmp/home'
assert 'GH_TOKEN' not in os.environ and 'CODEX_HOME' not in os.environ
assert stat.S_ISFIFO(os.fstat(1).st_mode) and stat.S_ISFIFO(os.fstat(2).st_mode)
assert Path('/dependencies/tool.txt').read_text() == 'synthetic dependency\\n'
try:
    Path('/dependencies/tool.txt').write_text('modified')
except OSError:
    pass
else:
    raise AssertionError('dependency mount was writable')
with socket.socket() as client:
    client.settimeout(1)
    assert client.connect_ex(('127.0.0.1', int(sys.argv[1]))) != 0
Path.home().joinpath('scratch').write_text('scratch')
Path('build-output.txt').write_text('synthetic output\\n')
print('isolated test completed')
'''
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            self.project.cfg['test_command'] = [
                '/usr/bin/python3', '-c', code, str(listener.getsockname()[1]),
                *secrets, '.git/config', 'outside-link',
            ]
            env = {'HOME': str(host_home), 'CODEX_HOME': str(host_home / '.codex'),
                   'GH_TOKEN': 'synthetic environment secret'}
            with patch.dict(os.environ, env):
                self.project.run_test()
        self.assertIn('isolated test completed', d.read_private(self.project.log))
        self.assertEqual((self.project.repo / 'build-output.txt').read_text(), 'synthetic output\n')
        self.assertEqual(git_config.read_text(), 'synthetic repository-local credential\n')
        self.assertEqual((deps / 'tool.txt').read_text(), 'synthetic dependency\n')
