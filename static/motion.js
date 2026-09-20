/* Motion for the first useful Steam result paint. Anime.js v4.5.0 is vendored locally. */
(() => {
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let activeAnimation = null;
  let activeTargets = [];

  function cancelActive() {
    if (activeAnimation) activeAnimation.cancel();
    if (activeTargets.length && window.anime) window.anime.set(activeTargets, { opacity: 1, y: 0 });
    activeAnimation = null;
    activeTargets = [];
  }

  function revealResults(root) {
    cancelActive();
    const targets = [...root.querySelectorAll(".card, tbody tr")].slice(0, 24);
    if (!targets.length || !window.anime) return;
    if (reducedMotion.matches) {
      window.anime.set(targets, { opacity: 1, y: 0 });
      return;
    }
    activeTargets = targets;
    activeAnimation = window.anime.animate(targets, {
      opacity: { from: 0 },
      y: { from: 8 },
      duration: 240,
      delay: window.anime.stagger(14),
      ease: "out(3)",
      onComplete: () => { activeAnimation = null; activeTargets = []; },
    });
  }

  function handlePreferenceChange() {
    if (reducedMotion.matches) cancelActive();
  }

  reducedMotion.addEventListener("change", handlePreferenceChange);
  window.GamePromoMotion = { revealResults };
  window.addEventListener("pagehide", () => {
    cancelActive();
    reducedMotion.removeEventListener("change", handlePreferenceChange);
    delete window.GamePromoMotion;
  }, { once: true });
})();
