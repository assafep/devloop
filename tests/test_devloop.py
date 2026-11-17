import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import devloop as d

class Tests(unittest.TestCase):
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
            home=Path(tmp)/'jobstein';home.mkdir()
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
