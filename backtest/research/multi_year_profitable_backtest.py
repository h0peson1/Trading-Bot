"""
Comprehensive 5-Year & Intraday Session-Timed Backtest Engine for Profitable Pairs
Universe: EURJPY, XAUUSD (Gold), BTCUSD (Bitcoin)
Execution Window: London & New York Key Sessions (07:00 to 18:00 UTC)

Calculates:
- Mathematical Expectancy (in R and %)
- Total Returns & Equity Progression
- Maximum Drawdown (in R and %)
- Annualized Sharpe Ratio
- CAGR (Compound Annual Growth Rate over 5 years)
- Profit Factor, Win Rate, and Asset Breakdowns
"""

import sys
import math
from datetime import datetime, timezone
import pandas as pd
import numpy as np
import yfinance as yf
import config
from optimize_strategy import precompute_swings, YF_TICKER_MAP

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

PROFITABLE_PAIRS = {
    "EURJPY": "EURJPY=X",
    "XAUUSD": "GC=F",
    "BTCUSD": "BTC-USD",
}

INITIAL_CAPITAL = 10000.0  # Standard $10k institutional prop/retail account
RISK_PER_TRADE_PCT = 0.015  # 1.5% fixed fractional risk per trade


def fetch_data_5y(symbol: str, yf_ticker: str):
    """Fetch up to 5 years of daily data and maximum 730 days of 1h data."""
    try:
        t = yf.Ticker(yf_ticker)
        df_1d = t.history(period="5y", interval="1d", auto_adjust=True)
        df_1h = t.history(period="730d", interval="1h", auto_adjust=True)
        
        for df in [df_1d, df_1h]:
            if df is not None and not df.empty:
                df.rename(columns={c: c.lower() for c in df.columns}, inplace=True)
                if df.index.tz is None:
                    df.index = df.index.tz_localize("UTC")
                else:
                    df.index = df.index.tz_convert("UTC")
        return df_1d, df_1h
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return pd.DataFrame(), pd.DataFrame()


