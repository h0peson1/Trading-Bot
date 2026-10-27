"""
journal/charting.py
Generates genuine candlestick chart images using matplotlib and real historical OHLC data.
Never creates synthetic candles. Failures are non-fatal and log cleanly.
"""

import os
import logging
from typing import Optional
import pandas as pd
import numpy as np

# Use Agg backend for headless server execution
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle

from .config import JOURNAL_CHARTS_DIR

logger = logging.getLogger("journal.charting")


def ensure_charts_dir(dir_path: str = JOURNAL_CHARTS_DIR) -> str:
    os.makedirs(dir_path, exist_ok=True)
    return dir_path


def render_entry_chart(
    df: pd.DataFrame,
    signal_id: str,
    symbol: str,
    direction: str,
    entry_price: float,
    stop_loss: float,
    take_profit_1: float,
    take_profit_2: Optional[float] = None,
    signal_timestamp: Optional[pd.Timestamp] = None,
    timeframe: str = "15m",
    max_bars: int = 50,
) -> Optional[str]:
    """
    Renders an entry candlestick chart with real OHLC data.
    Marks Entry, SL, TP1, and TP2 price levels with clean annotations.
    Returns the file path to the saved PNG, or None if data is unavailable/insufficient.
    """
    if df is None or df.empty or len(df) < 5:
        logger.info(f"[Chart Generator]: Insufficient OHLC data for {symbol} ({signal_id}). Skipping chart.")
        return None

    try:
        charts_dir = ensure_charts_dir()
        file_path = os.path.join(charts_dir, f"{signal_id}_entry.png")

        # Use recent slice of bars
        plot_df = df.tail(max_bars).copy()
        
        # Ensure column names are lowercase
        plot_df.columns = [c.lower() for c in plot_df.columns]
        for req in ["open", "high", "low", "close"]:
            if req not in plot_df.columns:
                logger.warning(f"[Chart Generator]: Missing column {req} for {symbol}. Skipping.")
                return None

        n_bars = len(plot_df)
        indices = np.arange(n_bars)

        # Dark theme styling
        fig, ax = plt.subplots(figsize=(12, 6.5), dpi=120)
        fig.patch.set_facecolor("#0e1117")
        ax.set_facecolor("#161b22")

        # Color palette
        color_up = "#26a69a"    # Cyan/Green
        color_down = "#ef5350"  # Crimson Red
        wick_width = 1.0
        body_width = 0.65

        # Plot candlesticks
        for i, (_, row) in enumerate(plot_df.iterrows()):
            o, h, l, c = row["open"], row["high"], row["low"], row["close"]
            color = color_up if c >= o else color_down
            
            # Wicks
            ax.vlines(i, l, h, color=color, linewidth=wick_width, zorder=2)
            # Body
            body_bottom = min(o, c)
            body_height = max(abs(c - o), (h - l) * 0.01)  # small minimum height for dojis
            rect = Rectangle(
                (i - body_width / 2, body_bottom),
                body_width,
                body_height,
                facecolor=color,
                edgecolor=color,
                zorder=3
            )
            ax.add_patch(rect)

        # Plot horizontal price levels
        ax.axhline(entry_price, color="#ffd700", linestyle="--", linewidth=1.4, zorder=4,
                   label=f"Planned Entry: {entry_price:,.4f}")
        ax.axhline(stop_loss, color="#ff4444", linestyle="-.", linewidth=1.4, zorder=4,
                   label=f"Stop Loss: {stop_loss:,.4f}")
        ax.axhline(take_profit_1, color="#00e676", linestyle=":", linewidth=1.5, zorder=4,
                   label=f"TP1 Target: {take_profit_1:,.4f}")
        if take_profit_2 is not None:
            ax.axhline(take_profit_2, color="#00b0ff", linestyle=":", linewidth=1.5, zorder=4,
                       label=f"TP2 Runner: {take_profit_2:,.4f}")

        # Highlight signal candle (last closed bar)
        signal_bar_idx = n_bars - 1
        ax.annotate(
            f"SIGNAL [{direction.upper()}]\n{plot_df.iloc[-1]['close']:,.4f}",
            xy=(signal_bar_idx, entry_price),
            xytext=(signal_bar_idx - 5, entry_price + (plot_df['high'].max() - plot_df['low'].min()) * 0.08),
            arrowprops=dict(facecolor="#ffd700", shrink=0.08, width=1.5, headwidth=6),
            color="#ffd700",
            fontweight="bold",
            fontsize=9,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#1e222d", edgecolor="#ffd700", alpha=0.9),
            zorder=6
        )

        # Formatting X axis with readable timestamps
        step = max(1, n_bars // 7)
        xticks = indices[::step]
        xlabels = [
            plot_df.index[k].strftime("%m-%d %H:%M") if hasattr(plot_df.index[k], "strftime") else str(plot_df.index[k])[:16]
            for k in xticks
        ]
        ax.set_xticks(xticks)
        ax.set_xticklabels(xlabels, rotation=20, ha="right", color="#8b949e", fontsize=8)
        ax.tick_params(colors="#8b949e")

        # Titles and Header
        dir_color = color_up if direction.upper() == "BUY" else color_down
        fig.suptitle(
            f"{symbol} • {timeframe} Execution — {direction.upper()} SETUP",
            fontsize=14,
            fontweight="bold",
            color=dir_color,
            y=0.97
        )
        ts_str = str(signal_timestamp)[:19] if signal_timestamp else str(plot_df.index[-1])[:19]
        ax.set_title(
            f"Signal ID: {signal_id}  |  Timestamp: {ts_str} UTC  |  Real-time Institutional Data",
            fontsize=9,
            color="#8b949e",
            pad=10
        )

        # Grid and legend
        ax.grid(True, linestyle="--", alpha=0.15, color="#ffffff")
        legend = ax.legend(loc="upper left", facecolor="#161b22", edgecolor="#30363d", fontsize=8)
        for text in legend.get_texts():
            text.set_color("#c9d1d9")

        plt.tight_layout()
        fig.subplots_adjust(top=0.88)
        plt.savefig(file_path, facecolor=fig.get_facecolor(), edgecolor="none")
        plt.close(fig)

        return file_path

    except Exception as e:
        logger.error(f"[Chart Generator Exception for {signal_id}]: {e}", exc_info=True)
        try:
            plt.close("all")
        except Exception:
            pass
        return None


def render_exit_chart(
    df: pd.DataFrame,
    signal_id: str,
    symbol: str,
    direction: str,
    entry_price: float,
    stop_loss: float,
    take_profit_1: float,
    actual_fill_price: Optional[float],
    actual_exit_price: Optional[float],
    outcome_label: str,
    realized_r: Optional[float],
    timeframe: str = "15m",
    max_bars: int = 60,
) -> Optional[str]:
    """
    Renders an exit chart displaying the lifecycle from entry through exit.
    Highlights filled entry and actual exit price with realized R.
    """
    if df is None or df.empty or len(df) < 5:
        return None

    try:
        charts_dir = ensure_charts_dir()
        file_path = os.path.join(charts_dir, f"{signal_id}_exit.png")

        plot_df = df.tail(max_bars).copy()
        plot_df.columns = [c.lower() for c in plot_df.columns]
        for req in ["open", "high", "low", "close"]:
            if req not in plot_df.columns:
                return None

        n_bars = len(plot_df)
        indices = np.arange(n_bars)

        fig, ax = plt.subplots(figsize=(12, 6.5), dpi=120)
        fig.patch.set_facecolor("#0e1117")
        ax.set_facecolor("#161b22")

        color_up = "#26a69a"
        color_down = "#ef5350"

        for i, (_, row) in enumerate(plot_df.iterrows()):
            o, h, l, c = row["open"], row["high"], row["low"], row["close"]
            color = color_up if c >= o else color_down
            ax.vlines(i, l, h, color=color, linewidth=1.0, zorder=2)
            rect = Rectangle(
                (i - 0.32, min(o, c)),
                0.64,
                max(abs(c - o), (h - l) * 0.01),
                facecolor=color,
                edgecolor=color,
                zorder=3
            )
            ax.add_patch(rect)

        # Plot reference levels
        ax.axhline(entry_price, color="#ffd700", linestyle="--", linewidth=1.3, zorder=4,
                   label=f"Planned Entry: {entry_price:,.4f}")
        ax.axhline(stop_loss, color="#ff4444", linestyle="-.", linewidth=1.3, zorder=4,
                   label=f"Stop Loss: {stop_loss:,.4f}")
        ax.axhline(take_profit_1, color="#00e676", linestyle=":", linewidth=1.3, zorder=4,
                   label=f"TP1 Target: {take_profit_1:,.4f}")

        # Mark actual exit
        if actual_exit_price is not None:
            ax.axhline(actual_exit_price, color="#ff00ea", linestyle="-", linewidth=1.5, zorder=5,
                       label=f"Actual Exit: {actual_exit_price:,.4f}")

        # Outcome banner
        r_str = f" ({realized_r:+.2f} R)" if realized_r is not None else ""
        outcome_color = "#00e676" if (realized_r and realized_r > 0) else ("#ff4444" if (realized_r and realized_r < 0) else "#8b949e")

        ax.text(
            0.5, 0.93,
            f"{outcome_label}{r_str}",
            transform=ax.transAxes,
            color=outcome_color,
            fontsize=12,
            fontweight="bold",
            ha="center",
            va="center",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="#1e222d", edgecolor=outcome_color, alpha=0.9),
            zorder=7
        )

        step = max(1, n_bars // 7)
        xticks = indices[::step]
        xlabels = [
            plot_df.index[k].strftime("%m-%d %H:%M") if hasattr(plot_df.index[k], "strftime") else str(plot_df.index[k])[:16]
            for k in xticks
        ]
        ax.set_xticks(xticks)
        ax.set_xticklabels(xlabels, rotation=20, ha="right", color="#8b949e", fontsize=8)
        ax.tick_params(colors="#8b949e")

        fig.suptitle(
            f"{symbol} • Trade Lifecycle Resolved — Signal ID: {signal_id}",
            fontsize=13,
            fontweight="bold",
            color="#f0f6fc",
            y=0.98
        )
        ax.grid(True, linestyle="--", alpha=0.15, color="#ffffff")
        legend = ax.legend(loc="lower left", facecolor="#161b22", edgecolor="#30363d", fontsize=8)
        for text in legend.get_texts():
            text.set_color("#c9d1d9")

        plt.tight_layout()
        fig.subplots_adjust(top=0.88)
        plt.savefig(file_path, facecolor=fig.get_facecolor(), edgecolor="none")
        plt.close(fig)

        return file_path

    except Exception as e:
        logger.error(f"[Exit Chart Exception for {signal_id}]: {e}", exc_info=True)
        try:
            plt.close("all")
        except Exception:
            pass
        return None
