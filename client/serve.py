"""
SHAKTI — Local development server
Run this from the client folder:

    python serve.py

Then open:  http://localhost:3000

Chrome will remember mic permission permanently for localhost.
"""
import http.server
import socketserver
import os

PORT = 3000
os.chdir(os.path.dirname(os.path.abspath(__file__)))

class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress request logs

print(f"\n  SHAKTI server running at http://localhost:{PORT}")
print(f"  Open this URL in Chrome — mic permission will be remembered.\n")
print(f"  Press Ctrl+C to stop.\n")

with socketserver.TCPServer(("", PORT), Handler) as httpd:
    httpd.serve_forever()