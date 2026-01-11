# binance_adapter.py
import asyncio
from decimal import Decimal
from datetime import datetime, timezone
from typing import List, Dict, Deque, Optional, Any, Tuple
from collections import defaultdict, deque
import time
import traceback

from logger.logger import get_logger
from .base_adapter import BaseAdapter
from ..service.ws_connector import WebSocketConnector
from ..service.rest_connector import RESTConnector
from ..core.data_models import MarketData, OrderBook, OrderBookLevel, ExchangeType, MarketType, TradeTick

logger = get_logger()

'''
币安官方指南：
    如何正确管理本地订单簿

        1. 建立 WebSocket 连接至 wss://stream.binance.com:9443/ws/bnbbtc@depth。

        2. 缓冲从数据流接收到的所有事件。记录你收到的第一个事件的 U 值。

        3. 通过 REST API 获取深度快照：https://api.binance.com/api/v3/depth?symbol=BNBBTC&limit=5000。

        4. 如果快照中的 lastUpdateId 严格小于 第2步中记录的 U 值，则回到第3步重新获取快照。

        5. 在缓冲的事件中，丢弃所有 u 小于等于 快照 lastUpdateId 的事件。此时，第一个缓冲事件的 [U, u] 范围应能包含该 lastUpdateId。

        6. 将你的本地订单簿设置为该快照。其更新ID即为 lastUpdateId。

        7. 将下述更新流程依次应用于所有缓冲事件，以及之后收到的所有后续事件。

    应用事件到本地订单簿的更新流程：

        1. 判断更新事件是否可应用：

            如果事件的最后更新ID (u) 小于 本地订单簿的当前更新ID，则忽略该事件。

            如果事件的起始更新ID (U) 大于 本地订单簿当前更新ID 加 1，说明你已丢失了一些事件。必须丢弃整个本地订单簿，并从头开始重启整个流程。

            通常，下一个事件的 U 会等于前一个事件的 u + 1。

        2. 应用变更： 对于事件中 bids (b) 和 asks (a) 里的每个价格档位：

            如果该价格档位不存在于订单簿中，则以其新数量插入。

            如果数量为零，则从订单簿中移除该价格档位。

        3. 将订单簿的更新ID设置为已处理事件的最后更新ID (u)。

    [!注意]
        由于从API获取的深度快照对价格档位数量有限制（每边最多5000档），因此对于初始快照之外的档位，除非它们发生变化，否则你将无法获知其数量。
        在使用这些档位的信息时请务必小心，因为它们可能无法反映订单簿的全貌。然而，对于大多数使用场景，每边看到5000档已足以理解市场并进行有效交易。
'''


# ---------------------------------------------------------------------------
# BinanceAdapter
#    * WS 先启动并 buffer 更新 -> 然后 REST snapshot -> 应用 buffer（Binance 推荐流程）
#    * pending_updates 严格按接收顺序处理并寻找链式起点：U <= lastUpdateId+1 <= u
#    * 提供 fallback 降级流程（仅在 REST 完全失败时使用）
#    * 非阻塞回调调度（避免阻塞 WS 处理）
#    * pending buffer 上限（防止内存无限增长）
# ---------------------------------------------------------------------------

