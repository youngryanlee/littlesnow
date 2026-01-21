# market/core/direction_detector.py

from collections import deque
from decimal import Decimal
from typing import Deque, Optional, Literal
from dataclasses import dataclass

from ..core.data_models import TradeTick, OrderBook

@dataclass(frozen=True)
class DirectionSignal:
    symbol: str
    direction: Literal["UP", "DOWN"]
    t0_server_ts: int
    t0_receive_ts: int

    trade_id: str
    mid_price: Decimal

class DirectionDetector:
    def __init__(
        self,
        *,
        window_ms: int = 150,
        min_trades: int = 3,
        volume_imbalance_ratio: Decimal = Decimal("0.7"),
        min_mid_move_ticks: Decimal = Decimal("2"),
        tick_size: Decimal = Decimal("0.5"),
    ):
        self.window_ms = window_ms
        self.min_trades = min_trades
        self.volume_imbalance_ratio = volume_imbalance_ratio
        self.min_mid_move_ticks = min_mid_move_ticks
        self.tick_size = tick_size
    
    def consume(
        self,
        *,
        trade: TradeTick,
        recent_trades: Deque[TradeTick],
        orderbook: OrderBook,
    ) -> Optional[DirectionSignal]:

        direction = self._detect_direction(
            now_trade=trade,
            recent_trades=recent_trades,
            orderbook=orderbook,
        )

        if direction is None:
            return None

        return DirectionSignal(
            symbol=trade.symbol,
            direction=direction,
            t0_server_ts=trade.server_timestamp,
            t0_receive_ts=trade.receive_timestamp,
            trade_id=trade.trade_id,
            mid_price=orderbook.get_mid_price(),
        )
    
    def _detect_direction(
        self,
        *,
        now_trade: TradeTick,
        recent_trades: Deque[TradeTick],
        orderbook: OrderBook,
    ) -> Optional[Literal["UP", "DOWN"]]:

        # 0️⃣ 基本防御
        if orderbook is None or not orderbook.is_update_id_valid():
            return None

        # 1️⃣ 时间窗口 trades（刚刚过去 window_ms）
        window_trades = self._filter_trades_in_window(
            recent_trades,
            now_trade.server_timestamp,
            self.window_ms,
        )

        if len(window_trades) < self.min_trades:
            return None

        # 2️⃣ trade flow
        flow = self._calc_trade_flow(window_trades)
        if flow is None:
            return None

        # 3️⃣ 方向判定
        if flow["buy_ratio"] >= self.volume_imbalance_ratio:
            direction = "UP"
        elif (Decimal("1") - flow["buy_ratio"]) >= self.volume_imbalance_ratio:
            direction = "DOWN"
        else:
            return None

        # 4️⃣ 盘口确认
        if not self._orderbook_pressure_confirmed(orderbook, direction):
            return None

        # 5️⃣ midprice 不可逆跳变
        if not self._midprice_jump_confirmed(
            window_trades,
            orderbook,
            self.tick_size,
            self.min_mid_move_ticks,
        ):
            return None

        # ✅ 真实方向已确认（返回方向）
        return direction
        
    @staticmethod
    def _filter_trades_in_window(
        trades: Deque[TradeTick],
        now_ts: int,
        window_ms: int,
    ) -> list[TradeTick]:
        start_ts = now_ts - window_ms
        return [
            t for t in trades
            if start_ts <= t.server_timestamp <= now_ts
        ]

    @staticmethod
    def _calc_trade_flow(trades: list[TradeTick]):
        buy_vol = Decimal("0")
        sell_vol = Decimal("0")

        for t in trades:
            if t.side == "BUY":
                buy_vol += t.size
            else:
                sell_vol += t.size

        total = buy_vol + sell_vol
        if total == 0:
            return None

        return {
            "buy_vol": buy_vol,
            "sell_vol": sell_vol,
            "buy_ratio": buy_vol / total,
            "net_vol": buy_vol - sell_vol,
        }

    @staticmethod
    def _orderbook_pressure_confirmed(
        orderbook: OrderBook,
        direction: Literal["UP", "DOWN"],
    ) -> bool:
        if not orderbook.bids or not orderbook.asks:
            return False

        best_bid = orderbook.bids[0]
        best_ask = orderbook.asks[0]

        # UP：ask 很薄 or 被打
        if direction == "UP":
            return best_ask.quantity <= best_bid.quantity * Decimal("0.7")

        # DOWN：bid 很薄 or 被打
        else:
            return best_bid.quantity <= best_ask.quantity * Decimal("0.7")

    @staticmethod 
    def _midprice_jump_confirmed(
        trades: list[TradeTick],
        orderbook: OrderBook,
        tick_size: Decimal,
        min_ticks: Decimal,
    ) -> bool:
        if len(trades) < 2:
            return False

        start_price = trades[0].price
        current_mid = orderbook.get_mid_price()

        if current_mid == 0:
            return False

        move = abs(current_mid - start_price)
        return move >= tick_size * min_ticks


