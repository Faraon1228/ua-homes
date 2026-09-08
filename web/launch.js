document.addEventListener("DOMContentLoaded", () => {
  if (["localhost", "127.0.0.1"].includes(window.location.hostname)) {
    document.querySelectorAll("[data-seller-link]").forEach((link) => {
      link.href = "/seller#add";
    });
  }

  document.querySelectorAll('a[href^="#"]').forEach((link) => {
    link.addEventListener("click", (event) => {
      const target = document.querySelector(link.getAttribute("href"));
      if (target) {
        event.preventDefault();
        target.scrollIntoView({ behavior: "smooth" });
      }
    });
  });
});
