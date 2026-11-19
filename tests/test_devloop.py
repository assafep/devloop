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
        for path in ['src/cv.pdf','src/secrets/key','src/.env','.github/workflows/ci.yml','build.gradle.kts']:
            with self.assertRaises(d.Blocked):d.validate_paths([path],['src/','README.md'])
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

if __name__=='__main__':unittest.main()