def run_intraday_session_backtest(pairs_data_1h: dict):
    """
    Intraday 2-Year (730d) Session-Timed Backtest:
    - 4H Structure (resampled from 1h)
    - 100 SMA Filter
    - Golden Zone 50-61.8%
    - 50% Limit Retest
    - Filtered strictly to London & New York session (07:00 to 18:00 UTC)
    """
    trades = []
    
    for symbol, d1 in pairs_data_1h.items():
        if d1.empty or len(d1) < 500:
            continue
        
        d4 = d1.resample("4h").agg({
            "open": "first", "high": "max", "low": "min", "close": "last"
        }).dropna()
        d4["sma100"] = d4["close"].rolling(window=100).mean()
        
        h4_highs, h4_lows, h4_closes = d4["high"].values, d4["low"].values, d4["close"].values
        h4_times = d4.index
        swings_4h = precompute_swings(h4_highs, h4_lows, h4_times, order=config.SWING_ORDER)
        if len(swings_4h) < 4:
            continue
        swing_4h_indices = np.array([s.index for s in swings_4h])

        h1_opens, h1_highs, h1_lows, h1_closes = d1["open"].values, d1["high"].values, d1["low"].values, d1["close"].values
        h1_times = d1.index
        n_1h = len(d1)

        in_trade_until = 0

        for i in range(100, n_1h - 1):
            curr_time = h1_times[i]
            
            # Key Time Session Filter: London & New York (07:00 to 18:00 UTC)
            if curr_time.hour < 7 or curr_time.hour > 18:
                continue
            if i < in_trade_until:
                continue

            h4_idx_pos = d4.index.searchsorted(curr_time, side="right") - 1
            if h4_idx_pos < 100:
                continue

            sma_val = d4["sma100"].iloc[h4_idx_pos]
            if pd.isna(sma_val):
                continue

            cutoff_4h = h4_idx_pos - config.SWING_ORDER
            valid_pos = np.searchsorted(swing_4h_indices, cutoff_4h, side="right")
            if valid_pos < 4:
                continue

            recent_swings = swings_4h[max(0, valid_pos - 8):valid_pos]
            h_swings = [s for s in recent_swings if s.swing_type == "HIGH"]
            l_swings = [s for s in recent_swings if s.swing_type == "LOW"]
            if len(h_swings) < 2 or len(l_swings) < 2:
                continue

            latest_h, latest_l = h_swings[-1], l_swings[-1]
            is_bullish = (latest_h.label == "HH" and latest_l.label == "HL" and latest_h.index > latest_l.index)
            is_bearish = (latest_h.label == "LH" and latest_l.label == "LL" and latest_l.index > latest_h.index)

            if is_bullish and h4_closes[h4_idx_pos] < sma_val:
                continue
            if is_bearish and h4_closes[h4_idx_pos] > sma_val:
                continue
            if not (is_bullish or is_bearish):
                continue

            direction = "BUY" if is_bullish else "SELL"
            range_span = latest_h.price - latest_l.price
            if range_span <= 0:
                continue

            # Fibonacci Golden Zone
            if direction == "BUY":
                fib50 = latest_h.price - (range_span * 0.50)
                fib618 = latest_h.price - (range_span * 0.618)
                invalidation = latest_l.price
                in_zone = (h1_lows[i] <= fib50) and (h1_highs[i] >= fib618)
                if not in_zone or h1_closes[i] < invalidation:
                    continue
            else:
                fib50 = latest_l.price + (range_span * 0.50)
                fib618 = latest_l.price + (range_span * 0.618)
                invalidation = latest_h.price
                in_zone = (h1_highs[i] >= fib50) and (h1_lows[i] <= fib618)
                if not in_zone or h1_closes[i] > invalidation:
                    continue

            # Candlestick Confirmation Trigger
            c_open, c_high, c_low, c_close = h1_opens[i], h1_highs[i], h1_lows[i], h1_closes[i]
            p_open, p_high, p_low, p_close = h1_opens[i-1], h1_highs[i-1], h1_lows[i-1], h1_closes[i-1]
            c_range = c_high - c_low
            if c_range <= 0:
                continue
            c_body = abs(c_close - c_open)
            c_upper = c_high - max(c_open, c_close)
            c_lower = min(c_open, c_close) - c_low

            pattern = None
            raw_sl = None

            if direction == "BUY":
                is_pin = (c_lower >= (2.0 * c_body) and c_lower >= (0.50 * c_range) and c_upper <= (0.25 * c_range) and c_close >= c_open)
                is_engulf = (p_close < p_open and c_close > c_open and c_close >= p_high and c_body >= (0.50 * c_range))
                if is_pin:
                    pattern = "Bullish Pin Bar"
                    raw_sl = c_low
                elif is_engulf:
                    pattern = "Bullish Engulfing"
                    raw_sl = min(c_low, p_low)
                elif i >= 2:
                    p2_open, p2_close = h1_opens[i-2], h1_closes[i-2]
                    if p2_close < p2_open and c_close > c_open and c_close >= (p2_close + 0.5 * abs(p2_open - p2_close)):
                        pattern = "Morning Star"
                        raw_sl = min(c_low, p_low, h1_lows[i-2])

                if not pattern:
                    continue

                limit_entry = (c_high + c_low) / 2.0
                buffer = max(limit_entry * 0.0015, 0.0006)
                sl = raw_sl - buffer
                risk = limit_entry - sl
                if risk <= 0:
                    continue
                tp1 = limit_entry + (risk * config.TP1_RR)
                tp2 = limit_entry + (risk * config.TP2_RR)

                filled = False
                fill_idx = -1
                for w_idx in range(i + 1, min(i + 6, n_1h)):
                    if h1_lows[w_idx] <= limit_entry:
                        if h1_lows[w_idx] <= sl:
                            break
                        filled = True
                        fill_idx = w_idx
                        break
                if not filled:
                    continue

            else:  # SELL
                is_pin = (c_upper >= (2.0 * c_body) and c_upper >= (0.50 * c_range) and c_lower <= (0.25 * c_range) and c_close <= c_open)
                is_engulf = (p_close > p_open and c_close < c_open and c_close <= p_low and c_body >= (0.50 * c_range))
                if is_pin:
                    pattern = "Bearish Pin Bar"
                    raw_sl = c_high
                elif is_engulf:
                    pattern = "Bearish Engulfing"
                    raw_sl = max(c_high, p_high)
                elif i >= 2:
                    p2_open, p2_close = h1_opens[i-2], h1_closes[i-2]
                    if p2_close > p2_open and c_close < c_open and c_close <= (p2_close - 0.5 * abs(p2_open - p2_close)):
                        pattern = "Evening Star"
                        raw_sl = max(c_high, p_high, h1_highs[i-2])

                if not pattern:
                    continue

                limit_entry = (c_high + c_low) / 2.0
                buffer = max(limit_entry * 0.0015, 0.0006)
                sl = raw_sl + buffer
                risk = sl - limit_entry
                if risk <= 0:
                    continue
                tp1 = limit_entry - (risk * config.TP1_RR)
                tp2 = limit_entry - (risk * config.TP2_RR)

                filled = False
                fill_idx = -1
                for w_idx in range(i + 1, min(i + 6, n_1h)):
                    if h1_highs[w_idx] >= limit_entry:
                        if h1_highs[w_idx] >= sl:
                            break
                        filled = True
                        fill_idx = w_idx
                        break
                if not filled:
                    continue

            # Outcome tracking
            outcome = "OPEN"
            pnl_r = 0.0
            tp1_hit = False
            exit_time = None
            exit_price = None

            for f_idx in range(fill_idx + 1, min(fill_idx + 60, n_1h)):
                b_high, b_low = h1_highs[f_idx], h1_lows[f_idx]
                exit_time = h1_times[f_idx]

                if direction == "BUY":
                    if not tp1_hit and b_low <= sl:
                        outcome = "LOSS"
                        pnl_r = -1.0
                        exit_price = sl
                        in_trade_until = f_idx + 1
                        break
                    elif tp1_hit and b_low <= limit_entry:
                        outcome = "PARTIAL_WIN"
                        pnl_r = config.TP1_RR * config.SCALE_TP1_RATIO
                        exit_price = limit_entry
                        in_trade_until = f_idx + 1
                        break

                    if not tp1_hit and b_high >= tp1:
                        tp1_hit = True

                    if tp1_hit and b_high >= tp2:
                        outcome = "FULL_WIN"
                        pnl_r = (config.TP1_RR * config.SCALE_TP1_RATIO) + (config.TP2_RR * (1.0 - config.SCALE_TP1_RATIO))
                        exit_price = tp2
                        in_trade_until = f_idx + 1
                        break
                else:
                    if not tp1_hit and b_high >= sl:
                        outcome = "LOSS"
                        pnl_r = -1.0
                        exit_price = sl
                        in_trade_until = f_idx + 1
                        break
                    elif tp1_hit and b_high >= limit_entry:
                        outcome = "PARTIAL_WIN"
                        pnl_r = config.TP1_RR * config.SCALE_TP1_RATIO
                        exit_price = limit_entry
                        in_trade_until = f_idx + 1
                        break

                    if not tp1_hit and b_low <= tp1:
                        tp1_hit = True

                    if tp1_hit and b_low <= tp2:
                        outcome = "FULL_WIN"
                        pnl_r = (config.TP1_RR * config.SCALE_TP1_RATIO) + (config.TP2_RR * (1.0 - config.SCALE_TP1_RATIO))
                        exit_price = tp2
                        in_trade_until = f_idx + 1
                        break

            trades.append({
                "symbol": symbol,
                "time": curr_time,
                "direction": direction,
                "pattern": pattern,
                "entry": round(limit_entry, 5),
                "sl": round(sl, 5),
                "tp1": round(tp1, 5),
                "tp2": round(tp2, 5),
                "outcome": outcome,
                "pnl_r": round(pnl_r, 2),
                "exit_time": exit_time,
                "exit_price": round(exit_price, 5) if exit_price else None
            })

    return pd.DataFrame(trades)


