"""
journal/telegram_publisher.py
Dedicated Telegram channel publisher for the trading journal.
Supports HTML messages, photo uploads, rate-limit retry handling,
and non-blocking background delivery queue.
"""

import os
import time
import logging
import queue
import threading
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Callable
import requests

from .models import JournalEntry, OutcomeStatus
from .config import get_telegram_bot_token, get_telegram_channel_id

logger = logging.getLogger("journal.telegram")


def format_signal_caption(entry: JournalEntry) -> str:
    """Formats a clean, comprehensive HTML journal post for a new signal."""
    dir_emoji = "🟢 <b>BUY</b>" if entry.direction.upper() == "BUY" else "🔴 <b>SELL</b>"
    
    tp2_str = f"{entry.take_profit_2:,.4f}" if entry.take_profit_2 is not None else "N/A (Unavailable)"
    
    # Parse metadata if present
    import json
    pattern = "N/A"
    reason = "N/A"
    bias = "N/A"
    try:
        meta = json.loads(entry.signal_metadata_json) if entry.signal_metadata_json else {}
        pattern = meta.get("pattern") or "N/A"
        reason = meta.get("reason") or "N/A"
        bias = meta.get("trend_bias") or "N/A"
    except Exception:
        pass

    # Timestamp audit display
    candle_ts = entry.candle_time or entry.signal_timestamp or "N/A"
    gen_ts = entry.signal_generated_at or "N/A"

    caption = (
        f"📖 <b>TRADING JOURNAL ENTRY</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>Signal ID:</b> <code>{entry.signal_id}</code>\n"
        f"📊 <b>Instrument:</b> {entry.symbol} ({entry.ticker})\n"
        f"🧭 <b>Direction:</b> {dir_emoji}\n"
        f"🎯 <b>Strategy:</b> {entry.strategy_id}\n"
        f"⏱ <b>Timeframe:</b> {entry.execution_timeframe} (Execution) / {entry.analysis_timeframe} (HTF Bias: {bias})\n"
        f"📝 <b>Order Type:</b> {entry.entry_mode}\n\n"
        f"<b>Trade Parameters:</b>\n"
        f"• <b>Planned Entry:</b> {entry.planned_entry_price:,.4f}\n"
        f"• <b>Stop Loss:</b> {entry.stop_loss:,.4f}\n"
        f"• <b>Target TP1:</b> {entry.take_profit_1:,.4f}\n"
        f"• <b>Target TP2:</b> {tp2_str}\n\n"
        f"<b>Signal Rationale:</b>\n"
        f"• <b>Trigger Pattern:</b> {pattern}\n"
        f"• <b>Context:</b> {reason}\n\n"
        f"<b>⏱ Timestamp Audit:</b>\n"
        f"• <b>Candle Close Time:</b> <code>{candle_ts}</code>\n"
        f"• <b>Signal Generated:</b> <code>{gen_ts}</code>\n\n"
        f"📌 <i>Status: SIGNAL_RECORDED (Awaiting execution / market outcome)</i>\n"
        f"<i>Note: Recorded automatically for audit purposes. Does not represent filled execution.</i>"
    )
    return caption


