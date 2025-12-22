from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from decimal import Decimal
from datetime import datetime, timezone
from enum import Enum
import json

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
    server_timestamp: int
    receive_timestamp: int
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

class MarketStatus(Enum):
    """市场状态枚举"""
    ACTIVE = "active"
    CLOSED = "closed"
    ARCHIVED = "archived"
    PENDING = "pending"

@dataclass(slots=True)
class MarketMeta:
    """市场元数据（核心信息）"""
    
    # 基本识别信息
    id: str
    question: str
    slug: str
    condition_id: str
    
    # 状态信息
    active: bool = False
    closed: bool = False
    featured: bool = False
    accepting_orders: bool = False
    
    # 交易配置
    enable_order_book: bool = False
    order_price_min_tick_size: float = 0.001  # 最小价格变动单位
    order_min_size: float = 5.0               # 最小订单规模（美元）
    spread: float = 0.001                     # 买卖价差
    clobTokenIds: List[str] = field(default_factory=list)
    
    # 时间信息
    end_date: Optional[str] = None
    start_date: Optional[str] = None
    
    # 当前价格信息
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    last_trade_price: Optional[float] = None
    
    # 结果和概率
    outcomes: List[str] = field(default_factory=list)
    outcome_prices: List[float] = field(default_factory=list)
    
    # 市场指标
    volume_24hr: Optional[float] = None
    liquidity: Optional[float] = None
    competitive: Optional[float] = None
    
    # 缓存元数据
    cached_at: Optional[str] = None
    original_data_size: int = 0
    
    # 🎯 计算属性（不存储在__slots__中）
    @property
    def status(self) -> MarketStatus:
        """获取市场状态"""
        if self.closed:
            return MarketStatus.CLOSED
        elif self.active:
            return MarketStatus.ACTIVE
        else:
            return MarketStatus.PENDING
    
    @property
    def yes_price(self) -> Optional[float]:
        """获取Yes代币价格（二元市场的第一个结果）"""
        if self.outcome_prices and len(self.outcome_prices) >= 1:
            return self.outcome_prices[0]
        return None
    
    @property
    def no_price(self) -> Optional[float]:
        """获取No代币价格（二元市场的第二个结果）"""
        if self.outcome_prices and len(self.outcome_prices) >= 2:
            return self.outcome_prices[1]
        return None
    
    @property
    def is_binary(self) -> bool:
        """是否为二元市场（Yes/No）"""
        return len(self.outcomes) == 2 and 'Yes' in self.outcomes and 'No' in self.outcomes
    
    @property
    def is_tradable(self) -> bool:
        """市场是否可交易"""
        return (
            self.active 
            and self.accepting_orders 
            and self.enable_order_book
            and not self.closed
        )
    
    @property
    def days_to_expiry(self) -> Optional[int]:
        """距离到期还有多少天"""
        if not self.end_date:
            return None
        
        try:
            expiry_date = datetime.fromisoformat(self.end_date.replace('Z', '+00:00'))
            current_date = datetime.utcnow()
            delta = expiry_date - current_date
            return max(0, delta.days)
        except (ValueError, AttributeError):
            return None
    
    def validate_order(self, price: float, size: float) -> List[str]:
        """验证订单参数，返回错误列表"""
        errors = []
        
        if not self.is_tradable:
            errors.append(f"市场 {self.id} 不可交易")
        
        if size < self.order_min_size:
            errors.append(f"订单规模 {size} 小于最小要求 {self.order_min_size}")
        
        if price <= 0:
            errors.append(f"价格 {price} 必须为正数")
        
        # 检查价格是否符合最小变动单位
        if price % self.order_price_min_tick_size != 0:
            errors.append(f"价格 {price} 不符合最小变动单位 {self.order_price_min_tick_size}")
        
        # 对于二元市场，价格应在0-1之间
        if self.is_binary and (price < 0 or price > 1):
            errors.append(f"二元市场价格必须在0-1之间，当前价格: {price}")
        
        return errors
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于JSON序列化）"""
        return asdict(self)
    
    @classmethod
    def from_api_data(cls, market_data: Dict[str, Any]) -> 'MarketMeta':
        """从API原始数据创建MarketMeta实例"""
        return cls(
            # 基本识别信息
            id=market_data.get('id', ''),
            question=market_data.get('question', ''),
            slug=market_data.get('slug', ''),
            condition_id=market_data.get('conditionId', ''),
            
            # 状态信息
            active=bool(market_data.get('active', False)),
            closed=bool(market_data.get('closed', False)),
            featured=bool(market_data.get('featured', False)),
            accepting_orders=bool(market_data.get('acceptingOrders', False)),
            
            # 交易配置
            enable_order_book=bool(market_data.get('enableOrderBook', False)),
            order_price_min_tick_size=float(market_data.get('orderPriceMinTickSize', 0.001)),
            order_min_size=float(market_data.get('orderMinSize', 5.0)),
            spread=float(market_data.get('spread', 0.001)),
            clobTokenIds=cls._parse_json_field(market_data.get('clobTokenIds')),
            
            # 时间信息
            end_date=market_data.get('endDate'),
            start_date=market_data.get('startDate'),
            
            # 当前价格信息
            best_bid=cls._safe_float(market_data.get('bestBid')),
            best_ask=cls._safe_float(market_data.get('bestAsk')),
            last_trade_price=cls._safe_float(market_data.get('lastTradePrice')),
            
            # 结果和概率
            outcomes=cls._parse_json_field(market_data.get('outcomes')),
            outcome_prices=cls._parse_float_list(market_data.get('outcomePrices')),
            
            # 市场指标
            volume_24hr=cls._safe_float(market_data.get('volume24hr')),
            liquidity=cls._safe_float(market_data.get('liquidity')),
            competitive=cls._safe_float(market_data.get('competitive')),
            
            # 缓存元数据
            cached_at=datetime.now(timezone.utc).isoformat(),
            original_data_size=len(str(market_data))
        )
    
    @staticmethod
    def _parse_json_field(field_value) -> List[str]:
        """安全解析JSON字段"""
        if isinstance(field_value, str):
            try:
                return json.loads(field_value)
            except (json.JSONDecodeError, TypeError):
                return []
        elif isinstance(field_value, list):
            return field_value
        return []
    
    @staticmethod
    def _parse_float_list(field_value) -> List[float]:
        """解析浮点数列表"""
        if isinstance(field_value, str):
            try:
                str_list = json.loads(field_value)
                return [float(x) for x in str_list]
            except (json.JSONDecodeError, TypeError, ValueError):
                return []
        elif isinstance(field_value, list):
            try:
                return [float(x) for x in field_value]
            except (ValueError, TypeError):
                return []
        return []
    
    @staticmethod
    def _safe_float(value) -> Optional[float]:
        """安全转换为浮点数"""
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None    

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