// Optional API key support for PyNode.
//
// Loaded as a CLASSIC script before the js/main.js module bundle (classic
// scripts execute during parse; module scripts are deferred), so the fetch
// wrapper below is installed before any application code runs. Every
// frontend module calls the global fetch() with '/api/...' URLs, so
// wrapping window.fetch here covers ALL API requests (JSON, FormData
// uploads, DELETEs, ...) without touching individual call sites.
//
// When the server has no API key configured it never returns 401, so none
// of this activates and behavior is identical to before.
(function () {
    'use strict';

    var STORAGE_KEY = 'pynode_api_key';
    var nativeFetch = window.fetch.bind(window);
    var prompting = false; // Only ever prompt once (page reloads on success)

    function getStoredKey() {
        try {
            return window.localStorage.getItem(STORAGE_KEY) || '';
        } catch (e) {
            return '';
        }
    }

    function storeKey(key) {
        try {
            window.localStorage.setItem(STORAGE_KEY, key);
        } catch (e) {
            // localStorage unavailable; the key is lost on reload but the
            // user will simply be prompted again.
        }
    }

    function isApiRequest(input) {
        var url = (typeof input === 'string') ? input : ((input && input.url) || '');
        try {
            var u = new URL(url, window.location.href);
            return u.origin === window.location.origin && u.pathname.indexOf('/api/') === 0;
        } catch (e) {
            return false;
        }
    }

    function withApiKey(init, key) {
        var next = Object.assign({}, init);
        var headers = new Headers((init && init.headers) || undefined);
        headers.set('X-API-Key', key);
        next.headers = headers;
        return next;
    }

    window.fetch = function (input, init) {
        if (!isApiRequest(input)) {
            return nativeFetch(input, init);
        }
        var key = getStoredKey();
        return nativeFetch(input, key ? withApiKey(init, key) : init).then(function (response) {
            if (response.status !== 401 || prompting) {
                return response;
            }
            prompting = true;
            var entered = window.prompt(
                'This PyNode server requires an API key.\nEnter the API key:');
            if (!entered) {
                prompting = false;
                return response; // User cancelled; surface the 401 as-is
            }
            storeKey(entered);
            // Verify the key against the failed request, then reload so
            // every in-flight/initial request reruns with the key attached.
            return nativeFetch(input, withApiKey(init, entered)).then(function (retry) {
                if (retry.status === 401) {
                    prompting = false;
                    window.alert('API key rejected by the server.');
                    return retry;
                }
                window.location.reload();
                // Hold callers until the reload tears the page down.
                return new Promise(function () {});
            });
        });
    };

    // For consumers that cannot set headers (EventSource / SSE): returns the
    // stored key so it can be passed as an api_key query parameter.
    window.pynodeApiKey = getStoredKey;
})();
