const SELECTOR = ".animIn";
const DELAY_ATTR = "data-animation-delay-in-seconds";

function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function applyDelay(element) {
  const delay = element.getAttribute(DELAY_ATTR);
  if (delay) {
    element.style.setProperty("--anim-delay", delay);
  }
}

export function initAnimator() {
  const nodes = document.querySelectorAll(SELECTOR);
  if (!nodes.length) return;

  nodes.forEach(applyDelay);

  if (prefersReducedMotion()) {
    nodes.forEach((node) => node.classList.add("animated"));
    return;
  }

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("animated");
        observer.unobserve(entry.target);
      });
    },
    { threshold: 0.5 }
  );

  nodes.forEach((node) => observer.observe(node));
}
