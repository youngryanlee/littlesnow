# binance_adapter.py
import asyncio
import logging
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
import json

from .base_adapter import BaseAdapter
from ..service.ws_connector import WebSocketConnector
from ..service.rest_connector import RESTConnector
from ..core.data_models import MarketData, OrderBook, OrderBookLevel, ExchangeType, MarketType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BinanceAdapter
#  - 修复点：
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

    def __init__(self):
        super().__init__("binance", ExchangeType.BINANCE)
        self.ws_url = "wss://stream.binance.com:9443/ws"
        self.rest_base_url = "https://api.binance.com/api/v3"

        # 订单簿状态管理
        self.orderbook_snapshots: Dict[str, OrderBook] = {}
        self.last_update_ids: Dict[str, int] = {}
        self.pending_updates: Dict[str, List[dict]] = {}      # buffered WS updates (preserve arrival order)
        self.snapshot_initialized: Dict[str, bool] = {}
        self.using_fallback: Dict[str, bool] = {}

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
        # 回调执行线程池（用于同步回调）
        self._callback_executor = None  # lazy init

    # -----------------------
    # helper: buffer management
    # -----------------------
    def _ensure_pending_structs(self, symbol: str):
        if symbol not in self.pending_updates:
            self.pending_updates[symbol] = []
        if symbol not in self.snapshot_initialized:
            self.snapshot_initialized[symbol] = False
        if symbol not in self.using_fallback:
            self.using_fallback[symbol] = False
        if symbol not in self.orderbook_snapshots:
            self.orderbook_snapshots[symbol] = OrderBook(bids=[], asks=[], timestamp=datetime.now(timezone.utc), symbol=symbol)

    def _buffer_incoming_update(self, symbol: str, update_data: dict):
        """把接收到的 WS 增量更新按接收顺序追加进 pending buffer"""
        self._ensure_pending_structs(symbol)
        buf = self.pending_updates[symbol]
        buf.append(update_data)

        # 防护：限制 buffer 长度
        if len(buf) > self.PENDING_MAX_LEN:
            # 保留最新部分（丢弃旧的）
            keep = buf[-(self.PENDING_MAX_LEN // 2):]
            self.pending_updates[symbol] = keep
            logger.warning(f"pending_updates for {symbol} exceeded max len; trimmed to {len(keep)}")

        # 如果 buffer 极度膨胀，建议重拉 snapshot（异步触发）
        if len(self.pending_updates[symbol]) > self.PENDING_RESYNC_THRESHOLD:
            logger.warning(f"pending_updates for {symbol} reached resync threshold ({len(self.pending_updates[symbol])}), scheduling snapshot re-init")
            asyncio.create_task(self._retry_snapshot_initialization(symbol))

    # -----------------------
    # connect / subscribe
    # -----------------------
    async def connect(self) -> bool:
        """建立 WS 连接（非阻塞）"""
        try:
            success = await self.connector.connect()
            self.is_connected = success
            logger.info("Binance WS connected=%s", success)
            return success
        except Exception as e:
            logger.exception("Binance connection failed: %s", e)
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
            self._ensure_pending_structs(symbol)

        subscribe_msg = {"method": "SUBSCRIBE", "params": streams, "id": 1}
        await self.connector.send_json(subscribe_msg)
        logger.info("Subscribed to %s on Binance", symbols)

        # 并行初始化 snapshot（带 buffering 处理）
        tasks = []
        for symbol in symbols:
            # 防止重复创建多个 init 任务
            if symbol in self._init_tasks and not self._init_tasks[symbol].done():
                continue
            t = asyncio.create_task(self._init_snapshot_with_buffering(symbol))
            self._init_tasks[symbol] = t
            tasks.append(t)

        if tasks:
            # 等待这些任务完成（可选择不 await，如果想要异步后台完成把这行注释）
            await asyncio.gather(*tasks, return_exceptions=True)

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
    # snapshot init with buffering (核心修复)
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
        self._ensure_pending_structs(symbol)

        try:
            # REST snapshot via RESTConnector context manager
            async with RESTConnector(base_url=self.rest_base_url, timeout=15, name=f"binance_{symbol}") as rest:
                snapshot = await rest.get_json(f"/depth?symbol={symbol}&limit=100")
        except Exception as e:
            logger.warning("snapshot REST failed for %s: %s", symbol, e)
            # do not immediately fallback to using first update — keep snapshot uninitialized
            self.snapshot_initialized[symbol] = False
            return False

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
        orderbook = OrderBook(bids=bids, asks=asks, timestamp=datetime.now(timezone.utc), symbol=symbol)

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

        applied_any = False
        expected = last_update_id + 1

        # 找到第一个满足 U <= expected <= u 的 update
        for upd in filtered:
            U = upd.get('U')
            u = upd.get('u')
            if U is None or u is None:
                # 如果字段缺失，跳过；但保留在 buffer 里以供后续判断或直接丢弃
                continue
            if U <= expected <= u:
                # apply this update
                try:
                    self._apply_orderbook_update(symbol, upd)
                    self.last_update_ids[symbol] = int(u)
                    expected = int(u) + 1
                    applied_any = True
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
                        self._apply_orderbook_update(symbol, upd)
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
            # 没有找到可以链上的更新 => 可能 out-of-sync；清空 buffer（或视策略保留）
            logger.info("No buffered updates chained for %s (buffered=%d). Clearing pending buffer.", symbol, len(buffered))
            self.pending_updates[symbol] = []

        return True

    # -----------------------
    # raw message handler（WS 回调入口）
    # -----------------------
    def _handle_raw_message(self, raw_data: dict):
        """
        on_message 入口。raw_data 可能是 stream 包装（{stream, data}）或 event 格式（{e: 'depthUpdate', ...}）
        我们把深度更新转到 _handle_orderbook_update。
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
            else:
                logger.debug("Unrecognized message shape from Binance WS: %s", raw_data)
        except Exception as e:
            logger.exception("Error handling raw message: %s", e)

    # -----------------------
    # orderbook update core
    # -----------------------
    def _handle_orderbook_update(self, data: dict):
        """处理订单簿增量更新（会先 buffer 未初始化状态下的更新）"""
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

            self._ensure_pending_structs(symbol)

            # 如果 snapshot 未初始化，缓冲更新
            if not self.snapshot_initialized.get(symbol, False):
                self._buffer_incoming_update(symbol, update_data)
                return

            # 下面是已初始化的常规处理逻辑，遵循 U/u 连续性与丢弃规则
            current_U = update_data.get('U')
            current_u = update_data.get('u')
            last_update_id = self.last_update_ids.get(symbol)

            # fallback 模式直接应用
            if self.using_fallback.get(symbol, False):
                self._apply_orderbook_update(symbol, update_data)
                if current_u is not None:
                    self.last_update_ids[symbol] = int(current_u)
                return

            # 丢弃旧更新
            if last_update_id is not None and current_u is not None and int(current_u) <= int(last_update_id):
                logger.debug("Dropping old update for %s: u=%s <= last=%s", symbol, current_u, last_update_id)
                return

            # 若能直接链上，应用之：U <= lastUpdateId+1 <= u
            if last_update_id is not None and current_U is not None and current_u is not None:
                expected = int(last_update_id) + 1
                if int(current_U) <= expected <= int(current_u):
                    # apply
                    self._apply_orderbook_update(symbol, update_data)
                    self.last_update_ids[symbol] = int(current_u)
                    # 之后尝试处理缓存 pending（如果有）
                    self._process_pending_updates(symbol)
                    return
                elif int(current_U) > expected:
                    # 说明 snapshot 过时（掉包），触发重新初始化（异步）
                    logger.warning("Snapshot outdated for %s: U=%s > expected=%s, scheduling re-init", symbol, current_U, expected)
                    asyncio.create_task(self._handle_outdated_snapshot(symbol, update_data))
                    return
                else:
                    # 无法链上 -> 缓存此更新
                    self._buffer_incoming_update(symbol, update_data)
                    return
            else:
                # 没有 last_update_id 的情况（通常不应发生） -> 尝试直接应用
                logger.debug("No last_update_id for %s, applying update directly", symbol)
                self._apply_orderbook_update(symbol, update_data)
                if current_u is not None:
                    self.last_update_ids[symbol] = int(current_u)
                return

        except Exception as e:
            logger.exception("Error processing Binance orderbook update: %s", e)

    def _process_pending_updates(self, symbol: str):
        """处理 pending buffer 中的更新（严格按序）"""
        if symbol not in self.pending_updates or not self.pending_updates[symbol]:
            return

        pending = list(self.pending_updates[symbol])  # copy
        last_update_id = self.last_update_ids.get(symbol)
        if last_update_id is None:
            return

        logger.debug("Processing %d pending updates for %s (last=%s)", len(pending), symbol, last_update_id)

        processed = 0
        # 按接收顺序遍历 pending，按能否链上去执行
        for upd in pending[:]:
            curU = upd.get('U')
            curu = upd.get('u')
            if curU is None or curu is None:
                # skip malformed
                pending.remove(upd)
                continue
            expected = int(last_update_id) + 1
            if int(curU) <= expected <= int(curu):
                # apply
                try:
                    self._apply_orderbook_update(symbol, upd)
                    last_update_id = int(curu)
                    self.last_update_ids[symbol] = last_update_id
                    processed += 1
                    pending.remove(upd)
                except Exception:
                    logger.exception("Failed applying pending update for %s", symbol)
                    break
            else:
                # cannot chain, stop processing further because ordering matters
                break

        # 更新 pending buffer （剩余按接收顺序保留）
        self.pending_updates[symbol] = pending
        logger.debug("Processed %d pending updates for %s; remaining=%d", processed, symbol, len(pending))

    # -----------------------
    # apply update -> snapshot merge
    # -----------------------
    def _apply_orderbook_update(self, symbol: str, update_data: dict):
        """把增量更新应用到本地 snapshot（简化的 add/remove 模型）"""
        try:
            current_orderbook = self.orderbook_snapshots.get(symbol)
            if current_orderbook is None:
                # create empty placeholder
                current_orderbook = OrderBook(bids=[], asks=[], timestamp=datetime.now(timezone.utc), symbol=symbol)

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

            # timestamp 使用事件时间 E（若有）或系统时间
            if 'E' in update_data:
                timestamp = datetime.fromtimestamp(update_data['E'] / 1000, tz=timezone.utc)
            else:
                timestamp = datetime.now(timezone.utc)

            updated = OrderBook(bids=new_bids, asks=new_asks, timestamp=timestamp, symbol=symbol)
            self.orderbook_snapshots[symbol] = updated

            # 发布 MarketData 给下游（非阻塞）
            market_data = MarketData(
                symbol=symbol,
                exchange=ExchangeType.BINANCE,
                market_type=MarketType.SPOT,
                timestamp=datetime.now(timezone.utc),
                orderbook=updated
            )

            logger.debug("Applied orderbook update for %s: bids=%d asks=%d", symbol, len(new_bids), len(new_asks))
            # dispatch callbacks asynchronously
            self._notify_callbacks(market_data)

        except Exception as e:
            logger.exception("Error applying orderbook update for %s: %s", symbol, e)
            raise

    # -----------------------
    # callbacks dispatch (非阻塞)
    # -----------------------
    def _ensure_callback_executor(self):
        if self._callback_executor is None:
            # lazy init a thread pool for sync callbacks
            loop = asyncio.get_event_loop()
            from concurrent.futures import ThreadPoolExecutor
            self._callback_executor = ThreadPoolExecutor(max_workers=4)

    def _notify_callbacks(self, market_data: MarketData):
        """
        将回调执行异步化：
         - 如果 callback 是协程函数，直接 create_task(awaitable)
         - 否则交给线程池执行以免阻塞事件循环
        """
        if not self.callbacks:
            return

        loop = asyncio.get_event_loop()
        self._ensure_callback_executor()

        for cb in list(self.callbacks):
            if asyncio.iscoroutinefunction(cb):
                try:
                    loop.create_task(cb(market_data))
                except Exception:
                    logger.exception("Failed scheduling coroutine callback")
            else:
                # run sync callback in threadpool to avoid blocking
                try:
                    loop.run_in_executor(self._callback_executor, cb, market_data)
                except Exception:
                    logger.exception("Failed scheduling sync callback")

    # -----------------------
    # trade / misc
    # -----------------------
    def _handle_trade(self, data: dict):
        # trade 消息目前可记录或转发给下游（这里保留空实现）
        try:
            logger.debug("Trade message (binance): %s", data if isinstance(data, dict) else str(data)[:200])
        except Exception:
            logger.exception("Error processing trade message")

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

    async def _retry_snapshot_initialization(self, symbol: str):
        """重试 snapshot 初始化（在严重 pending 堆积时）"""
        try:
            logger.info("Retrying snapshot initialization for %s", symbol)
            await self._init_snapshot_with_buffering(symbol)
        except Exception:
            logger.exception("Snapshot re-init failed for %s", symbol)

    # -----------------------
    # normalize / status
    # -----------------------
    def normalize_data(self, raw_data: dict) -> Optional[MarketData]:
        """保留用于兼容接口的占位方法"""
        return None

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
            "snapshot_initialized": dict(self.snapshot_initialized),
            "using_fallback": dict(self.using_fallback)
        }
