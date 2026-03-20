#!/usr/bin/env python3
import os
import sys
import math
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal

MIN_CONFIDENCE = 75
API_KEY = os.getenv("TWELVEDATA_API_KEY")
BASE_URL = "https://api.twelvedata.com/time_series"

PRIMARY_INSTRUMENTS = {
    "NVIDIA": {"symbol": "NVDA", "type": "stock", "priority": 12, "market": "NASDAQ"},
    "Tesla": {"symbol": "TSLA", "type": "stock", "priority": 12, "market": "NASDAQ"},
    "AMD": {"symbol": "AMD", "type": "stock", "priority": 11, "market": "NASDAQ"},
    "Meta": {"symbol": "META", "type": "stock", "priority": 10, "market": "NASDAQ"},
    "Amazon": {"symbol": "AMZN", "type": "stock", "priority": 10, "market": "NASDAQ"},
    "Microsoft": {"symbol": "MSFT", "type": "stock", "priority": 7, "market": "NASDAQ"},
    "S&P 500 ETF": {"symbol": "SPY", "type": "etf", "priority": 6, "market": "SP500"},
    "Nasdaq-100 ETF": {"symbol": "QQQ", "type": "etf", "priority": 6, "market": "NASDAQ"},
}

SECONDARY_INSTRUMENTS = {
    "Apple": {"symbol": "AAPL", "type": "stock", "priority": 6, "market": "NASDAQ"},
    "Rivian": {"symbol": "RIVN", "type": "stock", "priority": 3, "market": "NASDAQ"},
    "NIO": {"symbol": "NIO", "type": "stock", "priority": 3, "market": "NASDAQ"},
    "Palantir": {"symbol": "PLTR", "type": "stock", "priority": 3, "market": "NASDAQ"},
    "Emerging Markets ETF": {"symbol": "EEM", "type": "etf", "priority": 4, "market": "EM"},
}

THIRD_INSTRUMENTS = {
    "Plug Power": {"symbol": "PLUG", "type": "stock", "priority": 8, "market": "NASDAQ"},
    "Bitfarms": {"symbol": "BITF", "type": "stock", "priority": 6, "market": "NASDAQ"},
    "Snap": {"symbol": "SNAP", "type": "stock", "priority": 7, "market": "NYSE"},
}


def fmt(x: float) -> str:
    return f"{x:.2f}"


def require_api_key():
    if not API_KEY:
        raise RuntimeError("Missing TWELVEDATA_API_KEY in environment.")


def get_ny_now():
    return datetime.now(ZoneInfo("America/New_York"))


def get_nyse_schedule_for_today(now_ny: datetime):
    nyse = mcal.get_calendar("NYSE")
    today_str = now_ny.strftime("%Y-%m-%d")
    schedule = nyse.schedule(start_date=today_str, end_date=today_str)
    return nyse, schedule


def holiday_and_early_close_status(now_ny: datetime):
    ny_tz = ZoneInfo("America/New_York")
    pl_tz = ZoneInfo("Europe/Warsaw")

    nyse, schedule = get_nyse_schedule_for_today(now_ny)

    if schedule.empty:
        return False, False, None, None, "US market closed today (NYSE holiday or weekend)."

    early_df = nyse.early_closes(schedule)
    is_early_close = not early_df.empty

    market_open_utc = schedule.iloc[0]["market_open"].to_pydatetime()
    market_close_utc = schedule.iloc[0]["market_close"].to_pydatetime()

    market_open_ny = market_open_utc.astimezone(ny_tz)
    market_close_ny = market_close_utc.astimezone(ny_tz)
    market_close_pl = market_close_ny.astimezone(pl_tz)

    if is_early_close:
        msg = (
            f"US market is open today and it is an EARLY CLOSE day.\n"
            f"Market closes at {market_close_ny.strftime('%H:%M')} New York time / "
            f"{market_close_pl.strftime('%H:%M')} Poland time."
        )
    else:
        msg = "US market is scheduled to trade today."

    return True, is_early_close, market_open_ny, market_close_ny, msg


