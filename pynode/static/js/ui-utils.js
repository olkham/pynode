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

/**
 * Copy text to the clipboard, returning true on success.
 *
 * navigator.clipboard only exists in a secure context, so it is missing on
 * the plain-http LAN origins PyNode is usually reached on (http://<host>:5000).
 * Fall back to the legacy execCommand path there rather than silently doing
 * nothing.
 */
export async function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch (error) {
            // Permission denied / not focused - try the legacy path below.
            console.warn('Clipboard API copy failed, falling back:', error);
        }
    }

    const textarea = document.createElement('textarea');
    textarea.value = text;
    // Off-screen but still focusable: execCommand('copy') needs a real
    // selection in the document, so display:none / hidden will not work.
    textarea.style.position = 'fixed';
    textarea.style.top = '-1000px';
    textarea.setAttribute('readonly', '');
    document.body.appendChild(textarea);
    try {
        textarea.select();
        return document.execCommand('copy');
    } catch (error) {
        console.error('Copy to clipboard failed:', error);
        return false;
    } finally {
        textarea.remove();
    }
}

/**
 * Reveal the node Information panel: expand the right sidebar if the user
 * collapsed it, then activate its Info tab. Backs the properties panel's
 * `hint` rows, which point users at info-panel content.
 */
export function showInfoPanel() {
    const sidebar = document.getElementById('right-sidebar');
    if (sidebar && sidebar.classList.contains('collapsed')) {
        // Click the grab handle's toggle rather than editing classes here:
        // the collapsed flag and the persisted width live in that button's
        // own closure (setupOneSidePanelGrab in events.js).
        document.getElementById('right-sidebar-toggle')?.click();
    }
    document.querySelector('.sidebar-tab[data-panel="info"]')?.click();
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
