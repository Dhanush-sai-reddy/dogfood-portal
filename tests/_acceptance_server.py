"""A minimal standalone server for the acceptance checker."""
import sys
import socket
import uvicorn
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.main import create_app
from app.config import Settings

settings = Settings.from_env()
app = create_app()
app.state.settings = settings

class PortWritingServer(uvicorn.Server):
    def __init__(self, config, port_file):
        super().__init__(config)
        self.port_file = port_file
    
    async def startup(self, sockets=None):
        await super().startup(sockets)
        # Write the actual port after server binds
        for server in self.servers:
            for sock in server.sockets:
                port = sock.getsockname()[1]
                self.port_file.write_text(f"http://127.0.0.1:{port}")
                print(f"Portal ready at http://127.0.0.1:{port}", file=sys.stderr)
                return

def main():
    port_file = Path(sys.argv[1])
    config = uvicorn.Config(
        app,  # Pass app directly, not string
        host="127.0.0.1",
        port=0,
        log_level="warning",
    )
    server = PortWritingServer(config, port_file)
    server.run()

if __name__ == "__main__":
    main()