def market_time_check():
    ny_tz = ZoneInfo("America/New_York")
    pl_tz = ZoneInfo("Europe/Warsaw")

    now_ny = datetime.now(ny_tz)
    now_pl = datetime.now(pl_tz)

    (
        is_trading_day,
        _is_early_close,
        market_open_ny,
        market_close_ny,
        day_msg,
    ) = holiday_and_early_close_status(now_ny)

    if not is_trading_day:
        return False, (
            f"{day_msg}\n"
            f"Current New York time: {now_ny.strftime('%Y-%m-%d %H:%M')}\n"
            f"Current Poland time: {now_pl.strftime('%Y-%m-%d %H:%M')}"
        )

    opening_range_ready_ny = market_open_ny + timedelta(minutes=15)
    opening_range_ready_pl = opening_range_ready_ny.astimezone(pl_tz)

    if now_ny < market_open_ny:
        return False, (
            f"Too early — US market not open yet.\n"
            f"{day_msg}\n"
            f"Current New York time: {now_ny.strftime('%H:%M')}\n"
            f"Current Poland time: {now_pl.strftime('%H:%M')}\n"
            f"Run after {opening_range_ready_ny.strftime('%H:%M')} New York time / "
            f"{opening_range_ready_pl.strftime('%H:%M')} Poland time."
        )

    if now_ny < opening_range_ready_ny:
        return False, (
            f"Too early — wait for the first 15 minutes of the US session to complete.\n"
            f"{day_msg}\n"
            f"Current New York time: {now_ny.strftime('%H:%M')}\n"
            f"Current Poland time: {now_pl.strftime('%H:%M')}\n"
            f"Run after {opening_range_ready_ny.strftime('%H:%M')} New York time / "
            f"{opening_range_ready_pl.strftime('%H:%M')} Poland time."
        )

    if now_ny >= market_close_ny:
        market_close_pl = market_close_ny.astimezone(pl_tz)
        return False, (
            f"Too late — US market session is already closed.\n"
            f"{day_msg}\n"
            f"Closed at {market_close_ny.strftime('%H:%M')} New York time / "
            f"{market_close_pl.strftime('%H:%M')} Poland time.\n"
            f"Current New York time: {now_ny.strftime('%H:%M')}\n"
            f"Current Poland time: {now_pl.strftime('%H:%M')}"
        )

    return True, (
        f"Market timing OK.\n"
        f"{day_msg}\n"
        f"Current New York time: {now_ny.strftime('%Y-%m-%d %H:%M')}\n"
        f"Current Poland time: {now_pl.strftime('%Y-%m-%d %H:%M')}"
    )


def get_required_outputsize(interval: str = "1min") -> int:
    """
    Make sure we always fetch enough bars to include 09:30–09:45 NY,
    even late in the session.
    """
    now_ny = get_ny_now()
    (
        is_trading_day,
        _is_early_close,
        market_open_ny,
        _market_close_ny,
        _day_msg,
    ) = holiday_and_early_close_status(now_ny)

    if not is_trading_day:
        return 600

    minutes_since_open = max(0, int((now_ny - market_open_ny).total_seconds() / 60))

    if interval == "1min":
        # full session so far + buffer
        return max(240, minutes_since_open + 90)

    if interval == "5min":
        bars = math.ceil(minutes_since_open / 5)
        return max(100, bars + 20)

    return 600