def format_outcome_caption(entry: JournalEntry) -> str:
    """Formats an HTML update when an outcome has been recorded."""
    status_emoji = {
        OutcomeStatus.WIN_TP1.value: "🏆 <b>WIN (TP1 REACHED)</b>",
        OutcomeStatus.WIN_TP2.value: "🚀 <b>WIN (TP2 REACHED)</b>",
        OutcomeStatus.LOSS_SL.value: "🛑 <b>LOSS (STOP LOSS HIT)</b>",
        OutcomeStatus.BREAKEVEN.value: "⚖️ <b>BREAKEVEN</b>",
        OutcomeStatus.NOT_FILLED_EXPIRED.value: "⌛ <b>EXPIRED (ORDER NOT FILLED)</b>",
        OutcomeStatus.AMBIGUOUS.value: "⚠️ <b>AMBIGUOUS OUTCOME</b>",
        OutcomeStatus.UNRESOLVED.value: "❓ <b>UNRESOLVED</b>",
    }.get(entry.outcome_status, f"📊 <b>{entry.outcome_status}</b>")

    fill_price = f"{entry.actual_fill_price:,.4f}" if entry.actual_fill_price is not None else "N/A"
    fill_time = entry.filled_timestamp or "N/A"
    exit_price = f"{entry.actual_exit_price:,.4f}" if entry.actual_exit_price is not None else "N/A"
    exit_time = entry.exit_timestamp or "N/A"
    r_mult = f"{entry.realized_r:+.2f} R" if entry.realized_r is not None else "N/A"

    caption = (
        f"🏁 <b>JOURNAL OUTCOME UPDATE</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>Signal ID:</b> <code>{entry.signal_id}</code>\n"
        f"📊 <b>Instrument:</b> {entry.symbol} ({entry.direction})\n"
        f"📋 <b>Outcome:</b> {status_emoji}\n\n"
        f"<b>Execution Audit:</b>\n"
        f"• <b>Planned Entry:</b> {entry.planned_entry_price:,.4f}\n"
        f"• <b>Actual Fill:</b> {fill_price} (at {fill_time})\n"
        f"• <b>Exit Price:</b> {exit_price} (at {exit_time})\n"
        f"• <b>Realized Result:</b> <b>{r_mult}</b>\n\n"
        f"<i>Status: {entry.journal_status}</i>"
    )
    return caption


