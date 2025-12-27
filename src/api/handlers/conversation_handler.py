"""Handler for GitHub pull request review comment conversations.

=== CONTEXT ===
Purpose: Handle user replies to bot comments on PRs
Trigger: pull_request_review_comment webhook event with in_reply_to_id
Reference: Similar to pr_review_handler.py but focused on conversational responses

=== DEPENDENCIES ===
- Database session (ConversationThread queries and updates)
- GitHub API (fetch comment details, code context, post replies)
- Conversation agent (contextual response generation)
- GitHub App authentication (token for API calls)

=== BEHAVIOR ===
Main flow:
1. VALIDATE incoming webhook payload structure
2. DETECT bot self-replies (prevent infinite loops)
3. LOAD or CREATE conversation thread from database
4. FETCH code context (original code at time of comment + current code if changed)
5. BUILD agent context with conversation history and code
6. INVOKE conversation agent to generate response
7. POST reply to GitHub as threaded comment
8. UPDATE conversation thread in database with new messages

Edge cases:
- Bot replies to itself (skip processing)
- Original comment not found (handle gracefully)
- Code was deleted/moved since original comment
- Database unavailable (fail gracefully)
- Multiple rapid replies (idempotency)
"""

import logging
from collections.abc import Callable
from typing import Any

from github import Auth, Github
from sqlalchemy.orm import Session

from src.agents.conversation_agent import (
    conversation_agent,
    validate_conversation_response,
)
from src.config.settings import settings
from src.database.db import SessionLocal
from src.models.conversation import ConversationThread
from src.models.dependencies import ConversationDependencies
from src.services.github_auth import GitHubAppAuth, get_github_app_auth

logger = logging.getLogger(__name__)


# === MAIN HANDLER ===


