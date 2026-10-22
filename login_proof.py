#!/usr/bin/env python3
"""
MT5 Executor — Milestone 1: LOGIN PROOF ONLY.

Logs in to the account described by environment variables, prints the
account info, verifies the account is a DEMO account, and shuts down.

There is deliberately NO order function in this file. Milestone 1 proves
the connection only — nothing is traded, opened, modified, or closed.

Credentials come from the environment (GitHub Actions secrets in CI —
never hardcoded, never in chat):
    MT5_LOGIN     account login (number)
    MT5_PASSWORD  trading password
    MT5_SERVER    broker server name (e.g. Exness-MT5Trial16)

Runs on Windows (the MetaTrader5 package is Windows-only) and REQUIRES
a locally installed MetaTrader 5 terminal: the Python package talks to
the terminal over IPC. The workflow installs the terminal first
(official MetaQuotes installer). Run #1 (2026-10-22) proved this the
hard way: without a terminal, initialize() fails with
(-10003, 'IPC initialize failed, MetaTrader 5 x64 not found').

Exit codes: 0 = login proof OK, 1 = setup/initialize/login failure.
"""

import os
import sys
import time

TERMINAL_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"
INIT_ATTEMPTS = 3
INIT_RETRY_DELAY_S = 15


def fail(message: str) -> "SystemExit":
    print(f"ERROR: {message}", flush=True)
    return SystemExit(1)


def main() -> int:
    login_raw = os.environ.get("MT5_LOGIN", "").strip()
    password = os.environ.get("MT5_PASSWORD", "")
    server = os.environ.get("MT5_SERVER", "").strip()

    if not login_raw or not password or not server:
        raise fail(
            "Missing environment variables. MT5_LOGIN, MT5_PASSWORD and "
            "MT5_SERVER must all be set (in GitHub: repo Settings > "
            "Secrets and variables > Actions)."
        )

    try:
        login = int(login_raw)
    except ValueError:
        raise fail(f"MT5_LOGIN must be a number, got: {login_raw!r}")

    # Imported here (not at module top) so this file still byte-compiles
    # and stays importable on non-Windows machines for inspection.
    try:
        import MetaTrader5 as mt5
    except ImportError:
        raise fail(
            "MetaTrader5 package is not installed. It is Windows-only: "
            "run this on Windows / a windows-latest GitHub Actions runner "
            "after `pip install MetaTrader5`."
        )

    print(f"Connecting: login={login} server={server} ...", flush=True)

    init_kwargs = dict(login=login, password=password, server=server,
                       timeout=180000)
    if os.path.exists(TERMINAL_PATH):
        init_kwargs["path"] = TERMINAL_PATH
        print(f"Using terminal: {TERMINAL_PATH}", flush=True)
    else:
        print(f"Terminal not found at {TERMINAL_PATH}; "
              "letting the package locate it.", flush=True)

    ok = False
    for attempt in range(1, INIT_ATTEMPTS + 1):
        if mt5.initialize(**init_kwargs):
            ok = True
            break
        print(f"mt5.initialize() attempt {attempt} failed: "
              f"{mt5.last_error()}", flush=True)
        try:
            mt5.shutdown()
        except Exception:
            pass
        if attempt < INIT_ATTEMPTS:
            print(f"Retrying in {INIT_RETRY_DELAY_S}s ...", flush=True)
            time.sleep(INIT_RETRY_DELAY_S)

    if not ok:
        print("All initialize() attempts failed (see errors above).",
              flush=True)
        return 1

    try:
        info = mt5.account_info()
        if info is None:
            print(f"mt5.account_info() returned None: {mt5.last_error()}", flush=True)
            return 1

        # trade_mode values (ENUM_ACCOUNT_TRADE_MODE):
        #   0 = ACCOUNT_TRADE_MODE_DEMO
        #   1 = ACCOUNT_TRADE_MODE_CONTEST
        #   2 = ACCOUNT_TRADE_MODE_REAL
        trade_mode_names = {0: "DEMO", 1: "CONTEST", 2: "REAL"}
        trade_mode = getattr(info, "trade_mode", None)
        trade_mode_label = trade_mode_names.get(trade_mode, f"UNKNOWN ({trade_mode})")

        print("=" * 56)
        print("MT5 ACCOUNT INFO")
        print("=" * 56)
        print(f"login:      {info.login}")
        print(f"server:     {info.server}")
        print(f"balance:    {info.balance}")
        print(f"equity:     {info.equity}")
        print(f"currency:   {info.currency}")
        print(f"trade_mode: {trade_mode} ({trade_mode_label})")
        print(f"leverage:   {info.leverage}")
        name = getattr(info, "name", "")
        if name:
            print(f"name:       {name}")
        print("=" * 56)

        if trade_mode in (0, 1):
            print("*** DEMO ACCOUNT CONFIRMED ***")
            return 0

        print("*** WARNING: NOT A DEMO ACCOUNT ***")
        print("Milestone 1 expects a DEMO account. Stopping here —")
        print("no further action taken (this script never trades).")
        return 1
    finally:
        mt5.shutdown()
        print("MT5 connection closed (mt5.shutdown()).", flush=True)


if __name__ == "__main__":
    sys.exit(main())
