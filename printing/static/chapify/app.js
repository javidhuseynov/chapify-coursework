/* Chapify: small progressive enhancements. The app works fully without JavaScript;
   the server always calculates the authoritative price. */
(function () {
  "use strict";

  // 1. Upload: show the chosen file name and highlight the drop area while dragging.
  document.querySelectorAll("[data-dropzone]").forEach(function (zone) {
    var input = zone.querySelector('input[type="file"]');
    var output = zone.querySelector("[data-file-name]");
    if (!input || !output) return;

    input.addEventListener("change", function () {
      var file = input.files && input.files[0];
      if (!file) { output.textContent = ""; return; }
      var size = file.size >= 1048576
        ? (file.size / 1048576).toFixed(1) + " MB"
        : Math.max(1, Math.round(file.size / 1024)) + " KB";
      output.textContent = file.name + " (" + size + ")";
    });
    ["dragenter", "dragover"].forEach(function (name) {
      zone.addEventListener(name, function () { zone.classList.add("is-dragging"); });
    });
    ["dragleave", "drop"].forEach(function (name) {
      zone.addEventListener(name, function () { zone.classList.remove("is-dragging"); });
    });
  });

  // 2. Print settings: live price estimate using the published coefficients.
  var dataNode = document.getElementById("pricing-data");
  var form = document.querySelector("[data-price-form]");
  var output = document.querySelector("[data-price-estimate]");
  if (!dataNode || !form || !output) return;

  var pricing = JSON.parse(dataNode.textContent);

  function selected(name) {
    var checked = form.querySelector('input[name="' + name + '"]:checked');
    if (checked) return checked.value;
    var field = form.querySelector('[name="' + name + '"]');
    return field ? field.value : null;
  }

  function update() {
    var copies = parseInt(selected("copies"), 10);
    var color = pricing.color[selected("color_mode")];
    var paper = pricing.paper[selected("paper_format")];
    var duplex = pricing.duplex[selected("duplex_mode")];
    if (!copies || copies < 1 || !color || !paper || !duplex) { output.textContent = "-"; return; }
    var total = pricing.pages * copies * pricing.base * color * paper * duplex;
    output.textContent = (Math.round(total * 100 + 1e-9) / 100).toFixed(2);
  }

  form.addEventListener("input", update);
  form.addEventListener("change", update);
  update();
})();
