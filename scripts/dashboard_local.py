"""ダッシュボードをローカルで起動する。"""

import sys
from http.server import HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from api.index import handler

PORT = 8000

if __name__ == "__main__":
    print(f"Dashboard running at http://localhost:{PORT}/")
    print("Press Ctrl+C to stop")
    server = HTTPServer(("", PORT), handler)
    server.serve_forever()
