import time
import logging
from auth0 import table, MAX_ATTEMPTS

logger = logging.getLogger(__name__)

def handle_failure(old_image: dict, phone: str, current_attempt: int) -> None:
    """
    Pushes a failed record back into DynamoDB with exponential backoff.
    """
    if current_attempt >= MAX_ATTEMPTS:
        logger.warning(f"Abandoning {phone} - max attempts reached. Consider alerting an admin via SNS/Slack.")
        return

    next_attempt = current_attempt + 1
    # Exponential backoff: 60 * 5^next_attempt
    delay_seconds = int(60 * (5 ** next_attempt))
    next_unblock_at = int(time.time()) + delay_seconds

    logger.info(f"Requeueing {phone} for attempt {next_attempt} at TTL {next_unblock_at}")

    # Extract original values safely from the DynamoDB Stream format
    blocked_at = int(old_image.get("blockedAt", {}).get("N", time.time()))
    last_event_id = old_image.get("lastEventId", {}).get("S", "")

    table.put_item(
        Item={
            'phoneNumber': phone,
            'attemptCount': next_attempt,
            'blockedAt': blocked_at,
            'unBlockedAt': next_unblock_at,
            'status': 'BLOCKED',
            'lastEventId': last_event_id
        }
    )