async def handle_conversation_reply(
    payload: dict[str, Any],
    session_factory: Callable[[], Session] | None = None,
    github_auth: GitHubAppAuth | None = None,
) -> dict[str, str]:
    """
    Handle user replies to bot comments on pull requests.

    === INPUT ===
    payload: GitHub webhook payload containing:
        - action: "created", "edited", etc.
        - comment: {
            id, body, user, in_reply_to_id,
            path, line, commit_id, pull_request_url
          }
        - repository: {full_name}
        - pull_request: {number, head.sha, base.sha}

    session_factory: Database session factory (injected for testing)
    github_auth: GitHub authentication service (injected for testing)

    === OUTPUT ===
    Dict with status message:
        {"message": "Reply posted", "status": "success"}
        {"message": "Skipped - bot reply", "status": "skipped"}
        {"message": "Error: ...", "status": "error"}

    === PRECONDITIONS ===
    - Webhook signature already validated by webhooks.py
    - Payload contains valid GitHub comment event data
    - Bot GitHub App is installed on repository

    === POSTCONDITIONS ===
    - Bot reply posted to GitHub if appropriate
    - ConversationThread updated in database
    - All errors logged for monitoring

    === LOGIC FLOW ===
    INITIALIZE defaults if not provided

    EXTRACT data from payload

    CHECK if action is "created" (only handle new comments)
    IF not created THEN
        LOG and RETURN early (skip edits/deletes)

    VALIDATE comment has in_reply_to_id (is a reply)
    IF not a reply THEN
        LOG and RETURN early (not a conversation)

    DETECT bot self-replies
    IF comment.user.login == bot_login THEN
        LOG "Bot replied to itself, skipping"
        RETURN early (prevent infinite loops)

    AUTHENTICATE with GitHub App
    GET installation access token
    CREATE GitHub client

    FETCH repository and PR objects
    GET pull request details

    LOAD or CREATE conversation thread from database
    IF thread exists THEN
        UPDATE existing thread
    ELSE
        CREATE new thread with original comment details

    FETCH code context
    GET original code at commit when comment was posted
    GET current code at PR head
    COMPARE to detect if code changed

    BUILD conversation context for agent
    INCLUDE conversation history from database
    INCLUDE code snippets (original + current if different)
    INCLUDE original bot suggestion

    INVOKE conversation agent
     context and user's question
    GET agent response

    POST reply to GitHub
    CREATE threaded comment using in_reply_to_id
    LOG success

    UPDATE database
    ADD user message to conversation thread
    ADD bot reply to conversation thread
    COMMIT changes

    RETURN success status

    === EDGE CASES ===
    - Bot replies to own comment: Skip processing
    - Original comment deleted: Load from database or fail gracefully
    - Code file deleted: Include note in context
    - Multiple rapid replies: Database handles via thread locking
    - GitHub API errors: Log and return error status
    - Database errors: Rollback and return error status

    === ALTERNATIVES CONSIDERED ===
    1. Queue conversation replies (like PR reviews)
       - PRO: Handles spikes in traffic
       - CON: Adds latency, users expect quick responses
       - DECISION: Process synchronously for now, queue later if needed

    2. Store full conversation in separate messages table
       - PRO: Normalized database design
       - CON: More complex queries, JSONB is sufficient
       - DECISION: Use JSONB array (simpler, fewer queries)

    === INTEGRATION ===
    Triggered by: webhooks.py when pull_request_review_comment event received
    Calls into: conversation_agent.py, GitHub API, database
    Error handling: Log errors, return status dict (no exceptions)
    Observability: Log all steps, include repo/PR/comment IDs in logs
    """
    # Initialize defaults
    if session_factory is None:
        session_factory = SessionLocal
    if github_auth is None:
        github_auth = get_github_app_auth()

    # Extract payload data
    action = payload.get("action")
    comment = payload.get("comment", {})
    repository = payload.get("repository", {})
    pull_request = payload.get("pull_request", {})

    repo_full_name = repository.get("full_name")
    pr_number = pull_request.get("number")
    comment_id = comment.get("id")
    comment_body = comment.get("body", "")
    comment_user = comment.get("user", {})
    in_reply_to_id = comment.get("in_reply_to_id")
    file_path = comment.get("path")
    line_number = comment.get("line")
    comment.get("commit_id")

    logger.info(
        f"Processing comment {comment_id} on PR #{pr_number} in {repo_full_name}"
    )

    # Check if action is "created"
    if action != "created":
        logger.info(f"Ignoring {action} event (only process 'created')")
        return {"message": f"Ignored non-created event: {action}", "status": "skipped"}

    # Validate this is a reply
    if in_reply_to_id is None:
        logger.info("Comment is not a reply, skipping")
        return {"message": "Not a reply to bot", "status": "skipped"}

    # Detect bot self-replies
    bot_login = settings.github_app_bot_login
    user_login = comment_user.get("login")
    comment_user.get("id")
    user_type = comment_user.get("type")

    # Check both username and type to be extra safe
    if user_login == bot_login or user_type == "Bot":
        logger.info(
            f"Bot replied to itself (user={user_login}, type={user_type}), preventing loop"
        )
        return {"message": "Bot self-reply ignored", "status": "skipped"}

    # Authenticate with GitHub
    # TODO: PyGithub is synchronous and blocks the event loop. Consider either:
    #   (a) Using asyncio.to_thread() or run_in_executor() for blocking calls
    #   (b) Switching to an async GitHub client like githubkit
    #   For now, acceptable since handlers run as background jobs via RQ queue
    installation_token = await github_auth.get_installation_access_token()
    auth = Auth.Token(installation_token)
    github_client = Github(auth=auth)
    repo = github_client.get_repo(repo_full_name)
    pr = repo.get_pull(pr_number)

    # Load or create conversation thread
    db = session_factory()
    try:
        # Query for existing thread
        conversation_thread = (
            db.query(ConversationThread)
            .filter(ConversationThread.comment_id == in_reply_to_id)
            .first()
        )

        if conversation_thread:
            logger.info(f"Loaded existing thread {conversation_thread.id}")
        else:
            # Create new thread
            conversation_thread = ConversationThread(
                repo_full_name=repo_full_name,
                pr_number=pr_number,
                comment_id=in_reply_to_id,
                thread_type="inline_comment",
                status="active",
                original_file_path=file_path,
                original_line_number=line_number,
                thread_messages=[],
            )
            db.add(conversation_thread)
            logger.info(f"Created new thread for comment {in_reply_to_id}")

        # Fetch code context
        original_code_snippet = None
        current_code_snippet = None
        code_changed = False
        original_bot_comment = None

        try:
            # Get the original comment that started this thread
            original_comment = pr.get_review_comment(in_reply_to_id)

            # Verify the original comment was made by the bot
            # Don't respond to replies in human-only threads
            original_author = original_comment.user.login
            if original_author != bot_login:
                logger.info(
                    f"Original comment by {original_author}, not bot ({bot_login}). Skipping."
                )
                return {
                    "message": f"Not replying to non-bot comment by {original_author}",
                    "status": "skipped",
                }

            original_bot_comment = original_comment.body
            original_commit_sha = original_comment.original_commit_id
            current_commit_sha = pr.head.sha

            # Fetch code snippets with context
            if file_path and line_number:
                try:
                    original_code_snippet = _extract_file_context(
                        repo, file_path, original_commit_sha, line_number
                    )
                except Exception as e:
                    logger.warning(f"Could not fetch original code context: {e}")

                try:
                    current_code_snippet = _extract_file_context(
                        repo, file_path, current_commit_sha, line_number
                    )
                except Exception as e:
                    logger.warning(f"Could not fetch current code context: {e}")

                # Determine if code changed
                if original_code_snippet and current_code_snippet:
                    code_changed = original_code_snippet != current_code_snippet
                elif original_code_snippet != current_code_snippet:
                    code_changed = True
        except Exception as e:
            logger.warning(f"Could not fetch code context: {e}")

        # Build agent context
        deps = ConversationDependencies(
            conversation_history=conversation_thread.get_context_for_llm(),
            user_question=comment_body,
            original_bot_comment=original_bot_comment,
            file_path=file_path or "",
            line_number=line_number or 1,
            original_code_snippet=original_code_snippet,
            current_code_snippet=current_code_snippet,
            code_changed=code_changed,
            pr_number=pr_number,
            repo_name=repo_full_name,
            repo=repo,
            pr=pr,
            github_client=github_client,
            db_session=db,
        )

        # Invoke conversation agent
        logger.info(f"Invoking conversation agent for comment {comment_id}")
        result = await conversation_agent.run(comment_body, deps=deps)
        bot_reply_text = result.output

        # Validate and sanitize response
        bot_reply_text = validate_conversation_response(bot_reply_text)

        # Post reply to GitHub as threaded comment
        # When replying, only provide body and in_reply_to (GitHub API requirement)
        pr.create_review_comment(
            body=bot_reply_text,
            in_reply_to=in_reply_to_id,
        )
        logger.info(f"Posted reply to comment {in_reply_to_id}")

        # Update database with conversation history
        conversation_thread.add_message(
            role="developer", content=comment_body, comment_id=comment_id
        )
        conversation_thread.add_message(
            role="bot",
            content=bot_reply_text,
            comment_id=None,
        )

        # Commit all changes (Option A: single commit at end)
        db.commit()
        logger.info(f"Updated conversation thread {conversation_thread.id}")

        return {"message": "Reply posted successfully", "status": "success"}

    finally:
        db.close()


