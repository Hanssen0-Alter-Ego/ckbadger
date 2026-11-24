# Package upstream CKBadger v0.8.3 without merging

The **Package upstream CKBadger v0.8.3** pull-request check builds Linux amd64 from
[janx/ckbadger v0.8.3](https://github.com/janx/ckbadger/tree/da98312e44cdc3655a6be8b3373caf293631e35a).
It uses the fork's Docker recipe but not the fork's CKBadger source. It checks the
binary inside the image reports `ckbadger 0.8.3@da98312e44cd`, then tests the
embedded frontend and graceful Docker shutdown before exporting the image.
This does not merge the PR, publish to GHCR, or change `latest`.

1. If GitHub shows **Awaiting approval**, review the workflow changes, then choose
   **Approve workflows to run** on the PR. Keep the PR unmerged.
2. Open the successful run and download **ckbadger-v0.8.3-linux-amd64** from
   **Artifacts** (retained for seven days). Unzip it, then run:

   ```sh
   sha256sum -c ckbadger-v0.8.3-linux-amd64.tar.sha256
   docker load -i ckbadger-v0.8.3-linux-amd64.tar
   docker run --rm --network none ckbadger:0.8.3 --version
   ```

If the fork's Actions policy does not run workflows from this PR, check out the
PR head locally and use the same script. On an Ubuntu 24.04 x86_64 host with
Docker, Git, Python 3, Node.js 24, pnpm 9.15.0, stable Rust via rustup, and the
usual C/C++ build tools:

```sh
sudo apt-get install -y build-essential libclang-dev libssl-dev zlib1g-dev
bash scripts/package-v0.8.3.sh ./package-v0.8.3
```

The archive and checksum are written to that directory only after the tests pass.
The source commit is pinned; upstream v0.8.3 does not ship a Cargo lockfile, so
this is not a guarantee of byte-identical builds.

Loading the image does not change a running deployment or migrate its database.
Do not mount the current fork build’s layout-8 RocksDB stores into upstream
v0.8.3. Use a separate CKBadger workdir with fresh stores or a verified,
compatible completed snapshot. Packaging alone does not validate a testnet
re-index or recover an incomplete bulk build.
