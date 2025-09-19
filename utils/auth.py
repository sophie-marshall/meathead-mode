import http.server
from urllib.parse import parse_qs, urlparse


class OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    """Handles the OAuth callback and extracts the authorization code."""

    callback_code = None

    def do_GET(self):
        # parse callback url
        url = urlparse(self.path)
        params = parse_qs(url.query)

        if "code" in params:
            OAuthCallbackHandler.callback_code = params["code"][0]

            # mark as success
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"Authorization successful! You can close this window.")
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing authorization code in the callback URL.")
