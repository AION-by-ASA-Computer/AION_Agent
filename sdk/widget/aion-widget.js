/**
 * Minimal embed stub: full UI should use @aion/client + your framework.
 * Usage: see sdk/typescript for EventSource-compatible streaming with API keys.
 */
(function (global) {
  global.AionWidget = {
    init: function (opts) {
      console.info("[AionWidget] init", opts && opts.baseUrl);
    },
  };
})(typeof window !== "undefined" ? window : globalThis);
