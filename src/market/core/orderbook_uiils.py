# src/market/utils/orderbook_utils.py

from decimal import Decimal
from typing import List, Optional, Tuple

from ..core.data_models import OrderBook, OrderBookLevel


def get_best_bid(orderbook: OrderBook) -> Optional[OrderBookLevel]:
    """
    Return best bid level (highest price).
    """
    if not orderbook.bids:
        return None
    return orderbook.bids[0]


def get_best_ask(orderbook: OrderBook) -> Optional[OrderBookLevel]:
    """
    Return best ask level (lowest price).
    """
    if not orderbook.asks:
        return None
    return orderbook.asks[0]


def get_mid_price(orderbook: OrderBook) -> Optional[Decimal]:
    """
    mid = (best_bid + best_ask) / 2
    """
    bid = get_best_bid(orderbook)
    ask = get_best_ask(orderbook)
    if not bid or not ask:
        return None
    return (bid.price + ask.price) / Decimal("2")


def get_spread(orderbook: OrderBook) -> Optional[Decimal]:
    """
    spread = ask - bid
    """
    bid = get_best_bid(orderbook)
    ask = get_best_ask(orderbook)
    if not bid or not ask:
        return None
    return ask.price - bid.price


def get_microprice(orderbook: OrderBook) -> Optional[Decimal]:
    """
    microprice = (ask*bid_qty + bid*ask_qty) / (bid_qty + ask_qty)

    FirstOrder 的核心信号之一。
    """
    bid = get_best_bid(orderbook)
    ask = get_best_ask(orderbook)
    if not bid or not ask:
        return None

    denom = bid.quantity + ask.quantity
    if denom == 0:
        return None

    return (ask.price * bid.quantity + bid.price * ask.quantity) / denom


def get_orderbook_imbalance(orderbook: OrderBook) -> Optional[Decimal]:
    """
    imbalance = bid_qty / (bid_qty + ask_qty)
    """
    bid = get_best_bid(orderbook)
    ask = get_best_ask(orderbook)
    if not bid or not ask:
        return None

    denom = bid.quantity + ask.quantity
    if denom == 0:
        return None

    return bid.quantity / denom


def compute_vwap(levels: List[OrderBookLevel], depth: int = 5) -> Optional[Decimal]:
    """
    Compute VWAP using first N levels.
    VWAP = sum(price * qty) / sum(qty)
    """
    if not levels:
        return None

    total_qty = Decimal("0")
    total_val = Decimal("0")

    for lvl in levels[:depth]:
        total_qty += lvl.quantity
        total_val += lvl.quantity * lvl.price

    if total_qty == 0:
        return None

    return total_val / total_qty


def compute_bid_ask_vwap(orderbook: OrderBook, depth: int = 5) -> Tuple[Optional[Decimal], Optional[Decimal]]:
    """
    Return (bid_vwap, ask_vwap)
    """
    bid_vwap = compute_vwap(orderbook.bids, depth=depth)
    ask_vwap = compute_vwap(orderbook.asks, depth=depth)
    return bid_vwap, ask_vwap