class TelegramJournalPublisher:
    """
    Publisher sending signals, outcome updates, charts, and reports to a private Telegram channel.
    Executes sends in an isolated background thread to never block the trading engine.
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        channel_id: Optional[str] = None,
        max_retries: int = 3,
    ):
        self.bot_token = bot_token or get_telegram_bot_token()
        self.channel_id = channel_id or get_telegram_channel_id()
        self.max_retries = max_retries

        self._queue: queue.Queue = queue.Queue(maxsize=1000)
        self._worker_thread: Optional[threading.Thread] = None
        self._running = False
        self._start_worker()

    def _start_worker(self):
        self._running = True
        self._worker_thread = threading.Thread(
            target=self._process_queue,
            name="TelegramJournalWorker",
            daemon=True
        )
        self._worker_thread.start()

    def stop(self):
        self._running = False
        try:
            self._queue.put_nowait(None)
        except Exception:
            pass

    def _process_queue(self):
        while self._running:
            try:
                task = self._queue.get(timeout=1.0)
                if task is None:
                    break
                func, args, kwargs = task
                try:
                    func(*args, **kwargs)
                except Exception as e:
                    logger.error(f"[Telegram Publisher Task Error]: {e}", exc_info=True)
                finally:
                    self._queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"[Telegram Publisher Worker Loop Error]: {e}")

    def enqueue(self, func: Callable, *args, **kwargs):
        """Asynchronously enqueues a publication job."""
        try:
            self._queue.put_nowait((func, args, kwargs))
        except queue.Full:
            logger.warning("[Telegram Publisher Queue Full]: dropping task to prevent memory overflow.")

    def _send_request(self, endpoint: str, data: Dict[str, Any], files: Optional[Dict[str, Any]] = None) -> Optional[int]:
        """Performs HTTP POST to Telegram Bot API with retry and rate-limit backoff."""
        if not self.bot_token or not self.channel_id:
            logger.warning("[Telegram Publisher]: Missing bot token or channel ID. Message not published.")
            return None

        url = f"https://api.telegram.org/bot{self.bot_token}/{endpoint}"
        data["chat_id"] = self.channel_id

        for attempt in range(1, self.max_retries + 1):
            try:
                # Reopen file handle if retry
                resp = requests.post(url, data=data, files=files, timeout=25)
                
                if resp.status_code == 200:
                    res_json = resp.json()
                    msg_id = res_json.get("result", {}).get("message_id")
                    return msg_id
                
                elif resp.status_code == 429:
                    retry_after = 5
                    try:
                        retry_after = int(resp.json().get("parameters", {}).get("retry_after", 5))
                    except Exception:
                        pass
                    logger.warning(f"[Telegram 429 Rate Limit]: Retrying in {retry_after}s (attempt {attempt}/{self.max_retries})")
                    time.sleep(retry_after + 1)
                
                else:
                    logger.error(f"[Telegram HTTP {resp.status_code} Error]: {resp.text}")
                    time.sleep(2 ** attempt)

            except Exception as e:
                logger.error(f"[Telegram Network Exception on {endpoint}]: {e} (attempt {attempt}/{self.max_retries})")
                time.sleep(2 ** attempt)

        return None

    def publish_text(self, text: str) -> Optional[int]:
        """Sends an HTML formatted text message directly to the channel."""
        data = {
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        return self._send_request("sendMessage", data)

    def publish_photo(self, photo_path: str, caption: str) -> Optional[int]:
        """Sends a photo with HTML caption directly to the channel."""
        if not os.path.exists(photo_path):
            logger.warning(f"[Telegram Publisher]: Photo not found at {photo_path}. Falling back to text.")
            return self.publish_text(caption)

        try:
            with open(photo_path, "rb") as photo_file:
                files = {"photo": photo_file}
                data = {
                    "caption": caption[:1024],  # Telegram caption max length is 1024
                    "parse_mode": "HTML",
                }
                msg_id = self._send_request("sendPhoto", data, files=files)
                if msg_id:
                    return msg_id
        except Exception as e:
            logger.error(f"[Telegram sendPhoto Failed]: {e}. Falling back to text.")

        # Fallback to text message if photo upload fails
        return self.publish_text(caption)

    def publish_signal_entry(
        self,
        entry: JournalEntry,
        chart_path: Optional[str] = None,
        callback: Optional[Callable[[Optional[int], str], None]] = None,
    ):
        """Publishes a new signal entry, using photo if available or text fallback."""
        caption = format_signal_caption(entry)
        msg_id = None
        status = "FAILED"
        send_started_at = datetime.now(timezone.utc).isoformat()
        delivered_at = None

        try:
            if chart_path and os.path.exists(chart_path):
                msg_id = self.publish_photo(chart_path, caption)
            else:
                msg_id = self.publish_text(caption)

            if msg_id:
                delivered_at = datetime.now(timezone.utc).isoformat()
                status = "PUBLISHED"
                logger.info(
                    f"[Timestamp Audit] Signal {entry.signal_id} published successfully:\n"
                    f"  1. candle_time:             {entry.candle_time}\n"
                    f"  2. signal_generated_at:     {entry.signal_generated_at}\n"
                    f"  3. telegram_send_started_at: {send_started_at}\n"
                    f"  4. telegram_delivered_at:   {delivered_at}"
                )
        except Exception as e:
            logger.error(f"[Signal Entry Publication Error]: {e}")
        finally:
            if callback:
                try:
                    # Support callbacks accepting 4 or 2 arguments
                    import inspect
                    sig = inspect.signature(callback)
                    if len(sig.parameters) >= 4:
                        callback(msg_id, status, send_started_at, delivered_at)
                    else:
                        callback(msg_id, status)
                except Exception as cb_err:
                    logger.error(f"[Telegram Callback Error]: {cb_err}")

    def publish_outcome_entry(
        self,
        entry: JournalEntry,
        chart_path: Optional[str] = None,
        callback: Optional[Callable[[Optional[int], str], None]] = None,
    ):
        """Publishes an outcome update, using photo if available or text fallback."""
        caption = format_outcome_caption(entry)
        msg_id = None
        status = "FAILED"

        try:
            if chart_path and os.path.exists(chart_path):
                msg_id = self.publish_photo(chart_path, caption)
            else:
                msg_id = self.publish_text(caption)

            if msg_id:
                status = "PUBLISHED"
        except Exception as e:
            logger.error(f"[Outcome Entry Publication Error]: {e}")
        finally:
            if callback:
                try:
                    callback(msg_id, status)
                except Exception as cb_err:
                    logger.error(f"[Telegram Outcome Callback Error]: {cb_err}")
