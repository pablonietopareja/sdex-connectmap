# Publish the repository manually

Use repository name **`sdex-connectmap`** under **`pablonietopareja`**. The contents of `Github-Release/` become the repository root; do not upload an outer folder containing the project.

Suggested description:

> Read-only industrial topology viewer for SDEX Suite, with a persistent interactive map, offline demo and Docker deployment.

## 1. Review the local release

Read [README](../README.md), [License](../LICENSE), [Security](../SECURITY.md), [Licensing](LICENSING.md) and [Release audit](../RELEASE_AUDIT.md). Resolve any source-publication blocker before uploading. Deployment checks marked `NOT RUN` remain unqualified; do not describe them as passing in a release announcement.

Check that no `.env`, database, key, real diagnostic export, private address inventory or installed dependency directory is present in the staged files. Only synthetic test data belongs in this repository.

## 2. Create an empty GitHub repository

Sign in to GitHub and choose **New repository**:

- Owner: `pablonietopareja`
- Name: `sdex-connectmap`
- Visibility: **Public**
- Description: use the text above, or edit it to your preference.
- Leave **Add a README**, **Add .gitignore** and **Choose a license** unchecked. Those files already exist locally.

Create the repository and leave its empty-repository page open. Its HTTPS remote will be `https://github.com/pablonietopareja/sdex-connectmap.git`.

## 3. Enter the release folder in PowerShell

Replace the example path with the actual folder on your machine:

```powershell
Set-Location -LiteralPath 'C:\path\to\SDEX_ConnMap\Github-Release'
Get-Location
Get-ChildItem -Force
git --version
```

At this location, `README.md`, `LICENSE`, `Dockerfile`, `backend/` and `frontend/` must be directly visible. Do not run the following steps from their parent folder.

## 4. Initialize Git, or inspect an existing checkout

For a folder without its own `.git` directory:

```powershell
git init --initial-branch=main
git rev-parse --show-toplevel
git branch --show-current
git status --short
```

The top-level path must be this release folder, and the branch must be `main`. If initialization fails, stop and inspect the error before proceeding.

If `.git` already exists, inspect it first:

```powershell
git rev-parse --show-toplevel
git branch --show-current
git status --short
git diff --stat
git diff --cached --stat
git remote -v
```

If there are pre-existing edits or staged files, stop and review them. Do not run a reset, clean, forced checkout or overwrite to make the instructions fit. On a rerun, retain the existing commit and verified remote instead of initializing again. If a parent repository owns this directory, initialize a separate repository here deliberately and verify the reported root.

## 5. Verify author identity and remote

```powershell
git config user.name
git config user.email
git remote -v
```

If necessary, set a **local** identity. Replace the email placeholder with your verified GitHub email or the exact privacy address shown in GitHub's email settings:

```powershell
git config --local user.name 'Pablo Nieto Pareja'
git config --local user.email 'YOUR_VERIFIED_GITHUB_EMAIL'
```

For a checkout without an `origin` remote:

```powershell
git remote add origin https://github.com/pablonietopareja/sdex-connectmap.git
git remote -v
```

If `origin` already exists, compare its owner/name with the intended empty repository. Keep it when correct; stop and inspect a mismatch rather than silently replacing it. GitHub's browser/device sign-in or a configured credential manager can handle HTTPS authentication; do not put a token in the URL.

## 6. Stage and review

```powershell
git diff --check
git add --all
git diff --cached --check
git diff --cached --stat
git diff --cached --name-only
git status --short
```

Read the staged file inventory. It must show the application at the root, without an extra `Github-Release/` prefix. Generated `dist/`, `frontend/dist/`, `node_modules/`, `.venv/`, data directories and secrets must not be staged. Review the actual patch with `git diff --cached` if needed.

Create the local commit only after reviewing those files:

```powershell
git commit -m 'Initial public source release of SDEX ConnectMap 1.0.0'
git status --short
git log -1 --oneline
```

The working tree should be clean. A local commit does not publish anything.

## 7. Push when ready

After reviewing the local commit and confirming the remote, manually run:

```powershell
git push --set-upstream origin main
```

This is the publication step. It is intentionally separate from staging and committing. Do not use `--force`. If the remote is not empty and rejects the push, inspect its contents and history; do not overwrite them.

## 8. Verify GitHub

Open the repository and confirm:

- `main` is the default branch.
- The README renders correctly and all local documentation links work.
- GitHub identifies the MIT license and the copyright holder is correct.
- The Actions workflow runs and its job results are reviewed.
- **Settings > Code security** has private vulnerability reporting enabled when available.
- The About description and optional topics describe the actual application, for example `sdex`, `industrial-iot`, `docker`, `fastapi`, `react` and `topology`.

Do not add passing CI, native-architecture or vulnerability-free-image claims until the corresponding checks have executed. A first release tag or GitHub Release can be created later after reviewing the uploaded commit and CI results; these instructions do not create either automatically.
