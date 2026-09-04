/* Ledger portal behaviour: live status, count-up figures, section reveal,
   and the illustrative write-path animation. No dependencies. */

(function () {
  "use strict";

  // Marks that the script is alive. The reveal animation is scoped to this
  // class so a failed script load leaves the page readable rather than blank.
  document.documentElement.classList.add("js");

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- live status ---------- */

  function setDot(el, state) {
    if (!el) return;
    el.classList.remove("on", "bad");
    if (state) el.classList.add(state);
  }

  function text(id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function fmt(n) {
    return typeof n === "number" ? n.toLocaleString("en-GB") : "—";
  }

  function degrade() {
    text("live-text", "UNREACHABLE");
    setDot(document.getElementById("live-dot"), "bad");
    text("s-api", "unreachable");
    setDot(document.getElementById("s-api-dot"), "bad");
    text("s-db", "unknown");
    setDot(document.getElementById("s-db-dot"), "bad");
  }

  function refresh() {
    fetch("/status", { cache: "no-store" })
      .then(function (r) {
        if (!r.ok) throw new Error("status " + r.status);
        return r.json();
      })
      .then(function (d) {
        text("live-text", "LIVE");
        setDot(document.getElementById("live-dot"), "on");

        text("s-api", "operational");
        setDot(document.getElementById("s-api-dot"), "on");
        text("s-db", d.database === "connected" ? "connected" : "unavailable");
        setDot(
          document.getElementById("s-db-dot"),
          d.database === "connected" ? "on" : "bad"
        );

        var lat = d.db_latency_ms;
        text("s-lat", (lat > 0 ? lat : "<1") + " ms");
        text("s-txn", fmt(d.transactions));
        text("s-entries", fmt(d.ledger_entries));
        text("s-accounts", fmt(d.accounts));
        text("s-pending", fmt(d.outbox_pending));
      })
      .catch(degrade);
  }

  refresh();
  setInterval(refresh, 30000);

  /* ---------- count-up ---------- */

  function countUp(el) {
    var target = parseInt(el.getAttribute("data-count"), 10);
    if (isNaN(target)) return;
    if (reduceMotion || target === 0) {
      el.textContent = String(target);
      return;
    }
    var start = performance.now();
    var dur = 900;
    function step(now) {
      var p = Math.min((now - start) / dur, 1);
      // ease-out cubic
      var eased = 1 - Math.pow(1 - p, 3);
      el.textContent = String(Math.round(target * eased));
      if (p < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  /* ---------- reveal on scroll ---------- */

  var bands = document.querySelectorAll(".band");

  if (!("IntersectionObserver" in window)) {
    bands.forEach(function (b) { b.classList.add("in"); });
    document.querySelectorAll("[data-count]").forEach(countUp);
    document.querySelectorAll(".bar-fill").forEach(function (b) {
      b.classList.add("go");
    });
    return;
  }

  var io = new IntersectionObserver(
    function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        var el = entry.target;
        el.classList.add("in");

        el.querySelectorAll("[data-count]").forEach(countUp);
        el.querySelectorAll(".bar-fill").forEach(function (bar) {
          bar.classList.add("go");
        });

        io.unobserve(el);
      });
    },
    { threshold: 0.12, rootMargin: "0px 0px -40px 0px" }
  );

  bands.forEach(function (b) { io.observe(b); });

  /* ---------- write-path animation ---------- */

  var btn = document.getElementById("flow-btn");
  var steps = document.querySelectorAll("#flow-steps li");
  var result = document.getElementById("flow-result");
  var running = false;

  function runFlow() {
    if (running) return;
    running = true;
    btn.disabled = true;

    steps.forEach(function (s) { s.classList.remove("done"); });
    result.classList.remove("show");

    if (reduceMotion) {
      steps.forEach(function (s) { s.classList.add("done"); });
      result.classList.add("show");
      running = false;
      btn.disabled = false;
      return;
    }

    var i = 0;
    var timer = setInterval(function () {
      if (i < steps.length) {
        steps[i].classList.add("done");
        i += 1;
        return;
      }
      clearInterval(timer);
      result.classList.add("show");
      running = false;
      btn.disabled = false;
    }, 260);
  }

  if (btn) btn.addEventListener("click", runFlow);
})();
