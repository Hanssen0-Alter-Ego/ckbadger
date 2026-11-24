# Package upstream CKBadger v0.8.3

PRs targeting the fork's `0.8.3` branch can build and test this image without
publishing anything. Merging into that branch in `Hanssen0/ckbadger` starts a
fresh push run that builds, tests, and publishes only
`ghcr.io/hanssen0/ckbadger:sha-da98312e44cd`. The `0.8.3` branch starts at the
[upstream v0.8.3 commit](https://github.com/janx/ckbadger/tree/da98312e44cdc3655a6be8b3373caf293631e35a).
The script fetches that exact commit separately, so adding packaging files
does not change the source being built. This leaves the `main` branch and the `latest` and `v0.8.3`
image tags untouched.

## Before merging

- If GitHub shows **Awaiting approval**, review the workflow changes, then choose
  **Approve workflows to run** on the PR. Wait for the packaging check to pass.
  It checks for `ckbadger 0.8.3@da98312e44cd` inside the Linux amd64 image and
  runs the release's own embedded frontend smoke test and a Docker shutdown
  fixture copied with the runtime recipe from the fork. Both copied files
  are checksum-pinned.
- Check that the existing GHCR package grants the `Hanssen0/ckbadger`
  repository **Write** in the package's **Package settings → Manage Actions
  access** (inherited access also works). The publish job uses GitHub's
  short-lived token. No personal token is needed.

After merging, confirm the **Publish the tested upstream SHA to GHCR** job
succeeds, then pull the image:

```sh
docker pull ghcr.io/hanssen0/ckbadger:sha-da98312e44cd
docker run --rm --network none ghcr.io/hanssen0/ckbadger:sha-da98312e44cd --version
```

The publish job takes only the checksum-verified artifact from its own push
build. It reuses an existing image only if the image configuration digest is
identical; a different digest or unreadable tag fails without overwriting it.
Do not otherwise push this SHA tag while the release job is running.

## Artifact and local fallback

Download **ckbadger-v0.8.3-linux-amd64-attempt-N** under **Artifacts** in a
successful PR or push run (seven-day retention, where N is the workflow attempt).
Unzip it, then run:

```sh
sha256sum -c ckbadger-v0.8.3-linux-amd64.tar.sha256
docker load -i ckbadger-v0.8.3-linux-amd64.tar
docker run --rm --network none ckbadger:0.8.3 --version
```

If Actions cannot run, check out the PR head and use the same script on Ubuntu
24.04 x86_64 with Docker, Git, Python 3, Node.js 24, pnpm 9.15.0, and stable
Rust via rustup:

```sh
sudo apt-get install -y build-essential libclang-dev libssl-dev zlib1g-dev
bash scripts/package-v0.8.3.sh ./package-v0.8.3
```

The archive and checksum are written only after the tests pass. The upstream
source commit is pinned, but v0.8.3 does not ship a Cargo lockfile, so builds
are not guaranteed to be byte-identical.

Loading the image does not change a running deployment or migrate its database.
Do not mount the current fork build’s layout-8 RocksDB stores into upstream
v0.8.3. Use a separate CKBadger workdir with fresh stores or a verified,
compatible completed snapshot. Packaging alone does not validate a testnet
re-index or recover an incomplete bulk build.
