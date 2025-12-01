import aiohttp
import asyncio
import socket
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def check_dns_resolution():
    """检查 DNS 解析"""
    try:
        logger.info("解析 stream.binance.com...")
        result = socket.getaddrinfo("stream.binance.com", 9443)
        logger.info(f"DNS 解析成功: {result}")
        return True
    except Exception as e:
        logger.error(f"DNS 解析失败: {e}")
        return False

async def check_rest_api():
    """检查 REST API 连通性"""
    url = "https://api.binance.com/api/v3/ping"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                logger.info(f"REST API 状态: {response.status}")
                return response.status == 200
    except Exception as e:
        logger.error(f"REST API 连接失败: {e}")
        return False

async def check_websocket_direct():
    """直接测试 WebSocket 连接"""
    url = "wss://stream.binance.com:9443/ws"
    try:
        async with aiohttp.ClientSession() as session:
            logger.info("尝试 WebSocket 连接...")
            async with session.ws_connect(url, timeout=10) as ws:
                logger.info("WebSocket 连接成功!")
                return True
    except asyncio.TimeoutError:
        logger.error("WebSocket 连接超时")
        return False
    except Exception as e:
        logger.error(f"WebSocket 连接失败: {e}")
        return False

async def main():
    print("=== 网络连通性检查 ===")
    
    dns_ok = await check_dns_resolution()
    rest_ok = await check_rest_api()
    ws_ok = await check_websocket_direct()
    
    print(f"\n=== 检查结果 ===")
    print(f"DNS 解析: {'✅ 成功' if dns_ok else '❌ 失败'}")
    print(f"REST API: {'✅ 成功' if rest_ok else '❌ 失败'}")
    print(f"WebSocket: {'✅ 成功' if ws_ok else '❌ 失败'}")
    
    return all([dns_ok, rest_ok, ws_ok])

if __name__ == "__main__":
    result = asyncio.run(main())
    exit(0 if result else 1)