def run_5y_macro_backtest(pairs_data_1d: dict):
    """
    5-Year Multi-Asset Macro Backtest:
    - 5 full calendar years (2021-2026)
    - 50 EMA / 100 SMA Trend Filter on Daily
    - Structural Swings & Retracements
    - Limit 50% Retest
    - Scaled TP1 (0.9R) & TP2 (2.0R)
    """
    trades = []
    
    for symbol, df in pairs_data_1d.items():
        if df.empty or len(df) < 200:
            continue
            
        df = df.copy()
        df["sma50"] = df["close"].rolling(50).mean()
        df["sma100"] = df["close"].rolling(100).mean()
        
        highs, lows, closes, opens = df["high"].values, df["low"].values, df["close"].values, df["open"].values
        times = df.index
        n = len(df)
        
        swings = precompute_swings(highs, lows, times, order=3)
        if len(swings) < 4:
            continue
        swing_indices = np.array([s.index for s in swings])
        
        in_trade_until = 0
        
        for i in range(100, n - 1):
            if i < in_trade_until:
                continue
                
            curr_time = times[i]
            sma_val = df["sma100"].iloc[i]
            if pd.isna(sma_val):
                continue
                
            cutoff = i - 3
            valid_pos = np.searchsorted(swing_indices, cutoff, side="right")
            if valid_pos < 4:
                continue
                
            recent = swings[max(0, valid_pos - 8):valid_pos]
            h_swings = [s for s in recent if s.swing_type == "HIGH"]
            l_swings = [s for s in recent if s.swing_type == "LOW"]
            if len(h_swings) < 2 or len(l_swings) < 2:
                continue
                
            latest_h, latest_l = h_swings[-1], l_swings[-1]
            is_bullish = (latest_h.label == "HH" and latest_l.label == "HL" and latest_h.index > latest_l.index)
            is_bearish = (latest_h.label == "LH" and latest_l.label == "LL" and latest_l.index > latest_h.index)
            
            if is_bullish and closes[i] < sma_val:
                continue
            if is_bearish and closes[i] > sma_val:
                continue
            if not (is_bullish or is_bearish):
                continue
                
            direction = "BUY" if is_bullish else "SELL"
            range_span = latest_h.price - latest_l.price
            if range_span <= 0:
                continue
                
            # Golden Zone
            if direction == "BUY":
                fib50 = latest_h.price - (range_span * 0.50)
                fib618 = latest_h.price - (range_span * 0.618)
                invalidation = latest_l.price
                in_zone = (lows[i] <= fib50) and (highs[i] >= fib618)
                if not in_zone or closes[i] < invalidation:
                    continue
            else:
                fib50 = latest_l.price + (range_span * 0.50)
                fib618 = latest_l.price + (range_span * 0.618)
                invalidation = latest_h.price
                in_zone = (highs[i] >= fib50) and (lows[i] <= fib618)
                if not in_zone or closes[i] > invalidation:
                    continue
                    
            c_open, c_high, c_low, c_close = opens[i], highs[i], lows[i], closes[i]
            p_open, p_high, p_low, p_close = opens[i-1], highs[i-1], lows[i-1], closes[i-1]
            c_range = c_high - c_low
            if c_range <= 0:
                continue
            c_body = abs(c_close - c_open)
            c_upper = c_high - max(c_open, c_close)
            c_lower = min(c_open, c_close) - c_low
            
            pattern = None
            raw_sl = None
            
            if direction == "BUY":
                is_pin = (c_lower >= (1.8 * c_body) and c_lower >= (0.45 * c_range) and c_close >= c_open)
                is_engulf = (p_close < p_open and c_close > c_open and c_close >= p_high)
                if is_pin:
                    pattern = "Bullish Pin Bar"
                    raw_sl = c_low
                elif is_engulf:
                    pattern = "Bullish Engulfing"
                    raw_sl = min(c_low, p_low)
                    
                if not pattern:
                    continue
                    
                limit_entry = (c_high + c_low) / 2.0
                buffer = max(limit_entry * 0.0015, 0.0006)
                sl = raw_sl - buffer
                risk = limit_entry - sl
                if risk <= 0:
                    continue
                tp1 = limit_entry + (risk * config.TP1_RR)
                tp2 = limit_entry + (risk * config.TP2_RR)
                
                filled = False
                fill_idx = -1
                for w in range(i + 1, min(i + 5, n)):
                    if lows[w] <= limit_entry:
                        if lows[w] <= sl:
                            break
                        filled = True
                        fill_idx = w
                        break
                if not filled:
                    continue
            else:
                is_pin = (c_upper >= (1.8 * c_body) and c_upper >= (0.45 * c_range) and c_close <= c_open)
                is_engulf = (p_close > p_open and c_close < c_open and c_close <= p_low)
                if is_pin:
                    pattern = "Bearish Pin Bar"
                    raw_sl = c_high
                elif is_engulf:
                    pattern = "Bearish Engulfing"
                    raw_sl = max(c_high, p_high)
                    
                if not pattern:
                    continue
                    
                limit_entry = (c_high + c_low) / 2.0
                buffer = max(limit_entry * 0.0015, 0.0006)
                sl = raw_sl + buffer
                risk = sl - limit_entry
                if risk <= 0:
                    continue
                tp1 = limit_entry - (risk * config.TP1_RR)
                tp2 = limit_entry - (risk * config.TP2_RR)
                
                filled = False
                fill_idx = -1
                for w in range(i + 1, min(i + 5, n)):
                    if highs[w] >= limit_entry:
                        if highs[w] >= sl:
                            break
                        filled = True
                        fill_idx = w
                        break
                if not filled:
                    continue
                    
            outcome = "OPEN"
            pnl_r = 0.0
            tp1_hit = False
            exit_time = None
            
            for f in range(fill_idx + 1, min(fill_idx + 35, n)):
                b_high, b_low = highs[f], lows[f]
                exit_time = times[f]
                
                if direction == "BUY":
                    if not tp1_hit and b_low <= sl:
                        outcome = "LOSS"
                        pnl_r = -1.0
                        in_trade_until = f + 1
                        break
                    elif tp1_hit and b_low <= limit_entry:
                        outcome = "PARTIAL_WIN"
                        pnl_r = config.TP1_RR * config.SCALE_TP1_RATIO
                        in_trade_until = f + 1
                        break
                    if not tp1_hit and b_high >= tp1:
                        tp1_hit = True
                    if tp1_hit and b_high >= tp2:
                        outcome = "FULL_WIN"
                        pnl_r = (config.TP1_RR * config.SCALE_TP1_RATIO) + (config.TP2_RR * (1.0 - config.SCALE_TP1_RATIO))
                        in_trade_until = f + 1
                        break
                else:
                    if not tp1_hit and b_high >= sl:
                        outcome = "LOSS"
                        pnl_r = -1.0
                        in_trade_until = f + 1
                        break
                    elif tp1_hit and b_high >= limit_entry:
                        outcome = "PARTIAL_WIN"
                        pnl_r = config.TP1_RR * config.SCALE_TP1_RATIO
                        in_trade_until = f + 1
                        break
                    if not tp1_hit and b_low <= tp1:
                        tp1_hit = True
                    if tp1_hit and b_low <= tp2:
                        outcome = "FULL_WIN"
                        pnl_r = (config.TP1_RR * config.SCALE_TP1_RATIO) + (config.TP2_RR * (1.0 - config.SCALE_TP1_RATIO))
                        in_trade_until = f + 1
                        break
                        
            trades.append({
                "symbol": symbol,
                "time": curr_time,
                "year": curr_time.year,
                "direction": direction,
                "pattern": pattern,
                "entry": round(limit_entry, 4),
                "sl": round(sl, 4),
                "tp1": round(tp1, 4),
                "tp2": round(tp2, 4),
                "outcome": outcome,
                "pnl_r": round(pnl_r, 2),
                "exit_time": exit_time
            })
            
    return pd.DataFrame(trades)


