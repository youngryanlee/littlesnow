"""
Market Data Module
A comprehensive market data handling system with multi-exchange support.
"""

from .core import MarketData, OrderBook, TradeTick, PriceChange, ExchangeType, MarketType
from .adapter import BaseMarketAdapter, BinanceAdapter, BybitAdapter, DeribitAdapter, PolymarketAdapter
from .service import WebSocketManager, WebSocketConnector, MarketRouter, ExternalOracle, DataNormalizer
from .model import MarketSnapshot
from .monitor import MarketMonitor

__version__ = "1.0.0"
__all__ = [
    'BaseMarketAdapter',
    'MarketData',
    'OrderBook', 
    'TradeTick',
    'PriceChange'
    'ExchangeType',
    'MarketType',
    'BinanceAdapter',
    'BybitAdapter',
    'DeribitAdapter',
    'PolymarketAdapter',
    'WebSocketManager',
    'MarketRouter',
    'ExternalOracle', 
    'DataNormalizer',
    'MarketSnapshot',
    'MarketMonitor'
]