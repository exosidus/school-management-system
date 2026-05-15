#!/usr/bin/env python3
"""
e-School: Ethiopian Secondary School Information Management System
Run script for production deployment
"""

from app import app
import os

if __name__ == "__main__":
    # Get port from environment variable or default to 5000
    port = int(os.environ.get("PORT", 5000))

    # Get debug mode from environment variable
    debug = os.environ.get("DEBUG", "False").lower() == "true"

    # Run the application
    app.run(host="0.0.0.0", port=port, debug=debug)