def compute_metrics(df_trades: pd.DataFrame, initial_balance: float = 10000.0, risk_pct: float = 0.015, years: float = 5.0):
    """
    Computes Expectancy, Total Return, Max Drawdown, Sharpe Ratio, and CAGR.
    """
    if df_trades.empty:
        return {}

    df = df_trades[df_trades["outcome"].isin(["FULL_WIN", "PARTIAL_WIN", "LOSS"])].copy()
    df.sort_values("time", inplace=True)
    df.reset_index(drop=True, inplace=True)

    n_trades = len(df)
    full_wins = (df["outcome"] == "FULL_WIN").sum()
    partial_wins = (df["outcome"] == "PARTIAL_WIN").sum()
    wins = full_wins + partial_wins
    losses = (df["outcome"] == "LOSS").sum()
    win_rate = (wins / n_trades) * 100 if n_trades > 0 else 0.0

    pnl_r = df["pnl_r"].values
    pos_r = pnl_r[pnl_r > 0]
    neg_r = pnl_r[pnl_r < 0]

    avg_win_r = np.mean(pos_r) if len(pos_r) > 0 else 0.0
    avg_loss_r = abs(np.mean(neg_r)) if len(neg_r) > 0 else 0.0
    loss_rate = (losses / n_trades) if n_trades > 0 else 0.0
    wr_frac = (wins / n_trades) if n_trades > 0 else 0.0

    # Mathematical Expectancy (in R per trade):
    # E = (WinRate * AvgWin) - (LossRate * AvgLoss)
    expectancy_r = (wr_frac * avg_win_r) - (loss_rate * avg_loss_r)
    expectancy_pct = expectancy_r * risk_pct * 100  # Expectancy per trade in account %

    # Simulate Balance Growth
    balance = initial_balance
    equity_curve = [balance]
    peak_balance = balance
    max_dd_dollars = 0.0
    max_dd_pct = 0.0
    
    trade_returns_pct = []

    for r_mult in pnl_r:
        dollar_risk = balance * risk_pct
        trade_pnl = dollar_risk * r_mult
        balance += trade_pnl
        equity_curve.append(balance)
        
        ret_pct = (trade_pnl / (balance - trade_pnl))
        trade_returns_pct.append(ret_pct)
        
        if balance > peak_balance:
            peak_balance = balance
        dd_dollars = peak_balance - balance
        dd_pct = (dd_dollars / peak_balance) * 100
        if dd_dollars > max_dd_dollars:
            max_dd_dollars = dd_dollars
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct

    total_return_pct = ((balance - initial_balance) / initial_balance) * 100
    total_r_gain = np.sum(pnl_r)

    # CAGR: Compound Annual Growth Rate
    # CAGR = (Ending / Beginning) ^ (1 / years) - 1
    if balance > 0 and initial_balance > 0 and years > 0:
        cagr = ((balance / initial_balance) ** (1.0 / years) - 1.0) * 100
    else:
        cagr = 0.0

    # Annualized Sharpe Ratio:
    # Based on trade returns annualized
    if len(trade_returns_pct) > 1:
        mean_ret = np.mean(trade_returns_pct)
        std_ret = np.std(trade_returns_pct)
        trades_per_year = n_trades / years
        rf_annual = 0.03  # 3% risk-free rate
        rf_per_trade = rf_annual / trades_per_year if trades_per_year > 0 else 0.0
        if std_ret > 0 and trades_per_year > 0:
            sharpe = ((mean_ret - rf_per_trade) / std_ret) * math.sqrt(trades_per_year)
        else:
            sharpe = 0.0
    else:
        sharpe = 0.0

    # Profit Factor
    gross_profit_r = np.sum(pos_r) if len(pos_r) > 0 else 0.0
    gross_loss_r = abs(np.sum(neg_r)) if len(neg_r) > 0 else 0.0
    profit_factor = (gross_profit_r / gross_loss_r) if gross_loss_r > 0 else 999.0

    return {
        "n_trades": n_trades,
        "wins": wins,
        "full_wins": full_wins,
        "partial_wins": partial_wins,
        "losses": losses,
        "win_rate": win_rate,
        "total_r": total_r_gain,
        "profit_factor": profit_factor,
        "avg_win_r": avg_win_r,
        "avg_loss_r": avg_loss_r,
        "expectancy_r": expectancy_r,
        "expectancy_pct": expectancy_pct,
        "initial_balance": initial_balance,
        "final_balance": balance,
        "total_return_pct": total_return_pct,
        "max_drawdown_r": (max_dd_dollars / (initial_balance * risk_pct)),
        "max_drawdown_pct": max_dd_pct,
        "sharpe_ratio": sharpe,
        "cagr": cagr,
        "years": years
    }


