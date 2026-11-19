"""Offline review-only iteration with real Git and synthetic CLI stand-ins."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import devloop as d


class ReviewIterationTests(unittest.TestCase):
    def test_review_iteration_restricts_environment_and_preserves_changes(self):
        git_exe = shutil.which('git')
        self.assertIsNotNone(git_exe, 'Git is required for offline integration tests')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / 'home'
            home.mkdir()
            bin_dir = root / 'bin'
            bin_dir.mkdir()
            remote = root / 'remote.git'
            seed = root / 'seed'
            secrets = {'GH_TOKEN': 'synthetic-publication-token',
                       'CUSTOM_PUBLICATION_SECRET': 'synthetic-secret',
                       'SSH_AUTH_SOCK': '/synthetic/socket',
                       'GIT_ASKPASS': '/synthetic/askpass',
                       'PYTHONPATH': '/synthetic/python'}
            env = {'HOME': str(home), 'PATH': str(bin_dir) + os.pathsep + os.defpath,
                   'GIT_CONFIG_NOSYSTEM': '1', 'GIT_TERMINAL_PROMPT': '0',
                   'CODEX_HOME': str(home / 'codex'), **secrets}

            def git(*args, cwd=None):
                return subprocess.run([git_exe, *args], cwd=cwd, env=env,
                                      text=True, capture_output=True, check=True).stdout.strip()

            def executable(name, body):
                path = bin_dir / name
                path.write_text('#!' + sys.executable + '\n' + body)
                path.chmod(0o700)

            git('config', '--global', 'user.name', 'Synthetic Tester')
            git('config', '--global', 'user.email', 'tester@example.invalid')
            git('init', '--bare', '--initial-branch=main', str(remote))
            git('init', '--initial-branch=main', str(seed))
            (seed / 'README.md').write_text('baseline\n')
            git('add', 'README.md', cwd=seed)
            git('commit', '-m', 'Synthetic baseline', cwd=seed)
            git('push', str(remote), 'main', cwd=seed)
            baseline = git('rev-parse', 'HEAD', cwd=seed)
            # Route only transport operations locally; all repository checks use real Git.
            executable('git', f'''import subprocess, sys
real_git = {git_exe!r}
remote = {str(remote)!r}
url = 'https://github.com/synthetic/project.git'
args = sys.argv[1:]
if args[0] == 'clone':
    assert url in args
    args[args.index(url)] = remote
    subprocess.run([real_git, *args], check=True)
    subprocess.run([real_git, '-C', args[-1], 'remote', 'set-url', 'origin', url], check=True)
elif args[0] == 'fetch':
    assert args == ['fetch', 'origin', 'main']
    subprocess.run([real_git, 'fetch', remote, 'main:refs/remotes/origin/main'], check=True)
elif args[0] in ('push', 'commit'):
    raise RuntimeError('Review-only iteration attempted publication')
else:
    sys.exit(subprocess.call([real_git, *args]))
''')
            executable('gh', '''import json, os, sys
from pathlib import Path
home = Path(os.environ['HOME'])
with (home / 'gh-calls.jsonl').open('a') as out:
    out.write(json.dumps({'args': sys.argv[1:], 'env': dict(os.environ)}) + '\\n')
if sys.argv[1:3] == ['run', 'list']:
    sha = sys.argv[sys.argv.index('--commit') + 1]
    print(json.dumps([dict(headSha=sha, event='push', status='completed',
                          conclusion='success', databaseId=1)]))
''')
            executable('codex', '''import json, os, sys
from pathlib import Path
if sys.argv[1] == 'exec':
    home = Path(os.environ['HOME'])
    home.joinpath('agent-prompt.txt').write_text(sys.stdin.read())
    home.joinpath('agent-env.json').write_text(json.dumps(dict(os.environ)))
    Path('README.md').write_text('synthetic agent change\\n')
    Path(sys.argv[sys.argv.index('--output-last-message') + 1]).write_text('Synthetic report')
''')
            build_code = (
                "import json, os; from pathlib import Path; "
                "assert Path('README.md').read_text() == 'synthetic agent change\\n'; "
                "Path(os.environ['HOME'], 'build-env.json').write_text(json.dumps(dict(os.environ)))"
            )
            state_root = root / 'state'
            project_home = state_root / 'fixture'
            project_home.mkdir(parents=True)
            cfg = d.load(Path(__file__).resolve().parents[1] / 'examples/jobstein.json')
            cfg.update(repository='synthetic/project', allowed_paths=['README.md'],
                       test_command=[sys.executable, '-c', build_code],
                       instructions='Make one synthetic change.', auto_push=False)
            d.atomic(project_home / 'config.json', cfg)
            with patch.dict(os.environ, env, clear=True), patch.object(d, 'ROOT', state_root), \
                    patch.object(d, 'STOP', False), contextlib.redirect_stdout(io.StringIO()):
                project = d.Project('fixture')
                project.iteration()

            for filename in ('agent-env.json', 'build-env.json'):
                child = d.load(home / filename)
                for key in secrets:
                    self.assertNotIn(key, child, (filename, key))
                self.assertEqual(child['GIT_TERMINAL_PROMPT'], '0')
            self.assertIn('CODEX_HOME', d.load(home / 'agent-env.json'))
            self.assertNotIn('CODEX_HOME', d.load(home / 'build-env.json'))
            calls = [json.loads(line) for line in (home / 'gh-calls.jsonl').read_text().splitlines()]
            self.assertTrue(all(call['env']['GH_TOKEN'] == secrets['GH_TOKEN'] for call in calls))
            ci_calls = [call['args'] for call in calls if call['args'][:2] == ['run', 'list']]
            self.assertEqual(len(ci_calls), 1)
            self.assertEqual(ci_calls[0][ci_calls[0].index('--commit') + 1], baseline)
            prompt = (home / 'agent-prompt.txt').read_text()
            self.assertIn(f'Base commit {baseline}. Required CI workflow result: success. Run ID: 1.', prompt)
            self.assertIn('git rev-parse HEAD matches the full base commit and stop if it differs', prompt)
            self.assertIn('Use the supplied result and run ID to satisfy the project instructions on checking base CI.', prompt)
            self.assertIn('Do not query GitHub again for this CI result.', prompt)
            self.assertEqual(d.load(project.state)['status'], 'review')
            self.assertTrue(project.pause.exists())
            self.assertEqual(git('rev-parse', 'HEAD', cwd=project.repo), baseline)
            self.assertEqual(git('--git-dir=' + str(remote), 'rev-parse', 'main'), baseline)
            self.assertEqual(git('diff', '--cached', '--name-only', cwd=project.repo), 'README.md')
            self.assertIn('+synthetic agent change', git('diff', '--cached', cwd=project.repo))
            self.assertEqual(git('diff', cwd=project.repo), '')
