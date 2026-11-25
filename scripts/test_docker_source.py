#!/usr/bin/env python3
"""Three offline regressions for the workflow's actual source-selection step."""
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap

workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/docker.yml').read_text()
section = workflow.split('      - name: Resolve source revision\n', 1)[1].split('\n      - ', 1)[0]
script = textwrap.dedent(section.split('        run: |\n', 1)[1])

with tempfile.TemporaryDirectory() as directory:
    repo = Path(directory)

    def git(*args):
        return subprocess.check_output(
            ['git', '-C', directory, *args], text=True, stderr=subprocess.DEVNULL
        ).strip()

    git('init', '-b', 'testing')
    git('config', 'user.name', 'Test')
    git('config', 'user.email', 'test@example.com')
    for name in ('Dockerfile', 'scripts/test_frontend_release.py', 'scripts/test_docker_shutdown.sh'):
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    git('add', '.')
    git('commit', '-m', 'supported historical source')
    historical = git('rev-parse', 'HEAD')
    git('commit', '--allow-empty', '-m', 'selected branch HEAD')
    event_head = git('rev-parse', 'HEAD')
    git('checkout', '-b', 'other', historical)
    git('commit', '--allow-empty', '-m', 'other branch only')
    other = git('rev-parse', 'HEAD')

    for label, requested, expected in (
        ('blank uses selected event HEAD', '', event_head),
        ('selected branch historical SHA succeeds', historical, historical),
        ('other branch SHA is rejected', other, None),
    ):
        git('checkout', '--detach', event_head)
        output = repo / 'github-output'
        output.write_text('')
        env = {**os.environ, 'GITHUB_EVENT_NAME': 'workflow_dispatch',
               'GITHUB_REF': 'refs/heads/testing', 'GITHUB_SHA': event_head,
               'REQUESTED_SHA': requested, 'GITHUB_OUTPUT': str(output)}
        result = subprocess.run(
            ['bash', '-e', '-o', 'pipefail', '-c', script],
            cwd=repo, env=env, text=True, capture_output=True,
        )
        if expected is None:
            assert result.returncode != 0, label
            assert 'selected branch history at dispatch' in result.stdout, result.stdout
            assert git('rev-parse', 'HEAD') == event_head, label
            assert output.read_text() == '', label
        else:
            assert result.returncode == 0, result.stdout + result.stderr
            assert git('rev-parse', 'HEAD') == expected, label
            assert output.read_text() == f'revision={expected}\n', label
        print(f'PASS: {label}')
