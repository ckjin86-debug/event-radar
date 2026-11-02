"""OAuth Bootstrap helper for setting up Google Drive offline refresh token.

Run locally:
python scripts/oauth_bootstrap.py
"""

import sys
import urllib.parse
import requests


def main():
    print("=== Event Radar Google Drive OAuth 2.0 Bootstrap ===")
    print("1. Create an OAuth 2.0 Client ID (Desktop or Web) in Google Cloud Console.")
    print("2. Ensure Google Drive API is enabled in your Google Cloud Project.")
    print("3. Enter your Client ID and Client Secret below.\n")

    client_id = input("Enter GOOGLE_CLIENT_ID: ").strip()
    if not client_id:
        print("Error: Client ID is required.")
        return

    client_secret = input("Enter GOOGLE_CLIENT_SECRET: ").strip()
    if not client_secret:
        print("Error: Client Secret is required.")
        return

    redirect_uri = "https://oauth.pstmn.io/v1/browser-callback"
    scope = "https://www.googleapis.com/auth/drive.file"

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "access_type": "offline",
        "prompt": "consent",
    }
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"

    print("\n------------------------------------------------------------")
    print("Open the following authorization URL in your browser:")
    print(auth_url)
    print("------------------------------------------------------------\n")

    auth_code = input("Paste the authorization code from the redirect URL (?code=...): ").strip()
    if not auth_code:
        print("Error: Authorization code is required.")
        return

    # Exchange code for refresh token
    token_url = "https://oauth2.googleapis.com/token"
    token_data = {
        "code": auth_code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }

    try:
        resp = requests.post(token_url, data=token_data, timeout=15)
        if resp.status_code == 200:
            res_json = resp.json()
            refresh_token = res_json.get("refresh_token")
            print("\nSUCCESS! Add the following secrets to your GitHub repository:")
            print(f"GOOGLE_CLIENT_ID: {client_id}")
            print(f"GOOGLE_CLIENT_SECRET: {client_secret}")
            print(f"GOOGLE_REFRESH_TOKEN: {refresh_token}")
            print("GOOGLE_DRIVE_FOLDER_ID: <ID of target Google Drive Folder>")
        else:
            print(f"\nFailed to retrieve refresh token: {resp.text}")
    except Exception as e:
        print(f"\nError exchanging code: {e}")


if __name__ == "__main__":
    main()
