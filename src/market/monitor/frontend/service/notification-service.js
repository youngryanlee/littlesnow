// frontend/service/notification-service.js
export function createNotificationService() {
    return {
        show: (title, message, type = 'info') => {
            console.log(`[${type.toUpperCase()}] ${title}: ${message}`);
            
            // 简单的前端通知实现
            const notification = document.createElement('div');
            notification.className = `alert alert-${type} alert-dismissible fade show position-fixed`;
            notification.style.cssText = `
                position: fixed;
                top: 20px;
                right: 20px;
                z-index: 9999;
                min-width: 300px;
                max-width: 500px;
            `;
            
            const icons = {
                success: 'check-circle',
                error: 'exclamation-circle',
                warning: 'exclamation-triangle',
                info: 'info-circle'
            };
            
            notification.innerHTML = `
                <div class="d-flex align-items-center">
                    <i class="bi bi-${icons[type] || 'info-circle'} me-2"></i>
                    <div>
                        <strong>${title}</strong>
                        <div class="small">${message}</div>
                    </div>
                </div>
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            `;
            
            document.body.appendChild(notification);
            
            // 5秒后自动移除
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.remove();
                }
            }, 5000);
        }
    };
}