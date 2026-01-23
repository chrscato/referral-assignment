#!/usr/bin/env python3
"""
Convenience script to run the Referral CRM.
"""

import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))


def run_cli():
    """Run the CLI application."""
    from referral_crm.cli import app
    app()


def run_api():
    """Run the FastAPI server."""
    import uvicorn
    uvicorn.run(
        "referral_crm.api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


def run_ingestion():
    """Run email ingestion once."""
    from referral_crm.automations.email_ingestion import run_ingestion
    run_ingestion()


def run_poller():
    """Run continuous email polling."""
    from referral_crm.automations.email_ingestion import EmailPoller
    poller = EmailPoller()
    poller.start()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run.py <command>")
        print()
        print("Commands:")
        print("  cli       Run the command-line interface")
        print("  api       Start the FastAPI web server")
        print("  ingest    Run email ingestion once")
        print("  poll      Start continuous email polling")
        sys.exit(1)

    command = sys.argv[1]
    sys.argv = [sys.argv[0]] + sys.argv[2:]  # Remove command from args

    commands = {
        "cli": run_cli,
        "api": run_api,
        "ingest": run_ingestion,
        "poll": run_poller,
    }

    if command not in commands:
        print(f"Unknown command: {command}")
        sys.exit(1)

    commands[command]()
