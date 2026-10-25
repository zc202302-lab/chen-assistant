(() => {
  const format = value => {
    if (!Number.isFinite(value)) return '';
    const rounded = Math.round(value * 100) / 100;
    return Number.isInteger(rounded) ? String(rounded) : String(rounded).replace(/0+$/, '').replace(/\.$/, '');
  };

  const detail = document.querySelector('[data-v10-recipe-detail]');
  if (detail) {
    const input = document.getElementById('v10TargetAmount');
    const cookAmount = document.getElementById('v10CookAmount');
    const base = Number(detail.dataset.baseAmount || 0);
    const refresh = () => {
      const target = Number(input?.value || base);
      detail.querySelectorAll('[data-recipe-print-link]').forEach(link => {
        const url = new URL(link.href, window.location.href);
        url.searchParams.set('amount', String(target > 0 && Number.isFinite(target) ? target : base));
        link.href = url.href;
      });
      if (cookAmount) cookAmount.value = target > 0 ? target : base;
      detail.querySelectorAll('.v10-ingredient[data-ingredient-amount]').forEach(row => {
        const raw = row.dataset.ingredientAmount;
        const amount = Number(raw);
        const out = row.querySelector('[data-scaled]');
        if (!out || raw === '' || !Number.isFinite(amount)) return;
        const mode = row.dataset.scaleMode;
        let value = amount;
        if (mode === 'proportional' && base > 0 && target > 0) value = amount * target / base;
        out.textContent = format(value);
      });
    };
    input?.addEventListener('input', refresh);
    refresh();
  }

  const editor = document.querySelector('[data-v10-recipe-editor]');
  if (editor) {
    const ingredientList = editor.querySelector('[data-ingredient-list]');
    const ingredientTpl = document.getElementById('v10IngredientTemplate');
    const stepList = editor.querySelector('[data-step-list]');
    const stepTpl = document.getElementById('v10StepTemplate');
    const renumberSteps = () => {
      stepList?.querySelectorAll('.v10-step-edit').forEach((row, idx) => {
        const label = row.querySelector('.v10-step-edit-head strong');
        if (label) label.textContent = `步骤 ${idx + 1}`;
      });
    };
    if (!editor.hasAttribute('data-grouped-recipe-editor')) editor.querySelector('[data-add-ingredient]')?.addEventListener('click', () => {
      if (ingredientTpl && ingredientList) ingredientList.appendChild(ingredientTpl.content.cloneNode(true));
    });
    editor.querySelector('[data-add-step]')?.addEventListener('click', () => {
      if (stepTpl && stepList) stepList.appendChild(stepTpl.content.cloneNode(true));
      renumberSteps();
    });
    editor.addEventListener('click', event => {
      const button = event.target.closest('[data-remove-row]');
      if (!button) return;
      button.closest('.v10-edit-row,.v10-step-edit')?.remove();
      renumberSteps();
    });
    renumberSteps();
  }

  // Version rendering is server-driven through request.app.version in base.html.
  // Do not overwrite it in JavaScript; this keeps UI, /health and deploy checks aligned.
  if (!document.querySelector('link[href*="/static/v12.css"]')) {
    const link = document.createElement('link');
    link.rel = 'stylesheet'; link.href = '/static/v12.css?v=1200';
    document.head.appendChild(link);
  }
  if (location.pathname.startsWith('/life')) {
    const nav = document.querySelector('.bottom-nav');
    if (nav) {
      nav.innerHTML = '<a href="/life" class="nav-item">⌂<span>生活</span></a><a href="/life/recipes" class="nav-item">▤<span>菜谱</span></a><a href="/life/tools" class="nav-item">⌗<span>工具</span></a>';
      nav.style.gridTemplateColumns = 'repeat(3,1fr)';
    }
  }
  if (!document.querySelector('script[src*="/static/v12.js"]')) {
    const script = document.createElement('script');
    script.src = '/static/v12.js?v=1200';
    document.body.appendChild(script);
  }
})();
