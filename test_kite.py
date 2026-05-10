from kiteconnect import KiteConnect
from dotenv import load_dotenv
import os

load_dotenv()

api_key = os.getenv("KITE_API_KEY")
api_secret = os.getenv("KITE_API_SECRET")

request_token = "oc7lHs4IwBbVlvp3K7SaFZKreJPq8QZu"

kite = KiteConnect(api_key=api_key)

data = kite.generate_session(
    request_token,
    api_secret=api_secret
)

access_token = data["access_token"]

kite.set_access_token(access_token)

print("\nPROFILE:\n")
print(kite.profile())

print("\nHOLDINGS:\n")
print(kite.holdings())
