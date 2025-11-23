import sys
import os

# 添加 src 目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

def test_exchange_type_enum():
    """测试 ExchangeType 枚举"""
    from market.core.data_models import ExchangeType
    
    # 测试枚举值
    assert ExchangeType.BINANCE.value == "binance"
    assert ExchangeType.BYBIT.value == "bybit"
    assert ExchangeType.DERIBIT.value == "deribit"
    assert ExchangeType.POLYMARKET.value == "polymarket"
    
    # 测试枚举比较
    assert ExchangeType.BINANCE == ExchangeType.BINANCE
    assert ExchangeType.BYBIT == ExchangeType.BYBIT
    
    # 测试枚举成员
    assert ExchangeType("binance") == ExchangeType.BINANCE
    assert ExchangeType("bybit") == ExchangeType.BYBIT

def test_market_type_enum():
    """测试 MarketType 枚举"""
    from market.core.data_models import MarketType
    
    # 测试枚举值
    assert MarketType.SPOT.value == "spot"
    assert MarketType.FUTURES.value == "futures"
    assert MarketType.OPTION.value == "option"
    assert MarketType.PREDICTION.value == "prediction"
    
    # 测试枚举比较
    assert MarketType.SPOT == MarketType.SPOT
    assert MarketType.FUTURES == MarketType.FUTURES

def test_enum_import_consistency():
    """测试枚举导入一致性"""
    # 从不同路径导入枚举，确保它们是一致的
    from market.core.data_models import ExchangeType as CoreExchangeType
    from market import ExchangeType as MarketExchangeType
    from market.adapter.binance_adapter import ExchangeType as BinanceExchangeType
    
    # 测试值相等
    assert CoreExchangeType.BINANCE.value == MarketExchangeType.BINANCE.value
    assert CoreExchangeType.BYBIT.value == MarketExchangeType.BYBIT.value
    
    # 测试对象相等（如果导入路径正确，应该是同一个对象）
    assert CoreExchangeType.BINANCE is MarketExchangeType.BINANCE
    assert CoreExchangeType.BYBIT is MarketExchangeType.BYBIT

if __name__ == "__main__":
    test_exchange_type_enum()
    test_market_type_enum()
    test_enum_import_consistency()
    print("所有枚举测试通过！")