# Maintaining and publishing this repository

The public source repository is [pablonietopareja/sdex-connectmap](https://github.com/pablonietopareja/sdex-connectmap). Its default branch is `main`; it already has a README, MIT license, documentation, CI and source history. **Do not initialize a second repository or create a new empty GitHub repository to update it.**

The repository contains source code, not an image published to a Docker registry. Builds and deployments are documented separately in [Deployment](DEPLOYMENT.md).

## Update the existing repository

The commands below use Windows PowerShell. Adapt the clone path if it is stored elsewhere.

### 1. Inspect the checkout

```powershell
$repo = Join-Path $HOME 'Downloads\sdex-connectmap-repo'
Set-Location -LiteralPath $repo
git rev-parse --show-toplevel
git branch --show-current
git remote -v
git status --short
```

Confirm that the repository root is the intended local clone, the branch is `main`, and `origin` points to `https://github.com/pablonietopareja/sdex-connectmap.git` (or the equivalent SSH URL).

If local edits or staged changes already exist, **review and preserve them** before applying an update. Do not discard them using `git reset --hard`, `git clean`, or a forced checkout.

### 2. Synchronize only when safe

For a clean checkout:

```powershell
git fetch origin main
git pull --ff-only origin main
git status --short
```

If `pull --ff-only` cannot proceed, inspect the branch divergence before making further changes. Do not merge or force-push simply to make the command succeed.

### 3. Edit or copy the intended files

Only update files that are part of the reviewed change. For a documentation-only update, preserve source code, tests, CI, `LICENSE`, dependency locks, application assets and deployment data.

To review the resulting patch:

```powershell
git diff --check
git diff --stat
git diff -- README.md RELEASE_AUDIT.md CHANGELOG.md docs/DEPLOYMENT.md docs/DEVELOPMENT.md docs/PUBLISHING.md
git status --short
```

Review relative links and factual claims. CI results must identify a specific commit and completed run; site-specific field validation must be attributed separately from automated tests.

### 4. Stage only the changed documentation

If **all six** documentation files were intentionally changed:

```powershell
git add -- README.md RELEASE_AUDIT.md CHANGELOG.md docs/DEPLOYMENT.md docs/DEVELOPMENT.md docs/PUBLISHING.md
git diff --cached --check
git diff --cached --stat
git diff --cached --name-only
```

If fewer files were modified, stage only those files. Check that the staged inventory contains no `.env`, keys, databases, diagnostic exports, real topology data or generated archives. Review the full patch with `git diff --cached` when necessary.

### 5. Commit and push manually

When the staged files and author identity are correct:

```powershell
git config user.name
git config user.email
git commit -m "docs: finalize SDEX ConnectMap 1.0.0 release audit"
git push origin main
git status
```

Do not put credentials in the Git remote URL, and do not use `--force`. If a push is rejected because the remote has moved, fetch the new state and reconcile the changes without rewriting published history.

### 6. Review CI after the push

Open [GitHub Actions](https://github.com/pablonietopareja/sdex-connectmap/actions) and select the workflow run triggered by the **new commit**. Wait for its conclusion; a previous successful run is not proof that a later commit has passed.

Confirm these five jobs:

| Job | Expected result |
| --- | --- |
| `source (ubuntu-24.04)` | Success |
| `source (windows-2022)` | Success |
| `security` | Success |
| `container (ubuntu-24.04)` | Success |
| `container (ubuntu-24.04-arm)` | Success |

If a job fails, read its logs and reproduce the failure before making further changes. Keep the failure in the history rather than deleting or re-labeling it. The previously validated source run is [#38408177090](https://github.com/pablonietopareja/sdex-connectmap/actions/runs/38408177090), commit `2ce9fac20c9adb36087a779f636bc62f72cee8d0`.

## Tagging version 1.0.0 (optional)

At the time the release documentation was last reviewed, there was no `v1.0.0` tag or GitHub Release. Once the intended final source commit and its **new** CI run both pass, a maintainer may create a signed or annotated tag manually.

From an up-to-date, clean checkout:

```powershell
git fetch origin main --tags
git status
git tag --list v1.0.0
```

Only if the tag does **not** already exist and the current commit is the intended final release:

```powershell
git tag -a v1.0.0 -m "SDEX ConnectMap 1.0.0"
git push origin v1.0.0
```

Then open [Releases](https://github.com/pablonietopareja/sdex-connectmap/releases), choose **Draft a new release**, select the existing `v1.0.0` tag and write release notes based on [CHANGELOG.md](../CHANGELOG.md). Do not invent binary downloads or claim that container images were published to a registry. Source artifacts are generated locally with `scripts/build_release.py`.

Tagging is optional; it is deliberately separate from the ordinary documentation update. Never recreate or move a tag that others may already use without an explicit release-management decision.

## Review before public distribution

Check [License](../LICENSE), [Licensing](LICENSING.md), [Third-party notices](../THIRD_PARTY_NOTICES.md), [Security](../SECURITY.md) and the [Release audit](../RELEASE_AUDIT.md). Confirm that publication rights for the original code and artwork are appropriate. The repository must not include operational `.env`, credentials, SQLite volumes, customer data, industrial addresses or test captures from a real site.

Application dependency scans and synthetic native Docker acceptance are documented, but they are not a substitute for a built-image OS vulnerability/license scan, penetration test or production SDEX compatibility qualification.

For first-time forks, initialize and publish an independent repository under your own ownership. Those steps are different from updating this already established project.
