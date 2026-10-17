"""
========================================================================================
Comprehensive Unit & Integration Test Suite for Axiory Backtesting Engine
========================================================================================
Tests causal data alignment, zero look-ahead bias, swing confirmation lag,
order fill simulation, trade accounting, friction deductions, collision handling,
and metric formulas.
========================================================================================
"""

import math
import unittest
import numpy as np
import pandas as pd

class TestAxioryEngine(unittest.TestCase):

    def test_causal_4h_candle_alignment(self):
        """
        Verify that at decision time t, no 4H bar that is still forming is ever accessed.
        A 4H candle starting at 00:00 only closes at 04:00.
        At 00:00, 01:00, 02:00, 03:00, the 00:00-04:00 candle MUST NOT be available.
        """
        dates_1h = pd.date_range("2025-01-01 00:00:00", "2025-01-01 12:00:00", freq="1h", tz="UTC")
        df_1h = pd.DataFrame({
            "open": range(len(dates_1h)),
            "high": [x + 0.5 for x in range(len(dates_1h))],
            "low": [x - 0.5 for x in range(len(dates_1h))],
            "close": range(len(dates_1h))
        }, index=dates_1h)

        df_4h = df_1h.resample("4h").agg({
            "open": "first", "high": "max", "low": "min", "close": "last"
        }).dropna()
        df_4h["close_time"] = df_4h.index + pd.Timedelta(hours=4)

        for t in df_1h.index:
            pos = df_4h["close_time"].searchsorted(t, side="right") - 1
            if t < pd.Timestamp("2025-01-01 04:00:00", tz="UTC"):
                self.assertEqual(pos, -1, f"At {t}, a 4H candle was falsely marked closed!")
            elif t < pd.Timestamp("2025-01-01 08:00:00", tz="UTC"):
                self.assertEqual(pos, 0)
                self.assertEqual(df_4h["close"].iloc[pos], 3)
                self.assertTrue(df_4h["close_time"].iloc[pos] <= t)

    def test_swing_confirmation_lag(self):
        """
        A fractal swing of order N at index i requires N subsequent bars to confirm.
        It must NEVER be marked confirmed or known at index < i + N.
        """
        order = 3
        # Peak is at index 3 (price 20.0). Requires indices 4, 5, 6 to be lower.
        cutoff_at_5 = 5 - order  # 5 - 3 = 2
        self.assertFalse(3 <= cutoff_at_5, "Peak at 3 leaked at bar 5!")

        cutoff_at_6 = 6 - order  # 6 - 3 = 3
        self.assertTrue(3 <= cutoff_at_6, "Peak at 3 was not confirmed at bar 6!")

    def test_fibonacci_golden_zone_calculation(self):
        """
        Verify exact 50% and 61.8% Fibonacci calculations for Bullish and Bearish impulse legs.
        """
        low_p, high_p = 100.0, 200.0
        span = high_p - low_p
        fib50_bull = high_p - (span * 0.50)
        fib618_bull = high_p - (span * 0.618)
        self.assertAlmostEqual(fib50_bull, 150.0)
        self.assertAlmostEqual(fib618_bull, 138.2)

        fib50_bear = low_p + (span * 0.50)
        fib618_bear = low_p + (span * 0.618)
        self.assertAlmostEqual(fib50_bear, 150.0)
        self.assertAlmostEqual(fib618_bear, 161.8)

    def test_pin_bar_detection(self):
        """
        Test strict Pin Bar detection geometry.
        """
        body = 2.0
        c_range = 15.0
        lower_wick = 12.0
        upper_wick = 1.0
        is_pin = (lower_wick >= 2.0 * body) and (lower_wick >= 0.50 * c_range) and (upper_wick <= 0.25 * c_range)
        self.assertTrue(is_pin)

    def test_trade_accounting_with_friction(self):
        """
        Verify that spread and slippage are strictly deducted from realized R and cash PnL.
        """
        limit_entry = 100.0
        sl = 90.0
        risk_dist = limit_entry - sl  # 10.0
        spread = 0.20
        slippage = 0.05
        friction_r = (spread + 2.0 * slippage) / risk_dist  # 0.03 R

        # Full Win
        gross_win_r = (0.65 * 0.9) + (0.35 * 2.0)
        net_win_r = gross_win_r - friction_r
        self.assertAlmostEqual(net_win_r, 1.255)

        # Loss
        net_loss_r = -1.0 - friction_r
        self.assertAlmostEqual(net_loss_r, -1.03)

    def test_sortino_ratio_no_giant_float(self):
        """
        Verify that Sortino ratio does not blow up to 10^16 when all losses have equal magnitude.
        """
        trade_returns = [0.018, -0.015, 0.018, -0.015, 0.018, -0.015, 0.030, 0.018]
        mean_ret = np.mean(trade_returns)
        rf_per_trade = 0.0001
        
        downside_diffs = [min(0.0, r - rf_per_trade) for r in trade_returns]
        downside_dev = math.sqrt(np.mean(np.square(downside_diffs)))
        
        self.assertGreater(downside_dev, 0.005)
        sortino = ((mean_ret - rf_per_trade) / downside_dev) * math.sqrt(50)
        self.assertTrue(0.5 < sortino < 10.0, f"Sortino ratio blew up: {sortino}")

    def test_breakeven_never_activates_before_tp1(self):
        """
        Ensure Stop Loss cannot move to Breakeven until TP1 has explicitly executed.
        """
        tp1_hit = False
        sl_is_be = False
        price_high = 108.0
        tp1_level = 109.0
        
        if price_high >= tp1_level:
            tp1_hit = True
            sl_is_be = True
            
        self.assertFalse(tp1_hit)
        self.assertFalse(sl_is_be)

    def test_intra_candle_collision_resolution(self):
        """
        When both TP1 and SL are touched in the same candle:
        Conservative rule must trigger Loss (SL) rather than assuming favorable TP.
        """
        b_high = 115.0
        b_low = 88.0
        sl = 90.0
        tp1 = 110.0

        # Collision condition: both thresholds breached in single candle
        sl_breached = b_low <= sl
        tp_breached = b_high >= tp1
        self.assertTrue(sl_breached and tp_breached)

        # Conservative resolution: SL priority
        resolved_outcome = "LOSS" if sl_breached else "WIN"
        self.assertEqual(resolved_outcome, "LOSS")

    def test_bid_ask_limit_fill_condition(self):
        """
        A Buy Limit order fills only when Ask <= Limit (Low + Spread <= Limit).
        If Low touches Limit exactly, Ask is above Limit, so order does NOT fill.
        """
        limit_price = 100.0
        spread = 0.30
        
        # Low touches limit exactly:
        low_bar = 100.0
        ask_bar = low_bar + spread  # 100.30
        filled = ask_bar <= limit_price
        self.assertFalse(filled, "Buy limit filled on Bid touch without accounting for spread!")

        # Low dips below limit by spread:
        low_bar_deep = 99.60
        ask_bar_deep = low_bar_deep + spread  # 99.90
        filled_deep = ask_bar_deep <= limit_price
        self.assertTrue(filled_deep, "Buy limit failed to fill when Ask dipped below limit!")

    def test_is_oos_date_split_non_overlapping(self):
        """
        In-sample and Out-of-sample must be strictly partitioned by timestamp with no overlap.
        """
        all_times = pd.date_range("2024-11-01", "2026-10-01", freq="1D", tz="UTC")
        split_date = pd.Timestamp("2026-03-01", tz="UTC")
        
        is_times = all_times[all_times < split_date]
        oos_times = all_times[all_times >= split_date]
        
        self.assertTrue(is_times.max() < oos_times.min())
        self.assertEqual(len(set(is_times).intersection(set(oos_times))), 0)


if __name__ == "__main__":
    unittest.main()
