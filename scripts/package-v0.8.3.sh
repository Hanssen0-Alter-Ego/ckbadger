#!/usr/bin/env bash
set -euo pipefail

readonly source_url=https://github.com/janx/ckbadger
readonly revision=da98312e44cdc3655a6be8b3373caf293631e35a
readonly image=ckbadger:0.8.3
readonly tarball=ckbadger-v0.8.3-linux-amd64.tar
readonly recipe_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)/packaging/ckbadger-v0.8.3"

fail() { printf '%s\n' "$*" >&2; exit 1; }
[[ $# = 1 ]] || fail "Usage: $0 OUTPUT_DIRECTORY"
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] ||
    fail 'Use a Linux x86_64 build host (Ubuntu 24.04 recommended).'
for dependency in git rustup node pnpm docker python3 sha256sum; do
    command -v "$dependency" >/dev/null || fail "Missing dependency: $dependency"
done
[[ $(node -p 'process.versions.node.split(".")[0]') == 24 ]] || fail 'Use Node.js 24.'
[[ $(pnpm --version) == 9.15.0 ]] || fail 'Use pnpm 9.15.0.'
mkdir -p -- "$1"
output="$(cd -- "$1" && pwd -P)"
[[ ! -e "$output/$tarball" && ! -e "$output/$tarball.sha256" ]] ||
    fail 'Remove or move the previous archive and checksum first.'

# Refuse changes to the fork recipe and shutdown fixture verified at d0e72b6355ef.
(
    cd -- "$recipe_dir"
    sha256sum --check --status <<'SUMS'
42ed01faa7cfb1443913d162bdb1b43f0c7cf2a9dbb4a0727b23350ee1856984  Dockerfile
5a24191f691a2a046cc7cd67b78ab741dc7dd98e3d283c023ddb8e33beeb9e2e  test_docker_shutdown.sh
SUMS
) || fail 'Packaging recipe or shutdown fixture differs from the pinned fork files.'

scratch="$(mktemp -d)"
trap 'rm -rf -- "$scratch"' EXIT
source="$scratch/source"
git init --quiet "$source"
# Public anonymous fetch; never use the PR branch or a mutable tag as source.
GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/false git -C "$source" \
    -c credential.helper= -c core.hooksPath=/dev/null fetch --no-tags --depth=1 \
    "$source_url.git" "$revision"
[[ $(git -C "$source" rev-parse FETCH_HEAD) == "$revision" ]] ||
    fail 'Upstream checkout did not resolve to the pinned release commit.'
git -C "$source" -c core.hooksPath=/dev/null checkout --quiet --detach "$revision"

(
    cd -- "$source/frontend"
    pnpm install --frozen-lockfile
    pnpm build
)
# Upstream v0.8.3 does not track Cargo.lock; mirror its release build.
(
    cd -- "$source"
    CARGO_TARGET_DIR="$scratch/target" rustup run stable cargo build --release -j 2 -p ckbadger
)

context="$scratch/docker"
mkdir -- "$context"
install -m 0755 "$scratch/target/release/ckbadger" "$context/ckbadger"
docker build --pull --platform linux/amd64 --file "$recipe_dir/Dockerfile" --tag "$image" \
    --label "org.opencontainers.image.source=$source_url" \
    --label "org.opencontainers.image.revision=$revision" \
    --label 'org.opencontainers.image.version=0.8.3' "$context"

# Check the actual packaged executable, not just the image tag or OCI labels.
actual="$(docker run --rm --network none "$image" --version)"
expected="ckbadger 0.8.3@${revision:0:12}"
[[ $actual == "$expected" ]] || fail "Expected $expected, got: $actual"
printf '%s\n' "$actual"

# Use the pinned release's own deterministic loopback frontend fixture and the
# verified fork's container/SIGINT fixture; neither needs a node or chain data.
launcher="$scratch/run-packaged-frontend"
cat > "$launcher" <<'SH'
#!/bin/sh
set -eu
exec docker run --rm --init --network host --user "$(id -u):$(id -g)" \
    --mount "type=bind,src=$PWD,dst=$PWD" ckbadger:0.8.3 "$@"
SH
chmod +x "$launcher"
python3 "$source/scripts/test_frontend_release.py" --binary "$launcher"
bash "$recipe_dir/test_docker_shutdown.sh" "$image"

(
    cd -- "$scratch"
    docker save --output "$tarball" "$image"
    sha256sum "$tarball" > "$tarball.sha256"
    sha256sum --check "$tarball.sha256"
)
mv -- "$scratch/$tarball" "$scratch/$tarball.sha256" "$output/"
printf 'Image archive: %s/%s\n' "$output" "$tarball"
