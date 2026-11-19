import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import devloop as d

class Tests(unittest.TestCase):
    def test_subprocess_environment(self):
        # Real offline child process, with synthetic credentials only.
        with tempfile.TemporaryDirectory() as tmp:
            p = d.Project.__new__(d.Project)
            p.log = Path(tmp) / 'activity.log'
            p._iteration_active = False
            env = {'PATH': os.defpath, 'HOME': tmp, 'LANG': 'C',
                   'CODEX_HOME': tmp, 'GH_TOKEN': 'synthetic',
                   'GITHUB_TOKEN': 'synthetic', 'CUSTOM_PUBLICATION_SECRET': 'synthetic',
                   'SSH_AUTH_SOCK': '/synthetic/socket', 'GIT_ASKPASS': 'synthetic',
                   'PYTHONPATH': '/synthetic', 'LD_PRELOAD': '',
                   'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'alias.test',
                   'GIT_CONFIG_VALUE_0': 'synthetic'}
            command = [sys.executable, '-c',
                       'import json, os; print(json.dumps(dict(os.environ)))']
            with patch.dict(os.environ, env, clear=True):
                for options in ({'agent': True}, {'untrusted': True}):
                    with self.subTest(options=options):
                        child = json.loads(p.invoke(command, **options))
                        for key in env.keys() - {'PATH', 'HOME', 'LANG', 'CODEX_HOME'}:
                            self.assertNotIn(key, child)
                        self.assertEqual(child['HOME'], tmp)
                        self.assertEqual(child['PATH'], os.defpath)
                        self.assertEqual(child['GIT_TERMINAL_PROMPT'], '0')
                        self.assertEqual(child.get('CODEX_HOME'),
                                         tmp if options.get('agent') else None)
                trusted = json.loads(p.invoke(command))
                self.assertEqual(trusted['GH_TOKEN'], 'synthetic')

    def test_exact_ci(self):
        self.assertEqual(d.classify_ci([], 'a'), ('not-found', None))
        runs=[dict(headSha='b',event='push',status='completed',conclusion='success',databaseId=1)]
        self.assertEqual(d.classify_ci(runs,'a'),('not-found',None))
        runs.append(dict(headSha='a',event='push',status='in_progress',conclusion='',databaseId=2))
        self.assertEqual(d.classify_ci(runs,'a'),('pending',2))
        runs[-1].update(status='completed',conclusion='failure')
        self.assertEqual(d.classify_ci(runs,'a'),('failure',2))
        runs[-1].update(conclusion='success')
        self.assertEqual(d.classify_ci(runs,'a'),('success',2))
        runs[-1].update(conclusion='cancelled')
        self.assertEqual(d.classify_ci(runs,'a'),('blocked-cancelled',2))
    def test_paths(self):
        d.validate_paths(['src/a.java','README.md'],['src/','README.md'])
        for path in ['src/cv.pdf', 'src/Secrets/key', 'src/.env.local', 'src/.env',
                     '.github/workflows/ci.yml', 'src/new\nline', 'src/back\\slash',
                     'src/../outside', 'build.gradle.kts']:
            with self.assertRaises(d.Blocked):d.validate_paths([path],['src/','README.md'])

    def test_staged_blob_checks(self):
        for blob, expected in (
            (b'\x00', 'binary'),
            (b'\xff', 'binary'),
            (b'Staged executable\x1b', 'control'),
            (b'-----BEGIN OPENSSH PRIVATE KEY-----', 'credential'),
            (b'ghp_' + b'x' * 36, 'credential'),
            (b'ASIA' + b'B' * 16, 'credential'),
        ):
            with self.subTest(expected=expected), self.assertRaisesRegex(d.Blocked, expected):
                d.validate_staged_blob(blob)
        for blob in (b'', b'line\r\n\ttext\n', 'Café\n'.encode(), b'Document the ghp_ prefix.'):
            d.validate_staged_blob(blob)
    def test_atomic_and_lock(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(d,'ROOT',Path(tmp)):
            home=Path(tmp)/'jobstein';home.mkdir(mode=0o700)
            cfg=d.load(Path(__file__).resolve().parents[1]/'examples/jobstein.json')
            d.atomic(home/'config.json',cfg)
            p=d.Project('jobstein')
            with p.lock():
                with self.assertRaises(d.Blocked):
                    with p.lock():pass
            with p.lock():pass
            self.assertFalse(cfg['auto_push'])
    def test_latest_run(self):
        base=dict(headSha='a',event='push',status='completed',conclusion='success',databaseId=1,createdAt='2026-01-01')
        newer=dict(base,databaseId=2,createdAt='2026-01-02',conclusion='failure')
        self.assertEqual(d.classify_ci([base,newer],'a'),('failure',2))

    def test_ci_failure_log_redacts_credentials_and_bounds_untrusted_text(self):
        raw = 'Authorization: Bearer abc123\nsecret=private-value\nGH_TOKEN=ghp_example\n' + ('x' * 20000)
        result = d.redact_ci_log(raw)
        self.assertNotIn('abc123', result)
        self.assertNotIn('private-value', result)
        self.assertNotIn('ghp_example', result)
        self.assertLessEqual(len(result), d.CI_LOG_MAX_CHARS + len('\n[CI failure log truncated]'))
        self.assertIn('[CI failure log truncated]', result)

    def test_ci_failure_log_retrieval_is_bounded_and_fails_closed(self):
        project = d.Project.__new__(d.Project)
        project.cfg = {'repository': 'synthetic/repo'}
        project.invoke = lambda argv, **_: 'line\nsecret=hidden'
        self.assertEqual(project.ci_failure_log(42), 'line\nsecret=[REDACTED]')
        project.invoke = lambda argv, **_: (_ for _ in ()).throw(d.Blocked('offline'))
        self.assertIn('unavailable', project.ci_failure_log(42))

    def test_ci_failure_log_missing_run_id_is_safe(self):
        project = d.Project.__new__(d.Project)
        project.cfg = {'repository': 'synthetic/repo'}
        self.assertIn('no run ID', project.ci_failure_log(None))

    def test_ci_budget_expires_without_another_lookup(self):
        project = d.Project.__new__(d.Project)
        project.cfg = {'ci_timeout_seconds': 3, 'ci_poll_seconds': 60}
        project.is_paused = lambda: False
        simulated_time = [0]

        def wait(seconds, paused):
            self.assertEqual(seconds, 3)
            self.assertFalse(paused())
            simulated_time[0] += seconds

        with patch.object(d, 'STOP', False), \
                patch.object(d.time, 'monotonic', side_effect=lambda: simulated_time[0]), \
                patch.object(d, 'wait', side_effect=wait), \
                patch.object(project, 'ci', return_value=('pending', 17)) as ci, \
                patch.object(project, 'record'):
            self.assertEqual(project.wait_ci('a' * 40), ('pending', 17))
        ci.assert_called_once_with('a' * 40, timeout=3)

    def test_ci_budget_cancels_stalled_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = d.Project.__new__(d.Project)
            project.log = Path(tmp) / 'activity.log'
            project._iteration_active = False
            project.cfg = {'repository': 'synthetic/project', 'branch': 'main',
                           'workflow': 'ci.yml', 'ci_timeout_seconds': 1, 'ci_poll_seconds': 60}
            project.is_paused = lambda: False
            real_invoke = project.invoke

            def offline_ci(argv, *, timeout):
                self.assertEqual(argv[:3], ['gh', 'run', 'list'])
                self.assertIn('a' * 40, argv)
                self.assertLessEqual(timeout, 1)
                return real_invoke([sys.executable, '-c', 'import time; time.sleep(10)'],
                                   timeout=timeout)

            with patch.object(d, 'STOP', False), patch.object(project, 'invoke', side_effect=offline_ci):
                self.assertEqual(project.wait_ci('a' * 40), ('pending', None))

if __name__=='__main__':unittest.main()
