import os
import boto3
import requests
import urllib.parse
from dotenv import load_dotenv

load_dotenv()

MAX_ATTEMPTS = 5

AUTH0_DOMAIN = os.environ.get("AUTH0_DOMAIN")
AUTH0_CLIENT_ID = os.environ.get("AUTH0_CLIENT_ID")
AUTH0_CLIENT_SECRET = os.environ.get("AUTH0_CLIENT_SECRET")
TABLE_NAME = os.environ.get("TABLE_NAME", "otd-loyalty-provider-auth0-webhook")

# Global session to enable connection pooling for Auth0 API calls
http_session = requests.Session()

endpoint_url = os.environ.get("AWS_ENDPOINT_URL")
if endpoint_url:
    dynamodb = boto3.resource('dynamodb', endpoint_url=endpoint_url, region_name='ap-south-1')
else:
    dynamodb = boto3.resource('dynamodb')

table = dynamodb.Table(TABLE_NAME)

def get_auth0_token() -> str:
    """Fetches an Auth0 API token using the global requests Session."""
    url = f"https://{AUTH0_DOMAIN}/oauth/token"
    payload = {
        "grant_type": "client_credentials",
        "client_id": AUTH0_CLIENT_ID,
        "client_secret": AUTH0_CLIENT_SECRET,
        "audience": f"https://{AUTH0_DOMAIN}/api/v2/"
    }
    response = http_session.post(url, json=payload)
    response.raise_for_status()
    return response.json()["access_token"]

def unblock_user(phone: str, token: str) -> None:
    """Executes the DELETE request to unblock a user."""
    encoded_phone = urllib.parse.quote(phone)
    url = f"https://{AUTH0_DOMAIN}/api/v2/user-blocks?identifier={encoded_phone}"
    headers = {
        "Authorization": f"Bearer {token}"
    }
    response = http_session.delete(url, headers=headers)
    
    # Auth0 returns 404 if the user isn't found/blocked, which is a success condition here
    if response.status_code >= 400 and response.status_code != 404:
        response.raise_for_status()
