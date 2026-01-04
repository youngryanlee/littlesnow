import logging
from typing import Dict, Any, Optional
from decimal import Decimal
from datetime import datetime

from ..core.data_models import MarketData, OrderBook, OrderBookLevel, TradeTick, ExchangeType, MarketType

logger = logging.getLogger(__name__)

class DataNormalizer:
    """数据标准化器"""
    
    def __init__(self):
        self.symbol_mappings = self._initialize_symbol_mappings()
        
    def _initialize_symbol_mappings(self) -> Dict[str, Dict[str, str]]:
        """初始化交易对映射表"""
        return {
            'binance': {
                'BTCUSDT': 'BTC-USD',
                'ETHUSDT': 'ETH-USD',
            },
            'bybit': {
                'BTCUSDT': 'BTC-USD', 
                'ETHUSDT': 'ETH-USD',
            },
            # 其他交易所的映射...
        }
        
    def normalize_symbol(self, symbol: str, exchange: ExchangeType) -> str:
        """标准化交易对符号"""
        exchange_key = exchange.value
        if exchange_key in self.symbol_mappings and symbol in self.symbol_mappings[exchange_key]:
            return self.symbol_mappings[exchange_key][symbol]
        return symbol
        
    def normalize_price(self, price: Any) -> Decimal:
        """标准化价格数据"""
        try:
            if isinstance(price, (int, float, str)):
                return Decimal(str(price))
            elif isinstance(price, Decimal):
                return price
            else:
                logger.warning(f"Unsupported price type: {type(price)}")
                return Decimal('0')
        except Exception as e:
            logger.error(f"Error normalizing price {price}: {e}")
            return Decimal('0')
            
    def normalize_quantity(self, quantity: Any) -> Decimal:
        """标准化数量数据"""
        return self.normalize_price(quantity)  # 同样的逻辑
        
    def normalize_timestamp(self, timestamp: Any) -> datetime:
        """标准化时间戳"""
        if isinstance(timestamp, datetime):
            return timestamp
        elif isinstance(timestamp, (int, float)):
            # 假设是毫秒时间戳
            if timestamp > 1e12:  # 毫秒
                return datetime.utcfromtimestamp(timestamp / 1000)
            else:  # 秒
                return datetime.utcfromtimestamp(timestamp)
        elif isinstance(timestamp, str):
            try:
                return datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            except ValueError:
                logger.warning(f"Unable to parse timestamp: {timestamp}")
                return datetime.utcnow()
        else:
            logger.warning(f"Unsupported timestamp type: {type(timestamp)}")
            return datetime.utcnow()
            
    def create_market_data(self, 
                          symbol: str,
                          exchange: ExchangeType, 
                          market_type: MarketType,
                          orderbook: Optional[OrderBook] = None,
                          last_trade: Optional[TradeTick] = None,
                          last_price: Optional[Decimal] = None,
                          timestamp: Optional[datetime] = None) -> MarketData:
        """创建标准化的市场数据对象"""
        
        # 标准化符号
        normalized_symbol = self.normalize_symbol(symbol, exchange)
        
        # 标准化时间戳
        if timestamp is None:
            timestamp = datetime.utcnow()
        else:
            timestamp = self.normalize_timestamp(timestamp)
            
        # 标准化价格
        if last_price:
            last_price = self.normalize_price(last_price)
            
        return MarketData(
            symbol=normalized_symbol,
            exchange=exchange,
            market_type=market_type,
            timestamp=timestamp,
            orderbook=orderbook,
            last_trade=last_trade,
            last_price=last_price
        )
        
    def validate_data_quality(self, data: MarketData) -> bool:
        """验证数据质量"""
        if not data.is_valid():
            return False
            
        # 检查价格合理性
        if data.last_price and data.last_price <= Decimal('0'):
            logger.warning(f"Invalid price for {data.symbol}: {data.last_price}")
            return False
            
        # 检查时间戳是否合理（不是未来时间，不太旧）
        now = datetime.utcnow()
        time_diff = (now - data.timestamp).total_seconds()
        if time_diff < -1 or time_diff > 300:  # 不允许未来时间，最多接受5分钟前的数据
            logger.warning(f"Invalid timestamp for {data.symbol}: {data.timestamp}")
            return False
            
        return True