# GitHub Actions Setup Guide

This guide explains how to configure GitHub Actions for the AI Code Reviewer project.

## Overview

The project uses three GitHub Actions workflows:

1. **Tests** (`.github/workflows/test.yml`) - Runs on push and pull requests
2. **Code Quality** (`.github/workflows/lint.yml`) - Runs linting and type checking
3. **CI/CD Pipeline** (`.github/workflows/deploy.yml`) - Validates code before Railway auto-deploys

**Note:** Railway handles deployments automatically via built-in GitHub integration. The CI/CD workflow validates code, then Railway deploys when checks pass.

## Required GitHub Secrets

### Setting Up Secrets

1. Go to your GitHub repository
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Add the following secrets:

### Secret: `CODECOV_TOKEN` (Optional)

**Required for:** Test coverage reporting

**How to get it:**
1. Go to https://codecov.io and sign in with GitHub
2. Add your repository
3. Copy the upload token from repository settings
4. Add it to GitHub as `CODECOV_TOKEN`

**Usage:** Uploads test coverage reports to Codecov for tracking

**Note:** This is optional. The workflow will continue without it (see `fail_ci_if_error: false` in test.yml)

## Workflow Configuration

### Test Workflow

**File:** `.github/workflows/test.yml`

**Triggers:**
- Push to `main` or `develop` branches
- Pull requests to `main` or `develop` branches

**What it does:**
- Tests on Python 3.10, 3.11, and 3.12
- Installs dependencies with pip caching
- Creates a test environment file with dummy credentials
- Runs pytest with coverage reporting
- Uploads coverage to Codecov (if token is set)

**Environment Variables:**
All test environment variables are created automatically in the workflow. No secrets needed for tests!

### Lint Workflow

**File:** `.github/workflows/lint.yml`

**Triggers:**
- Push to `main` or `develop` branches
- Pull requests to `main` or `develop` branches

**What it does:**
- Runs Ruff linter with GitHub annotations
- Checks Ruff formatting
- Checks Black formatting
- Runs mypy type checking

**No secrets required** for this workflow.

### CI/CD Pipeline Workflow

**File:** `.github/workflows/deploy.yml`

**Triggers:**
- Push to `main` branch
- Pull requests to `main` branch

**What it does:**
- Runs quick validation tests
- Runs linting checks
- Shows deployment status message

**Note:** Railway automatically deploys when this workflow passes!

**No secrets required** for this workflow.

## Verifying Your Setup

### 1. Check Workflow Status

After pushing code:
1. Go to your repository on GitHub
2. Click the **Actions** tab
3. You should see workflows running

### 2. Test the Workflows

Create a test pull request:
```bash
git checkout -b test-ci
echo "# Test" >> README.md
git add README.md
git commit -m "test: Verify CI workflows"
git push origin test-ci
```

Then create a PR on GitHub. Both test and lint workflows should run.

### 3. Check for Errors

If workflows fail:
- Click on the failed workflow
- Expand the failed step
- Read the error message
- Common issues:
  - Missing dependencies in `pyproject.toml`
  - Linting errors (fix with `ruff check --fix` and `black .`)
  - Type errors (fix based on mypy output)

## Railway Auto-Deployment Setup

Railway automatically deploys your app when you push to the connected branch. No GitHub Actions secrets needed!

### Setup Steps

1. **Connect GitHub Repository to Railway:**
   - Go to https://railway.app/new
   - Select "Deploy from GitHub repo"
   - Choose your AI-Code-Reviewer repository
   - Railway will create a project

2. **Configure Source Branch:**
   - In Railway project → Settings → Source
   - Select which branch triggers deployments (typically `main`)

3. **Enable "Wait for CI" (Recommended):**
   - In Railway project → Settings → Deploy
   - Enable "Wait for CI to complete before deploying"
   - Railway will wait for GitHub Actions to pass before deploying

4. **Configure Railway Environment Variables:**

   In Railway dashboard → Variables tab, add:
   - `OPENAI_API_KEY` - Your OpenAI API key
   - `GITHUB_TOKEN` - GitHub personal access token
   - `GITHUB_WEBHOOK_SECRET` - Your webhook secret
   - `LOGFIRE_TOKEN` - (optional) Logfire token
   - `ENVIRONMENT=production`
   - `DEBUG=False`
   - `LOG_LEVEL=INFO`

### How It Works

1. You push code to `main` branch
2. GitHub Actions run tests and linting
3. Railway waits for checks to pass (if "Wait for CI" is enabled)
4. Railway automatically builds and deploys your app
5. Your app is live at your Railway URL

### Monitoring Deployments

- View deployments in Railway dashboard
- Check build logs for any errors
- Monitor application logs in real-time

## Workflow Badges

Add status badges to your README.md:

```markdown
![Tests](https://github.com/yourusername/AI-Code-Reviewer/actions/workflows/test.yml/badge.svg)
![Lint](https://github.com/yourusername/AI-Code-Reviewer/actions/workflows/lint.yml/badge.svg)
![Deploy](https://github.com/yourusername/AI-Code-Reviewer/actions/workflows/deploy.yml/badge.svg)
```

Replace `yourusername` with your GitHub username.

## Troubleshooting

### Workflow not running

- Check that workflow files are in `.github/workflows/`
- Verify the branch names in the `on:` triggers
- Check repository settings → Actions → ensure Actions are enabled

### Railway deployment fails

- Check Railway project is connected to GitHub
- Verify "Wait for CI" settings if enabled
- Ensure Railway environment variables are set
- Check Railway dashboard for deployment logs
- Verify GitHub Actions passed before Railway tried to deploy

### Tests fail in CI but pass locally

- Check Python version compatibility
- Verify all dependencies are in `pyproject.toml`
- Check for environment-specific issues
- Review the test environment file creation in test.yml

### Coverage upload fails

- Verify `CODECOV_TOKEN` is set (or remove the upload step)
- Check Codecov repository settings
- Review Codecov action logs for details

## Next Steps

1. ✅ Connect Railway to your GitHub repository
2. ✅ Configure Railway environment variables
3. ✅ Enable "Wait for CI" in Railway settings
4. ✅ (Optional) Set up `CODECOV_TOKEN` for coverage tracking
5. ✅ Push code to trigger workflows
6. ✅ Monitor GitHub Actions tab for workflow runs
7. ✅ Verify Railway automatically deploys after checks pass

## Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Railway Documentation](https://docs.railway.app)
- [Codecov Documentation](https://docs.codecov.com)