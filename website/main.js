const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");

const video = document.getElementById("hero-video");
if (video) {
  const apply = () => {
    if (reduce.matches) {
      video.pause();
      video.removeAttribute("autoplay");
    } else if (video.paused) {
      video.play().catch(() => {});
    }
  };
  apply();
  reduce.addEventListener("change", apply);
}

for (const btn of document.querySelectorAll("button[data-copy]")) {
  btn.addEventListener("click", async () => {
    const text = document.getElementById(btn.dataset.copy)?.textContent ?? "";
    try {
      await navigator.clipboard.writeText(text);
      btn.textContent = "Copied";
    } catch {
      btn.textContent = "Select it";
    }
    setTimeout(() => { btn.textContent = "Copy"; }, 1600);
  });
}

// The raw receipt line types in once, the first time it scrolls into view.
const raw = document.querySelector("[data-type]");
if (raw && !reduce.matches && "IntersectionObserver" in window) {
  const full = raw.textContent;
  raw.setAttribute("aria-label", full);
  raw.textContent = "";
  const io = new IntersectionObserver((entries) => {
    if (!entries.some((e) => e.isIntersecting)) return;
    io.disconnect();
    let i = 0;
    const step = () => {
      i += 2;
      raw.textContent = full.slice(0, i);
      if (i < full.length) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }, { threshold: 0.6 });
  io.observe(raw);
}
