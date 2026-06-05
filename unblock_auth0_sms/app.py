import logging
from auth0 import get_auth0_token, unblock_user
from dynamodb import handle_failure

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    records = event.get('Records', [])
    logger.info(f"Received {len(records)} stream records")

    for record in records:
        if record.get('eventName') == 'REMOVE':
            old_image = record.get('dynamodb', {}).get('OldImage')
            if not old_image or 'phoneNumber' not in old_image:
                continue
            
            phone = old_image['phoneNumber']['S']
            attempt_count = int(old_image.get('attemptCount', {}).get('N', 0))

            logger.info(f"Processing TTL unblock for phone: {phone}, attempt: {attempt_count}")

            try:
                token = get_auth0_token()
                unblock_user(phone, token)
                logger.info(f"Successfully unblocked {phone}")
            except Exception as e:
                logger.error(f"Failed to unblock {phone}: {str(e)}")
                handle_failure(old_image, phone, attempt_count)
