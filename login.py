from kiteconnect import KiteConnect
from dotenv import load_dotenv
import os

load_dotenv()

api_key = os.getenv("KITE_API_KEY")

kite = KiteConnect(api_key=api_key)

print(kite.login_url())