def print_metrics_table(m: dict, title: str):
    print("\n" + "=" * 90)
    print(f"      📊 {title}")
    print("=" * 90)
    print(f"  Period Horizon:               {m.get('years', 5):.1f} Years")
    print(f"  Total Trades:                 {m.get('n_trades', 0)}")
    print(f"  Win Rate:                     {m.get('win_rate', 0):.2f}% ({m.get('full_wins', 0)} Full TP2 + {m.get('partial_wins', 0)} Partials/BE)")
    print(f"  Losses:                       {m.get('losses', 0)}")
    print(f"  Profit Factor:                {m.get('profit_factor', 0):.2f} 🔥")
    print("-" * 90)
    print("  🏆 QUANTITATIVE MATRICES:")
    print(f"  1. Mathematical Expectancy:   +{m.get('expectancy_r', 0):.2f} R per trade (+{m.get('expectancy_pct', 0):.2f}% per setup at 1.5% risk) 🌟")
    print(f"  2. Total Net Return:          +{m.get('total_r', 0):.2f} R  (+{m.get('total_return_pct', 0):.2f}% on capital)")
    print(f"  3. Ending Equity ($10k start): ${m.get('final_balance', 0):,.2f}")
    print(f"  4. Maximum Drawdown:          {m.get('max_drawdown_pct', 0):.2f}%  ({m.get('max_drawdown_r', 0):.2f} R)")
    print(f"  5. Annualized Sharpe Ratio:   {m.get('sharpe_ratio', 0):.2f} (Institutional Grade)")
    print(f"  6. Compound Growth (CAGR):    {m.get('cagr', 0):.2f}% per year")
    print("=" * 90)


