# GitHub App Setup Guide

This guide explains how to set up your AI Code Reviewer as a GitHub App so it can:
- Automatically review pull requests when they're opened
- Show up as a reviewer/bot on PRs
- Be requested as a reviewer by team members
- Post review comments and suggestions directly on code

## Why Use a GitHub App?

**GitHub App Benefits:**
- ✅ Appears as its own identity (not tied to a personal account)
- ✅ Can be installed on multiple repositories
- ✅ Fine-grained permissions (only what's needed)
- ✅ Shows up in "Reviewers" dropdown on PRs
- ✅ Built-in webhook support
- ✅ More secure than personal access tokens

**vs Personal Access Token:**
- ❌ Tied to a specific user account
- ❌ If user leaves, token breaks
- ❌ Broad permissions across all repos
- ❌ Reviews appear as coming from that user

## Step 1: Create GitHub App

1. **Navigate to GitHub App Settings:**
   - Go to https://github.com/settings/apps
   - Click **New GitHub App**

2. **Basic Information:**
   - **GitHub App name:** `AI Code Reviewer` (must be unique across GitHub)
   - **Homepage URL:** Your Railway app URL (e.g., `https://your-app.up.railway.app`)
   - **Webhook URL:** `https://your-app.up.railway.app/webhook/github`
   - **Webhook secret:** Use the same secret from your `.env.local` (`GITHUB_WEBHOOK_SECRET`)

3. **Permissions:**

   **Repository permissions:**
   - **Contents:** Read (to read PR files)
   - **Pull requests:** Read & Write (to post reviews)
   - **Metadata:** Read (automatically required)

   **Subscribe to events:**
   - ✅ Pull request
   - ✅ Pull request review
   - ✅ Pull request review comment

4. **Where can this GitHub App be installed:**
   - Select **Only on this account** (or "Any account" if you want others to install it)

5. **Create the app:**
   - Click **Create GitHub App**

## Step 2: Generate Private Key

1. After creating the app, scroll down to **Private keys**
2. Click **Generate a private key**
3. A `.pem` file will download automatically
4. **Save this file securely** - you'll need it for authentication

## Step 3: Install the App on Your Repository

1. In your GitHub App settings, click **Install App** (left sidebar)
2. Click **Install** next to your username/organization
3. Choose:
   - **All repositories** - App works on all your repos
   - **Only select repositories** - Choose specific repos (recommended for testing)
4. Click **Install**

## Step 4: Get Required Credentials

You'll need these values for your environment configuration:

### App ID
- Found at the top of your GitHub App settings page
- Example: `2335089`

### Client ID
- Found in your GitHub App settings under "About"
- Example: `Iv23likwHTFv9bcvicoA`

### Client Secret
1. In GitHub App settings, scroll to **Client secrets**
2. Click **Generate a new client secret**
3. Copy the secret immediately (you won't see it again)

### Installation ID
1. Go to https://github.com/settings/installations
2. Click **Configure** next to your app
3. Look at the URL: `https://github.com/settings/installations/XXXXXXXX`
4. The number at the end is your Installation ID

### Private Key Path
- Path to the `.pem` file you downloaded earlier
- Example: `./obomighieai.2025-01-28.private-key.pem`

## Step 5: Configure Environment Variables

Update your `.env.local` (for local development):

```bash
# GitHub App Configuration
GITHUB_APP_ID=your_app_id
GITHUB_APP_CLIENT_ID=your_client_id
GITHUB_APP_CLIENT_SECRET=your_client_secret
GITHUB_APP_INSTALLATION_ID=your_installation_id
GITHUB_APP_PRIVATE_KEY_PATH=./your-app-name.private-key.pem

# Or use the private key content directly (for production)
# GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"

# Webhook Secret (same as before)
GITHUB_WEBHOOK_SECRET=your_webhook_secret

# Keep existing config
OPENAI_API_KEY=your_openai_key
OPENAI_MODEL=gpt-4o
```

For **Railway/Production**, you can either:
- Upload the `.pem` file and use the path, OR
- Copy the entire private key content into an environment variable

**To use private key content:**
```bash
# Get the key content
cat your-app-name.private-key.pem

# Copy the output and set as GITHUB_APP_PRIVATE_KEY in Railway
# Make sure to preserve the newlines (\n)
```

## Step 6: Update Application Code

The application will need to:
1. Authenticate as a GitHub App using the private key
2. Get an installation access token
3. Use that token to make API calls
4. Post review comments on PRs

See the implementation in `src/services/github_auth.py` (to be created).

## How It Works

### Webhook Flow

1. User opens a PR in your repository
2. GitHub sends webhook to your app: `POST /webhook/github`
3. Your app verifies the webhook signature
4. Your app authenticates as the GitHub App
5. Your app fetches the PR diff
6. Your app sends code to OpenAI for review
7. Your app posts review comments using GitHub API
8. Review appears on PR from "AI Code Reviewer" bot

### Manual Review Request Flow

1. User goes to PR and clicks "Reviewers"
2. User selects "AI Code Reviewer" from the list
3. GitHub sends a `pull_request_review_requested` event
4. Your app processes it the same way as auto-review

## Permissions Explained

| Permission | Access | Why Needed |
|------------|--------|------------|
| Contents | Read | Fetch PR file contents and diffs |
| Pull requests | Read & Write | Read PR details, post reviews and comments |
| Metadata | Read | Basic repository information |

## Testing Your Setup

1. **Test webhook delivery:**
   ```bash
   # In your repo settings → Webhooks
   # Find your webhook and click "Recent Deliveries"
   # You should see a successful ping event
   ```

2. **Test PR review:**
   ```bash
   # Create a test PR
   git checkout -b test-ai-review
   echo "// Test code" >> test.js
   git add test.js
   git commit -m "test: AI review"
   git push origin test-ai-review
   # Create PR on GitHub
   ```

3. **Check the logs:**
   - Railway dashboard → Logs
   - Look for webhook received and review posted messages

## Troubleshooting

### App not appearing in Reviewers list
- Ensure the app is installed on the repository
- Check that "Pull requests" permission is set to Read & Write
- Verify the app is active (not suspended)

### Webhook signature verification fails
- Confirm `GITHUB_WEBHOOK_SECRET` matches in both GitHub and your app
- Check that the secret doesn't have extra whitespace

### Authentication errors
- Verify the private key is correctly formatted
- Check that `GITHUB_APP_ID` is correct
- Ensure installation ID matches the repo where you're testing

### Reviews not posting
- Check Railway logs for API errors
- Verify the installation access token is being generated
- Confirm "Pull requests" write permission is granted

## Security Best Practices

1. **Private Key Security:**
   - Never commit `.pem` files to git (already in `.gitignore`)
   - Use Railway environment variables for production
   - Rotate keys periodically

2. **Webhook Secret:**
   - Use a strong random string
   - Never expose in logs or error messages
   - Always verify signatures before processing

3. **Permissions:**
   - Only request minimum required permissions
   - Review and audit permissions regularly

## Next Steps

After setup:
1. ✅ Create GitHub App
2. ✅ Install on repositories
3. ✅ Configure environment variables
4. ✅ Implement GitHub App authentication in code
5. ✅ Implement PR review posting logic
6. ✅ Test with real PRs
7. ✅ Deploy to production

## Resources

- [GitHub Apps Documentation](https://docs.github.com/en/apps)
- [Creating a GitHub App](https://docs.github.com/en/apps/creating-github-apps)
- [Authenticating as a GitHub App](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app)
- [Pull Request Reviews API](https://docs.github.com/en/rest/pulls/reviews)