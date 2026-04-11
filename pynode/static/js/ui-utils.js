// UI utilities
export function showToast(message, type = 'info', duration = 3000) {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.classList.remove('toast-error');
    if (type === 'error') {
        toast.classList.add('toast-error');
        duration = Math.max(duration, 5000);
    }
    toast.classList.add('show');
    
    setTimeout(() => {
        toast.classList.remove('show');
    }, duration);
}
