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

// Background light motes, the same particles that drift around the hero object.
// Drawn once and left still when the visitor prefers reduced motion.
const field = document.querySelector(".bg");
if (field) {
  const canvas = document.createElement("canvas");
  field.appendChild(canvas);
  const ctx = canvas.getContext("2d");
  let motes = [];
  let w = 0, h = 0, last = 0, raf = 0;

  const seed = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    w = window.innerWidth; h = window.innerHeight;
    canvas.width = w * dpr; canvas.height = h * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const count = Math.round(Math.min(120, (w * h) / 16000));
    motes = Array.from({ length: count }, () => ({
      x: Math.random() * w,
      y: Math.random() * h,
      r: 0.5 + Math.random() * 1.2,
      a: 0.12 + Math.random() * 0.5,
      vy: 3 + Math.random() * 9,
      vx: (Math.random() - 0.5) * 2,
      tw: Math.random() * Math.PI * 2,
    }));
  };

  const draw = (t) => {
    ctx.clearRect(0, 0, w, h);
    for (const m of motes) {
      const glow = m.a * (0.65 + 0.35 * Math.sin(t / 1400 + m.tw));
      ctx.beginPath();
      ctx.arc(m.x, m.y, m.r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(186, 230, 253, ${glow.toFixed(3)})`;
      ctx.fill();
    }
  };

  const tick = (t) => {
    const dt = last ? Math.min((t - last) / 1000, 0.1) : 0;
    last = t;
    for (const m of motes) {
      m.y -= m.vy * dt;
      m.x += m.vx * dt;
      if (m.y < -4) { m.y = h + 4; m.x = Math.random() * w; }
    }
    draw(t);
    raf = requestAnimationFrame(tick);
  };

  const start = () => {
    cancelAnimationFrame(raf);
    last = 0;
    if (reduce.matches || document.hidden) { draw(0); return; }
    raf = requestAnimationFrame(tick);
  };

  seed(); start();
  let resizeTimer;
  window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { seed(); start(); }, 150); });
  document.addEventListener("visibilitychange", start);
  reduce.addEventListener("change", start);
}