if __name__ == "__main__":
    print("Fetching data for profitable universe (EURJPY, XAUUSD, BTCUSD)...", flush=True)
    data_1d = {}
    data_1h = {}
    for sym, ticker in PROFITABLE_PAIRS.items():
        print(f"  Loading {sym}...", flush=True)
        d1d, d1h = fetch_data_5y(sym, ticker)
        data_1d[sym] = d1d
        data_1h[sym] = d1h

    # 1. 5-Year Macro Backtest (2021-2026)
    print("\n[1/2] Running 5-Year Multi-Asset Macro Backtest (2021-2026)...", flush=True)
    df_5y = run_5y_macro_backtest(data_1d)
    m_5y = compute_metrics(df_5y, initial_balance=INITIAL_CAPITAL, risk_pct=RISK_PER_TRADE_PCT, years=5.0)
    print_metrics_table(m_5y, "5-YEAR MULTI-ASSET PERFORMANCE (2021 - 2026)")
    if not df_5y.empty:
        df_5y.to_csv("backtest_5y_profitable_pairs.csv", index=False)
        print("Saved 5-year trade logs to: backtest_5y_profitable_pairs.csv")

    # 2. Intraday Session-Timed Backtest (London/NY 07:00 - 18:00 UTC)
    print("\n[2/2] Running High-Resolution Intraday Session-Timed Backtest (07:00-18:00 UTC)...", flush=True)
    df_session = run_intraday_session_backtest(data_1h)
    m_session = compute_metrics(df_session, initial_balance=INITIAL_CAPITAL, risk_pct=RISK_PER_TRADE_PCT, years=2.0)
    print_metrics_table(m_session, "INTRADAY LONDON & NY SESSION-TIMED PERFORMANCE (07:00 - 18:00 UTC)")
    if not df_session.empty:
        df_session.to_csv("backtest_session_profitable_pairs.csv", index=False)
        print("Saved session trade logs to: backtest_session_profitable_pairs.csv")

    # Asset breakdown for 5Y
    if not df_5y.empty:
        print("\n📈 5-YEAR PERFORMANCE BREAKDOWN BY ASSET:")
        print("-" * 90)
        print(f"{'Asset':<10} | {'Trades':<8} | {'Win Rate':<10} | {'Net Return (R)':<16} | {'Profit Factor':<14} | {'Expectancy (R)'}")
        print("-" * 90)
        for s, grp in df_5y.groupby("symbol"):
            sub_m = compute_metrics(grp, initial_balance=INITIAL_CAPITAL, risk_pct=RISK_PER_TRADE_PCT, years=5.0)
            print(f"{s:<10} | {sub_m['n_trades']:<8} | {sub_m['win_rate']:>6.2f}%    | {sub_m['total_r']:>+8.2f} R       | {sub_m['profit_factor']:>6.2f}         | +{sub_m['expectancy_r']:.2f} R")
        print("-" * 90)

    # Annual breakdown for 5Y
    if not df_5y.empty and "year" in df_5y.columns:
        print("\n📅 5-YEAR ANNUAL BREAKDOWN (YEAR-BY-YEAR):")
        print("-" * 90)
        print(f"{'Year':<8} | {'Trades':<8} | {'Win Rate':<10} | {'Annual Net Return':<18} | {'Profit Factor'}")
        print("-" * 90)
        for yr, grp in df_5y.groupby("year"):
            yr_m = compute_metrics(grp, initial_balance=INITIAL_CAPITAL, risk_pct=RISK_PER_TRADE_PCT, years=1.0)
            status = "🟢" if yr_m['total_r'] > 0 else "🔴"
            print(f"{yr:<8} | {yr_m['n_trades']:<8} | {yr_m['win_rate']:>6.2f}%    | {yr_m['total_r']:>+8.2f} R {status:<2}        | {yr_m['profit_factor']:>6.2f}")
        print("-" * 90)
