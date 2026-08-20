/**
 * AI Agent Widget Loader v1
 *
 * One-line embed:
 *   <script src="https://app.com/widget/v1/loader.js" data-agent-id="ag_xK9mN2pQ" defer></script>
 */
(function () {
  "use strict";

  // Find our own script tag
  var currentScript =
    document.currentScript ||
    (function () {
      var scripts = document.getElementsByTagName("script");
      for (var i = scripts.length - 1; i >= 0; i--) {
        if (scripts[i].src && scripts[i].src.indexOf("loader.js") !== -1) {
          return scripts[i];
        }
      }
      return null;
    })();

  if (!currentScript) {
    console.error("[ai-agent] Could not locate loader script tag.");
    return;
  }

  var agentId = currentScript.getAttribute("data-agent-id");
  if (!agentId) {
    console.error("[ai-agent] Missing required data-agent-id attribute.");
    return;
  }

  // Derive the base URL from the script's src (strip /widget/v1/loader.js)
  var scriptSrc = currentScript.src;
  var baseUrl = scriptSrc.substring(
    0,
    scriptSrc.indexOf("/widget/v1/loader.js")
  );

  // Map channel_mode from config to the widget mode attribute
  function mapMode(channelMode) {
    if (channelMode === "text") return "chat";
    if (channelMode === "voice") return "voice";
    return "both";
  }

  // Load the widget script, then create the web component
  function initWidget(config) {
    var widgetScript = document.createElement("script");
    widgetScript.src = baseUrl + "/widget/v1/widget.js";

    widgetScript.onload = function () {
      var el = document.createElement("ai-agent");
      el.setAttribute("agent-id", config.public_id || agentId);
      el.setAttribute("mode", mapMode(config.channel_mode));
      el.setAttribute("theme", config.theme || "auto");
      el.setAttribute("position", config.position || "bottom-right");
      el.setAttribute("primary-color", config.primary_color || "#6366f1");
      el.setAttribute("button-text", config.button_text || "Talk to AI");
      el.setAttribute("base-url", baseUrl);
      document.body.appendChild(el);
    };

    widgetScript.onerror = function () {
      console.error("[ai-agent] Failed to load widget.js");
    };

    document.head.appendChild(widgetScript);
  }

  // Fetch agent config then bootstrap. The custom header is browser-settable,
  // while the API cross-checks it against the browser's real Origin header.
  var configUrl = baseUrl + "/api/v1/p/embed/" + agentId + "/config";

  fetch(configUrl, {
    headers: { "X-Embed-Parent-Origin": window.location.origin },
  })
    .then(function (res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    })
    .then(initWidget)
    .catch(function (err) {
      console.error("[ai-agent] Failed to load config:", err);
    });
})();