class BinanceAdapter(BaseAdapter):
    """Binance 交易所适配器 - snapshot + buffering + pending 合并的完整实现"""

    # pending buffer 最大长度（保护内存）
    PENDING_MAX_LEN = 10000
    # 如果 pending 超过这个数量，触发重拉 snapshot 的阈值（可以根据场景调整）
    PENDING_RESYNC_THRESHOLD = 5000

    def __init__(self, verification_enabled: bool = True, verification_interval: int = 1):
        super().__init__("binance", ExchangeType.BINANCE)
        self.ws_url = "wss://stream.binance.com:9443/ws"
        self.ws_url_1 = "wss://stream.binance.com:443"
        self.ws_url_market_data = "wss://data-stream.binance.vision"
        self.rest_base_url = "https://api.binance.com/api/v3"

        # 订单簿状态管理
        self.orderbook_snapshots: Dict[str, OrderBook] = {}
        self.last_update_ids: Dict[str, int] = {}
        self.pending_updates: Dict[str, List[dict]] = {}      # 严格按序存放暂无法处理的实时增量更新的队列
        self.snapshot_initialized: Dict[str, bool] = {}       # 布尔锁。False时所有更新进“待办清单”；True后更新可直接应用

        # 交易数据管理
        self.last_trade: Dict[str, TradeTick] = {}
        self.recent_trades: Dict[str, Deque[TradeTick]] = defaultdict(lambda: deque(maxlen=100))

        # 验证控制
        self._verification_enabled = verification_enabled
        self._verification_interval = verification_interval
        self._verification_tasks: Dict[str, asyncio.Task] = {}
        self._verification_stats: Dict[str, Dict] = defaultdict(lambda: {
            'total_verifications': 0,
            'passed_verifications': 0,
            'failed_verifications': 0,
            'last_verification_time': None,
            'last_verification_result': None,
        })

        # WebSocket connector (假设已实现)
        self.connector = WebSocketConnector(
            url=self.ws_url,
            on_message=self._handle_raw_message,
            on_error=self._handle_connection_error,
            ping_interval=30,
            timeout=10,
            name="binance"
        )

        # 用以存放 subscribe 后正在进行 snapshot 初始化的任务，避免重复 init
        self._init_tasks: Dict[str, asyncio.Task] = {}

    # -----------------------
    # helper: buffer management
    # -----------------------
    def _ensure_symbol_structs(self, symbol: str):
        if symbol not in self.pending_updates:
            self.pending_updates[symbol] = []
        if symbol not in self.snapshot_initialized:
            self.snapshot_initialized[symbol] = False
        if symbol not in self.orderbook_snapshots:
            self.orderbook_snapshots[symbol] = OrderBook(
                bids=[], 
                asks=[], 
                server_timestamp=0,  # 明确表示“未知”
                receive_timestamp=0,  # 明确表示“未知”
                symbol=symbol)  
        if symbol not in self.last_trade:
            self.last_trade[symbol] = None
        if symbol not in self.recent_trades:
            # 默认保存最近100条交易记录
            self.recent_trades[symbol] = deque(maxlen=100)    
            
    def _reset_symbol_state(self, symbol: str):
        """清理指定symbol的所有状态"""
        self.orderbook_snapshots.pop(symbol, None)
        self.last_update_ids.pop(symbol, None)
        if symbol in self.pending_updates:
            self.pending_updates[symbol] = []
        self.snapshot_initialized[symbol] = False 
        logger.debug(f"Reset state for symbol {symbol}")                 

    # -----------------------
    # snapshot init with buffering
    # -----------------------
    async def _init_snapshot_with_buffering(self, symbol: str) -> bool:
        """
        正确的 snapshot 初始化流程（严格遵循 Binance 官方顺序）：
        1) WS 已在运行并把所有更新缓冲到 pending_updates[symbol]
        2) 通过 REST 获取 snapshot(lastUpdateId)
        3) 从 pending 中丢弃所有 u <= lastUpdateId（已包含在snapshot）
        4) 找到第一个满足 U <= lastUpdateId+1 <= u 的 buffered update 作为起点，应用它和之后能连上的更新
        5) 若无法找到链式起点，则尝试清空 buffer 或者触发重拉 snapshot（视具体容忍策略）
        """
        symbol = symbol.upper()
        self._ensure_symbol_structs(symbol)

        try:
            # REST snapshot via RESTConnector context manager
            async with RESTConnector(base_url=self.rest_base_url, timeout=15, name=f"binance_{symbol}") as rest:
                snapshot = await rest.get_json(f"/depth?symbol={symbol}&limit=100")
        except Exception as e:
            logger.exception("snapshot REST failed for %s: %s", symbol, e)
            # do not immediately fallback to using first update — keep snapshot uninitialized
            self.snapshot_initialized[symbol] = False
            return False

        logger.info("Get snapshot for %s", symbol)
        # parse snapshot
        try:
            last_update_id = int(snapshot['lastUpdateId'])
        except Exception:
            logger.error("snapshot missing lastUpdateId for %s: %s", symbol, snapshot)
            self.snapshot_initialized[symbol] = False
            return False

        # build orderbook from snapshot
        bids = [OrderBookLevel(price=Decimal(b[0]), quantity=Decimal(b[1])) for b in snapshot.get('bids', [])]
        asks = [OrderBookLevel(price=Decimal(a[0]), quantity=Decimal(a[1])) for a in snapshot.get('asks', [])]
        bids.sort(key=lambda x: x.price, reverse=True)
        asks.sort(key=lambda x: x.price)
        bids = bids[:20]
        asks = asks[:20]

        receive_ts = int(datetime.now(timezone.utc).timestamp() * 1000)
        orderbook = OrderBook(
            bids=bids,
            asks=asks,
            server_timestamp=last_update_id,   # 使用 last_update_id 作为 server_timestamp 的占位符
            receive_timestamp=receive_ts,      # 本地接收时间
            symbol=symbol,
            last_update_id=last_update_id
        )

        # store snapshot
        self.orderbook_snapshots[symbol] = orderbook
        self.last_update_ids[symbol] = last_update_id
        self.snapshot_initialized[symbol] = True
        logger.info("Initialized snapshot for %s lastUpdateId=%d (pending buffer len=%d)",
                    symbol, last_update_id, len(self.pending_updates.get(symbol, [])))

        # process buffered updates
        buffered = list(self.pending_updates.get(symbol, []))  # shallow copy preserving order
        # drop any buffered update with u <= last_update_id (already included)
        filtered = [u for u in buffered if (u.get('u') or 0) > last_update_id]

        # 清空pending队列（无论是否应用更新）
        self.pending_updates[symbol] = []

        applied_any = False
        expected = last_update_id + 1

        # 找到第一个满足 U <= expected <= u 的 update
        for upd in filtered:
            U = upd.get('U')
            u = upd.get('u')
            logger.debug(f"applying {upd} to {symbol}, expected = {expected}, U = {U}, u = {u}")
            if U is None or u is None:
                # 如果字段缺失，跳过；但保留在 buffer 里以供后续判断或直接丢弃
                continue
            if U <= expected <= u:
                # apply this update
                try:
                    self._apply_orderbook_update(symbol, upd, False)
                    self.last_update_ids[symbol] = int(u)
                    expected = int(u) + 1
                    applied_any = True
                    logger.debug(f"applied {upd} to {symbol}, expected = {expected}, U = {U}, u = {u}")
                except Exception:
                    logger.exception("Failed to apply chained update during init for %s", symbol)
                break

        if applied_any:
            # apply remaining updates in order if they can be chained
            remaining = [u for u in filtered if (u.get('u') or 0) > self.last_update_ids[symbol]]
            for upd in remaining:
                curU = upd.get('U')
                curu = upd.get('u')
                if curU is None or curu is None:
                    continue
                if curU <= self.last_update_ids[symbol] + 1 <= curu:
                    try:
                        self._apply_orderbook_update(symbol, upd, False)
                        self.last_update_ids[symbol] = int(curu)
                    except Exception:
                        logger.exception("Failed to apply subsequent buffered update for %s", symbol)
                else:
                    # 无法继续链式连接 -> 把尚未应用的 remaining 放回 pending（保留接收顺序）
                    idx = remaining.index(upd)
                    self.pending_updates[symbol] = remaining[idx:]
                    logger.warning("Could not chain buffered updates for %s, leaving %d in pending", symbol, len(self.pending_updates[symbol]))
                    break
        else:
            if len(filtered) == 0:
                # 情况1：所有缓冲更新都是旧数据（u <= last_update_id），这是正常的！
                logger.info(
                    f"All buffered updates for {symbol} are already included in snapshot. "
                    f"Buffered={len(buffered)}, last_update_id={last_update_id}. "
                    f"This is normal - waiting for new updates."
                )
                # 已经清空了pending，不需要额外操作
            else:
                # 情况2：有新的更新（u > last_update_id），但无法连接
                # 刚性正确：如果找不到链式起点，说明缓冲区与快照无法对齐
                # 这是严重的数据不一致，需要标记状态无效
                logger.error(
                    f"Rigid correctness: Cannot chain buffered updates for {symbol}. "
                    f"Buffered={len(buffered)}, last_update_id={last_update_id}. "
                    f"Marking snapshot as uninitialized."
                )
            
                # 清理状态，保持一致性
                self._reset_symbol_state(symbol)
            
                return False  
        
        return True

    # -----------------------
    # apply update -> snapshot merge
    # -----------------------
    def _apply_orderbook_update(self, symbol: str, update_data: dict, notify: bool = True):
        """把增量更新应用到本地 snapshot（简化的 add/remove 模型）"""
        try:
            current_orderbook = self.orderbook_snapshots.get(symbol)
            if current_orderbook is None:
                # 这不应该发生！记录严重错误，并触发紧急恢复或停止处理。
                logger.critical(
                    f"CRITICAL: Attempted to apply update for {symbol} but orderbook snapshot is None. "
                    f"This indicates a serious state management bug. Update data: {update_data}"
                )
                # 抛出异常，让上层错误处理逻辑接管（可能触发重连/重启）
                raise ValueError(f"Orderbook snapshot for {symbol} is missing. State inconsistent.")

            # shallow copy lists
            new_bids = list(current_orderbook.bids) if current_orderbook.bids else []
            new_asks = list(current_orderbook.asks) if current_orderbook.asks else []

            # bids 更新
            for price_str, quantity_str in update_data.get('b', []):
                price = Decimal(price_str)
                quantity = Decimal(quantity_str)
                # remove any existing at that price
                new_bids = [b for b in new_bids if b.price != price]
                if quantity > 0:
                    new_bids.append(OrderBookLevel(price=price, quantity=quantity))

            # asks 更新
            for price_str, quantity_str in update_data.get('a', []):
                price = Decimal(price_str)
                quantity = Decimal(quantity_str)
                new_asks = [a for a in new_asks if a.price != price]
                if quantity > 0:
                    new_asks.append(OrderBookLevel(price=price, quantity=quantity))

            # 排序与裁剪
            new_bids.sort(key=lambda x: x.price, reverse=True)
            new_asks.sort(key=lambda x: x.price)
            new_bids = new_bids[:20]
            new_asks = new_asks[:20]

            # 确定 server_timestamp
            server_ts = update_data.get('E')
            if server_ts is None:
                logger.warning(f"No 'E' field for {symbol} in {update_data}")

            # 确定 last_update_id
            last_update_id = update_data.get('u')
            if last_update_id is None:
                logger.warning(f"No 'u' field for {symbol} in {update_data}")

            receive_ts = int(datetime.now(timezone.utc).timestamp() * 1000)

            updated = OrderBook(
                bids=new_bids,
                asks=new_asks,
                server_timestamp=int(server_ts),   # 来自服务器的事件时间
                receive_timestamp=receive_ts,      # 本地接收时间
                symbol=symbol,
                last_update_id=last_update_id  # 使用更新消息中的u字段
            )    

            self.orderbook_snapshots[symbol] = updated
            logger.debug("Applied orderbook update for %s: bids=%d asks=%d", symbol, len(new_bids), len(new_asks))

            # 发布 MarketData 给下游（非阻塞）
            if notify: # 只有当 notify=True 时才触发回调
                # 创建市场数据并触发回调
                market_data = self._create_market_data(
                    symbol=symbol,
                    exchange=ExchangeType.BINANCE,
                    market_type=MarketType.SPOT,
                    external_timestamp=receive_ts,
                    orderbook=updated
                )
                
                if market_data:
                    logger.debug(f"Callback for {market_data}")
                    self._notify_callbacks(market_data)

        except Exception as e:
            logger.exception("Error applying orderbook update for %s: %s", symbol, e)
            raise    

    # -----------------------
    # connect / subscribe
    # -----------------------
    async def connect(self) -> bool:
        """建立 WS 连接（非阻塞）"""
        try:
            success = await self.connector.connect()
            self.is_connected = success
            logger.info("Binance WS connected=%s", success)
            self._record_connection_event(success)
            return success
        except Exception as e:
            logger.exception("Binance connection failed: %s", e)
            self._record_connection_event(False)
            self.is_connected = False
            return False

    async def disconnect(self):
        try:
            await self.connector.disconnect()
        finally:
            self.is_connected = False

    async def _do_subscribe(self, symbols: List[str]):
        """
        订阅深度+trade流，重要流程：
         1) 先确保 WS 已 connect 并开始接收（默认 connector 已连接）
         2) 对每个 symbol 初始化 pending 结构
         3) 发起订阅
         4) 并行触发 _init_snapshot_with_buffering(symbol)（REST snapshot），让 WS 在此期间持续 buffer
        """
        if not self.is_connected:
            logger.warning("Not connected to Binance")
            return

        streams = []
        for symbol in symbols:
            symbol_lower = symbol.lower()
            streams.extend([f"{symbol_lower}@depth@100ms", f"{symbol_lower}@trade"])
            self._ensure_symbol_structs(symbol)

        subscribe_msg = {"method": "SUBSCRIBE", "params": streams, "id": 1}
        await self.connector.send_json(subscribe_msg)
        logger.info("Subscribed to %s on Binance， msg is: %s", symbols, subscribe_msg)

        # 记录成功和失败的symbol
        success_symbols = []
        fail_symbols = []

        # 并行初始化 snapshot（带 buffering 处理）
        tasks = []
        for symbol in symbols:
            # 防止重复创建多个 init 任务
            if symbol in self._init_tasks and not self._init_tasks[symbol].done():
                continue
            t = asyncio.create_task(self._init_snapshot_with_buffering(symbol))
            self._init_tasks[symbol] = t
            tasks.append((symbol, t))
        
        if tasks:
            # 使用gather并行等待，但捕获每个任务的结果
            results = await asyncio.gather(
                *(task for _, task in tasks),
                return_exceptions=True
            )
            
            # 处理每个任务的结果
            for (symbol, _), result in zip(tasks, results):
                if isinstance(result, Exception):
                    logger.error(f"{symbol}: Initialization exception: {result}")
                    fail_symbols.append(symbol)
                elif result:
                    logger.info(f"{symbol}: Initialization successful")
                    success_symbols.append(symbol)

                    try:
                        if self._verification_enabled:
                            # 启动验证任务，每秒验证一次（可根据需要调整间隔）
                            self.start_verification(symbol, interval_seconds=1)
                    except Exception as e:
                        logger.error(f"Failed to start verification for {symbol}: {e}Error messageClick to retry")
                else:
                    logger.error(f"{symbol}: Initialization failed")
                    fail_symbols.append(symbol)
                
                # 清理已完成的任务
                if symbol in self._init_tasks:
                    task = self._init_tasks[symbol]
                    if task.done():
                        self._init_tasks.pop(symbol, None)
        
        # 总结日志
        if success_symbols:
            logger.info(f"Successfully initialized: {success_symbols}")
        if fail_symbols:
            logger.error(f"Failed to initialize: {fail_symbols}")

    async def _do_unsubscribe(self, symbols: List[str]):
        if not self.is_connected:
            return
        streams = []
        for symbol in symbols:
            symbol_lower = symbol.lower()
            streams.extend([f"{symbol_lower}@depth@100ms", f"{symbol_lower}@trade"])
        unsubscribe_msg = {"method": "UNSUBSCRIBE", "params": streams, "id": 1}
        await self.connector.send_json(unsubscribe_msg)
        logger.info("Unsubscribed from %s on Binance", symbols)
        

    # -----------------------
    # raw message handler（WS 回调入口）
    # -----------------------
    def _handle_raw_message(self, raw_data: dict):
        """
        on_message 入口。raw_data 可能是 stream 包装（{stream, data}）或 event 格式（{e: 'depthUpdate', ...}）
        """
        try:
            # stream 包装
            if 'stream' in raw_data:
                stream = raw_data['stream']
                if '@depth' in stream:
                    # depth updates are in raw_data['data']
                    self._handle_orderbook_update(raw_data)
                elif '@trade' in stream:
                    self._handle_trade(raw_data)
                else:
                    logger.debug("Unknown stream message: %s", stream)
            # event 格式
            elif 'e' in raw_data:
                event_type = raw_data['e']
                if event_type == 'depthUpdate':
                    self._handle_orderbook_update(raw_data)
                elif event_type == 'trade':
                    self._handle_trade(raw_data)
                else:
                    logger.debug("Unhandled event type: %s", event_type)
            elif 'result' in raw_data:
                event_type = raw_data['result']  
                if event_type is None:
                    pass
                else:
                    logger.info("Unrecognized message shape from Binance WS: %s", raw_data)
            else:
                logger.info("Unrecognized message shape from Binance WS: %s", raw_data)
        except Exception as e:
            logger.exception("Error handling raw message: %s", e)

    # -----------------------
    # orderbook update core
    # -----------------------
    def _handle_orderbook_update(self, data: dict):
        """处理订单簿增量更新（刚性正确策略：任何不连续都触发重同步）"""
        try:
            if 'stream' in data:
                symbol = data['stream'].split('@')[0].upper()
                update_data = data['data']
            else:
                symbol = data.get('s') or data.get('symbol')
                update_data = data

            if not symbol:
                logger.warning("Orderbook update missing symbol: %s", data)
                return

            self._ensure_symbol_structs(symbol)

            # 如果 snapshot 未初始化，缓冲更新
            if not self.snapshot_initialized.get(symbol, False):
                self._buffer_incoming_update(symbol, update_data)
                return

            # 已初始化的处理逻辑（严格检查连续性）
            current_U = update_data.get('U')
            current_u = update_data.get('u')
            last_update_id = self.last_update_ids.get(symbol)

            # 1. 丢弃旧更新
            if last_update_id is not None and current_u is not None and int(current_u) <= int(last_update_id):
                logger.debug("Dropping old update for %s: u=%s <= last=%s", symbol, current_u, last_update_id)
                return

            # 2. 严格连续性检查
            if last_update_id is not None and current_U is not None and current_u is not None:
                expected = int(last_update_id) + 1
                
                if int(current_U) <= expected <= int(current_u):
                    # 完美连续：应用更新
                    self._apply_orderbook_update(symbol, update_data)
                    self.last_update_ids[symbol] = int(current_u)
                    return
                else:
                    # 🔥 任何不连续性都触发重新同步
                    # 这包括两种情况：
                    # 1. current_U > expected：有明显遗漏
                    # 2. current_U <= expected 但 expected > current_u：U较小但u不够大（实际上不应发生）
                    logger.warning(
                        f"Rigid correctness triggered: gap for {symbol}. "
                        f"last_update_id={last_update_id}, expected={expected}, "
                        f"received U={current_U}, u={current_u}. Triggering re-init."
                    )
                    asyncio.create_task(self._retry_snapshot_initialization(symbol))
                    return
            else:
                # 3. 缺少必要字段：视为错误状态，触发重新同步
                logger.error(
                    f"Missing required fields for {symbol}: last_update_id={last_update_id}, "
                    f"U={current_U}, u={current_u}. raw data={data}. Triggering re-init."
                )
                asyncio.create_task(self._retry_snapshot_initialization(symbol))
                return

        except Exception as e:
            logger.exception("Error processing Binance orderbook update: %s", e)          

    def _buffer_incoming_update(self, symbol: str, update_data: dict):
        """把接收到的 WS 增量更新按接收顺序追加进 pending buffer"""
        self._ensure_symbol_structs(symbol)
        buf = self.pending_updates[symbol]
        buf.append(update_data)

        # 防护：限制 buffer 长度
        if len(buf) > self.PENDING_MAX_LEN:
            # 保留最新部分（丢弃旧的一半）
            keep = buf[-(self.PENDING_MAX_LEN // 2):]
            self.pending_updates[symbol] = keep
            logger.warning(f"pending_updates for {symbol} exceeded max len; trimmed to {len(keep)}")

        # 如果 buffer 极度膨胀，建议重拉 snapshot（异步触发）
        if len(self.pending_updates[symbol]) > self.PENDING_RESYNC_THRESHOLD:
            # 检查是否已经有重试任务在运行
            if symbol in self._init_tasks and not self._init_tasks[symbol].done():
                logger.debug(f"Retry already in progress for {symbol}, skipping")
                return
                
            logger.warning(f"pending_updates for {symbol} reached resync threshold ({len(self.pending_updates[symbol])}), scheduling snapshot re-init")
            task = asyncio.create_task(self._retry_snapshot_initialization(symbol))
            self._init_tasks[symbol] = task     


    # -----------------------
    # trade
    # -----------------------
    def _handle_trade(self, data: dict) -> None:
        """
        处理交易消息
        Binance trade 消息格式:
        {
            "e": "trade",        // 事件类型
            "E": 123456789,      // 事件时间 (服务器时间)
            "s": "BTCUSDT",      // 交易对
            "t": 12345,          // 交易ID
            "p": "0.001",        // 价格
            "q": "100",          // 数量
            "b": 88,             // 买方订单ID
            "a": 50,             // 卖方订单ID
            "T": 123456785,      // 交易时间戳
            "m": true,           // 买方是否是做市方？如果是true，则买方是市价单，卖方是挂单方，即主动卖出
            "M": true            // 忽略
        }
        
        注意：m字段表示买方是否是做市方
        - m=True: 买方是市价单，卖方是挂单方 -> 主动卖出 (SELL)
        - m=False: 买方是挂单方，卖方是市价单 -> 主动买入 (BUY)
        """
        try:
            # 从data中提取交易数据
            if 'stream' in data:
                # stream格式: btcusdt@trade
                stream_data = data['data']
                symbol = stream_data.get('s', '').upper()
                trade_data = stream_data
            else:
                symbol = data.get('s', '').upper()
                trade_data = data
            
            if not symbol:
                logger.warning("Trade message missing symbol: %s", data)
                return
            
            # 获取价格和数量
            price_str = trade_data.get('p')
            quantity_str = trade_data.get('q')
            
            if not price_str or not quantity_str:
                logger.warning("Trade message missing price or quantity: %s", trade_data)
                return
            
            # 解析交易方向
            # m=True: 买方是市价单 -> 主动卖出 (SELL)
            # m=False: 买方是挂单方 -> 主动买入 (BUY)
            is_market_maker = trade_data.get('m', False)
            side = "SELL" if is_market_maker else "BUY"
            
            # 获取时间戳
            # 优先使用交易时间戳(T)，如果没有则使用事件时间戳(E)
            trade_time = trade_data.get('T', trade_data.get('E'))
            if not trade_time:
                logger.warning("Trade message missing timestamp: %s", trade_data)
                return
            
            # 创建TradeTick对象
            trade_tick = TradeTick(
                symbol=symbol,
                trade_id=str(trade_data.get('t', '')),
                price=Decimal(price_str),
                size=Decimal(quantity_str),
                side=side,
                server_timestamp=int(trade_time),
                receive_timestamp=int(datetime.now(timezone.utc).timestamp() * 1000),
                exchange=ExchangeType.BINANCE
            )
            
            # 更新last_trade
            self.last_trade[symbol] = trade_tick
            
            # 添加到recent_trades
            if symbol in self.recent_trades:
                self.recent_trades[symbol].append(trade_tick)
            
            # 创建市场数据并触发回调
            market_data = self._create_market_data(
                symbol=symbol,
                exchange=ExchangeType.BINANCE,
                last_trade=trade_tick,
                external_timestamp=datetime.fromtimestamp(trade_time/1000, timezone.utc)
            )
            
            if market_data:
                logger.debug(f"Callback for {market_data}")
                self._notify_callbacks(market_data)
            
            
            logger.debug("Processed trade for %s: %s %s @ %s", 
                        symbol, side, quantity_str, price_str)
            
        except Exception as e:
            logger.exception("Error processing trade message: %s", e) 


    def _handle_connection_error(self, error: Exception):
        logger.error("Binance WebSocket connection error: %s", error)
        self.is_connected = False
        # 异步重连
        asyncio.create_task(self._attempt_reconnect())

    async def _attempt_reconnect(self):
        logger.info("Attempting to reconnect to Binance WS...")
        await asyncio.sleep(2)
        try:
            success = await self.connect()
            if success and self.subscribed_symbols:
                await self.subscribe(list(self.subscribed_symbols))
        except Exception:
            logger.exception("Reconnection attempt failed")
    

    async def _retry_snapshot_initialization(self, symbol: str) -> bool:
        """重试快照初始化（同步重试）"""
        # 防止并发重试
        if symbol in self._init_tasks and not self._init_tasks[symbol].done():
            logger.debug(f"Already retrying for {symbol}")
            return False
        
        logger.info(f"Starting snapshot re-init for {symbol}")
        
        # 同步重试，最多3次
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # 重置状态
                self._reset_symbol_state(symbol)
                
                # 直接调用初始化（同步等待）
                success = await self._init_snapshot_with_buffering(symbol)
                
                if success:
                    logger.info(f"Retry {attempt+1} successful for {symbol}")
                    # 重试成功，清理任务引用
                    self._init_tasks.pop(symbol, None)
                    return True
                else:
                    logger.warning(f"Retry {attempt+1} failed for {symbol}")
                    
            except Exception as e:
                logger.warning(f"Retry {attempt+1} exception for {symbol}: {e}")
            
            # 如果不是最后一次重试，等待后继续
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)  # 指数退避
        
        logger.error(f"All {max_retries} retries failed for {symbol}")
        # 所有重试都失败，清理任务引用
        self._init_tasks.pop(symbol, None)
        return False
    

    def normalize_data(self, raw_data: dict) -> Optional[MarketData]:
        """保留用于兼容接口的占位方法"""
        return None


    # -----------------------
    # 监控方法
    # -----------------------
    def get_connection_status(self) -> dict:
        base_status = super().get_connection_status()
        connector_info = {}
        try:
            connector_info = self.connector.get_connection_info()
        except Exception:
            connector_info = {"info": "n/a"}
        return {
            **base_status,
            "connector_info": connector_info,
            "subscribed_symbols": list(self.subscribed_symbols),
            "snapshot_initialized": dict(self.snapshot_initialized)
        }


    def get_symbol_status(self, symbol: str) -> str:
        """获取symbol的当前状态"""
        symbol = symbol.upper()
        
        if symbol not in self.pending_updates:
            return "unsubscribed"
        
        if self.snapshot_initialized.get(symbol, False):
            return "ready"
        
        if symbol in self._init_tasks:
            task = self._init_tasks[symbol]
            if task.done():
                try:
                    if task.result():
                        return "ready"  # 任务成功，应该已经被标记为ready
                    else:
                        return "failed"
                except Exception:
                    return "failed"
            else:
                return "initializing"
        
        return "pending"  # 已订阅但未开始初始化
    
    async def verify_orderbook_snapshot(self, symbol: str, tolerance: float = 0.001) -> Tuple[bool, Dict]:
        """
        精准验证订单簿数据正确性
        
        验证策略：
        1. 检查更新ID序列的连续性
        2. 验证本地数据包含快照更新ID之后的所有更新
        3. 使用REST API的深度数据进行交叉验证
        
        Args:
            symbol: 交易对
            tolerance: 允许的数量误差百分比（默认0.1%）
            
        Returns:
            (是否一致, 差异详情)
        """
        symbol = symbol.upper()
        
        try:
            # 1. 获取REST API快照和深度
            async with RESTConnector(base_url=self.rest_base_url, timeout=10, name=f"binance_verify_{symbol}") as rest:
                snapshot = await rest.get_json(f"/depth?symbol={symbol}&limit=100")
                # 同时获取最新成交作为参考
                trades = await rest.get_json(f"/trades?symbol={symbol}&limit=1")
            
            snapshot_last_update_id = int(snapshot['lastUpdateId'])
            local_last_update_id = self.last_update_ids.get(symbol, 0)
            logger.info(f" 订单簿验证: {symbol} (本地更新ID: {local_last_update_id}, 快照更新ID: {snapshot_last_update_id})")
            
            # 2. 获取本地订单簿
            local_ob = self.orderbook_snapshots.get(symbol)
            if not local_ob:
                # 更新统计
                self._update_verification_stats(symbol, False, {'reason': 'local_orderbook_missing'})
                return False, {'reason': 'local_orderbook_missing'}
            
            # 3. 检查更新ID的正确性（核心验证）
            # 本地更新ID应该 >= 快照更新ID（因为我们处理了快照之后的更新）
            update_id_info = {
                'snapshot_update_id': snapshot_last_update_id,
                'local_update_id': local_last_update_id,
                'update_id_diff': local_last_update_id - snapshot_last_update_id
            }
            
            # 关键验证点1：本地应该包含快照之后的所有更新
            if local_last_update_id < snapshot_last_update_id:
                # 本地缺少快照之后的更新，这是严重问题
                return False, {
                    'reason': 'missing_updates_after_snapshot',
                    'message': f'本地更新ID({local_last_update_id})小于快照更新ID({snapshot_last_update_id})，缺少{snapshot_last_update_id - local_last_update_id}个更新',
                    **update_id_info
                }
            
            # 4. 深度交叉验证（使用更精确的方法）
            snapshot_bids = {Decimal(b[0]): Decimal(b[1]) for b in snapshot.get('bids', [])}
            snapshot_asks = {Decimal(a[0]): Decimal(a[1]) for a in snapshot.get('asks', [])}
            
            # 5. 获取本地订单簿的前N档（深度100）
            local_bids = {}
            local_asks = {}
            
            for bid in local_ob.bids[:100]:
                local_bids[bid.price] = bid.quantity
            for ask in local_ob.asks[:100]:
                local_asks[ask.price] = ask.quantity

            logger.debug(f" 订单簿验证: {symbol} (本地bids: {local_bids}, 快照bids: {snapshot_bids})")    
            logger.debug(f" 订单簿验证: {symbol} (本地asks: {local_asks}, 快照asks: {snapshot_asks})")    
            
            # 检查差异
            differences = []
            warnings = []
            critical_issues = []
            
            # 关键验证点2： 验证买卖盘交叉（基本规则）
            if local_ob.bids and local_ob.asks:
                best_bid = local_ob.bids[0].price
                best_ask = local_ob.asks[0].price
                if best_bid >= best_ask:
                    critical_issues.append(f"买卖盘交叉: 最佳买价 {best_bid} >= 最佳卖价 {best_ask}")
            
            # 关键验证点3： 验证价格单调性
            for i in range(len(local_ob.bids) - 1):
                if local_ob.bids[i].price <= local_ob.bids[i + 1].price:
                    critical_issues.append(f"买盘价格非单调递减: {local_ob.bids[i].price} <= {local_ob.bids[i + 1].price}")
                    break
            
            for i in range(len(local_ob.asks) - 1):
                if local_ob.asks[i].price >= local_ob.asks[i + 1].price:
                    critical_issues.append(f"卖盘价格非单调递增: {local_ob.asks[i].price} >= {local_ob.asks[i + 1].price}")
                    break
            
            # 6. 与快照的精确比较（使用Binance的增量更新逻辑）
            # Binance的更新机制保证：如果我们的更新ID >= 快照更新ID，并且正确处理了所有更新，
            # 那么本地订单簿应该是正确的。但我们可以验证一些关键点：
            
            # 检查pending buffer状态
            pending_updates = len(self.pending_updates.get(symbol, []))
            
            # 关键验证点4：如果pending buffer过长，说明数据处理有问题
            if pending_updates > self.PENDING_RESYNC_THRESHOLD:
                critical_issues.append(f"pending buffer过长: {pending_updates}个更新等待处理")
            
            # 关键验证点5：验证数据的时间戳合理性
            if hasattr(local_ob, 'server_timestamp'):
                current_time = int(time.time() * 1000)
                time_diff = current_time - local_ob.server_timestamp
                
                if time_diff > 60000:  # 超过1分钟
                    critical_issues.append(f"数据延迟过大: {time_diff}ms")
                elif time_diff > 10000:  # 超过10秒
                    warnings.append(f"数据有一定延迟: {time_diff}ms")  

            # 关键验证点6：策略关键一致性（price only）
            # ⚠️ 只有在本地与快照几乎同步时才检查最优价一致性
            PRICE_CHECK_MAX_UPDATE_DIFF = 5  # <= 5 个 update 认为是“同步”
            update_id_diff = update_id_info['update_id_diff']

            price_mismatch = False
            if abs(update_id_diff) <= PRICE_CHECK_MAX_UPDATE_DIFF:
                if snapshot_bids and local_ob.bids:
                    if local_ob.bids[0].price != max(snapshot_bids.keys()):
                        price_mismatch = True

                if snapshot_asks and local_ob.asks:
                    if local_ob.asks[0].price != min(snapshot_asks.keys()):
                        price_mismatch = True

                if price_mismatch:
                    critical_issues.append("最优价位与快照不一致（同步状态下）")
            else:
                logger.info(
                    f"跳过最优价一致性校验：local 比 snapshot 新 {update_id_diff} 个更新"
                )    

            # ====== 下面验证辅助信息 ======
            # 7. 数量一致性检查（只检查存在的数据）
            # 对于快照中的每个价格档位，如果本地也有，检查数量是否匹配
            # 8. 数量一致性检查
            matched_bids = 0
            matched_asks = 0
            checked_prices = set()
            MAX_ACCEPTABLE_QTY_DIFF = tolerance * 100          # 0.1%
            MAX_WARNING_QTY_DIFF = tolerance * 100 * 5         # 0.5%

            # 根据更新ID差异调整期望匹配率
            if update_id_diff == 0:
                EXPECTED_MATCH_RATE = 0.8  # 80%
            elif update_id_diff < 100:
                EXPECTED_MATCH_RATE = 0.6  # 60%
            else:
                EXPECTED_MATCH_RATE = 0.4  # 40%

            # 检查本地买盘档位是否在快照中
            for local_price, local_qty in local_bids.items():
                snapshot_qty = snapshot_bids.get(local_price)
                if snapshot_qty is not None:
                    matched_bids += 1
                    checked_prices.add(local_price)
                    if snapshot_qty != Decimal('0') and local_qty != Decimal('0'):
                        qty_diff_pct = abs(float(snapshot_qty - local_qty) / float(snapshot_qty)) * 100
                        if qty_diff_pct > MAX_WARNING_QTY_DIFF:
                            warnings.append(f"bid {local_price}: 数量严重差异 {qty_diff_pct:.2f}% (快照: {snapshot_qty}, 本地: {local_qty})")
                        elif qty_diff_pct > MAX_ACCEPTABLE_QTY_DIFF:
                            differences.append(f"bid {local_price}: 数量轻微差异 {qty_diff_pct:.2f}% (快照: {snapshot_qty}, 本地: {local_qty})")

            # 检查本地卖盘档位是否在快照中
            for local_price, local_qty in local_asks.items():
                snapshot_qty = snapshot_asks.get(local_price)
                if snapshot_qty is not None:
                    matched_asks += 1
                    checked_prices.add(local_price)
                    if snapshot_qty != Decimal('0') and local_qty != Decimal('0'):
                        qty_diff_pct = abs(float(snapshot_qty - local_qty) / float(snapshot_qty)) * 100
                        if qty_diff_pct > MAX_WARNING_QTY_DIFF:
                            warnings.append(f"ask {local_price}: 数量严重差异 {qty_diff_pct:.2f}% (快照: {snapshot_qty}, 本地: {local_qty})")
                        elif qty_diff_pct > MAX_ACCEPTABLE_QTY_DIFF:
                            differences.append(f"ask {local_price}: 数量轻微差异 {qty_diff_pct:.2f}% (快照: {snapshot_qty}, 本地: {local_qty})")

            # 9. 验证匹配的价格档位数量
            matched_levels = len(checked_prices)
            total_snapshot_levels = len(snapshot_bids) + len(snapshot_asks)
            total_local_levels = len(local_bids) + len(local_asks)

            logger.info(f"匹配统计: 本地{total_local_levels}档, 匹配{matched_levels}档, 快照{total_snapshot_levels}档")
            logger.info(f"买盘匹配: {matched_bids}/{len(local_bids)}, 卖盘匹配: {matched_asks}/{len(local_asks)}")
            logger.info(f"更新ID差异: {update_id_diff}")

            # 检查匹配率
            if len(local_bids) > 0:
                bid_match_rate = matched_bids / len(local_bids)
                if bid_match_rate < EXPECTED_MATCH_RATE:
                    differences.append(f"买盘匹配率{bid_match_rate:.1%}低于预期{EXPECTED_MATCH_RATE:.0%}")
                    if bid_match_rate < 0.2:
                        warnings.append(f"买盘匹配严重不足: {bid_match_rate:.1%}")

            if len(local_asks) > 0:
                ask_match_rate = matched_asks / len(local_asks)
                if ask_match_rate < EXPECTED_MATCH_RATE:
                    differences.append(f"卖盘匹配率{ask_match_rate:.1%}低于预期{EXPECTED_MATCH_RATE:.0%}")
                    if ask_match_rate < 0.2:
                        warnings.append(f"卖盘匹配严重不足: {ask_match_rate:.1%}")

            # 检查快照数据完整性
            if total_snapshot_levels < 200:  # 预期是200档（100买+100卖）
                warnings.append(f"快照数据不完整: 只获取了{total_snapshot_levels}档（预期200档）")
                if total_snapshot_levels < 100:
                    logger.warning("快照数据严重不足，验证可能不可靠")

            
            # 10. 严重性判断
            # 根据更新ID差异调整验证严格度
            update_id_diff = update_id_info['update_id_diff']
            
            if update_id_diff > 0:
                # 本地数据比快照新，允许数量差异（这是正常的市场变化）
                # 只检查是否有严重问题，不检查普通数量差异
                is_valid = len(critical_issues) == 0   
                logger.info(f"本地数据比快照新 {update_id_diff} 个更新，允许数量差异")
            else:
                # 本地数据与快照同步，应该严格检查
                is_valid = len(critical_issues) == 0 and len(warnings) == 0

            # 构建结果
            result = {
                'reason': 'verification_completed',
                'is_valid': is_valid,
                'critical_issues': critical_issues,
                'differences': differences,
                'warnings': warnings,
                'update_id_info': update_id_info,
                'pending_updates': pending_updates,
                'local_bids_count': len(local_bids),
                'local_asks_count': len(local_asks),
                'snapshot_bids_count': len(snapshot_bids),
                'snapshot_asks_count': len(snapshot_asks),
                'matched_price_levels': matched_levels,
                'data_timestamp': local_ob.server_timestamp if hasattr(local_ob, 'server_timestamp') else None,
                'snapshot_update_id': snapshot_last_update_id,
                'local_update_id': local_last_update_id,
                'local_data_newer': update_id_diff > 0,
            }    

            # 更新验证统计
            self._update_verification_stats(symbol, is_valid, result)
            
            return is_valid, result
            
        except Exception as e:
            logger.error(f"订单簿验证出错: {e}", exc_info=True)
            error_details = {
                'reason': 'verification_error', 
                'error': str(e), 
                'traceback': traceback.format_exc()
            }
            # 更新验证统计
            self._update_verification_stats(symbol, False, error_details)
            return False, error_details
    
    def start_verification(self, symbol: str, interval_seconds: int = 60):
        """启动持续验证任务"""
        symbol = symbol.upper()
        
        async def verification_loop():
            while True:
                await asyncio.sleep(interval_seconds)

                if not self.is_connected:
                    logger.info(f"连接断开，暂停验证: {symbol}")
                    # 等待连接恢复
                    while not self.is_connected:
                        await asyncio.sleep(1)
                    logger.debug(f"连接恢复，继续验证: {symbol}")
                
                is_valid, details = await self.verify_orderbook_snapshot(symbol)
                
                # 从 update_id_info 中获取更新ID
                update_id_info = details.get('update_id_info', {})
                local_update_id = update_id_info.get('local_last_update_id', 'N/A')
                snapshot_update_id = update_id_info.get('snapshot_update_id', 'N/A')
                
                if is_valid:
                    logger.info(f"✅ 订单簿验证通过: {symbol} "
                            f"(本地更新ID: {local_update_id}, 快照更新ID: {snapshot_update_id})")
                else:
                    logger.warning(f"⚠️ 订单簿验证失败: {symbol}, 原因: {details.get('reason')}")
                    if 'differences' in details and details['differences']:
                        logger.warning(f"差异详情:")
                        for diff in details['differences'][:5]:  # 只显示前5个差异
                            logger.warning(f"  - {diff}")
                    
                    # 如果数据严重不一致，可以触发重新同步
                    if details.get('reason') in ['local_data_older', 'local_orderbook_missing', 'missing_updates_after_snapshot']:
                        logger.critical(f"数据严重不一致: {symbol}")
                        # 可以考虑触发重新同步
                        # await self._init_snapshot_with_buffering(symbol)
        
        # 启动验证任务
        self._verification_tasks[symbol] = asyncio.create_task(verification_loop())
        logger.info(f"已启动 {symbol} 的验证任务，间隔: {interval_seconds}秒")

    def _update_verification_stats(self, symbol: str, is_valid: bool, details: Dict):
        """更新验证统计信息"""
        if symbol not in self._verification_stats:
            self._verification_stats[symbol] = {
                'total_verifications': 0,
                'passed_verifications': 0,
                'failed_verifications': 0,
                'last_verification_time': None,
                'last_verification_result': None,
            }
        
        stats = self._verification_stats[symbol]
        stats['total_verifications'] += 1
        
        if is_valid:
            stats['passed_verifications'] += 1
        else:
            stats['failed_verifications'] += 1
        
        stats['last_verification_time'] = time.time()
        stats['last_verification_result'] = details
        
        logger.debug(f"验证统计更新: {symbol} - 总计: {stats['total_verifications']}, "
                    f"通过: {stats['passed_verifications']}, 失败: {stats['failed_verifications']}")
        
        # 触发验证结果记录
        self._record_verification_result(symbol, is_valid, stats)    

    def get_verification_status(self, symbol: str = None) -> Dict:
        """获取验证状态"""
        if symbol:
            symbol = symbol.upper()
            stats = self._verification_stats.get(symbol, {})
            total = stats.get('total_verifications', 0)
            passed = stats.get('passed_verifications', 0)
            failed = stats.get('failed_verifications', 0)
            
            # 计算成功率
            if total > 0:
                success_rate = passed / total
            else:
                success_rate = 0
            
            return {
                'symbol': symbol,
                'verification_enabled': self._verification_enabled,
                'verification_running': symbol in self._verification_tasks,
                'total_verifications': total,
                'passed_verifications': passed,
                'failed_verifications': failed,
                'success_rate': f"{success_rate:.2%}",
                'last_verification_time': stats.get('last_verification_time'),
                'last_verification_result': stats.get('last_verification_result', {}).get('reason'),
            }
        else:
            # 返回所有交易对的汇总信息
            all_symbols = list(self._verification_stats.keys())
            
            # 计算总统计数据
            total_verifications = 0
            total_passed = 0
            total_failed = 0
            
            for stats in self._verification_stats.values():
                total_verifications += stats.get('total_verifications', 0)
                total_passed += stats.get('passed_verifications', 0)
                total_failed += stats.get('failed_verifications', 0)
            
            # 计算总成功率
            if total_verifications > 0:
                overall_success_rate = total_passed / total_verifications
            else:
                overall_success_rate = 0
            
            return {
                'total_symbols': len(all_symbols),
                'total_verifications': total_verifications,
                'total_passed': total_passed,
                'total_failed': total_failed,
                'overall_success_rate': f"{overall_success_rate:.2%}",
                'verification_enabled': self._verification_enabled,
                'running_tasks': len(self._verification_tasks),
                'symbols': all_symbols,
            } 
        
    def print_verification_summary(self):
        """打印验证统计摘要"""
        print("=" * 80)
        print("验证统计摘要")
        print("=" * 80)
        
        for symbol, stats in self._verification_stats.items():
            total = stats.get('total_verifications', 0)
            if total > 0:
                passed = stats.get('passed_verifications', 0)
                failed = stats.get('failed_verifications', 0)
                success_rate = passed / total
                
                print(f"{symbol}:")
                print(f"  总计验证: {total}")
                print(f"  通过: {passed} ({success_rate:.2%})")
                print(f"  失败: {failed}")
                print(f"  最后验证时间: {stats.get('last_verification_time')}")
                print(f"  最后结果: {stats.get('last_verification_result', {}).get('reason')}")
                print()


    def is_symbol_ready(self, symbol: str) -> bool:
        """检查symbol是否已成功初始化"""
        return self.snapshot_initialized.get(symbol.upper(), False)
    
    def get_last_trade(self, symbol: str) -> Optional[TradeTick]:
        """获取指定交易对的最新交易"""
        return self.last_trade.get(symbol.upper())
    
    def get_recent_trades(self, symbol: str, limit: int = 50) -> List[TradeTick]:
        """获取指定交易对的最近交易记录"""
        symbol = symbol.upper()
        if symbol not in self.recent_trades:
            return []
        
        # 返回最近的limit条交易记录
        trades = list(self.recent_trades[symbol])
        return trades[-limit:] if len(trades) > limit else trades
    
    def get_trade_statistics(self, symbol: str, window_seconds: int = 300) -> Dict[str, Any]:
        """
        获取交易统计信息（最近window_seconds秒内的统计）
        """
        symbol = symbol.upper()
        if symbol not in self.recent_trades:
            return {}
        
        now_timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)
        window_millis = window_seconds * 1000
        
        # 过滤窗口期内的交易
        recent_trades = [
            trade for trade in self.recent_trades[symbol]
            if now_timestamp - trade.server_timestamp <= window_millis
        ]
        
        if not recent_trades:
            return {}
        
        # 计算统计信息
        buy_trades = [t for t in recent_trades if t.side == "BUY"]
        sell_trades = [t for t in recent_trades if t.side == "SELL"]
        
        total_volume = sum(float(t.size) for t in recent_trades)
        buy_volume = sum(float(t.size) for t in buy_trades)
        sell_volume = sum(float(t.size) for t in sell_trades)
        
        prices = [float(t.price) for t in recent_trades]
        
        return {
            "symbol": symbol,
            "window_seconds": window_seconds,
            "trade_count": len(recent_trades),
            "buy_count": len(buy_trades),
            "sell_count": len(sell_trades),
            "total_volume": total_volume,
            "buy_volume": buy_volume,
            "sell_volume": sell_volume,
            "volume_ratio": float(buy_volume / sell_volume) if sell_volume > 0 else float('inf'),
            "avg_price": sum(prices) / len(prices) if prices else 0,
            "min_price": min(prices) if prices else 0,
            "max_price": max(prices) if prices else 0,
            "last_price": float(recent_trades[-1].price) if recent_trades else 0,
        }