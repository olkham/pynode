// UI utilities

/**
 * Human-readable display label for a node category.
 * Underlying category values stay as the nodes declare them (compared
 * case-insensitively everywhere); only the label is prettified:
 * 'common' -> 'Common', 'node probes' -> 'Node Probes', 'opencv' -> 'OpenCV'.
 */
export function categoryLabel(category) {
    const key = String(category || 'custom').toLowerCase();
    if (key === 'opencv') return 'OpenCV';
    return key.replace(/\b\w/g, ch => ch.toUpperCase());
}

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
