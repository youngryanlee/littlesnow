from dataclasses import dataclass
from typing import List, Optional, Dict
from decimal import Decimal
from datetime import datetime
from enum import Enum

class MarketType(Enum):
    SPOT = "spot"
    FUTURES = "futures"
    OPTION = "option"
    PREDICTION = "prediction"

class ExchangeType(Enum):
    BINANCE = "binance"
    BYBIT = "bybit" 
    DERIBIT = "deribit"
    POLYMARKET = "polymarket"

@dataclass(frozen=True)
class OrderBookLevel:
    price: Decimal
    quantity: Decimal
    
    def to_dict(self):
        return {
            'price': float(self.price),
            'quantity': float(self.quantity)
        }

@dataclass(frozen=True)
class OrderBook:
    bids: List[OrderBookLevel]
    asks: List[OrderBookLevel]
    timestamp: datetime
    symbol: str
    
    def get_spread(self) -> Decimal:
        if not self.bids or not self.asks:
            return Decimal('0')
        return self.asks[0].price - self.bids[0].price
        
    def get_mid_price(self) -> Decimal:
        if not self.bids or not self.asks:
            return Decimal('0')
        return (self.bids[0].price + self.asks[0].price) / 2

@dataclass(frozen=True)
class Trade:
    trade_id: str
    price: Decimal
    quantity: Decimal
    timestamp: datetime
    is_buyer_maker: bool

@dataclass(frozen=True)
class MarketData:
    """标准化的市场数据结构"""
    symbol: str
    exchange: ExchangeType
    market_type: MarketType
    timestamp: datetime
    
    # 可选字段
    orderbook: Optional[OrderBook] = None
    last_trade: Optional[Trade] = None
    last_price: Optional[Decimal] = None
    volume_24h: Optional[Decimal] = None
    price_change_24h: Optional[Decimal] = None
    
    def is_valid(self) -> bool:
        """验证数据是否有效"""
        return (self.orderbook is not None or 
                self.last_trade is not None or 
                self.last_price is not None)
                
    def to_dict(self):
        """转换为字典格式"""
        result = {
            'symbol': self.symbol,
            'exchange': self.exchange.value,
            'market_type': self.market_type.value,
            'timestamp': self.timestamp.isoformat(),
            'last_price': float(self.last_price) if self.last_price else None
        }
        
        if self.orderbook:
            result['orderbook'] = {
                'bids': [bid.to_dict() for bid in self.orderbook.bids[:5]],
                'asks': [ask.to_dict() for ask in self.orderbook.asks[:5]],
                'timestamp': self.orderbook.timestamp.isoformat()
            }
            
        if self.last_trade:
            result['last_trade'] = {
                'trade_id': self.last_trade.trade_id,
                'price': float(self.last_trade.price),
                'quantity': float(self.last_trade.quantity),
                'timestamp': self.last_trade.timestamp.isoformat(),
                'is_buyer_maker': self.last_trade.is_buyer_maker
            }
            
        return result

@dataclass(frozen=True)
class MarketSnapshot:
    """市场快照 - 不可变数据结构"""
    
    symbol: str
    timestamp: datetime
    exchange_data: Dict[str, MarketData]  # exchange_name -> MarketData
    
    @property
    def primary_price(self) -> Optional[Decimal]:
        """获取主要价格（优先使用有订单簿的交易所）"""
        for data in self.exchange_data.values():
            if data.orderbook and data.last_price:
                return data.last_price
                
        for data in self.exchange_data.values():
            if data.last_price:
                return data.last_price
                
        return None
        
    @property
    def best_bid(self) -> Optional[Decimal]:
        """获取最佳买价"""
        best_bid = None
        for data in self.exchange_data.values():
            if data.orderbook and data.orderbook.bids:
                bid = data.orderbook.bids[0].price
                if best_bid is None or bid > best_bid:
                    best_bid = bid
        return best_bid
        
    @property
    def best_ask(self) -> Optional[Decimal]:
        """获取最佳卖价"""
        best_ask = None
        for data in self.exchange_data.values():
            if data.orderbook and data.orderbook.asks:
                ask = data.orderbook.asks[0].price
                if best_ask is None or ask < best_ask:
                    best_ask = ask
        return best_ask
        
    @property
    def spread(self) -> Optional[Decimal]:
        """获取最小点差"""
        best_bid = self.best_bid
        best_ask = self.best_ask
        if best_bid and best_ask:
            return best_ask - best_bid
        return None
        
    def get_consensus_price(self, exclude: list = None) -> Optional[Decimal]:
        """获取共识价格（排除指定交易所）"""
        if exclude is None:
            exclude = []
            
        prices = []
        for exchange, data in self.exchange_data.items():
            if exchange not in exclude and data.last_price:
                prices.append(data.last_price)
                
        if not prices:
            return None
            
        return sum(prices, Decimal('0')) / len(prices)
        
    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            'symbol': self.symbol,
            'timestamp': self.timestamp.isoformat(),
            'primary_price': float(self.primary_price) if self.primary_price else None,
            'best_bid': float(self.best_bid) if self.best_bid else None,
            'best_ask': float(self.best_ask) if self.best_ask else None,
            'spread': float(self.spread) if self.spread else None,
            'exchange_data': {
                exchange: data.to_dict() 
                for exchange, data in self.exchange_data.items()
            }
        }