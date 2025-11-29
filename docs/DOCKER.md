# Docker Deployment Guide

This guide explains how to build and deploy the AI Code Reviewer using Docker.

## Overview

The application is containerized using Docker for consistent deployment across environments. Railway automatically builds and deploys using the Dockerfile.

## Dockerfile Features

- **Base Image:** Python 3.12 slim (lightweight)
- **Multi-stage:** Optimized for production
- **Health Check:** Automatic health monitoring
- **Port Configuration:** Flexible port binding (Railway sets `PORT`)
- **Environment Variables:** All config via env vars

## Local Docker Build

### Build the Image

```bash
docker build -t ai-code-reviewer .
```

### Run Locally

```bash
# Using .env.local file
docker run -p 8000:8000 \
  --env-file .env.local \
  ai-code-reviewer

# Or with individual environment variables
docker run -p 8000:8000 \
  -e OPENAI_API_KEY=your_key \
  -e GITHUB_APP_ID=your_app_id \
  -e GITHUB_APP_INSTALLATION_ID=your_installation_id \
  -e GITHUB_APP_PRIVATE_KEY="$(cat your-app.pem)" \
  -e GITHUB_WEBHOOK_SECRET=your_secret \
  ai-code-reviewer
```

### Access the Application

- **API:** http://localhost:8000
- **Docs:** http://localhost:8000/docs
- **Health:** http://localhost:8000/health

## Docker Compose (Optional)

Create `docker-compose.yml` for local development:

```yaml
version: '3.8'

services:
  app:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env.local
    volumes:
      - ./src:/app/src
    environment:
      - DEBUG=True
      - LOG_LEVEL=DEBUG
```

Run with:
```bash
docker-compose up
```

## Railway Deployment

Railway automatically:
1. Detects the Dockerfile
2. Builds the image
3. Sets the `PORT` environment variable
4. Deploys to production

### Environment Variables in Railway

Set these in Railway dashboard:

**Required:**
- `OPENAI_API_KEY`
- `GITHUB_APP_ID`
- `GITHUB_APP_INSTALLATION_ID`
- `GITHUB_APP_PRIVATE_KEY` (full PEM content)
- `GITHUB_WEBHOOK_SECRET`

**Optional:**
- `GITHUB_APP_CLIENT_ID`
- `GITHUB_APP_CLIENT_SECRET`
- `LOGFIRE_TOKEN`
- `ENVIRONMENT=production`
- `DEBUG=False`
- `LOG_LEVEL=INFO`

### Private Key in Railway

For the private key, use the **full content** as an environment variable:

```bash
# Get the key content
cat your-app-name.private-key.pem

# Copy the entire output including BEGIN/END lines
# Paste into Railway as GITHUB_APP_PRIVATE_KEY
```

Railway will preserve the newlines correctly.

## Health Checks

The Dockerfile includes a health check:

- **Interval:** Every 30 seconds
- **Timeout:** 10 seconds
- **Start Period:** 5 seconds (grace period)
- **Retries:** 3 attempts before marking unhealthy

This ensures the container is restarted if the application becomes unresponsive.

## Optimization

### Build Optimization

The Dockerfile is optimized for faster builds:

1. **Dependency Layer Caching:** Dependencies are installed before copying code
2. **Minimal Base Image:** Uses `python:3.12-slim`
3. **Clean APT Cache:** Removes package lists to reduce image size

### Image Size

Approximate image size: **~500MB**

- Base Python 3.12 slim: ~120MB
- Dependencies: ~300MB
- Application code: <10MB

## Troubleshooting

### Build Fails

**Issue:** Dependency installation fails

```bash
# Solution: Clear Docker cache
docker build --no-cache -t ai-code-reviewer .
```

**Issue:** `gcc` not found

```bash
# Already handled in Dockerfile - gcc is installed
# Check Dockerfile line 16-18
```

### Container Won't Start

**Issue:** Missing environment variables

```bash
# Check logs
docker logs <container-id>

# Verify all required env vars are set
docker run ai-code-reviewer env | grep GITHUB
```

**Issue:** Port already in use

```bash
# Use a different port
docker run -p 8001:8000 ai-code-reviewer
```

### Health Check Fails

**Issue:** Health check keeps failing

```bash
# Check if app is running
docker exec <container-id> curl http://localhost:8000/health

# Check logs
docker logs <container-id>

# Disable health check for debugging
docker run --health-cmd='' ai-code-reviewer
```

### Private Key Issues

**Issue:** Private key not loading

```bash
# Verify key is properly formatted
docker run ai-code-reviewer python -c "
from src.config.settings import settings
print('Key starts with:', settings.github_app_private_key[:30])
"
```

## Testing the Docker Image

### Test Build

```bash
# Build
docker build -t ai-code-reviewer:test .

# Verify image
docker images | grep ai-code-reviewer

# Check layers
docker history ai-code-reviewer:test
```

### Test Run

```bash
# Start container
docker run -d \
  --name ai-code-reviewer-test \
  -p 8000:8000 \
  --env-file .env.local \
  ai-code-reviewer:test

# Check logs
docker logs -f ai-code-reviewer-test

# Test health endpoint
curl http://localhost:8000/health

# Stop and remove
docker stop ai-code-reviewer-test
docker rm ai-code-reviewer-test
```

### Test Authentication

```bash
# Run test script inside container
docker run --env-file .env.local ai-code-reviewer:test \
  python scripts/test_github_app_auth.py
```

## Production Best Practices

1. **Use Environment Variables:** Never hardcode secrets
2. **Enable Health Checks:** Let Railway restart unhealthy containers
3. **Monitor Logs:** Use Railway's log viewer
4. **Keep Images Small:** Current setup is optimized
5. **Update Regularly:** Rebuild with latest Python patches

## CI/CD Integration

The GitHub Actions workflows automatically test before Railway deploys:

1. **PR opened** → Tests run → Railway waits for CI
2. **Tests pass** → Railway builds Docker image
3. **Build succeeds** → Railway deploys to production

See `.github/workflows/deploy.yml` for CI configuration.

## Advanced Configuration

### Custom Entrypoint

Override the default command:

```bash
docker run ai-code-reviewer \
  uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Volume Mounts for Development

```bash
docker run -v $(pwd)/src:/app/src ai-code-reviewer
```

### Multi-stage Build (Future Optimization)

For even smaller images, consider multi-stage builds:

```dockerfile
# Build stage
FROM python:3.12-slim as builder
# ... install dependencies

# Runtime stage
FROM python:3.12-slim
COPY --from=builder /usr/local/lib/python3.12 /usr/local/lib/python3.12
# ... copy app
```

## Resources

- [Docker Documentation](https://docs.docker.com)
- [Railway Docker Guide](https://docs.railway.app/deploy/dockerfiles)
- [Python Docker Best Practices](https://docs.docker.com/language/python/)