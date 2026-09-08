"""AEGIS Trading Agent — Autonomous trading on IB paper accounts.

Phase 0 mandate:
  • IBKR paper account + data pipeline + SQLite logging
  • Hard limits:
    - Max position: 5% of paper equity
    - Max daily drawdown: 2% of paper equity
    - Max open positions: 5
    - Equities only (no options, futures, crypto, leverage)
    - Stop-loss required on every position before entry
    - Zero live capital until Phase 2 gate approval
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

from agent.ib_gateway_auth import IBGatewayAuthManager, IBSessionToken


@dataclass
class Position:
    """Open trading position."""

    symbol: str
    quantity: int
    entry_price: float
    entry_time: datetime
    stop_loss_price: float
    max_position_value: float  # 5% of account
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    pnl: Optional[float] = None
    closed: bool = False

    def current_pnl(self, current_price: float) -> float:
        """Calculate unrealized P&L at current price."""
        if self.closed:
            return self.pnl or 0
        return (current_price - self.entry_price) * self.quantity

    def is_stopped_out(self, current_price: float) -> bool:
        """Check if position hit stop loss."""
        if self.closed:
            return False
        if self.quantity > 0:  # Long
            return current_price <= self.stop_loss_price
        else:  # Short
            return current_price >= self.stop_loss_price


@dataclass
class AEGISState:
    """AEGIS agent state and trading constraints."""

    account_id: str = "paper"
    account_equity: float = 100_000.0  # Initial paper trading equity
    daily_return_pct: float = 0.0
    daily_max_loss_pct: float = -2.0  # Hard stop at -2%
    max_position_count: int = 5
    current_positions: List[Position] = field(default_factory=list)
    closed_today: List[Position] = field(default_factory=list)
    session_token: Optional[IBSessionToken] = None

    def max_position_size(self) -> float:
        """Maximum value per position (5% of account)."""
        return self.account_equity * 0.05

    def available_positions(self) -> int:
        """How many more positions can be opened."""
        return self.max_position_count - len(self.current_positions)

    def daily_pnl(self) -> float:
        """Total P&L for today across all positions."""
        realized_pnl = sum(p.pnl for p in self.closed_today if p.pnl)
        unrealized_pnl = sum(p.current_pnl(0) for p in self.current_positions)
        return realized_pnl + unrealized_pnl

    def daily_pnl_pct(self) -> float:
        """Daily P&L as percentage of starting equity."""
        starting_equity = 100_000.0
        return (self.daily_pnl() / starting_equity) * 100

    def can_open_position(self, position_value: float) -> bool:
        """Check if a new position can be opened."""
        constraints = [
            len(self.current_positions) < self.max_position_count,
            position_value <= self.max_position_size(),
            self.daily_pnl_pct() > self.daily_max_loss_pct,
        ]
        return all(constraints)


class AEGISTrader:
    """AEGIS trading system for IB paper accounts."""

    def __init__(self, data_dir: Optional[Path] = None):
        """Initialize AEGIS trader.

        Args:
            data_dir: Directory for SQLite logs and position history.
                      Defaults to ~/.hermes/aegis/
        """
        if data_dir is None:
            data_dir = Path.home() / ".hermes" / "aegis"

        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = self.data_dir / "trading.db"
        self.auth_manager = IBGatewayAuthManager()
        self.state = AEGISState()

        self._init_database()

    def _init_database(self) -> None:
        """Initialize SQLite logging database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Trades log
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL,
                stop_loss REAL NOT NULL,
                pnl REAL,
                pnl_pct REAL,
                account_equity REAL,
                closed BOOLEAN DEFAULT 0
            )
        """
        )

        # Daily performance log
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_performance (
                date DATE PRIMARY KEY,
                opening_equity REAL NOT NULL,
                closing_equity REAL NOT NULL,
                daily_pnl REAL NOT NULL,
                daily_pnl_pct REAL NOT NULL,
                positions_opened INTEGER DEFAULT 0,
                positions_closed INTEGER DEFAULT 0,
                max_positions INTEGER DEFAULT 0,
                notes TEXT
            )
        """
        )

        # Constraint violations log (for audit)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS constraint_checks (
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                check_type TEXT NOT NULL,
                violation_type TEXT,
                description TEXT,
                action_taken TEXT
            )
        """
        )

        conn.commit()
        conn.close()

    def log_trade(
        self,
        symbol: str,
        side: str,
        quantity: int,
        entry_price: float,
        stop_loss: float,
        exit_price: Optional[float] = None,
        pnl: Optional[float] = None,
    ) -> None:
        """Log a trade to SQLite.

        Args:
            symbol: Ticker symbol
            side: 'buy' or 'sell'
            quantity: Number of shares
            entry_price: Entry price per share
            stop_loss: Stop loss price
            exit_price: Exit price (if closed)
            pnl: Realized P&L (if closed)
        """
        pnl_pct = None
        if pnl and entry_price:
            pnl_pct = (pnl / (entry_price * abs(quantity))) * 100

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO trades
            (symbol, side, quantity, entry_price, exit_price,
             stop_loss, pnl, pnl_pct, account_equity, closed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                symbol,
                side,
                quantity,
                entry_price,
                exit_price,
                stop_loss,
                pnl,
                pnl_pct,
                self.state.account_equity,
                exit_price is not None,
            ),
        )

        conn.commit()
        conn.close()

    def check_constraints(self) -> Dict[str, Any]:
        """Audit trading constraints.

        Returns:
            Dict with constraint check results
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        violations = []

        # Check max positions
        if len(self.state.current_positions) > self.state.max_position_count:
            violations.append(
                f"Max positions exceeded: "
                f"{len(self.state.current_positions)} > {self.state.max_position_count}"
            )

        # Check daily drawdown
        daily_pnl_pct = self.state.daily_pnl_pct()
        if daily_pnl_pct < self.state.daily_max_loss_pct:
            violations.append(
                f"Daily max loss exceeded: {daily_pnl_pct:.2f}% < {self.state.daily_max_loss_pct}%"
            )

        # Check position sizes
        for pos in self.state.current_positions:
            if pos.max_position_value > self.state.max_position_size():
                violations.append(
                    f"Position size exceeded for {pos.symbol}: "
                    f"{pos.max_position_value:.2f} > {self.state.max_position_size():.2f}"
                )

        # Log audit check
        for violation in violations:
            cursor.execute(
                """
                INSERT INTO constraint_checks
                (check_type, violation_type, description, action_taken)
                VALUES (?, ?, ?, ?)
            """,
                ("constraint_audit", "violation", violation, "ALERT_SENT"),
            )

        conn.commit()
        conn.close()

        return {
            "timestamp": datetime.now().isoformat(),
            "constraints_ok": len(violations) == 0,
            "violations": violations,
            "current_positions": len(self.state.current_positions),
            "daily_pnl_pct": daily_pnl_pct,
            "account_equity": self.state.account_equity,
        }

    def ensure_gateway_connected(self) -> bool:
        """Ensure IB Gateway is authenticated and connected.

        Returns:
            True if connected, False otherwise
        """
        # Check for valid session token
        token = self.auth_manager.load_session_token()
        if not token:
            print("❌ No valid IB Gateway session. Run ib-gateway-login.py first.")
            return False

        self.state.session_token = token

        # Verify gateway is accessible
        if not self.auth_manager.is_gateway_accessible():
            print("❌ IB Gateway not accessible on localhost:4001")
            return False

        hours_remaining = (token.expires_at - time.time()) / 3600
        print(f"✅ IB Gateway connected (session expires in {hours_remaining:.1f}h)")
        return True

    def daily_summary(self) -> str:
        """Generate daily trading summary."""
        summary = f"""
        AEGIS Daily Summary
        {'='*50}
        Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        Account: {self.state.account_id}
        Equity: ${self.state.account_equity:,.2f}
        Daily P&L: ${self.state.daily_pnl():,.2f} ({self.state.daily_pnl_pct():.2f}%)
        Open Positions: {len(self.state.current_positions)}/{self.state.max_position_count}
        Closed Today: {len(self.state.closed_today)}

        Constraints Status:
        {'='*50}
        """

        audit = self.check_constraints()
        if audit["constraints_ok"]:
            summary += "✅ All constraints met\n"
        else:
            summary += "⚠️  Constraint violations:\n"
            for violation in audit["violations"]:
                summary += f"  • {violation}\n"

        return summary
