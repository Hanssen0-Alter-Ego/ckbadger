#!/usr/bin/env python3
"""Offline tests of the actual Docker workflow shell steps. No image is published."""
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / '.github/workflows/docker.yml').read_text()


def step(name):
    section = WORKFLOW.split('      - name: ' + name + '\n', 1)[1]
    body = section.split('        run: |\n', 1)[1]
    lines = []
    for line in body.splitlines():
        if line.strip() and not line.startswith('          '):
            break
        lines.append(line)
    return textwrap.dedent('\n'.join(lines))


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.com')
        self.git('commit', '--allow-empty', '-m', 'pre Docker')
        self.old = self.git('rev-parse', 'HEAD')
        for name in ('Dockerfile', 'scripts/test_frontend_release.py', 'scripts/test_docker_shutdown.sh'):
            p = self.repo / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('main version\n')
        self.git('add', '.')
        self.git('commit', '-m', 'Docker support')
        self.historical = self.git('rev-parse', 'HEAD')
        self.git('commit', '--allow-empty', '-m', 'main advance')
        self.main = self.git('rev-parse', 'HEAD')
        self.git('update-ref', 'refs/remotes/origin/main', self.main)
        self.git('checkout', '-b', 'testing', self.historical)
        (self.repo / 'Dockerfile').write_text('branch Dockerfile\n')
        self.git('commit', '-am', 'branch support')
        self.branch = self.git('rev-parse', 'HEAD')
        self.git('update-ref', 'refs/remotes/origin/testing', self.branch)
        self.git('commit', '--allow-empty', '-m', 'unpublished')
        self.unpublished = self.git('rev-parse', 'HEAD')
        self.git('tag', 'tag-only', self.unpublished)
        self.git('update-ref', 'refs/remotes/another-fork/testing', self.unpublished)
        self.git('update-ref', 'refs/pull/123/head', self.unpublished)
        self.git('checkout', '--detach', self.main)

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], text=True, stderr=subprocess.DEVNULL).strip()

    def resolve(self, sha='', event='workflow_dispatch', ref='refs/heads/main', event_sha=None):
        self.output = self.root / 'output'
        self.output.write_text('')
        env = {**os.environ, 'GITHUB_OUTPUT': str(self.output), 'GITHUB_EVENT_NAME': event,
               'GITHUB_REF': ref, 'GITHUB_SHA': event_sha or self.main, 'REQUESTED_SHA': sha}
        return subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', step('Resolve source revision')],
                              cwd=self.repo, env=env, capture_output=True, text=True)

    def assert_revision(self, result, sha):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git('rev-parse', 'HEAD'), sha)
        self.assertEqual(self.output.read_text(), 'revision=' + sha + '\n')

    def test_empty_uses_selected_main_head(self):
        self.assert_revision(self.resolve(), self.main)

    def test_explicit_main(self):
        self.assert_revision(self.resolve(self.main), self.main)

    def test_branch_only_abbreviated_uppercase_and_own_dockerfile(self):
        self.assert_revision(self.resolve(self.branch[:12].upper(), ref='refs/heads/testing', event_sha=self.branch), self.branch)
        self.assertEqual((self.repo / 'Dockerfile').read_text(), 'branch Dockerfile\n')

    def test_compatible_historical_source(self):
        self.assert_revision(self.resolve(self.historical), self.historical)

    def test_pre_docker_source_fails_clearly(self):
        r = self.resolve(self.old)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('lacks Dockerfile', r.stdout)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.old)
        self.assertEqual(self.output.read_text(), '')

    def test_each_missing_smoke_file_fails(self):
        for name in ('scripts/test_frontend_release.py', 'scripts/test_docker_shutdown.sh'):
            with self.subTest(name=name):
                self.git('checkout', '--detach', self.main)
                self.git('rm', name)
                self.git('commit', '-m', 'missing support')
                sha = self.git('rev-parse', 'HEAD')
                self.git('update-ref', 'refs/remotes/origin/missing-support', sha)
                r = self.resolve(sha, ref='refs/heads/missing-support', event_sha=sha)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn('lacks ' + name, r.stdout)

    def test_local_tag_other_remote_and_pr_ref_are_not_branches(self):
        r = self.resolve(self.unpublished)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('selected branch history at dispatch', r.stdout)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.main)

    def test_other_pushed_branch_is_not_eligible(self):
        r = self.resolve(self.branch)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.main)

    def test_empty_uses_selected_branch_event_head_even_if_ref_moves(self):
        self.git('update-ref', 'refs/remotes/origin/testing', self.unpublished)
        self.assert_revision(self.resolve(ref='refs/heads/testing', event_sha=self.branch), self.branch)
        self.assertNotEqual(self.resolve(self.unpublished, ref='refs/heads/testing', event_sha=self.branch).returncode, 0)

    def test_selected_branch_history(self):
        self.assert_revision(self.resolve(self.historical, ref='refs/heads/testing', event_sha=self.branch), self.historical)

    def test_invalid_or_unknown_sha(self):
        for sha in ('main', '../main', 'a' * 6, 'f' * 41, 'f' * 40, '$(touch bad)'):
            with self.subTest(sha=sha):
                self.assertNotEqual(self.resolve(sha).returncode, 0)
                self.assertEqual(self.git('rev-parse', 'HEAD'), self.main)

    def test_manual_workflow_must_start_on_branch(self):
        r = self.resolve(self.branch, ref='refs/tags/v0.8.3', event_sha=self.branch)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('from a branch, not a tag', r.stdout)

    def test_non_manual_uses_original_checkout(self):
        self.git('checkout', '--detach', self.old)
        for event, ref in [('pull_request', 'refs/pull/1/merge'), ('push', 'refs/tags/v0.8.3')]:
            with self.subTest(event=event):
                self.assert_revision(self.resolve('invalid ignored', event, ref), self.old)

    def test_packaging_labels_use_selected_source(self):
        self.assert_revision(self.resolve(self.branch, ref='refs/heads/testing', event_sha=self.branch), self.branch)
        binary = self.repo / 'target/release/ckbadger'
        binary.parent.mkdir(parents=True)
        binary.write_text('branch binary')
        shim = self.root / 'bin'
        shim.mkdir()
        docker = shim / 'docker'
        docker.write_text('#!/usr/bin/env python3\nimport json,sys\nfrom pathlib import Path\n'
                          'assert Path("Dockerfile").read_text()=="branch Dockerfile\\n"\n'
                          'assert (Path(sys.argv[-1])/"ckbadger").read_text()=="branch binary"\n'
                          'print(json.dumps(sys.argv[1:]))\n')
        docker.chmod(0o755)
        import json
        env = {**os.environ, 'PATH': str(shim) + ':' + os.environ['PATH'],
               'SOURCE_REVISION': self.branch, 'SOURCE_URL': 'https://github.com/example/repo',
               'GITHUB_REF_NAME': 'main', 'GITHUB_EVENT_NAME': 'workflow_dispatch', 'TMPDIR': str(self.root)}
        r = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', step('Package Docker image')],
                           cwd=self.repo, env=env, text=True, capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        args = json.loads(r.stdout)
        self.assertIn('org.opencontainers.image.version=sha-' + self.branch[:12], args)
        self.assertIn('org.opencontainers.image.revision=' + self.branch, args)
        self.assertEqual(args[args.index('--file') + 1], 'Dockerfile')


