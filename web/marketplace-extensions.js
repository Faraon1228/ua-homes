(function () {
  const styleId = 'ua-marketplace-extensions-style';
  if (!document.getElementById(styleId)) {
    const style = document.createElement('style');
    style.id = styleId;
    style.textContent = `
      .ua-marketplace-extensions {
        margin: 2rem auto 0;
        max-width: 1200px;
        padding: 0 1rem 3rem;
      }

      .ua-extension-grid {
        display: grid;
        gap: 1.25rem;
        grid-template-columns: 1.4fr 1fr;
      }

      .ua-card {
        background: linear-gradient(145deg, #ffffff 0%, #f8fbff 100%);
        border: 1px solid rgba(37, 99, 235, 0.12);
        border-radius: 24px;
        box-shadow: 0 16px 48px rgba(15, 23, 42, 0.08);
        padding: 1.35rem;
      }

      .ua-card h2 {
        font-size: 1.3rem;
        font-weight: 800;
        color: #0f172a;
        margin: 0 0 0.35rem;
      }

      .ua-card p {
        color: #475569;
        line-height: 1.6;
        margin: 0 0 1rem;
      }

      .ua-pill {
        display: inline-flex;
        align-items: center;
        gap: .35rem;
        padding: .4rem .75rem;
        border-radius: 999px;
        background: #eff6ff;
        color: #2563eb;
        font-size: .8rem;
        font-weight: 700;
        margin-bottom: .75rem;
      }

      .ua-mortgage-form {
        display: grid;
        gap: .8rem;
      }

      .ua-form-row {
        display: grid;
        gap: .6rem;
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .ua-form-field {
        display: flex;
        flex-direction: column;
        gap: .35rem;
      }

      .ua-form-field label {
        font-size: .8rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: .04em;
        color: #64748b;
      }

      .ua-form-field input,
      .ua-form-field select {
        border: 1px solid #dbeafe;
        border-radius: 14px;
        padding: .75rem .9rem;
        font-size: 1rem;
        background: #fff;
        color: #0f172a;
      }

      .ua-switch {
        display: flex;
        align-items: center;
        gap: .55rem;
        font-weight: 600;
        color: #334155;
      }

      .ua-submit-button,
      .ua-secondary-button {
        border: none;
        border-radius: 999px;
        padding: .8rem 1rem;
        font-weight: 700;
        cursor: pointer;
        transition: transform .2s ease, box-shadow .2s ease;
      }

      .ua-submit-button {
        background: linear-gradient(135deg, #2563eb, #1d4ed8);
        color: white;
        box-shadow: 0 10px 24px rgba(37, 99, 235, .2);
      }

      .ua-secondary-button {
        background: #f8fafc;
        color: #0f172a;
        border: 1px solid #e2e8f0;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        text-decoration: none;
      }

      .ua-submit-button:hover,
      .ua-secondary-button:hover {
        transform: translateY(-1px);
      }

      .ua-result-box {
        background: linear-gradient(135deg, rgba(37, 99, 235, 0.08), rgba(16, 185, 129, 0.08));
        border-radius: 18px;
        padding: 1rem;
        display: grid;
        gap: .4rem;
      }

      .ua-result-box strong {
        font-size: 1.2rem;
        color: #0f172a;
      }

      .ua-success {
        color: #0f766e;
        font-weight: 700;
        margin-top: .45rem;
      }

      .ua-developments {
        display: grid;
        gap: 1rem;
      }

      .ua-dev-card {
        border: 1px solid #e2e8f0;
        border-radius: 18px;
        padding: 1rem;
        background: white;
        display: flex;
        flex-direction: column;
        gap: .65rem;
      }

      .ua-dev-card .meta {
        display: flex;
        flex-wrap: wrap;
        gap: .45rem;
      }

      .ua-dev-card .meta span {
        font-size: .78rem;
        background: #f1f5f9;
        color: #334155;
        border-radius: 999px;
        padding: .3rem .55rem;
      }

      .ua-dev-card .title {
        font-size: 1.02rem;
        font-weight: 800;
        color: #0f172a;
      }

      .ua-dev-card .price {
        font-size: 1rem;
        font-weight: 700;
        color: #2563eb;
      }

      .ua-mini-stats {
        display: flex;
        gap: .7rem;
        flex-wrap: wrap;
      }

      .ua-mini-stats span {
        background: #eff6ff;
        color: #2563eb;
        border-radius: 999px;
        padding: .35rem .6rem;
        font-size: .78rem;
        font-weight: 700;
      }

      @media (max-width: 900px) {
        .ua-extension-grid {
          grid-template-columns: 1fr;
        }
      }
    `;
    document.head.appendChild(style);
  }

  function formatCurrency(value) {
    return new Intl.NumberFormat('uk-UA', {
      style: 'currency',
      currency: 'UAH',
      maximumFractionDigits: 0,
    }).format(value);
  }

  function calculateMortgage(amount, downPaymentPct, years, eOselya) {
    const principal = amount * (1 - downPaymentPct / 100);
    const annualRate = eOselya ? 0.12 : 0.17;
    const months = years * 12;
    const monthlyRate = annualRate / 12;
    if (monthlyRate <= 0 || months <= 0 || principal <= 0) return null;
    const payment = principal * (monthlyRate / (1 - Math.pow(1 + monthlyRate, -months)));
    return {
      payment,
      total: payment * months,
      interest: payment * months - principal,
    };
  }

  const API_BASE = (() => {
    const configured =
      window.UA_HOMES_API ||
      '__UA_HOMES_API__';
    if (configured && configured !== '__UA_HOMES_API__') return configured.replace(/\/$/, '');
    if (location.protocol === 'file:' || ['localhost', '127.0.0.1'].includes(location.hostname)) {
      return 'http://localhost:5050';
    }
    return location.origin;
  })();

  const PUBLIC_SITE = (() => {
    const configured =
      window.UA_HOMES_PUBLIC_URL ||
      '__UA_HOMES_PUBLIC_URL__';
    if (configured && configured !== '__UA_HOMES_PUBLIC_URL__') return configured.replace(/\/$/, '');
    if (location.protocol === 'file:' || ['localhost', '127.0.0.1'].includes(location.hostname)) {
      return 'http://localhost:5050';
    }
    return location.origin;
  })();

  const DEVELOPMENT_PROJECTS = [
    { slug: 'river-garden-residence', title: 'River Garden Residence' },
    { slug: 'skyline-park', title: 'Skyline Park' },
    { slug: 'city-green-quarter', title: 'City Green Quarter' },
  ];

  const developmentUrl = (slug) => `${PUBLIC_SITE}/zhk/${slug}`;

  function trackEvent(name, payload) {
    if (window.uaTrack) {
      window.uaTrack(name, payload || {});
    }
    if (window.dataLayer) {
      window.dataLayer.push({ event: name, ...payload });
    }
  }

  function createExtensions() {
    const container = document.createElement('section');
    container.className = 'ua-marketplace-extensions';
    container.innerHTML = `
      <div class="ua-extension-grid">
        <div class="ua-card">
          <div class="ua-pill">🏦 Іпотека v2</div>
          <h2>Порівняйте умови за 60 секунд</h2>
          <p>Підберіть ставку під єОселя, перегляньте щомісячний платіж та відправте заявку в один клік.</p>
          <form class="ua-mortgage-form" id="ua-mortgage-form">
            <div class="ua-form-row">
              <div class="ua-form-field">
                <label for="ua-bank">Банк</label>
                <select id="ua-bank" name="bank">
                  <option value="ПриватБанк">ПриватБанк</option>
                  <option value="Ощадбанк">Ощадбанк</option>
                  <option value="Укрексімбанк">Укрексімбанк</option>
                  <option value="ПУМБ">ПУМБ</option>
                </select>
              </div>
              <div class="ua-form-field">
                <label for="ua-amount">Сума кредиту</label>
                <input id="ua-amount" name="amount" type="number" value="1800000" min="100000" step="5000" />
              </div>
            </div>
            <div class="ua-form-row">
              <div class="ua-form-field">
                <label for="ua-down">Перший внесок</label>
                <select id="ua-down" name="down">
                  <option value="10">10%</option>
                  <option value="20" selected>20%</option>
                  <option value="30">30%</option>
                  <option value="40">40%</option>
                </select>
              </div>
              <div class="ua-form-field">
                <label for="ua-years">Термін</label>
                <select id="ua-years" name="years">
                  <option value="10">10 років</option>
                  <option value="15" selected>15 років</option>
                  <option value="20">20 років</option>
                  <option value="25">25 років</option>
                  <option value="30">30 років</option>
                </select>
              </div>
            </div>
            <label class="ua-switch">
              <input type="checkbox" id="ua-eoselya" />
              <span>Маю право на єОселя 3% / 7%</span>
            </label>
            <div class="ua-form-row">
              <div class="ua-form-field">
                <label for="ua-name">Ім'я</label>
                <input id="ua-name" name="name" type="text" placeholder="Олександр" />
              </div>
              <div class="ua-form-field">
                <label for="ua-phone">Телефон</label>
                <input id="ua-phone" name="phone" type="tel" placeholder="+380..." />
              </div>
            </div>
            <div class="ua-form-field">
              <label for="ua-email">Email</label>
              <input id="ua-email" name="email" type="email" placeholder="name@email.com" />
            </div>
            <button type="submit" class="ua-submit-button">Надіслати заявку</button>
          </form>
          <div class="ua-result-box" id="ua-mortgage-result">
            <div class="ua-mini-stats">
              <span>Ставка: 12% / 17%</span>
              <span>Рішення за день</span>
            </div>
            <div>Платіж: <strong id="ua-payment">—</strong></div>
            <div>Загалом: <strong id="ua-total">—</strong></div>
          </div>
          <div class="ua-success" id="ua-submit-success" aria-live="polite"></div>
        </div>
        <div class="ua-card">
          <div class="ua-pill">🏗️ Новобудови</div>
          <h2>ЖК з планами поверхів і прозорими умовами</h2>
          <p>Переходьте від перегляду до покупки через сторінки ЖК, де вже є поетапна розбивка по будівлях і поверхах.</p>
          <div class="ua-developments">
            <div class="ua-dev-card">
              <div class="title">River Garden Residence</div>
              <div class="meta">
                <span>Київ</span>
                <span>Під ключ</span>
                <span>Іпотека від 8.9%</span>
              </div>
              <div class="price">від 7 900 ₴/м²</div>
              <a class="ua-secondary-button" href="${developmentUrl('river-garden-residence')}" data-project="River Garden Residence">Дивитись план поверхів</a>
            </div>
            <div class="ua-dev-card">
              <div class="title">Skyline Park</div>
              <div class="meta">
                <span>Львів</span>
                <span>Комфорт+</span>
                <span>ЄОселя доступно</span>
              </div>
              <div class="price">від 6 450 ₴/м²</div>
              <a class="ua-secondary-button" href="${developmentUrl('skyline-park')}" data-project="Skyline Park">Отримати консультацію</a>
            </div>
            <div class="ua-dev-card">
              <div class="title">City Green Quarter</div>
              <div class="meta">
                <span>Одеса</span>
                <span>Тихий район</span>
                <span>Зручний під'їзд</span>
              </div>
              <div class="price">від 5 300 ₴/м²</div>
              <a class="ua-secondary-button" href="${developmentUrl('city-green-quarter')}" data-project="City Green Quarter">Запросити презентацію</a>
            </div>
          </div>
        </div>
      </div>
    `;

    const root = document.getElementById('root') || document.body;
    root.appendChild(container);

    const form = container.querySelector('#ua-mortgage-form');
    const paymentEl = container.querySelector('#ua-payment');
    const totalEl = container.querySelector('#ua-total');
    const successEl = container.querySelector('#ua-submit-success');
    const nameInput = form.elements.namedItem('name');
    const phoneInput = form.elements.namedItem('phone');
    const emailInput = form.elements.namedItem('email');
    const amountInput = form.elements.namedItem('amount');
    const downInput = form.elements.namedItem('down');
    const yearsInput = form.elements.namedItem('years');
    const eoselyaInput = form.querySelector('#ua-eoselya');

    const renderMortgage = () => {
      const amount = Number(amountInput.value || 0);
      const down = Number(downInput.value || 0);
      const years = Number(yearsInput.value || 15);
      const eOselya = eoselyaInput.checked;
      const result = calculateMortgage(amount, down, years, eOselya);
      if (!result) {
        paymentEl.textContent = '—';
        totalEl.textContent = '—';
        return;
      }
      paymentEl.textContent = formatCurrency(result.payment);
      totalEl.textContent = formatCurrency(result.total);
    };

    form.addEventListener('input', renderMortgage);
    form.addEventListener('change', renderMortgage);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const amount = Number(amountInput.value || 0);
      const bank = form.elements.namedItem('bank').value;
      const down = Number(downInput.value || 0);
      const years = Number(yearsInput.value || 15);
      const eOselya = eoselyaInput.checked;
      const name = nameInput.value.trim();
      const phone = phoneInput.value.trim();
      const email = emailInput.value.trim();
      if (!name || (!phone && !email)) {
        successEl.textContent = 'Вкажіть імʼя та телефон або email.';
        return;
      }
      successEl.textContent = 'Надсилаємо заявку...';
      try {
        const response = await fetch(`${API_BASE}/api/leads`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            lead_type: 'mortgage',
            source: 'mortgage-widget',
            name,
            phone,
            email,
            bank,
            amount,
            down_payment: down,
            years,
            eOselya,
            message: `Mortgage calculator submission from ${bank}`,
          }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(data.error || 'Не вдалося відправити заявку');
        }
        successEl.textContent = `Заявка відправлена для ${bank} — ми зв'яжемося найближчим часом.`;
        trackEvent('mortgage_submit', {
          bank,
          amount,
          down_payment: down,
          years,
          eoselya: eOselya,
        });
      } catch (error) {
        successEl.textContent = error.message || 'Помилка відправки';
      }
    });

    container.querySelectorAll('[data-project]').forEach((button) => {
      button.addEventListener('click', () => {
        const project = button.getAttribute('data-project');
        trackEvent('development_interest', { project_name: project });
        successEl.textContent = `Ми підготували матеріали по ЖК ${project}.`;
      });
    });

    renderMortgage();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', createExtensions, { once: true });
  } else {
    createExtensions();
  }
})();
