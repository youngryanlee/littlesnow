# market/core/direction_detector.py

from collections import deque
from decimal import Decimal
from typing import Deque, Optional, Literal, Dict
from dataclasses import dataclass
import time

from ..core.data_models import TradeTick, OrderBook
from ..monitor.direction_detector_monitor import DirectionDetectorMonitor, SignalRecord, StateTransitionRecord


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

        # 🔒 工程级约束
        cooldown_ms: int = 80,
        midprice_dedupe_ticks: Decimal = Decimal("2"),
    ):

        self.window_ms = window_ms
        self.min_trades = min_trades
        self.volume_imbalance_ratio = volume_imbalance_ratio
        self.min_mid_move_ticks = min_mid_move_ticks
        self.tick_size = tick_size
        self.cooldown_ms = cooldown_ms
        self.midprice_dedupe_ticks = midprice_dedupe_ticks

        # 监控
        self.enable_monitoring = True # 默认打开监控
        if self.enable_monitoring:
            self._last_signal_time: Optional[int] = None

        # 🧠 状态机
        self._active_direction: Optional[Literal["UP", "DOWN"]] = None
        self._last_t0_ts: Optional[int] = None
        self._last_t0_mid_price: Optional[Decimal] = None

    def set_monitor(self, monitor: DirectionDetectorMonitor):
        if monitor and self.enable_monitoring:
            self.monitor = monitor

    def consume(
        self,
        *,
        trade: TradeTick,
        recent_trades: Deque[TradeTick],
        orderbook: OrderBook,
    ) -> Optional[DirectionSignal]:
        
        detected_direction = self._detect_direction(
            now_trade=trade,
            recent_trades=recent_trades,
            orderbook=orderbook,
        )

        # ❶ 条件不成立：如果之前在 Phase 1，则退出
        if detected_direction is None:
            if self._active_direction is not None:

                # 监控：记录状态转换（退出Phase 1）
                if self.enable_monitoring:
                    self._record_state_transition(
                            from_state=self._active_direction,
                            to_state=None,
                            reason="检测失败，退出Phase 1"
                        ) 
                    
                self._active_direction = None
                        
            return None

        # ❷ 已经在 Phase 1 中，不允许重复 T0
        if self._active_direction is not None: 
            return None

        # ❸ 冷却时间检查
        now_ts = trade.server_timestamp
        if self._last_t0_ts is not None:
            if now_ts - self._last_t0_ts < self.cooldown_ms:
                # 记录实际冷却间隔
                if self.enable_monitoring:
                    actual_cooldown = now_ts - self._last_t0_ts
                    self.monitor.record_cooldown_interval(actual_cooldown)
                return None

        # ❹ midprice 去重检查
        current_mid = orderbook.get_mid_price()
        if self._last_t0_mid_price is not None:
            if abs(current_mid - self._last_t0_mid_price) < (
                self.tick_size * self.midprice_dedupe_ticks
            ):
                return None

        # ✅ 状态跃迁：None → Direction
        old_state = self._active_direction
        self._active_direction = detected_direction
        self._last_t0_ts = now_ts
        self._last_t0_mid_price = current_mid

        # 创建信号
        signal = DirectionSignal(
            symbol=trade.symbol,
            direction=detected_direction,
            t0_server_ts=trade.server_timestamp,
            t0_receive_ts=trade.receive_timestamp,
            trade_id=trade.trade_id,
            mid_price=current_mid,
        )
    
        # 记录信号和状态转换
        if self.enable_monitoring:
            # 记录信号
            signal_record = SignalRecord(
                timestamp=now_ts,
                direction=detected_direction,
                mid_price=current_mid,
                trade_id=trade.trade_id
            )
            self.monitor.record_signal(signal_record)
            
            # 记录状态转换（进入Phase 1）
            self._record_state_transition(
                from_state=old_state,
                to_state=detected_direction,
                reason=f"检测到{detected_direction}信号"
            )
            
            # 更新上次信号时间
            self._last_signal_time = now_ts

        print("=========》》》》》》》》》》》》Got Signal")   
        #print(self.monitor.generate_detailed_diagnostic())
        return signal    

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

        if direction == "UP":
            return best_ask.quantity <= best_bid.quantity * Decimal("0.7")
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
    
    # 监控接口
    def _record_state_transition(self, from_state: Optional[str], to_state: Optional[str], reason: str):
        """记录状态转换"""
        if not self.enable_monitoring:
            return
        
        # 如果状态没有变化，不记录
        if from_state == to_state:
            return
        
        transition = StateTransitionRecord(
            timestamp=int(time.time() * 1000),
            from_state=from_state,
            to_state=to_state,
            reason=reason
        )
        self.monitor.record_state_transition(transition)
    
    def update_signal_result(self, signal: DirectionSignal, 
                            success: bool, 
                            actual_duration_ms: Optional[int] = None,
                            profit_pct: Optional[Decimal] = None):
        """
        更新信号结果（由外部策略调用）
        """
        if not self.enable_monitoring:
            return
        
        # 创建信号记录
        signal_record = SignalRecord(
            timestamp=signal.t0_server_ts,
            direction=signal.direction,
            mid_price=signal.mid_price,
            trade_id=signal.trade_id
        )
        
        # 标记结果
        self.monitor.mark_signal_result(
            signal_record, 
            success, 
            actual_duration_ms, 
            profit_pct
        )
    
    def get_monitoring_metrics(self) -> Dict:
        """获取监控指标"""
        if not self.enable_monitoring:
            return {}
        
        return self.monitor.calculate_metrics()
    
    def get_monitoring_report(self) -> str:
        """获取监控报告"""
        if not self.enable_monitoring:
            return "监控未启用"
        
        return self.monitor.generate_report()
    
    def get_cooldown_statistics(self) -> Dict:
        """获取冷却时间统计"""
        if not self.enable_monitoring:
            return {}
        
        return self.monitor.get_cooldown_statistics()
