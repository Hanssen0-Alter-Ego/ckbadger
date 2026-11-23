#!/usr/bin/env python3
"""Exercise workflow shell entry points with fake cargo/docker; never publish.

Optionally pass a compiled crates/cli/build.rs executable to test the actual
Rust version generator against real temporary Git commits as well.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
STEPS = yaml.safe_load((ROOT / '.github/workflows/docker.yml').read_text())['jobs']['build']['steps']
BUILD = next(s['run'] for s in STEPS if s.get('name') == 'Build release binary')
VERIFY = next(s['run'] for s in STEPS if s.get('name') == 'Verify Docker binary version')
GENERATOR = str(Path(sys.argv.pop()).resolve()) if len(sys.argv) == 2 else None
SHA = '0123456789abcdef0123456789abcdef01234567'

class WorkflowTests(unittest.TestCase):
    def run_step(self, script, *, supported=True, event='workflow_dispatch', output=None):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'crates/cli').mkdir(parents=True)
            (root / 'crates/cli/build.rs').write_text((ROOT / 'crates/cli/build.rs').read_text() if supported else 'fn main() {}')
            for name, body in {'cargo': 'printf "cargo:%s" "${CKBADGER_DOCKER_SHA-unset}"', 'docker': 'printf "%s\\n" "$FAKE_VERSION"'}.items():
                p = root / name
                p.write_text('#!/bin/sh\n' + body + '\n')
                p.chmod(0o755)
            env = {**os.environ, 'PATH': d + ':' + os.environ['PATH'], 'GITHUB_EVENT_NAME': event,
                   'SOURCE_REVISION': SHA, 'CKBADGER_DOCKER_SHA': 'inherited-wrong-value',
                   'FAKE_VERSION': output or 'ckbadger sha-' + SHA[:12]}
            return subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', script], cwd=d, env=env, capture_output=True, text=True)

    def test_manual_passes_selected_full_sha(self):
        r = self.run_step(BUILD)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, 'cargo:' + SHA)

    def test_old_checkout_fails_before_cargo(self):
        r = self.run_step(BUILD, supported=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn('cargo:', r.stdout)

    def test_release_clears_override_even_with_old_source(self):
        r = self.run_step(BUILD, supported=False, event='push')
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, 'cargo:unset')

    def test_exact_container_version(self):
        self.assertEqual(self.run_step(VERIFY).returncode, 0)

    def test_mislabeled_or_ignored_override_rejected(self):
        for output in ['ckbadger 0.8.2@0123456789ab', 'ckbadger sha-ffffffffffff', 'ckbadger sha-' + SHA[:12] + ' extra']:
            with self.subTest(output=output):
                self.assertNotEqual(self.run_step(VERIFY, output=output).returncode, 0)

    def test_release_version_unchanged(self):
        self.assertEqual(self.run_step(VERIFY, event='push', output='ckbadger 0.8.2@abc').returncode, 0)

@unittest.skipUnless(GENERATOR, 'pass compiled build.rs to exercise Rust generator')
class GeneratorTests(unittest.TestCase):
    def test_real_checkout_and_override_transitions(self):
        with tempfile.TemporaryDirectory() as d:
            def git(*args):
                return subprocess.check_output(['git', '-C', d, *args], text=True).strip()
            git('init', '-b', 'main')
            git('-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '--allow-empty', '-m', 'first')
            first = git('rev-parse', 'HEAD')
            git('-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '--allow-empty', '-m', 'second')
            second = git('rev-parse', 'HEAD')
            def run(sha=None):
                env = {**os.environ, 'CARGO_MANIFEST_DIR': d, 'CARGO_PKG_VERSION': '0.8.2'}
                env.pop('CKBADGER_DOCKER_SHA', None)
                if sha is not None:
                    env['CKBADGER_DOCKER_SHA'] = sha
                return subprocess.run([GENERATOR], env=env, capture_output=True, text=True)
            self.assertIn('CKBADGER_BUILD_VERSION=0.8.2@' + second[:12], run().stdout)
            self.assertIn('CKBADGER_BUILD_VERSION=sha-' + second[:12], run(second).stdout)
            for invalid in [first, '', second[:12], 'x' * 40]:
                self.assertNotEqual(run(invalid).returncode, 0)
            git('checkout', '--detach', first)
            self.assertNotEqual(run(second).returncode, 0)
            self.assertIn('CKBADGER_BUILD_VERSION=sha-' + first[:12], run(first).stdout)
            self.assertIn('CKBADGER_BUILD_VERSION=0.8.2@' + first[:12], run().stdout)
            self.assertIn('cargo:rerun-if-env-changed=CKBADGER_DOCKER_SHA', run().stdout)

if __name__ == '__main__':
    unittest.main()
