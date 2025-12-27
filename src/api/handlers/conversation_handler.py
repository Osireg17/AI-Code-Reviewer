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


async def handle_conversation_reply(
    payload: dict[str, Any],
    session_factory: Callable[[], Session] | None = None,
    github_auth: GitHubAppAuth | None = None,
) -> dict[str, str]:
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
            commit=pr.head.sha,
            path=file_path,
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


def _extract_file_context(
    repo: Any,  # github.Repository.Repository
    file_path: str,
    commit_sha: str,
    line_number: int,
    context_lines: int = 5,
) -> str:
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
