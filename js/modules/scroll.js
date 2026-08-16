const DURATION = 800;
const EXTRA_OFFSET = 8;

function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function easeOutQuad(t) {
  return t * (2 - t);
}

function animateScrollTo(targetY, duration) {
  const startY = window.scrollY;
  const distance = targetY - startY;
  const startTime = performance.now();

  return new Promise((resolve) => {
    function step(now) {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      window.scrollTo(0, startY + distance * easeOutQuad(progress));
      if (progress < 1) {
        requestAnimationFrame(step);
      } else {
        resolve();
      }
    }
    requestAnimationFrame(step);
  });
}

function headerOffset() {
  const header = document.querySelector(".site-header");
  return (header ? header.offsetHeight : 0) + EXTRA_OFFSET;
}

export function initSmoothScroll() {
  document.addEventListener("click", (event) => {
    const link = event.target.closest('a[href^="#"]');
    if (!link) return;

    const hash = link.getAttribute("href");
    if (!hash || hash === "#") return;

    const target = document.querySelector(hash);
    if (!target) return;

    event.preventDefault();
    const top = target.getBoundingClientRect().top + window.scrollY - headerOffset();

    const finish = () => {
      history.pushState(null, "", hash);
      if (!target.hasAttribute("tabindex")) {
        target.setAttribute("tabindex", "-1");
      }
      target.focus({ preventScroll: true });
    };

    if (prefersReducedMotion()) {
      window.scrollTo(0, top);
      finish();
      return;
    }

    animateScrollTo(top, DURATION).then(finish);
  });
}
