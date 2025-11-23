import logging
from typing import Dict, Optional
from decimal import Decimal
from datetime import datetime

from ..core.data_models import MarketData, ExchangeType, MarketType

logger = logging.getLogger(__name__)

class ExternalOracle:
    """外部价格预言机"""
    
    def __init__(self):
        self.price_sources: Dict[str, Decimal] = {}
        self.twap_data: Dict[str, list] = {}
        self.index_sources: Dict[str, Decimal] = {}
        
    def update_price_source(self, source: str, symbol: str, price: Decimal):
        """更新价格源数据"""
        key = f"{source}:{symbol}"
        self.price_sources[key] = price
        logger.debug(f"Updated {key} price: {price}")
        
    def get_consensus_price(self, symbol: str, sources: list = None) -> Optional[Decimal]:
        """获取共识价格（多数据源加权平均）"""
        relevant_prices = []
        
        for source_key, price in self.price_sources.items():
            source, price_symbol = source_key.split(':', 1)
            if price_symbol == symbol and (sources is None or source in sources):
                relevant_prices.append(price)
                
        if not relevant_prices:
            return None
            
        # 简单平均，可扩展为加权平均
        return sum(relevant_prices, Decimal('0')) / len(relevant_prices)
        
    def calculate_twap(self, symbol: str, window_minutes: int = 5) -> Optional[Decimal]:
        """计算时间加权平均价格"""
        if symbol not in self.twap_data:
            return None
            
        data_points = self.twap_data[symbol]
        now = datetime.utcnow()
        window_start = now - timedelta(minutes=window_minutes)
        
        # 过滤时间窗口内的数据点
        recent_data = [point for point in data_points if point['timestamp'] >= window_start]
        
        if not recent_data:
            return None
            
        # 简单实现：等权重平均
        total_price = sum(Decimal(point['price']) for point in recent_data)
        return total_price / len(recent_data)
        
    def is_price_abnormal(self, symbol: str, current_price: Decimal, threshold_percent: float = 10.0) -> bool:
        """检查价格是否异常（偏离共识价格超过阈值）"""
        consensus = self.get_consensus_price(symbol)
        if not consensus:
            return False
            
        deviation = abs(current_price - consensus) / consensus * 100
        return deviation > threshold_percent
        
    def update_twap_data(self, symbol: str, price: Decimal, timestamp: datetime = None):
        """更新 TWAP 数据"""
        if timestamp is None:
            timestamp = datetime.utcnow()
            
        if symbol not in self.twap_data:
            self.twap_data[symbol] = []
            
        self.twap_data[symbol].append({
            'price': price,
            'timestamp': timestamp
        })
        
        # 保持最近的数据点（例如最近1小时）
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        self.twap_data[symbol] = [
            point for point in self.twap_data[symbol] 
            if point['timestamp'] > one_hour_ago
        ]