class PublishTests(unittest.TestCase):
    def test_publish_job_guard(self):
        from types import SimpleNamespace
        section = WORKFLOW.split('  publish:', 1)[1]
        expression = section.split('    if: >-\n', 1)[1].split('    needs:', 1)[0].strip()
        expression = expression.replace('&&', 'and').replace('||', 'or').replace('\n', ' ')
        cases = [
            ('workflow_dispatch', 'branch', 'refs/heads/testing', True),
            ('workflow_dispatch', 'branch', 'refs/heads/main', True),
            ('workflow_dispatch', 'tag', 'refs/tags/v0.8.3', False),
            ('pull_request', 'branch', 'refs/pull/1/merge', False),
            ('push', 'branch', 'refs/heads/testing', False),
            ('push', 'tag', 'refs/tags/v0.8.3', True),
        ]
        for event, kind, ref, expected in cases:
            with self.subTest(event=event, ref=ref):
                actual = eval(expression, {'__builtins__': {}}, {
                    'github': SimpleNamespace(event_name=event, ref_type=kind, ref=ref),
                    'startsWith': lambda value, prefix: value.startswith(prefix),
                })
                self.assertEqual(actual, expected)

    def publish(self, mode):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        sha = '0123456789abcdef0123456789abcdef01234567'
        shim = root / 'bin'
        shim.mkdir()
        for command in ('docker', 'skopeo'):
            p = shim / command
            p.write_text(r"""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
root = Path(os.environ['FIXTURE_ROOT'])
args = sys.argv[1:]
with (root / 'calls').open('a') as f:
    f.write(json.dumps([Path(sys.argv[0]).name, *args]) + '\n')
assert not any(':latest' in arg or ':v0.' in arg for arg in args)
mode = os.environ['FIXTURE_MODE']
if Path(sys.argv[0]).name == 'skopeo':
    revision = os.environ['SOURCE_REVISION'] if mode == 'reuse' else 'f' * 40
    print(json.dumps({'Labels': {'org.opencontainers.image.revision': revision}}))
elif args[0] == 'login':
    sys.stdin.read()
elif args[:3] == ['buildx', 'imagetools', 'inspect']:
    if mode != 'new' or (root / 'pushed').exists():
        print('sha256:' + 'a' * 64)
    else:
        print('ERROR: ' + args[-1] + ': not found', file=sys.stderr)
        sys.exit(1)
elif args[0] == 'push':
    (root / 'pushed').touch()
elif args[0] not in ('load', 'tag'):
    raise AssertionError(args)
""")
            p.chmod(0o755)
        env = {**os.environ, 'PATH': str(shim) + ':' + os.environ['PATH'],
               'FIXTURE_ROOT': str(root), 'FIXTURE_MODE': mode, 'SOURCE_REVISION': sha,
               'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_REF': 'refs/heads/testing',
               'GITHUB_REF_NAME': 'testing', 'GITHUB_REPOSITORY': 'Example/Repo',
               'GITHUB_ACTOR': 'fixture', 'GHCR_TOKEN': 'not-a-real-token',
               'RUNNER_TEMP': str(root), 'GITHUB_STEP_SUMMARY': str(root / 'summary')}
        result = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', step('Push tested release image')],
                                env=env, text=True, capture_output=True)
        import json
        calls = [json.loads(line) for line in (root / 'calls').read_text().splitlines()]
        return result, calls

    def test_branch_dispatch_pushes_only_sha_image(self):
        result, calls = self.publish('new')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(['docker', 'push', 'ghcr.io/example/repo:sha-0123456789ab'], calls)
        self.assertEqual(sum(c[:2] == ['docker', 'push'] for c in calls), 1)

    def test_existing_sha_is_reused_without_push(self):
        result, calls = self.publish('reuse')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(any(c[:2] == ['docker', 'push'] for c in calls))

    def test_sha_collision_is_rejected_without_push(self):
        result, calls = self.publish('collision')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('different or unknown source revision', result.stderr)
        self.assertFalse(any(c[:2] == ['docker', 'push'] for c in calls))


if __name__ == '__main__':
    unittest.main()