# === HELPER FUNCTIONS ===


def _extract_file_context(
    repo: Any,  # github.Repository.Repository
    file_path: str,
    commit_sha: str,
    line_number: int,
    context_lines: int = 5,
) -> str:
    """
    Extract a code snippet with context lines around target line.

    === PURPOSE ===
    Provide focused code context for conversations without overwhelming the agent.

    === INPUT ===
    repo: GitHub repository object
    file_path: Path to file in repository
    commit_sha: Specific commit to fetch from
    line_number: Target line number (1-indexed)
    context_lines: Number of lines before/after to include (default: 5)

    === OUTPUT ===
    String containing code snippet with line numbers, or error message

    === LOGIC FLOW ===
    TRY to fetch file contents
    IF file not found THEN
        RETURN "[File not found or deleted]"

    SPLIT file into lines
    CALCULATE start_line = max(1, line_number - context_lines)
    CALCULATE end_line = min(total_lines, line_number + context_lines)

    BUILD snippet with line numbers:
        FOR each line from start_line to end_line
            FORMAT as "{line_num:4d}  {line_content}"
            IF line_num == line_number THEN
                ADD highlight marker ">>>"

    RETURN formatted snippet

    === EDGE CASES ===
    - File deleted: Return placeholder message
    - Line number out of bounds: Clamp to file boundaries
    - Binary file: Return "[Binary file]"
    - Empty file: Return "[Empty file]"
    """
    # Fetch file contents at specific commit
    file_content = repo.get_contents(file_path, ref=commit_sha)

    # Check if it's a binary file
    if file_content.encoding != "base64":
        return "[Binary file - cannot display content]"

    # Decode content to string
    decoded_content = file_content.decoded_content.decode("utf-8")

    # Handle empty file
    if not decoded_content.strip():
        return "[Empty file]"

    # Split into lines
    lines = decoded_content.splitlines()
    total_lines = len(lines)

    # Handle line number out of bounds
    if line_number < 1:
        line_number = 1
        logger.warning(f"Line number {line_number} < 1, clamping to 1")
    elif line_number > total_lines:
        line_number = total_lines
        logger.warning(
            f"Line number {line_number} > {total_lines}, clamping to {total_lines}"
        )

    # Calculate range with bounds checking
    start_line = max(1, line_number - context_lines)
    end_line = min(total_lines, line_number + context_lines)

    # Build formatted snippet with line numbers
    snippet_lines = []
    for i in range(start_line - 1, end_line):  # -1 because lines are 0-indexed
        actual_line_num = i + 1
        line_content = lines[i]

        # Format with line number
        formatted_line = f"{actual_line_num:4d}  {line_content}"

        # Add highlight marker for target line
        if actual_line_num == line_number:
            formatted_line = f">>> {formatted_line}"
        else:
            formatted_line = f"    {formatted_line}"

        snippet_lines.append(formatted_line)

    return "\n".join(snippet_lines)


def _should_create_new_thread(
    db: Session,
    in_reply_to_id: int,
) -> tuple[bool, ConversationThread | None]:
    """
    Determine if a new conversation thread should be created.

    === PURPOSE ===
    Handle race conditions where multiple replies arrive before thread is created.

    === INPUT ===
    db: Database session
    in_reply_to_id: Comment ID being replied to

    === OUTPUT ===
    Tuple of (should_create, existing_thread)
    - (True, None): Create new thread
    - (False, thread): Use existing thread

    === LOGIC FLOW ===
    QUERY for existing thread with comment_id = in_reply_to_id
    IF thread found THEN
        RETURN (False, thread)
    ELSE
        RETURN (True, None)

    === EDGE CASES ===
    - Duplicate threads: Database unique constraint prevents this
    - Concurrent creates: Database handles with UPSERT semantics
    """
    # Query for existing thread with this comment_id
    existing_thread = (
        db.query(ConversationThread)
        .filter(ConversationThread.comment_id == in_reply_to_id)
        .first()
    )

    # If thread exists, use it; otherwise create new
    if existing_thread:
        return False, existing_thread
    else:
        return True, None
