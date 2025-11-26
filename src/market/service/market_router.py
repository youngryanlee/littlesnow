from typing import Dict, List, Callable, Optional
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from logger.logger import get_logger
from ..adapter.base_adapter import BaseAdapter
from ..core.data_models import MarketData, MarketSnapshot
from ..adapter.adapter_interface import BaseMarketAdapter

logger = get_logger()

class MarketRouter:
    """市场数据路由器"""
    
    def __init__(self):
        self.adapters: Dict[str, BaseMarketAdapter] = {}
        self.callbacks: List[Callable[[MarketData], None]] = []
        self.snapshot_callbacks: List[Callable[[MarketSnapshot], None]] = []
        self.market_data: Dict[str, Dict[str, MarketData]] = defaultdict(dict)
        self.snapshot_interval = timedelta(milliseconds=100)  # 100ms 生成快照
        
    def register_adapter(self, name: str, adapter: BaseMarketAdapter):
        """注册适配器并设置回调"""
        self.adapters[name] = adapter
        adapter.add_callback(self._on_market_data)
        logger.info(f"MarketRouter registered adapter: {name}")
        
    def add_callback(self, callback: Callable[[MarketData], None]):
        """添加市场数据回调"""
        self.callbacks.append(callback)
        
    def add_snapshot_callback(self, callback: Callable[[MarketSnapshot], None]):
        """添加快照回调"""
        self.snapshot_callbacks.append(callback)
        
    def _on_market_data(self, data: MarketData):
        """处理来自适配器的市场数据"""
        logger.debug(f"🔄 MarketRouter 收到市场数据，准备调用 {len(self.callbacks)} 个回调")
        try:
            # 存储最新数据
            self.market_data[data.exchange.value][data.symbol] = data
            
            # 通知数据回调
            for i, callback in enumerate(self.callbacks):
                try:
                    logger.debug(f"  📞 MarketRouter 调用第 {i+1} 个回调")
                    callback(data)
                    logger.debug(f"  ✅ MarketRouter 第 {i+1} 个回调调用成功")
                except Exception as e:
                    logger.debug(f"  ❌ MarketRouter 第 {i+1} 个回调调用失败: {e}")
                    logger.error(f"Error in market data callback: {e}")
                    
            # 检查是否需要生成快照
            self._check_snapshot_creation(data)
            
        except Exception as e:
            logger.error(f"Error processing market data: {e}")
            
    def _check_snapshot_creation(self, data: MarketData):
        """检查并生成市场快照"""
        # 这里可以实现基于时间或条件的快照生成逻辑
        # 例如：每100ms生成一次，或者当关键数据更新时生成
        
        # 简化的实现：直接为每个新数据生成快照
        snapshot = self._create_snapshot(data.symbol)
        if snapshot:
            for callback in self.snapshot_callbacks:
                try:
                    callback(snapshot)
                except Exception as e:
                    logger.error(f"Error in snapshot callback: {e}")
                    
    def _create_snapshot(self, symbol: str) -> Optional[MarketSnapshot]:
        """为指定交易对创建市场快照"""
        try:
            from ..model.market_snapshot import MarketSnapshot
            
            # 收集所有交易所的该交易对数据
            exchange_data = {}
            for exchange, symbols_data in self.market_data.items():
                if symbol in symbols_data:
                    exchange_data[exchange] = symbols_data[symbol]
                    
            if not exchange_data:
                return None
                
            # 创建快照
            snapshot = MarketSnapshot(
                symbol=symbol,
                timestamp=datetime.now(timezone.utc),
                exchange_data=exchange_data
            )
            
            return snapshot
            
        except Exception as e:
            logger.error(f"Error creating snapshot for {symbol}: {e}")
            return None
            
    def get_latest_data(self, symbol: str, exchange: str = None) -> Optional[MarketData]:
        """获取指定交易对的最新数据"""
        if exchange:
            return self.market_data.get(exchange, {}).get(symbol)
        else:
            # 返回任意交易所的数据
            for exchange_data in self.market_data.values():
                if symbol in exchange_data:
                    return exchange_data[symbol]
            return None
            
    def get_all_exchange_data(self, symbol: str) -> Dict[str, MarketData]:
        """获取指定交易对所有交易所的数据"""
        result = {}
        for exchange, symbols_data in self.market_data.items():
            if symbol in symbols_data:
                result[exchange] = symbols_data[symbol]
        return result