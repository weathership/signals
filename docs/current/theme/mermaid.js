// Render ```mermaid fences in the book. The source stays in the markdown
// so GitHub and other renderers can use the same text. If the CDN is
// unreachable the fenced source remains on the page.
(function () {
  "use strict";

  function blocks() {
    return document.querySelectorAll("pre code.language-mermaid");
  }

  if (!blocks().length) {
    return;
  }

  function render() {
    var codes = blocks();
    var nodes = [];
    var i;
    for (i = 0; i < codes.length; i++) {
      var code = codes[i];
      var pre = code.parentElement;
      if (!pre) {
        continue;
      }
      var el = document.createElement("div");
      el.className = "mermaid";
      el.textContent = code.textContent;
      pre.replaceWith(el);
      nodes.push(el);
    }
    if (!nodes.length || !window.mermaid) {
      return;
    }
    window.mermaid.initialize({
      startOnLoad: false,
      securityLevel: "antiscript",
      flowchart: { htmlLabels: true, curve: "basis" }
    });
    var pending = window.mermaid.run({ nodes: nodes });
    if (pending && typeof pending.catch === "function") {
      pending.catch(function () {});
    }
  }

  if (window.mermaid) {
    render();
    return;
  }

  var script = document.createElement("script");
  script.src = "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.min.js";
  script.onload = render;
  document.head.appendChild(script);
})();
