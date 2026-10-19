(function () {
  function init() {
    const gallery = document.getElementById("gallery");
    if (!gallery) return;
    const images = Array.from(gallery.querySelectorAll("img"));
    if (!images.length) return;

    let overlay = null;
    let index = 0;
    let opener = null;
    let touchX = null;

    const show = (next) => {
      index = (next + images.length) % images.length;
      overlay.querySelector("img").src = images[index].currentSrc || images[index].src;
      overlay.querySelector("img").alt = images[index].alt;
      const counter = overlay.querySelector("[data-counter]");
      if (counter) counter.textContent = images.length > 1 ? `${index + 1} / ${images.length}` : "";
    };

    const close = () => {
      if (!overlay) return;
      overlay.remove();
      overlay = null;
      document.body.style.overflow = "";
      document.removeEventListener("keydown", onKey, true);
      if (opener) opener.focus({ preventScroll: true });
    };

    function onKey(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        close();
      } else if (event.key === "ArrowRight" && images.length > 1) show(index + 1);
      else if (event.key === "ArrowLeft" && images.length > 1) show(index - 1);
    }

    const button = (label, text, css, handler) => {
      const el = document.createElement("button");
      el.type = "button";
      el.setAttribute("aria-label", label);
      el.textContent = text;
      el.style.cssText =
        "position:absolute;display:flex;align-items:center;justify-content:center;width:48px;height:48px;" +
        "border:0;border-radius:9999px;background:rgba(15,23,42,.75);color:#fff;font-size:28px;line-height:1;cursor:pointer;" +
        css;
      el.addEventListener("click", (event) => {
        event.stopPropagation();
        handler();
      });
      return el;
    };

    const open = (start) => {
      if (overlay) return;
      opener = document.activeElement;
      overlay = document.createElement("div");
      overlay.setAttribute("role", "dialog");
      overlay.setAttribute("aria-modal", "true");
      overlay.setAttribute("aria-label", "Фото на весь екран");
      overlay.style.cssText =
        "position:fixed;inset:0;z-index:100000;background:rgba(2,6,23,.96);display:flex;align-items:center;justify-content:center;touch-action:pan-y";
      const img = document.createElement("img");
      img.style.cssText = "max-width:100%;max-height:100%;object-fit:contain;user-select:none";
      overlay.appendChild(img);
      const closeButton = button(
        "Закрити",
        "×",
        "top:calc(12px + env(safe-area-inset-top,0px));right:calc(12px + env(safe-area-inset-right,0px));font-size:34px;",
        close
      );
      overlay.appendChild(closeButton);
      if (images.length > 1) {
        overlay.appendChild(button("Попереднє фото", "‹", "left:12px;top:50%;transform:translateY(-50%);", () => show(index - 1)));
        overlay.appendChild(button("Наступне фото", "›", "right:12px;top:50%;transform:translateY(-50%);", () => show(index + 1)));
      }
      const counter = document.createElement("span");
      counter.setAttribute("data-counter", "");
      counter.style.cssText =
        "position:absolute;left:50%;bottom:calc(16px + env(safe-area-inset-bottom,0px));transform:translateX(-50%);color:#fff;font:600 14px system-ui,sans-serif";
      overlay.appendChild(counter);
      overlay.addEventListener("click", (event) => {
        if (event.target === overlay) close();
      });
      overlay.addEventListener("touchstart", (event) => {
        touchX = event.touches[0].clientX;
      }, { passive: true });
      overlay.addEventListener("touchend", (event) => {
        if (touchX === null || images.length < 2) return;
        const delta = event.changedTouches[0].clientX - touchX;
        touchX = null;
        if (Math.abs(delta) > 50) show(index + (delta < 0 ? 1 : -1));
      }, { passive: true });
      document.body.appendChild(overlay);
      document.body.style.overflow = "hidden";
      document.addEventListener("keydown", onKey, true);
      show(start);
      closeButton.focus({ preventScroll: true });
    };

    images.forEach((image, imageIndex) => {
      image.style.cursor = "zoom-in";
      image.addEventListener("click", () => open(imageIndex));
    });
    gallery.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      const width = gallery.clientWidth || 1;
      open(Math.min(images.length - 1, Math.round(gallery.scrollLeft / width)));
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
