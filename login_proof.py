#!/usr/bin/env python3
"""
MT5 Executor — Milestone 1: LOGIN PROOF ONLY.

Prints the logged-in account info, verifies the account is a DEMO
account, and shuts down. There is deliberately NO order function in
this file — nothing is traded, opened, modified, or closed.

How the login happens (v3, after two failed runs taught us the shape):
  - The workflow installs the MetaTrader 5 terminal, then launches it
    with a startup config (built from secrets, kept outside the repo)
    so the TERMINAL logs itself into the account, and waits ~2 min
    for first-run init/update to settle.
  - This script first tries to ATTACH to that already-running,
    already-logged-in terminal (initialize with the terminal path,
    no credentials).
  - If no account is logged in, it falls back to a credential
    initialize() with the env secrets, with retries.

Run history:
  #1 (-10003 'MetaTrader 5 x64 not found') — no terminal installed.
  #2 (-10005 'IPC timeout' x3) — terminal installed but cold-started
     by Python; first-run init/wizard kept IPC from ever coming up.

Credentials come from the environment (GitHub Actions secrets —
never hardcoded, never in chat): MT5_LOGIN, MT5_PASSWORD, MT5_SERVER.

Exit codes: 0 = login proof OK, 1 = any failure.
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


def report_account(mt5) -> int:
    """Print the account block; return 0 iff a DEMO/CONTEST account."""
    info = mt5.account_info()
    if info is None:
        print(f"mt5.account_info() returned None: {mt5.last_error()}", flush=True)
        return 1

    # trade_mode values (ENUM_ACCOUNT_TRADE_MODE):
    #   0 = DEMO, 1 = CONTEST, 2 = REAL
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

    path_kw = {}
    if os.path.exists(TERMINAL_PATH):
        path_kw["path"] = TERMINAL_PATH
        print(f"Using terminal: {TERMINAL_PATH}", flush=True)

    try:
        # --- Path A: attach to the terminal the workflow pre-launched
        # (it logged itself in via the startup config).
        print("Attach attempt: initialize() against running terminal ...",
              flush=True)
        if mt5.initialize(**path_kw):
            info = mt5.account_info()
            if info is not None and getattr(info, "login", None):
                print(f"Attached. Terminal already logged in as "
                      f"{info.login}.", flush=True)
                return report_account(mt5)
            print("Attached but no account logged in; "
                  "falling back to credential login.", flush=True)
            mt5.shutdown()
        else:
            print(f"Attach failed: {mt5.last_error()}", flush=True)
            try:
                mt5.shutdown()
            except Exception:
                pass

        # --- Path B: credential initialize, with retries.
        print(f"Credential login: login={login} server={server} ...",
              flush=True)
        for attempt in range(1, INIT_ATTEMPTS + 1):
            if mt5.initialize(login=login, password=password,
                              server=server, timeout=120000, **path_kw):
                return report_account(mt5)
            print(f"initialize() attempt {attempt} failed: "
                  f"{mt5.last_error()}", flush=True)
            try:
                mt5.shutdown()
            except Exception:
                pass
            if attempt < INIT_ATTEMPTS:
                print(f"Retrying in {INIT_RETRY_DELAY_S}s ...", flush=True)
                time.sleep(INIT_RETRY_DELAY_S)

        print("All login attempts failed (see errors above).", flush=True)
        return 1
    finally:
        try:
            mt5.shutdown()
            print("MT5 connection closed (mt5.shutdown()).", flush=True)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
