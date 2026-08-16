const INTERVAL = 5000;
const DESKTOP_QUERY = "(min-width: 960px)";

function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function initCarousel() {
  const root = document.querySelector("[data-carousel]");
  if (!root) return;

  const list = root.querySelector(".awards__list");
  const slides = list ? [...list.children] : [];
  const prev = root.querySelector("[data-carousel-prev]");
  const next = root.querySelector("[data-carousel-next]");
  const dotsWrap = root.querySelector("[data-carousel-dots]");
  if (!list || slides.length < 2) return;

  let index = 0;
  let timer = 0;
  const desktop = window.matchMedia(DESKTOP_QUERY);

  const dots = slides.map((_, i) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "awards-carousel__dot";
    button.setAttribute("aria-label", `Aller à la distinction ${i + 1}`);
    button.addEventListener("click", () => goTo(i, true));
    dotsWrap?.append(button);
    return button;
  });

  function apply() {
    if (desktop.matches) {
      list.style.transform = "";
      root.removeAttribute("data-active");
      slides.forEach((slide) => slide.removeAttribute("aria-hidden"));
      return;
    }

    list.style.transform = `translateX(-${index * 100}%)`;
    root.setAttribute("data-active", String(index));
    slides.forEach((slide, i) => {
      slide.setAttribute("aria-hidden", i === index ? "false" : "true");
    });
    dots.forEach((dot, i) => {
      dot.setAttribute("aria-current", i === index ? "true" : "false");
    });
  }

  function goTo(nextIndex, userAction) {
    index = (nextIndex + slides.length) % slides.length;
    apply();
    if (userAction) restart();
  }

  function stop() {
    window.clearInterval(timer);
    timer = 0;
  }

  function start() {
    stop();
    if (desktop.matches || prefersReducedMotion()) return;
    timer = window.setInterval(() => goTo(index + 1, false), INTERVAL);
  }

  function restart() {
    stop();
    start();
  }

  prev?.addEventListener("click", () => goTo(index - 1, true));
  next?.addEventListener("click", () => goTo(index + 1, true));

  root.addEventListener("pointerenter", stop);
  root.addEventListener("pointerleave", start);
  root.addEventListener("focusin", stop);
  root.addEventListener("focusout", start);

  desktop.addEventListener("change", () => {
    apply();
    restart();
  });

  apply();
  start();
}
