from dataclasses import dataclass
from typing import Dict, Optional
from datetime import datetime
from decimal import Decimal

from ..core.data_models import MarketData

@dataclass(frozen=True)
class MarketSnapshot:
    """市场快照 - 不可变数据结构"""
    
    symbol: str
    timestamp: datetime
    exchange_data: Dict[str, MarketData]  # exchange_name -> MarketData
    
    @property
    def primary_price(self) -> Optional[Decimal]:
        """获取主要价格（优先使用有订单簿的交易所）"""
        # 优先返回有订单簿数据的交易所价格
        for data in self.exchange_data.values():
            if data.orderbook and data.last_price:
                return data.last_price
                
        # 其次返回任意有最新价格的交易所
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
        
    def is_arbitrage_opportunity(self, threshold_percent: float = 1.0) -> bool:
        """检查是否存在套利机会"""
        if not self.best_bid or not self.best_ask:
            return False
            
        # 如果最佳买价高于最佳卖价，存在套利机会
        if self.best_bid >= self.best_ask:
            return True
            
        # 检查点差是否超过阈值
        mid_price = (self.best_bid + self.best_ask) / 2
        spread_percent = (self.spread / mid_price * 100) if mid_price > 0 else 0
        
        return spread_percent > threshold_percent