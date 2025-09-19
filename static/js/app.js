// Configuração global
const API_BASE = '/api';

// Token management
function getToken() {
    return localStorage.getItem('token');
}

function isAuthenticated() {
    const token = getToken();
    if (!token) return false;
    
    try {
        // Verificar se o token não expirou (básico)
        const payload = JSON.parse(atob(token.split('.')[1]));
        return payload.exp * 1000 > Date.now();
    } catch {
        return false;
    }
}

function logout() {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    window.location.href = '/';
}

// HTTP client com autenticação
async function fetchWithAuth(url, options = {}) {
    const token = getToken();
    
    const defaultOptions = {
        headers: {
            'Content-Type': 'application/json',
            ...(token && { 'Authorization': `Bearer ${token}` })
        }
    };
    
    const mergedOptions = {
        ...defaultOptions,
        ...options,
        headers: {
            ...defaultOptions.headers,
            ...options.headers
        }
    };
    
    const response = await fetch(url, mergedOptions);
    
    // Se não autorizado, fazer logout
    if (response.status === 401) {
        logout();
        return;
    }
    
    return response;
}

// Verificar autenticação nas páginas protegidas
function requireAuth() {
    if (!isAuthenticated()) {
        window.location.href = '/';
        return false;
    }
    
    // Atualizar informações do usuário na navbar
    const user = JSON.parse(localStorage.getItem('user') || '{}');
    const userNameElement = document.getElementById('userName');
    const brokersMenu = document.getElementById('brokersMenu');
    
    if (userNameElement) {
        userNameElement.textContent = user.name || 'Usuário';
    }
    
    // Mostrar menus apenas para admin
    if (user.is_admin) {
        if (brokersMenu) brokersMenu.style.display = 'block';
        const settingsMenu = document.getElementById('settingsMenu');
        if (settingsMenu) settingsMenu.style.display = 'block';
        const whatsappMenu = document.getElementById('whatsappMenu');
        if (whatsappMenu) whatsappMenu.style.display = 'block';
    }
    
    return true;
}

// Utilitários
function formatDate(dateString) {
    return new Date(dateString).toLocaleDateString('pt-BR', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

function formatPhone(phone) {
    // Formatar telefone brasileiro
    return phone.replace(/(\d{2})(\d{5})(\d{4})/, '($1) $2-$3');
}

function getStatusBadge(status) {
    const statusMap = {
        'novo': { class: 'bg-info', text: 'Novo' },
        'em_andamento': { class: 'bg-warning text-dark', text: 'Em Andamento' },
        'fechado': { class: 'bg-success', text: 'Fechado' },
        'perdido': { class: 'bg-danger', text: 'Perdido' }
    };
    
    const config = statusMap[status] || { class: 'bg-secondary', text: status };
    return `<span class="badge ${config.class}">${config.text}</span>`;
}

// Notificações
function showToast(title, message, type = 'info') {
    const toastContainer = document.getElementById('toastContainer') || createToastContainer();
    
    const toastId = 'toast-' + Date.now();
    const iconMap = {
        'success': 'bi-check-circle',
        'error': 'bi-exclamation-triangle',
        'warning': 'bi-exclamation-triangle',
        'info': 'bi-info-circle'
    };
    
    const colorMap = {
        'success': 'text-success',
        'error': 'text-danger',
        'warning': 'text-warning',
        'info': 'text-info'
    };
    
    const toastHtml = `
        <div class="toast" id="${toastId}" role="alert" aria-live="assertive" aria-atomic="true">
            <div class="toast-header">
                <i class="bi ${iconMap[type]} ${colorMap[type]} me-2"></i>
                <strong class="me-auto">${title}</strong>
                <button type="button" class="btn-close" data-bs-dismiss="toast"></button>
            </div>
            <div class="toast-body">${message}</div>
        </div>
    `;
    
    toastContainer.insertAdjacentHTML('beforeend', toastHtml);
    
    const toast = new bootstrap.Toast(document.getElementById(toastId));
    toast.show();
    
    // Remover toast após ser fechado
    document.getElementById(toastId).addEventListener('hidden.bs.toast', function() {
        this.remove();
    });
}

function createToastContainer() {
    const container = document.createElement('div');
    container.id = 'toastContainer';
    container.className = 'toast-container position-fixed top-0 end-0 p-3';
    container.style.zIndex = '9999';
    document.body.appendChild(container);
    return container;
}

// Loading states
function showLoading(element, text = 'Carregando...') {
    const originalContent = element.innerHTML;
    element.dataset.originalContent = originalContent;
    element.innerHTML = `
        <span class="spinner-border spinner-border-sm me-2"></span>
        ${text}
    `;
    element.disabled = true;
}

function hideLoading(element) {
    const originalContent = element.dataset.originalContent;
    if (originalContent) {
        element.innerHTML = originalContent;
        delete element.dataset.originalContent;
    }
    element.disabled = false;
}

// Validações
function validateEmail(email) {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
}

function validatePhone(phone) {
    const phoneRegex = /^\(\d{2}\)\s\d{4,5}-\d{4}$/;
    return phoneRegex.test(phone) || /^\d{10,11}$/.test(phone.replace(/\D/g, ''));
}

// Máscaras
function maskPhone(input) {
    let value = input.value.replace(/\D/g, '');
    if (value.length <= 10) {
        value = value.replace(/(\d{2})(\d{4})(\d{4})/, '($1) $2-$3');
    } else {
        value = value.replace(/(\d{2})(\d{5})(\d{4})/, '($1) $2-$3');
    }
    input.value = value;
}

// Filtros
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Confirmações
function confirmAction(message, callback) {
    if (confirm(message)) {
        callback();
    }
}

// Inicialização global
document.addEventListener('DOMContentLoaded', function() {
    // Verificar autenticação em páginas protegidas
    if (window.location.pathname !== '/') {
        requireAuth();
    }
    
    // Configurar tooltips do Bootstrap
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
    
    // Configurar popovers do Bootstrap
    const popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'));
    popoverTriggerList.map(function (popoverTriggerEl) {
        return new bootstrap.Popover(popoverTriggerEl);
    });
});

// Exportar funções globalmente
window.app = {
    fetchWithAuth,
    showToast,
    formatDate,
    formatPhone,
    getStatusBadge,
    showLoading,
    hideLoading,
    validateEmail,
    validatePhone,
    maskPhone,
    debounce,
    confirmAction,
    logout,
    requireAuth
};