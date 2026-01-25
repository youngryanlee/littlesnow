export function createWebSocketService() {
    let ws = null;
    let reconnectAttempts = 0;
    const maxReconnectAttempts = 5;
    const listeners = new Map();
    
    function connect() {
        if (ws?.readyState === WebSocket.OPEN) {
            return;
        }
        
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;
        
        console.log(`连接WebSocket: ${wsUrl}`);
        
        ws = new WebSocket(wsUrl);
        
        ws.onopen = () => {
            console.log('✅ WebSocket连接已建立');
            reconnectAttempts = 0;
            emit('connected');
            
            // 请求初始数据
            setTimeout(() => {
                requestInitialData();
            }, 1000);
        };
        
        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                emit('message', data);
            } catch (error) {
                console.error('解析消息失败:', error);
            }
        };
        
        ws.onclose = (event) => {
            console.log('WebSocket连接已关闭', event);
            emit('disconnected');
            
            // 自动重连
            if (reconnectAttempts < maxReconnectAttempts) {
                reconnectAttempts++;
                const delay = Math.min(3000 * reconnectAttempts, 30000);
                console.log(`将在 ${delay}ms 后重连 (${reconnectAttempts}/${maxReconnectAttempts})`);
                
                setTimeout(() => {
                    connect();
                }, delay);
            }
        };
        
        ws.onerror = (error) => {
            console.error('WebSocket错误:', error);
            emit('error', error);
        };
    }
    
    function disconnect() {
        if (ws) {
            ws.close();
            ws = null;
        }
    }
    
    function send(data) {
        if (ws?.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify(data));
            return true;
        }
        return false;
    }
    
    function requestInitialData() {
        send({ type: 'get_initial_data' });
    }
    
    // 事件系统
    function on(event, callback) {
        if (!listeners.has(event)) {
            listeners.set(event, []);
        }
        listeners.get(event).push(callback);
    }
    
    function off(event, callback) {
        if (listeners.has(event)) {
            const callbacks = listeners.get(event);
            const index = callbacks.indexOf(callback);
            if (index > -1) {
                callbacks.splice(index, 1);
            }
        }
    }
    
    function emit(event, data) {
        if (listeners.has(event)) {
            listeners.get(event).forEach(callback => {
                try {
                    callback(data);
                } catch (error) {
                    console.error(`事件 ${event} 的回调函数出错:`, error);
                }
            });
        }
    }
    
    return {
        connect,
        disconnect,
        send,
        requestInitialData,
        on,
        off,
        
        // 状态查询
        get isConnected() {
            return ws?.readyState === WebSocket.OPEN;
        }
    };
}