def fetch_intraday(symbol: str, interval: str = "1min", outputsize: int | None = None) -> list[dict]:
    require_api_key()

    if outputsize is None:
        outputsize = get_required_outputsize(interval)

    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": API_KEY,
        "format": "JSON",
        "order": "asc",
    }

    response = requests.get(BASE_URL, params=params, timeout=15)
    response.raise_for_status()
    data = response.json()

    if "status" in data and data["status"] == "error":
        raise ValueError(data.get("message", "Unknown Twelve Data error"))

    values = data.get("values")
    if not values:
        raise ValueError("No values returned")

    candles = []
    for row in values:
        try:
            candles.append({
                "datetime": row["datetime"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            })
        except (KeyError, ValueError, TypeError):
            continue

    if not candles:
        raise ValueError("No valid candles parsed")

    return candles


def build_opening_range(candles: list[dict]):
    if len(candles) < 15:
        return None

    opening_candles = []

    for c in candles:
        # Twelve Data intraday datetimes for US stocks are effectively in exchange-local time.
        dt = datetime.fromisoformat(c["datetime"])

        if dt.hour == 9 and 30 <= dt.minute < 45:
            opening_candles.append(c)

    if len(opening_candles) < 10:
        return None

    or_high = max(c["high"] for c in opening_candles)
    or_low = min(c["low"] for c in opening_candles)
    current_price = candles[-1]["close"]

    return or_high, or_low, current_price


def calculate_vwap(candles: list[dict]):
    total_price = 0.0
    count = 0

    for c in candles:
        typical = (c["high"] + c["low"] + c["close"]) / 3
        total_price += typical
        count += 1

    if count == 0:
        return None

    return total_price / count


def get_day_high_low(candles: list[dict]):
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    return max(highs), min(lows)


def get_market_direction(candles: list[dict]):
    or_data = build_opening_range(candles)
    if not or_data:
        return None

    or_high, or_low, price = or_data

    if price > or_high:
        return "BUY"
    if price < or_low:
        return "SELL"
    return "NEUTRAL"


def evaluate_symbol(name: str, info: dict, candles: list[dict], account_size: float, benchmark_directions: dict):
    checks = {}
    metrics = {
        "symbol": info["symbol"],
        "type": info["type"],
        "priority": info["priority"],
        "market": info["market"],
    }

    or_data = build_opening_range(candles)
    if not or_data:
        return {
            "name": name,
            "decision": "REJECTED",
            "final_reason": "Opening range not available.",
            "checks": {"opening_range_available": False},
            "metrics": metrics,
        }

    or_high, or_low, price = or_data
    opening_range = or_high - or_low
    vwap = calculate_vwap(candles)
    day_high, day_low = get_day_high_low(candles)
    day_range = day_high - day_low

    metrics.update({
        "price": price,
        "or_high": or_high,
        "or_low": or_low,
        "opening_range": opening_range,
        "vwap": vwap,
        "day_high": day_high,
        "day_low": day_low,
        "day_range": day_range,
    })

    checks["opening_range_available"] = True
    checks["opening_range_positive"] = opening_range > 0

    if opening_range <= 0:
        return {
            "name": name,
            "decision": "REJECTED",
            "final_reason": "Opening range is invalid.",
            "checks": checks,
            "metrics": metrics,
        }

    opening_range_pct = opening_range / price
    metrics["opening_range_pct"] = opening_range_pct

    if info["type"] == "stock":
        checks["volatility_filter"] = opening_range_pct >= 0.0025
    else:
        checks["volatility_filter"] = opening_range_pct >= 0.0015

    if not checks["volatility_filter"]:
        return {
            "name": name,
            "decision": "REJECTED",
            "final_reason": "Volatility too low.",
            "checks": checks,
            "metrics": metrics,
        }

    checks["outside_opening_range"] = not (or_low <= price <= or_high)
    if not checks["outside_opening_range"]:
        return {
            "name": name,
            "decision": "REJECTED",
            "final_reason": "Price still inside opening range.",
            "checks": checks,
            "metrics": metrics,
        }

    checks["vwap_available"] = vwap is not None
    if vwap is None:
        return {
            "name": name,
            "decision": "REJECTED",
            "final_reason": "VWAP not available.",
            "checks": checks,
            "metrics": metrics,
        }

    direction = "BUY" if price > or_high else "SELL"
    metrics["direction"] = direction

    if direction == "BUY":
        checks["vwap_alignment"] = price > vwap
    else:
        checks["vwap_alignment"] = price < vwap

    if not checks["vwap_alignment"]:
        return {
            "name": name,
            "decision": "REJECTED",
            "final_reason": "VWAP alignment failed.",
            "checks": checks,
            "metrics": metrics,
        }

    if info["type"] == "stock":
        stop_distance = max(opening_range * 0.35, price * 0.003)
    else:
        stop_distance = max(opening_range * 0.30, price * 0.0025)

    if direction == "BUY":
        entry = price
        stop = price - stop_distance
        target = price + (2 * stop_distance)
        breakout = price - or_high
        setup_reason = "Price is above OR high and above VWAP."
    else:
        entry = price
        stop = price + stop_distance
        target = price - (2 * stop_distance)
        breakout = or_low - price
        setup_reason = "Price is below OR low and below VWAP."

    metrics.update({
        "entry": entry,
        "stop": stop,
        "target": target,
        "breakout": breakout,
        "stop_distance": stop_distance,
    })

    if info["type"] == "stock":
        checks["anti_chase_filter"] = breakout <= opening_range * 1.0
    else:
        checks["anti_chase_filter"] = breakout <= opening_range * 0.8

    if not checks["anti_chase_filter"]:
        return {
            "name": name,
            "decision": "REJECTED",
            "final_reason": "Move already too extended from opening range.",
            "checks": checks,
            "metrics": metrics,
        }

    market_key = info.get("market")
    benchmark_direction = benchmark_directions.get(market_key)
    metrics["benchmark_key"] = market_key
    metrics["benchmark_direction"] = benchmark_direction

    if market_key in ("SP500", "NASDAQ"):
        checks["benchmark_available"] = benchmark_direction is not None
        if benchmark_direction is None:
            return {
                "name": name,
                "decision": "REJECTED",
                "final_reason": "Benchmark direction unavailable.",
                "checks": checks,
                "metrics": metrics,
            }

        checks["benchmark_not_neutral"] = benchmark_direction != "NEUTRAL"
        if not checks["benchmark_not_neutral"]:
            return {
                "name": name,
                "decision": "REJECTED",
                "final_reason": "Benchmark is neutral.",
                "checks": checks,
                "metrics": metrics,
            }

        checks["benchmark_alignment"] = benchmark_direction == direction
        if not checks["benchmark_alignment"]:
            return {
                "name": name,
                "decision": "REJECTED",
                "final_reason": "Benchmark direction does not match symbol direction.",
                "checks": checks,
                "metrics": metrics,
            }

    now_ny = get_ny_now()
    minutes_after_open = (now_ny.hour * 60 + now_ny.minute) - (9 * 60 + 30)
    metrics["minutes_after_open"] = minutes_after_open

    late_session_strict = now_ny.hour > 11 or (now_ny.hour == 11 and now_ny.minute >= 30)
    checks["late_session_strict_rule"] = True
    if late_session_strict and info["priority"] < 10 and info["type"] == "stock":
        checks["late_session_strict_rule"] = False
        return {
            "name": name,
            "decision": "REJECTED",
            "final_reason": "Later in session: only stronger names allowed.",
            "checks": checks,
            "metrics": metrics,
        }

    risk_amount = account_size * 0.02
    risk_per_share = abs(entry - stop)

    risk_based_shares = int(risk_amount / risk_per_share) if risk_per_share > 0 else 0
    cash_affordable_shares = int(account_size / entry) if entry > 0 else 0
    shares = min(risk_based_shares, cash_affordable_shares)

    actual_position_cost = shares * entry
    actual_risk = shares * risk_per_share

    metrics.update({
        "risk_amount": risk_amount,
        "risk_per_share": risk_per_share,
        "risk_based_shares": risk_based_shares,
        "cash_affordable_shares": cash_affordable_shares,
        "shares": shares,
        "actual_position_cost": actual_position_cost,
        "actual_risk": actual_risk,
    })

    checks["cash_affordability"] = cash_affordable_shares >= 1
    if not checks["cash_affordability"]:
        return {
            "name": name,
            "decision": "REJECTED",
            "final_reason": "Instrument price is above account buying power.",
            "checks": checks,
            "metrics": metrics,
        }

    checks["position_size_valid"] = shares >= 1
    if not checks["position_size_valid"]:
        return {
            "name": name,
            "decision": "REJECTED",
            "final_reason": "Position size too small for account/risk settings.",
            "checks": checks,
            "metrics": metrics,
        }

    if day_range > 0:
        if direction == "BUY":
            extension = target - day_low
        else:
            extension = day_high - target
        metrics["reward_extension"] = extension
        checks["reward_sanity_filter"] = extension <= day_range * 1.5
        if not checks["reward_sanity_filter"]:
            return {
                "name": name,
                "decision": "REJECTED",
                "final_reason": "Target too stretched versus current session range.",
                "checks": checks,
                "metrics": metrics,
            }
    else:
        checks["reward_sanity_filter"] = False
        return {
            "name": name,
            "decision": "REJECTED",
            "final_reason": "Day range invalid.",
            "checks": checks,
            "metrics": metrics,
        }

    base_confidence = int(
        70
        + min(10, opening_range_pct * 1000)
        + min(10, (breakout / price) * 1500)
        + (3 if info["type"] == "stock" else 1)
    )
    priority = info.get("priority", 0)

    time_penalty = 0
    if minutes_after_open > 60:
        time_penalty += 2
    if minutes_after_open > 120:
        time_penalty += 4
    if minutes_after_open > 180:
        time_penalty += 6

    final_confidence = base_confidence + priority - time_penalty

    metrics.update({
        "base_confidence": base_confidence,
        "priority_boost": priority,
        "time_penalty": time_penalty,
        "final_confidence": final_confidence,
    })

    checks["confidence_threshold"] = final_confidence >= MIN_CONFIDENCE
    if not checks["confidence_threshold"]:
        return {
            "name": name,
            "decision": "REJECTED",
            "final_reason": "Final confidence below threshold.",
            "checks": checks,
            "metrics": metrics,
        }

    return {
        "name": name,
        "decision": "VALID",
        "final_reason": setup_reason,
        "checks": checks,
        "metrics": metrics,
    }


def format_trade(eval_result: dict) -> str:
    m = eval_result["metrics"]
    return f"""{eval_result['name']} ({m['symbol']})
Confidence: {m['final_confidence']} (Base: {m['base_confidence']} + Priority: {m['priority_boost']} - TimePenalty: {m['time_penalty']})

Direction: {m['direction']}
Entry: {fmt(m['entry'])}
Stop: {fmt(m['stop'])}
Target: {fmt(m['target'])}

Shares: {m['shares']}
Position Cost: ${fmt(m['actual_position_cost'])}
Estimated Risk/Share: {fmt(m['risk_per_share'])}
Actual Risk: ${fmt(m['actual_risk'])}
Max Allowed Risk: ${fmt(m['risk_amount'])}

OR High: {fmt(m['or_high'])}
OR Low: {fmt(m['or_low'])}
VWAP: {fmt(m['vwap'])}
Benchmark: {m.get('benchmark_key', 'N/A')} = {m.get('benchmark_direction', 'N/A')}
Reason: {eval_result['final_reason']}"""


def format_debug_result(eval_result: dict) -> str:
    m = eval_result.get("metrics", {})
    checks = eval_result.get("checks", {})

    lines = [
        f"{eval_result['name']} ({m.get('symbol', 'N/A')})",
        f"Decision: {eval_result['decision']}",
        f"Final Reason: {eval_result['final_reason']}",
        "",
        "Market Data:",
    ]

    for label, key in [
        ("Current Price", "price"),
        ("OR High", "or_high"),
        ("OR Low", "or_low"),
        ("Opening Range", "opening_range"),
        ("VWAP", "vwap"),
        ("Day High", "day_high"),
        ("Day Low", "day_low"),
        ("Day Range", "day_range"),
    ]:
        if key in m and m[key] is not None:
            lines.append(f"- {label}: {fmt(m[key])}")

    if "direction" in m:
        lines.append(f"- Direction: {m['direction']}")
    if "benchmark_key" in m:
        lines.append(f"- Benchmark Used: {m['benchmark_key']}")
        lines.append(f"- Benchmark Direction: {m.get('benchmark_direction', 'N/A')}")
    if "minutes_after_open" in m:
        lines.append(f"- Minutes After Open: {m['minutes_after_open']}")

    lines.append("")
    lines.append("Checks:")
    for k, v in checks.items():
        lines.append(f"- {k}: {'PASS' if v else 'FAIL'}")

    if "base_confidence" in m:
        lines.append("")
        lines.append("Confidence Breakdown:")
        lines.append(f"- Base Confidence: {m['base_confidence']}")
        lines.append(f"- Priority Boost: {m['priority_boost']}")
        lines.append(f"- Time Penalty: {m['time_penalty']}")
        lines.append(f"- Final Confidence: {m['final_confidence']}")

    if "shares" in m:
        lines.append("")
        lines.append("Sizing:")
        lines.append(f"- Risk-Based Shares: {m['risk_based_shares']}")
        lines.append(f"- Cash-Affordable Shares: {m['cash_affordable_shares']}")
        lines.append(f"- Final Shares: {m['shares']}")
        lines.append(f"- Position Cost: ${fmt(m['actual_position_cost'])}")
        lines.append(f"- Risk/Share: {fmt(m['risk_per_share'])}")
        lines.append(f"- Actual Risk: ${fmt(m['actual_risk'])}")
        lines.append(f"- Max Allowed Risk: ${fmt(m['risk_amount'])}")

    return "\n".join(lines)


def get_benchmark_instruments():
    return {
        "S&P 500 ETF": PRIMARY_INSTRUMENTS["S&P 500 ETF"],
        "Nasdaq-100 ETF": PRIMARY_INSTRUMENTS["Nasdaq-100 ETF"],
    }


def fetch_instruments(instruments: dict):
    cache = {}
    fetch_ok = []
    fetch_fail = []

    for name, info in instruments.items():
        try:
            candles = fetch_intraday(info["symbol"])
            cache[name] = candles
            fetch_ok.append(f"{name} ({info['symbol']})")
        except Exception as e:
            fetch_fail.append(f"{name} ({info['symbol']}): {str(e)[:160]}")

    return cache, fetch_ok, fetch_fail


def get_benchmark_directions_from_cache(cache: dict):
    directions = {}
    failures = {}

    if "S&P 500 ETF" in cache:
        directions["SP500"] = get_market_direction(cache["S&P 500 ETF"])
    else:
        failures["SP500"] = "Missing cached candles for S&P 500 ETF"

    if "Nasdaq-100 ETF" in cache:
        directions["NASDAQ"] = get_market_direction(cache["Nasdaq-100 ETF"])
    else:
        failures["NASDAQ"] = "Missing cached candles for Nasdaq-100 ETF"

    return directions, failures


def run_scan(account_size: float, mode: str):
    if mode == "primary":
        selected_instruments = PRIMARY_INSTRUMENTS
    elif mode == "secondary":
        selected_instruments = SECONDARY_INSTRUMENTS
    elif mode == "third":
        selected_instruments = THIRD_INSTRUMENTS
    else:
        raise ValueError("Mode must be 'primary', 'secondary', or 'third'")

    benchmark_instruments = get_benchmark_instruments()

    benchmark_cache, benchmark_ok, benchmark_fail = fetch_instruments(benchmark_instruments)
    benchmark_directions, benchmark_direction_fail = get_benchmark_directions_from_cache(benchmark_cache)

    if mode == "primary":
        non_benchmark_instruments = {
            name: info
            for name, info in selected_instruments.items()
            if name not in benchmark_instruments
        }
    else:
        non_benchmark_instruments = selected_instruments

    instrument_cache, instrument_ok, instrument_fail = fetch_instruments(non_benchmark_instruments)

    combined_cache = {}
    combined_cache.update(benchmark_cache)
    combined_cache.update(instrument_cache)

    fetch_ok = benchmark_ok + instrument_ok
    fetch_fail = benchmark_fail + instrument_fail

    for k, v in benchmark_direction_fail.items():
        fetch_fail.append(f"Benchmark {k}: {v}")

    valid_trades = []
    evaluations = []

    for name, info in selected_instruments.items():
        candles = combined_cache.get(name)
        if not candles:
            evaluations.append({
                "name": name,
                "decision": "REJECTED",
                "final_reason": "No candles fetched.",
                "checks": {"data_fetch": False},
                "metrics": {"symbol": info["symbol"]},
            })
            continue

        try:
            result = evaluate_symbol(name, info, candles, account_size, benchmark_directions)
            evaluations.append(result)
            if result["decision"] == "VALID":
                valid_trades.append(result)
        except Exception as e:
            fetch_fail.append(f"{name} ({info['symbol']}): analyze error: {str(e)[:160]}")

    valid_trades.sort(key=lambda x: -x["metrics"]["final_confidence"])
    return valid_trades, evaluations, fetch_ok, fetch_fail, benchmark_directions, mode.upper()


def print_test(account_size: float, mode: str, debug: bool):
    ny_tz = ZoneInfo("America/New_York")
    pl_tz = ZoneInfo("Europe/Warsaw")
    now_ny = datetime.now(ny_tz)
    now_pl = datetime.now(pl_tz)

    is_trading_day, _is_early_close, _market_open_ny, _market_close_ny, holiday_msg = holiday_and_early_close_status(now_ny)
    ok, timing_msg = market_time_check()

    lines = [
        "TEST OK",
        "",
        f"Mode: {mode.upper()}",
        f"Debug: {'ON' if debug else 'OFF'}",
        "",
        "Holiday / Session Check:",
        holiday_msg,
        "",
        "Timing Check:",
        timing_msg,
        "",
        f"Current New York time: {now_ny.strftime('%Y-%m-%d %H:%M')}",
        f"Current Poland time: {now_pl.strftime('%Y-%m-%d %H:%M')}",
        "",
    ]

    if not is_trading_day:
        lines.append("Final output right now:")
        lines.append("No trade today (holiday/weekend filter blocked scanning)")
        print("\n".join(lines))
        return

    trades, evaluations, fetch_ok, fetch_fail, benchmark_directions, source = run_scan(account_size, mode)

    lines.append("Benchmark Directions:")
    for k, v in benchmark_directions.items():
        lines.append(f"- {k}: {v}")

    lines.append("")
    lines.append(f"Source: {source} WATCHLIST")
    lines.append("")
    lines.append(f"API fetch SUCCESS: {len(fetch_ok)}")

    if fetch_ok:
        lines.append("Fetched successfully:")
        lines.extend([f"- {x}" for x in fetch_ok])
        lines.append("")

    if fetch_fail:
        lines.append(f"API fetch FAILED: {len(fetch_fail)}")
        lines.append("Failures:")
        lines.extend([f"- {x}" for x in fetch_fail])
        lines.append("")

    if ok and trades:
        lines.append(f"Valid setups above confidence {MIN_CONFIDENCE}: {len(trades)}")
        lines.append("")
        lines.append("Top setup:")
        lines.append(format_trade(trades[0]))
        if len(trades) > 1:
            lines.append("")
            lines.append("Other setups:")
            for t in trades[1:]:
                lines.append("")
                lines.append(format_trade(t))
    elif ok:
        lines.append("Final output right now:")
        lines.append("No trade today")
    else:
        lines.append("Final output right now:")
        lines.append("No live scan yet because timing check has not passed.")

    if debug:
        lines.append("")
        lines.append("Detailed Evaluation:")
        for ev in evaluations:
            lines.append("")
            lines.append(format_debug_result(ev))

    print("\n".join(lines))


def main():
    args = sys.argv[1:]
    debug = "--debug" in args
    args = [a for a in args if a != "--debug"]

    if len(args) < 2:
        print("Usage: python3 trade_scan.py <AccountSize> <primary|secondary|third> [--debug]")
        print("   or: python3 trade_scan.py --test <AccountSize> <primary|secondary|third> [--debug]")
        return

    if args[0] == "--test":
        if len(args) < 3:
            print("Usage: python3 trade_scan.py --test <AccountSize> <primary|secondary|third> [--debug]")
            return
        account_size = float(args[1])
        mode = args[2].lower()
        print_test(account_size, mode, debug)
        return

    account_size = float(args[0])
    mode = args[1].lower()

    ok, msg = market_time_check()
    if not ok:
        print(msg)
        return

    trades, evaluations, _, _, _, source = run_scan(account_size, mode)

    if not trades and not debug:
        print(f"Source: {source} WATCHLIST\n\nNo trade today\n\nNo valid setups above confidence {MIN_CONFIDENCE} right now.")
        return

    output = [msg, "", f"Source: {source} WATCHLIST", ""]

    if trades:
        output.append("Valid setups:")
        output.append("")
        for t in trades:
            output.append(format_trade(t))
            output.append("")
    else:
        output.append("No trade today")
        output.append("")
        output.append(f"No valid setups above confidence {MIN_CONFIDENCE} right now.")
        output.append("")

    if debug:
        output.append("Detailed Evaluation:")
        for ev in evaluations:
            output.append("")
            output.append(format_debug_result(ev))

    print("\n".join(output).strip())


if __name__ == "__main__":
    main()