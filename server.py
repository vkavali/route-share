"""Run the closed-beta app on loopback for local development."""

import ipaddress
import os
import sys

from app import create_app


def main() -> None:
    host = os.environ.get("HOST", "127.0.0.1")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if host.lower() != "localhost":
            raise SystemExit("HOST must be localhost, 127.0.0.1, or ::1")
    else:
        if not address.is_loopback:
            raise SystemExit("Refusing non-loopback binding for the local closed beta")
    try:
        port = int(os.environ.get("PORT", "5000"))
    except ValueError:
        raise SystemExit("PORT must be an integer from 1 to 65535") from None
    if not 1 <= port <= 65535:
        raise SystemExit("PORT must be an integer from 1 to 65535")

    app = create_app()
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
