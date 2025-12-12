#!/usr/bin/env python3
"""Test script for GitHub App authentication."""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services.github_auth import get_github_app_auth


async def main() -> None:
    """Test GitHub App authentication."""
    print("\n" + "=" * 70)
    print("GitHub App Authentication Test")
    print("=" * 70)

    try:
        # Get the auth instance
        github_auth = get_github_app_auth()

        # Test 1: Generate JWT
        print("\n1. Generating JWT...")
        jwt_token = github_auth.generate_jwt()
        print(f"   ✅ JWT generated: {jwt_token[:50]}...")

        # Test 2: Get installation access token
        print("\n2. Getting installation access token...")
        access_token = await github_auth.get_installation_access_token()
        print(f"   ✅ Access token obtained: {access_token[:20]}...")
        print(f"   Token expires at: {github_auth._token_expires_at}")

        # Test 3: Test authenticated client
        print("\n3. Testing authenticated client...")
        async with await github_auth.get_authenticated_client() as client:
            # Get repositories accessible to this installation
            response = await client.get(
                "https://api.github.com/installation/repositories"
            )
            if response.status_code == 200:
                repo_data = response.json()
                print("   ✅ Installation token is valid!")
                print(f"   Total repositories: {repo_data['total_count']}")
                if repo_data["repositories"]:
                    print(
                        f"   Sample repo: {repo_data['repositories'][0]['full_name']}"
                    )
            else:
                print(f"   ❌ Failed to access repositories: {response.status_code}")
                print(f"   Response: {response.text}")

        print("\n" + "=" * 70)
        print("✅ All tests passed!")
        print("=" * 70 + "\n")

    except ValueError as e:
        print(f"\n❌ Configuration Error: {e}")
        print("\nMake sure you have set up your .env.local with:")
        print("  - GITHUB_APP_ID")
        print("  - GITHUB_APP_INSTALLATION_ID")
        print("  - GITHUB_APP_PRIVATE_KEY or GITHUB_APP_PRIVATE_KEY_PATH")
        print("\nSee docs/GITHUB_APP_SETUP.md for details.\n")
        sys.exit(1)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        print(f"   Type: {type(e).__name__}\n")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
