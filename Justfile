set shell := ["bash", "-cu"]

default:
    @just --list

fmt:
    cargo fmt --all

fmt-check:
    cargo fmt --all -- --check

check:
    cargo check --workspace

test:
    cargo test --workspace

ci: fmt-check check test

# === SNAPSHOTS ===

# Update SNAPSHOT.md files
update-snapshots:
    @echo "Updating snapshots..." && cb tree-sync-batch -y

# Locate SNAPSHOT.md files
locate-snapshots:
    @echo "Locating snapshots..." && cb --snapshots
