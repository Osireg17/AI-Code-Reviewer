# Deployment Guide

This guide walks you through deploying the AI Code Reviewer to Railway and connecting it to GitHub webhooks.

## Prerequisites

- Railway account (https://railway.app)
- GitHub account with admin access to the target repository
- OpenAI API key
- GitHub personal access token with `repo` scope

## Step 1: Deploy to Railway

1. **Connect your repository to Railway:**
   - Go to https://railway.app and create a new project
   - Select "Deploy from GitHub repo"
   - Choose your AI-Code-Reviewer repository
   - Railway will automatically detect the project

2. **Configure the build:**
   - Railway should automatically detect Python and use the `pyproject.toml`
   - If needed, set the start command to: `uvicorn src.main:app --host 0.0.0.0 --port $PORT`

## Step 2: Generate Webhook Secret

Generate a strong random secret for webhook verification:

```bash
# Using Python
python3 -c "import secrets; print(secrets.token_hex(32))"

# Or using OpenSSL
openssl rand -hex 32
```

Save this secret - you'll need it for both Railway and GitHub configuration.

## Step 3: Configure Environment Variables in Railway

In your Railway project dashboard:

1. Navigate to the **Variables** tab
2. Add the following environment variables:

```bash
# Required Variables
OPENAI_API_KEY=sk-...your-openai-api-key
GITHUB_TOKEN=ghp_...your-github-personal-access-token
GITHUB_WEBHOOK_SECRET=...your-generated-secret-from-step-2

# Optional Variables (with defaults)
OPENAI_MODEL=gpt-4o
DEBUG=False
LOG_LEVEL=INFO
ENVIRONMENT=production
MAX_FILES_PER_REVIEW=10
MAX_RETRIES=2
REVIEW_TEMPERATURE=0.3

# Optional: Pydantic Logfire for observability
LOGFIRE_TOKEN=...your-logfire-token
```

3. Click **Save** - Railway will automatically redeploy with the new variables

## Step 4: Get Your Railway Deployment URL

Once deployed, Railway will provide a public URL for your application:

1. Go to your project **Settings** tab
2. Under **Domains**, you'll see your deployment URL (e.g., `https://your-app.up.railway.app`)
3. Copy this URL - you'll need it for GitHub webhook configuration

Test your deployment:
```bash
curl https://your-app.up.railway.app/health
```

Expected response:
```json
{
  "status": "healthy",
  "environment": "production",
  "version": "0.1.0"
}
```

## Step 5: Configure GitHub Webhook

1. **Navigate to your GitHub repository settings:**
   - Go to your repository on GitHub
   - Click **Settings** → **Webhooks** → **Add webhook**

2. **Configure the webhook:**
   - **Payload URL**: `https://your-app.up.railway.app/webhook/github`
   - **Content type**: `application/json`
   - **Secret**: Paste the same secret you generated in Step 2
   - **SSL verification**: Enable SSL verification (recommended)

3. **Select events:**
   - Choose "Let me select individual events"
   - Check **Pull requests**
   - Uncheck other events (optional: you can keep "Pushes" for testing)

4. **Save the webhook:**
   - Click **Add webhook**
   - GitHub will send a `ping` event to verify the connection
   - Check for a green checkmark indicating successful delivery

## Step 6: Verify the Integration

1. **Check webhook delivery:**
   - In GitHub webhook settings, click on your webhook
   - Go to the **Recent Deliveries** tab
   - You should see a successful `ping` event with a 200 response

2. **Test with a pull request:**
   - Create a test pull request in your repository
   - Check Railway logs to verify the webhook was received
   - The webhook should trigger for `opened`, `reopened`, and `synchronize` events

3. **Monitor Railway logs:**
   ```bash
   # View logs in Railway dashboard or use Railway CLI
   railway logs
   ```

## Troubleshooting

### Webhook signature verification fails
- Ensure the `GITHUB_WEBHOOK_SECRET` in Railway matches the secret in GitHub webhook settings
- Check Railway logs for detailed error messages

### Application fails to start
- Verify all required environment variables are set in Railway
- Check Railway logs for missing configuration errors
- Ensure your OpenAI API key is valid

### Webhook not triggering
- Verify the webhook URL is correct (include `/webhook/github` path)
- Check GitHub webhook delivery history for error messages
- Ensure the webhook is configured for "Pull requests" events

### SSL/TLS errors
- Ensure SSL verification is enabled in GitHub webhook settings
- Railway provides automatic HTTPS - no additional configuration needed

## Security Best Practices

1. **Keep secrets secure:**
   - Never commit secrets to version control
   - Use Railway's environment variable management
   - Rotate secrets periodically

2. **Webhook signature verification:**
   - The application automatically verifies GitHub webhook signatures
   - This prevents unauthorized requests from triggering reviews

3. **GitHub token permissions:**
   - Use a token with minimal required permissions (`repo` scope)
   - Consider using a GitHub App for more granular permissions

4. **Rate limiting:**
   - Monitor OpenAI API usage to avoid unexpected costs
   - Consider implementing rate limiting for webhook endpoints

## Next Steps

After successful deployment:

1. Implement the PR review orchestration logic (currently marked as TODO in `src/api/webhooks.py:99`)
2. Add GitHub API integration to post review comments
3. Configure additional observability with Pydantic Logfire
4. Set up monitoring and alerting for production deployment

## Resources

- [Railway Documentation](https://docs.railway.app)
- [GitHub Webhooks Guide](https://docs.github.com/en/webhooks)
- [FastAPI Deployment](https://fastapi.tiangolo.com/deployment/)
- [Pydantic AI Documentation](https://ai.pydantic.dev)